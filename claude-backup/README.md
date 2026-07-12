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

- **固め+秘密情報の除外+クラウド転送**はシェル(`run-backup.sh`)で機械的に。
- **差分判定・要約・台帳記録**だけを Claude + Notion MCP で知的に。
- **バイナリ転送は LLM/MCP に任せない**。MCP コネクタはバイナリ非対応なので、
  実ファイルは「デスクトップ同期フォルダへの cp」か「rclone」で確実に転送する。
- **秘密情報**(`~/.claude.json` の OAuth トークン等)は**アーカイブから除外**。
  任意で `age` 暗号化も可能。復元後は `claude login` で再認証する。
- **復元手順.txt** を転送先フォルダ直下に自動配置(データの隣に手順書)。PCが
  壊れても、Drive を開けば「これは何/どう戻すか」がその場で分かる。

### クラウド転送の2方式(どちらか一方を設定)

| 方式 | 設定 | 向き |
|---|---|---|
| **同期フォルダへ cp**(推奨・追加ツール不要) | `CLAUDE_BACKUP_LOCAL_SYNC_DIR` に Google Drive / Box デスクトップアプリの同期フォルダを指定 | Drive/Box デスクトップアプリを使っている人 |
| **rclone** | `rclone config` で remote を作成し `CLAUDE_BACKUP_RCLONE_REMOTE` に remote 名を指定 | デスクトップアプリ無しでCLI転送したい人 |

どちらも未設定なら、アーカイブはローカル(`~/.claude/backup/`)に世代保持され、
Notion 台帳には「失敗(クラウド未転送・ローカル保持のみ)」と記録される(データは失わない)。

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
| `CLAUDE_BACKUP_MACHINE` | `hostname` | マシン識別ラベル。保存先サブフォルダと台帳に使用(複数PC分離用) |
| `CLAUDE_BACKUP_LOCAL_SYNC_DIR` | (空) | Drive/Box 同期フォルダのパス。設定するとそこへ cp(推奨) |
| `CLAUDE_BACKUP_RCLONE_REMOTE` | (空) | rclone の remote 名。同期フォルダ未設定時に使用 |
| `CLAUDE_BACKUP_DEST_FOLDER` | `ClaudeBackups` | 保存先サブフォルダ名 |
| `CLAUDE_BACKUP_NOTION_LEDGER` | `Claudeバックアップ台帳` | Notion 台帳DB名 |
| `CLAUDE_BACKUP_NOTION_MCP` | `Notion` | Notion の MCP サーバー名(`claude mcp list` の表示名) |
| `CLAUDE_BACKUP_AGE_RECIPIENT` | (空) | 設定すると age 暗号化を有効化 |
| `CLAUDE_BACKUP_MIN_INTERVAL` | `1800` | 連発時にスキップする最小間隔(秒) |
| `CLAUDE_BACKUP_RETAIN_LOCAL` | `5` | ローカルに残す世代数 |
| `CLAUDE_BACKUP_EXTRA_EXCLUDES` | (空) | tar の追加除外パターン(空白区切り) |
| `CLAUDE_BACKUP_CLAUDE_BIN` | (自動探索) | claude CLI の実体パス。launchd/cron は PATH を引き継がないため、台帳記録が「claude CLI 不在」でスキップされる場合は config に明示する |

> Notion MCP サーバー名は `claude mcp list` の表示名に一致させること(台帳記録の
> `--allowedTools` 照合に使用)。**実ファイルのアップロードに MCP は使わない**
> (バイナリ非対応のため)。転送は同期フォルダ cp か rclone で行う。

## 複数マシンで使う

各PCにこのキットを個別にインストールする(守る対象は各PCのローカル `~/.claude/`)。
同じ Google Drive / Notion 台帳を共有しても、`CLAUDE_BACKUP_MACHINE` でマシンごとに
分離される:

- Drive: `ClaudeBackups/<マシン名>/` にマシン別サブフォルダで保存
- Notion: 台帳の「マシン」列と、エントリ名「<マシン名> <日時>」で識別

各PCの `~/.claude/backup/config` に `CLAUDE_BACKUP_MACHINE="母艦"` のように設定する
(未設定なら hostname)。

## 対応プラットフォーム

macOS(BSD userland / 標準 bash 3.2)と Linux(GNU)の両対応。`flock` / `mapfile` /
`date -Is` といった GNU・bash4 専用機能は使っていない。日次スケジュールは
**macOS では launchd**、それ以外では cron を `install.sh` が自動登録する。

## Notion 台帳のスキーマ

台帳DBは**作成済み**です: [Claudeバックアップ台帳](https://app.notion.com/p/3a76063ad84541f5b0323508e3b2ee05)
(フォーマット確認用のサンプル行が1件入っています。確認後は削除可)。
`run-backup.sh` は既定でこのDBに追記します。別DBにしたい場合は
`CLAUDE_BACKUP_NOTION_LEDGER_URL` を上書き、空にすると名前検索/自動作成にフォールバックします。

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
