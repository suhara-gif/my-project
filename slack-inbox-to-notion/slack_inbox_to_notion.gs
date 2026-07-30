/**
 * Slack の 📥(:inbox_tray:) リアクション → Notion タスクDB へ INBOX 登録
 *
 * 方式: Slack Events API(reaction_added) → Google Apps Script Web App → Notion API
 * Workflow Builder / Zapier / Make は使わない。カスタムエージェントも使わない。
 *
 * 秘密情報(トークン類)はこのファイルに書かない。すべて「スクリプト プロパティ」から読む。
 * 設定できるキーの一覧は同ディレクトリの .env.example / README.md を参照。
 *
 * 設計上の重要な前提(README「制約と、その回避策」も参照):
 *  - GAS の doPost は HTTP ヘッダを読めない。よって Slack 署名(X-Slack-Signature)の検証は
 *    原理的に不可能。代替として Request URL に共有シークレット(?key=...)を付ける。
 *  - Slack は 3 秒以内に 200 が返らないとイベントを再送する。GAS + 外部 API 4 本では
 *    3 秒を超えうるため、「再送されても二重登録しない」ことで安全側に倒す。
 *    (スクリプトロック + event_id キャッシュ + Notion 側「Slackリンク」完全一致の三重)
 */

// ===== 既定値(スクリプト プロパティで上書き可能) =====
var DEFAULTS = {
  TARGET_REACTION: 'inbox_tray',
  NOTION_VERSION: '2022-06-28',
  NOTION_STATUS_VALUE: 'INBOX',
  NOTION_ASSIGNEE_NAME: '須原弘之',
  PROP_TITLE: '名前',
  PROP_STATUS: 'ステータス',
  PROP_ASSIGNEE: '担当者',
  PROP_TEXT: 'テキスト',
  PROP_SLACK_URL: 'Slackリンク',
  TITLE_BODY_LENGTH: '40',
  TARGET_CHANNEL_NAME: '',
  REQUEST_SECRET: ''
};

// 必須のスクリプト プロパティ(未設定なら testConfig() が落とす)
var REQUIRED_KEYS = [
  'SLACK_BOT_TOKEN',
  'NOTION_API_TOKEN',
  'NOTION_TASK_DATABASE_ID',
  'NOTION_ASSIGNEE_USER_ID',
  'ALLOWED_SLACK_USER_ID',
  'TARGET_REACTION',
  'TARGET_CHANNEL_ID'
];

var NOTION_TEXT_CHUNK = 2000; // Notion の rich_text 1要素あたりの文字数上限
var EVENT_CACHE_SEC = 3600;   // event_id の重複排除を保つ秒数(Slack の再送は最長5分程度)
var SCHEMA_CACHE_SEC = 21600; // Notion DB スキーマのキャッシュ(6時間 = CacheService の上限)
var LOCK_WAIT_MS = 20000;

// =====================================================================
// エントリポイント(Slack Events API の Request URL がここを叩く)
// =====================================================================

/**
 * @param {Object} e Apps Script の doPost イベント。e.postData.contents に Slack の JSON。
 * @return {TextOutput}
 */
function doPost(e) {
  var payload;
  try {
    payload = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    console.error('[error] リクエストボディを JSON として読めません: ' + err);
    return textOut_('bad request');
  }

  // ① 共有シークレット照合。GAS はヘッダを読めず署名検証ができないため、これが唯一の入口制限。
  //    REQUEST_SECRET 未設定(既定)なら素通し = 後方互換。
  var secret = prop_('REQUEST_SECRET', DEFAULTS.REQUEST_SECRET);
  if (secret !== '') {
    var given = (e && e.parameter && e.parameter.key) || '';
    if (given !== secret) {
      console.error('[deny] REQUEST_SECRET が一致しません。Request URL の ?key= を確認してください。');
      return textOut_('forbidden');
    }
  }

  // ② URL verification(challenge)。ここは他の設定の検証より前に返す。
  //    そうしないと「スクリプト プロパティ未入力 → challenge も失敗」で切り分けが難しくなる。
  if (payload.type === 'url_verification') {
    console.log('[url_verification] challenge に応答しました');
    return textOut_(String(payload.challenge || ''));
  }

  if (payload.type !== 'event_callback') {
    console.log('[skip] 対象外の payload.type: ' + payload.type);
    return textOut_('ignored');
  }

  try {
    var result = handleEventCallback_(payload);
    console.log('[done] ' + result);
    return textOut_('ok');
  } catch (err) {
    // 想定外の失敗は 500 を返す。Slack が再送してくれるし、三重の重複排除があるので
    // 再送で二重登録にはならない。握り潰して 200 を返すとリアクションが黙って消える。
    console.error('[error] ' + (err && err.stack ? err.stack : err));
    throw err;
  }
}

