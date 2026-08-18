# 学びノート (docs/learnings)

このリポジトリで非自明な問題を解いたときに残す、**1問1ノート**のアトミックな記録置き場です。
解いた答えそのものより、次に同種の問題へ当たったときに効く**推論と判断基準**を残します。

- 書き方・テンプレートは `.claude/skills/extract-approach/SKILL.md` を参照。
- CLAUDE.md の learning law により、非自明な解決のたびにここへ1件追加します
  (学びノートの無い解決は未完了とみなす)。
- ファイル名は `<YYYYMMDD>-<短いスラッグ>.md`(例 `20260711-bsd-date-portability.md`)。

## 収録ノート

- [20260712-launchd-cron-path-not-inherited.md](20260712-launchd-cron-path-not-inherited.md)
  — launchd/cron は最小 PATH でジョブを起動するため、`command -v` 単独依存だと本番だけ CLI が見つからない。
- [20260809-absence-of-evidence-needs-a-control.md](20260809-absence-of-evidence-needs-a-control.md)
  — 不在証拠（Xが無い）から因果を語る前に「正常時にXは有ったか」を確認する対照試験を1本入れる。
- [20260817-promote-only-after-listing-assumptions.md](20260817-promote-only-after-listing-assumptions.md)
  — 観察を推奨アクション・断定・数値へ昇格させる前に、依存する前提を列挙し確認済みかを付す。
