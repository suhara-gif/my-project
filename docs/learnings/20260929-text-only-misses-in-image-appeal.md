# 広告本文だけの訴求軸判定は、画像内の見出しを取りこぼす(text_only と実際に見た結果の差)

- 日付: 2026-09-29
- 種別: 調査
- 触れたファイル: meta-ads-autopilot/README.md, BigQuery upty-meta-ads.meta_ads.creative_features

## 問題
ネットワークアクセスを Full にして fbcdn.net から静止画を取得し、実際に見て解析したところ、
9/28 に本文・タイトル・CTA だけで付けた text_only の appeal_axis と結果が食い違った。

## 文脈
対象は ASC_ブランド訴求16_整備士(費用¥177,278・CV 13件、トヨワクで最も成果の出た広告)。
- text_only: 本文「トヨタディーラー専門の求人サイト」→ appeal_axis = brand
- multimodal: 画像内に『整備士から、トヨタエンジニアへ。』という見出しがあり、appeal_axis = career(副軸 brand)
- CTA も食い違う: Meta のボタンは SIGN_UP(今すぐ登録)だが、画像内には『一歩踏み出す』というボタン風の装飾があった

## 解法と、その理由
1. 画像を Read tool で直接見て CreativeFeatures を組み立て、analysis_scope='multimodal' で新しい行として投入した。
   既存の text_only 行は消さず履歴に残す(v_creative_performance は analyzed_at が最新の行を使う)。
2. API キーは使わない。analyzer.analyze() は別の API 呼び出しになるが、セッションの Claude 自身が画像を見られるため不要。

## うまくいかなかったこと
- 動画: `ads_get_ad_videos` の `download_hd_url` が null(元ファイルへの権限がこのアプリに無い)で、
  取れたのは 160x284 の表紙1コマだけ(髪の長い女性が作業着で手を振り、テロップ『年収500万円以上、多数』)。
  フック・テンポ・露出秒は1コマでは判定できないため、動画は text_only のまま残した。
- 表紙のサムネイル URL は `stp=...p64x64` の指定で 64x64 に縮小されている。別フィールド(picture)は 160px。

## 抽出したルール / ヒューリスティック
- 静止画は本文だけで訴求軸を決めない。画像内の文字が主訴求のことがあり、text_only の appeal_axis は暫定値として扱う。
- パターン分析に text_only の appeal_axis を使うときは、multimodal で確認できた行と食い違う例があることを前提にする。
- 動画の解析には元ファイルが要る。サムネイル1コマで multimodal 扱いにしない。

## 関連
- [20260928-verify-blocker-before-reporting-it.md](20260928-verify-blocker-before-reporting-it.md)
