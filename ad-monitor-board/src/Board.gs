/**
 * 広告 監視ボード
 *
 * daily_summary(日次・媒体×サイト別の広告実績)の横に「監視ボード」シートを作り、
 * 媒体×サイトごとに「判定」「推移の折れ線」「昨日の値」「7日平均比」「週ごとの比較(改善/悪化)」
 * 「整備士CPAの2週連続の傾向」「空欄の連続日数」を1行で並べる。
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

  // 週比較。「今週」= 直近 LAG_DAYS 日を除いた7日間、「先週」「先々週」はその前の7日間ずつ。
  // 整備士数は確定が遅れるため直近を外す。費用・CVも同じ窓で比べる(指標ごとに期間がずれないように)。
  // daily_summary は直近約31日分しか持たないため、LAG_DAYS + 21 が31を超えないようにする。
  LAG_DAYS: 3,
  WEEK_CHANGE: 0.2, // 先週比 ±20% 未満は「横ばい」
  WEEK_MIN_COUNT: 3, // CV・整備士CVがどちらかの週でこの件数未満なら「件数不足」として改善/悪化を出さない
  CPA_ALERT: 0.5, // 整備士CPAが先週比 +50% 以上なら要確認
};

var MB_HEADER_ROWS = 4; // ボード上部の見出しエリアの行数(5行目から明細)
var MB_TITLE = '広告 監視ボード'; // A1 の見出し。作り直してよいシートかの目印にも使う

// 列の配置。表示列(A〜U)と、週合計を置く非表示の補助列(W〜AE)
var MB_COLS = {
  key: 'A', media: 'B', site: 'C', judge: 'D', reason: 'E',
  costSpark: 'F', costLast: 'G', costRatio: 'H', mechSpark: 'I',
  costWeek: 'J', costChg: 'K', cvWeek: 'L', cvChg: 'M', mechWeek: 'N', mechChg: 'O',
  cpaNow: 'P', cpaPrev: 'Q', cpaChg: 'R', trend: 'S', blank: 'T', lastDate: 'U',
  // 補助列: 今週(0)・先週(1)・先々週(2)の合計
  c0: 'W', c1: 'X', c2: 'Y', v0: 'Z', v1: 'AA', v2: 'AB', m0: 'AC', m1: 'AD', m2: 'AE',
};

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
  var C = MB_COLS;
  var body = function (col) { return col + (MB_HEADER_ROWS + 1) + ':' + col; };
  board.getRange('A1').setValue(MB_TITLE).setFontSize(14).setFontWeight('bold');
  // B3: 判定に使う最終行(日付列の何行目か)。最終行が今日以降なら集計途中とみなして1行戻す
  board.getRange('A3:B3').setValues([['判定に使う行', '=LET(k, COUNTA(' + d + '), v, INDEX(' + d + ', k), ' +
    'dv, IF(ISNUMBER(v), v, DATEVALUE(v)), k - IF(dv >= TODAY(), 1, 0))']]);
  board.getRange('A2:B2').setValues([['基準日(昨日)', '=LET(v, INDEX(' + d + ', B3), IF(ISNUMBER(v), v, DATEVALUE(v)))']]);
  board.getRange('B2').setNumberFormat('yyyy/mm/dd (ddd)');
  board.getRange('D2:I2').setValues([[
    '要確認', '=COUNTIF(' + body(C.judge) + ', "要確認")',
    '整備士CPA 改善', '=COUNTIF(' + body(C.cpaChg) + ', "*改善*")',
    '整備士CPA 悪化', '=COUNTIF(' + body(C.cpaChg) + ', "*悪化*")',
  ]]).setFontWeight('bold');
  // 今週の期間(例: 09/18〜09/24)
  var day = function (off) {
    return 'TEXT(LET(v, INDEX(' + d + ', B3 - ' + off + '), IF(ISNUMBER(v), v, DATEVALUE(v))), "mm/dd")';
  };
  var wk = function (k) {
    var endOff = MB_CONFIG.LAG_DAYS + 7 * k;
    return day(endOff + 6) + ' & "〜" & ' + day(endOff);
  };
  board.getRange('K2').setFormula('="今週 " & ' + wk(0) + ' & " ・ 先週 " & ' + wk(1) +
    ' & "(整備士数の確定遅れを避けるため直近' + MB_CONFIG.LAG_DAYS + '日を除く)"').setFontColor('#666666');

  var cols = [
    'キー', '媒体', 'サイト', '判定', '理由',
    '費用 推移(' + MB_CONFIG.SPARK_DAYS + '日)', '昨日 費用', '費用 7日平均比', '整備士 推移(' + MB_CONFIG.SPARK_DAYS + '日)',
    '費用 今週', '費用 先週比', 'CV 今週', 'CV 先週比', '整備士CV 今週', '整備士CV 先週比',
    '整備士CPA 今週', '整備士CPA 先週', '整備士CPA 先週比', '傾向(2週連続)',
    '費用 空欄日数', '費用 最終入力日', '',
    '費用 今週', '費用 先週', '費用 先々週', 'CV 今週', 'CV 先週', 'CV 先々週', '整備士 今週', '整備士 先週', '整備士 先々週',
  ];
  board.getRange(MB_HEADER_ROWS, 1, 1, cols.length).setValues([cols])
    .setFontWeight('bold').setBackground('#eeeeee').setWrap(true);
}

function mbWriteRows_(board, keys, headers) {
  var hasHeader = {};
  headers.forEach(function (h) { hasHeader[String(h).trim()] = true; });
  var C = MB_COLS;

  var rows = keys.map(function (k, i) {
    var r = MB_HEADER_ROWS + 1 + i;
    var at = function (col) { return col + r; };
    var hasMech = hasHeader[k.key + '_' + MB_CONFIG.METRIC_MECH];
    var hasCv = hasHeader[k.key + '_' + MB_CONFIG.METRIC_CV];
    var cost = mbCol_('$A' + r, MB_CONFIG.METRIC_COST);
    var cv = hasCv ? mbCol_('$A' + r, MB_CONFIG.METRIC_CV) : null;
    var mech = hasMech ? mbCol_('$A' + r, MB_CONFIG.METRIC_MECH) : null;
    var n = MB_CONFIG.WEEK_MIN_COUNT;

    var row = {};
    row.key = k.key;
    row.media = MB_CONFIG.MEDIA_NAMES[k.media] || k.media;
    row.site = k.site;
    row.judge = '=IF(' + at(C.blank) + ' = "データなし", "データなし", IF(' + at(C.reason) + ' = "", "正常", "要確認"))';
    row.reason = mbReason_(r, !!mech);
    row.costSpark = mbSpark_(cost, '#1a73e8');
    row.costLast = '=' + mbWrap_(cost, 'INDEX(c, $B$3)');
    row.costRatio = '=' + mbWrap_(cost, 'LET(a, AVERAGE(' + mbWin_(7, 1) + '), IF(a=0, "", INDEX(c, $B$3) / a))');
    row.mechSpark = mech ? mbSpark_(mech, '#188038') : '—';

    row.costWeek = '=' + at(C.c0);
    row.costChg = '=' + mbChange_(at(C.c0), at(C.c1), '', '増', '減');
    row.cvWeek = cv ? '=' + at(C.v0) : '—';
    row.cvChg = cv ? '=' + mbChange_(at(C.v0), at(C.v1), 'OR(' + at(C.v0) + ' < ' + n + ', ' + at(C.v1) + ' < ' + n + ')', '改善', '悪化') : '—';
    row.mechWeek = mech ? '=' + at(C.m0) : '—';
    row.mechChg = mech ? '=' + mbChange_(at(C.m0), at(C.m1), 'OR(' + at(C.m0) + ' < ' + n + ', ' + at(C.m1) + ' < ' + n + ')', '改善', '悪化') : '—';
    row.cpaNow = mech ? '=' + mbCpa_(at(C.c0), at(C.m0)) : '—';
    row.cpaPrev = mech ? '=' + mbCpa_(at(C.c1), at(C.m1)) : '—';
    // CPA は下がるほど良いので、上がったら「悪化」
    row.cpaChg = mech ? '=' + mbChange_(at(C.cpaNow), at(C.cpaPrev), 'OR(' + at(C.m0) + ' < ' + n + ', ' + at(C.m1) + ' < ' + n + ')', '悪化', '改善') : '—';
    row.trend = mech ? '=' + mbTrend_(r) : '—';

    row.blank = '=' + mbWrap_(cost, 'LET(z, IFERROR(MAX(FILTER(SEQUENCE($B$3), CHOOSEROWS(c, SEQUENCE($B$3)) <> "")), 0), ' +
      'IF(z = 0, "データなし", $B$3 - z))');
    row.lastDate = '=IF(ISNUMBER(' + at(C.blank) + '), LET(v, INDEX(' + mbDateCol_() + ', $B$3 - ' + at(C.blank) + '), ' +
      'IF(ISNUMBER(v), v, DATEVALUE(v))), "")';

    [cost, cv, mech].forEach(function (expr, j) {
      var names = [['c0', 'c1', 'c2'], ['v0', 'v1', 'v2'], ['m0', 'm1', 'm2']][j];
      names.forEach(function (name, wIdx) {
        row[name] = expr ? '=' + mbWeekSum_(expr, wIdx) : '';
      });
    });

    // 列文字の順に並べる(間の空き列 V は空欄)
    var out = [];
    for (var col = 1; col <= mbColIndex_(C.m2); col++) out.push('');
    Object.keys(C).forEach(function (name) { out[mbColIndex_(C[name]) - 1] = row[name]; });
    return out;
  });
  board.getRange(MB_HEADER_ROWS + 1, 1, rows.length, rows[0].length).setValues(rows);
}

function mbApplyFormats_(board, n) {
  var C = MB_COLS;
  var first = MB_HEADER_ROWS + 1;
  var range = function (col) { return board.getRange(col + first + ':' + col + (first + n - 1)); };
  var top = function (col) { return col + first; };

  [C.costLast, C.costWeek, C.cpaNow, C.cpaPrev, C.c0, C.c1, C.c2].forEach(function (col) {
    range(col).setNumberFormat('¥#,##0');
  });
  range(C.costRatio).setNumberFormat('0%');
  range(C.lastDate).setNumberFormat('mm/dd');

  var red = '#f4c7c3';
  var blue = '#c6dafc';
  var green = '#ceead6';
  var rules = [
    mbRule_(range(C.judge), '=' + top(C.judge) + ' = "要確認"', '#fce8b2'),
    mbRule_(range(C.judge), '=' + top(C.judge) + ' = "データなし"', '#e8eaed'),
    mbRule_(range(C.costRatio), '=AND(ISNUMBER(' + top(C.costRatio) + '), ' + top(C.costRatio) + ' >= ' + (1 + MB_CONFIG.RATIO_ALERT) + ')', red),
    mbRule_(range(C.costRatio), '=AND(ISNUMBER(' + top(C.costRatio) + '), ' + top(C.costRatio) + ' <= ' + (1 - MB_CONFIG.RATIO_ALERT) + ')', blue),
    mbRule_(range(C.blank), '=AND(ISNUMBER(' + top(C.blank) + '), ' + top(C.blank) + ' >= ' + MB_CONFIG.BLANK_ALERT_DAYS + ')', red),
  ];
  // 先週比・傾向の列: 「悪化」を赤、「改善」を緑
  [C.cvChg, C.mechChg, C.cpaChg, C.trend].forEach(function (col) {
    rules.push(mbRule_(range(col), '=ISNUMBER(SEARCH("悪化", ' + top(col) + '))', red));
    rules.push(mbRule_(range(col), '=ISNUMBER(SEARCH("改善", ' + top(col) + '))', green));
  });
  board.setConditionalFormatRules(rules);

  board.setFrozenRows(MB_HEADER_ROWS);
  board.setFrozenColumns(4);
  board.setColumnWidth(1, 70);
  board.setColumnWidth(mbColIndex_(C.reason), 220);
  board.setColumnWidth(mbColIndex_(C.costSpark), 150);
  board.setColumnWidth(mbColIndex_(C.mechSpark), 150);
  [C.costChg, C.cvChg, C.mechChg, C.cpaChg].forEach(function (col) { board.setColumnWidth(mbColIndex_(col), 110); });
  board.setColumnWidth(mbColIndex_(C.trend), 150);
  board.setRowHeights(first, n, 28);
  // 補助列は隠す(消すと週比較が壊れるので、削除はしない)
  board.hideColumns(mbColIndex_(C.c0), mbColIndex_(C.m2) - mbColIndex_(C.c0) + 1);
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

/** 列文字(例: 'AC')を列番号に直す */
function mbColIndex_(letters) {
  var n = 0;
  for (var i = 0; i < letters.length; i++) n = n * 26 + (letters.charCodeAt(i) - 64);
  return n;
}

