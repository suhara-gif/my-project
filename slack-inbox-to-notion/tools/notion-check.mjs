#!/usr/bin/env node
/**
 * Slack リンク完全一致で Notion のページを探し、いまの状態をターミナルに出す。
 *
 *   npm run notion:check -- <Slackメッセージのpermalink>
 *   npm run notion:check              # 引数省略時は .env.local の TEST_MESSAGE_URL
 *
 * ── なぜ必要か ────────────────────────────────────────────────
 * Notion の「INBOX」ビューの件数で登録の成否を判定してはいけない。
 * 登録直後に別の主体(オートメーション / 他エージェント / 手動)が
 * ステータスを書き換えることがあり、「INBOX に居ない = 未登録」ではない。
 * 実際にこれで一度、成功を失敗と誤判定した。
 *
 * このツールは GAS の重複判定とまったく同じ条件(Slackリンク完全一致)で
 * 検索するので、判定基準がコード側と一致する。しかも Chrome を開かずに
 * 何度でも実行できるので、「放置して変化を見る」対照実験に使える。
 * ─────────────────────────────────────────────────────────────
 */
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// --- .env.local(値は表示しない) ---
const env = {};
const envPath = join(ROOT, '.env.local');
if (!existsSync(envPath)) {
  console.error('✗ .env.local がありません。npm run env:init から始めてください。');
  process.exit(1);
}
for (const line of readFileSync(envPath, 'utf8').split(/\r?\n/)) {
  const t = line.trim();
  if (t === '' || t.startsWith('#')) continue;
  const i = t.indexOf('=');
  if (i === -1) continue;
  let v = t.slice(i + 1).trim().replace(/^["']|["']$/g, '');
  if (/^<.*>$/.test(v)) v = '';
  env[t.slice(0, i).trim()] = v;
}

const token = env.NOTION_API_TOKEN;
const dbId = env.NOTION_TASK_DATABASE_ID;
if (!token || !dbId) {
  console.error('✗ .env.local に NOTION_API_TOKEN / NOTION_TASK_DATABASE_ID がありません。');
  process.exit(1);
}

const permalink = (process.argv[2] || env.TEST_MESSAGE_URL || '').trim();
if (!permalink) {
  console.error('✗ Slack の permalink を指定してください。');
  console.error('    npm run notion:check -- https://<workspace>.slack.com/archives/C…/p…');
  console.error('  または .env.local に TEST_MESSAGE_URL を設定してください。');
  process.exit(1);
}

const propUrl = env.PROP_SLACK_URL || 'Slackリンク';
const propTitle = env.PROP_TITLE || '名前';
const propStatus = env.PROP_STATUS || 'ステータス';
const version = env.NOTION_VERSION || '2022-06-28';

const res = await fetch(`https://api.notion.com/v1/databases/${dbId}/query`, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${token}`,
    'Notion-Version': version,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    filter: { property: propUrl, url: { equals: permalink } },
    page_size: 5
  })
});

const body = await res.json().catch(() => null);
if (!res.ok) {
  console.error(`✗ Notion API エラー (HTTP ${res.status}): ${(body && body.message) || ''}`);
  if (res.status === 401) console.error('  → NOTION_API_TOKEN を確認してください。');
  if (res.status === 404) console.error('  → タスクDB にインテグレーションを「接続」しているか確認してください。');
  process.exit(1);
}

const results = body.results || [];
console.log('Slackリンク: ' + permalink);

if (!results.length) {
  console.log('\n結果: 未登録(このSlackメッセージに対応するページはありません)');
  process.exit(2);
}

const statusName = (p) => {
  if (!p) return '(不明)';
  if (p.type === 'status') return (p.status && p.status.name) || '(空)';
  if (p.type === 'select') return (p.select && p.select.name) || '(空)';
  if (p.type === 'rich_text') return (p.rich_text || []).map((t) => t.plain_text).join('') || '(空)';
  return `(${p.type} 型)`;
};
const jst = (iso) => {
  if (!iso) return '(不明)';
  return new Date(iso).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo' });
};

const expected = env.NOTION_STATUS_VALUE || 'INBOX';
let drift = false;

console.log(`\n結果: ${results.length} 件`);
for (const page of results) {
  const props = page.properties || {};
  const titleArr = (props[propTitle] || {}).title || [];
  const status = statusName(props[propStatus]);
  console.log('---');
  console.log('  タイトル  : ' + (titleArr.map((t) => t.plain_text).join('') || '(なし)'));
  console.log('  ステータス: ' + status + (status === expected ? '' : `  ← 期待値は ${expected}`));
  console.log('  作成      : ' + jst(page.created_time));
  console.log('  最終更新  : ' + jst(page.last_edited_time));
  console.log('  page id   : ' + page.id);
  if (status !== expected) drift = true;
}

if (results.length > 1) {
  console.warn('\n⚠ 同じ Slackリンクのページが複数あります。重複判定が効いていない可能性があります。');
}

if (drift) {
  console.warn(`\n⚠ ステータスが「${expected}」ではありません。`);
  console.warn('  この連携はページを作成するだけで、作成後の更新は一切行いません');
  console.warn('  (Notion への呼び出しは databases/query と pages の2つのみ)。');
  console.warn('  → 別の主体が書き換えています。作成時刻と最終更新の差を見てください:');
  console.warn('     ほぼ同時   … DB のオートメーション(⚡)の可能性が高い');
  console.warn('     数分〜数十分後 … 定期実行の別処理、または手動操作の可能性が高い');
  process.exit(3);
}

console.log(`\n✓ ステータスは「${expected}」のままです。書き換えは起きていません。`);