/**
 * event_callback を処理する。スキップした場合もその理由を文字列で返す(例外にしない)。
 * @param {Object} payload
 * @return {string} 処理結果の説明
 */
function handleEventCallback_(payload) {
  var ev = payload.event || {};
  if (ev.type !== 'reaction_added') {
    return 'skip: event.type=' + ev.type + '(reaction_added ではない)';
  }

  var cfg = loadConfig_();

  // 絵文字名。肌色バリアント(:xxx::skin-tone-3:)が付く場合があるので落とす。
  var reaction = String(ev.reaction || '').replace(/::skin-tone-\d+$/, '');
  if (reaction !== cfg.targetReaction) {
    return 'skip: reaction=' + reaction + '(対象は ' + cfg.targetReaction + ')';
  }
  if (ev.user !== cfg.allowedUserId) {
    return 'skip: user=' + ev.user + '(許可は ' + cfg.allowedUserId + ' のみ)';
  }

  var item = ev.item || {};
  if (item.type !== 'message') {
    return 'skip: item.type=' + item.type + '(メッセージ以外のリアクション)';
  }
  if (item.channel !== cfg.targetChannelId) {
    return 'skip: channel=' + item.channel + '(対象は ' + cfg.targetChannelId + ')';
  }

  requireConfig_(cfg); // ここから先は全プロパティが要る

  var lock = LockService.getScriptLock();
  if (!lock.tryLock(LOCK_WAIT_MS)) {
    // 先行実行が処理中。Slack の再送なら先行分で登録済みになるので、ここは諦めてよい。
    throw new Error('スクリプトロックを取得できませんでした(先行実行が処理中)。Slack の再送を待ちます。');
  }
  try {
    return registerReaction_(cfg, {
      channel: item.channel,
      ts: item.ts,
      reaction: reaction,
      eventId: payload.event_id || ''
    });
  } finally {
    lock.releaseLock();
  }
}

// =====================================================================
// 本体: Slack から情報を集めて Notion に1件作る
// =====================================================================

/**
 * @param {Object} cfg loadConfig_() の戻り
 * @param {{channel:string, ts:string, reaction:string, eventId:string}} target
 * @param {boolean=} dryRun true なら Notion への書き込みを行わない
 * @return {string}
 */
