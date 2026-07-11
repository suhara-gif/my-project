# my-project

Claude Code / Fable のローカル運用を支える、自己完結な「キット」集です。

| キット | 役割 |
|---|---|
| [`claude-backup/`](claude-backup/) | ローカルの Claude データ(設定・スキル・スケジュール)を自動でクラウドへ退避し、変更履歴を Notion 台帳に残す |
| [`second-brain/`](second-brain/) | Obsidian の Markdown フォルダを「セカンドブレイン」にする vault 構造・4 つのルール・維持ループ(セッション採掘 / 夜間コンパイル / 週次 lint・総合)とリサーチ機 |

各キットはローカルPCで動くシェルスクリプト(macOS bash 3.2 / Linux 両対応)で、
それぞれの `README.md` に導入手順があります。
