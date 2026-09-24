// ==== 設定 ====
// スクリプトプロパティに以下を保存しておくこと
// - SLACK_BOT_TOKEN  (xoxb-...)  公開/プライベートチャンネル用
// - SLACK_USER_TOKEN (xoxp-...)  任意。設定すると自分のDM・グループDM・
//                                 Botが入っていないプライベートチャンネルも保存する
// - NOTION_TOKEN     (ntn_... もしくは secret_...)
// - NOTION_DATABASE_ID (fe1ad2... のDB ID)
// - LAST_TS は初回 0 推奨（未設定でもOK）
//   チャンネルごとの進捗は LAST_TS_<チャンネルID>、最終発言時刻は ACT_<チャンネルID> に自動で保存される
const PROPS = PropertiesService.getScriptProperties();
const CONF = {
  slackBotToken: PROPS.getProperty('SLACK_BOT_TOKEN'),
  slackUserToken: PROPS.getProperty('SLACK_USER_TOKEN'),
  notionToken: PROPS.getProperty('NOTION_TOKEN'),
  notionDbId: PROPS.getProperty('NOTION_DATABASE_ID'),
  lastTsPropKey: 'LAST_TS',
  convLastTsPrefix: 'LAST_TS_',
  failPrefix: 'FAIL_',
  activityPrefix: 'ACT_',
  types: ['public_channel', 'private_channel', 'im', 'mpim'],
  pageSize: 1000,
  historyLookbackSec: 60 * 60 * 24,
  // この期間内に立ったスレッドへの新しい返信を拾う（古いスレッドへの返信は拾えない）
  threadLookbackSec: 60 * 60 * 24 * 7,
  // Slackとの時計ズレ対策。直近この秒数の投稿は次回に回す
  safetyMarginSec: 60,
  // この期間やり取りの無い会話は「休眠」とみなし、毎回ではなく間隔を空けて見に行く
  dormantAfterSec: 60 * 60 * 24 * 14,
  dormantCheckIntervalSec: 60 * 60 * 12,
  // GASの実行上限(6分)より手前で打ち切り、残りは次回に続きから処理する
  timeBudgetMs: 4.5 * 60 * 1000,
  // 同じメッセージの保存がこの回数失敗したら諦めて先へ進む
  maxFailures: 3
};

// ------------- エントリポイント（増分同期）-------------
function syncSlackToNotion() {
  const startedAt = Date.now();
  const nowSec = Math.floor(startedAt / 1000);

  // 従来の LAST_TS は「チャンネル別の進捗がまだ無い会話」の開始位置として使う
  let defaultLastTs = PROPS.getProperty(CONF.lastTsPropKey);
  if (!parseFloat(defaultLastTs)) {
    defaultLastTs = String(nowSec - CONF.historyLookbackSec);
    PROPS.setProperty(CONF.lastTsPropKey, defaultLastTs);
  }
  Logger.log(`start sync: default lastTs=${defaultLastTs}, userToken=${!!CONF.slackUserToken}`);

  const convs = listTargetConversations();
  const userMap = buildUserMap();
  const baseUrl = getWorkspaceUrl();
  const queue = buildQueue(convs, defaultLastTs, nowSec);
  Logger.log(`convs=${convs.length} due=${queue.length} (active=${queue.filter(q => q.active).length})`);

  let done = 0;
  let saved = 0;
  for (const conv of queue) {
    if (isOverBudget(startedAt)) {
      Logger.log(`time budget reached: ${done}/${queue.length} due convs processed`);
      break;
    }
    saved += syncConversation(conv, userMap, defaultLastTs, startedAt, baseUrl);
    done++;
  }
  Logger.log(`done. saved=${saved}`);
}

// 今回見に行く会話の順番を決める
// - 一度も見ていない会話・最近やり取りのある会話: 毎回
// - 休眠中の会話: dormantCheckIntervalSec ごと
// 最近やり取りのある会話を先に、その中では前回見てから時間が経っているものを先に処理する
function buildQueue(convs, defaultLastTs, nowSec) {
  const all = PROPS.getProperties();
  const queue = [];
  convs.forEach(conv => {
    const id = conv.channel.id;
    const lastTs = parseFloat(all[CONF.convLastTsPrefix + id] || defaultLastTs);
    const actStr = all[CONF.activityPrefix + id];
    const scanned = actStr !== undefined;
    const active = scanned && nowSec - parseFloat(actStr) < CONF.dormantAfterSec;
    if (scanned && !active && nowSec - lastTs < CONF.dormantCheckIntervalSec) return;
    queue.push(Object.assign({ lastTs: lastTs, active: active || !scanned }, conv));
  });
  queue.sort((a, b) => (b.active - a.active) || (a.lastTs - b.lastTs));
  return queue;
}

