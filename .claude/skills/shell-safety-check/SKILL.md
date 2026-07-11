---
name: shell-safety-check
description: claude-backup のシェルスクリプトを変更・コミットする前に、このリポジトリ固有の不変条件(macOS bash 3.2 / BSD 移植性、データを失わない、秘密の除外、MCP へバイナリを渡さない、再帰ガード、プロンプト・インジェクション対策、shellcheck 警告ゼロ)を機械的に検証する。claude-backup/*.sh を触ったら実行する。CLAUDE.md の品質バーを実行可能にしたもの。
---

# shell-safety-check — シェル変更の品質ゲート

`claude-backup/*.sh` を変更したら、コミット前にこのチェックを上から順に実行する。
CLAUDE.md の「壊しやすい間違い」と「品質バー」を機械的に確認するためのもの。

## 実行するチェック

1. **構文** — 全スクリプトを構文チェック:
   ```bash
   for f in claude-backup/*.sh; do bash -n "$f" && echo "ok: $f"; done
   ```

2. **shellcheck 警告ゼロ** — CI と同じ:
   ```bash
   shellcheck claude-backup/*.sh
   ```
   新しく `# shellcheck disable=SCxxxx` を足したなら、直前行に**理由コメント**があるか目視確認。

3. **GNU/bash4 依存の混入** — macOS 標準環境で動かない機能を検出(コメント行は除外):
   ```bash
   grep -nE '(mapfile|readarray|flock|realpath|readlink -f|declare -A|grep -P|sed -i[^ ]|date -d |date -Is)' claude-backup/*.sh \
     | grep -vE ':[0-9]+:[[:space:]]*#'
   ```
   ヒット(コメント以外)があれば BSD/GNU 双方に存在する代替へ置き換える(例: 配列一括は
   `ls -1t | tail | while read`、ロックは `mkdir`、日時は `date +%s` / `date +"%...%z"`)。
   これらの語は既存コードでは「不使用」を明記するコメントにのみ現れる(実コードには無い)。

4. **データ保全の不変条件** — 追加した失敗経路すべてで、アーカイブがローカルに残るか目視確認。
   `run-backup.sh` の `UPLOAD_OK=0` 分岐(`STATE_DIR` への `cp`)が生きているか:
   ```bash
   grep -nE 'UPLOAD_OK|STATE_DIR' claude-backup/run-backup.sh
   ```

5. **秘密の除外を弱めていない** — 除外パターンが揃っているか:
   ```bash
   grep -nE "exclude=.*(\.claude\.json|token|credential|\.key)" claude-backup/run-backup.sh
   ```
   4パターン(`.claude.json` / `*token*` / `*credential*` / `*.key`)が残っていること。減っていたら差し戻す。

6. **MCP へバイナリを渡していない / 権限を広げていない** — `claude -p` の許可ツールを確認:
   ```bash
   grep -nE 'allowedTools|claude -p|rclone|cp ' claude-backup/run-backup.sh
   ```
   `--allowedTools` が `mcp__${NOTION_MCP}` の範囲を超えていないこと。実ファイル転送が
   同期フォルダ `cp` か `rclone` に限られていること。

7. **SessionEnd 再帰ガード** — 子起動に `CLAUDE_BACKUP_RUNNING=1` が付き、冒頭ガードが生きているか:
   ```bash
   grep -nE 'CLAUDE_BACKUP_RUNNING' claude-backup/run-backup.sh
   ```
   冒頭の早期 exit と、`claude -p` 起動時の付与の**両方**が残っていること。

8. **プロンプト・インジェクション対策** — `claude -p` プロンプトが静的テンプレ + `${//}` 置換で
   組まれているか(差分値を素の変数展開で連結していないか)目視確認:
   ```bash
   grep -nE 'TEMPLATE|@@|PROMPT=\$\{PROMPT//' claude-backup/run-backup.sh
   ```

9. **可能なら実走** — 破壊しないダミーで試走してログを確認:
   ```bash
   tmp=$(mktemp -d); mkdir -p "$tmp/.claude"; echo hi > "$tmp/.claude/x";
   CLAUDE_BACKUP_SRC="$tmp/.claude" CLAUDE_BACKUP_STATE="$tmp/state" \
     CLAUDE_BACKUP_MIN_INTERVAL=0 bash claude-backup/run-backup.sh;
   tail -n 20 "$tmp/state/backup.log"
   ```
   `[ok]` か、転送先未設定なら `[warn] クラウド転送手段が未設定` + ローカル保持を確認。

## 完了条件

- [ ] 1〜3 が警告なしで通る。
- [ ] 4〜8 の不変条件が目視で保たれている。
- [ ] 9 を実行したなら、失敗経路でもアーカイブがローカルに残ることを確認した。
- [ ] いずれかで判断に迷ったら、CLAUDE.md のエスカレーション規則に従い人間に確認する。
