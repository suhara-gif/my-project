// ==========================================================
// CW参照元メディア SF日次連携 v2.1 (2026-10-09)
//
// 【v2.1 2026-10-09】
//  - 「流入後突合cw」の参照元メディア列を、列の文字(固定)ではなく1行目の見出し「参照元メディア」で探す。
//    シートに列を足しても追従する（流入後突合cwでは「流入日」列の追加で参照元メディアがO→P列にずれ、
//    O列の日付を読んで全件「辞書未収録」スキップ→9/24以降の新規が空欄のままだった）。
//  - 会員ID(B)・日付(A)は IMPORTRANGE 由来で見出しが無いため列固定のまま。
//  - 次の場合は黙って「完了」にせずエラーで止める: 見出しが見つからない / 参照元メディア列に日付が
//    入っている / 有効IDが0件 / 参照元メディアが1件も辞書に当たらない / SOQLがHTTPエラー・件数不一致。
//  - それ以外のロジック（空欄のみ書く・コンタクト状況未設定はスキップ等）は v2.0 と同じ。
//
// ---- 以下 v2.0 ----
// CW参照元メディア SF日次連携 v2.0（2026-09-20）
//
// 追加先: Apps Script プロジェクト「【応募者リスト】indeed直接募集_オウンドメディア→SF 簡易自動登録」
//         （オーナー: ahr info）に本ファイルを新規追加。他ファイルは無変更。
// 前提: 同プロジェクトに SF_Auth.gs の getSfToken_()、OwnedMedia_SF_Sync.gs の omSoqlAll_() /
//       reportHeartbeat_() が存在すること（TwMediaSync.gsと同一GASプロジェクト内での運用を想定）
//
// 目的: 流入経路別の「決まりやすさ」を見るため、Contact の
//       sourceMedium_j_cw__c（【メディア】参照元メディア_cw）を日次で埋める。
//       突合キーは ManagementCarwakuId_del__c（【管理】カーワクID）。
//       新規Contactは絶対に作らない。既存の1項目更新のみ。
//
// 【2026-09-20 v2.0で訂正】v1.0のコメントで「TWと同型の変換済みラベル列を持つ突合シートが
// 見つからなかった」としていたのは誤り。須原さんの指摘で再調査した結果、TWの「流入後突合tw」
// と同じスプレッドシート（1hf0NeZIlB_1RvMut1it1bfDk9HZBv9N0EM-m19KaRZ4）内に「流入後突合cw」
// タブが実在し、TWと全く同じ二段変換（生sourceMedium→シート側の数式でラベル変換→GASの辞書で
// SF API値へ変換）が既に構築済みであることをスプレッドシートを直接開いて確認した。v1.0は
// 別スプレッドシート（SS_GA4連携）の生GA4データを自前の正規表現辞書で変換する設計だったが、
// v2.0でTwMediaSync.gs本番稼働コードと同じ「流入後突合cw」参照方式に作り直した。
//
// この訂正により、v1.0時点で「google / organic 等はSFピックリストに該当値が無く須原さんの
// picklist新設判断が必要」と報告した結論も撤回する。実際は「流入後突合cw」のO列側の数式が
// google / organic 等を「オーガニック」ラベルに変換済みで、TW本番と同じ辞書
// （CW_MEDIUM_VALUE_MAP、'オーガニック' → 'chatgpt.com / (not set)'）で解決できる。
// picklist新設は不要。
//
// ソース①: SS 1hf0NeZIlB_1RvMut1it1bfDk9HZBv9N0EM-m19KaRZ4 / シート「流入後突合cw」
//          A=日付(YYYYMMDD相当) ／B=cw会員ID ／O=参照元メディア（シート側で変換済みラベル）
//          （2026-09-20 実データをgviz経由で確認: F列以降にID登録日/レギュ/資格/…/流入日/
//          参照元メディア(O)/type(P)の列があり、TWの「流入後突合tw」と同じ列位置。A〜E列は
//          生GA4データのミラー領域でヘッダーラベルなし。B列（会員ID）の直近データでの実際の
//          充足率は[要確認]。cwTestDictionaryCoverage()の実行結果（GA4行数/有効ID数）で
//          都度確認すること）
// ソース②: SS 1OfSiE6lRjYB1nsKNLVUV3DPDgQlgQPufBgrowwuJuR8 / シート「indeed_entry_cw」
//          （Indeedならメディア=Indeed）
//          【2026-09-19 第三者検証で判明・修正済み】indeed_entry_cwの列構成は tw版
//          （indeed_entry_tw、W=登録元システム）と異なり、AE=登録元システン。B/Wのハード
//          コードは廃止し、ヘッダー行（1行目）から「ユーザーID」「登録元システム」という
//          文字列を実行時に検索して列位置を特定する方式にしている（INDEED_HEADER設定・
//          cwFindHeaderCol_）。実データでA1=ユーザーID、AE1=登録元システムと確認済み。
//
// 統合ルール（TWと同じ方針を踏襲、2026-09-19 須原さん承認、v2.0でも変更なし）:
// 1) 参照元メディアは初回流入で固定（同一IDが複数行あればA列=日付が最も早い行を採用）
// 2) GA4優先。GA4側のラベルが「その他/不明分/(direct) / (none)/空」のときだけIndeedで上書き
// 3) SF側のsourceMedium_j_cw__cが空のときだけ書く（値がある行は上書きせずログに記録するだけ）
// 4) カーワクID重複（同一IDで複数Contact、実測33件）は該当する全レコードを更新
// 5) IscContactStatusSelection__c（【IS】コンタクト状況（選択））が空のContactは、TWで9日間
//    58件が失敗し続けた教訓を踏まえ、最初から対象外スキップにする（実測: カーワクID保有
//    33,453件中2,738件が該当）
//
// 広告タイプ（media_ad_type_cw__c 相当）のSalesforceフィールドは存在しないため、
// 参照元メディアのみを書き込む（2026-09-19 須原さん承認・Phase1、v2.0でも変更なし）。
//
// 参照元メディアは選択リストで、画面ラベルとAPI保存値が別物。辞書は sourceMedium_j_tw__c /
// sourceMedium_j_mw__c / sourceMedium_j_cw__c の3項目で選択肢が完全一致することを
// 2026-09-19にスキーマで確認済み。CW_MEDIUM_VALUE_MAPはTW_MEDIUM_VALUE_MAPと同一内容。
//
// 実書き込みテストは夜間窓の外=10:00〜19:00 JST のみで行う（既存の再発防止ルール踏襲）。
//
// 【2026-09-19時点で判明・今回は対処なし・v2.0でも未対応】SS_GA4連携の cw_会員id タブ自体
// （流入後突合cwの生データ元）が10,650件中10,000件しか取得できておらず650行が欠損している
// 可能性がある（Report ConfigurationのLimitが1000のままなのに実際は10,000件取得できており
// 不整合）。今回のタスク範囲外のため対処しない。別途対応が必要な既知の課題として記録。
// ==========================================================