/** 週 wIdx(0=今週, 1=先週, 2=先々週)の合計。各週は直近 LAG_DAYS 日を除いた7日間ずつ */
function mbWeekSum_(colExpr, wIdx) {
  var endOff = MB_CONFIG.LAG_DAYS + 7 * wIdx;
  return 'IFERROR(SUM(CHOOSEROWS(' + colExpr + ', SEQUENCE(7, 1, $B$3 - ' + (endOff + 6) + '))), "")';
}

/** 費用 ÷ 整備士数。整備士0件で費用があれば「整備士0」 */
function mbCpa_(costCell, mechCell) {
  return 'IF(OR(' + costCell + ' = "", ' + mechCell + ' = ""), "", IF(' + mechCell + ' = 0, IF(' + costCell + ' > 0, "整備士0", ""), ' +
    costCell + ' / ' + mechCell + '))';
}

/**
 * 今週 a と先週 b を比べたラベル(例: 「↑ 改善 +32%」「→ 横ばい -5%」「件数不足」)。
 * upLabel / downLabel は増えたとき・減ったときの呼び方(CPA なら 上がる=悪化)。
 * thinCond が真なら件数が少なすぎるので判定しない。
 */
function mbChange_(a, b, thinCond, upLabel, downLabel) {
  var pct = 'TEXT(' + a + ' / ' + b + ' - 1, "+0%;-0%;0%")';
  // 表示(整数%)と判定がずれないよう、丸めてから閾値と比べる(-19.9% を「-20% 横ばい」と出さない)
  var body = 'IF(ABS(ROUND(' + a + ' / ' + b + ' - 1, 2)) < ' + MB_CONFIG.WEEK_CHANGE + ', "→ 横ばい " & ' + pct + ', ' +
    'IF(' + a + ' > ' + b + ', "↑ ' + upLabel + ' ", "↓ ' + downLabel + ' ") & ' + pct + ')';
  var guard = 'OR(NOT(ISNUMBER(' + a + ')), NOT(ISNUMBER(' + b + ')), ' + b + ' = 0)';
  return 'IFERROR(IF(' + guard + ', "", ' + (thinCond ? 'IF(' + thinCond + ', "件数不足", ' + body + ')' : body) + '), "")';
}

