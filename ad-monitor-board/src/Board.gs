/**
 * 広告 監視ボード
 *
 * daily_summary(日次・媒体×サイト別の広告実績)の横に「監視ボード」シートを作り、
 * 媒体×サイトごとに「推移の折れ線」「昨日の値」「7日平均比」「空欄の連続日数」
 * 「整備士CPAの変化」「判定」を1行で並べる。
 *
 * - ボードの中身はすべて数式。buildMonitorBoard() を1回実行すれば、以後は daily_summary が
 *   更新されるたびに自動で再計算される(定期実行ジョブは作らない)。
 * - daily_summary には一切書き込まない(読み取りのみ)。
 * - 列は見出し名で参照する(MATCH)ため、daily_summary 側で列が挿入・移動されても壊れない。
 *   シート参照は INDIRECT にしてあり、集計ジョブがシートを消して作り直しても #REF! にならない。
 * - 「昨日」= 当日より前の最終行。集計途中の当日行は判定に使わない。
 *
 * - 既存の集計スクリプトと同じプロジェクトに置いても名前がぶつからないよう、グローバルな名前は
 *   すべて MB_ / mb 接頭辞にしている。onOpen も定義しない(既存の onOpen を上書きしないため)。
 *
 * セットアップは docs/setup.md を参照。
 */

var MB_CONFIG = {
  SOURCE_SHEET: 'daily_summary', // 元データのシート名
  BOARD_SHEET: '監視ボード', // 作成するシート名(同名があれば作り直す)
  DATE_COLUMN: 'A', // 日付が入っている列(2行目から日付が連続している前提)

  // 見出しの形: 「媒体_サイト_指標」(例: G_CW_費用)
  METRIC_COST: '費用',
  METRIC_CV: 'CV',
  METRIC_MECH: '整備士CV', // 整備士数の列の指標名。無い媒体×サイト(例: M_CW)は整備士系の欄が「—」になる

  MEDIA_NAMES: { G: 'Google', M: 'Meta', I: 'Indeed', Q: '求人BOX', S: 'スタンバイ' },

  SPARK_DAYS: 28, // 折れ線に出す日数
  RATIO_ALERT: 0.5, // 昨日費用が7日平均から ±50% 以上ずれたら要確認
  BLANK_ALERT_DAYS: 2, // 費用が末尾から何日続けて空欄なら要確認
  MECH_LAG_DAYS: 3, // 整備士数は確定が遅れるため、直近この日数は整備士CPAの計算から外す
  MECH_WINDOW_DAYS: 7, // 整備士CPAの「今」の集計日数
  MECH_BASE_DAYS: 14, // 整備士CPAの「比較基準」の集計日数(今の窓の直前)。daily_summary は直近約31日分しか
  //                    持たないため、LAG + WINDOW + BASE が31日を超えないようにする
  MECH_CPA_ALERT: 1.5, // 整備士CPAが基準の1.5倍以上なら要確認
};

var MB_HEADER_ROWS = 4; // ボード上部の見出しエリアの行数(5行目から明細)
var MB_TITLE = '広告 監視ボード'; // A1 の見出し。作り直してよいシートかの目印にも使う

/** 監視ボードを作る(作り直す)。daily_summary の列構成が変わったときも再実行する */
function buildMonitorBoard() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var src = ss.getSheetByName(MB_CONFIG.SOURCE_SHEET);
  if (!src) {
    throw new Error('シート「' + MB_CONFIG.SOURCE_SHEET + '」が見つかりません。MB_CONFIG.SOURCE_SHEET を確認してください。');
  }

  var headers = src.getRange(1, 1, 1, src.getLastColumn()).getDisplayValues()[0];
  var keys = mbFindKeys_(headers);
  if (keys.length === 0) {
    throw new Error('「媒体_サイト_' + MB_CONFIG.METRIC_COST + '」形式の見出しが1つも見つかりません。MB_CONFIG を確認してください。');
  }

  var board = ss.getSheetByName(MB_CONFIG.BOARD_SHEET);
  if (board) {
    // 同名の別シートを消さないよう、このスクリプトが作ったボードのときだけ作り直す
    if (board.getRange('A1').getDisplayValue() !== MB_TITLE) {
      throw new Error('シート「' + MB_CONFIG.BOARD_SHEET + '」は既にあり、このスクリプトが作ったものではありません。' +
        '上書きしないよう中断しました。MB_CONFIG.BOARD_SHEET を別の名前にしてください。');
    }
    board.clear();
    board.clearConditionalFormatRules();
  } else {
    board = ss.insertSheet(MB_CONFIG.BOARD_SHEET, 0);
  }

  mbWriteHeader_(board);
  mbWriteRows_(board, keys, headers);
  mbApplyFormats_(board, keys.length);
  SpreadsheetApp.getActiveSpreadsheet().toast(keys.length + ' 行のボードを作成しました', '監視ボード');
}

