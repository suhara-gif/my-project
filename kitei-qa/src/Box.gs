/**
 * Box API まわり。
 *
 * 認証は Box の「クライアント資格情報許可(Client Credentials Grant)」アプリを使う。
 * アプリのサービスアカウントを規程フォルダに「ビューアー」で招待しておけば、
 * 従業員一人ひとりが Box アカウントを持っていなくても規程を読める。
 */

var BOX_API = 'https://api.box.com/2.0';
var TEXT_EXTENSIONS = ['pdf', 'docx', 'doc', 'txt', 'md'];
var CACHE_TTL_SECONDS = 21600; // CacheService の上限(6時間)
var CACHE_CHUNK_CHARS = 30000; // 1キー100KB上限。日本語は1文字最大3バイトなので余裕を持たせる

function getBoxToken_() {
  var cache = CacheService.getScriptCache();
  var cached = cache.get('box_token');
  if (cached) return cached;

  var res = UrlFetchApp.fetch('https://api.box.com/oauth2/token', {
    method: 'post',
    payload: {
      grant_type: 'client_credentials',
      client_id: getConfig_('BOX_CLIENT_ID'),
      client_secret: getConfig_('BOX_CLIENT_SECRET'),
      box_subject_type: 'enterprise',
      box_subject_id: getConfig_('BOX_ENTERPRISE_ID'),
    },
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    // レスポンス本文には秘密情報は含まれないが、念のためステータスだけを出す
    throw new Error('Boxの認証に失敗しました(HTTP ' + res.getResponseCode() + ')。管理者に連絡してください。');
  }
  var body = JSON.parse(res.getContentText());
  // 有効期限より少し早めに捨てる
  cache.put('box_token', body.access_token, Math.max(60, Math.min(body.expires_in - 300, CACHE_TTL_SECONDS)));
  return body.access_token;
}

function boxGet_(url, extraHeaders) {
  var headers = { Authorization: 'Bearer ' + getBoxToken_() };
  Object.keys(extraHeaders || {}).forEach(function (k) { headers[k] = extraHeaders[k]; });
  return UrlFetchApp.fetch(url, { headers: headers, muteHttpExceptions: true });
}

/**
 * フォルダ直下のファイル(=現行版)を返す。サブフォルダ(「旧フォルダ」等)の中は見ない。
 * @return {{id: string, name: string, modifiedAt: string, versionId: string}[]}
 */
function listCurrentRuleFiles_(folderId) {
  var files = [];
  var offset = 0;
  while (true) {
    var res = boxGet_(BOX_API + '/folders/' + folderId + '/items' +
      '?fields=id,type,name,extension,modified_at,file_version&limit=1000&offset=' + offset);
    if (res.getResponseCode() !== 200) {
      throw new Error('Boxの規程フォルダを読めませんでした(HTTP ' + res.getResponseCode() + ')。管理者に連絡してください。');
    }
    var body = JSON.parse(res.getContentText());
    body.entries.forEach(function (item) {
      if (item.type !== 'file') return;
      if (TEXT_EXTENSIONS.indexOf(String(item.extension).toLowerCase()) === -1) return;
      files.push({
        id: item.id,
        name: item.name,
        modifiedAt: item.modified_at,
        versionId: item.file_version ? item.file_version.id : item.modified_at,
      });
    });
    offset += body.entries.length;
    if (body.entries.length === 0 || offset >= body.total_count) break;
  }
  return files;
}

/**
 * ファイル本文のテキストを返す。読めない(スキャン画像PDF等)場合は空文字。
 * キャッシュキーにバージョンIDを含めるので、Box上でファイルが更新されれば自動で読み直す。
 */
function getFileText_(file) {
  var cacheKey = 'txt_' + file.id + '_' + file.versionId;
  var cached = getLargeCache_(cacheKey);
  if (cached !== null) return cached;

  var text = fetchExtractedText_(file.id);
  if (text !== null) putLargeCache_(cacheKey, text);
  return text || '';
}

/**
 * Box が生成する extracted_text 表現を取得する。
 * 生成待ち(pending)の間は数回だけ待つ。取得できなければ null(=次回また試す)。
 */
function fetchExtractedText_(fileId) {
  for (var attempt = 0; attempt < 4; attempt++) {
    var res = boxGet_(BOX_API + '/files/' + fileId + '?fields=representations',
      { 'x-rep-hints': '[extracted_text]' });
    if (res.getResponseCode() !== 200) return null;
    var entries = (JSON.parse(res.getContentText()).representations || {}).entries || [];
    var rep = entries.filter(function (e) { return e.representation === 'extracted_text'; })[0];
    if (!rep) return '';

    var state = rep.status && rep.status.state;
    if (state === 'success') {
      var content = boxGet_(rep.content.url_template.replace('{+asset_path}', ''));
      if (content.getResponseCode() === 200) return content.getContentText('UTF-8');
      if (content.getResponseCode() !== 202) return null;
    } else if (state === 'error') {
      return ''; // テキスト層が無い等。キャッシュして毎回の再試行を避ける
    } else {
      // none / pending: info URL を叩くと生成が始まる
      boxGet_(rep.info.url);
    }
    Utilities.sleep(2000);
  }
  return null;
}

function putLargeCache_(key, text) {
  var cache = CacheService.getScriptCache();
  var chunks = [];
  for (var i = 0; i < text.length; i += CACHE_CHUNK_CHARS) {
    chunks.push(text.substring(i, i + CACHE_CHUNK_CHARS));
  }
  var values = {};
  values[key] = String(chunks.length);
  chunks.forEach(function (c, i) { values[key + '_' + i] = c; });
  cache.putAll(values, CACHE_TTL_SECONDS);
}

function getLargeCache_(key) {
  var cache = CacheService.getScriptCache();
  var count = cache.get(key);
  if (count === null) return null;
  var keys = [];
  for (var i = 0; i < Number(count); i++) keys.push(key + '_' + i);
  var values = cache.getAll(keys);
  var parts = [];
  for (var j = 0; j < keys.length; j++) {
    if (values[keys[j]] === undefined) return null; // 一部が消えていたら読み直す
    parts.push(values[keys[j]]);
  }
  return parts.join('');
}