function registerReaction_(cfg, target, dryRun) {
  var cache = CacheService.getScriptCache();
  var evKey = 'ev_' + target.eventId;

  // 重複排除 その1: 同じ event_id を既に処理済みか(Slack の 3 秒タイムアウト再送対策)
  if (target.eventId && cache.get(evKey)) {
    return 'skip: event_id=' + target.eventId + ' は処理済み(Slack の再送)';
  }

  var message = slackFetchMessage_(cfg.slackToken, target.channel, target.ts);
  var body = String(message.text || '');
  var authorId = message.user || message.bot_id || '';
  var authorName = slackResolveUserName_(cfg.slackToken, message.user) ||
    message.username || authorId || '(不明)';
  var permalink = slackGetPermalink_(cfg.slackToken, target.channel, target.ts);
  var channelLabel = cfg.targetChannelName ?
    cfg.targetChannelName + '(' + target.channel + ')' : target.channel;

  // 重複排除 その2: Notion 側「Slackリンク」の完全一致(これが最終的な正)
  var existing = notionFindByUrl_(cfg, permalink);
  if (existing) {
    if (target.eventId) cache.put(evKey, '1', EVENT_CACHE_SEC);
    return 'skip: 同じ Slackリンクが既に登録済み(page id=' + existing + ')';
  }

  var now = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss');
  var title = buildTitle_(authorName, body, cfg.titleBodyLength);
  var memo = [
    '【Slack本文】',
    body === '' ? '(本文なし)' : body,
    '',
    '【投稿者】' + authorName,
    '【チャンネル】' + channelLabel,
    '【Slackリンク】' + permalink,
    '【リアクション】:' + target.reaction + ':',
    '【登録日時】' + now + ' JST'
  ].join('\n');

  var schema = notionSchema_(cfg);
  var properties = buildProperties_(cfg, schema, {
    title: title,
    memo: memo,
    url: permalink
  });

  if (dryRun) {
    console.log('[dry-run] 作成せずに終了します。以下が Notion に送る予定の properties です。');
    console.log(JSON.stringify({ parent: { database_id: cfg.databaseId }, properties: properties }, null, 2));
    return 'dry-run: 登録はしていません(タイトル: ' + title + ')';
  }

  var page = notionCreatePage_(cfg, properties);
  if (target.eventId) cache.put(evKey, '1', EVENT_CACHE_SEC);
  return 'created: ' + title + ' / page id=' + page.id;
}

/**
 * 「Slack｜{投稿者}｜{本文先頭N字}」。改行・連続空白は 1 個の空白に潰す。
 * N 字を超えていた場合だけ末尾に … を付ける。
 */
function buildTitle_(authorName, body, n) {
  var flat = String(body).replace(/\s+/g, ' ').trim();
  var head = flat.length > n ? flat.slice(0, n) + '…' : flat;
  if (head === '') head = '(本文なし)';
  return 'Slack｜' + authorName + '｜' + head;
}

// =====================================================================
// Slack API
// =====================================================================

/**
 * リアクションが付いたメッセージ本体を取る。
 * conversations.history はスレッド返信を返さないため、空なら conversations.replies も見る。
 */
function slackFetchMessage_(token, channel, ts) {
  var hist = slackApi_(token, 'conversations.history', {
    channel: channel, latest: ts, oldest: ts, inclusive: 'true', limit: 1
  });
  var msgs = hist.messages || [];
  for (var i = 0; i < msgs.length; i++) {
    if (msgs[i].ts === ts) return msgs[i];
  }

  // スレッド返信の場合。ts にはスレッド内の任意のメッセージ ts を渡せる。
  var rep = slackApi_(token, 'conversations.replies', {
    channel: channel, ts: ts, limit: 1, inclusive: 'true', latest: ts, oldest: ts
  });
  var reps = rep.messages || [];
  for (var j = 0; j < reps.length; j++) {
    if (reps[j].ts === ts) return reps[j];
  }
  throw new Error('Slack メッセージを取得できません(channel=' + channel + ', ts=' + ts +
    ')。Bot が対象チャンネルに参加しているか、channels:history スコープがあるか確認してください。');
}

/** 表示名を取れなければ空文字を返す(名前が取れないだけで登録は止めない)。 */
function slackResolveUserName_(token, userId) {
  if (!userId) return '';
  try {
    var res = slackApi_(token, 'users.info', { user: userId });
    var p = (res.user && res.user.profile) || {};
    return p.display_name || p.real_name || (res.user && res.user.name) || '';
  } catch (err) {
    console.warn('[warn] users.info に失敗しました(投稿者IDで代用します): ' + err);
    return '';
  }
}

/** permalink は「Slackリンク」の重複判定キー。形式がぶれると判定が壊れるので必ず Slack に作らせる。 */
function slackGetPermalink_(token, channel, ts) {
  var res = slackApi_(token, 'chat.getPermalink', { channel: channel, message_ts: ts });
  if (!res.permalink) throw new Error('chat.getPermalink が permalink を返しませんでした。');
  return res.permalink;
}