// 1会話ぶんの同期。保存した件数を返す
function syncConversation(conv, userMap, defaultLastTs, startedAt, baseUrl) {
  const c = conv.channel;
  const token = conv.token;
  const label = conversationLabel(c, userMap);
  const tsKey = CONF.convLastTsPrefix + c.id;
  const lastTsStr = PROPS.getProperty(tsKey) || defaultLastTs;
  const lastTs = parseFloat(lastTsStr);
  const upperTs = Math.floor(Date.now() / 1000) - CONF.safetyMarginSec;
  if (upperTs <= lastTs) return 0;

  // スレッド親を探すため、前回位置より前（threadLookbackSec）まで遡って読む
  const windowOldest = Math.min(lastTs, upperTs - CONF.threadLookbackSec);
  const items = [];
  try {
    const history = fetchHistory(c.id, token, windowOldest, upperTs);
    recordActivity(c.id, history);
    history.forEach(m => {
      if (parseFloat(m.ts) > lastTs && !m.subtype) {
        items.push({ message: m, isReply: false });
      }
      if (m.reply_count > 0 && parseFloat(m.latest_reply || 0) > lastTs) {
        fetchReplies(c.id, token, m.ts, lastTs, upperTs).forEach(r => {
          // 親メッセージ自身も返ってくるので除外。「チャンネルにも送信」された返信はここで拾う
          if (r.ts === r.thread_ts) return;
          if (r.subtype && r.subtype !== 'thread_broadcast') return;
          items.push({ message: r, isReply: true });
        });
      }
    });
  } catch (e) {
    Logger.log(`fetch failed (${label}): ${e}`);
    return 0;
  }

  items.sort((a, b) => parseFloat(a.message.ts) - parseFloat(b.message.ts));
  Logger.log(`${label}: new=${items.length} (replies=${items.filter(i => i.isReply).length})`);

  // 時系列順に保存し、途中で止まったら「最後に保存できた位置」までしか進めない
  let savedUpTo = lastTsStr;
  let saved = 0;
  for (const { message, isReply } of items) {
    if (isOverBudget(startedAt)) {
      PROPS.setProperty(tsKey, savedUpTo);
      return saved;
    }
    try {
      saveMessage(c, token, message, isReply, userMap, baseUrl);
      clearFailure(c.id);
      saved++;
      savedUpTo = message.ts;
      Utilities.sleep(120);
    } catch (e) {
      Logger.log(`create failed (${label} ${message.ts}): ${e}`);
      if (recordFailure(c.id, message.ts) < CONF.maxFailures) {
        PROPS.setProperty(tsKey, savedUpTo);
        return saved;
      }
      Logger.log(`give up (${label} ${message.ts}) after ${CONF.maxFailures} failures`);
      clearFailure(c.id);
      savedUpTo = message.ts;
    }
  }
  PROPS.setProperty(tsKey, String(upperTs));
  return saved;
}

function saveMessage(c, token, m, isReply, userMap, baseUrl) {
  const sender = userMap[m.user]?.name || m.username || m.user || 'unknown';
  createNotionPage({
    title: (isReply ? '[返信] ' : '') + buildTitle(m, sender),
    text: buildPlainText(m),
    slackLink: buildPermalink(baseUrl, c.id, m) || getPermalink(c.id, m.ts, token),
    channelName: conversationLabel(c, userMap),
    sender: sender,
    postedAt: new Date(parseFloat(m.ts) * 1000).toISOString(),
    isDm: c.is_im === true || c.is_mpim === true
  });
}

// 会話の最終発言時刻(返信を含む)を記録する。一度見た会話には必ずキーを作る
function recordActivity(channelId, history) {
  const key = CONF.activityPrefix + channelId;
  let latest = parseFloat(PROPS.getProperty(key)) || 0;
  history.forEach(m => {
    latest = Math.max(latest, parseFloat(m.ts) || 0, parseFloat(m.latest_reply) || 0);
  });
  PROPS.setProperty(key, String(latest));
}

// ワークスペースのURL(https://xxx.slack.com/)。取れなければ空文字
function getWorkspaceUrl() {
  try {
    const url = slackFetch('https://slack.com/api/auth.test', CONF.slackBotToken).url || '';
    return url && !url.endsWith('/') ? url + '/' : url;
  } catch (e) {
    Logger.log(`auth.test failed: ${e}`);
    return '';
  }
}

