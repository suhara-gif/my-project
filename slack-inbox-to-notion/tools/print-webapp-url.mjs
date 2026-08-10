#!/usr/bin/env node
/**
 * `clasp deployments` の出力から Web App の /exec URL を組み立てて表示する。
 * Slack の Request URL 欄に貼る文字列を、手で組み立てなくて済むようにするためのもの。
 *
 *   npm run url        … ベースURL(…/exec)だけ表示
 *   npm run url:full   … .env.local の REQUEST_SECRET を読んで ?secret=… まで付けて表示
 *                        (端末に秘密が出るので、画面共有中は使わないこと)
 */
import { execFileSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const withSecret = process.argv.includes('--with-secret');

let out;
try {
  // stderr も捕まえる(捕まえないと npx の生エラーがそのまま画面に出て分かりにくい)
  out = execFileSync('npx', ['clasp', 'deployments'], {
    cwd: ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  });
} catch (err) {
  const detail = String((err && err.stdout) || '') + String((err && err.stderr) || '');
  console.error('✗ clasp deployments に失敗しました。次を順に確認してください。');
  console.error('  1. npm install を実行したか(clasp が入っていないと動きません)');
  console.error('  2. .clasp.json があるか(npm run create か clone で作られます)');
  console.error('  3. npm run login 済みか');
  if (detail.trim()) {
    console.error('\n--- clasp の出力 ---\n' + detail.trim().split('\n').slice(0, 8).join('\n'));
  }
  process.exit(1);
}

// 例) - AKfycbx... @1 - slack-inbox-to-notion
//     - AKfycbx... @HEAD
const deployments = [];
for (const line of out.split(/\r?\n/)) {
  const m = line.match(/^\s*-\s+(\S+)\s+@(\S+)/);
  if (m) deployments.push({ id: m[1], version: m[2], line: line.trim() });
}

const versioned = deployments.filter((d) => d.version !== 'HEAD');
if (!versioned.length) {
  console.error('✗ バージョン付きのデプロイが見つかりません(@HEAD はテスト用で Slack からは使えません)。');
  console.error('  先に `npm run deploy` を実行してください。');
  console.error('\nclasp deployments の出力:\n' + out.trim());
  process.exit(1);
}

// 最後に作られたものを最新とみなす
const latest = versioned[versioned.length - 1];
const base = `https://script.google.com/macros/s/${latest.id}/exec`;

console.log('デプロイ: ' + latest.line);
console.log('\nWeb App URL(ベース):');
console.log('  ' + base);

let secret = '';
const envPath = join(ROOT, '.env.local');
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const t = line.trim();
    if (t.startsWith('#')) continue;
    const m = t.match(/^REQUEST_SECRET\s*=\s*(.+)$/);
    if (m) {
      secret = m[1].trim().replace(/^["']|["']$/g, '');
      if (/^<.*>$/.test(secret)) secret = '';
    }
  }
}

console.log('\nSlack の Request URL 欄に貼る値:');
if (withSecret && secret) {
  console.log('  ' + base + '?secret=' + secret);
} else if (secret) {
  console.log('  ' + base + '?secret=<REQUEST_SECRET の値>');
  console.log('  (実値付きで表示するには: npm run url:full)');
} else {
  console.log('  ' + base + '?secret=<REQUEST_SECRET の値>');
  console.log('  ※ .env.local に REQUEST_SECRET が見つかりませんでした。');
  console.log('    共有シークレットを使わない場合は ?secret=… を付けずにベースURLを貼ります。');
}

if (versioned.length > 1) {
  console.log('\n⚠ バージョン付きデプロイが ' + versioned.length + ' 件あります。');
  console.log('  Slack に登録済みの URL と一致しているか確認してください。');
  console.log('  URL を変えたくないときは「新しいデプロイ」ではなく既存デプロイの更新を使います。');
}
