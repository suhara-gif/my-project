#!/usr/bin/env node
/**
 * 秘密情報の実値が入った使い捨てファイル setup.local.gs をローカルから削除する。
 * このあと `clasp push -f` が走ることで、GAS プロジェクト側からも消える
 * (clasp push はローカルに無いファイルをリモートから削除するため)。
 *
 * npm run props:clean から呼ばれる。
 */
import { existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const TARGET = join(dirname(fileURLToPath(import.meta.url)), '..', 'setup.local.gs');

if (existsSync(TARGET)) {
  rmSync(TARGET, { force: true });
  console.log('✓ setup.local.gs をローカルから削除しました');
} else {
  console.log('· setup.local.gs は既にありません');
}
console.log('  続けて clasp push が走り、GAS プロジェクトからも削除されます。');
