# meta-ads-autopilot

Meta広告の実績を BigQuery に集め、ファネル分解で異常を見つけて Slack に通知し、
CR をマルチモーダル解析して勝ちパターン候補を出し、動画CRの台本・音声・組み立てを行い、
新CRを既存の勝ちCRと比べて停止・継続・横展・次の仮説を決めるパイプラインです。

```
Meta Insights API ──(広告×日, 直近7日を毎日取り直し)──▶ BigQuery raw_ad_daily
                                                        │ ビュー: キャンペーン推移 / 配信シェア / 直近7日
                                                        ▼
              detect: ファネル分解(広告別の内訳つき)・配信の偏り・勝ちCRの失速/停止・データ欠落 ──▶ Slack
                                                        │
Meta 素材 ──▶ creative 解析(Claude, フレーム+実測値) ──▶ creative_features ──JOIN──▶ v_creative_performance
                                                        ▼
                                  patterns: 勝ちパターン「候補」(キャンペーン補正 + 縮約 + 冗長除去)
                                                        ▼
               generate: 台本(Opus 5.5)→ 事実・パターンの機械チェック → TTS → ffmpeg 組み立て
                                                        ▼  人が確認して PAUSED で入稿(自動入稿はしない)
               lifecycle: 新CR vs 親CR(同じ配信日で比較)→ STOP / CONTINUE / SCALE / EXTEND_TEST ──▶ Slack
```

## 設計上の判断(依頼内容から変えた点)

実データ(トヨワク 直近28日: 広告約20本で CV 計約49件、1広告1日あたり 0〜1件)を前提に、
依頼の構想から次の点を変えています。

1. **CPA・CVR を点推定の閾値で比べない。** この件数で「広告×日のCVR低下」を判定するとノイズで鳴り続けます。
   率は Beta-Binomial、CPA は Gamma-Poisson で「悪化している確率」を出し、確率と変化幅の両方で判定します
   ([`stats.py`](src/meta_autopilot/stats.py))。ファネル分解はキャンペーン×(直近7日 vs 前21日)で行い、
   CV が少なくても件数の多い上流(CPM・CTR・LPV率)の崩れは早く検知できます。
2. **分解は対数で厳密に行う。** `ln(CPA比) = ln(CPM比) − ln(CTR比) − ln(LPV率比) − ln(CVR比)` が恒等的に成り立つので、
   「どの段が CPA を何%押し上げたか」を足し算で読めます([`detect/funnel.py`](src/meta_autopilot/detect/funnel.py))。
3. **キャンペーンの段の崩れは、広告別に内訳を出す。** トヨワクの実データで試したところ、ASCキャンペーンの CVR 急落(1.97%→0.36%)は
   LP や計測の問題ではありませんでした。勝ちCRの配信が止まり、新CRに配信が寄ったことが原因です。内訳を出さないと原因を取り違えるため、
   不足分を広告別に割り振り、新CR・シェアが急増したCRが主因のときは「配信構成の変化」と明示します。勝ちCRの配信停止も別に検知します。
4. **配信の偏りは「負けCRに寄ったとき」だけ警報。** 勝ちCRに寄るのは正常なので、寄り先の CPA が同キャンペーン内の
   他CR合計より確からしく悪い場合に限定しています。
5. **「勝ちパターン」は仮説として出す。** Meta は成績の良さそうなCRに配信を寄せるため、特徴量×実績は
   「配信されたCRの特徴」と「成果を生む特徴」が混ざります。キャンペーンごとの CPA 水準差を補正し、
   組み合わせの水増しを除いたうえで、確定は lifecycle(同じ日に並走させた比較)に任せます。
   CR が数十本の規模では、3要素の組み合わせ(「不安訴求×UGC×冒頭2秒」)が有意に出ることはまれです。
6. **Opus + TTS で作れるのは台本と音声まで。映像素材が別に要ります。** 組み立ては素材ライブラリ(ファイル名に
   `visual_tag` を含む画像・動画)から選び、足りないカットは一覧にして止めます。黒画面で埋めて入稿はしません。
7. **数字は人が渡した事実だけ。** 求人広告は職業安定法の的確表示義務があるため、台本の数字が事実リストに無ければ
   レンダリングを止めます(`validate_facts`)。最上級表現などは検出できないので、人の確認は省略しません。
8. **自動で書き込むのは「広告の一時停止」だけ。** `dry_run: true` が既定。`auto_execute` に入れた判定だけ
   実行し、横展(予算増・複製)と新規入稿は人が行います。

## 評価指標についての注意(最重要)

Meta の CV(登録完了)は整備士の獲得とは一致しません(`company/knowledge/business.md`、
`docs/learnings/20260925-meta-sf-mechanic-join.md`)。SF にはキャンペーンIDが無いため、広告単位で整備士数を
突き合わせることはできません。広告単位で使える指標のうち整備士に最も近いのは、TW にあるカスタムCV
**Mechanic_Lead** です。`primary_conversion` を `conversions:offsite_conversion.fb_pixel_custom.Mechanic_Lead`
に切り替えると、パターン分析と新CR判定がこの指標で動きます。登録完了のまま最適化すると、
「登録は増えるが整備士は増えないCR」を勝ちとして横展するおそれがあります。

## セットアップ

