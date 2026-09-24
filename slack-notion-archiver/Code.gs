// ==== 設定 ====
// スクリプトプロパティに以下を保存しておくこと
// - SLACK_BOT_TOKEN  (xoxb-...)  公開/プライベートチャンネル用
// - SLACK_USER_TOKEN (xoxp-...)  任意。設定すると自分のDM・グループDM・
//                                 Botが入っていないプライベートチャンネルも保存する
// - NOTION_TOKEN     (ntn_... もしくは secret_...)
// - NOTION_DATABASE_ID (fe1ad2... のDB ID)
// - LAST_TS は初回 0 推奨（未設定でもOK）
//   チャンネルごとの進捗は LAST_TS_<チャンネルID> に自動で保存される
const PROPS = PropertiesService.getScriptProperties();
const CONF = {
  slackBotToken: PROPS.getProperty('SLACK_BOT_TOKEN'),
  slackUserToken: PROPS.getProperty('SLACK_USER_TOKEN'),
  notionToken: PROPS.getProperty('NOTION_TOKEN'),
  notionDbId: PROPS.getProperty('NOTION_DATABASE_ID'),
  lastTsPropKey: 'LAST_TS',
  convLastTsPrefix: 'LAST_TS_',
  failPrefix: 'FAIL_',
  cursorPropKey: 'CONV_CURSOR',
  types: ['public_channel', 'private_channel', 'im', 'mpim'],
  pageSize: 1000,
  historyLookbackSec: 60 * 60 * 24,
  // この期間内に立ったスレッドへの新しい返信を拾う（古いスレッドへの返信は拾えない）
  threadLookbackSec: 60 * 60 * 24 * 7,
  // Slackとの時計ズレ対策。直近この秒数の投稿は次回に回す
  safetyMarginSec: 60,
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
  Logger.log(`convs=${convs.length}`);
  if (convs.length === 0) return;

  // 時間切れで後ろの会話が毎回漏れないよう、前回の続きから回す
  let start = parseInt(PROPS.getProperty(CONF.cursorPropKey), 10) || 0;
  if (start >= convs.length) start = 0;

  let done = 0;
  let saved = 0;
  while (done < convs.length) {
    if (isOverBudget(startedAt)) {
      Logger.log(`time budget reached: ${done}/${convs.length} convs processed`);
      break;
    }
    const conv = convs[(start + done) % convs.length];
    saved += syncConversation(conv, userMap, defaultLastTs, startedAt);
    done++;
  }
  PROPS.setProperty(CONF.cursorPropKey, String((start + done) % convs.length));
  Logger.log(`done. saved=${saved}`);
}