// ---------- 設定 ----------
var CW_CONFIG = {
  SF_API_VERSION: 'v60.0',

  GA4_SHEET_ID: '1hf0NeZIlB_1RvMut1it1bfDk9HZBv9N0EM-m19KaRZ4',
  GA4_SHEET_NAME: '流入後突合cw',
  GA4_COL: { id: 'B', date: 'A' },
  // 参照元メディア列は1行目の見出しで探す（v2.1）。見出し名を変えたらここに足す。
  GA4_HEADERS: { medium: ['参照元メディア'] },

  INDEED_SHEET_ID: '1OfSiE6lRjYB1nsKNLVUV3DPDgQlgQPufBgrowwuJuR8',
  INDEED_SHEET_NAME: 'indeed_entry_cw',
  // 列文字のハードコードは廃止。ヘッダー行の見出し文字列で動的に列を特定する（下記参照）。
  INDEED_HEADER: { id: 'ユーザーID', system: '登録元システム' },

  LOG_SHEET: '_cw_media_log',
  LOG_SHEET_SPREADSHEET_ID: '1hUCLntzNBavn8AcJMwyL6GJ4ME8YZuFRRHeYVohWLcU',
  DRY_RUN: false,
  SF_WRITE_CHUNK: 200,
  SF_ID_FIELD: 'ManagementCarwakuId_del__c',
  SF_MEDIUM_FIELD: 'sourceMedium_j_cw__c',
  SF_STATUS_FIELD: 'IscContactStatusSelection__c',

  SLACK_WEBHOOK_PROP: 'SLACK_WEBHOOK_URL',

  // 「流入後突合cw」のO列（参照元メディアラベル）がこれらの値のときはGA4側を「その他/不明」
  // とみなし、Indeedからの流入が確認できればIndeedで上書きする（TW_CONFIG.FALLBACK_LABELSと同一）。
  FALLBACK_LABELS: ['その他', '不明分', '(direct) / (none)', ''],
};

// 「流入後突合cw」O列のラベル → SF書き込み値。
// TwMediaSync.gs本番稼働中のTW_MEDIUM_VALUE_MAPと同一内容
// （sourceMedium_j_cw__c / _mw__c / _tw__c のピックリスト選択肢が完全一致するため）。
var CW_MEDIUM_VALUE_MAP = {
  'google': 'google / cpc',
  'indeed': 'Indeed / cpc',
  'Indeed': 'Indeed / cpc',
  'line': 'line',
  'meta': 'meta / cpc',
  'yahoo': 'yahoo / cpc',
  'アフィリエイト': 'アフィリエイト',
  // 2026-09-24 須原さん判断で一時除外: 選択リストのラベル「オーガニック」の保存値が
  // 'chatgpt.com / (not set)' という設定ミスのままなため、誤った値を書き込まないよう
  // 辞書から外してある（該当行は「辞書未収録」としてスキップ・ログに残る）。
  // SF側の選択リスト値を修正したら、正しい値でこの行を復活させること。
  'スタンバイ': 'stanby / cpc',
  'スタンバイリファラル': 'スタンバイリファラル',
  'その他': '(direct) / (none)',
  '不明分': '(direct) / (none)',
  '求人BOX': 'kbox / cpc',
  '求人Boxリファラル': '求人ボックス.com / referral',
  'Yahoo!オーガニック': 'yahoo / organic',
  'CWコラム': 'carworkassist / column_banner',
};


