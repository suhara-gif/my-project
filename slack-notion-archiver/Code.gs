// ==== 設定 ====
// スクリプトプロパティに以下を保存しておくこと
// - SLACK_BOT_TOKEN  (xoxb-...)
// - NOTION_TOKEN     (ntn_... もしくは secret_...)
// - NOTION_DATABASE_ID (fe1ad2... のDB ID)
// - LAST_TS は初回 0 推奨（未設定でもOK）
const CONF = {
  slackToken: PropertiesService.getScriptProperties().getProperty('SLACK_BOT_TOKEN'),
  notionToken: PropertiesService.getScriptProperties().getProperty('NOTION_TOKEN'),
  notionDbId: PropertiesService.getScriptProperties().getProperty('NOTION_DATABASE_ID'),
  lastTsPropKey: 'LAST_TS',
  types: ['public_channel', 'private_channel', 'im', 'mpim'],
  pageSize: 1000,
  historyLookbackSec: 60 * 60 * 24
};

// ------------- エントリポイント（増分同期）-------------
function syncSlackToNotion() {
  const nowSec = Math.floor(Date.now() / 1000);
  const props = PropertiesService.getScriptProperties();
  const lastTs = parseFloat(props.getProperty(CONF.lastTsPropKey)) || (nowSec - CONF.historyLookbackSec);
  Logger.log(`start sync: lastTs=${lastTs} (${new Date(lastTs * 1000).toISOString()})`);

  const convs = listAllConversations(CONF.types);
  Logger.log(`convs=${convs.length} types=${CONF.types.join(',')}`);

  let maxSeenTs = lastTs;
  const messages = [];

  convs.forEach(c => {
    const msgs = fetchConversationHistorySince(c, lastTs);
    Logger.log(`${c.name || c.id}: fetched ${msgs.length} msgs, is_member=${c.is_member}, private=${!!c.is_private}, im=${!!c.is_im}`);
    msgs.forEach(m => {
      if (!m.subtype) {
        messages.push({ channel: c, message: m });
        const tsNum = parseFloat(m.ts);
        if (tsNum > maxSeenTs) maxSeenTs = tsNum;
      }
    });
  });

  if (messages.length === 0) {
    Logger.log('no new messages.');
    props.setProperty(CONF.lastTsPropKey, String(maxSeenTs));
    return;
  }

  const userMap = buildUserMap();

  messages.sort((a, b) => parseFloat(a.message.ts) - parseFloat(b.message.ts));
  messages.forEach(item => {
    const { channel, message } = item;
    const sender = userMap[message.user]?.name || message.username || message.user || 'unknown';
    const permalink = getPermalink(channel.id, message.ts);
    const postedAt = new Date(parseFloat(message.ts) * 1000).toISOString();

    try {
      createNotionPage({
        title: buildTitle(message, sender),
        text: buildPlainText(message),
        slackLink: permalink,
        channelName: channel.name || channel.id,
        sender: sender,
        postedAt: postedAt,
        isDm: channel.is_im === true
      });
      Utilities.sleep(120);
    } catch (e) {
      Logger.log(`create failed (${channel.name || channel.id} ${message.ts}): ${e}`);
    }
  });

  props.setProperty(CONF.lastTsPropKey, String(maxSeenTs));
  Logger.log(`done. saved=${messages.length}, new lastTs=${maxSeenTs}`);
}

// ------------- 全量バックフィル（初回・任意実行）-------------
function backfillAllHistory() {
  const props = PropertiesService.getScriptProperties();
  const userMap = buildUserMap();
  const convs = listAllConversations(CONF.types);
  Logger.log(`BACKFILL start: convs=${convs.length}`);

  const targets = convs; // 必要に応じてフィルタ

  let saved = 0;
  for (const c of targets) {
    // 公開CHで未参加なら join（プライベート/IMは不可）
    if (!c.is_member && c.is_channel && !c.is_private) {
      try { slackFetch('https://slack.com/api/conversations.join?channel=' + encodeURIComponent(c.id)); c.is_member = true; }
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
        res = slackFetch(url);
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
        const permalink = getPermalink(c.id, m.ts) || `${c.id}:${m.ts}`;
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

function listAllConversations(types) {
  const result = [];
  const typeParam = types.join(',');
  let cursor = null;
  do {
    const url = 'https://slack.com/api/conversations.list?limit=' + CONF.pageSize
      + '&types=' + encodeURIComponent(typeParam)
      + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url);
    (res.channels || []).forEach(ch => result.push(ch));
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return result;
}

function fetchConversationHistorySince(channel, oldestTs) {
  if (!channel.is_member && channel.is_channel && !channel.is_private) {
    try {
      slackFetch('https://slack.com/api/conversations.join?channel=' + encodeURIComponent(channel.id));
      channel.is_member = true;
      Logger.log(`joined public channel: ${channel.name || channel.id}`);
    } catch (e) {
      Logger.log(`join failed: ${channel.name || channel.id} -> ${e}`);
    }
  }
  if (!channel.is_member && (channel.is_channel || channel.is_group)) {
    return [];
  }

  const out = [];
  let cursor = null;
  do {
    const url = 'https://slack.com/api/conversations.history?limit=200'
      + '&channel=' + encodeURIComponent(channel.id)
      + '&oldest=' + encodeURIComponent(String(oldestTs))
      + (cursor ? ('&cursor=' + encodeURIComponent(cursor)) : '');
    try {
      const res = slackFetch(url);
      (res.messages || []).forEach(m => out.push(m));
      cursor = res.response_metadata?.next_cursor || null;
    } catch (e) {
      Logger.log(`history error ${channel.name || channel.id}: ${e}`);
      return [];
    }
  } while (cursor);
  return out;
}

function buildUserMap() {
  const map = {};
  let cursor = null;
  do {
    const url = 'https://slack.com/api/users.list' + (cursor ? ('?cursor=' + encodeURIComponent(cursor)) : '');
    const res = slackFetch(url);
    (res.members || []).forEach(u => {
      map[u.id] = { name: u.profile?.display_name || u.profile?.real_name || u.name || u.id };
    });
    cursor = res.response_metadata?.next_cursor || null;
  } while (cursor);
  return map;
}

function getPermalink(channelId, ts) {
  const url = 'https://slack.com/api/chat.getPermalink?channel=' + encodeURIComponent(channelId)
    + '&message_ts=' + encodeURIComponent(ts);
  const res = slackFetch(url);
  return res.ok ? (res.permalink || '') : '';
}

function slackFetch(url) {
  const options = {
    method: 'get',
    headers: { 'Authorization': 'Bearer ' + CONF.slackToken },
    muteHttpExceptions: true
  };
  const res = UrlFetchApp.fetch(url, options);
  const json = JSON.parse(res.getContentText());
  if (res.getResponseCode() >= 300 || json.ok === false) {
    throw new Error(`Slack API error: HTTP ${res.getResponseCode()} ${res.getContentText()}`);
  }
  return json;
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

// 15分トリガーの作成（必要なら）
function create15minTrigger() {
  ScriptApp.newTrigger('syncSlackToNotion').timeBased().everyMinutes(15).create();
}

// 既存トリガーの全削除（必要なら）
function deleteAllTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
}
