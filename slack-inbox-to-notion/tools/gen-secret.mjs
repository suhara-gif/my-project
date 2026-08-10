#!/usr/bin/env node
/**
 * 共有シークレット(REQUEST_SECRET)用のランダム値を生成して表示する。
 * URL のクエリに入れるので、記号の混ざらない 16進64桁にしてある。
 *
 *   npm run secret
 *
 * 出た値を .env.local の REQUEST_SECRET に貼るだけでよい
 * (Slack の Request URL 側は npm run url:full が自動で組み立てる)。
 */
import { randomBytes } from 'node:crypto';

const secret = randomBytes(32).toString('hex');

console.log('REQUEST_SECRET に設定する値:\n');
console.log('  ' + secret + '\n');
console.log('次の手順:');
console.log('  1. .env.local の REQUEST_SECRET= の行に上の値を貼る');
console.log('  2. npm run props:push で GAS のスクリプト プロパティに反映');
console.log('  3. デプロイ後、npm run url:full で Slack に貼る Request URL を表示');
console.log('\n※ この値はコード・README・GitHub に書かないこと。');
