-- テーブル定義。${dataset} は apply 時に <project>.<dataset> へ置換される。
-- 既存テーブルは壊さない(IF NOT EXISTS)。列追加は ALTER TABLE で行うこと。

-- 広告×日の実績(最小粒度)。集計はすべてビューで行う。
CREATE TABLE IF NOT EXISTS `${dataset}.raw_ad_daily` (
  date DATE NOT NULL,
  account_id STRING NOT NULL,
  campaign_id STRING,
  campaign_name STRING,
  adset_id STRING,
  adset_name STRING,
  ad_id STRING NOT NULL,
  ad_name STRING,
  spend FLOAT64,
  impressions INT64,
  reach INT64,
  frequency FLOAT64,
  link_clicks INT64,
  landing_page_views FLOAT64,
  cv FLOAT64,                -- config の primary_conversion で数えた CV
  cv_definition STRING,      -- どの action を CV とみなしたか(定義変更の追跡用)
  video_thruplay FLOAT64,
  video_p25 FLOAT64,
  video_p100 FLOAT64,
  actions_json STRING,       -- 生の actions(別定義で再集計できるよう保持)
  conversions_json STRING,
  fetched_at TIMESTAMP
)
PARTITION BY date
CLUSTER BY account_id, campaign_id, ad_id;

-- マルチモーダル解析したCR特徴量。creative_id × analyzer_version で1行。
CREATE TABLE IF NOT EXISTS `${dataset}.creative_features` (
  creative_id STRING NOT NULL,
  ad_id STRING,
  account_id STRING,
  media_type STRING,              -- video / image
  duration_sec FLOAT64,
  hook_type STRING,               -- 冒頭フックの型(質問/数字/悩み/共感/驚き/権威/UGC風 等)
  hook_text STRING,
  appeal_axis STRING,             -- 訴求軸(待遇/環境/悩み解決/不安/キャリア/地域 等)
  benefit STRING,
  offer STRING,
  cta STRING,
  subject_exposure_sec FLOAT64,   -- 求人・サービス(商品に相当)の露出開始秒
  subject_exposure_total_sec FLOAT64,
  has_person BOOL,
  person_type STRING,             -- 整備士本人風/採用担当/ナレーターのみ 等
  format_style STRING,            -- UGC風/テロップ主体/インタビュー/図解 等
  aspect_ratio STRING,            -- 9:16 / 4:5 / 1:1 / 16:9
  shot_framing STRING,            -- 画角(寄り/引き/手元/自撮り 等)
  cuts_per_10s FLOAT64,           -- テンポ
  has_subtitles BOOL,
  has_voiceover BOOL,
  features_json STRING,           -- 上記を含む解析結果の全体
  analyzer_model STRING,
  analyzer_version STRING,
  analyzed_at TIMESTAMP
);

-- 生成CRの管理(どの仮説・どの親CRから作ったか)。
CREATE TABLE IF NOT EXISTS `${dataset}.generated_creatives` (
  generated_id STRING NOT NULL,
  hypothesis_id STRING,
  parent_ad_ids ARRAY<STRING>,    -- 比較対象(コントロール)にする既存勝ちCR
  pattern_json STRING,            -- 生成の元にした特徴量パターン
  script_json STRING,
  video_uri STRING,
  status STRING,                  -- draft / approved / uploaded / rejected
  ad_id STRING,                   -- 入稿後に紐づく Meta の広告ID
  created_at TIMESTAMP,
  approved_by STRING,
  approved_at TIMESTAMP
);

-- 停止・継続・横展の判定ログ(判定の再現と振り返り用)。
CREATE TABLE IF NOT EXISTS `${dataset}.cr_decisions` (
  decided_at TIMESTAMP NOT NULL,
  ad_id STRING NOT NULL,
  control_ad_ids ARRAY<STRING>,
  decision STRING,                -- STOP / CONTINUE / SCALE / EXTEND_TEST
  reason STRING,
  prob_better FLOAT64,
  spend FLOAT64,
  cv FLOAT64,
  next_hypothesis STRING,
  executed BOOL,                  -- dry_run=false で実際に Meta に反映したか
  evidence_json STRING
);