/**
 * 見出しから「媒体_サイト」のキーを集める。費用列があるものだけを対象にする。
 * 例: G_CW_費用 → { key: 'G_CW', media: 'G', site: 'CW' }
 */
function mbFindKeys_(headers) {
  var suffix = '_' + MB_CONFIG.METRIC_COST;
  var seen = {};
  var keys = [];
  headers.forEach(function (h) {
    h = String(h).trim();
    if (h.length <= suffix.length || h.slice(-suffix.length) !== suffix) return;
    var key = h.slice(0, -suffix.length);
    var sep = key.indexOf('_');
    if (sep <= 0 || seen[key]) return;
    seen[key] = true;
    keys.push({ key: key, media: key.slice(0, sep), site: key.slice(sep + 1) });
  });
  keys.sort(function (a, b) {
    return a.site === b.site ? (a.media < b.media ? -1 : 1) : a.site < b.site ? -1 : 1;
  });
  return keys;
}

function mbWriteHeader_(board) {
  var d = mbDateCol_();
  board.getRange('A1').setValue(MB_TITLE).setFontSize(14).setFontWeight('bold');
  // B3: 判定に使う最終行(日付列の何行目か)。最終行が今日以降なら集計途中とみなして1行戻す
  board.getRange('A3:B3').setValues([['判定に使う行', '=LET(k, COUNTA(' + d + '), v, INDEX(' + d + ', k), ' +
    'dv, IF(ISNUMBER(v), v, DATEVALUE(v)), k - IF(dv >= TODAY(), 1, 0))']]);
  board.getRange('A2:B2').setValues([['基準日(昨日)', '=LET(v, INDEX(' + d + ', B3), IF(ISNUMBER(v), v, DATEVALUE(v)))']]);
  board.getRange('B2').setNumberFormat('yyyy/mm/dd (ddd)');
  board.getRange('D2:E2').setValues([['要確認', '=COUNTIF(O' + (MB_HEADER_ROWS + 1) + ':O, "要確認")']]);
  board.getRange('D2:E2').setFontWeight('bold');
  board.getRange('G2').setValue(
    '整備士CPAは直近' + MB_CONFIG.MECH_LAG_DAYS + '日を除いた' + MB_CONFIG.MECH_WINDOW_DAYS +
      '日間と、その前' + MB_CONFIG.MECH_BASE_DAYS + '日間の比較(整備士数の確定遅れを避けるため)'
  ).setFontColor('#666666');

  var cols = [
    'キー', '媒体', 'サイト',
    '費用 推移(' + MB_CONFIG.SPARK_DAYS + '日)', '昨日 費用', '費用 7日平均比',
    '整備士 推移(' + MB_CONFIG.SPARK_DAYS + '日)', '昨日 整備士',
    '整備士CPA(今)', '整備士CPA(基準)', '整備士CPA 比',
    '費用 空欄日数', '費用 最終入力日', '理由', '判定',
  ];
  board.getRange(MB_HEADER_ROWS, 1, 1, cols.length).setValues([cols])
    .setFontWeight('bold').setBackground('#eeeeee').setWrap(true);
}