function cwSyncMediaFields() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) { Logger.log('⚠️ 別プロセス実行中のためスキップ'); return; }

  try {
    var stat = {
      ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0,
      candidates: 0, unmappedLabel: 0, noSfMatch: 0, alreadySet: 0,
      statusBlocked: 0,
      willUpdateContacts: 0, updated: 0, failed: 0,
    };

    var ga4Map = cwLoadGa4Map_(stat);
    var indeedSet = cwLoadIndeedSet_(stat);

    var resolved = cwResolveMedia_(ga4Map, indeedSet, stat);
    stat.candidates = Object.keys(resolved).length;

    if (!stat.candidates) {
      Logger.log('[CW] 対象カーワクIDなし。GA4=' + stat.ga4ValidId + ' / Indeed=' + stat.indeedValidId);
      cwReportHeartbeatSafe_();
      return;
    }

    var sfByCwId = cwLoadSfContactsByCwId_(Object.keys(resolved));

    var logRows = [];
    var updates = [];

    Object.keys(resolved).forEach(function (cwId) {
      var r = resolved[cwId];
      var contacts = sfByCwId[cwId];

      if (!contacts || !contacts.length) {
        stat.noSfMatch++;
        logRows.push([new Date(), cwId, '', '', 'skip:SF側に該当Contactなし']);
        return;
      }

      contacts.forEach(function (c) {
        if (!String(c[CW_CONFIG.SF_STATUS_FIELD] || '').trim()) {
          stat.statusBlocked++;
          logRows.push([new Date(), cwId, c.Id, r.value || '',
            'skip:コンタクト状況(選択)未設定のため対象外(埋まれば次回以降で自動的に対象復帰)']);
          return;
        }

        var curMedium = String(c[CW_CONFIG.SF_MEDIUM_FIELD] || '').trim();

        if (!r.value || curMedium) {
          stat.alreadySet++;
          logRows.push([new Date(), cwId, c.Id, r.value || '',
            curMedium ? 'skip:既存値あり(上書きしない)' : 'skip:書き込み値なし']);
          return;
        }

        var fields = {};
        fields[CW_CONFIG.SF_MEDIUM_FIELD] = r.value;

        stat.willUpdateContacts++;
        updates.push({ Id: c.Id, fields: fields });
        logRows.push([new Date(), cwId, c.Id, r.value, CW_CONFIG.DRY_RUN ? 'DRY:書込予定' : '']);
      });
    });

    Logger.log('[CW] GA4行=' + stat.ga4Rows + '/有効ID=' + stat.ga4ValidId +
      ' Indeed行=' + stat.indeedRows + '/有効ID=' + stat.indeedValidId +
      ' 対象ID=' + stat.candidates + ' 辞書未収録=' + stat.unmappedLabel +
      ' SF不一致=' + stat.noSfMatch + ' 既存値あり=' + stat.alreadySet +
      ' コンタクト状況未設定=' + stat.statusBlocked +
      ' 更新対象Contact=' + stat.willUpdateContacts);

    if (!CW_CONFIG.DRY_RUN && updates.length) {
      var result = cwBatchPatchContacts_(updates);
      stat.updated = result.updated;
      stat.failed = result.failed;
      result.errors.forEach(function (e) {
        logRows.push([new Date(), '', e.Id, '', 'error:' + e.message]);
      });
    }

    cwAppendLog_(logRows, stat);
    Logger.log((CW_CONFIG.DRY_RUN ? '[DRY] ' : '') + '完了: 更新対象=' + stat.willUpdateContacts +
      ' 成功=' + stat.updated + ' 失敗=' + stat.failed + ' コンタクト状況未設定で対象外=' + stat.statusBlocked);
    cwNotifyFailuresIfAny_(stat);
    cwReportHeartbeatSafe_();

  } finally {
    lock.releaseLock();
  }
}


