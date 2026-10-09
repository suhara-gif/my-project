// ==========================================================
// TW参照元メディア／広告タイプ SF日次連携 v1.4（2026-10-09）
//
// 追加先: Apps Script プロジェクト「【応募者リスト】indeed直接募集_オウンドメディア→SF 簡易自動登録」
//         （オーナー: ahr info）の TwMediaSync.gs をこのファイル全文で置き換える。
// 前提: 同プロジェクトに SF_Auth.gs の getSfToken_()、OwnedMedia_SF_Sync.gs の omSoqlAll_() /
//       reportHeartbeat_() が存在すること（同一GASプロジェクト内なのでグローバル関数として流用できる）
//
// 目的: 流入経路別／属性別の「決まりやすさ」を見るため、Contact の
//       sourceMedium_j_tw__c（【メディア】参照元メディア_tw）と
//       media_ad_type_tw__c（【メディア】広告タイプ_tw）を日次で埋める。
//       突合キーは ManagementToyowakuId_del__c（【管理】トヨワクID）。
//       新規Contactは絶対に作らない。既存の2項目更新のみ。
//
// ソース①: SS 1hf0NeZIlB_1RvMut1it1bfDk9HZBv9N0EM-m19KaRZ4 / シート「流入後突合tw」
// ソース②: SS 1OfSiE6lRjYB1nsKNLVUV3DPDgQlgQPufBgrowwuJuR8 / シート「indeed_entry_tw」
//          B=ユーザーID／W=登録元システム（Indeedならメディア=Indeed）
//
// 統合ルール（2026-09-02 須原さん承認）:
// 1) 参照元メディアは初回流入で固定（同一IDが複数行あれば日付が最も早い行を採用）
// 2) GA4優先。GA4側が「その他/不明分」（(direct) / (none) 相当）のときだけIndeedで上書き
// 3) SF側の当該項目が空のときだけ書く（値がある行は上書きせずログに記録するだけ）
// 4) トヨワクID重複（同一IDで複数Contact）は該当する全レコードを更新
//
// --- v1.1 / v1.2（2026-09-11）---
// コンタクト状況(選択)未設定のContactを対象外にする。失敗が出た日はSlack通知。
//
// --- v1.4 変更点（2026-10-09）---
// 「流入後突合tw」に列が1つ追加され（10/6〜10/7ごろ）、O列=参照元メディア／P列=type の
// 固定指定がずれた。O列に日付が入って参照元メディアが全件「辞書未収録」でスキップ、
// P列（実は参照元メディア）が広告タイプとして約1,540件書き込まれた。実行結果は毎日「完了」だった。
// 今後も列は足すため、次のように変更した。
// 1) 列は文字ではなく1行目の見出し名で探す（GA4_HEADERS）。見つからなければ例外で止める。
// 2) 参照元メディア列に日付が入っていたら例外で止める（列ずれの検知）。
// 3) 有効IDがあるのに参照元メディアが1件も辞書に当たらない日は例外で止める。
//    → どれも実行結果が「失敗」になり、エラー通知メールで気づける。
// ==========================================================


// ---------- 設定 ----------
var TW_CONFIG = {
  SF_API_VERSION: 'v60.0',

  GA4_SHEET_ID: '1hf0NeZIlB_1RvMut1it1bfDk9HZBv9N0EM-m19KaRZ4',
  GA4_SHEET_NAME: '流入後突合tw',
  // 見出し名の候補（上から順に探す）。シートの見出しを変えたらここに足す。
  GA4_HEADERS: {
    id: ['tw会員ID', '会員ID', 'ユーザーID'],
    medium: ['参照元メディア'],
    adType: ['type', '広告タイプ'],
    date: ['日付'],
  },

  INDEED_SHEET_ID: '1OfSiE6lRjYB1nsKNLVUV3DPDgQlgQPufBgrowwuJuR8',
  INDEED_SHEET_NAME: 'indeed_entry_tw',
  INDEED_COL: { id: 'B', system: 'W' },

  LOG_SHEET: '_tw_media_log',
  LOG_SHEET_SPREADSHEET_ID: '1ZOB2Y9EKtfzsA2MRnhjGCaniPo_bnWJoASbNx-PuMK4',
  DRY_RUN: false,
  SF_WRITE_CHUNK: 200,
  SF_ID_FIELD: 'ManagementToyowakuId_del__c',
  SF_MEDIUM_FIELD: 'sourceMedium_j_tw__c',
  SF_ADTYPE_FIELD: 'media_ad_type_tw__c',
  SF_STATUS_FIELD: 'IscContactStatusSelection__c',

  SLACK_WEBHOOK_PROP: 'SLACK_WEBHOOK_URL',

  FALLBACK_LABELS: ['その他', '不明分', '(direct) / (none)', ''],
};