function mbWriteRows_(board, keys, headers) {
  var hasHeader = {};
  headers.forEach(function (h) { hasHeader[String(h).trim()] = true; });

  var rows = keys.map(function (k, i) {
    var r = MB_HEADER_ROWS + 1 + i;
    var hasMech = hasHeader[k.key + '_' + MB_CONFIG.METRIC_MECH];
    var cost = mbCol_('$A' + r, MB_CONFIG.METRIC_COST);
    var mech = hasMech ? mbCol_('$A' + r, MB_CONFIG.METRIC_MECH) : null;
    return [
      k.key,
      MB_CONFIG.MEDIA_NAMES[k.media] || k.media,
      k.site,
      mbSpark_(cost, '#1a73e8'),
      '=' + mbWrap_(cost, 'INDEX(c, $B$3)'),
      '=' + mbWrap_(cost, 'LET(a, AVERAGE(' + mbWin_(7, 1) + '), IF(a=0, "", INDEX(c, $B$3) / a))'),
      mech ? mbSpark_(mech, '#188038') : '—',
      mech ? '=' + mbWrap_(mech, 'INDEX(c, $B$3)') : '—',
      mech ? '=' + mbMechCpa_(cost, mech, MB_CONFIG.MECH_WINDOW_DAYS, MB_CONFIG.MECH_LAG_DAYS) : '—',
      mech ? '=' + mbMechCpa_(cost, mech, MB_CONFIG.MECH_BASE_DAYS, MB_CONFIG.MECH_LAG_DAYS + MB_CONFIG.MECH_WINDOW_DAYS) : '—',
      mech ? '=IFERROR(I' + r + ' / J' + r + ', "")' : '—',
      '=' + mbWrap_(cost, 'LET(z, IFERROR(MAX(FILTER(SEQUENCE($B$3), CHOOSEROWS(c, SEQUENCE($B$3)) <> "")), 0), ' +
        'IF(z = 0, "データなし", $B$3 - z))'),
      '=IF(ISNUMBER(L' + r + '), LET(v, INDEX(' + mbDateCol_() + ', $B$3 - L' + r + '), IF(ISNUMBER(v), v, DATEVALUE(v))), "")',
      mbReason_(r, !!mech),
      '=IF(L' + r + ' = "データなし", "データなし", IF(N' + r + ' = "", "正常", "要確認"))',
    ];
  });
  board.getRange(MB_HEADER_ROWS + 1, 1, rows.length, rows[0].length).setValues(rows);
}

function mbApplyFormats_(board, n) {
  var first = MB_HEADER_ROWS + 1;
  var range = function (a1col) { return board.getRange(a1col + first + ':' + a1col + (first + n - 1)); };

  range('E').setNumberFormat('¥#,##0');
  range('F').setNumberFormat('0%');
  range('I').setNumberFormat('¥#,##0');
  range('J').setNumberFormat('¥#,##0');
  range('K').setNumberFormat('0%');
  range('M').setNumberFormat('mm/dd');

  var red = '#f4c7c3';
  var blue = '#c6dafc';
  var rules = [
    mbRule_(range('F'), '=AND(ISNUMBER(F' + first + '), F' + first + ' >= ' + (1 + MB_CONFIG.RATIO_ALERT) + ')', red),
    mbRule_(range('F'), '=AND(ISNUMBER(F' + first + '), F' + first + ' <= ' + (1 - MB_CONFIG.RATIO_ALERT) + ')', blue),
    mbRule_(range('K'), '=AND(ISNUMBER(K' + first + '), K' + first + ' >= ' + MB_CONFIG.MECH_CPA_ALERT + ')', red),
    mbRule_(range('L'), '=AND(ISNUMBER(L' + first + '), L' + first + ' >= ' + MB_CONFIG.BLANK_ALERT_DAYS + ')', red),
    mbRule_(range('O'), '=O' + first + ' = "要確認"', '#fce8b2'),
    mbRule_(range('O'), '=O' + first + ' = "データなし"', '#e8eaed'),
  ];
  board.setConditionalFormatRules(rules);

  board.setFrozenRows(MB_HEADER_ROWS);
  board.setFrozenColumns(3);
  board.setColumnWidth(1, 70);
  board.setColumnWidth(4, 160);
  board.setColumnWidth(7, 160);
  board.setColumnWidth(14, 260);
  board.setRowHeights(first, n, 28);
}

// ---- 数式の部品 -------------------------------------------------------------

