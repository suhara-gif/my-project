/**
 * スキャン画像PDF(文字データが無いPDF)の文字認識。
 *
 * Box が生成するページ画像(PNG)を1ページずつ取得し、Googleドライブの文字認識(画像→Googleドキュメント変換)に
 * かけて本文を得る。ドライブの文字認識はファイルサイズ・ページ数に制限があるとされるため、PDFをまとめて
 * 変換せず、1ページずつ画像で変換する。費用はかからない。
 *
 * 結果はページごと・ファイルのバージョンごとにドライブのテキストファイルとして保存し、同じ版は二度と認識し直さない。
 * 1回の実行時間内に終わらなくても、次の実行では続きのページから再開する。
 */

var OCR_CACHE_FOLDER_NAME = '社内規程Q&A_文字認識キャッシュ';
var OCR_PAGE_HINT = '[png?dimensions=2048x2048]';
var OCR_MAX_PAGES = 300;

/**
 * @param {{id: string, name: string, versionId: string}} file
 * @param {number} deadline この時刻(ミリ秒)を過ぎたら中断する
 * @return {?string} 認識した本文。時間切れ・Box側の準備中なら null(次回の実行で続きから試す)
 */
function ocrFile_(file, deadline) {
  var folder = getOcrCacheFolder_();
  var cacheName = file.id + '_' + file.versionId + '.txt';
  var cached = readCacheFile_(folder, cacheName);
  if (cached !== null) return cached;

  var rep = fetchRepresentation_(file.id, OCR_PAGE_HINT, 'png');
  if (!rep) return null;

  var pageCount = getPageCount_(rep);
  var pages = [];
  for (var p = 1; p <= Math.min(pageCount || OCR_MAX_PAGES, OCR_MAX_PAGES); p++) {
    var pageCacheName = file.id + '_' + file.versionId + '_p' + p + '.txt';
    var pageText = readCacheFile_(folder, pageCacheName);
    if (pageText === null) {
      if (Date.now() > deadline) return null;
      var res = boxGet_(rep.content.url_template.replace('{+asset_path}', p + '.png'));
      if (res.getResponseCode() === 404 && !pageCount) break; // ページ数が分からないときは、404で終わりと判断する
      if (res.getResponseCode() !== 200) return null;
      pageText = ocrImage_(res.getBlob().setName(file.name + '_p' + p + '.png'));
      folder.createFile(pageCacheName, pageText, MimeType.PLAIN_TEXT);
    }
    pages.push(pageText);
  }

  var text = pages.join('\n\n');
  folder.createFile(cacheName, text, MimeType.PLAIN_TEXT);
  return text;
}

/** 画像1枚をGoogleドキュメントに変換して文字を取り出し、一時ドキュメントは削除する */
function ocrImage_(blob) {
  var doc = Drive.Files.create(
    { name: '社内規程Q&A_一時ファイル', mimeType: MimeType.GOOGLE_DOCS },
    blob,
    { ocrLanguage: 'ja', fields: 'id' });
  try {
    return DocumentApp.openById(doc.id).getBody().getText();
  } finally {
    Drive.Files.remove(doc.id);
  }
}

/**
 * Box のページ画像の表現を取得する。準備中なら数回だけ待つ。用意できなければ null。
 */
function fetchRepresentation_(fileId, hint, repName) {
  for (var attempt = 0; attempt < 4; attempt++) {
    var res = boxGet_(BOX_API + '/files/' + fileId + '?fields=representations', { 'x-rep-hints': hint });
    if (res.getResponseCode() !== 200) return null;
    var entries = (JSON.parse(res.getContentText()).representations || {}).entries || [];
    var rep = entries.filter(function (e) { return e.representation === repName; })[0];
    if (!rep) return null;
    var state = rep.status && rep.status.state;
    if (state === 'success') return rep;
    if (state === 'error') return null;
    boxGet_(rep.info.url); // none / pending: info URL を叩くと生成が始まる
    Utilities.sleep(2000);
  }
  return null;
}

/** ページ数。Box の info に載っていなければ 0(=不明) */
function getPageCount_(rep) {
  var res = boxGet_(rep.info.url);
  if (res.getResponseCode() !== 200) return 0;
  var info = JSON.parse(res.getContentText());
  return (info.metadata && Number(info.metadata.pages)) || 0;
}

function readCacheFile_(folder, name) {
  var it = folder.getFilesByName(name);
  return it.hasNext() ? it.next().getBlob().getDataAsString('UTF-8') : null;
}

function getOcrCacheFolder_() {
  var props = PropertiesService.getScriptProperties();
  var folderId = props.getProperty('OCR_FOLDER_ID');
  if (folderId) return DriveApp.getFolderById(folderId);
  var folder = DriveApp.createFolder(OCR_CACHE_FOLDER_NAME);
  props.setProperty('OCR_FOLDER_ID', folder.getId());
  return folder;
}