```bash
cd meta-ads-autopilot
pip install -e ".[gcp,llm,dev]"
cp config.example.yaml config.yaml   # [要確認] の値を埋める
export META_ACCESS_TOKEN=...          # システムユーザーの長期トークン(ads_read。停止を使うなら ads_management)
export SLACK_WEBHOOK_URL=...
export ANTHROPIC_API_KEY=...
python -m meta_autopilot.cli -c config.yaml init-bq
python -m meta_autopilot.cli -c config.yaml daily
```

ffmpeg / ffprobe(CR解析のフレーム切り出しと動画の組み立て)と、字幕用の日本語フォント(既定 Noto Sans CJK JP)が必要です。

## コマンド

| コマンド | 内容 | 頻度の目安 |
|---|---|---|
| `init-bq` | テーブル・ビュー作成(既存は壊さない) | 初回・SQL変更時 |
| `daily` | 取り込み → 検知 → 新CR判定 → Slack | 毎朝 |
| `analyze-pending` | 未解析CRを費用の多い順に解析 | 毎日 or 入稿後 |
| `mine -o out/patterns.json` | 勝ちパターン候補を出力 | 週1 |
| `generate --pattern p.json --facts facts.txt -o s.json` | 台本生成 + 事実・パターンのチェック | 仮説ごと |
| `render --script s.json --assets dir/ [--tts-command ...] -o cr.mp4` | TTS + 組み立て | 台本確定後 |

生成CRを入稿したら、`generated_creatives` に `status='uploaded'`・`ad_id`・`parent_ad_ids`(比較相手の勝ちCR)を
登録します。登録した広告だけが `daily` の判定対象になります。

## 判定ルール(lifecycle の既定値)

| 新CRの費用 | 見るもの | 判定 |
|---|---|---|
| 目標CPA×0.5 未満 | なし | CONTINUE(学習中) |
| ×0.5〜×2 | CTR のみ | 親CR比 −35% 以下かつ悪化確率 97% 以上なら STOP、他は CONTINUE |
| ×2 以上 | CPA(Gamma-Poisson) | 親より良い確率 90% 以上 → SCALE / 15% 以下 → STOP |
| ×4 到達 | 決着せず | CPA が目標内なら CONTINUE、超過なら STOP |

比較は**新CRが配信された日だけ**に揃えます(期間がずれると季節・競合の影響が混ざるため)。

## 要確認

- `graph_api_version` と Insights の各フィールド名(実装時点の最新版で動作未確認)
- 目標CPA(`target_cpa`)。「CV 1件あたり」の目標で、整備士CPAとは別物
- Mechanic_Lead の計測開始日と発火数(切り替えの前提)
- 「3.8 Flash TTS」の正式なモデルIDとAPI。確認できていないため `CommandTTS` で任意のCLIを呼ぶ形にしている
- 音声の文字起こし(STT)の手段。Claude API は音声を受け取らないため、今はフレーム+広告本文のみで解析している
- AI生成の人物・音声を使う場合の Meta の開示ラベル要否
- BigQuery への実書き込み・実APIでの `daily` の通し実行(このリポジトリではユニットテストのみ実施)
- ~~ffmpeg を使う `render` / フレーム切り出しの実行確認~~ → 2026-09-28 訂正: ffmpeg は `apt-get install ffmpeg`
  で導入できる(実行環境依存の未確認事項ではなかった)。実際の壁は下記。
- **CR解析の実データ実行(訂正・新規)**: 2026-09-28、このリポジトリを操作するリモート実行セッションの
  ネットワークポリシーが Meta の配信CDN(`*.fbcdn.net`。creative の image_url/thumbnail_url/動画ダウンロード元)
  への直接アクセスを拒否することを確認した(403、ポリシー拒否)。Meta Ads MCP 経由の広告本文・タイトル・CTA・
  動画の長さ(ads_get_ad_videos の length。ダウンロード不要)は取得できるが、画素・音声そのものは取得できない。
  これが解消するまで、CR解析は `analysis_scope='text_only'`(本文・タイトル・CTAのみ。視覚項目はNULL)に限られる。
  解消には、このセッションの環境設定(環境メニュー→Edit→Network access)で `*.fbcdn.net` を許可するか、
  ffmpeg・ネットワークとも制約の無い別実行環境(須原さんのローカル、または専用のGCP実行基盤等)に移す必要がある。

## テスト

```bash
pip install -e ".[dev]" && pytest -q
```

判定ロジック(統計・ファネル分解・配信の偏り・失速・パターン分析・新CR判定・事実チェック)は外部接続なしでテストできます。

## コネクタだけで回す運用(トークン不要・現在の運用)

トークンや鍵を登録せず、Claude のコネクタ(Meta Ads MCP / BigQuery / Salesforce / Slack)と定期実行(Routine)で毎朝回す。

1. Meta Ads MCP で直近7日の広告×日を取得し、`raw_ad_daily` の同期間を削除して入れ直す
   - CV は `omni_complete_registration`。**結果が無い日は NULL ではなく 0 を入れる**(NULL は「0件」と区別できず、判定から外れる)
   - Mechanic_Lead で最適化している広告は `cv = NULL`、`cv_definition = 'mechanic_lead_unavailable_via_meta_ads_mcp'`
2. 直近35日を JSON で取り出し、`python -m meta_autopilot.offline --rows rows.json --target-cpa 5800 --label トヨワク` で判定
3. Salesforce で直近35日の Meta 経由の整備士数を数え、整備士CPA を添えて Slack に送る

目標CPA ¥5,800 は「整備士CPA ¥40,000 × 整備士9件 ÷ 登録62件」(2026-08-24〜09-27)から換算した値。
整備士の件数が少ないので、1〜2か月ごとに見直す。