/** daily_summary の範囲を INDIRECT で参照する式(シートが作り直されても壊れない) */
function mbSrcRange_(a1) {
  var name = "'" + MB_CONFIG.SOURCE_SHEET.replace(/'/g, "''") + "'!" + a1;
  return 'INDIRECT("' + name.replace(/"/g, '""') + '")';
}

/** 日付列(2行目以降) */
function mbDateCol_() {
  return mbSrcRange_(MB_CONFIG.DATE_COLUMN + '2:' + MB_CONFIG.DATE_COLUMN);
}

/**
 * キーのセル(例: $A5)と指標名から、daily_summary の該当列(2行目以降)を返す式。
 * 値が「38,759」のような文字列で入っていても数値に直す。空欄は "" のまま残す(0 と区別するため)。
 */
function mbCol_(keyCell, metric) {
  var raw = 'INDEX(' + mbSrcRange_('A2:ZZZ') + ', 0, MATCH(' + keyCell + ' & "_' + metric + '", ' + mbSrcRange_('1:1') + ', 0))';
  return 'ARRAYFORMULA(LET(x, ' + raw + ', IF(x = "", "", IFERROR(VALUE(x), ""))))';
}

/** 列 c を束縛して body を評価する。列が無ければ空文字 */
function mbWrap_(colExpr, body) {
  return 'IFERROR(LET(c, ' + colExpr + ', ' + body + '), "")';
}

/** 末尾から offset 日前を終点とする days 日分(例: mbWin_(7, 1) = 昨日を除く直前7日) */
function mbWin_(days, offset) {
  return 'CHOOSEROWS(c, SEQUENCE(' + days + ', 1, $B$3 - ' + (offset + days - 1) + '))';
}

function mbSpark_(colExpr, color) {
  // 空欄は折れ線上では 0 として描く(空欄そのものは「費用 空欄日数」の列で別に見る)
  var body = 'SPARKLINE(ARRAYFORMULA(LET(w, CHOOSEROWS(c, SEQUENCE(' + MB_CONFIG.SPARK_DAYS + ', 1, $B$3 - ' +
    (MB_CONFIG.SPARK_DAYS - 1) + ')), IF(w = "", 0, w))), {"charttype","line";"color","' + color + '";"linewidth",2})';
  return '=' + mbWrap_(colExpr, body);
}

/** 末尾から offset 日を除いた days 日分の 費用合計 / 整備士合計 */
function mbMechCpa_(costExpr, mechExpr, days, offset) {
  var seq = 'SEQUENCE(' + days + ', 1, $B$3 - ' + (offset + days - 1) + ')';
  return 'IFERROR(LET(cs, SUM(CHOOSEROWS(' + costExpr + ', ' + seq + ')), ms, SUM(CHOOSEROWS(' + mechExpr + ', ' + seq +
    ')), IF(ms = 0, IF(cs > 0, "整備士0", ""), cs / ms)), "")';
}

/** 要確認の理由を「、」でつなぐ。何も無ければ空欄(=正常) */
function mbReason_(r, hasMech) {
  var parts = [
    'IF(AND(ISNUMBER(L' + r + '), L' + r + ' >= ' + MB_CONFIG.BLANK_ALERT_DAYS + '), "費用が" & L' + r + ' & "日空欄", "")',
    'IF(AND(ISNUMBER(F' + r + '), F' + r + ' >= ' + (1 + MB_CONFIG.RATIO_ALERT) + '), "費用が平均より多い", "")',
    'IF(AND(ISNUMBER(F' + r + '), F' + r + ' <= ' + (1 - MB_CONFIG.RATIO_ALERT) + '), "費用が平均より少ない", "")',
  ];
  if (hasMech) {
    parts.push('IF(AND(ISNUMBER(K' + r + '), K' + r + ' >= ' + MB_CONFIG.MECH_CPA_ALERT + '), "整備士CPA悪化", "")');
    parts.push('IF(I' + r + ' = "整備士0", "整備士0件(費用あり)", "")');
  }
  return '=TEXTJOIN("、", TRUE, ' + parts.join(', ') + ')';
}

function mbRule_(range, formula, color) {
  return SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied(formula)
    .setBackground(color)
    .setRanges([range])
    .build();
}
