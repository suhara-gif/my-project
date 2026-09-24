/**
 * 電話コミュニケーション基本マニュアル 理解度テスト
 *
 * - Googleアカウントでログイン(Web Appのデプロイ設定でドメイン内限定にする)
 * - 各問サーバ側で採点(正解はクライアントに渡さない)
 * - 結果はスプレッドシートの「results」シートに1受験1行で記録
 * - 誤答した問題の章から復習フィードバックを生成
 *
 * セットアップは docs/setup.md を参照。
 */

var PASS_SCORE = 90; // 合格基準(100点満点中)

function doGet(e) {
  var template = HtmlService.createTemplateFromFile('Index');
  template.userEmail = Session.getActiveUser().getEmail();
  return template.evaluate()
    .setTitle('電話コミュニケーション理解度テスト')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** クライアントへ渡す問題一覧(正解・解説は含めない) */
function getQuestionsForClient() {
  return getQuestionBank_().map(function (q) {
    return {
      id: q.id,
      category: q.category,
      question: q.question,
      choices: q.choices,
    };
  });
}

/**
 * 回答を採点し、結果を記録してフィードバックを返す。
 * @param {Object} answers { "問題id(文字列)": 選択した選択肢のindex }
 */
function submitAnswers(answers) {
  var bank = getQuestionBank_();
  var total = bank.length;
  var pointsPerQuestion = 100 / total;
  var correctCount = 0;
  var wrongDetails = [];

  bank.forEach(function (q) {
    var chosen = answers ? answers[String(q.id)] : undefined;
    var isCorrect = chosen === q.correct;
    if (isCorrect) {
      correctCount++;
    } else {
      wrongDetails.push({
        id: q.id,
        category: q.category,
        question: q.question,
        chosenText: typeof chosen === 'number' ? q.choices[chosen] : '(未回答)',
        correctText: q.choices[q.correct],
        explanation: q.explanation,
      });
    }
  });

  var score = Math.round(correctCount * pointsPerQuestion);
  var pass = score >= PASS_SCORE;
  var feedback = buildFeedback_(wrongDetails, pass);
  var email = Session.getActiveUser().getEmail();

  recordResult_({
    email: email,
    score: score,
    pass: pass,
    wrongDetails: wrongDetails,
    feedback: feedback,
  });

  return {
    email: email,
    score: score,
    total: total,
    correctCount: correctCount,
    passScore: PASS_SCORE,
    pass: pass,
    wrongDetails: wrongDetails,
    feedback: feedback,
  };
}

/** 誤答した章をもとに復習フィードバック文を組み立てる */
function buildFeedback_(wrongDetails, pass) {
  if (wrongDetails.length === 0) {
    return '全問正解です。基本の型がしっかり身についています。';
  }
  var categories = [];
  wrongDetails.forEach(function (d) {
    if (categories.indexOf(d.category) === -1) categories.push(d.category);
  });
  var header = pass
    ? '合格です。ただし次の内容は復習しておくとさらに定着します。'
    : '合格ラインに届きませんでした。次の内容を重点的に復習してください。';
  return header + '\n・' + categories.join('\n・');
}

/** 受験結果をスプレッドシートに1行追記する */
function recordResult_(result) {
  var sheet = getResultsSheet_();
  var wrongIds = result.wrongDetails.map(function (d) { return d.id; }).join(',');
  var wrongCategories = [];
  result.wrongDetails.forEach(function (d) {
    if (wrongCategories.indexOf(d.category) === -1) wrongCategories.push(d.category);
  });
  sheet.appendRow([
    new Date(),
    result.email,
    result.score,
    result.pass ? '合格' : '不合格',
    wrongIds,
    wrongCategories.join(' / '),
    result.feedback,
  ]);
}

function getResultsSheet_() {
  var ss = SpreadsheetApp.openById(getSheetId_());
  var sheet = ss.getSheetByName('results');
  if (!sheet) {
    sheet = ss.insertSheet('results');
    sheet.appendRow(['受験日時', 'メールアドレス', '点数', '合否', '誤答問題ID', '誤答した章', 'フィードバック']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function getSheetId_() {
  var id = PropertiesService.getScriptProperties().getProperty('RESULTS_SHEET_ID');
  if (!id) {
    throw new Error('スクリプトプロパティ RESULTS_SHEET_ID が未設定です。docs/setup.md を参照してください。');
  }
  return id;
}
