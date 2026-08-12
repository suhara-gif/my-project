---
paths:
  - "claude-backup/*.sh"
  - "claude-backup/**/*.sh"
  - "second-brain/*.sh"
  - "second-brain/**/*.sh"
---

# シェルキットの規則（claude-backup / second-brain）

このファイルは `claude-backup/` と `second-brain/` の **`.sh` を読んだときに読み込まれる**
path-scoped ルール。ルート CLAUDE.md から切り出したもので、内容は変えていない。
両キットが同じ不変条件(BSD/GNU 両対応・データを失わない・秘密の除外)を共有し、
CI も両方を対象にしているため、キットごとに分けず1ファイルに束ねている。

## 壊しやすい間違い（名前付き）と、それを防ぐ規則

弱いモデルがこのコードベースで犯しがちな具体的ミス。各項目の「規則」がそれを防ぐ。

1. **GNU/bash4 依存の混入。**
   `mapfile`/`readarray`、`flock`、`date -Is` や `date -d`、`sed -i`(引数なし)、
   `grep -P`、`realpath`、`readlink -f`、連想配列 `declare -A` は macOS 標準環境で動かない。
   - 規則: 配列一括読みは `ls -1t ... | tail -n +N | while read` の形（既存 `run-backup.sh` 参照）。
     ロックは `mkdir "$LOCK_DIR"` のアトミック性で取る(flock 不使用)。日時は
     `date +"%Y-%m-%dT%H:%M:%S%z"` か `date +%s`。**追加する前に BSD/GNU 双方に存在する形か確認する。**

2. **データを失う失敗経路を作ってしまう。**
   クラウド転送や `claude` CLI が失敗したときに、アーカイブを捨ててしまう分岐を書く。
   - 規則: **どの失敗経路でもローカルアーカイブは必ず残す。** 転送不可なら `STATE_DIR` に `cp` し、
     台帳状態を「失敗(ローカル保持のみ)」にする(既存の `UPLOAD_OK` 分岐が基準)。
     「失敗してもデータは失わない」は交渉不可の不変条件。

3. **秘密情報をアーカイブに含める。**
   除外パターンを緩める、あるいは新しい認証ファイルの除外を忘れる。
   - 規則: `.claude.json`・`*token*`・`*credential*`・`*.key` は必ず除外する。新たに秘密を含みうる
     パスが増えたら除外を**追加**する。除外を外す/緩める変更は原則しない(する場合は人間に確認)。

4. **バイナリ転送を MCP/LLM にやらせる。**
   「Notion にアップロードすればいい」と考えてしまう。MCP コネクタはバイナリ非対応。
   - 規則: 実ファイル転送は同期フォルダ `cp` か `rclone` のみ。`claude -p` に渡すのは
     **テキストの台帳記録だけ**で、`--allowedTools "mcp__${NOTION_MCP}"` を超える権限を与えない。

5. **SessionEnd フックの無限再帰。**
   ②で起動する `claude -p` の子セッションが終了時にまた `run-backup.sh` を呼ぶ。
   - 規則: 子は必ず `CLAUDE_BACKUP_RUNNING=1` を付けて起動し、スクリプト冒頭の再帰ガードを保つ。
     このガードや環境変数名を変えない。

6. **`claude -p` プロンプトへのインジェクション / `set -u` クラッシュ。**
   差分テキスト(`$` や `$(...)` を含みうる)を素朴に文字列連結してしまう。
   - 規則: プロンプトは**クォート付き heredoc の静的テンプレ**に `@@PLACEHOLDER@@` を置き、
     `${PROMPT//@@X@@/$value}` で置換する(置換値は再展開されない)。素の変数展開でプロンプトを
     組み立てない。既存 `run-backup.sh` の `TEMPLATE`→`${//}` 方式を踏襲する。

7. **フック/launchd/cron 環境で環境変数が効かないと勘違いする。**
   これらは `~/.zshrc` 等を読まないため、シェルに export しても届かない。
   - 規則: 恒久設定は `~/.claude/backup/config`(KEY=VALUE)に置く。`run-backup.sh` はこれを
     読み込む。新しい設定項目はこの config 経由でも効くようにする。

8. **`install.sh` の非冪等化。**
   フックや cron 行を重複登録してしまう。
   - 規則: settings.json マージは `unique_by(.hooks[0].command)`、cron は既存行を
     `grep -v` で除いてから再追加。再実行しても重複しない状態を保つ。

9. **スケジュール実行で外部 CLI が見つからない(`command -v` 単独依存)。**
   launchd/cron は最小限の PATH でジョブを起動するため、Homebrew や `~/.local/bin` の
   CLI(`claude` 等)は手動実行では見つかってもスケジュール実行では見つからず、
   全ループが安全側スキップになる。初回の自動発火まで露見しない。
   - 規則: 外部 CLI は config に固定した絶対パス → PATH → 既知の設置場所、の
     **3段フォールバック**で解決する(`second-brain/lib.sh` の `sb_resolve_claude` /
     `run-backup.sh` の `CLAUDE_BIN` 解決が基準)。install 時に `command -v` の結果を
     config へ書き込む。検証は手動実行でなく `launchctl kickstart` で行う。
     詳細: docs/learnings/20260712-launchd-cron-path-not-inherited.md

プロンプトに専門家ペルソナを付けない規則(キット横断)はルート CLAUDE.md にある。

## 品質バー: シェルスクリプトの変更

`claude-backup/*.sh` / `second-brain/*.sh` を触ったら、コミット前に全項目を満たすこと。

- [ ] `shellcheck claude-backup/*.sh` と `shellcheck second-brain/*.sh` が警告ゼロ
      (新規 disable には理由コメント併記)。CI はこの2つを実行する
      (`.github/workflows/shellcheck.yml`)。
- [ ] 追加/変更したコマンドが macOS(bash 3.2 / BSD)と Linux の両方に存在する。
- [ ] 追加した失敗経路すべてでローカルアーカイブが保全される。
- [ ] 秘密除外パターンを弱めていない(むしろ必要なら追加している)。
- [ ] `claude -p` に渡す文字列は静的テンプレ + `${//}` 置換で組んでいる。
- [ ] プロンプトに専門家ペルソナを足していない(役割 + 手順 + 出力形式で書いている)。
- [ ] 可能なら実際に実行して確認: `bash -n` 構文チェック + `run-backup.sh` を
      `CLAUDE_BACKUP_SRC=<小さなダミー>` で試走し、ログの `[ok]/[warn]` を確認。

コミット前の機械的確認には `shell-safety-check` スキルを使う
(定義は `.claude/skills/shell-safety-check/SKILL.md`)。
