// ==========================================================
// トヨワク 直近1か月の参照元メディア・広告タイプ・キャンペーン名 入れ直し（1回限り, 2026-10-16）
//
// 追加先: TwMediaSync.gs と同じ Apps Script プロジェクトに新規ファイルとして追加する。
//         （getSfToken_ / twSoqlAllStrict_ / twFindCol_ / twLoadIndeedSet_ / twResolveMedia_ /
//          twBatchPatchContacts_ / twNormalizeDateKey_ / TW_CONFIG / TW_MEDIUM_VALUE_MAP を流用）
//
// 何をするか:
//   流入日が直近 RESYNC_DAYS 日のトヨワクContactについて、「流入後突合tw」の内容で
//     - Contact.sourceMedium_j_tw__c（参照元メディア）
//     - Contact.media_ad_type_tw__c（広告タイプ）
//     - ContactExtended_JS__c.media_ad_campaign_tw__c（キャンペーン名）
//   を入れ直す。日次の twSyncMediaFields は「空欄のときだけ書く」が、これは値が違えば上書きする。
//
// 守っていること:
//   - シート側に値が無いときは、SF の既存値を消さない（空で上書きしない）
//   - 書き込む前に、変更する全件の「旧値→新値」をログSSの _tw_resync_backup タブへ退避する（DRYでも書く）
//   - コンタクト状況(選択)が空のContactは、SFの入力規則で失敗するため対象外にする
//   - 求職者拡張情報(ContactExtended_JS__c)が無いContactには新規作成しない（件数だけ報告）
//   - 広告名（セッションの手動広告コンテンツ）はSFに項目が無いので、退避タブに記録だけする
//
// 使い方:
//   1) twResync30d を実行（RESYNC_DRY_RUN=true）→ ログで件数を確認。_tw_resync_backup に予定が出る。
//   2) RESYNC_DRY_RUN を false にして再実行 → 書き込む。
//   3) RESYNC_DRY_RUN を true に戻す。
// ==========================================================

var RESYNC_DRY_RUN = true;
var RESYNC_DAYS = 31;
var RESYNC_BACKUP_SHEET = '_tw_resync_backup';

// GA4レポート部分（A列から）の見出し行にある列名
var RESYNC_REPORT_HEADERS = {
  campaign: 'campaignName',
  content: 'セッションの手動広告コンテンツ',
};

// キャンペーン名として書かない値（GA4の既定値）
var RESYNC_CAMPAIGN_SKIP = ['', '(not set)', '(direct)', '(organic)', '(referral)', '(none)'];


