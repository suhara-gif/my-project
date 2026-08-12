# SMA クロスオーバー自動売買 Bot (Alpaca ペーパートレード)

移動平均クロスオーバー戦略の株式自動売買 Bot です。記事でよく紹介される
「短期線が長期線を上抜けたら買う」構成を、安全装置込みで実装しています。

- **戦略**: 短期SMA (デフォルト20日) が長期SMA (50日) を上抜けたら買い、下抜けたら売り
- **安全装置**: 利確・損切りはブラケット注文で取引所側に常設 / 1日の損失上限で新規買い停止 / デフォルトはペーパートレード
- **バックテスト**: ルックアヘッド防止 (翌日始値約定)、スリッページ・手数料込み
- **依存ライブラリなし**: Python 3.10+ の標準ライブラリのみで動作

> ⚠️ **免責**: これは学習用のサンプルです。利益を保証するものではなく、特定銘柄の売買を推奨するものでもありません。実際のバックテストでも、この戦略は単純なバイ&ホールドに負けることが珍しくありません。投資は必ず余剰資金・自己責任で。

## クイックスタート (APIキー不要)

```bash
cd trading-bot
python3 -m unittest discover -s tests   # テスト実行
python3 run_backtest.py                 # 同梱の合成データでバックテスト
python3 run_backtest.py --fast 10 --slow 30   # パラメータを変えて再検証
```

`data/sample/` の CSV は `gen_sample_data.py` が生成した**合成データ**です
(実在銘柄の実際の価格ではありません)。エンジンの動作確認と学習用です。

## 実データで使う (Alpaca APIキーが必要)

1. [Alpaca](https://alpaca.markets/) の口座を開設し、ダッシュボードで **Paper Trading** の APIキーを発行
2. `.env` を作成:

   ```bash
   cp .env.example .env
   # ALPACA_API_KEY と ALPACA_SECRET_KEY を記入
   ```

3. 実データでバックテスト:

   ```bash
   python3 run_backtest.py --fetch --symbols AAPL MSFT GOOGL --start 2020-01-01
   ```

4. ペーパートレードで実行:

   ```bash
   # config.json の symbols を実在銘柄に変更してから
   python3 run_bot.py           # dry-run: 判定のみ、注文は出さない
   python3 run_bot.py --trade   # ペーパー口座に実際に発注
   ```

## 定期実行 (VPS / cron)

市場が開いている時間帯に1日1回動かします。市場が閉まっていれば何もせず終了するので、
多少ズレても安全です。例 (米東部時間10:00 = UTC 14:00/15:00 頃):

```cron
30 14 * * 1-5 cd /path/to/trading-bot && /usr/bin/python3 run_bot.py --trade >> bot.log 2>&1
```

## 設定 (config.json)

| キー | 意味 | デフォルト |
|---|---|---|
| `symbols` | 対象銘柄 | 合成データの5銘柄 |
| `fast_period` / `slow_period` | 短期/長期SMAの日数 | 20 / 50 |
| `position_fraction` | 1回のエントリーで使う資産割合 | 0.10 (10%) |
| `take_profit_pct` / `stop_loss_pct` | 利確 / 損切りライン | +15% / -7% |
| `daily_loss_limit_pct` | 1日の損失がこれを超えたら新規買い停止 | 3% |
| `slippage_pct` / `commission_pct` | バックテストの摩擦コスト | 0.05% / 0% |

## 構成

```
trading-bot/
├── run_backtest.py      # バックテストCLI
├── run_bot.py           # 売買判定CLI (cronから呼ぶ)
├── gen_sample_data.py   # 合成サンプルデータ生成
├── config.json          # 戦略・リスク設定
├── .env.example         # APIキーのテンプレート (.envにコピー)
├── sma_bot/
│   ├── strategy.py      # SMA計算とクロス判定
│   ├── backtest.py      # バックテストエンジンと成績指標
│   ├── broker.py        # Alpaca Trading APIクライアント
│   ├── bot.py           # 1日1回の売買判定ロジック
│   ├── data.py          # CSV読み書き・Alpacaデータ取得
│   └── config.py        # 設定読み込み
├── data/sample/         # 合成データ (動作確認用)
└── tests/               # ユニットテスト
```

## 安全設計のポイント

- **デフォルトはペーパートレード**。本番口座 (`api.alpaca.markets`) に接続するには、
  環境変数 `ALPACA_LIVE=1` と `ALPACA_LIVE_CONFIRM=yes-i-understand-the-risk` の
  両方を明示的に設定する必要があります。
- **利確・損切りは Bot 側で監視せず、ブラケット注文で取引所側に置く**。
  VPS や Bot が落ちている間も損切りが機能します。
- **1日の損失上限**を超えたら、その日は新規買いを出しません。
- **ルックアヘッド防止**: バックテストではシグナル当日の終値ではなく翌営業日の始値で約定させます。
  ここを間違えると成績が実力より良く見えます。

## よくある落とし穴

- **カーブフィッティング**: パラメータを過去データに合わせて調整しすぎると、
  バックテストの成績は上がるのに実運用では機能しなくなります。
  期間を分けて検証する (例: 2020-2023で調整し、2024以降で確認する) のが基本です。
- **バイ&ホールドとの比較を必ず見る**: このリポジトリのバックテストは
  「同じ銘柄を買って放置した場合」を常に併記します。それに勝てない戦略を
  動かす意味があるかは冷静に判断してください。
- **APIキーの管理**: `.env` はコミット禁止 (`.gitignore` 済み)。VPS に置く場合は
  ファイル権限を `chmod 600 .env` にしてください。