function slackApi_(token, method, params) {
  var qs = [];
  for (var k in params) {
    if (Object.prototype.hasOwnProperty.call(params, k)) {
      qs.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
    }
  }
  var url = 'https://slack.com/api/' + method + (qs.length ? '?' + qs.join('&') : '');
  var res = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true
  });
  var code = res.getResponseCode();
  var text = res.getContentText();
  var json;
  try {
    json = JSON.parse(text);
  } catch (err) {
    throw new Error('Slack API ' + method + ' の応答が JSON ではありません(HTTP ' + code + '): ' +
      text.slice(0, 200));
  }
  if (code !== 200 || !json.ok) {
    throw new Error('Slack API ' + method + ' に失敗: ' + (json.error || ('HTTP ' + code)) +
      slackErrorHint_(json.error) + (json.needed ? ' / needed=' + json.needed : ''));
  }
  return json;
}

function slackErrorHint_(err) {
  var hints = {
    not_in_channel: '(→ 対象チャンネルで /invite @アプリ名 して Bot を招待してください)',
    channel_not_found: '(→ TARGET_CHANNEL_ID を確認、または Bot をチャンネルに招待してください)',
    missing_scope: '(→ Slack App の OAuth スコープを追加し、ワークスペースに再インストールしてください)',
    invalid_auth: '(→ SLACK_BOT_TOKEN が誤っています。xoxb- で始まる Bot User OAuth Token です)',
    not_authed: '(→ SLACK_BOT_TOKEN が未設定です)',
    ratelimited: '(→ Slack のレート制限。しばらく待つと復帰します)'
  };
  return hints[err] || '';
}

// =====================================================================
// Notion API
// =====================================================================

/**
 * DB のプロパティ名 → 型 の対応表。型に合わせて値の作り方を変えるために使う
 * (「ステータス」が status 型か select 型かは DB により違うため)。
 */
function notionSchema_(cfg) {
  var cache = CacheService.getScriptCache();
  var key = 'notion_schema_' + cfg.databaseId;
  var hit = cache.get(key);
  if (hit) {
    try { return JSON.parse(hit); } catch (err) { /* 壊れていたら取り直す */ }
  }
  var db = notionApi_(cfg, 'get', 'https://api.notion.com/v1/databases/' + cfg.databaseId);
  var map = {};
  var props = db.properties || {};
  for (var name in props) {
    if (Object.prototype.hasOwnProperty.call(props, name)) map[name] = props[name].type;
  }
  cache.put(key, JSON.stringify(map), SCHEMA_CACHE_SEC);
  return map;
}

function buildProperties_(cfg, schema, data) {
  var props = {};

  requireProp_(schema, cfg.propTitle, ['title']);
  props[cfg.propTitle] = { title: richText_(data.title) };

  // ステータス: status 型 / select 型 のどちらでも INBOX を入れられるようにする
  var stType = requireProp_(schema, cfg.propStatus, ['status', 'select', 'rich_text']);
  if (stType === 'status') {
    props[cfg.propStatus] = { status: { name: cfg.statusValue } };
  } else if (stType === 'select') {
    props[cfg.propStatus] = { select: { name: cfg.statusValue } };
  } else {
    props[cfg.propStatus] = { rich_text: richText_(cfg.statusValue) };
  }

  // 担当者: people 型が本命。select / rich_text の DB でも名前で入るようにしておく
  var asType = requireProp_(schema, cfg.propAssignee, ['people', 'select', 'rich_text']);
  if (asType === 'people') {
    props[cfg.propAssignee] = { people: [{ object: 'user', id: cfg.assigneeUserId }] };
  } else if (asType === 'select') {
    props[cfg.propAssignee] = { select: { name: cfg.assigneeName } };
  } else {
    props[cfg.propAssignee] = { rich_text: richText_(cfg.assigneeName) };
  }

  requireProp_(schema, cfg.propText, ['rich_text']);
  props[cfg.propText] = { rich_text: richText_(data.memo) };

  requireProp_(schema, cfg.propSlackUrl, ['url']);
  props[cfg.propSlackUrl] = { url: data.url };

  // 対応日・締切日・プロジェクトDB は指定どおり触らない(未指定 = Notion 側で空欄のまま)
  return props;
}