// 1会話ぶんの同期。保存した件数を返す
function syncConversation(conv, userMap, defaultLastTs, startedAt) {
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
      saveMessage(c, token, message, isReply, userMap);
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

function saveMessage(c, token, m, isReply, userMap) {
  const sender = userMap[m.user]?.name || m.username || m.user || 'unknown';
  createNotionPage({
    title: (isReply ? '[返信] ' : '') + buildTitle(m, sender),
    text: buildPlainText(m),
    slackLink: getPermalink(c.id, m.ts, token),
    channelName: conversationLabel(c, userMap),
    sender: sender,
    postedAt: new Date(parseFloat(m.ts) * 1000).toISOString(),
    isDm: c.is_im === true || c.is_mpim === true
  });
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
// - DM/グループDM: ユーザートークンがあれば自分の会話をすべて読む。
//   無ければBot宛てのDMだけ
function listTargetConversations() {
  const byId = {};
  listAllConversations(CONF.types, CONF.slackBotToken).forEach(c => {
    if (!c.is_member && c.is_channel && !c.is_private) {
      try {
        slackFetch('https://slack.com/api/conversations.join?channel=' + encodeURIComponent(c.id), CONF.slackBotToken);
        c.is_member = true;
        Logger.log(`joined public channel: ${c.name || c.id}`);
      } catch (e) {
        Logger.log(`join failed: ${c.name || c.id} -> ${e}`);
      }
    }
    if (!c.is_member && !c.is_im && !c.is_mpim) return;
    byId[c.id] = { channel: c, token: CONF.slackBotToken };
  });

  if (CONF.slackUserToken) {
    listAllConversations(CONF.types, CONF.slackUserToken).forEach(c => {
      if (byId[c.id]) return;
      if (!c.is_member && !c.is_im && !c.is_mpim) return; // 自分が入っていないCHには参加しない
      byId[c.id] = { channel: c, token: CONF.slackUserToken };
    });
  }

  return Object.keys(byId).sort().map(id => byId[id]);
}

function listAllConversations(types, token) {
  const result = [];
  const typeParam = types.join(',');
  let cursor = null;
  do {
    const url = 'https://slack.com/api/conversations.list?limit=' + CONF.pageSize
      + '&types=' + encodeURIComponent(typeParam)
      + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url, token);
    (res.channels || []).forEach(ch => result.push(ch));
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return result;
}

// oldestTs < ts < latestTs のメッセージ（スレッド親を含むトップレベルのみ）
function fetchHistory(channelId, token, oldestTs, latestTs) {
  const out = [];
  let cursor = null;
  do {
    const url = 'https://slack.com/api/conversations.history?limit=200'
      + '&channel=' + encodeURIComponent(channelId)
      + '&oldest=' + encodeURIComponent(String(oldestTs))
      + '&latest=' + encodeURIComponent(String(latestTs))
      + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url, token);
    (res.messages || []).forEach(m => out.push(m));
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return out;
}

// スレッド内で oldestTs < ts < latestTs のメッセージ（親が範囲内なら親も含む）
function fetchReplies(channelId, token, threadTs, oldestTs, latestTs) {
  const out = [];
  let cursor = null;
  do {
    const url = 'https://slack.com/api/conversations.replies?limit=200'
      + '&channel=' + encodeURIComponent(channelId)
      + '&ts=' + encodeURIComponent(threadTs)
      + '&oldest=' + encodeURIComponent(String(oldestTs))
      + '&latest=' + encodeURIComponent(String(latestTs))
      + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url, token);
    (res.messages || []).forEach(m => out.push(m));
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return out;
}

// NotionのChannel欄に入れる名前。1対1のDMは「DM: 相手の名前」にする
function conversationLabel(c, userMap) {
  if (c.is_im) return 'DM: ' + (userMap[c.user]?.name || c.user || c.id);
  return c.name || c.id;
}

function buildUserMap() {
  const map = {};
  let cursor = null;
  do {
    const url = 'https://slack.com/api/users.list' + (cursor ? ('?cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url, CONF.slackBotToken);
    (res.members || []).forEach(u => {
      map[u.id] = { name: u.profile?.display_name || u.profile?.real_name || u.name || u.id };
    });
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return map;
}

function getPermalink(channelId, ts, token) {
  const url = 'https://slack.com/api/chat.getPermalink?channel=' + encodeURIComponent(channelId)
    + '&message_ts=' + encodeURIComponent(ts);
  try {
    const res = slackFetch(url, token);
    return res.permalink || '';
  } catch (e) {
    return '';
  }
}

// レート制限(429)は Retry-After だけ待って再試行する
function slackFetch(url, token) {
  const options = {
    method: 'get',
    headers: { 'Authorization': 'Bearer ' + token },
    muteHttpExceptions: true
  };
  for (let attempt = 0; ; attempt++) {
    const res = UrlFetchApp.fetch(url, options);
    if (res.getResponseCode() === 429 && attempt < 5) {
      const wait = parseInt(res.getHeaders()['Retry-After'], 10) || 1;
      Utilities.sleep(wait * 1000);
      continue;
    }
    const json = JSON.parse(res.getContentText());
    if (res.getResponseCode() >= 300 || json.ok === false) {
      throw new Error(`Slack API error: HTTP ${res.getResponseCode()} ${res.getContentText()}`);
    }
    return json;
  }
}

// ------------- Notionヘルパー（2,000文字分割対応）-------------

function buildPlainText(m) {
  return (m.text || '').trim();
}

// タイトルは短く（最大200文字に抑制）
function buildTitle(m, sender) {
  const text = buildPlainText(m);
  const head = text ? text.slice(0, 50).replace(/\s+/g, ' ') : '';
  const title = `${sender}: ${head || '(no text)'}`;
  return title.slice(0, 200);
}

// 2,000文字制限に対応して段落ブロックを分割生成
function makeParagraphChildren(text) {
  if (!text) return [];
  const MAX = 1900; // 余裕を持って分割
  const blocks = [];
  for (let i = 0; i < text.length; i += MAX) {
    const chunk = text.slice(i, i + MAX);
    blocks.push({
      object: 'block',
      paragraph: { rich_text: [{ type: 'text', text: { content: chunk } }] }
    });
  }
  return blocks;
}

function createNotionPage({ title, text, slackLink, channelName, sender, postedAt, isDm }) {
  const children = makeParagraphChildren(text);
  const payload = {
    parent: { database_id: CONF.notionDbId },
    properties: {
      'Title': { title: [{ text: { content: title } }] },
      'Slack Link': { url: slackLink || null },
      'Channel': { rich_text: [{ text: { content: channelName } }] },
      'Sender': { rich_text: [{ text: { content: sender } }] },
      'Posted At': { date: { start: postedAt } },
      'DM?': { checkbox: !!isDm }
    },
    children
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: { 'Authorization': 'Bearer ' + CONF.notionToken, 'Notion-Version': '2022-06-28' },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  const res = UrlFetchApp.fetch('https://api.notion.com/v1/pages', options);
  if (res.getResponseCode() >= 300) {
    throw new Error('Notion create page failed: ' + res.getResponseCode() + ' ' + res.getContentText());
  }
}

// ------------- 補助ユーティリティ -------------

// 最小のNotion接続テスト（必要なら）
function testNotionCreate_min() {
  const payload = {
    parent: { database_id: CONF.notionDbId },
    properties: { Title: { title: [{ text: { content: '接続テスト(最小)' } }] } }
  };
  const res = UrlFetchApp.fetch('https://api.notion.com/v1/pages', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + CONF.notionToken, 'Notion-Version': '2022-06-28' },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  Logger.log('HTTP ' + res.getResponseCode());
  Logger.log(res.getContentText());
}

// ユーザートークンで読める会話の数を確認する（保存はしない）
function testUserTokenAccess() {
  if (!CONF.slackUserToken) {
    Logger.log('SLACK_USER_TOKEN が未設定です');
    return;
  }
  const auth = slackFetch('https://slack.com/api/auth.test', CONF.slackUserToken);
  Logger.log(`user=${auth.user} team=${auth.team}`);
  const convs = listAllConversations(['im', 'mpim', 'private_channel'], CONF.slackUserToken);
  Logger.log(`im=${convs.filter(c => c.is_im).length} mpim=${convs.filter(c => c.is_mpim).length} private=${convs.filter(c => c.is_private && !c.is_mpim).length}`);
}

// 15分トリガーの作成（必要なら）
function create15minTrigger() {
  ScriptApp.newTrigger('syncSlackToNotion').timeBased().everyMinutes(15).create();
}

// 既存トリガーの全削除（必要なら）
function deleteAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
}