/** 整備士CPAが先々週→先週→今週と、同じ向きに2週続けて ±WEEK_CHANGE 以上動いたか */
function mbTrend_(r) {
  var C = MB_COLS;
  var at = function (col) { return col + r; };
  var n = MB_CONFIG.WEEK_MIN_COUNT;
  var th = MB_CONFIG.WEEK_CHANGE;
  var cpa = function (c, m) { return '(' + at(c) + ' / ' + at(m) + ')'; };
  var p0 = cpa(C.c0, C.m0), p1 = cpa(C.c1, C.m1), p2 = cpa(C.c2, C.m2);
  return 'IFERROR(IF(OR(' + at(C.m0) + ' < ' + n + ', ' + at(C.m1) + ' < ' + n + ', ' + at(C.m2) + ' < ' + n + '), "件数不足", ' +
    'IF(AND(' + p0 + ' / ' + p1 + ' - 1 >= ' + th + ', ' + p1 + ' / ' + p2 + ' - 1 >= ' + th + '), "悪化傾向(2週連続)", ' +
    'IF(AND(' + p0 + ' / ' + p1 + ' - 1 <= -' + th + ', ' + p1 + ' / ' + p2 + ' - 1 <= -' + th + '), "改善傾向(2週連続)", ""))), "")';
}

