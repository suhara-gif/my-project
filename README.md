# my-project

個人(須原弘之)の作業リポジトリです。ローカル運用を支える自己完結な「キット」に加えて、
AI秘書やエージェントシステムなど複数のプロジェクトが同居しています。

| ディレクトリ | 役割 |
|---|---|
| [`claude-backup/`](claude-backup/) | ローカルの Claude データ(設定・スキル・スケジュール)を自動でクラウドへ退避し、変更履歴を Notion 台帳に残す |
| [`second-brain/`](second-brain/) | Obsidian の Markdown フォルダを「セカンドブレイン」にする vault 構造・4 つのルール・維持ループ(セッション採掘 / 夜間コンパイル / 週次 lint・総合)とリサーチ機 |
| [`company/`](company/) | AI秘書「アプ子」まわりの設定・ナレッジ・日報 |
| [`fable5-agent-system/`](fable5-agent-system/) | Claude API 上の自己改善型エージェントシステムの実装(Python) |

`claude-backup/` と `second-brain/` はローカルPCで動くシェルスクリプト(macOS bash 3.2 /
Linux 両対応)で、それぞれの `README.md` に導入手順があります。全体の運用ルールは
[`CLAUDE.md`](CLAUDE.md) を参照してください。