function requireProp_(schema, name, allowedTypes) {
  var type = schema[name];
  if (!type) {
    throw new Error('Notion DB に「' + name + '」プロパティがありません。' +
      'プロパティ名を直すか、対応するスクリプト プロパティ(PROP_*)で名前を上書きしてください。' +
      ' / DB にある名前: ' + Object.keys(schema).join(', '));
  }
  if (allowedTypes.indexOf(type) === -1) {
    throw new Error('Notion の「' + name + '」は ' + type + ' 型ですが、対応しているのは ' +
      allowedTypes.join(' / ') + ' です。');
  }
  return type;
}

/** Notion の rich_text は 1 要素 2000 文字まで。本文全文を落とさないよう分割する。 */
function richText_(s) {
  var str = (s === null || s === undefined) ? '' : String(s);
  if (str === '') return [{ text: { content: '' } }];
  var out = [];
  for (var i = 0; i < str.length && out.length < 100; i += NOTION_TEXT_CHUNK) {
    out.push({ text: { content: str.slice(i, i + NOTION_TEXT_CHUNK) } });
  }
  return out;
}

/** 「Slackリンク」完全一致で既存ページを探す。見つかればページ ID、無ければ null。 */
function notionFindByUrl_(cfg, url) {
  var res = notionApi_(cfg, 'post',
    'https://api.notion.com/v1/databases/' + cfg.databaseId + '/query', {
      filter: { property: cfg.propSlackUrl, url: { equals: url } },
      page_size: 1
    });
  var results = res.results || [];
  return results.length > 0 ? results[0].id : null;
}

function notionCreatePage_(cfg, properties) {
  return notionApi_(cfg, 'post', 'https://api.notion.com/v1/pages', {
    parent: { database_id: cfg.databaseId },
    properties: properties
  });
}

function notionApi_(cfg, method, url, body) {
  var options = {
    method: method,
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + cfg.notionToken,
      'Notion-Version': cfg.notionVersion
    },
    muteHttpExceptions: true
  };
  if (body) options.payload = JSON.stringify(body);

  var res = UrlFetchApp.fetch(url, options);
  var code = res.getResponseCode();
  var text = res.getContentText();
  var json;
  try {
    json = JSON.parse(text);
  } catch (err) {
    throw new Error('Notion API の応答が JSON ではありません(HTTP ' + code + '): ' + text.slice(0, 200));
  }
  if (code < 200 || code >= 300) {
    throw new Error('Notion API に失敗(HTTP ' + code + ' ' + (json.code || '') + '): ' +
      (json.message || text.slice(0, 300)) + notionErrorHint_(code, json.code));
  }
  return json;
}

function notionErrorHint_(code, notionCode) {
  if (code === 401) return '(→ NOTION_API_TOKEN が誤っています。ntn_/secret_ で始まるインテグレーションのトークンです)';
  if (code === 404) return '(→ NOTION_TASK_DATABASE_ID が誤っているか、DB にインテグレーションを「接続」していません)';
  if (notionCode === 'validation_error') return '(→ プロパティ名/型、または担当者の Notion ユーザーIDを確認してください)';
  return '';
}

// =====================================================================
// 設定
// =====================================================================

function prop_(key, fallback) {
  var v = PropertiesService.getScriptProperties().getProperty(key);
  if (v === null || v === undefined) return fallback;
  v = String(v).trim();
  return v === '' ? fallback : v;
}

