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
- [20260822-nested-claude-md-verify-before-trusting.md](20260822-nested-claude-md-verify-before-trusting.md)
  — 「ファイルが存在する」ことを「その仕組みが今のコンテキストで機能している」ことと混同しない。
- [20260823-recurring-loop-needs-purpose-gate.md](20260823-recurring-loop-needs-purpose-gate.md)
  — 変化検知ループには「そもそも検知対象があるか」の起動ゲートを別に入れる。
- [20260824-polling-interval-should-track-human-cadence.md](20260824-polling-interval-should-track-human-cadence.md)
  — 「監視すべきか」と「どの間隔で監視すべきか」は別のゲート。間隔は人間の反応速度に合わせる。
- [20260830-subagent-mcp-tools-server-level-only.md](20260830-subagent-mcp-tools-server-level-only.md)
  — サブエージェントの MCP ツール権限はサーバー単位でしか絞れない。最小権限設計には上限がある。
- [20260902-dispatch-cannot-touch-local-mac-state.md](20260902-dispatch-cannot-touch-local-mac-state.md)
  — リモート実行セッションはローカルの Mac の状態に触れない。対象がローカルなら判定してから指示文で渡す。
- [20260903-gas-domain-login-writer-separation.md](20260903-gas-domain-login-writer-separation.md)
  — GAS の社内アプリで「本人特定」と「書き込み権限」を分離する。
- [20260906-mask-secrets-before-terminal-relay.md](20260906-mask-secrets-before-terminal-relay.md)
  — 秘密情報を含みうる出力は、見た目でなく機能で判定し、提示前にマスクする。
- [20260924-textual-merge-clean-is-not-semantic-clean.md](20260924-textual-merge-clean-is-not-semantic-clean.md)
  — git が衝突を出さなくても、設定JSONは重複キーで黙って壊れる。仮マージ結果をパースして検証する。
