# CLAUDE.md — meta-ads-autopilot

Meta広告の監視・CR解析・動画CR生成・新CR判定のパイプライン。全体像は [README.md](README.md)。

## 変更するときに守ること

- **判定ロジックは純関数に置く。** `stats.py` / `detect/` / `patterns/` / `lifecycle/decide.py` / `generate/script.py` の
  チェック関数は外部接続なしで動くこと。BigQuery・Meta・Slack・Claude への入出力は `pipeline.py` / `cli.py` /
  `ingest/` / `creative/analyzer.py` に閉じ込める。
- **点推定の閾値判定を足さない。** CV は 1広告1日あたり 0〜1件の規模。新しい判定を足すときは `stats.py` の
  確率ベースの比較を使い、「最低件数・最低費用のガード」とセットにする。
- **Meta への書き込みは一時停止だけ。** 削除・予算増額・入稿を自動化するコードを足さない。足す必要が出たら
  人の承認フローを先に設計し、須原さんに確認する。`dry_run` の既定値 `true` を変えない。
- **台本の数字は facts 由来のみ。** `validate_facts` を外したり緩めたりしない(求人広告の的確表示義務)。
- **CV の定義を変えたら `cv_definition` 列で追えるようにする。** 定義の違う期間を混ぜて比較しない。
- 変更後は `pytest -q` を通す。

## 数字を扱うとき

`company/knowledge/business.md` の「数字を扱うときの必読ルール」に従う。Meta の CV は整備士数ではない。
