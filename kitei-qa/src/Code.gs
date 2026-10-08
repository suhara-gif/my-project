/**
 * 社内規程Q&A
 *
 * - 社内ドメインのGoogleアカウントでログインした従業員が、就業規則などの社内規程について口語で質問できる
 * - 質問のたびに Box の社内規程フォルダ「直下」のファイルを最新版として読み込む(サブフォルダ=旧版は対象外)
 *   → 規程を改定したら Box のファイルを差し替えるだけで、このアプリ側の更新作業は不要
 * - 回答は Claude API が、読み込んだ規程の記載だけを根拠に生成する
 *
 * セットアップは docs/setup.md を参照。
 */

var MAX_QUESTION_LENGTH = 2000; // 1回の質問の最大文字数

/** 質問者が選べる区分(適用される規程を絞り込むためのヒント) */
var CATEGORIES = [
  '指定しない',
  '株式会社アプティ 正社員',
  '株式会社アプティ 契約社員',
  '株式会社アプティグローバル',
  '派遣社員',
];

function doGet(e) {
  var template = HtmlService.createTemplateFromFile('Index');
  template.userEmail = Session.getActiveUser().getEmail();
  template.categories = CATEGORIES;
  return template.evaluate()
    .setTitle('社内規程Q&A')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/**
 * 質問に回答する(クライアントから google.script.run で呼ばれる)。
 * @param {string} question 質問文
 * @param {string} category CATEGORIES のいずれか
 * @return {{answer: string, sources: Object[], unreadable: string[]}}
 */
function ask(question, category) {
  question = String(question || '').trim();
  if (!question) throw new Error('質問を入力してください。');
  if (question.length > MAX_QUESTION_LENGTH) {
    throw new Error('質問は' + MAX_QUESTION_LENGTH + '文字以内にしてください。');
  }
  if (CATEGORIES.indexOf(category) === -1) category = CATEGORIES[0];

  var library = loadRuleLibrary_();
  if (library.readable.length === 0) {
    throw new Error('規程ファイルを1件も読み込めませんでした。管理者に連絡してください。');
  }

  var answer = askClaude_(buildDocumentsText_(library), buildUserMessage_(question, category));

  logQuestion_(question, category);

  return {
    answer: answer,
    sources: library.readable.map(function (f) {
      return { name: f.name, modifiedAt: f.modifiedAt, url: 'https://app.box.com/file/' + f.id };
    }),
    unreadable: library.unreadable.map(function (f) { return f.name; }),
  };
}

/**
 * Box の規程フォルダ直下から、本文を読めたファイルと読めなかったファイルを返す。
 * 並び順はファイル名順で固定する(プロンプトキャッシュを効かせるため)。
 */
function loadRuleLibrary_() {
  var files = listCurrentRuleFiles_(getConfig_('BOX_FOLDER_ID'));
  files.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });

  var readable = [];
  var unreadable = [];
  files.forEach(function (f) {
    var text = getFileText_(f);
    if (text && text.replace(/\s/g, '').length > 0) {
      f.text = text;
      readable.push(f);
    } else {
      unreadable.push(f);
    }
  });
  return { readable: readable, unreadable: unreadable };
}

function buildDocumentsText_(library) {
  var parts = library.readable.map(function (f, i) {
    return '<document index="' + (i + 1) + '">\n' +
      '<source>' + f.name + '</source>\n' +
      '<last_modified>' + f.modifiedAt + '</last_modified>\n' +
      '<content>\n' + f.text + '\n</content>\n' +
      '</document>';
  });
  var text = '<documents>\n' + parts.join('\n') + '\n</documents>';
  if (library.unreadable.length > 0) {
    text += '\n\n<unreadable_files>\n以下のファイルはフォルダにあるが本文を読み取れなかった' +
      '(スキャン画像のPDF等)。内容は不明として扱うこと。\n' +
      library.unreadable.map(function (f) { return '- ' + f.name; }).join('\n') +
      '\n</unreadable_files>';
  }
  return text;
}

function buildUserMessage_(question, category) {
  return '質問者の区分: ' + category + '\n\n質問:\n' + question;
}

/**
 * 質問ログ(任意)。スクリプトプロパティ LOG_SHEET_ID が設定されているときだけ記録する。
 * 退職・育休・懲戒など人に知られたくない質問もありうるため、既定では記録しない。
 */
function logQuestion_(question, category) {
  var sheetId = PropertiesService.getScriptProperties().getProperty('LOG_SHEET_ID');
  if (!sheetId) return;
  var ss = SpreadsheetApp.openById(sheetId);
  var sheet = ss.getSheetByName('log') || ss.insertSheet('log');
  if (sheet.getLastRow() === 0) sheet.appendRow(['日時', '区分', '質問']);
  // 個人を特定しないため、メールアドレスは記録しない
  sheet.appendRow([new Date(), category, question]);
}

function getConfig_(key) {
  var value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) throw new Error('スクリプトプロパティ ' + key + ' が未設定です。管理者に連絡してください。');
  return value;
}

/** セットアップ確認用。エディタから手動実行し、読み込めたファイル/読めなかったファイルをログに出す。 */
function checkSetup() {
  var library = loadRuleLibrary_();
  library.readable.forEach(function (f) {
    Logger.log('OK  ' + f.name + '(' + f.text.length + '文字)');
  });
  library.unreadable.forEach(function (f) {
    Logger.log('NG  ' + f.name + '(本文を読み取れません。文字入りのPDFかWordに差し替えてください)');
  });
}