function twResync30d() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) { Logger.log('⚠️ 別プロセス実行中のためスキップ'); return; }
  try {
    var stat = { ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0, unmappedLabel: 0 };
    var sheetMap = rsLoadSheetMap_(stat);
    var indeedSet = twLoadIndeedSet_(stat);
    var resolved = twResolveMedia_(sheetMap, indeedSet, stat);

    var sf = getSfToken_();
    var contacts = twSoqlAllStrict_(sf,
      'SELECT Id, ' + TW_CONFIG.SF_ID_FIELD + ', ManagementToyowakuInflowDate_del__c, ' +
      TW_CONFIG.SF_MEDIUM_FIELD + ', ' + TW_CONFIG.SF_ADTYPE_FIELD + ', ' + TW_CONFIG.SF_STATUS_FIELD +
      ' FROM Contact WHERE ' + TW_CONFIG.SF_ID_FIELD + ' != null' +
      ' AND ManagementToyowakuInflowDate_del__c = LAST_N_DAYS:' + RESYNC_DAYS);
    var exts = twSoqlAllStrict_(sf,
      'SELECT Id, Contact__c, media_ad_campaign_tw__c FROM ContactExtended_JS__c' +
      ' WHERE Contact__r.' + TW_CONFIG.SF_ID_FIELD + ' != null' +
      ' AND Contact__r.ManagementToyowakuInflowDate_del__c = LAST_N_DAYS:' + RESYNC_DAYS);
    var extByContact = {};
    exts.forEach(function (e) { (extByContact[e.Contact__c] = extByContact[e.Contact__c] || []).push(e); });

    var cnt = { contacts: contacts.length, noSheet: 0, statusBlocked: 0, noExt: 0,
      medium: 0, adType: 0, campaign: 0, same: 0 };
    var contactUpdates = [], extUpdates = [], backup = [];
    var stamp = new Date();

    contacts.forEach(function (c) {
      var twId = String(c[TW_CONFIG.SF_ID_FIELD] || '').trim();
      var row = sheetMap[twId];
      var res = resolved[twId] || {};
      if (!row && !res.value) { cnt.noSheet++; return; }
      if (!String(c[TW_CONFIG.SF_STATUS_FIELD] || '').trim()) { cnt.statusBlocked++; return; }

      var inflow = c.ManagementToyowakuInflowDate_del__c;
      var content = row ? row.content : '';
      var fields = {};
      var changed = false;

      var newMedium = res.value || '';
      var curMedium = String(c[TW_CONFIG.SF_MEDIUM_FIELD] || '');
      if (newMedium && newMedium !== curMedium) {
        fields[TW_CONFIG.SF_MEDIUM_FIELD] = newMedium; cnt.medium++; changed = true;
        backup.push([stamp, twId, c.Id, inflow, '参照元メディア', curMedium, newMedium, content, RESYNC_DRY_RUN ? 'DRY' : '']);
      }
      var newType = row ? row.adType : '';
      var curType = String(c[TW_CONFIG.SF_ADTYPE_FIELD] || '');
      if (newType && newType !== curType) {
        fields[TW_CONFIG.SF_ADTYPE_FIELD] = newType; cnt.adType++; changed = true;
        backup.push([stamp, twId, c.Id, inflow, '広告タイプ', curType, newType, content, RESYNC_DRY_RUN ? 'DRY' : '']);
      }
      if (changed) contactUpdates.push({ Id: c.Id, fields: fields });

      var newCamp = row ? row.campaign : '';
      if (newCamp) {
        var list = extByContact[c.Id];
        if (!list || !list.length) {
          cnt.noExt++;
          backup.push([stamp, twId, c.Id, inflow, 'キャンペーン名', '(拡張情報なし)', newCamp, content, '未作成のため対象外']);
        } else {
          list.forEach(function (e) {
            var cur = String(e.media_ad_campaign_tw__c || '');
            if (cur === newCamp) return;
            extUpdates.push({ Id: e.Id, fields: { media_ad_campaign_tw__c: newCamp } });
            cnt.campaign++; changed = true;
            backup.push([stamp, twId, c.Id, inflow, 'キャンペーン名', cur, newCamp, content, RESYNC_DRY_RUN ? 'DRY' : '']);
          });
        }
      }
      if (!changed) cnt.same++;
    });

    rsWriteBackup_(backup);
    Logger.log('[RESYNC] 対象Contact(流入' + RESYNC_DAYS + '日以内)=' + cnt.contacts +
      ' シートに無し=' + cnt.noSheet + ' コンタクト状況未設定で対象外=' + cnt.statusBlocked +
      ' 変更なし=' + cnt.same);
    Logger.log('[RESYNC] 変更予定: 参照元メディア=' + cnt.medium + ' 広告タイプ=' + cnt.adType +
      ' キャンペーン名=' + cnt.campaign + ' 拡張情報が無くキャンペーン名を書けない=' + cnt.noExt +
      ' 辞書未収録=' + stat.unmappedLabel);
    Logger.log('[RESYNC] 退避: ' + RESYNC_BACKUP_SHEET + ' に ' + backup.length + ' 行');

    if (RESYNC_DRY_RUN) {
      Logger.log('[RESYNC][DRY] SFには書いていません。RESYNC_DRY_RUN=false にして再実行すると書き込みます');
      return;
    }
    var r1 = twBatchPatchContacts_(contactUpdates);
    var r2 = rsBatchPatch_('ContactExtended_JS__c', extUpdates);
    Logger.log('[RESYNC] Contact: 成功=' + r1.updated + ' 失敗=' + r1.failed +
      ' / 拡張情報: 成功=' + r2.updated + ' 失敗=' + r2.failed);
    r1.errors.concat(r2.errors).slice(0, 20).forEach(function (e) { Logger.log('  失敗 ' + e.Id + ': ' + e.message); });
  } finally {
    lock.releaseLock();
  }
}


