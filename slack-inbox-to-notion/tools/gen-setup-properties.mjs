#!/usr/bin/env node
/**
 * .env.local を読み、GAS のスクリプト プロパティを一括設定する使い捨てファイル
 * setup.local.gs を生成する。
 *
 * 目的は「GAS の設定画面に 8 個の値を手で打ち込む」作業をなくすこと。
 * 生成物には秘密情報の実値が入るので .gitignore 済み。使い終わったら
 * `npm run props:clean` で削除して GAS 側からも消すこと。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const ENV_PATH = join(ROOT, '.env.local');
const OUT_PATH = join(ROOT, 'setup.local.gs');

const REQUIRED = [
  'SLACK_BOT_TOKEN',
  'NOTION_API_TOKEN',
  'NOTION_TASK_DATABASE_ID',
  'NOTION_ASSIGNEE_USER_ID',
  'ALLOWED_SLACK_USER_ID',
  'TARGET_REACTION',
  'TARGET_CHANNEL_ID'
];

// 設定してよい任意キー。ここに無いキーは打ち間違いとみなして警告する。
const OPTIONAL = [
  'REQUEST_SECRET',
  'TARGET_CHANNEL_NAME',
  'TITLE_BODY_LENGTH',
  'NOTION_STATUS_VALUE',
  'NOTION_ASSIGNEE_NAME',
  'NOTION_VERSION',
  'PROP_TITLE',
  'PROP_STATUS',
  'PROP_ASSIGNEE',
  'PROP_TEXT',
  'PROP_SLACK_URL',
  'TEST_MESSAGE_URL'
];

function die(msg) {
  console.error('\n✗ ' + msg + '\n');
  process.exit(1);
}

if (!existsSync(ENV_PATH)) {
  die(
    '.env.local がありません。まず雛形をコピーして実値を入れてください:\n' +
    '    cp .env.example .env.local\n' +
    '    (エディタで開いて <...> の箇所を埋める)\n\n' +
    '  .env.local は .gitignore 済みなのでコミットされません。'
  );
}

// --- .env.local を読む(KEY=VALUE 形式。# 以降はコメント行のみ対応) ---
const env = {};
const unknown = [];
const raw = readFileSync(ENV_PATH, 'utf8').split(/\r?\n/);
for (const line of raw) {
  const t = line.trim();
  if (t === '' || t.startsWith('#')) continue;
  const i = t.indexOf('=');
  if (i === -1) continue;
  const key = t.slice(0, i).trim();
  let val = t.slice(i + 1).trim();
  // 前後のクォートを外す
  if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
    val = val.slice(1, -1);
  }
  if (val === '') continue;
  // 埋め忘れの <...> は未設定として扱う
  if (/^<.*>$/.test(val)) continue;
  if (!REQUIRED.includes(key) && !OPTIONAL.includes(key)) unknown.push(key);
  env[key] = val;
}

const missing = REQUIRED.filter((k) => !(k in env));
if (missing.length) {
  die(
    '.env.local に次の必須キーの実値がありません:\n' +
    missing.map((k) => '    - ' + k).join('\n') +
    '\n\n  <...> のままになっていないか確認してください。'
  );
}

if (unknown.length) {
  console.warn('⚠ 見覚えのないキーがあります(打ち間違い?): ' + unknown.join(', '));
}

// --- 値の健全性チェック(GAS に上げる前に落とす) ---
if ('REQUEST_SECRET' in env) {
  if (/[&?#/\s]/.test(env.REQUEST_SECRET)) {
    die('REQUEST_SECRET に & ? # / 空白 が含まれています。URL のクエリとして壊れます。\n' +
      '  英数字だけの値にしてください(GAS の testGenerateSecret() で生成できます)。');
  }
  if (env.REQUEST_SECRET.length < 16) {
    die('REQUEST_SECRET が短すぎます(16文字以上にしてください)。');
  }
} else {
  console.warn('⚠ REQUEST_SECRET が未設定です。Web App の URL を知られると誰でも叩ける状態になります。');
  console.warn('  GAS で testGenerateSecret() を実行 → 出た値を .env.local に入れて再実行を推奨します。');
}
if (!/^C[A-Z0-9]+$/.test(env.TARGET_CHANNEL_ID)) {
  console.warn('⚠ TARGET_CHANNEL_ID が Slack のチャンネルID形式(C…)に見えません: ' + env.TARGET_CHANNEL_ID);
}
if (!/^U[A-Z0-9]+$/.test(env.ALLOWED_SLACK_USER_ID)) {
  console.warn('⚠ ALLOWED_SLACK_USER_ID が Slack のユーザーID形式(U…)に見えません: ' + env.ALLOWED_SLACK_USER_ID);
}

// --- setup.local.gs を生成 ---
const keys = [...REQUIRED, ...OPTIONAL].filter((k) => k in env);
const entries = keys.map((k) => '    ' + JSON.stringify(k) + ': ' + JSON.stringify(env[k])).join(',\n');

const out = `/**
 * === 自動生成ファイル / コミット禁止 ===
 *
 * tools/gen-setup-properties.mjs が .env.local から生成しました。
 * 中に秘密情報の実値が入っています(.gitignore 済み)。
 *
 * 使い方:
 *   1. GAS エディタでこの関数 setupPropertiesFromEnvLocal を 1 回実行する
 *   2. 実行ログで設定結果を確認する
 *   3. ローカルで \`npm run props:clean\` を実行し、このファイルを
 *      ローカルからも GAS プロジェクトからも消す
 */
function setupPropertiesFromEnvLocal() {
  var props = {
${entries}
  };
  // 第2引数 false = 既存の他プロパティは消さない
  PropertiesService.getScriptProperties().setProperties(props, false);

  var names = Object.keys(props);
  var secretish = ['SLACK_BOT_TOKEN', 'NOTION_API_TOKEN', 'REQUEST_SECRET'];
  var lines = names.map(function (k) {
    var v = String(props[k]);
    var shown = secretish.indexOf(k) === -1 ? v : (v.slice(0, 4) + '…(' + v.length + '文字)');
    return '  ' + k + ' = ' + shown;
  });
  console.log('スクリプト プロパティを ' + names.length + ' 件設定しました:\\n' + lines.join('\\n'));
  console.log('\\n次: testConfig() を実行して設定を検証してください。');
  console.log('検証が通ったら、ローカルで npm run props:clean を実行してこのファイルを消してください。');
}
`;

writeFileSync(OUT_PATH, out, 'utf8');

console.log('✓ setup.local.gs を生成しました(' + keys.length + ' 件のプロパティ)');
console.log('  設定されるキー: ' + keys.join(', '));
console.log('\n次の手順:');
console.log('  1. npm run push            # GAS へ反映');
console.log('  2. npm run open            # GAS エディタを開く');
console.log('  3. エディタで setupPropertiesFromEnvLocal を 1 回実行');
console.log('  4. エディタで testConfig を実行して検証');
console.log('  5. npm run props:clean     # 使い捨てファイルを削除して GAS からも消す');
