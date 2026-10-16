# network-diagnostics — 自宅ネット回線の実測診断

自宅の回線が遅いとき、推測ではなく実測で原因を切り分けるためのツール。
**この2本のスクリプトは、実際に自宅Wi-Fi/ルーターに接続しているマシン
(自分のMacやLinux機)で実行すること。** クラウド上のセッションで実行しても
自宅回線の実測にはならない。

## 使い方

```bash
# 1. 計測して results/ にJSONで保存する (ラベルを変えて何度でも実行できる)
python3 net_diag.py --label before

# (何か対策をした後に、もう一度)
python3 net_diag.py --label after-router-reboot

# 2. 指標を整理して見る
python3 analyze.py results/xxxx_before.json

# 3. 前後比較する
python3 analyze.py --before results/xxxx_before.json --after results/xxxx_after-router-reboot.json
```

依存はPython標準ライブラリのみ(追加インストール不要)。ただし以下の外部コマンドが
入っている前提: `ping`, `traceroute`(無ければ`tracepath`)。Wi-Fi計測は
macOSでは`system_profiler`(標準搭載)、Linuxでは`iw`(未インストールなら
`apt install iw` 等)を使う。バッファブロート計測(`networkQuality`)はmacOS専用。

## 計測項目

1. **Wi-Fi**: RSSI・ノイズ・SNR・リンク速度・規格・チャンネル・帯域幅
2. **IPv6**: グローバルアドレスの有無・デフォルト経路の有無
3. **遅延**: デフォルトゲートウェイ / 1.1.1.1 / 8.8.8.8 への平均・最大・ロス率(`ping -c 10`)
4. **経路**: 1.1.1.1・8.8.8.8 それぞれへの traceroute 先頭4ホップ(IP・応答時間)
5. **DNS**: ルーター(=ゲートウェイIPと仮定)・1.1.1.1・8.8.8.8 への応答時間
   (標準ライブラリの`socket`だけで自前UDPクエリを投げるので `dig` 不要)
6. **スループット**: 単一接続ダウンロードと6並列ダウンロード
   (既定は日本国内(Linode Tokyo)の非WAF静的ファイル。CloudflareのSpeed Testは
   Python製クライアントをボット判定で403にすることがあり、User-Agent偽装では
   回避できないため使っていない。また遠いリージョンのファイルだと長いRTTで
   単一接続スループットがTCPウィンドウで頭打ちになり、単一/並列比較が歪む点にも
   注意。`--throughput-url`で別の静的ファイルホストに変更可)
7. **バッファブロート**: `networkQuality -v` のRPMとアイドル遅延(macOSのみ)

失敗したセクションは結果を止めずに `"error"` として記録される。Wi-Fiの
フィールド名解析はOSバージョンで変わりやすいので、失敗時も `"raw"` に
生出力を必ず残している。

## analyze.py が出力するタグの意味

- `[実測]` — JSONの値をそのまま読んでいる事実
- `[推測]` — 複数の実測値を組み合わせた仮説(結論ではない)
- `[未検証]` — このツールでは確認できない、または計測自体が失敗した
- `[要確認]` — 判断のために追加で必要な情報(契約回線の種別、時間帯を変えた再測定など)

`analyze.py` は「ボトルネックはこれだ」と断定はしない。指標を並べて分類する
だけなので、最終的な原因の絞り込みと対策の優先順位付けは、この出力を見て
人間(またはこのJSON/出力を渡されたClaude)が行う。

## プライバシー

`results/*.json` はデフォルトで `.gitignore` により追跡対象外にしている
(ローカルIP・traceroute経路などが含まれるため)。前後比較の記録をリポジトリに
残したい場合は、明示的に `git add -f` すること。
