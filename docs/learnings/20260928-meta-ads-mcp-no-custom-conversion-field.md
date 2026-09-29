# Meta Ads MCP はカスタムコンバージョン(Mechanic_Lead等)の発火数を取得できない

- 日付: 2026-09-28
- 種別: 調査 / 設計判断
- 触れたファイル: meta-ads-autopilot/config.example.yaml, meta-ads-autopilot/README.md

## 問題

meta-ads-autopilot の初回セットアップで、トヨワク(アカウント 1280868240318718)の直近35日の
広告×日データを Meta Ads MCP 経由で取得し BigQuery `raw_ad_daily` に投入しようとした。
config.example.yaml には TW 用のカスタムCV `Mechanic_Lead` を
`conversions:offsite_conversion.fb_pixel_custom.Mechanic_Lead` という生API形式の action 名で
指定する想定が書かれていたが、この形式のフィールド名は Meta Ads MCP の `ads_get_ad_entities` /
`ads_get_field_context` の両方で `unknown_fields` として拒否された。

## 文脈

依頼では「CVの定義が Mechanic_Lead の広告(TEST_ブランド訴求15/16)は、登録完了と混ぜない」ことが
明示されていた。つまり広告ごとに異なる CV 定義を正しく tagging する必要があり、取得できないからと
言って登録完了の値を代わりに入れることは許されない(定義の異なる期間・広告を混ぜない、という
CLAUDE.md の数値ルールにも反する)。

`ads_get_field_context`(field_names省略、全件取得)で122フィールド全部を確認したところ、
提供されているのは `omni_complete_registration` / `lead` / `onsite_conversion_lead_grouped` などの
Meta 側で標準化された集計フィールドのみで、アカウント固有のカスタムコンバージョン名(pixel の
custom conversion)を個別に指定して発火数を取るフィールドが存在しなかった。
`ads_get_customconversions` というツールもあるが、これは「カスタムコンバージョンの定義(ID)一覧」を
返すだけで(ツール説明に "No metrics fields" と明記)、日次の発火数は返さない。

## 解法と、その理由

生の `actions` 配列やカスタムイベント名でのクエリができない前提で、次の設計にした。

1. 通常広告: `cv = omni_complete_registration`、`cv_definition = 'omni_complete_registration'`
2. ユーザーが名指しした Mechanic_Lead 運用広告(`TEST_ブランド訴求15_整備士` /
   `TEST_ブランド訴求16_整備士` の完全一致のみ): `cv = NULL`、
   `cv_definition = 'mechanic_lead_unavailable_via_meta_ads_mcp'`

登録完了の値を代入せず NULL にすることで、「定義の異なる CV を混ぜない」という制約を守った。
`raw_ad_daily.cv_definition` 列が最初から用意されていたため、この tagging は追加スキーマ変更なしで
実現できた。生データ(omni_complete_registration 等)は `actions_json` に保持しているので、後で
Mechanic_Lead を別ルートで取れるようになったときに `cv` を埋め直せる。

広告名の完全一致だけをフィルタ条件にしたのも意図的な判断。データには
`テストA ― ASC_ブランド訴求15_整備士` / `テスト A― ASC_ブランド訴求15_整備士` という、
ユーザーが指定した `TEST_ブランド訴求15_整備士` とダッシュ・スペースの表記だけが違う広告も
混在していた。表記揺れを「同じ意図だろう」と推測して同一視すると、CV 定義を誤って混同する
リスクの方が、対象を過小に扱うリスクより高いと判断し、完全一致以外は通常(登録完了)扱いのまま
残し、要確認として報告に回した。

## うまくいかなかったこと

- `actions:offsite_conversion.fb_pixel_complete_registration` や
  `conversions:offsite_conversion.fb_pixel_custom.Mechanic_Lead` を `ads_get_field_context` の
  `field_names` にそのまま渡す → `unknown_fields` に入るだけで解決しない。
- `cost_per_action_type` から逆に action_type ごとのカウントフィールドがあるはずと当たりを
  つけて全フィールド名を `action_type|custom_conv|conversion_id` 等で検索 → 該当なし。
  MCP のフィールド体系は Graph API の `actions` ブレークダウンをそのまま透過していない。

## 抽出したルール / ヒューリスティック

Meta Ads MCP でカスタムコンバージョン名(pixel custom conversion)や generic な `actions` 配列を
指定したくなったら、まず `ads_get_field_context()`(引数なし・全件)を取って `omni_*` / `lead` 系の
標準集計フィールドで代替できないか確認する。代替できない指標(アカウント固有のカスタムイベント)は
このMCP単体では取得不可と判断してよく、代わりに Meta Graph API Insights を直接叩く
`meta-ads-autopilot/src/meta_autopilot/ingest/meta_insights.py`(実装済み)を使う。
(当初このノートは「実装が別途必要」と書いたが誤り。既存コードを読まずに断言した。
[20260929-verify-existing-code-before-claiming-missing.md](20260929-verify-existing-code-before-claiming-missing.md) 参照)取得不可な広告には、代替指標の値を
決して代入せず、`cv_definition` のような出所列に明示的な「取得不可」マーカーを入れて NULL のまま
残すこと。

## 関連

- [20260925-meta-sf-mechanic-join.md](20260925-meta-sf-mechanic-join.md)
- [20260925-gtm-trigger-timing-mechanic-lead.md](20260925-gtm-trigger-timing-mechanic-lead.md)
