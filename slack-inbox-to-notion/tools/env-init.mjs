#!/usr/bin/env node
/**
 * .env.local を用意し、共有シークレット(REQUEST_SECRET)を自動生成して書き込む。
 *
 *   npm run env:init
 *
 * シークレットは**画面に一切表示しない**。表示するとターミナルのスクロールバックや
 * 画面共有・スクリーンショット経由で漏れるため(実際に一度チャットへ流出させた)。
 * 値が必要になる場面は「Slack の Request URL を組み立てるとき」だけで、そこは
 * `npm run url:full` が .env.local から読んで組み立てるので、人間が見る必要はない。
 *
 * 既に .env.local がある場合は上書きしない(--force で REQUEST_SECRET だけ再生成)。
 */
import { existsSync, copyFileSync, readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = join(ROOT, '.env.example');
const DST = join(ROOT, '.env.local');
const force = process.argv.includes('--force');

if (existsSync(DST) && !force) {
  console.log('· .env.local は既にあります(上書きしません)');
  console.log('  シークレットだけ作り直すなら: npm run env:init -- --force');
} else if (!existsSync(DST)) {
  copyFileSync(SRC, DST);
  console.log('✓ .env.example から .env.local を作成しました');
}

// REQUEST_SECRET を生成して埋める(新規作成時、または --force 時)
const text = readFileSync(DST, 'utf8');
const current = (text.match(/^REQUEST_SECRET=(.*)$/m) || [])[1] || '';
const unset = current.trim() === '' || /^<.*>$/.test(current.trim());

if (unset || force) {
  const secret = randomBytes(32).toString('hex');
  writeFileSync(DST, text.replace(/^REQUEST_SECRET=.*$/m, () => 'REQUEST_SECRET=' + secret));
  console.log('✓ REQUEST_SECRET を生成して .env.local に書き込みました(画面には表示しません)');
  if (force) {
    console.log('\n⚠ シークレットを変更したので、以下の両方が必要です:');
    console.log('   1. npm run props:push → GAS エディタで setupPropertiesFromEnvLocal を実行');
    console.log('   2. Slack の Request URL を貼り直す(npm run url:full の出力)');
    console.log('   片方だけだと全イベントが forbidden で弾かれます。');
  }
} else {
  console.log('· REQUEST_SECRET は設定済みです');
}

console.log('\n次: .env.local を開いて <...> の箇所に実値を入れてください');
console.log('    open -e .env.local');
console.log('  そのあと: npm run env:check');