var TW_MEDIUM_VALUE_MAP = {
  'google': 'google / cpc',
  'indeed': 'Indeed / cpc',
  'Indeed': 'Indeed / cpc',
  'line': 'line',
  'meta': 'meta / cpc',
  'yahoo': 'yahoo / cpc',
  'アフィリエイト': 'アフィリエイト',
  'オーガニック': 'chatgpt.com / (not set)',
  'スタンバイ': 'stanby / cpc',
  'スタンバイリファラル': 'スタンバイリファラル',
  'その他': '(direct) / (none)',
  '不明分': '(direct) / (none)',
  '求人BOX': 'kbox / cpc',
  '求人Boxリファラル': '求人ボックス.com / referral',
  'Yahoo!オーガニック': 'yahoo / organic',
  'CWコラム': 'carworkassist / column_banner',
};


function twSyncMediaFields() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) { Logger.log('⚠️ 別プロセス実行中のためスキップ'); return; }

  try {
    var stat = {
      ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0,
      candidates: 0, unmappedLabel: 0, noSfMatch: 0, alreadySet: 0,
      statusBlocked: 0,
      willUpdateContacts: 0, updated: 0, failed: 0,
    };

    var ga4Map = twLoadGa4Map_(stat);
    var indeedSet = twLoadIndeedSet_(stat);

    var resolved = twResolveMedia_(ga4Map, indeedSet, stat);
    stat.candidates = Object.keys(resolved).length;

    twAssertMediumMapped_(ga4Map);

    if (!stat.candidates) {
      Logger.log('[TW] 対象トヨワクIDなし。GA4=' + stat.ga4ValidId + ' / Indeed=' + stat.indeedValidId);
      twReportHeartbeatSafe_();
      return;
    }

    var sfByTwId = twLoadSfContactsByTwId_(Object.keys(resolved));

    var logRows = [];
    var updates = [];

    Object.keys(resolved).forEach(function (twId) {
      var r = resolved[twId];
      var contacts = sfByTwId[twId];

      if (!contacts || !contacts.length) {
        stat.noSfMatch++;
        logRows.push([new Date(), twId, '', '', '', 'skip:SF側に該当Contactなし']);
        return;
      }

      contacts.forEach(function (c) {
        if (!String(c[TW_CONFIG.SF_STATUS_FIELD] || '').trim()) {
          stat.statusBlocked++;
          logRows.push([new Date(), twId, c.Id, r.value || '', r.adType || '',
            'skip:コンタクト状況(選択)未設定のため対象外(埋まれば次回以降で自動的に対象復帰)']);
          return;
        }

        var fields = {};
        var curMedium = String(c[TW_CONFIG.SF_MEDIUM_FIELD] || '').trim();
        var curAdType = String(c[TW_CONFIG.SF_ADTYPE_FIELD] || '').trim();

        if (r.value && !curMedium) fields[TW_CONFIG.SF_MEDIUM_FIELD] = r.value;
        if (r.adType && !curAdType) fields[TW_CONFIG.SF_ADTYPE_FIELD] = r.adType;

        if (!Object.keys(fields).length) {
          stat.alreadySet++;
          logRows.push([new Date(), twId, c.Id, r.value || '', r.adType || '', 'skip:既存値あり(上書きしない)']);
          return;
        }

        stat.willUpdateContacts++;
        updates.push({ Id: c.Id, fields: fields });
        logRows.push([new Date(), twId, c.Id,
          fields[TW_CONFIG.SF_MEDIUM_FIELD] || '(変更なし)',
          fields[TW_CONFIG.SF_ADTYPE_FIELD] || '(変更なし)',
          TW_CONFIG.DRY_RUN ? 'DRY:書込予定' : '']);
      });
    });

    Logger.log('[TW] GA4行=' + stat.ga4Rows + '/有効ID=' + stat.ga4ValidId +
      ' Indeed行=' + stat.indeedRows + '/有効ID=' + stat.indeedValidId +
      ' 対象ID=' + stat.candidates + ' 辞書未収録=' + stat.unmappedLabel +
      ' SF不一致=' + stat.noSfMatch + ' 既存値あり=' + stat.alreadySet +
      ' コンタクト状況未設定=' + stat.statusBlocked +
      ' 更新対象Contact=' + stat.willUpdateContacts);

    if (!TW_CONFIG.DRY_RUN && updates.length) {
      var result = twBatchPatchContacts_(updates);
      stat.updated = result.updated;
      stat.failed = result.failed;
      result.errors.forEach(function (e) {
        logRows.push([new Date(), '', e.Id, '', '', 'error:' + e.message]);
      });
    }

    twAppendLog_(logRows, stat);
    Logger.log((TW_CONFIG.DRY_RUN ? '[DRY] ' : '') + '完了: 更新対象=' + stat.willUpdateContacts +
      ' 成功=' + stat.updated + ' 失敗=' + stat.failed + ' コンタクト状況未設定で対象外=' + stat.statusBlocked);
    twNotifyFailuresIfAny_(stat);
    twReportHeartbeatSafe_();

  } finally {
    lock.releaseLock();
  }
}