// 「流入後突合cw」から 会員ID → {label, date} のマップを作る。
// TwMediaSync.gsのtwLoadGa4Map_と同じ方式: ヘッダー行の有無に依存せず、A列（会員ID）が
// 数字のみの行だけを有効データとして扱う（アドオンのプリアンブル行や見出し行は
// 数字IDではないため自然に除外される）。
function cwLoadGa4Map_(stat) {
  var ss = SpreadsheetApp.openById(CW_CONFIG.GA4_SHEET_ID);
  var sheet = ss.getSheetByName(CW_CONFIG.GA4_SHEET_NAME);
  if (!sheet) throw new Error('シート未検出: ' + CW_CONFIG.GA4_SHEET_NAME);

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  var idCol = cwColLetterToIndex_(CW_CONFIG.GA4_COL.id);
  var mediumCol = cwFindCol_(values[0], CW_CONFIG.GA4_HEADERS.medium, 'medium');
  var dateCol = cwColLetterToIndex_(CW_CONFIG.GA4_COL.date);

  var map = {};

  for (var r = 1; r < values.length; r++) {
    stat.ga4Rows++;
    var row = values[r];
    var cwId = String(row[idCol] || '').trim();
    if (!cwId || cwId === '(not set)' || !/^\d+$/.test(cwId)) continue;

    stat.ga4ValidId++;
    var mediumRaw = row[mediumCol];
    if (Object.prototype.toString.call(mediumRaw) === '[object Date]') {
      throw new Error('流入後突合cw の参照元メディア列(' + (mediumCol + 1) + '列目)に日付が入っています（' +
        (r + 1) + '行目）。列ずれの可能性があるため中止しました。');
    }
    var label = String(mediumRaw || '').trim();
    var dateRaw = row[dateCol];
    var dateKey = cwNormalizeDateKey_(dateRaw);

    var existing = map[cwId];
    if (!existing || (dateKey && (!existing.date || dateKey < existing.date))) {
      map[cwId] = { label: label, date: dateKey };
    }
  }

  if (!stat.ga4ValidId) {
    throw new Error('流入後突合cw のB列に有効な会員IDが1件もありません（行数=' + (values.length - 1) +
      '）。IMPORTRANGE の参照切れや列ずれの可能性があるため中止しました。');
  }
  cwAssertMediumMapped_(map);
  return map;
}


// 見出し行から候補名に一致する列(0始まり)を返す。見つからなければ中止する。
function cwFindCol_(header, candidates, key) {
  var norm = header.map(function (h) { return String(h || '').trim(); });
  for (var i = 0; i < candidates.length; i++) {
    var idx = norm.indexOf(candidates[i]);
    if (idx >= 0) return idx;
  }
  throw new Error('流入後突合cw の見出しに「' + candidates.join(' / ') + '」(' + key + ') が見つかりません。' +
    '見出し行: [' + norm.join(' | ') + ']。CW_CONFIG.GA4_HEADERS に今の見出し名を足してください。');
}


// 参照元メディアが1件も辞書に当たらなければ列ずれとみなして中止する。
function cwAssertMediumMapped_(ga4Map) {
  var ids = Object.keys(ga4Map);
  if (!ids.length) return;
  var hit = 0;
  for (var i = 0; i < ids.length; i++) {
    var label = ga4Map[ids[i]].label;
    if (CW_MEDIUM_VALUE_MAP[label] || CW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0) hit++;
  }
  if (!hit) {
    throw new Error('流入後突合cw の参照元メディアが ' + ids.length + ' 件すべて辞書に当たりません。' +
      '列ずれか見出しの変更の可能性があるため中止しました。');
  }
}


function cwLoadIndeedSet_(stat) {
  var ss = SpreadsheetApp.openById(CW_CONFIG.INDEED_SHEET_ID);
  var sheet = ss.getSheetByName(CW_CONFIG.INDEED_SHEET_NAME);
  if (!sheet) throw new Error('シート未検出: ' + CW_CONFIG.INDEED_SHEET_NAME);

  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return {};

  var header = values[0];
  var idCol = cwFindHeaderCol_(header, CW_CONFIG.INDEED_HEADER.id);
  var sysCol = cwFindHeaderCol_(header, CW_CONFIG.INDEED_HEADER.system);

  var set = {};

  for (var r = 1; r < values.length; r++) {
    stat.indeedRows++;
    var row = values[r];
    var cwId = String(row[idCol] || '').trim();
    if (!cwId || !/^\d+$/.test(cwId)) continue;

    var sys = String(row[sysCol] || '').trim();
    if (sys !== 'Indeed') continue;

    stat.indeedValidId++;
    set[cwId] = true;
  }

  return set;
}


// GA4側ラベルとIndeed流入フラグから、統合ルールに従って最終的なSF書き込み値を決める。
// TwMediaSync.gsのtwResolveMedia_と同じロジック。
function cwResolveMedia_(ga4Map, indeedSet, stat) {
  var resolved = {};
  var allIds = {};
  Object.keys(ga4Map).forEach(function (id) { allIds[id] = true; });
  Object.keys(indeedSet).forEach(function (id) { allIds[id] = true; });

  Object.keys(allIds).forEach(function (cwId) {
    var ga4 = ga4Map[cwId];
    var fromIndeed = !!indeedSet[cwId];

    var label = ga4 ? ga4.label : '';
    var isFallback = CW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0;

    var finalLabel = label;
    if ((!label || isFallback) && fromIndeed) finalLabel = 'Indeed';

    var value = '';
    if (finalLabel) {
      value = CW_MEDIUM_VALUE_MAP[finalLabel] || '';
      if (!value) {
        stat.unmappedLabel++;
        Logger.log('[CW] 辞書未収録のためスキップ: cwId=' + cwId + ' label=[' + finalLabel + ']');
      }
    }

    if (!value) return;
    resolved[cwId] = { value: value, labelForLog: finalLabel };
  });

  return resolved;
}


