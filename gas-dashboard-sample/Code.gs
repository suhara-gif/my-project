/**
 * GAS Dashboard Sample
 * スプレッドシートをDB代わりに使い、HTMLサービスでインタラクティブな
 * グラフダッシュボードを公開する最小構成のサンプル。
 */

const SHEET_NAME = 'SampleData';

/**
 * Webアプリのエントリーポイント。
 */
function doGet() {
  return HtmlService.createHtmlOutputFromFile('index')
    .setTitle('売上ダッシュボード（サンプル）')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * スプレッドシートのメニューからサンプルデータを投入できるようにする。
 * (Webアプリとしてではなく、紐づくシートを直接開いたときに使う)
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('ダッシュボード')
    .addItem('サンプルデータを投入', 'setupSampleData')
    .addToUi();
}

/**
 * SampleDataシートが無ければ作成し、デモ用データを書き込む。
 * 既にデータがある場合は何もしない（誤って上書きしないため）。
 */
function setupSampleData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }
  if (sheet.getLastRow() > 1) {
    return; // 既にデータがある
  }

  const header = ['date', 'channel', 'amount'];
  const channels = ['Web広告', '紹介', '展示会', 'メルマガ'];
  const rows = [];
  const today = new Date();

  for (let i = 0; i < 90; i++) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);
    // 1日あたり1〜3件、チャネルと金額はランダム生成
    const entries = 1 + Math.floor(Math.random() * 3);
    for (let j = 0; j < entries; j++) {
      const channel = channels[Math.floor(Math.random() * channels.length)];
      const amount = Math.floor(10000 + Math.random() * 90000);
      rows.push([date, channel, amount]);
    }
  }

  sheet.getRange(1, 1, 1, header.length).setValues([header]);
  sheet.getRange(2, 1, rows.length, header.length).setValues(rows);
  sheet.getRange('A2:A' + (rows.length + 1)).setNumberFormat('yyyy-MM-dd');
}

/**
 * ダッシュボード表示用にSampleDataシートの全行を返す。
 * フィルタリングはクライアント側で行う。
 */
function getDashboardData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet || sheet.getLastRow() < 2) {
    return [];
  }

  const values = sheet
    .getRange(2, 1, sheet.getLastRow() - 1, 3)
    .getValues();

  return values.map(function (row) {
    return {
      date: Utilities.formatDate(new Date(row[0]), 'Asia/Tokyo', 'yyyy-MM-dd'),
      channel: row[1],
      amount: Number(row[2]),
    };
  });
}
