#!/usr/bin/env node
/**
 * いま Slack が実際に叩いているコードが、ローカルの最新と一致しているか確認する。
 *
 *   npm run verify:deployed
 *
 * GAS は push してもデプロイ済み Web App に反映されないため、
 * 「ローカルは直っているのに本番は古い」というズレが起きる。
 * doGet が返す SCRIPT_VERSION とローカルの値を突き合わせて、それを検出する。
 *
 * 動かない気がしたら、まずこれを実行すること。
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

const src = readFileSync(join(ROOT, 'slack_inbox_to_notion.gs'), 'utf8');
const localVersion = (src.match(/^var SCRIPT_VERSION\s*=\s*'([^']+)'/m) || [])[1] || '(不明)';

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

let deployments;
try {
  deployments = execFileSync('npx', ['clasp', 'deployments'], {
    cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
  });
} catch (err) {
  console.error('✗ clasp deployments に失敗しました。npm install / npm run login / .clasp.json を確認してください。');
  process.exit(1);
}

const versioned = [];
for (const line of deployments.split(/\r?\n/)) {
  const m = line.match(/^\s*-\s+(\S+)\s+@(\S+)/);
  if (m && m[2] !== 'HEAD') versioned.push(m[1]);
}

const target = env.DEPLOYMENT_ID || versioned[versioned.length - 1];
if (!target) {
  console.error('✗ バージョン付きデプロイが見つかりません。先に npm run deploy を実行してください。');
  process.exit(1);
}

let url = 'https://script.google.com/macros/s/' + target + '/exec';
if (env.REQUEST_SECRET) url += '?secret=' + encodeURIComponent(env.REQUEST_SECRET);

let body;
try {
  body = execFileSync('curl', ['-sSL', '--max-time', '30', url], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
  });
} catch (err) {
  console.error('✗ Web App に到達できませんでした。');
  process.exit(1);
}

if (body.trim() === 'forbidden') {
  console.error('✗ forbidden が返りました。.env.local の REQUEST_SECRET と');
  console.error('  GAS のスクリプト プロパティの値がずれています。');
  process.exit(1);
}

let info;
try {
  info = JSON.parse(body);
} catch (err) {
  console.error('✗ バージョン情報が返りませんでした。doGet を持たない古いコードが配信されています。');
  console.error('  → npm run release で最新を配信してください。');
  console.error('  応答の先頭: ' + body.slice(0, 150));
  process.exit(1);
}

console.log('デプロイID  : ' + target);
console.log('ローカル    : ' + localVersion);
console.log('配信中      : ' + info.version);
console.log('リアクション: ' + info.reaction);
console.log('対象チャンネル: ' + info.channelFilter);

if (info.version !== localVersion) {
  console.error('\n✗ ズレています。ローカルの修正が本番に反映されていません。');
  console.error('  → npm run release を実行してください(URL は変わりません)。');
  process.exit(1);
}
console.log('\n✓ 一致しています。ローカルの最新コードが配信されています。');
