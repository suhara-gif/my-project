#!/usr/bin/env node
/**
 * コード変更を「本番に効く形で」反映する。
 *
 *   npm run release
 *
 * ── なぜ必要か ────────────────────────────────────────────────
 * GAS は `clasp push` してもデプロイ済み Web App には反映されない。
 * push はエディタで見える HEAD を更新するだけで、Slack が叩く URL は
 * デプロイ時点のバージョンに固定されたまま動き続ける。
 *
 * この落とし穴を実際に踏んだ:
 *   「チャンネル限定を外す修正を push した → Slack から叩いても直らない」
 *   → 原因はデプロイがバージョン1のままだったこと。ログが読めない環境では
 *     この状態の切り分けに非常に時間がかかる。
 *
 * そこで push と deploy を1コマンドに束ね、**既存デプロイを更新する**
 * (= URL を変えない)ようにした。さらにデプロイ後に doGet を叩いて、
 * 実際に配信されているコードのバージョンを検証する。
 * ─────────────────────────────────────────────────────────────
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

function run(cmd, args, opts = {}) {
  return execFileSync(cmd, args, {
    cwd: ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    ...opts
  });
}

function die(msg, detail) {
  console.error('\n✗ ' + msg);
  if (detail) console.error(String(detail).trim().split('\n').slice(0, 10).join('\n'));
  process.exit(1);
}

// --- ローカルの SCRIPT_VERSION を読む ---
const src = readFileSync(join(ROOT, 'slack_inbox_to_notion.gs'), 'utf8');
const localVersion = (src.match(/^var SCRIPT_VERSION\s*=\s*'([^']+)'/m) || [])[1];
if (!localVersion) die('slack_inbox_to_notion.gs から SCRIPT_VERSION を読めませんでした。');
console.log('ローカルの SCRIPT_VERSION: ' + localVersion);

// --- .env.local から secret / DEPLOYMENT_ID を読む(値は表示しない) ---
const env = {};
const envPath = join(ROOT, '.env.local');
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const t = line.trim();
    if (t === '' || t.startsWith('#')) continue;
    const i = t.indexOf('=');
    if (i === -1) continue;
    let v = t.slice(i + 1).trim().replace(/^["']|["']$/g, '');
    if (/^<.*>$/.test(v)) v = '';
    env[t.slice(0, i).trim()] = v;
  }
}

// --- 1. push ---
console.log('\n[1/3] clasp push …');
try {
  console.log(run('npx', ['clasp', 'push', '-f']).trim());
} catch (err) {
  die('clasp push に失敗しました。', (err.stdout || '') + (err.stderr || ''));
}

// --- 2. 既存デプロイを更新(URL 不変) ---
console.log('\n[2/3] 既存デプロイを新バージョンに更新 …');
let deployments;
try {
  deployments = run('npx', ['clasp', 'deployments']);
} catch (err) {
  die('clasp deployments に失敗しました。', (err.stdout || '') + (err.stderr || ''));
}

const versioned = [];
for (const line of deployments.split(/\r?\n/)) {
  const m = line.match(/^\s*-\s+(\S+)\s+@(\S+)/);
  if (m && m[2] !== 'HEAD') versioned.push({ id: m[1], line: line.trim() });
}

let target = env.DEPLOYMENT_ID || '';
if (!target) {
  if (versioned.length === 1) {
    target = versioned[0].id;
  } else if (versioned.length === 0) {
    die(
      'バージョン付きデプロイがありません。初回だけ次を実行してください:\n' +
      '    npm run deploy\n' +
      '  そのあと Slack に Request URL を登録し、以降は npm run release を使います。'
    );
  } else {
    die(
      'バージョン付きデプロイが ' + versioned.length + ' 件あります。どれを更新すべきか決められません。\n' +
      '  .env.local に DEPLOYMENT_ID=<Slack に登録している方のID> を追記してください。\n\n' +
      deployments.trim()
    );
  }
}

console.log('更新対象デプロイ: ' + target);
try {
  console.log(run('npx', ['clasp', 'deploy', '-i', target, '-d', 'release ' + localVersion]).trim());
} catch (err) {
  die('clasp deploy に失敗しました。', (err.stdout || '') + (err.stderr || ''));
}

// --- 3. 配信中のコードを検証 ---
console.log('\n[3/3] 配信中のコードを検証 …');
let url = 'https://script.google.com/macros/s/' + target + '/exec';
if (env.REQUEST_SECRET) url += '?secret=' + encodeURIComponent(env.REQUEST_SECRET);

let body = '';
try {
  // -L: GAS は googleusercontent へリダイレクトする
  body = run('curl', ['-sSL', '--max-time', '30', url]);
} catch (err) {
  console.warn('⚠ 検証リクエストに失敗しました(デプロイ自体は完了しています)。');
  console.warn('  手動で確認するには: npm run verify:deployed');
  process.exit(0);
}

let info;
try {
  info = JSON.parse(body);
} catch (err) {
  die(
    '配信中のコードがバージョン情報を返しませんでした。\n' +
    '  doGet を持たない古いコードが配信されている可能性があります。\n' +
    '  応答の先頭: ' + body.slice(0, 200)
  );
}

if (info.version !== localVersion) {
  die(
    'デプロイは成功しましたが、配信中のバージョンがローカルと一致しません。\n' +
    '  ローカル : ' + localVersion + '\n' +
    '  配信中   : ' + info.version + '\n' +
    '  別のデプロイIDを Slack に登録している可能性があります。'
  );
}

console.log('✓ 配信中のコード = ローカル(' + info.version + ')');
console.log('  リアクション: ' + info.reaction + ' / 対象チャンネル: ' + info.channelFilter);
console.log('\n✓ リリース完了。URL は変わっていないので Slack 側の再設定は不要です。');