/** 要確認の理由を「、」でつなぐ。何も無ければ空欄(=正常) */
function mbReason_(r, hasMech) {
  var C = MB_COLS;
  var at = function (col) { return col + r; };
  var parts = [
    'IF(AND(ISNUMBER(' + at(C.blank) + '), ' + at(C.blank) + ' >= ' + MB_CONFIG.BLANK_ALERT_DAYS + '), "費用が" & ' + at(C.blank) + ' & "日空欄", "")',
    'IF(AND(ISNUMBER(' + at(C.costRatio) + '), ' + at(C.costRatio) + ' >= ' + (1 + MB_CONFIG.RATIO_ALERT) + '), "昨日の費用が平均より多い", "")',
    'IF(AND(ISNUMBER(' + at(C.costRatio) + '), ' + at(C.costRatio) + ' <= ' + (1 - MB_CONFIG.RATIO_ALERT) + '), "昨日の費用が平均より少ない", "")',
  ];
  if (hasMech) {
    parts.push('IFERROR(IF(AND(ISNUMBER(' + at(C.cpaNow) + '), ISNUMBER(' + at(C.cpaPrev) + '), ' + at(C.m0) + ' >= ' + MB_CONFIG.WEEK_MIN_COUNT +
      ', ' + at(C.m1) + ' >= ' + MB_CONFIG.WEEK_MIN_COUNT + ', ' + at(C.cpaNow) + ' / ' + at(C.cpaPrev) + ' - 1 >= ' + MB_CONFIG.CPA_ALERT +
      '), "整備士CPAが先週より大幅悪化", ""), "")');
    parts.push('IF(' + at(C.trend) + ' = "悪化傾向(2週連続)", "整備士CPAが2週連続悪化", "")');
    parts.push('IF(' + at(C.cpaNow) + ' = "整備士0", "今週の整備士0件(費用あり)", "")');
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