// 1行目の見出しから列番号(0始まり)を探す。見つからなければ例外。
function twFindCol_(header, candidates, key) {
  var norm = header.map(function (h) { return String(h || '').trim(); });
  for (var i = 0; i < candidates.length; i++) {
    var idx = norm.indexOf(candidates[i]);
    if (idx >= 0) return idx;
  }
  throw new Error('流入後突合tw の見出しに「' + candidates.join(' / ') + '」(' + key + ') が見つかりません。' +
    '見出し行: [' + norm.join(' | ') + ']。TW_CONFIG.GA4_HEADERS に今の見出し名を足してください。');
}


function twLoadGa4Map_(stat) {
  var ss = SpreadsheetApp.openById(TW_CONFIG.GA4_SHEET_ID);
  var sheet = ss.getSheetByName(TW_CONFIG.GA4_SHEET_NAME);
  if (!sheet) throw new Error('シート未検出: ' + TW_CONFIG.GA4_SHEET_NAME);

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  var header = values[0];
  var idCol = twFindCol_(header, TW_CONFIG.GA4_HEADERS.id, 'id');
  var mediumCol = twFindCol_(header, TW_CONFIG.GA4_HEADERS.medium, 'medium');
  var adTypeCol = twFindCol_(header, TW_CONFIG.GA4_HEADERS.adType, 'adType');
  var dateCol = twFindCol_(header, TW_CONFIG.GA4_HEADERS.date, 'date');
  Logger.log('[TW] 列位置: id=' + (idCol + 1) + ' medium=' + (mediumCol + 1) +
    ' adType=' + (adTypeCol + 1) + ' date=' + (dateCol + 1) + '（1始まり）');

  var map = {};

  for (var r = 1; r < values.length; r++) {
    stat.ga4Rows++;
    var row = values[r];
    var twId = String(row[idCol] || '').trim();
    if (!twId || twId === '(not set)' || !/^\d+$/.test(twId)) continue;

    var mediumRaw = row[mediumCol];
    if (Object.prototype.toString.call(mediumRaw) === '[object Date]') {
      throw new Error('流入後突合tw の参照元メディア列(' + (mediumCol + 1) + '列目)に日付が入っています(' +
        (r + 1) + '行目)。列ずれの可能性があるため中止しました。');
    }

    stat.ga4ValidId++;
    var label = String(mediumRaw || '').trim();
    var adType = String(row[adTypeCol] || '').trim().slice(0, 255);
    var dateKey = twNormalizeDateKey_(row[dateCol]);

    var existing = map[twId];
    if (!existing || (dateKey && (!existing.date || dateKey < existing.date))) {
      map[twId] = { label: label, adType: adType, date: dateKey };
    }
  }

  return map;
}


// 有効IDがあるのに参照元メディアが1件も辞書に当たらない＝読む列が違う、とみなして止める
function twAssertMediumMapped_(ga4Map) {
  var ids = Object.keys(ga4Map);
  if (!ids.length) return;
  var hit = 0;
  for (var i = 0; i < ids.length; i++) {
    var label = ga4Map[ids[i]].label;
    if (TW_MEDIUM_VALUE_MAP[label] || TW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0) hit++;
  }
  if (!hit) {
    throw new Error('流入後突合tw の参照元メディアが ' + ids.length + ' 件すべて辞書に当たりません。' +
      '列ずれか見出しの変更の可能性があるため中止しました。');
  }
}


function twLoadIndeedSet_(stat) {
  var ss = SpreadsheetApp.openById(TW_CONFIG.INDEED_SHEET_ID);
  var sheet = ss.getSheetByName(TW_CONFIG.INDEED_SHEET_NAME);
  if (!sheet) throw new Error('シート未検出: ' + TW_CONFIG.INDEED_SHEET_NAME);

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  var idCol = twColLetterToIndex_(TW_CONFIG.INDEED_COL.id);
  var sysCol = twColLetterToIndex_(TW_CONFIG.INDEED_COL.system);

  var set = {};

  for (var r = 1; r < values.length; r++) {
    stat.indeedRows++;
    var row = values[r];
    var twId = String(row[idCol] || '').trim();
    if (!twId || !/^\d+$/.test(twId)) continue;

    var sys = String(row[sysCol] || '').trim();
    if (sys !== 'Indeed') continue;

    stat.indeedValidId++;
    set[twId] = true;
  }

  return set;
}


