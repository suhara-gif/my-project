// - DM/グループDM: ユーザートークンがあれば自分の会話をすべて読む。
//   無ければBot宛てのDMだけ
function listTargetConversations() {
  const byId = {};
  let canJoin = true; // Botに channels:join 権限が無ければ、1回目の失敗以降は試さない
  listAllConversations(CONF.types, CONF.slackBotToken).forEach(c => {
    if (canJoin && !c.is_member && c.is_channel && !c.is_private) {
      try {
        slackFetch('https://slack.com/api/conversations.join?channel=' + encodeURIComponent(c.id), CONF.slackBotToken);
        c.is_member = true;
        Logger.log(`joined public channel: ${c.name || c.id}`);
      } catch (e) {
        if (String(e).indexOf('missing_scope') >= 0) {
          canJoin = false;
          Logger.log('Botに channels:join 権限が無いため、公開チャンネルへの自動参加をスキップします');
        } else {
          Logger.log(`join failed: ${c.name || c.id} -> ${e}`);
        }
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
