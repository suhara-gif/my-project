# 合成サンプルデータ

このディレクトリのCSVは `gen_sample_data.py` が生成した**合成データ**です。
実在銘柄の実際の価格ではありません。バックテストエンジンの動作確認・学習専用です。

実データで検証するには Alpaca の APIキーを `.env` に設定して
`python run_backtest.py --fetch --symbols AAPL MSFT` を実行してください。
