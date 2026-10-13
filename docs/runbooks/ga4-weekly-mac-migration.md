# GA4 週次レポートを母艦(サービスアカウント)へ移す 設計

状態: **実装済み(別セッション、2026-10-12)。本書は検証メモ** / 作成: 2026-10-13

> 訂正(2026-10-13): 母艦版 `weekly_ga4_report.py`(BQ + keyEvents は Data API、SA鍵、launchd 月曜)は既に稼働済みで、
> 10/12 13:30 に5サイトとも成功していた(`weekly_ga4_report_last.json`)。下の設計・突合は重複作業だったが、
> 突合で「レポートの AU は distinct user_pseudo_id で、GA4画面の activeUsers と 1〜2%ずれる」ことが分かった(下表)。
> keyEvents の Data API が SA で通っているため、SA は5プロパティに登録済み(8月の403は解消)。

## 結論
- 母艦のサービスアカウントは、5サイトすべての `analytics_*.events_*` を読めた(2026-10-13 母艦実測、Slack投稿 OK)。
  管理者操作(GA4 に SA を追加)は不要。ユーザーOAuthを使わないので、毎日切れる問題も起きない。
- 方式は **BigQuery エクスポートを SA で集計**する。GA4 Data API 方式(`ga4_weekly_report.py`)は
  各プロパティで SA を「アナリスト」に追加する管理者操作(5件)が要るため、予備にする。
- ただし **数値は GA4 画面と完全一致しない**。定義を揃える(下表)まで、レポートの数字を前週と並べない。

## 実測(2026-10-06〜10-12、BQ=母艦SA / API=GA4 Data API)
| サイト | BQ ユーザー | API totalUsers | API activeUsers | BQ セッション | API セッション | BQ イベント | API イベント |
|---|---|---|---|---|---|---|---|
| トヨワク | 1510 | 1510 | 1485 | 1697 | 1700 | 77388 | 77308 |
| カーワク | 12603 | 12670 | 12485 | 13852 | 13760 | 221389 | 217631 |
| メカワク | 4409 | 4409 | 4399 | 4532 | 4472 | 44217 | 44217 |
| アプキャリ | 2115 | 2115 | 2106 | 2186 | 2177 | 14856 | 14856 |
| U-match | 1293 | 取得失敗(セッション切れ) | - | 1389 | - | 13088 | - |

読み取れること(確認済み):
- BQ の `COUNT(DISTINCT user_pseudo_id)` は **totalUsers** に近い。週次レポートが使う **activeUsers** とは別物(0.2〜1%小さい)。
- セッションは BQ が +0.2〜+1.3% 多い。イベントは3サイトで一致、カーワクのみ +1.7%。
未確認 [要確認]: セッション差の原因(session_start 件数で数えれば合うか)、カーワクのイベント差の原因、
activeUsers を BQ で再現する条件(engagement_time_msec>0 など)、U-match の突合、keyEvents・engagedSessions の再現。

## 移行設計
1. `ga4_weekly_report_bq.py`: 5サイトを `events_*` から集計(期間=前週月〜日)。
   - activeUsers 相当 = engagement_time_msec>0 のユーザー、sessions = session_start 件数、で定義を揃えて**再度 API と突合**し、
     差が1%以内に収まってから本番切替。
   - keyEvents は GA4 側で key event に指定されたイベント名の一覧が要る [要確認]。
2. 出力は従来の Slack 形式(#6-attracting 向けではなく、まず Slack DM)。投稿は `lib/slack_notify.post_slack`。
3. `.command`: 自己更新・Slack結果・貼り付け不要(`command_lint` 準拠)。launchd は月曜 08:00 JST
   (`weekly_ga4_report.py` が既にあるか確認し、あれば置換でなく統合 [要確認])。
4. claude.ai 側の GA4 週次ルーティンは、母艦版が1回成功してから停止(須原さん操作)。

## 工数(目安)
- 実装 + 突合 + `.command`/launchd: 半日。突合で定義が合わない場合は +半日。
- 代替(Data API): SA を5プロパティに追加(管理者・各1分)→ 既存 `run_ga4_report.command` が使える。数値は画面と一致する。

## 承認が要ること
- 方式: BQ(定義差あり・追加操作なし) か API(画面一致・管理者操作5件) か。

## 突合の追加結果(23_, session_start 方式)
- sessions: session_start 件数で トヨワク ±0 / カーワク +0.5% / メカワク +1.5% / アプキャリ -0.5%(現行は distinct(user+ga_session_id) で +0.2〜+1.3%)。
- activeUsers を engagement_time_msec>0 で数える案は -9〜-44% で不採用。
- 結論: BQ の AU は totalUsers 相当。画面の activeUsers に合わせるなら Data API を使う(SA は既に通る)。