function loadConfig_() {
  var len = parseInt(prop_('TITLE_BODY_LENGTH', DEFAULTS.TITLE_BODY_LENGTH), 10);
  return {
    slackToken: prop_('SLACK_BOT_TOKEN', ''),
    notionToken: prop_('NOTION_API_TOKEN', ''),
    databaseId: prop_('NOTION_TASK_DATABASE_ID', ''),
    assigneeUserId: prop_('NOTION_ASSIGNEE_USER_ID', ''),
    allowedUserId: prop_('ALLOWED_SLACK_USER_ID', ''),
    targetReaction: prop_('TARGET_REACTION', DEFAULTS.TARGET_REACTION),
    targetChannelId: prop_('TARGET_CHANNEL_ID', ''),
    targetChannelName: prop_('TARGET_CHANNEL_NAME', DEFAULTS.TARGET_CHANNEL_NAME),
    notionVersion: prop_('NOTION_VERSION', DEFAULTS.NOTION_VERSION),
    statusValue: prop_('NOTION_STATUS_VALUE', DEFAULTS.NOTION_STATUS_VALUE),
    assigneeName: prop_('NOTION_ASSIGNEE_NAME', DEFAULTS.NOTION_ASSIGNEE_NAME),
    propTitle: prop_('PROP_TITLE', DEFAULTS.PROP_TITLE),
    propStatus: prop_('PROP_STATUS', DEFAULTS.PROP_STATUS),
    propAssignee: prop_('PROP_ASSIGNEE', DEFAULTS.PROP_ASSIGNEE),
    propText: prop_('PROP_TEXT', DEFAULTS.PROP_TEXT),
    propSlackUrl: prop_('PROP_SLACK_URL', DEFAULTS.PROP_SLACK_URL),
    titleBodyLength: (isNaN(len) || len <= 0) ? 40 : len
  };
}

function missingRequired_() {
  var sp = PropertiesService.getScriptProperties();
  var missing = [];
  for (var i = 0; i < REQUIRED_KEYS.length; i++) {
    var k = REQUIRED_KEYS[i];
    var v = sp.getProperty(k);
    if (v === null || String(v).trim() === '') missing.push(k);
  }
  return missing;
}

function requireConfig_(cfg) {
  var missing = missingRequired_();
  if (missing.length) {
    throw new Error('スクリプト プロパティが未設定です: ' + missing.join(', ') +
      ' /「プロジェクトの設定 → スクリプト プロパティ」で設定してください。');
  }
  return cfg;
}

function textOut_(s) {
  return ContentService.createTextOutput(s);
}

// =====================================================================
// 手動テスト用(GAS エディタから実行する。Slack を経由せず切り分けできる)
// =====================================================================

/**
 * 設定の健康診断。Slack 認証・Notion 認証・DB のプロパティ名/型をまとめて確認する。
 * デプロイ直後にまずこれを実行すること。
 */
function testConfig() {
  var errors = [];
  var ok = [];

  var missing = missingRequired_();
  if (missing.length) {
    console.error('[NG] 未設定のスクリプト プロパティ: ' + missing.join(', '));
    console.error('先にプロパティを埋めてから再実行してください。');
    return;
  }
  ok.push('必須スクリプト プロパティ: 7件すべて設定済み');

  var cfg = loadConfig_();

  // Slack
  try {
    var auth = slackApi_(cfg.slackToken, 'auth.test', {});
    ok.push('Slack 認証: OK(team=' + auth.team + ', bot=' + auth.user + ')');
  } catch (err) {
    errors.push('Slack 認証: ' + err.message);
  }
  try {
    slackApi_(cfg.slackToken, 'conversations.history', { channel: cfg.targetChannelId, limit: 1 });
    ok.push('対象チャンネル読み取り: OK(' + cfg.targetChannelId + ')');
  } catch (err) {
    errors.push('対象チャンネル読み取り(' + cfg.targetChannelId + '): ' + err.message);
  }

  // Notion
  try {
    var schema = notionSchema_(cfg);
    ok.push('Notion DB 取得: OK(プロパティ ' + Object.keys(schema).length + '件)');
    var checks = [
      [cfg.propTitle, ['title']],
      [cfg.propStatus, ['status', 'select', 'rich_text']],
      [cfg.propAssignee, ['people', 'select', 'rich_text']],
      [cfg.propText, ['rich_text']],
      [cfg.propSlackUrl, ['url']]
    ];
    for (var i = 0; i < checks.length; i++) {
      try {
        var t = requireProp_(schema, checks[i][0], checks[i][1]);
        ok.push('プロパティ「' + checks[i][0] + '」: OK(' + t + ' 型)');
      } catch (err2) {
        errors.push(err2.message);
      }
    }
    // ステータス選択肢に INBOX があるか(あくまで警告)
    notionWarnStatusOption_(cfg);
  } catch (err) {
    errors.push('Notion DB 取得: ' + err.message);
  }

  console.log('----- OK -----\n' + ok.join('\n'));
  if (errors.length) {
    console.error('----- 要対応 -----\n' + errors.join('\n'));
  } else {
    console.log('----- 要対応なし。testDryRun() に進んでください。 -----');
  }
}

