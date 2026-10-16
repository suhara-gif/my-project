// ==========================================================
// TW 広告タイプ(media_ad_type_tw__c)の誤記入を消す 1回限りの掃除（2026-10-09）
//
// 追加先: TwMediaSync.gs と同じ Apps Script プロジェクトに新規ファイルとして追加する。
//         （getSfToken_() と twSoqlAllStrict_()（TwMediaSync.gs v1.4.2）を流用する）
//
// 背景: 「流入後突合tw」の列ずれ（10/6〜10/7）で、広告タイプ項目に参照元メディアの名前
//       （google / meta / 不明分 / オーガニック / indeed / x / 求人BOX など）が書き込まれた。
//       本来この項目に入るのは SEARCH / PERFORMANCE_MAX / DEMAND_GEN / DISPLAY などの
//       Google広告のキャンペーンタイプだけ。
//       TwMediaSync は「既存値があれば上書きしない」ので、誤った値を消してから
//       twSyncMediaFields を実行し直すと、正しい値（type列）で埋め直される。
//
// 使い方:
//   1) twCleanupWrongAdType を実行（DRY_RUN=true）→ ログで件数と内訳を確認。SFには書かない。
//   2) 念のためSFの値を退避（ログSS「TW参照元メディア連携ログ」に _adtype_backup タブを作って書き出す。
//      これは DRY_RUN でも行う）。
//   3) CLEANUP_DRY_RUN を false にして再実行 → 対象の media_ad_type_tw__c を空にする。
//   4) twSyncMediaFields を実行 → 正しい広告タイプで埋め直される。
//   5) CLEANUP_DRY_RUN を true に戻す。
// ==========================================================

var CLEANUP_DRY_RUN = true;

// 消す対象の値（参照元メディアのラベル）。Google広告のキャンペーンタイプはここに入れない。
var TW_WRONG_ADTYPE_VALUES = ['google', 'meta', '不明分', 'オーガニック', 'indeed', 'Indeed', 'x', '求人BOX',
  'line', 'yahoo', 'その他', 'アフィリエイト', 'スタンバイ', '求人Boxリファラル'];

function twCleanupWrongAdType() {
  var sf = getSfToken_();
  var soql = "SELECT Id, ManagementToyowakuId_del__c, media_ad_type_tw__c FROM Contact " +
    "WHERE ManagementToyowakuId_del__c != null AND media_ad_type_tw__c != null";
  var records = twSoqlAllStrict_(sf, soql);

  var targets = records.filter(function (c) {
    return TW_WRONG_ADTYPE_VALUES.indexOf(String(c.media_ad_type_tw__c || '').trim()) >= 0;
  });

  var counts = {};
  targets.forEach(function (c) {
    var v = String(c.media_ad_type_tw__c).trim();
    counts[v] = (counts[v] || 0) + 1;
  });
  Logger.log('[CLEANUP] 広告タイプが入っているContact=' + records.length + ' うち消す対象=' + targets.length);
  Object.keys(counts).sort().forEach(function (v) { Logger.log('  [' + v + '] × ' + counts[v]); });

  if (!targets.length) { Logger.log('[CLEANUP] 対象なし。終了'); return; }

  // 退避（DRY_RUNでも毎回書き出す）
  var ss = SpreadsheetApp.openById(TW_CONFIG.LOG_SHEET_SPREADSHEET_ID);
  var sh = ss.getSheetByName('_adtype_backup') || ss.insertSheet('_adtype_backup');
  var stamp = new Date();
  var rows = targets.map(function (c) {
    return [stamp, c.Id, c.ManagementToyowakuId_del__c, c.media_ad_type_tw__c, CLEANUP_DRY_RUN ? 'DRY' : '消去'];
  });
  if (sh.getLastRow() === 0) sh.appendRow(['退避日時', 'ContactId', 'トヨワクID', '消す前の広告タイプ', 'モード']);
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
  Logger.log('[CLEANUP] 退避: _adtype_backup に ' + rows.length + ' 行');

  if (CLEANUP_DRY_RUN) {
    Logger.log('[CLEANUP][DRY] SFには書いていません。CLEANUP_DRY_RUN=false にして再実行すると消去します');
    return;
  }

  var updates = targets.map(function (c) {
    var f = {};
    f[TW_CONFIG.SF_ADTYPE_FIELD] = null;
    return { Id: c.Id, fields: f };
  });
  var result = twBatchPatchContacts_(updates);
  Logger.log('[CLEANUP] 消去: 成功=' + result.updated + ' 失敗=' + result.failed);
  result.errors.slice(0, 20).forEach(function (e) { Logger.log('  失敗 ' + e.Id + ': ' + e.message); });
}
