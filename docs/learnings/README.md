# 学びノート (docs/learnings)

このリポジトリで非自明な問題を解いたときに残す、**1問1ノート**のアトミックな記録置き場です。
解いた答えそのものより、次に同種の問題へ当たったときに効く**推論と判断基準**を残します。

- 書き方・テンプレートは `.claude/skills/extract-approach/SKILL.md` を参照。
- CLAUDE.md の learning law により、非自明な解決のたびにここへ1件追加します
  (学びノートの無い解決は未完了とみなす)。
- ファイル名は `<YYYYMMDD>-<短いスラッグ>.md`(例 `20260711-bsd-date-portability.md`)。

現在のノート:

- [20260712-launchd-cron-path-not-inherited.md](20260712-launchd-cron-path-not-inherited.md) — スケジュール実行は
  ログインシェルの PATH を引き継がない。外部 CLI は3段フォールバックで解決する。
- [20260809-absence-of-evidence-needs-a-control.md](20260809-absence-of-evidence-needs-a-control.md) — 不在証拠から
  因果を推論する前に、対照試験を1本入れる。
- [20260810-decision-rules-must-outlive-the-session.md](20260810-decision-rules-must-outlive-the-session.md) — 会話で
  合意した判断規則は次のセッションに残らない。ファイルに書き、非対話経路でも成立するか確認する。
- [20260810-path-scoped-rules-beat-nested-claude-md.md](20260810-path-scoped-rules-beat-nested-claude-md.md) — 規則の
  置き場所はディレクトリ名でなく「実際に適用されるファイル集合」で決める。範囲が跨るなら `paths:` を使う。