function notionWarnStatusOption_(cfg) {
  var db = notionApi_(cfg, 'get', 'https://api.notion.com/v1/databases/' + cfg.databaseId);
  var p = (db.properties || {})[cfg.propStatus];
  if (!p) return;
  var opts = [];
  if (p.type === 'status' && p.status && p.status.options) opts = p.status.options;
  if (p.type === 'select' && p.select && p.select.options) opts = p.select.options;
  if (!opts.length) return;
  var names = opts.map(function (o) { return o.name; });
  if (names.indexOf(cfg.statusValue) === -1) {
    console.warn('[warn]「' + cfg.propStatus + '」に「' + cfg.statusValue +
      '」の選択肢がありません。現在の選択肢: ' + names.join(', ') +
      ' → Notion 側に追加するか NOTION_STATUS_VALUE を変更してください。');
  }
}

/**
 * スクリプト プロパティ TEST_MESSAGE_URL に Slack メッセージの permalink を入れてから実行。
 * Notion への書き込みは行わず、送信予定の JSON をログに出す。
 */
function testDryRun() {
  runFromTestUrl_(true);
}

/**
 * testDryRun() と同じ入力で、実際に Notion へ 1 件登録する。
 * 2 回実行して 2 回目が「skip: 同じ Slackリンクが既に登録済み」になれば重複判定も確認できる。
 */
function testRegister() {
  runFromTestUrl_(false);
}

function runFromTestUrl_(dryRun) {
  var url = prop_('TEST_MESSAGE_URL', '');
  if (!url) {
    console.error('[NG] スクリプト プロパティ TEST_MESSAGE_URL に Slack メッセージの permalink を設定してください。');
    console.error('  例) https://<workspace>.slack.com/archives/C06F5DJ74UU/p1753800000123456');
    return;
  }
  var cfg = requireConfig_(loadConfig_());
  var parsed = parsePermalink_(url);
  if (parsed.channel !== cfg.targetChannelId) {
    console.warn('[warn] permalink のチャンネル(' + parsed.channel + ')が TARGET_CHANNEL_ID(' +
      cfg.targetChannelId + ')と違います。本番では channel 判定でスキップされます。');
  }
  var result = registerReaction_(cfg, {
    channel: parsed.channel,
    ts: parsed.ts,
    reaction: cfg.targetReaction,
    eventId: '' // 手動テストでは event_id 重複排除を使わない
  }, dryRun);
  console.log(result);
}

/**
 * NOTION_ASSIGNEE_USER_ID を調べるための補助。ワークスペースのユーザー一覧を
 * 「名前 / UUID」でログに出す。須原弘之さんの UUID をコピーしてプロパティに入れる。
 */
function testListNotionUsers() {
  var cfg = loadConfig_();
  if (!cfg.notionToken) {
    console.error('[NG] NOTION_API_TOKEN が未設定です。');
    return;
  }
  var res = notionApi_(cfg, 'get', 'https://api.notion.com/v1/users?page_size=100');
  var rows = (res.results || []).filter(function (u) { return u.type === 'person'; });
  if (!rows.length) {
    console.warn('[warn] ユーザーを取得できませんでした。インテグレーションの権限を確認してください。');
    return;
  }
  console.log(rows.map(function (u) { return (u.name || '(名前なし)') + '\t' + u.id; }).join('\n'));
}

/** https://x.slack.com/archives/C06F5DJ74UU/p1753800000123456 → {channel, ts} */
function parsePermalink_(url) {
  var m = String(url).match(/\/archives\/([A-Z0-9]+)\/p(\d{10})(\d{6})/);
  if (!m) {
    throw new Error('Slack の permalink 形式ではありません: ' + url +
      ' /(メッセージの「リンクをコピー」で取得できる URL を貼ってください)');
  }
  return { channel: m[1], ts: m[2] + '.' + m[3] };
}
