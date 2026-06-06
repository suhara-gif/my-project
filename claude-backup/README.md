# Claude バックアップ仕組み (claude-backup)

Claude Code / Cowork の**ローカルデータ(設定・スキル・スケジュール定義など)を
自動でクラウドへ退避し、変更履歴を Notion に台帳として残す**ための仕組みです。
手で寄せるのではなく、**イベントで自動発火 → Claude が差分判定 → クラウド保存 +
Notion 台帳記録**を回します。

## なぜ必要か

`~/.claude/`(設定・トランスクリプト・スキル)やデスクトップのスケジュールタスクは
**ローカルPCに保存**され、組み込みのクラウド同期・バックアップはありません
(設定ファイルの直近5世代ローカルバックアップはあるが同一ディスク上なので、
PCクラッシュ対策にはならない)。クラウドの Routine だけは Anthropic 側に残ります。
→ **ローカルにあるものは自分で守る仕組みが要る。**

## アーキテクチャ(責務分離)

```
①トリガ層(機械的・確実)   SessionEnd フック + 日次 cron/launchd
        ↓
②判定層(Claudeが知的判定) claude -p が前回からの差分を検出・要約
        ↓
③保存層(2系統に分離)
     実体(tar.gz)  → Google Drive / Box
     台帳(履歴)    → Notion DB「Claudeバックアップ台帳」
```

- **確実にやるべき固め+秘密情報の除外**はシェル(`run-backup.sh`)で機械的に。
- **差分判定・要約・アップロード先振り分け・台帳記録**は Claude + MCP で知的に。
- **秘密情報**(`~/.claude.json` の OAuth トークン等)は**アーカイブから除外**。
  任意で `age` 暗号化も可能。復元後は `claude login` で再認証する。

## 構成ファイル

| ファイル | 役割 |
|---|---|
| `run-backup.sh` | バックアップ本体。①の固め+除外、②の Claude 委譲、後始末。 |
| `restore.sh` | アーカイブから `~/.claude` を復元。age 復号対応。 |
| `install.sh` | ローカルへ配置し、SessionEnd フック+日次 cron を有効化。 |
| `settings.snippet.json` | `~/.claude/settings.json` に手動マージする用の hooks 断片。 |

## インストール(ローカルPCで実行)

> 守る対象は**あなたのローカル** `~/.claude/` です。クラウドセッションではなく
> ローカルマシンで実行してください。

```bash
git clone <this-repo> && cd <this-repo>/claude-backup
./install.sh
```

`install.sh` がやること:
1. `run-backup.sh` / `restore.sh` を `~/.claude/backup/` へ配置
2. `~/.claude/settings.json` に SessionEnd フックをマージ(jq 使用)
3. 日次 cron(毎日 09:30)を登録 ※macOS/Win は launchd/タスクスケジューラで代替

### 設定(環境変数)

| 変数 | 既定 | 説明 |
|---|---|---|
| `CLAUDE_BACKUP_DEST` | `googledrive` | `googledrive` または `box` |
| `CLAUDE_BACKUP_DEST_FOLDER` | `ClaudeBackups` | 保存先フォルダ名 |
| `CLAUDE_BACKUP_NOTION_LEDGER` | `Claudeバックアップ台帳` | Notion 台帳DB名 |
| `CLAUDE_BACKUP_AGE_RECIPIENT` | (空) | 設定すると age 暗号化を有効化 |
| `CLAUDE_BACKUP_MIN_INTERVAL` | `1800` | 連発時にスキップする最小間隔(秒) |
| `CLAUDE_BACKUP_RETAIN_LOCAL` | `5` | ローカルに残す世代数 |

## Notion 台帳のスキーマ

初回実行時、なければ自動作成されます(`claude -p` 経由)。

| プロパティ | 型 | 例 |
|---|---|---|
| 日時 | date | 2026-06-06 23:10 |
| 種別 | select | フルバックアップ / 設定変更 / スケジュール変更 |
| 変更サマリ | rich_text | 日次レポートのRoutineを1件追加 |
| 変更ファイル | rich_text | settings.json, scheduled-tasks.json |
| アーカイブリンク | url | (Drive/Box の該当ファイル) |
| サイズ | rich_text | 4.2M |
| 状態 | select | 成功 / 失敗 |

## 復元

PC を入れ替えた/クラッシュした場合:

1. Notion 台帳で復元したい時点の行を開き、アーカイブをダウンロード。
2. 復元:
   ```bash
   ./restore.sh ~/Downloads/claude-backup-YYYYMMDD-HHMMSS.tar.gz
   ```
3. `claude login` で再認証(トークンはバックアップに含まれないため)。

## 前提ツール

- `claude` CLI(MCP: Notion + Google Drive/Box を有効化済み)
- `tar`, `flock`, `jq`(install 用), 任意で `age`, `cron`/`launchd`

## 設計上の割り切り

- `claude` CLI が無い/失敗しても、**ローカルアーカイブは必ず残す**(データは失わない)。
- 認証情報は意図的にバックアップしない(漏洩リスク回避)。
- クラウドの Routine は元々 Anthropic 側に保持されるため、この仕組みの対象外。
