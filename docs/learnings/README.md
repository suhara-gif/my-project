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
- [20260928-ad-level-stats-need-volume-check.md](20260928-ad-level-stats-need-volume-check.md)
  — 広告の自動判定は、判定単位あたりのCV件数を実データで数えてから統計手法を決める。
- [20260928-campaign-funnel-needs-ad-breakdown.md](20260928-campaign-funnel-needs-ad-breakdown.md)
  — キャンペーン単位の段の崩れは広告の入れ替わりと区別できない。広告別の内訳を出してから原因を書く。
- [20260928-monitor-must-not-share-failure-mode.md](20260928-monitor-must-not-share-failure-mode.md)
  — 監視の仕組みは監視対象と同じ壊れ方(ジョブ停止・シート再作成・集計途中の行)をしない形で作る。常に出続ける要確認は先に除外する。
- [20260928-null-cv-is-not-zero.md](20260928-null-cv-is-not-zero.md)
  — 手作業で投入した日次データは、合計値に加えて列ごとの NULL 件数を数える。NULL に意味を持たせない。
- [20260928-verify-blocker-before-reporting-it.md](20260928-verify-blocker-before-reporting-it.md)
  — 「実行できない」と報告する前に実際に1回試す。ffmpeg不在は誤りで、真の壁はネットワークポリシーだった。
- [20260929-text-only-misses-in-image-appeal.md](20260929-text-only-misses-in-image-appeal.md)
  — 静止画は本文だけで訴求軸を決めない。実際に見たら画像内の見出しが主訴求で、text_only の判定と食い違った。
- [20260929-winner-definition-hides-major-dropout.md](20260929-winner-definition-hides-major-dropout.md) — 暫定目標に依存する「勝ち」定義が主力CRの停止検知を素通りさせた
- [20261008-empty-text-is-not-empty-document.md](20261008-empty-text-is-not-empty-document.md)
  — PDFの本文取得が空でも文書が空とは限らない。pdffonts/Creatorでスキャン画像か確かめ、「文字データが無い」と報告する。
- [20261008-notebooklm-autosync-needs-stable-doc.md](20261008-notebooklm-autosync-needs-stable-doc.md)
  — NotebookLMの自動同期は登録済みドキュメントの編集にしか効かない。改定が別ファイルで来るなら固定のドキュメント1つに束ねる。