function twResolveMedia_(ga4Map, indeedSet, stat) {
  var resolved = {};
  var allIds = {};
  Object.keys(ga4Map).forEach(function (id) { allIds[id] = true; });
  Object.keys(indeedSet).forEach(function (id) { allIds[id] = true; });

  Object.keys(allIds).forEach(function (twId) {
    var ga4 = ga4Map[twId];
    var fromIndeed = !!indeedSet[twId];

    var label = ga4 ? ga4.label : '';
    var isFallback = TW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0;

    var finalLabel = label;
    if ((!label || isFallback) && fromIndeed) finalLabel = 'Indeed';

    var value = '';
    if (finalLabel) {
      value = TW_MEDIUM_VALUE_MAP[finalLabel] || '';
      if (!value) {
        stat.unmappedLabel++;
        Logger.log('[TW] 辞書未収録のためスキップ: twId=' + twId + ' label=[' + finalLabel + ']');
      }
    }

    var adType = ga4 ? ga4.adType : '';

    if (!value && !adType) return;
    resolved[twId] = { value: value, adType: adType, labelForLog: finalLabel };
  });

  return resolved;
}


function twLoadSfContactsByTwId_(twIds) {
  var sf = getSfToken_();
  var wantSet = {};
  twIds.forEach(function (id) { wantSet[id] = true; });

  var soql = 'SELECT Id, ' + TW_CONFIG.SF_ID_FIELD + ', ' +
    TW_CONFIG.SF_MEDIUM_FIELD + ', ' + TW_CONFIG.SF_ADTYPE_FIELD + ', ' + TW_CONFIG.SF_STATUS_FIELD +
    ' FROM Contact WHERE ' + TW_CONFIG.SF_ID_FIELD + ' != null';

  var records = omSoqlAll_(sf, soql);

  var byTwId = {};
  records.forEach(function (c) {
    var twId = String(c[TW_CONFIG.SF_ID_FIELD] || '').trim();
    if (!twId || !wantSet[twId]) return;
    if (!byTwId[twId]) byTwId[twId] = [];
    byTwId[twId].push(c);
  });

  return byTwId;
}


function twBatchPatchContacts_(updates) {
  var sf = getSfToken_();
  var result = { updated: 0, failed: 0, errors: [] };

  for (var i = 0; i < updates.length; i += TW_CONFIG.SF_WRITE_CHUNK) {
    var chunk = updates.slice(i, i + TW_CONFIG.SF_WRITE_CHUNK);
    var records = chunk.map(function (u) {
      var rec = { attributes: { type: 'Contact' }, Id: u.Id };
      Object.assign(rec, u.fields);
      return rec;
    });

    var url = sf.instance_url + '/services/data/' + TW_CONFIG.SF_API_VERSION + '/composite/sobjects';
    var res = UrlFetchApp.fetch(url, {
      method: 'patch',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + sf.access_token },
      payload: JSON.stringify({ allOrNone: false, records: records }),
      muteHttpExceptions: true,
    });

    var body = JSON.parse(res.getContentText() || '[]');
    body.forEach(function (r, idx) {
      if (r.success) {
        result.updated++;
      } else {
        result.failed++;
        var msg = (r.errors && r.errors.length) ? r.errors.map(function (e) { return e.message; }).join('; ') : 'unknown';
        result.errors.push({ Id: chunk[idx].Id, message: msg });
      }
    });
  }

  return result;
}


