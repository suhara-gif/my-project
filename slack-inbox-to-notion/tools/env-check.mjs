#!/usr/bin/env node
/**
 * .env.local の設定状況を、値を表示せずに確認する。
 *
 *   npm run env:check
 *
 * これを npm script として用意してあるのは、同じことを `node -e "..."` の
 * ワンライナーでやると zsh が壊すため。zsh はダブルクォート内の `!` を
 * 履歴展開として解釈するので、`if (!x)` を含むワンライナーが
 * `zsh: event not found` で落ちる(実際に踏んだ)。
 */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const DST = join(ROOT, '.env.local');

if (!existsSync(DST)) {
  console.error('✗ .env.local がありません。先に `npm run env:init` を実行してください。');
  process.exit(1);
}

const REQUIRED = [
  'SLACK_BOT_TOKEN',
  'NOTION_API_TOKEN',
  'NOTION_TASK_DATABASE_ID',
  'NOTION_ASSIGNEE_USER_ID',
  'ALLOWED_SLACK_USER_ID',
  'TARGET_REACTION',
  'TARGET_CHANNEL_ID'
];
const RECOMMENDED = ['REQUEST_SECRET', 'TARGET_CHANNEL_NAME'];
const SECRETISH = ['SLACK_BOT_TOKEN', 'NOTION_API_TOKEN', 'REQUEST_SECRET'];

const env = {};
for (const line of readFileSync(DST, 'utf8').split(/\r?\n/)) {
  const t = line.trim();
  if (t === '' || t.startsWith('#')) continue;
  const i = t.indexOf('=');
  if (i === -1) continue;
  let v = t.slice(i + 1).trim().replace(/^["']|["']$/g, '');
  if (/^<.*>$/.test(v)) v = '';
  env[t.slice(0, i).trim()] = v;
}

let missing = 0;
const show = (k, required) => {
  const v = env[k] || '';
  if (v === '') {
    if (required) missing++;
    console.log(`  ✗ ${k}  ← 未入力`);
    return;
  }
  // 値は出さない。秘密でないものだけそのまま、秘密は長さのみ。
  const detail = SECRETISH.includes(k) ? `(${v.length}文字)` : v;
  console.log(`  ✓ ${k}  ${detail}`);
};

console.log('必須:');
REQUIRED.forEach((k) => show(k, true));
console.log('推奨:');
RECOMMENDED.forEach((k) => show(k, false));

if (env.REQUEST_SECRET) {
  if (/[&?#/\s]/.test(env.REQUEST_SECRET)) {
    console.error('\n✗ REQUEST_SECRET に & ? # / 空白 が含まれています。URL のクエリとして壊れます。');
    process.exit(1);
  }
  if (env.REQUEST_SECRET.length < 16) {
    console.error('\n✗ REQUEST_SECRET が短すぎます(16文字以上)。');
    process.exit(1);
  }
}

if (missing) {
  console.error(`\n✗ 必須の未入力が ${missing} 件あります。open -e .env.local で埋めてください。`);
  process.exit(1);
}
console.log('\n✓ 必須項目はすべて設定済みです。次: npm run props:push');