// 流入後突合tw を読み、会員ID → 最初の流入行の {label, adType, campaign, content, date}
function rsLoadSheetMap_(stat) {
  var sheet = SpreadsheetApp.openById(TW_CONFIG.GA4_SHEET_ID).getSheetByName(TW_CONFIG.GA4_SHEET_NAME);
  if (!sheet) throw new Error('シート未検出: ' + TW_CONFIG.GA4_SHEET_NAME);
  var values = sheet.getDataRange().getValues();

  var idCol = twColLetterToIndex_(TW_CONFIG.GA4_COL.id);
  var dateCol = twColLetterToIndex_(TW_CONFIG.GA4_COL.date);
  var mediumCol = twFindCol_(values[0], TW_CONFIG.GA4_HEADERS.medium, 'medium');
  var adTypeCol = twFindCol_(values[0], TW_CONFIG.GA4_HEADERS.adType, 'adType');

  // GA4レポートの見出し行（A列が "date" の行）から campaignName / 手動広告コンテンツ の列を探す
  var hdrRow = -1;
  for (var i = 0; i < Math.min(values.length, 50); i++) {
    if (String(values[i][0]).trim() === 'date') { hdrRow = i; break; }
  }
  if (hdrRow < 0) throw new Error('流入後突合tw にGA4レポートの見出し行（A列="date"）が見つかりません');
  var campCol = twFindCol_(values[hdrRow], [RESYNC_REPORT_HEADERS.campaign], 'campaign');
  var contentCol = values[hdrRow].map(function (h) { return String(h).trim(); })
    .indexOf(RESYNC_REPORT_HEADERS.content); // 無くても続行（広告名は記録用）
  Logger.log('[RESYNC] 列位置(1始まり): id=' + (idCol + 1) + ' medium=' + (mediumCol + 1) +
    ' adType=' + (adTypeCol + 1) + ' campaign=' + (campCol + 1) + ' content=' + (contentCol + 1));

  var map = {};
  for (var r = hdrRow + 1; r < values.length; r++) {
    stat.ga4Rows++;
    var row = values[r];
    var twId = String(row[idCol] || '').trim();
    if (!/^\d+$/.test(twId)) continue;
    if (Object.prototype.toString.call(row[mediumCol]) === '[object Date]') {
      throw new Error('参照元メディア列に日付が入っています（' + (r + 1) + '行目）。列ずれの可能性があるため中止しました。');
    }
    stat.ga4ValidId++;
    var camp = String(row[campCol] || '').trim();
    if (RESYNC_CAMPAIGN_SKIP.indexOf(camp) >= 0) camp = '';
    var content = contentCol >= 0 ? String(row[contentCol] || '').trim() : '';
    if (content === '(not set)') content = '';
    var dateKey = twNormalizeDateKey_(row[dateCol]);

    var ex = map[twId];
    if (!ex || (dateKey && (!ex.date || dateKey < ex.date))) {
      map[twId] = {
        label: String(row[mediumCol] || '').trim(),
        adType: String(row[adTypeCol] || '').trim().slice(0, 255),
        campaign: camp.slice(0, 255),
        content: content,
        date: dateKey,
      };
    }
  }
  if (!stat.ga4ValidId) throw new Error('流入後突合tw から会員IDが1件も読めません');
  return map;
}


function rsWriteBackup_(rows) {
  var ss = SpreadsheetApp.openById(TW_CONFIG.LOG_SHEET_SPREADSHEET_ID);
  var sh = ss.getSheetByName(RESYNC_BACKUP_SHEET) || ss.insertSheet(RESYNC_BACKUP_SHEET);
  if (sh.getLastRow() === 0) {
    sh.appendRow(['実行日時', 'トヨワクID', 'ContactId', '流入日', '項目', '旧値', '新値', '広告名(記録のみ)', 'モード']);
  }
  if (!rows.length) return;
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}


function rsBatchPatch_(sobject, updates) {
  var sf = getSfToken_();
  var result = { updated: 0, failed: 0, errors: [] };
  for (var i = 0; i < updates.length; i += TW_CONFIG.SF_WRITE_CHUNK) {
    var chunk = updates.slice(i, i + TW_CONFIG.SF_WRITE_CHUNK);
    var records = chunk.map(function (u) {
      var rec = { attributes: { type: sobject }, Id: u.Id };
      Object.assign(rec, u.fields);
      return rec;
    });
    var res = UrlFetchApp.fetch(sf.instance_url + '/services/data/' + TW_CONFIG.SF_API_VERSION + '/composite/sobjects', {
      method: 'patch',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + sf.access_token },
      payload: JSON.stringify({ allOrNone: false, records: records }),
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() >= 300 && res.getResponseCode() !== 400) {
      throw new Error(sobject + ' 更新失敗(HTTP ' + res.getResponseCode() + '): ' + res.getContentText().slice(0, 300));
    }
    JSON.parse(res.getContentText() || '[]').forEach(function (r, idx) {
      if (r.success) { result.updated++; return; }
      result.failed++;
      result.errors.push({ Id: chunk[idx].Id,
        message: (r.errors || []).map(function (e) { return e.message; }).join('; ') || 'unknown' });
    });
  }
  return result;
}
