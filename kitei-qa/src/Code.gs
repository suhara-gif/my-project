/**
 * 社内規程Q&A(NotebookLM連携)
 *
 * Box の社内規程フォルダ「直下」のファイル(=現行版)の本文を、1つの Google ドキュメント
 * 「社内規程_現行版(自動更新)」にまとめて書き出す。1時間ごとに Box を確認し、変更があったときだけ書き直す。
 *
 * NotebookLM はソースに追加した Google ドキュメントの変更を自動で取り込むので、
 * このドキュメントを NotebookLM のソースにしておけば、規程の改定が質問の回答にも反映される。
 * 規程は改定のたびに別ファイル(別ID)として Box に置かれるため、ファイルごとにドキュメントを
 * 作るとソースの追加し直しが必要になる。それを避けるため、全規程を1つのドキュメントにまとめる。
 *
 * セットアップは docs/setup.md を参照。
 */

var DOC_TITLE = '社内規程_現行版(自動更新)';
var DOC_MAX_CHARS = 1000000; // Google ドキュメントの文字数上限(約102万字)より少し手前
var RUN_BUDGET_MS = 4.5 * 60 * 1000; // GAS の1回の実行上限(6分)より手前で切り上げる
var PENDING_ALERT_MS = 24 * 60 * 60 * 1000; // 取り込み待ちがこれ以上続いたら知らせる

/** 時間主導トリガーから1時間ごとに呼ばれる。手動実行してもよい。 */
function syncRules() {
  var files = listCurrentRuleFiles_(getConfig_('BOX_FOLDER_ID'));
  files.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });

  var signature = files.map(function (f) { return f.id + ':' + f.versionId; }).join(',');
  var props = PropertiesService.getScriptProperties();
  if (signature === props.getProperty('LAST_SIGNATURE')) return; // 変更なし

  var deadline = Date.now() + RUN_BUDGET_MS;
  var readable = [];
  var unreadable = [];
  var pending = [];
  files.forEach(function (f) {
    var text = getFileText_(f);
    if (text !== null && isBlank_(text) && f.extension === 'pdf') {
      // 文字データの無いPDF(スキャン画像)は、ページ画像から文字認識する
      text = ocrFile_(f, deadline);
      f.ocr = true;
    }
    if (text === null) {
      pending.push(f); // Box 側の準備中、または文字認識の途中で時間切れ。次回また試す
    } else if (isBlank_(text)) {
      unreadable.push(f);
    } else {
      f.text = text;
      readable.push(f);
    }
  });

  // 取り込み待ちのファイルがある間は、ドキュメントを書き換えない。
  // 書き換えると、改定直後の規程がまるごと抜けた状態で NotebookLM に同期されてしまうため。
  if (pending.length > 0) {
    alertIfPendingTooLong_(pending);
    return;
  }
  props.deleteProperty('PENDING_SINCE');

  var doc = getOrCreateDoc_();
  writeDoc_(doc, readable, unreadable);
  props.setProperty('LAST_SIGNATURE', signature);
  notifyAdmin_(doc, readable, unreadable);
}

function isBlank_(text) {
  return text.replace(/\s/g, '').length === 0;
}

/** 取り込み待ちが長く続いたら(Box の障害など)、1回だけメールで知らせる */
function alertIfPendingTooLong_(pending) {
  var props = PropertiesService.getScriptProperties();
  var since = Number(props.getProperty('PENDING_SINCE'));
  if (!since) {
    props.setProperty('PENDING_SINCE', String(Date.now()));
    return;
  }
  if (since < 0 || Date.now() - since < PENDING_ALERT_MS) return;
  props.setProperty('PENDING_SINCE', '-1'); // 通知済み
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(),
    '[社内規程Q&A] 規程の取り込みが24時間以上止まっています',
    '次の規程を取り込めない状態が続いているため、ドキュメントを更新できていません。\n' +
    pending.map(function (f) { return '・' + f.name; }).join('\n') +
    '\n\nApps Script の「実行数」でエラー内容を確認してください。');
}

function getOrCreateDoc_() {
  var props = PropertiesService.getScriptProperties();
  var docId = props.getProperty('DOC_ID');
  if (docId) return DocumentApp.openById(docId);

  var doc = DocumentApp.create(DOC_TITLE);
  // NotebookLM は Drive の閲覧権限に従うので、社内の全員が閲覧できるようにしておく
  DriveApp.getFileById(doc.getId()).setSharing(DriveApp.Access.DOMAIN_WITH_LINK, DriveApp.Permission.VIEW);
  props.setProperty('DOC_ID', doc.getId());
  return doc;
}

function writeDoc_(doc, readable, unreadable) {
  var total = readable.reduce(function (sum, f) { return sum + f.text.length; }, 0);
  if (total > DOC_MAX_CHARS) {
    throw new Error('規程の合計が' + total + '文字あり、Googleドキュメントの上限を超えます。');
  }

  var body = doc.getBody();
  body.clear();
  body.appendParagraph(DOC_TITLE).setHeading(DocumentApp.ParagraphHeading.TITLE);
  body.appendParagraph(
    'このドキュメントは Box の社内規程フォルダから自動で作成しています。直接編集しないでください' +
    '(次回の更新で上書きされます)。\n最終更新: ' +
    Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy-MM-dd HH:mm'));

  if (unreadable.length > 0) {
    body.appendParagraph('読み取れなかった規程').setHeading(DocumentApp.ParagraphHeading.HEADING1);
    body.appendParagraph(
      '次の規程は Box のフォルダにありますが、文字を読み取れなかったため、' +
      'このドキュメントには含まれていません。これらの規程に関する質問には答えられません。\n' +
      unreadable.map(function (f) { return '・' + f.name; }).join('\n'));
  }

  readable.forEach(function (f) {
    body.appendParagraph(f.name.replace(/\.[^.]+$/, '')).setHeading(DocumentApp.ParagraphHeading.HEADING1);
    body.appendParagraph('元ファイル: ' + f.name + '(Box 最終更新 ' + f.modifiedAt.substring(0, 10) + ')' +
      (f.ocr ? '\n※スキャン画像から文字認識した本文です。数字や語句を読み間違えている可能性があるため、' +
        '重要な点は元ファイルで確認してください。' : ''));
    body.appendParagraph(f.text);
  });
  doc.saveAndClose();
}

/** 書き直したときだけ、スクリプトの所有者にメールで知らせる(読めない規程に気づけるように) */
function notifyAdmin_(doc, readable, unreadable) {
  var lines = [
    '社内規程ドキュメントを更新しました。',
    doc.getUrl(),
    '',
    '取り込んだ規程(' + readable.length + '件):',
  ].concat(readable.map(function (f) { return '・' + f.name + (f.ocr ? '(文字認識)' : ''); }));
  if (unreadable.length > 0) {
    lines = lines.concat(['', '読み取れなかった規程(' + unreadable.length + '件。画像が不鮮明でないか、対応していない形式でないか確認してください):'])
      .concat(unreadable.map(function (f) { return '・' + f.name; }));
  }
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), '[社内規程Q&A] 規程ドキュメントを更新しました', lines.join('\n'));
}

/** 1時間ごとの自動実行を設定する。最初に1回だけ手動で実行する。 */
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncRules') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncRules').timeBased().everyHours(1).create();
}

/** 次回の syncRules で必ず書き直させる(取り込み結果を確認し直したいとき用) */
function forceResync() {
  PropertiesService.getScriptProperties().deleteProperty('LAST_SIGNATURE');
  syncRules();
}

function getConfig_(key) {
  var value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) throw new Error('スクリプトプロパティ ' + key + ' が未設定です。');
  return value;
}