function twAppendLog_(logRows, stat) {
  var ss = SpreadsheetApp.openById(TW_CONFIG.LOG_SHEET_SPREADSHEET_ID);
  var sh = ss.getSheetByName(TW_CONFIG.LOG_SHEET);
  if (!sh) {
    sh = ss.insertSheet(TW_CONFIG.LOG_SHEET);
    sh.appendRow(['実行日時', 'トヨワクID', 'ContactId', '書いた参照元メディア', '書いた広告タイプ', '結果']);
  }

  var CHUNK_SIZE = 500;
  var writtenRows = 0, failedChunks = 0;
  for (var i = 0; i < logRows.length; i += CHUNK_SIZE) {
    var chunk = logRows.slice(i, i + CHUNK_SIZE);
    try {
      sh.getRange(sh.getLastRow() + 1, 1, chunk.length, chunk[0].length).setValues(chunk);
      writtenRows += chunk.length;
    } catch (e) {
      failedChunks++;
      Logger.log('⚠️ ログ書き込み失敗（chunk開始index=' + i + '、' + chunk.length + '行）: ' + e);
    }
    if (i + CHUNK_SIZE < logRows.length) Utilities.sleep(300);
  }
  if (failedChunks) {
    Logger.log('⚠️ ログ書き込み: ' + writtenRows + '/' + logRows.length + '行 成功、' + failedChunks + 'チャンク失敗');
  }

  var summarySheet = ss.getSheetByName('_tw_media_log_summary') || ss.insertSheet('_tw_media_log_summary');
  if (summarySheet.getLastRow() === 0) {
    summarySheet.appendRow(['実行日時', 'GA4総行数', 'GA4有効ID数', 'Indeed総行数', 'Indeed有効ID数',
      '対象ID数', '辞書未収録', 'SF不一致', '既存値あり(スキップ)', '更新対象Contact数', '成功', '失敗', 'DRY_RUN']);
  }
  summarySheet.appendRow([new Date(), stat.ga4Rows, stat.ga4ValidId, stat.indeedRows, stat.indeedValidId,
    stat.candidates, stat.unmappedLabel, stat.noSfMatch, stat.alreadySet, stat.willUpdateContacts,
    stat.updated, stat.failed, TW_CONFIG.DRY_RUN]);
}


function twNotifyFailuresIfAny_(stat) {
  if (TW_CONFIG.DRY_RUN) return;
  if (!stat.failed) return;

  try {
    var url = PropertiesService.getScriptProperties().getProperty(TW_CONFIG.SLACK_WEBHOOK_PROP);
    if (!url) {
      Logger.log('⚠️ SLACK_WEBHOOK_URL未設定のためSlack通知をスキップ（失敗件数=' + stat.failed + '）');
      return;
    }
    var text = '⚠️ TwMediaSync: 本日の実行で ' + stat.failed + ' 件が更新に失敗しました。' +
      '（更新対象=' + stat.willUpdateContacts + ' 成功=' + stat.updated + '）' +
      ' 詳細はログSS「TW参照元メディア連携ログ」の_tw_media_logシートを確認してください。';
    UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ text: text }),
      muteHttpExceptions: true,
    });
  } catch (e) {
    Logger.log('⚠️ Slack通知失敗（無視して継続）: ' + e);
  }
}


function twReportHeartbeatSafe_() {
  try {
    if (typeof reportHeartbeat_ === 'function') reportHeartbeat_('TW参照元メディア連携/twSyncMediaFields');
  } catch (e) {
    Logger.log('⚠️ heartbeat報告失敗（無視して継続）: ' + e);
  }
}


function twColLetterToIndex_(letter) {
  var s = String(letter).toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
  return n - 1;
}

function twNormalizeDateKey_(raw) {
  if (!raw) return '';
  if (Object.prototype.toString.call(raw) === '[object Date]') {
    return Utilities.formatDate(raw, 'Asia/Tokyo', 'yyyyMMdd');
  }
  var s = String(raw).trim().replace(/[^\d]/g, '');
  return s || '';
}


function twSetupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'twSyncMediaFields') ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('twSyncMediaFields')
    .timeBased()
    .atHour(10)
    .everyDays(1)
    .inTimezone('Asia/Tokyo')
    .create();

  Logger.log('トリガー設置完了: twSyncMediaFields 毎日10時台 JST');
}


function twTestSfConnection() {
  var sf = getSfToken_();
  Logger.log('[TEST] instance_url=' + sf.instance_url + ' token取得OK');
}

// 置き換え後に最初に手動実行する。列位置と辞書の当たり具合をログに出すだけで、SFには書かない。
function twTestDictionaryCoverage() {
  var stat = { ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0 };
  var ga4Map = twLoadGa4Map_(stat);

  var labelCounts = {};
  Object.keys(ga4Map).forEach(function (id) {
    var label = ga4Map[id].label;
    labelCounts[label] = (labelCounts[label] || 0) + 1;
  });

  Logger.log('[TEST] GA4行=' + stat.ga4Rows + ' 有効ID=' + stat.ga4ValidId);
  Object.keys(labelCounts).sort().forEach(function (label) {
    var mapped = TW_MEDIUM_VALUE_MAP[label] || TW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0;
    Logger.log('  [' + label + '] × ' + labelCounts[label] + (mapped ? '' : '  ⚠️辞書未収録'));
  });
}
