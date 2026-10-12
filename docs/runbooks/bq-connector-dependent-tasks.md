# BigQuery コネクタ(個人OAuth)に依存する定期実行の棚卸し(2026-10-12)

- 目的: コネクタが約1日で失効する前提([学びノート](../learnings/20261011-oauth-connector-expires-daily-scheduled-runs.md))で、止まりやすい定期実行を洗い出し、母艦(サービスアカウント)への移行順を決める。
- 方法: 読み取りのみ。Slack の失敗通知・Notion の台帳と棚卸しページ(10/11)・claude.ai の Routine 一覧(`list_triggers`、enabled=true の全14件の本文)を突き合わせた。

## 結果: 確認できた依存は2件

| # | タスク | 実行場所・頻度 | 依存の根拠 | 止まった回数(確認できた分) | 移行の難しさ | 優先 |
|---|---|---|---|---|---|---|
| 1 | トヨワク Meta 広告デイリー監視(「✅Bigquery認証_⚡ Meta広告デイリー監視(トヨワク)」trig_019iBS9AoEYUbLfuF5716L5t) | claude.ai(Cowork)・平日 8:52 | 手順2で `raw_ad_daily` を DELETE/INSERT(コネクタ) | 9/30・10/1・10/2・10/3・10/4・10/5・10/6・10/8・10/9・10/11・10/12 の朝に「sign in again」等で停止。成功は 9/29・10/7・10/10 | **移行済み**(母艦 `toyowaku_meta_monitor.py`、平日 8:50。10/12 08:50 に初回の投稿を確認) | 完了待ち。クラウド版の停止判定は 10/14 10:30(trig_01L6Rb7M6q2s2vT1Sh5mXwQ9) |
| 2 | GA4 週次レポート(5プロパティ: トヨワク/カーワク/メカワク/アプキャリ/U-match) | Cowork・週次(月曜朝) | 本文のエラー「BigQuery MCP … The user's connection to this connector was invalidated」(10/12 08:05 の Slack DM) | 10/12 の1回(それ以前の履歴は未確認) | 中。GA4 の BigQuery エクスポート(`analytics_*`)は `bright-drake-417501` にあり、母艦のサービスアカウントは同プロジェクトに接続済み(`check_bq_auth.py` が OK_LIVE)。`analytics_*` の読み取り権限は未確認 [要確認] | **高**(母艦移行の次の候補) |

## 確認できなかったこと(範囲の限界)
- claude.ai の Routine(enabled 14件)の本文には、BigQuery を実際に使うものは **0件**。接続リストに付いているだけのものがある。
- 上の1・2の定期実行は、Routine 一覧(`list_triggers`)に出てこない(Cowork のスケジュールタスクは別管理)。
  このため、**Cowork のスケジュールタスク全体の BigQuery 依存は、私の側から網羅できていない** [要確認]。
  Cowork 側のタスク一覧(`list_scheduled_tasks`)で確認するか、10/11 の棚卸しページ(Notion「定期実行・監視の棚卸し」)の対象一覧と照合する必要がある。
- 失敗通知を Slack で「BigQuery」「コネクタ」「invalidated」で検索した範囲では、上記2件以外に、BigQuery コネクタ起因の停止は見つからなかった。

## 提案(次の Phase1)
- GA4 週次レポートを、母艦(サービスアカウント)へ移す。範囲: `analytics_*` の読み取り権限の確認(読み取りのみ)→移行の設計→承認後に実装。
