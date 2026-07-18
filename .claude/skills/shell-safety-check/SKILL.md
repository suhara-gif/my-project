---
name: shell-safety-check
description: claude-backup のシェルスクリプトを変更・コミットする前に、このリポジトリ固有の不変条件(macOS bash 3.2 / BSD 移植性、データを失わない、秘密の除外、MCP へバイナリを渡さない、再帰ガード、プロンプト・インジェクション対策、shellcheck 警告ゼロ)を機械的に検証する。claude-backup/*.sh を触ったら実行する。CLAUDE.md の品質バーを実行可能にしたもの。
---

# shell-safety-check — シェル変更の品質ゲート

`claude-backup/*.sh` を変更したら、**コミット前に**同梱スクリプトを走らせ、出力を読む。
CLAUDE.md の「壊しやすい間違い」と「品質バー」を、目視ではなく実行可能なチェックに落としたもの。

## 実行

```bash
.claude/skills/shell-safety-check/scripts/check.sh            # 静的チェック一式(高速・副作用なし)
.claude/skills/shell-safety-check/scripts/check.sh --dry-run  # + 破壊しないダミー実走(下記9)
```

リポジトリのどこから呼んでもよい(スクリプトが `git rev-parse` でルートへ移動する)。
終了コード: 不変条件を満たさなければ `1`、満たせば `0`。出力の `[FAIL]`/`[warn]` を必ず読む。

## スクリプトが検証する不変条件

| # | チェック | 何を守るか |
|---|---------|-----------|
| 1 | `bash -n` 構文 | 壊れた構文で push しない |
| 2 | shellcheck 警告ゼロ(CI と同じ) | 未インストールなら警告してスキップ |
| 3 | GNU/bash4 依存の非混入(コメント除外) | macOS bash 3.2 / BSD で動く |
| 4 | `UPLOAD_OK=0` 分岐で `STATE_DIR` へ退避 | どの失敗経路でもデータを失わない |
| 5 | 除外 4 パターン(`.claude.json`/`*token*`/`*credential*`/`*.key`) | 秘密をアーカイブに含めない |
| 6 | `--allowedTools` が `mcp__${NOTION_MCP}` 限定 / 転送は cp・rclone | MCP へバイナリを渡さない・権限を広げない |
| 7 | `CLAUDE_BACKUP_RUNNING` の早期 exit + 子への付与 | SessionEnd フックの無限再帰を防ぐ |
| 8 | 静的テンプレ heredoc + `${//}` 置換 | プロンプト・インジェクション / `set -u` クラッシュを防ぐ |
| 9 | (`--dry-run` 時)ダミー実走で `[done]` 到達 + ローカル保全 | 失敗経路でもアーカイブが残ることを実地確認 |

チェックの根拠と対処法は CLAUDE.md「壊しやすい間違い(名前付き)」を参照。
`[FAIL]` が出たら、そのチェックが守っている不変条件を壊しているということ。安全側
(データを残す / 除外を強める / 権限を狭める)に倒して直す。

補足:
- `--dry-run`(9)は `mktemp` の使い捨てディレクトリに対して `run-backup.sh` を実走する。
  環境に `claude` CLI があれば台帳記録を試みる(副作用として実 CLI を起動しうる)ため、
  純粋な静的確認だけしたいときは引数なしで実行する。
- 対象は `claude-backup/*.sh`。`second-brain/*.sh` は CI の shellcheck 対象だが、
  本スキルの不変条件(秘密除外・再帰ガード等)は `run-backup.sh` 固有のためここでは対象外。

## 完了条件

- [ ] `check.sh`(引数なし)が `FAIL=0` で終了する。
- [ ] `[warn]` があれば内容を確認した(shellcheck 未導入なら CI に委ねる旨を認識)。
- [ ] 失敗経路を追加・変更したなら `--dry-run` も実行し、ローカル保全を確認した。
- [ ] いずれかで判断に迷ったら、CLAUDE.md のエスカレーション規則に従い人間に確認する。
