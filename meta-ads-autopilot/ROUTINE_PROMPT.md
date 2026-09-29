# 毎朝のルーティン用の指示文(トヨワク)

claude.ai のルーティン作成画面で次のように設定し、下の「指示文」を貼り付ける。

- リポジトリ: suhara-gif/my-project
- コネクタ: Meta Ads / Google Cloud BigQuery / Salesforce / Slack
- 実行タイミング: 平日 8:52(日本時間)

## 指示文

トヨワクのMeta広告デイリー監視を実行し、結果を須原さん本人のSlack DMに送ってください。広告の設定変更(停止・予算変更など)は一切しないこと。読み取りと、BigQueryの自テーブルへの書き込み、Slack送信だけを行う。

前提
- meta-ads-autopilot/README.md の「コネクタだけで回す運用」を参照
- Metaアカウント: トヨワク 1280868240318718
- BigQuery: `upty-meta-ads.meta_ads.raw_ad_daily`(列は meta-ads-autopilot/sql/01_tables.sql)
- 目標CPA(登録1件あたり): 5800 円(整備士CPA 4万円から換算)

手順
0. 日付は必ず日本時間で決める。実行環境はUTCなので、最初に `TZ=Asia/Tokyo date +%F` で今日の日付を確認し、その前日を「昨日」とする(UTCのまま決めると、朝8:52 JST の実行で昨日が1日ずれ、9/29朝の実行で 9/27 までしか取れない)。
1. Meta Ads MCP(ads_get_ad_entities, level=ad, time_increment="1")で、日本時間の昨日までの直近7日の広告×日を取得する。fields: id, name, campaign_id, campaign_name, adset_id, adset_name, amount_spent, impressions, link_click, landing_page_view, omni_complete_registration, frequency。費用0の日は入れなくてよい。
2. raw_ad_daily の同じ7日間・同アカウントの行を DELETE し、取得した行を INSERT する。
   - cv = omni_complete_registration。値が無い/Not available の日は必ず 0(NULLにしない)。cv_definition = 'omni_complete_registration'。link_clicks・landing_page_views も無ければ 0。
   - Mechanic_Lead で最適化している広告(結果の指標が Mechanic_Lead のもの。例: TEST_ブランド訴求15_整備士 / TEST_ブランド訴求16_整備士)は cv = NULL、cv_definition = 'mechanic_lead_unavailable_via_meta_ads_mcp'。
   - 取得が0行・エラーのときは DELETE しない(既存データを消さない)。その旨をSlackに書く。
3. 直近35日の行を次のSQLで取り出し、JSON配列を rows.json に保存する:
   `SELECT TO_JSON_STRING(ARRAY_AGG(STRUCT(CAST(date AS STRING) AS date, campaign_id, campaign_name, ad_id, ad_name, spend, impressions, link_clicks, landing_page_views AS lpv, cv, cv_definition, frequency) ORDER BY date, ad_id)) FROM `upty-meta-ads.meta_ads.raw_ad_daily` WHERE account_id='1280868240318718' AND date > DATE_SUB((SELECT MAX(date) FROM `upty-meta-ads.meta_ads.raw_ad_daily`), INTERVAL 35 DAY)`
4. `cd meta-ads-autopilot && pip install -q numpy pydantic pyyaml && PYTHONPATH=src python -m meta_autopilot.offline --rows rows.json --target-cpa 5800 --label トヨワク` を実行し、出力を本文にする(異常検知に加え、直近14日に配信が始まった新CRの判定 STOP/CONTINUE/SCALE も出る。通知のみで広告は変更しない)。
5. Salesforce で手順3と同じ期間の Contact を数える: ManagementToyowakuInflowDate_del__c が期間内 かつ sourceMedium_j_tw__c = 'meta / cpc' の件数と、そのうち Field63__c = '整備士' の件数(Field63__c は GROUP BY 不可なので WHERE で COUNT)。整備士CPA = 期間の費用合計 ÷ 整備士数。本文の2行目の後に「整備士CPA(直近35日・SF突合): 約¥X(費用¥Y ÷ 整備士Z件) / 目標 ¥40,000」を入れる。
6. 未解析の新CRを解析する(1日3本まで)。`SELECT ad_id FROM raw_ad_daily WHERE ad_id NOT IN (SELECT ad_id FROM creative_features)` で見つかった広告について、ads_get_ad_entities の creative_id → ads_get_creatives の image_url を curl で取得し、Read で画像を見て creative_features に INSERT する(analysis_scope='multimodal'、語彙は creative/schema.py に従う、1080x1080などの実測値は notes に書く)。動画は download_hd_url が null で映像に到達できないため、本文から確定できる項目だけを analysis_scope='text_only' で入れる。画像が取れない/見えないときは text_only で入れ、Slack に「画像未取得: 広告名」と1行足す。[要確認] Routine の実行環境で画像取得と目視ができるかは未検証(できない場合はこの手順を飛ばしてよい)。
7. 本文の *太字* を **太字** に変換し、Slack の自分宛てDM(slack_send_message の channel_id に自分の user_id)へ送る。

注意
- 本文の数字・通知内容は手を加えず、スクリプトの出力をそのまま使う(要約で数字を変えない)。
- いずれかのコネクタが使えない場合は、使える範囲で進め、どこで止まったかをSlack DMに1行で書く。