function cwLoadSfContactsByCwId_(cwIds) {
  var sf = getSfToken_();
  var wantSet = {};
  cwIds.forEach(function (id) { wantSet[id] = true; });

  var soql = 'SELECT Id, ' + CW_CONFIG.SF_ID_FIELD + ', ' +
    CW_CONFIG.SF_MEDIUM_FIELD + ', ' + CW_CONFIG.SF_STATUS_FIELD +
    ' FROM Contact WHERE ' + CW_CONFIG.SF_ID_FIELD + ' != null' +
    ' ORDER BY Id';

  // 2026-09-24: omSoqlAll_()はページング非対応のため cwSoqlAll_() を使う
  var records = cwSoqlAll_(sf, soql);

  var byCwId = {};
  records.forEach(function (c) {
    var cwId = String(c[CW_CONFIG.SF_ID_FIELD] || '').trim();
    if (!cwId || !wantSet[cwId]) return;
    if (!byCwId[cwId]) byCwId[cwId] = [];
    byCwId[cwId].push(c);
  });

  return byCwId;
}


// 2026-09-24 追加: Salesforce REST /query API のページング（nextRecordsUrl）対応版SOQL全件取得。
// TwMediaSync.gs の twSoqlAll_() と同等。共有関数 omSoqlAll_()（OwnedMedia_SF_Sync.gs）は
// 他の呼び出し元への影響を避けるため変更せず、本ファイル専用に新設した。
function cwSoqlAll_(sf, soql) {
  // v2.1: HTTPエラー時は途中までの結果を返さず中止する。totalSize と取得件数の一致も確認する。
  var records = [];
  var totalSize = null;
  var page = 0;
  var url = sf.instance_url + '/services/data/' + CW_CONFIG.SF_API_VERSION + '/query?q=' + encodeURIComponent(soql);

  while (url) {
    page++;
    var res = UrlFetchApp.fetch(url, {
      headers: { Authorization: 'Bearer ' + sf.access_token },
      muteHttpExceptions: true,
    });

    var code = res.getResponseCode();
    var text = res.getContentText() || '';
    if (code !== 200) {
      throw new Error('SOQL取得失敗(' + page + 'ページ目, HTTP ' + code + '): ' + text.slice(0, 300));
    }

    var body = JSON.parse(text || '{}');
    if (totalSize === null) totalSize = body.totalSize;
    records = records.concat(body.records || []);

    url = (!body.done && body.nextRecordsUrl)
      ? sf.instance_url + body.nextRecordsUrl
      : null;
  }

  if (totalSize !== null && records.length !== totalSize) {
    throw new Error('SOQL取得件数が合いません: 取得=' + records.length + ' / totalSize=' + totalSize + '（' + page + 'ページ）');
  }
  Logger.log('[CW] SF取得件数=' + records.length + '（' + page + 'ページ）');
  return records;
}

