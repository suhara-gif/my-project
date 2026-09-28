# 手作業で投入した日次データは「0件の日」が NULL になっていないかを最初に数える

- 日付: 2026-09-28
- 種別: バグ修正 / 失敗した試み
- 触れたファイル: meta-ads-autopilot/src/meta_autopilot/offline.py, meta-ads-autopilot/README.md, meta-ads-autopilot/ROUTINE_PROMPT.md

## 問題
別セッションが Meta Ads MCP 経由で BigQuery `raw_ad_daily` に投入したトヨワク35日分(524行)を判定にかけると、
ほぼ全広告が「CV定義が違うため除外」と出た。

## 文脈
Meta Ads MCP は、結果が無い日の CV を「Not available」で返す。投入時にこれが 0 ではなく NULL になり、
cv_definition も NULL になっていた(478行)。判定側は「cv が NULL = 定義の違う広告(Mechanic_Lead)」とみなしていたため、
0件の日と定義違いの広告を区別できなかった。費用とCVの合計値は正しかったので、合計の突き合わせでは気づけない。

## 解法と、その理由
1. `cv_definition` ごとに NULL・0・正の件数を数え、NULL の行が定義未設定(=0件の日)であることを確認してから 0 に更新した。
2. 判定側の除外条件を「cv が NULL」から「最も多い cv_definition と違う」に変えた。NULL を意味づけに使わない。
3. 毎朝の投入手順(ROUTINE_PROMPT.md)に「値が無い日は必ず 0」を明記した。

## うまくいかなかったこと
- 合計値(費用・CV)の一致だけで投入を検証済みとしていた。NULL の混入は合計に出ない。
- 毎朝の定期実行を create_trigger で作ったが、この組織ではコネクタもリポジトリも付けられず、
  起動しても何もできない Routine になった(警告で判明し、即削除)。コネクタが要る Routine は claude.ai の画面から作る。

## 抽出したルール / ヒューリスティック
- 日次データの投入を検証するときは、合計値に加えて主要列の NULL 件数を列ごとに数える。
- NULL に「定義が違う」「取得不可」などの意味を持たせない。意味は専用の列(cv_definition 等)に書き、NULL は欠損だけに使う。
- create_trigger の結果に「コネクタなし」の警告が出たら、その Routine は作成済みとして報告しない。

## 関連
- [20260928-ad-level-stats-need-volume-check.md](20260928-ad-level-stats-need-volume-check.md)
- [20260928-campaign-funnel-needs-ad-breakdown.md](20260928-campaign-funnel-needs-ad-breakdown.md)
