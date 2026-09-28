-- 集計ビュー。すべて raw_ad_daily(広告×日)から作る。

-- 広告×日(ファネル指標つき)
CREATE OR REPLACE VIEW `${dataset}.v_ad_daily` AS
SELECT
  date, account_id, campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name,
  spend, impressions, reach, frequency, link_clicks, landing_page_views AS lpv, cv,
  SAFE_DIVIDE(spend, impressions) * 1000 AS cpm,
  SAFE_DIVIDE(link_clicks, impressions) AS ctr,
  SAFE_DIVIDE(landing_page_views, link_clicks) AS lpv_rate,
  SAFE_DIVIDE(cv, landing_page_views) AS cvr,
  SAFE_DIVIDE(spend, NULLIF(cv, 0)) AS cpa,
  SAFE_DIVIDE(video_thruplay, impressions) AS thruplay_rate
FROM `${dataset}.raw_ad_daily`;

-- キャンペーン×日の推移(7日移動平均つき)
CREATE OR REPLACE VIEW `${dataset}.v_campaign_daily` AS
WITH d AS (
  SELECT date, account_id, campaign_id, ANY_VALUE(campaign_name) AS campaign_name,
         SUM(spend) AS spend, SUM(impressions) AS impressions, SUM(link_clicks) AS link_clicks,
         SUM(landing_page_views) AS lpv, SUM(cv) AS cv
  FROM `${dataset}.raw_ad_daily`
  GROUP BY date, account_id, campaign_id
)
SELECT
  *,
  SAFE_DIVIDE(spend, impressions) * 1000 AS cpm,
  SAFE_DIVIDE(link_clicks, impressions) AS ctr,
  SAFE_DIVIDE(lpv, link_clicks) AS lpv_rate,
  SAFE_DIVIDE(cv, lpv) AS cvr,
  SAFE_DIVIDE(spend, NULLIF(cv, 0)) AS cpa,
  -- 日次CPAはCVが少なくぶれるので、7日合計ベースの CPA を併記する
  SAFE_DIVIDE(
    SUM(spend) OVER w7,
    NULLIF(SUM(cv) OVER w7, 0)
  ) AS cpa_7d_rolling,
  SUM(spend) OVER w7 AS spend_7d_rolling,
  SUM(cv) OVER w7 AS cv_7d_rolling
FROM d
WINDOW w7 AS (PARTITION BY account_id, campaign_id ORDER BY UNIX_DATE(date) RANGE BETWEEN 6 PRECEDING AND CURRENT ROW);

-- どこに配信が寄っているか: キャンペーン内・アカウント内の費用シェア(直近7日 vs その前21日)
CREATE OR REPLACE VIEW `${dataset}.v_delivery_share` AS
WITH latest AS (SELECT MAX(date) AS d FROM `${dataset}.raw_ad_daily`),
w AS (
  SELECT
    r.account_id, r.campaign_id, ANY_VALUE(r.campaign_name) AS campaign_name,
    r.ad_id, ANY_VALUE(r.ad_name) AS ad_name,
    SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.spend, 0)) AS spend_7d,
    SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.cv, 0)) AS cv_7d,
    SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY) AND r.date > DATE_SUB(l.d, INTERVAL 28 DAY), r.spend, 0)) AS spend_prev21d,
    SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY) AND r.date > DATE_SUB(l.d, INTERVAL 28 DAY), r.cv, 0)) AS cv_prev21d
  FROM `${dataset}.raw_ad_daily` r CROSS JOIN latest l
  WHERE r.date > DATE_SUB(l.d, INTERVAL 28 DAY)
  GROUP BY r.account_id, r.campaign_id, r.ad_id
)
SELECT
  *,
  SAFE_DIVIDE(spend_7d, SUM(spend_7d) OVER (PARTITION BY account_id, campaign_id)) AS share_in_campaign_7d,
  SAFE_DIVIDE(spend_prev21d, SUM(spend_prev21d) OVER (PARTITION BY account_id, campaign_id)) AS share_in_campaign_prev21d,
  SAFE_DIVIDE(spend_7d, SUM(spend_7d) OVER (PARTITION BY account_id)) AS share_in_account_7d
FROM w;

-- 直近7日の動き: 広告ごとに直近7日と前7日を並べる
CREATE OR REPLACE VIEW `${dataset}.v_last7d` AS
WITH latest AS (SELECT MAX(date) AS d FROM `${dataset}.raw_ad_daily`)
SELECT
  r.account_id, r.campaign_id, ANY_VALUE(r.campaign_name) AS campaign_name,
  r.ad_id, ANY_VALUE(r.ad_name) AS ad_name,
  SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.spend, 0)) AS spend_7d,
  SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.impressions, 0)) AS impressions_7d,
  SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.link_clicks, 0)) AS link_clicks_7d,
  SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.landing_page_views, 0)) AS lpv_7d,
  SUM(IF(r.date > DATE_SUB(l.d, INTERVAL 7 DAY), r.cv, 0)) AS cv_7d,
  SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.spend, 0)) AS spend_prev7d,
  SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.impressions, 0)) AS impressions_prev7d,
  SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.link_clicks, 0)) AS link_clicks_prev7d,
  SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.landing_page_views, 0)) AS lpv_prev7d,
  SUM(IF(r.date <= DATE_SUB(l.d, INTERVAL 7 DAY), r.cv, 0)) AS cv_prev7d
FROM `${dataset}.raw_ad_daily` r CROSS JOIN latest l
WHERE r.date > DATE_SUB(l.d, INTERVAL 14 DAY)
GROUP BY r.account_id, r.campaign_id, r.ad_id;

-- CR特徴量 × 実績(広告の全期間累計)。パターン分析の入力。
-- 同一 creative の最新解析結果だけを使う。
CREATE OR REPLACE VIEW `${dataset}.v_creative_performance` AS
WITH perf AS (
  SELECT account_id, campaign_id, ad_id, ANY_VALUE(ad_name) AS ad_name,
         MIN(date) AS first_date, MAX(date) AS last_date,
         SUM(spend) AS spend, SUM(impressions) AS impressions, SUM(link_clicks) AS link_clicks,
         SUM(landing_page_views) AS lpv, SUM(cv) AS cv
  FROM `${dataset}.raw_ad_daily`
  GROUP BY account_id, campaign_id, ad_id
),
feat AS (
  SELECT * EXCEPT(rn) FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY ad_id ORDER BY analyzed_at DESC) AS rn
    FROM `${dataset}.creative_features`
  ) WHERE rn = 1
)
SELECT p.*, f.* EXCEPT(ad_id, account_id)
FROM perf p
JOIN feat f USING (ad_id);