function cwBatchPatchContacts_(updates) {
  var sf = getSfToken_();
  var result = { updated: 0, failed: 0, errors: [] };

  for (var i = 0; i < updates.length; i += CW_CONFIG.SF_WRITE_CHUNK) {
    var chunk = updates.slice(i, i + CW_CONFIG.SF_WRITE_CHUNK);
    var records = chunk.map(function (u) {
      var rec = { attributes: { type: 'Contact' }, Id: u.Id };
      Object.assign(rec, u.fields);
      return rec;
    });

    var url = sf.instance_url + '/services/data/' + CW_CONFIG.SF_API_VERSION + '/composite/sobjects';
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


function cwAppendLog_(logRows, stat) {
  var ss = SpreadsheetApp.openById(CW_CONFIG.LOG_SHEET_SPREADSHEET_ID);
  var sh = ss.getSheetByName(CW_CONFIG.LOG_SHEET);
  if (!sh) {
    sh = ss.insertSheet(CW_CONFIG.LOG_SHEET);
    sh.appendRow(['実行日時', 'カーワクID', 'ContactId', '書いた参照元メディア', '結果']);
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

  var summarySheet = ss.getSheetByName('_cw_media_log_summary') || ss.insertSheet('_cw_media_log_summary');
  if (summarySheet.getLastRow() === 0) {
    summarySheet.appendRow(['実行日時', 'GA4総行数', 'GA4有効ID数', 'Indeed総行数', 'Indeed有効ID数',
      '対象ID数', '辞書未収録', 'SF不一致', '既存値あり(スキップ)', '更新対象Contact数', '成功', '失敗', 'DRY_RUN']);
  }
  summarySheet.appendRow([new Date(), stat.ga4Rows, stat.ga4ValidId, stat.indeedRows, stat.indeedValidId,
    stat.candidates, stat.unmappedLabel, stat.noSfMatch, stat.alreadySet, stat.willUpdateContacts,
    stat.updated, stat.failed, CW_CONFIG.DRY_RUN]);
}


function cwNotifyFailuresIfAny_(stat) {
  if (CW_CONFIG.DRY_RUN) return;
  if (!stat.failed) return;

  try {
    var url = PropertiesService.getScriptProperties().getProperty(CW_CONFIG.SLACK_WEBHOOK_PROP);
    if (!url) {
      Logger.log('⚠️ SLACK_WEBHOOK_URL未設定のためSlack通知をスキップ（失敗件数=' + stat.failed + '）');
      return;
    }
    var text = '⚠️ CwMediaSync: 本日の実行で ' + stat.failed + ' 件が更新に失敗しました。' +
      '（更新対象=' + stat.willUpdateContacts + ' 成功=' + stat.updated + '）' +
      ' 詳細はログSS「CW参照元メディア連携ログ」の_cw_media_logシートを確認してください。';
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


function cwReportHeartbeatSafe_() {
  try {
    if (typeof reportHeartbeat_ === 'function') reportHeartbeat_('CW参照元メディア連携/cwSyncMediaFields');
  } catch (e) {
    Logger.log('⚠️ heartbeat報告失敗（無視して継続）: ' + e);
  }
}


function cwColLetterToIndex_(letter) {
  var s = String(letter).toUpperCase();
  var n = 0;
  for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
  return n - 1;
}

// ヘッダー行（配列）から見出し文字列に完全一致する列のインデックス(0始まり)を返す。
// 見つからなければ即エラー（indeed_entry_cwの列構成が想定と違う場合、黙って誤った列を
// 読むのではなくここで実行を止めて気づけるようにするための安全装置）。
function cwFindHeaderCol_(header, name) {
  for (var i = 0; i < header.length; i++) {
    if (String(header[i]).trim() === name) return i;
  }
  throw new Error('ヘッダー列未検出: "' + name + '"（シート:' + CW_CONFIG.INDEED_SHEET_NAME +
    '）。列構成が想定と異なる可能性があります。シートを直接確認してください。');
}

function cwNormalizeDateKey_(raw) {
  if (!raw) return '';
  if (Object.prototype.toString.call(raw) === '[object Date]') {
    return Utilities.formatDate(raw, 'Asia/Tokyo', 'yyyyMMdd');
  }
  var s = String(raw).trim().replace(/[^\d]/g, '');
  return s || '';
}


function cwSetupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'cwSyncMediaFields') ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger('cwSyncMediaFields')
    .timeBased()
    .atHour(10)
    .everyDays(1)
    .inTimezone('Asia/Tokyo')
    .create();

  Logger.log('トリガー設置完了: cwSyncMediaFields 毎日10時台 JST');
}


function cwTestSfConnection() {
  var sf = getSfToken_();
  Logger.log('[TEST] instance_url=' + sf.instance_url + ' token取得OK');
}

// 本番投入前に必ず最初に実行すること。
// 「流入後突合cw」のO列（参照元メディアラベル）に実際どんな値が入っているかを集計し、
// CW_MEDIUM_VALUE_MAPでカバーできているかを一覧表示する。辞書未収録が多ければ
// マップを追加してから改めてDRY_RUNに進む。
function cwTestDictionaryCoverage() {
  var stat = { ga4Rows: 0, ga4ValidId: 0 };
  var ga4Map = cwLoadGa4Map_(stat);

  var labelCounts = {};
  Object.keys(ga4Map).forEach(function (id) {
    var label = ga4Map[id].label;
    labelCounts[label] = (labelCounts[label] || 0) + 1;
  });

  Logger.log('[TEST] GA4行=' + stat.ga4Rows + ' 有効ID=' + stat.ga4ValidId);
  Object.keys(labelCounts).sort(function (a, b) { return labelCounts[b] - labelCounts[a]; }).forEach(function (label) {
    var mapped = CW_MEDIUM_VALUE_MAP[label] || CW_CONFIG.FALLBACK_LABELS.indexOf(label) >= 0;
    Logger.log('  [' + label + '] × ' + labelCounts[label] + (mapped ? '' : '  ⚠️辞書未収録'));
  });
}

// 2026-09-24 追加（ドライラン専用）: 書き込みもログSSへの追記も一切行わず、
// 対象件数 / 一致件数 / 書き込み予定件数 だけをログに出す。
function cwDryRunCounts() {
  var t0 = new Date().getTime();
  var stat = { ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0, unmappedLabel: 0 };
  var ga4Map = cwLoadGa4Map_(stat);
  var indeedSet = cwLoadIndeedSet_(stat);
  var resolved = cwResolveMedia_(ga4Map, indeedSet, stat);
  var ids = Object.keys(resolved);
  var tSrc = (new Date().getTime() - t0) / 1000;

  var sf = getSfToken_();
  var soql = 'SELECT Id, ' + CW_CONFIG.SF_ID_FIELD + ', ' +
    CW_CONFIG.SF_MEDIUM_FIELD + ', ' + CW_CONFIG.SF_STATUS_FIELD +
    ' FROM Contact WHERE ' + CW_CONFIG.SF_ID_FIELD + ' != null' +
    ' ORDER BY Id';
  var records = cwSoqlAll_(sf, soql);
  var tSf = (new Date().getTime() - t0) / 1000;

  var wantSet = {};
  ids.forEach(function (id) { wantSet[id] = true; });
  var matched = 0, noSfMatch = 0, statusBlocked = 0, alreadySet = 0, willUpdate = 0;
  var byId = {};
  records.forEach(function (c) {
    var k = String(c[CW_CONFIG.SF_ID_FIELD] || '').trim();
    if (!k || !wantSet[k]) return;
    if (!byId[k]) byId[k] = [];
    byId[k].push(c);
  });
  ids.forEach(function (k) {
    var cs = byId[k];
    if (!cs || !cs.length) { noSfMatch++; return; }
    matched++;
    cs.forEach(function (c) {
      if (!String(c[CW_CONFIG.SF_STATUS_FIELD] || '').trim()) { statusBlocked++; return; }
      if (String(c[CW_CONFIG.SF_MEDIUM_FIELD] || '').trim()) { alreadySet++; return; }
      willUpdate++;
    });
  });

  Logger.log('[CW-DRYRUN] SF全件取得=' + records.length +
    ' / 対象カーワクID数(GA4+Indeed由来)=' + ids.length +
    ' / 一致カーワクID数=' + matched +
    ' / SF不一致=' + noSfMatch +
    ' / コンタクト状況未設定で対象外=' + statusBlocked +
    ' / 既存値あり=' + alreadySet +
    ' / 書き込み予定=' + willUpdate +
    ' / 辞書未収録=' + stat.unmappedLabel +
    ' / 経過秒(シート)=' + tSrc.toFixed(1) + ' 経過秒(SF取得完)=' + tSf.toFixed(1) +
    ' 経過秒(全体)=' + ((new Date().getTime() - t0) / 1000).toFixed(1));
}


// ==========================================================
// 2026-09-24 追加: 初回バックフィル専用の分割実行関数。
// ・1回あたり最大 CW_BACKFILL_LIMIT 件だけ書き込む（6分上限対策）
// ・PATCHの前に「書き込み予定ContactId」を先にログSSへ残す（タイムアウト時の証跡確保）
// ・バッチ開始/終了マーカーを残す
// ・エラー率が5%を超えたらその時点で中断する
// 既存値を上書きしない設計のため冪等。途中で落ちても再実行すれば続きから進む。
// ==========================================================
var CW_BACKFILL_LIMIT = 3000;
var CW_BACKFILL_SHEET = '_cw_backfill_log';

function cwBackfillBatch() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) { Logger.log('⚠️ 別プロセス実行中のためスキップ'); return; }
  try {
    var t0 = new Date().getTime();
    var batchId = 'CWBF-' + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyyMMdd-HHmmss');
    var stat = { ga4Rows: 0, ga4ValidId: 0, indeedRows: 0, indeedValidId: 0, unmappedLabel: 0 };
    var resolved = cwResolveMedia_(cwLoadGa4Map_(stat), cwLoadIndeedSet_(stat), stat);
    var ids = Object.keys(resolved);

    var sf = getSfToken_();
    var soql = 'SELECT Id, ' + CW_CONFIG.SF_ID_FIELD + ', ' +
      CW_CONFIG.SF_MEDIUM_FIELD + ', ' + CW_CONFIG.SF_STATUS_FIELD +
      ' FROM Contact WHERE ' + CW_CONFIG.SF_ID_FIELD + ' != null' +
      ' ORDER BY Id';
    var records = cwSoqlAll_(sf, soql);

    var want = {};
    ids.forEach(function (k) { want[k] = true; });
    var byId = {};
    records.forEach(function (c) {
      var k = String(c[CW_CONFIG.SF_ID_FIELD] || '').trim();
      if (!k || !want[k]) return;
      if (!byId[k]) byId[k] = [];
      byId[k].push(c);
    });

    var updates = [];
    ids.forEach(function (k) {
      var cs = byId[k];
      if (!cs || !cs.length) return;
      var r = resolved[k];
      cs.forEach(function (c) {
        if (!String(c[CW_CONFIG.SF_STATUS_FIELD] || '').trim()) return;
        if (String(c[CW_CONFIG.SF_MEDIUM_FIELD] || '').trim()) return;
        var f = {};
        f[CW_CONFIG.SF_MEDIUM_FIELD] = r.value;
        updates.push({ Id: c.Id, key: k, value: r.value, fields: f });
      });
    });

    var remaining = updates.length;
    if (updates.length > CW_BACKFILL_LIMIT) updates = updates.slice(0, CW_BACKFILL_LIMIT);
    var tPrep = (new Date().getTime() - t0) / 1000;

    var sh = cwBackfillSheet_();
    sh.appendRow([new Date(), batchId, 'BATCH_START', '', '',
      '未書き込み残数=' + remaining + ' / 今回対象=' + updates.length +
      ' / 辞書未収録(除外)=' + stat.unmappedLabel + ' / 準備秒=' + tPrep.toFixed(1)]);
    SpreadsheetApp.flush();
    if (!updates.length) {
      sh.appendRow([new Date(), batchId, 'BATCH_END', '', '', '対象なし。バックフィル完了']);
      Logger.log('[CW-BACKFILL] ' + batchId + ' 対象なし。バックフィル完了');
      return;
    }

    cwBackfillWrite_(sh, updates.map(function (u) {
      return [new Date(), batchId, 'PLANNED', u.key, u.Id, u.value];
    }));

    var res = cwBackfillPatch_(sf, updates);

    cwBackfillWrite_(sh, res.rows.map(function (x) {
      return [new Date(), batchId, x.ok ? 'OK' : 'ERROR', x.key, x.Id, x.ok ? x.value : x.msg];
    }));

    var done = res.updated + res.failed;
    var rate = done ? (res.failed / done * 100) : 0;
    var sec = (new Date().getTime() - t0) / 1000;
    sh.appendRow([new Date(), batchId, 'BATCH_END', '', '',
      '成功=' + res.updated + ' / 失敗=' + res.failed + ' / エラー率=' + rate.toFixed(2) +
      '% / 5%超で中断=' + res.aborted + ' / 所要秒=' + sec.toFixed(1)]);
    SpreadsheetApp.flush();

    Logger.log('[CW-BACKFILL] ' + batchId +
      ' 未書き込み残数=' + remaining + ' 今回対象=' + updates.length +
      ' 成功=' + res.updated + ' 失敗=' + res.failed +
      ' エラー率=' + rate.toFixed(2) + '%' +
      ' 5%超で中断=' + res.aborted +
      ' 辞書未収録(除外)=' + stat.unmappedLabel +
      ' 準備秒=' + tPrep.toFixed(1) + ' 所要秒=' + sec.toFixed(1));
  } finally {
    lock.releaseLock();
  }
}

function cwBackfillPatch_(sf, updates) {
  var out = { updated: 0, failed: 0, aborted: false, rows: [] };
  for (var i = 0; i < updates.length; i += CW_CONFIG.SF_WRITE_CHUNK) {
    var chunk = updates.slice(i, i + CW_CONFIG.SF_WRITE_CHUNK);
    var recs = chunk.map(function (u) {
      var r = { attributes: { type: 'Contact' }, Id: u.Id };
      Object.assign(r, u.fields);
      return r;
    });
    var res = UrlFetchApp.fetch(sf.instance_url + '/services/data/' + CW_CONFIG.SF_API_VERSION + '/composite/sobjects', {
      method: 'patch',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + sf.access_token },
      payload: JSON.stringify({ allOrNone: false, records: recs }),
      muteHttpExceptions: true,
    });
    var body = JSON.parse(res.getContentText() || '[]');
    body.forEach(function (r, idx) {
      if (r.success) {
        out.updated++;
        out.rows.push({ ok: true, Id: chunk[idx].Id, key: chunk[idx].key, value: chunk[idx].value });
      } else {
        out.failed++;
        var m = (r.errors && r.errors.length) ? r.errors.map(function (e) { return e.message; }).join('; ') : 'unknown';
        out.rows.push({ ok: false, Id: chunk[idx].Id, key: chunk[idx].key, msg: m });
      }
    });
    var done = out.updated + out.failed;
    if (done >= 400 && (out.failed / done) > 0.05) { out.aborted = true; break; }
  }
  return out;
}

function cwBackfillSheet_() {
  var ss = SpreadsheetApp.openById(CW_CONFIG.LOG_SHEET_SPREADSHEET_ID);
  var sh = ss.getSheetByName(CW_BACKFILL_SHEET);
  if (!sh) {
    sh = ss.insertSheet(CW_BACKFILL_SHEET);
    sh.appendRow(['日時', 'バッチID', '区分', 'カーワクID', 'ContactId', '値 / メッセージ']);
  }
  return sh;
}

function cwBackfillWrite_(sh, rows) {
  var N = 500;
  for (var i = 0; i < rows.length; i += N) {
    var c = rows.slice(i, i + N);
    sh.getRange(sh.getLastRow() + 1, 1, c.length, 6).setValues(c);
    if (i + N < rows.length) Utilities.sleep(200);
  }
  SpreadsheetApp.flush();
}

