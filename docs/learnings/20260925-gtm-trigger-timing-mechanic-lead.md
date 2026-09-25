# 整備士イベント(Mechanic_Lead)が止まった原因は GTM トリガーの発火タイミングだった

- 日付: 2026-09-25
- 種別: バグ修正 / 調査
- 触れたファイル: company/knowledge/business.md（GTM本体はリポジトリ外: GTM-K65GPM9S）

## 問題
トヨワクの Meta ピクセルで、整備士登録時に送る `Mechanic_Lead` が 2026-09-20 朝以降 0 件になった。
SF 上は同期間に資格欄「自動車整備士」の登録が続いていた。同じトリガーを使う Google 広告の整備士CV(TechSol)も 9/18 以降 0 件。

## 文脈
- タグ本体は GTM(web) のカスタムHTML `fbq('trackCustom','Mechanic_Lead')`。トリガー85は DOM Ready で
  「URL が complete|reg-entry」かつ「`#license` の innerText が 自動車整備士|自動車検査員」。
- GTM の公開は 9/17 が最後で、GTM 側の変更は無かった。
- 完了ページを後からコンソールで見ると `#license` は読めた（＝条件は満たしているように見える）。

## 解法と、その理由
1. GTM の公開履歴 → 変更なし。Google 広告の他CVは毎日計上 → GTM 自体は動いている。
2. テスト登録で完了ページを実測 → URL・資格表示・会員ID・fbq すべて OK。なのに Meta に `Mechanic_Lead` が届かない。
3. 「判定時点(DOM Ready)では資格欄が未描画で空、表示後に見ると読める」と判断し、
   トリガーを「ウィンドウの読み込み」に変更＋リロード判定を追加、タグに `eventID: 'mech_'+{{会員ID}}` を付与。
4. 公開後のテスト登録で Meta に `Mechanic_Lead` が届くことを確認（ブラウザ1件＋サーバー1件のペア）。

## うまくいかなかったこと
- Comet ブラウザでのテスト: 標準のトラッキング防止で fbq が無く、Tag Assistant も接続できず、判断材料にならなかった。
- `performance.getEntriesByType('resource')` で facebook.com/tr への送信を探す方法: 送信が記録に出ず空だった。
  Meta 側の受信統計（1時間程度の遅延あり）で確かめるしかなかった。
- 「CompleteRegistration が偶数件＝イベント設定ツールの2ルールで二重計上」と一度推定したが、
  イベント元別に見ると「ブラウザ1件＋サーバー1件」のペアだった。推定は誤り。

## 抽出したルール / ヒューリスティック
- ページ内の文字を条件にする GTM トリガーは、DOM Ready ではなく「ウィンドウの読み込み」以降で判定する。
  コンソールで後から読めても、判定時点で読めた証拠にはならない。
- 計測テストは、トラッキング防止のあるブラウザ(Comet/Brave等)では行わない。普通の Chrome のシークレットで行う。
- Meta の受信件数が偶数で揃っているときは、二重発火と決めつける前に `event_source` 別（WEB/SERVER）に分けて見る。

## 関連
- [20260925-meta-sf-mechanic-join.md](20260925-meta-sf-mechanic-join.md)
