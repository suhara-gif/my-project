# my-project

Claude Code / Fable のローカル運用を支える、自己完結な「キット」集です。

| キット | 役割 |
|---|---|
| [`claude-backup/`](claude-backup/) | ローカルの Claude データ(設定・スキル・スケジュール)を自動でクラウドへ退避し、変更履歴を Notion 台帳に残す |
| [`second-brain/`](second-brain/) | Obsidian の Markdown フォルダを「セカンドブレイン」にする vault 構造・4 つのルール・維持ループ(セッション採掘 / 夜間コンパイル / 週次 lint・総合)とリサーチ機 |
| [`slack-inbox-to-notion/`](slack-inbox-to-notion/) | Slack で 📥 を押したメッセージを Notion タスクDB に INBOX として登録する(Slack Events API + Google Apps Script + Notion API) |

`claude-backup/` と `second-brain/` はローカルPCで動くシェルスクリプト
(macOS bash 3.2 / Linux 両対応)、`slack-inbox-to-notion/` は Google Apps Script です。
それぞれの `README.md` に導入手順があります。
