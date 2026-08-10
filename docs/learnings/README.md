# 学びノート (docs/learnings)

このリポジトリで非自明な問題を解いたときに残す、**1問1ノート**のアトミックな記録置き場です。
解いた答えそのものより、次に同種の問題へ当たったときに効く**推論と判断基準**を残します。

- 書き方・テンプレートは `.claude/skills/extract-approach/SKILL.md` を参照。
- CLAUDE.md の learning law により、非自明な解決のたびにここへ1件追加します
  (学びノートの無い解決は未完了とみなす)。
- ファイル名は `<YYYYMMDD>-<短いスラッグ>.md`(例 `20260711-bsd-date-portability.md`)。

## ノート一覧

| ノート | 一言 |
|---|---|
| [20260712-launchd-cron-path-not-inherited.md](20260712-launchd-cron-path-not-inherited.md) | launchd/cron は PATH を継承しない。外部CLIは3段フォールバックで解決する |
| [20260730-gas-dopost-no-headers-slack-retry.md](20260730-gas-dopost-no-headers-slack-retry.md) | GAS の `doPost` はHTTPヘッダを読めない。Webhookは「速く返す」でなく「冪等」で守る |
| [20260731-two-system-setup-dependency-cycle.md](20260731-two-system-setup-dependency-cycle.md) | 2サービスの設定が相互依存したら、定義ファイルを循環の切れ目で2段に割る |
| [20260731-gas-push-does-not-deploy.md](20260731-gas-push-does-not-deploy.md) | `clasp push` は本番を更新しない。「直したのに直らない」は配信中バージョンを疑う |
| [20260731-attribute-state-change-with-control-experiment.md](20260731-attribute-state-change-with-control-experiment.md) | 「別の何かが書き換えている」は終状態でなく、放置対照実験(時間軸)で判定する |
