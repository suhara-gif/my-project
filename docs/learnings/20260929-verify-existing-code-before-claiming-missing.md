# 「未実装」と断言する前に既存コードを読む(Mechanic_Lead取り込みは実装済みだった)

- 日付: 2026-09-29
- 種別: 失敗した試み / 設計判断
- 触れたファイル: meta-ads-autopilot/src/meta_autopilot/config.py, meta-ads-autopilot/src/meta_autopilot/ingest/meta_insights.py, meta-ads-autopilot/src/meta_autopilot/pipeline.py, meta-ads-autopilot/config.example.yaml, meta-ads-autopilot/tests/test_ingest_slack.py

## 問題
Meta Ads MCP でカスタムCV(Mechanic_Lead)が取れないと分かった時点で、ユーザーに
「Graph API 直叩きの取り込み実装が別途必要。現状のコードベースには未実装」と回答した。
ユーザーはこれを前提に「Graph API直叩きを優先したい」と意思決定した。
実際に `ingest/meta_insights.py` を読むと、`conversions:...Mechanic_Lead` 形式の CV 抽出を含む
Graph API 取り込みは実装済みだった(README の「セットアップ」節にも手順がある)。

## 文脈
同セッションで `meta-ads-autopilot/CLAUDE.md` と README は読んでいたが、`src/` は読まずに
「MCP に無い → コードにも無いだろう」と推測で答えた。CLAUDE.md の「観察を昇格させるときの
前提チェック」(未確認の前提が残るなら `[要確認]` に留める)に反していた。
ユーザーの判断材料になる断言だったため、誤りの影響が大きかった。

## 解法と、その理由
1. 着手前に `src/` の該当モジュールを読み、実装済みと判明 → ユーザーへ訂正を先に伝えた。
2. 本当に足りなかったのは「広告単位のCV定義の切り替え」だけだった。CV 定義は
   `primary_conversion` がアカウント単位のため、Mechanic_Lead 運用の TEST_ブランド訴求15/16 だけ
   別定義にする手段が無かった。
3. `AccountConfig.conversion_overrides`(広告ID → CV指定)を追加し、`to_bq_row` で広告IDが
   一致した行だけ上書き、採用した定義を `cv_definition` に残す最小変更にした。
   広告名ではなく広告IDで指定したのは、名前に表記ゆれ(`テストA ― ...` / `テスト A― ...`)があり
   完全一致でも取り違えうるため(広告IDは BigQuery の raw_ad_daily から取得)。
4. `pytest -q` 48件パス(追加テスト2件: 上書きは指定広告だけに効く / YAML数値キーを文字列化)。

## うまくいかなかったこと
- 実APIでの動作確認はできていない。`META_ACCESS_TOKEN` が未設定で、`conversions` に
  Mechanic_Lead が実際に入って返るかも未検証。config.example.yaml に `[要確認]` を残した。

## 抽出したルール / ヒューリスティック
「〜は未実装」「〜の実装が必要」とユーザーに伝える前に、対象ディレクトリを Grep/Read して
該当機能の有無を確認する。外部ツール(MCP等)で取れないことは、コードベースに無いことの根拠にならない。
確認していない場合は「未確認」と書き、断言しない。

## 関連
- [20260928-meta-ads-mcp-no-custom-conversion-field.md](20260928-meta-ads-mcp-no-custom-conversion-field.md)
- [20260817-promote-only-after-listing-assumptions.md](20260817-promote-only-after-listing-assumptions.md)
