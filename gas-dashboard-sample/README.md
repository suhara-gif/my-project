# GAS Dashboard Sample

NewsPicksの記事「ClaudeCode×GASだけで社内アプリを爆速公開」を参考に、
**スプレッドシートをDB代わりに使い、GASのHTMLサービスでグラフ付き
ダッシュボードを公開する**最小構成を試すためのサンプルです。

記事にあった「GAS Auto Pilot」スキル（ブラウザ手動アップロード不要でGASに
デプロイできるツール）は前提が異なるため使わず、代わりに標準の `clasp` CLI
でこのリポジトリのコードをそのままデプロイできる構成にしています。

## 構成

| ファイル | 役割 |
|---|---|
| `Code.gs` | サーバーサイド。`doGet()` でHTMLを返し、`getDashboardData()` でスプレッドシートの値をJSONで返す |
| `index.html` | クライアントサイド。Chart.jsで日別推移グラフ・チャネル別合計グラフを描画し、期間・チャネルで絞り込みできる |
| `appsscript.json` | マニフェスト。Webアプリの公開範囲などを定義 |

データは `SampleData` という名前のシートに `date / channel / amount` の3列で
持たせる想定です。ダミーデータ投入用の `setupSampleData()` 関数を用意して
あるので、実データを用意しなくてもすぐ動作確認できます。

## デプロイ手順（clasp）

このセッションはGitHubリポジトリの操作までしかできません。以下はご自身の
ローカル環境またはこのファイル一式をダウンロードした環境で実行してください。

```bash
# 1. clasp のインストールとログイン（初回のみ）
npm install -g @google/clasp
clasp login

# 2. このディレクトリに移動
cd gas-dashboard-sample

# 3. 新規のGoogleスプレッドシート＋紐づくGASプロジェクトを作成
#    （「スプレッドシートをDB代わりに使う」構成のため、type は sheets）
clasp create --type sheets --title "GAS Dashboard Sample" --rootDir .

# 4. コードをプッシュ
clasp push

# 5. Apps Scriptエディタを開く
clasp open
```

エディタが開いたら:

1. 紐づくスプレッドシート（`clasp open --webapp` ではなくエディタ上部のリンク
   か、Apps Scriptの「概要」から開けます）を開き、メニューの
   「ダッシュボード → サンプルデータを投入」を実行してデモデータを作成
2. Apps Scriptエディタで「デプロイ → 新しいデプロイ → 種類の選択: ウェブアプリ」
3. アクセスできるユーザーを選択（下記「権限設定について」を参照）してデプロイ
4. 発行されたURLにアクセスして表示確認

## 権限設定について

`appsscript.json` の `webapp.access` は `"DOMAIN"`（同一Google Workspace
ドメイン内の全員）にしてあります。これは記事にもある「経費データのような
重要情報を意図せず流出させない」ための既定値です。

**個人のGoogleアカウント（Workspaceでない@gmail.comなど）ではDOMAIN制限が
使えません。** その場合はデプロイ時に「自分のみ」または「全員」を選ぶ必要が
あります。サンプルデータとはいえ、実データを入れて試す場合は公開範囲を
必ず確認してください。

## GASの6分制限について

このサンプルは1回のリクエストで全件（サンプルは最大約90日分の少量データ）
を読み込む簡易構成のため、6分の実行時間制限には該当しません。実データで
行数が数万〜数十万件規模になる場合は、`getDashboardData()` 側で期間や件数
を絞り込む・ページングするなどの対応が必要になります。

## 実データに置き換える場合

1. `SampleData` シートの列構成（`date / channel / amount`）に実データを
   合わせるか、`Code.gs` の `getDashboardData()` を実データの列構成に
   合わせて書き換える
2. `setupSampleData()` は初回の動作確認用なので、実運用に入ったら削除するか
   呼び出さないようにする