// メッセージへのリンクを自前で組み立てる(1件ごとの chat.getPermalink 呼び出しを省く)
function buildPermalink(baseUrl, channelId, m) {
  if (!baseUrl) return '';
  let url = baseUrl + 'archives/' + channelId + '/p' + m.ts.replace('.', '');
  if (m.thread_ts && m.thread_ts !== m.ts) {
    url += '?thread_ts=' + m.thread_ts + '&cid=' + channelId;
  }
  return url;
}

function isOverBudget(startedAt) {
  return Date.now() - startedAt > CONF.timeBudgetMs;
}

// 同じメッセージで何回失敗したかを数える（直近1件のみ保持）
function recordFailure(channelId, ts) {
  const key = CONF.failPrefix + channelId;
  const prev = (PROPS.getProperty(key) || '').split(':');
  const count = prev[0] === ts ? (parseInt(prev[1], 10) || 0) + 1 : 1;
  PROPS.setProperty(key, `${ts}:${count}`);
  return count;
}

function clearFailure(channelId) {
  PROPS.deleteProperty(CONF.failPrefix + channelId);
}

// ------------- 全量バックフィル（初回・任意実行）-------------
// 注意: Notion側の重複チェックはしないので、保存済みの期間に対して再実行すると重複する
function backfillAllHistory() {
  const userMap = buildUserMap();
  const convs = listAllConversations(CONF.types, CONF.slackBotToken);
  Logger.log(`BACKFILL start: convs=${convs.length}`);

  const targets = convs; // 必要に応じてフィルタ

  let saved = 0;
  for (const c of targets) {
    // 公開CHで未参加なら join（プライベート/IMは不可）
    if (!c.is_member && c.is_channel && !c.is_private) {
      try { slackFetch('https://slack.com/api/conversations.join?channel=' + encodeURIComponent(c.id), CONF.slackBotToken); c.is_member = true; }
      catch (e) { Logger.log(`join failed: ${c.name || c.id} -> ${e}`); }
    }
    if (!c.is_member && (c.is_channel || c.is_group)) {
      Logger.log(`skip (not member): ${c.name || c.id}`);
      continue;
    }

    Logger.log(`channel=${c.name || c.id} backfill...`);
    let cursor = null;
    let page = 0;
    const seen = new Set(); // 実行中の重複防止

    do {
      const url = 'https://slack.com/api/conversations.history?limit=200'
        + '&channel=' + encodeURIComponent(c.id)
        + '&oldest=0'
        + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
      let res;
      try {
        res = slackFetch(url, CONF.slackBotToken);
      } catch (e) {
        Logger.log(`history error ${c.name || c.id}: ${e}`);
        break;
      }

      const msgs = res.messages || [];
      Logger.log(`  page=${++page}, msgs=${msgs.length}`);

      for (const m of msgs) {
        if (m.subtype) continue; // 必要なら外す
        const sender = userMap[m.user]?.name || m.username || m.user || 'unknown';
        const ts = parseFloat(m.ts);
        const postedAt = new Date(ts * 1000).toISOString();
        const permalink = getPermalink(c.id, m.ts, CONF.slackBotToken) || `${c.id}:${m.ts}`;
        if (seen.has(permalink)) continue;
        seen.add(permalink);

        try {
          createNotionPage({
            title: buildTitle(m, sender),
            text: buildPlainText(m),
            slackLink: permalink,
            channelName: c.name || c.id,
            sender: sender,
            postedAt: postedAt,
            isDm: c.is_im === true
          });
          saved++;
        } catch (e) {
          Logger.log(`create failed (${c.name || c.id} ${m.ts}): ${e}`);
        }

        Utilities.sleep(150);
      }

      cursor = res.response_metadata?.next_cursor || null;
      Utilities.sleep(300);
    } while (cursor);
  }

  // 終了時にLAST_TSを現在に進めたい場合はコメントアウト解除
  // PropertiesService.getScriptProperties().setProperty(CONF.lastTsPropKey, String(Math.floor(Date.now()/1000)));

  Logger.log(`BACKFILL done. saved=${saved}`);
}

// ------------- Slackヘルパー -------------

// 同期対象の会話と、それを読むのに使うトークンの組を返す（ID順）
// - チャンネル: 従来どおりBotで読む（公開CHは自動join）。Botが読めない
//   プライベートCHは、ユーザートークンがあればそちらで読む
