# Slack 📥 → Notion INBOX (slack-inbox-to-notion)

Slack のメッセージに **📥(`:inbox_tray:`)** を押すと、その内容が **Notion のタスクDB に
「INBOX」ステータスで 1 件登録**される仕組みです。あとで整理する前提の「とりあえず放り込む」入口。

- 方式: **Slack Events API → Google Apps Script(Web App) → Notion API**
- Workflow Builder は使いません。Zapier / Make など課金前提の外部自動化も使いません。
- カスタムエージェントも使いません。動くのは GAS のスクリプト 1 本だけです。
- **コードは `clasp` で GAS へ push します。エディタへの手コピペは不要です。**

```
Slack #6-attracting のメッセージに 📥 を押す
        ↓ Slack Events API (reaction_added)
GAS Web App  doPost()
        ↓  ① 門番(合言葉/リアクション/押した人/チャンネル/種別)で弾く
        ↓  ② Slack API で 本文・投稿者・permalink を取得
        ↓  ③ Notion に同じ「Slackリンク」が無いか確認(重複判定)
        ↓  ④ 無ければ pages.create
Notion タスクDB に INBOX として 1 件
```

## 構成ファイル

| ファイル | 役割 |
|---|---|
| **[`RUNBOOK.md`](RUNBOOK.md)** | **構築後の運用メモ。日々の使い方・止め方・設定変更はこちら。** |
| `slack_inbox_to_notion.gs` | 本体。clasp が GAS へ push する。 |
| `appsscript.json` | GAS のマニフェスト。**Web App の公開設定(全員/自分として実行)と最小 OAuth スコープをここで宣言**しているので、デプロイ設定を画面で選ぶ必要がない。 |
| `.clasp.json.example` | clasp の設定雛形。実体 `.clasp.json` は `npm run create` / `clone` が生成(gitignore 済み)。 |
| `.claspignore` | GAS へ送るファイルを 3 つだけに限定。 |
| `.env.example` | 設定値の雛形。`cp .env.example .env.local` して実値を入れる。 |
| `package.json` | clasp まわりの npm scripts。 |
| `tools/gen-setup-properties.mjs` | `.env.local` から**スクリプト プロパティ一括設定用の使い捨てファイル**を生成。 |
| `tools/clean-setup-properties.mjs` | その使い捨てファイルをローカル・GAS 双方から削除。 |
| `tools/gen-secret.mjs` | 共有シークレットのランダム値を生成。 |
| `tools/print-webapp-url.mjs` | デプロイ済み Web App の URL を `?secret=` 付きで組み立てて表示。 |
| `slack-app-manifest.yml` | Slack App 作成用マニフェスト①(そのまま貼れる)。 |
| `slack-app-manifest.with-events.yml` | Request URL 登録用マニフェスト②(1 行だけ書き換え)。 |

> **秘密情報はリポジトリに入れません。** 実値は `.env.local`(gitignore 済み)にだけ書き、
> そこから GAS のスクリプト プロパティへ流し込みます。`.env.example` と 2 つのマニフェストは
> placeholder のままコミットされます。

---

## あなたが手でやること(全体像)

自動化できたところは自動化しました。**残る手作業はこれだけ**です。

| # | やること | 所要 |
|---|---|---|
| 1 | Notion インテグレーション作成 + タスクDB に「接続」 | 2分 |
| 2 | Slack App をマニフェスト①から作成 → インストール | 2分 |
| 3 | `#6-attracting` に Bot を招待(`/invite @inbox-to-notion`) | 10秒 |
| 4 | Apps Script API を ON(トグル1つ) | 10秒 |
| 5 | `npm run login`(ブラウザで Google 認証) | 30秒 |
| 6 | `.env.local` に 4 つの値を貼る | 2分 |
| 7 | GAS エディタで関数を 2 回実行(初回認可を含む) | 1分 |
| 8 | マニフェスト②に URL を貼って Slack に適用 → Reinstall | 1分 |
| 9 | 動作テスト | 3分 |

コマンドはすべてコピペで流せます。**値を手で入力するのは手順 6 の 4 箇所だけ**です。

---

## セットアップ

### 前提

`node`(18 以上)、`npm`、`git` が入っていること。`clasp` は `npm install` で入ります。

> ### ⚠ このセットアップは「あなたのローカルPC」で実行してください
>
> **Claude Code のクラウドセッション(claude.ai/code の web セッション)では実行できません。**
> クラウド実行環境のネットワークポリシーが `script.google.com` / `slack.com` /
> `api.notion.com` への接続を **403 で拒否**するため、`clasp login` も `clasp push` も
> 到達できません(GitHub と npm レジストリのみ許可)。
>
> 加えて、クラウド側にトークンを渡すにはチャットへ貼る必要があり、これは秘密の扱いとして
> 不適切です。コンテナは一定時間で破棄されるため `.env.local` も残りません。
>
> **クラウドセッションでできること**: コードの変更、テスト(モック)、README 更新、PR 作業。
> **ローカルでしかできないこと**: `clasp` 経由の GAS 反映・デプロイ、実 API を叩く
> `testConfig` / `testDryRun` / `testRegister`、Slack 実機テスト。
>
> 確認コマンド:
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" https://script.google.com/
> ```
> **`302`(や `200`)が返れば到達できています** — 数字が何であれ接続自体は成功しています。
> **`000` は接続できていない**(ポリシー拒否)ので、そのマシンでは進められません。

```bash
cd slack-inbox-to-notion
npm install
```

> 順序が重要です。**A→B→C→D→E** の順に進めてください。
> 「Slack の Bot Token が GAS の設定に必要」「GAS のデプロイ URL が Slack の設定に必要」と
> 依存が交差しているため、この順以外だと必ずどこかで詰まります。

### A. Notion 側(あなたの手作業 ①)

1. https://www.notion.so/profile/integrations で内部インテグレーションを作成し、
   **Internal Integration Token** を控えます。
2. タスクDB のページを開き、右上 `…` → **接続 → 作成したインテグレーション名**。
   **これを忘れると API から 404 になります**(最頻出のつまずき)。
3. DB の URL から **データベースID**(32桁の16進)を控えます。
   `https://www.notion.so/<workspace>/<★ここ★>?v=...`
4. タスクDB のプロパティを確認します(名前は完全一致)。

   | プロパティ名 | 型 | 用途 |
   |---|---|---|
   | `名前` | タイトル | `Slack｜{投稿者}｜{本文先頭40字}` |
   | `ステータス` | ステータス(または選択) | `INBOX` を入れる |
   | `担当者` | ユーザー(または選択/テキスト) | 須原弘之 |
   | `テキスト` | テキスト | Slack本文全文 + メタ情報 |
   | `Slackリンク` | URL | 元メッセージの permalink。**重複判定キー** |

   **「ステータス」に `INBOX` という選択肢を作っておいてください**(無いと Notion 側で弾かれます)。
   `対応日` `締切日` `プロジェクトDB` はスクリプトが触らないので空欄のままになります。

### B. Slack App を作る(あなたの手作業 ②③)

1. https://api.slack.com/apps → **Create New App → From an app manifest** → ワークスペース選択
2. **YAML** タブに `slack-app-manifest.yml` の中身を**そのまま貼って** Create。
   (このマニフェストは書き換え不要です。スコープ 3 つだけが入っています)
3. **Install to Workspace** → 許可。
4. **OAuth & Permissions → Bot User OAuth Token** を控えます。
5. Slack で `#6-attracting` を開き、**`/invite @inbox-to-notion`** で Bot を招待します。
   招待しないと `not_in_channel` になります。

> Event Subscriptions はまだ設定しません(GAS のデプロイ URL が要るため。手順 E で行います)。

### C. GAS にコードと設定を反映する

#### C-1. Apps Script API を ON(あなたの手作業 ④)

https://script.google.com/home/usersettings を開き、**「Google Apps Script API」を ON**。
clasp がプロジェクトを作成・更新するのに必要です。トグル 1 つだけ。

#### C-2. Google 認証(あなたの手作業 ⑤)

```bash
npm run login
```

ブラウザが開くので Google アカウントで許可します。

#### C-3. GAS プロジェクトを用意する

**パターン A: 新規に作る場合**

```bash
npm run create
```

新しい GAS プロジェクトが作られ、`.clasp.json` が生成されます。
(このコマンドは `clasp create` の直後に `git checkout -- appsscript.json` を実行します。
clasp がテンプレートで `appsscript.json` を上書きしてしまい、Web App の公開設定が
消えるのを戻すためです)

**パターン B: 既存の GAS プロジェクトに紐づける場合**

既存プロジェクトの**スクリプトID**を用意します
(GAS エディタ → プロジェクトの設定 → スクリプト ID、または URL の
`https://script.google.com/home/projects/★ここ★/edit`)。

```bash
cp .clasp.json.example .clasp.json
# .clasp.json を開いて <GASプロジェクトのスクリプトID> を実際のIDに置き換える
```

または clasp に取りに行かせる場合:

```bash
npx clasp clone <スクリプトID> --rootDir .
git checkout -- appsscript.json   # clone がテンプレートで上書きするため戻す
```

> ⚠ パターン B は**既存プロジェクトの中身を置き換えます**。`clasp push` は
> ローカルに無いファイルをリモートから削除します。既存コードがある場合は
> 先に `npx clasp pull` で退避するか、新規プロジェクト(パターン A)を使ってください。

#### C-4. 共有シークレットを生成する

GAS は HTTP ヘッダを読めず Slack 署名検証ができません(→「制約」の項)。
代わりに **Request URL に合言葉を付けて、Slack 以外からのリクエストを弾きます。**

- **スクリプト プロパティ名: `REQUEST_SECRET`**
- **URL に付けるクエリ名: `?secret=`**

名前は違いますが、**値が一致していれば OK** です。

**この値は次の C-5 (`npm run env:init`) が自動生成して `.env.local` に書き込むので、
ここで何かする必要はありません。** 人間がシークレットの実値を目にする場面はありません。

> **シークレットの実値を画面に出さないこと。** ターミナルに表示すると、スクロールバック・
> スクリーンショット・チャットへの貼り付けで漏れます(このリポジトリの構築中に実際に
> チャットへ流出させ、ローテーションする羽目になりました)。
> `npm run url:full` の出力も `?secret=` 付きの完全 URL なので、**共有・貼り付け厳禁**です。
> クリップボード経由で Slack の入力欄へ直接貼ってください:
> ```bash
> npm run url:full | tail -1 | tr -d ' ' | pbcopy
> ```
>
> 漏らしてしまったら `npm run env:init -- --force` でローテーションできます
> (GAS プロパティの再投入と Slack の Request URL 貼り直しの**両方**が必要)。

#### C-5. `.env.local` に実値を入れる(あなたの手作業 ⑥)

```bash
npm run env:init
```

`.env.example` から `.env.local` を作り、**共有シークレットを自動生成して書き込みます**
(C-4 を手でやる必要はありません)。**シークレットは画面に一切表示しません** —
ターミナルのスクロールバックやスクリーンショット経由で漏れるためです。
値が必要になるのは Slack の Request URL を作るときだけで、そこは `npm run url:full` が
`.env.local` から読んで組み立てます。

次に `.env.local` を開いて、**`<...>` になっている 3 箇所だけ**実値に置き換えます。

```bash
open -e .env.local     # macOS。テキストエディットで開きます
```

> `.env.local` は**先頭がドットの隠しファイル**なので Finder には出てきません。
> 上のコマンドで開くのが確実です。

| キー | 何を入れるか |
|---|---|
| `SLACK_BOT_TOKEN` | B-4 で控えた Bot User OAuth Token |
| `NOTION_API_TOKEN` | A-1 で控えた Internal Integration Token |
| `NOTION_TASK_DATABASE_ID` | A-3 で控えた 32 桁 |

`REQUEST_SECRET` は `env:init` が生成済みです。残り
(`NOTION_ASSIGNEE_USER_ID` / `ALLOWED_SLACK_USER_ID` / `TARGET_REACTION` /
`TARGET_CHANNEL_ID` / `TARGET_CHANNEL_NAME`)は**確定値が入っているのでそのままで OK** です。

入力できたか確認します(**値は表示されません**):

```bash
npm run env:check
```

`✓ 必須項目はすべて設定済みです` が出れば次へ進めます。

> `.env.local` は `.gitignore` 済みです。コミットされません。
>
> 確認を `node -e "..."` のワンライナーで代用しないでください。**zsh はダブルクォート内の
> `!` を履歴展開として解釈する**ため、`if (!x)` を含むワンライナーが
> `zsh: event not found` で落ちます(実際に踏みました)。`npm run env:check` を使ってください。

#### C-6. コードとプロパティを GAS へ push

```bash
npm run props:push
```

これは 2 つのことをします。

1. `.env.local` を読んで `setup.local.gs`(スクリプト プロパティを一括設定する
   使い捨てファイル)を生成
2. `clasp push` で本体 + マニフェスト + 使い捨てファイルを GAS へ反映

値の不備(必須キーの埋め忘れ、`REQUEST_SECRET` に URL を壊す文字が入っている等)は
ここで止まります。

#### C-7. GAS エディタで 2 つの関数を実行(あなたの手作業 ⑦)

```bash
npm run open
```

エディタが開いたら、上部の関数選択から順に実行します。

1. **`setupPropertiesFromEnvLocal`** を実行
   - **初回は認可ダイアログが出ます。**「詳細」→「(プロジェクト名)に移動」→ 許可。
     求められる権限は「外部サービスへの接続」だけです(`appsscript.json` で最小宣言済み)。
   - 実行ログにスクリプト プロパティ 9 件が設定されたことが出ます(トークン類はマスク表示)。
2. **`testConfig`** を実行
   - `----- 要対応なし -----` が出れば設定は健全です。
   - 何か出たら「トラブルシュート」へ。

#### C-8. 使い捨てファイルを消す

```bash
npm run props:clean
```

`setup.local.gs`(秘密情報の実値が入っている)をローカルからも GAS プロジェクトからも削除します。
**プロパティ自体は GAS に保存済みなので消えません。** 設定を変えたくなったら
`.env.local` を直して C-6〜C-8 をもう一度回すだけです。

### D. Web App としてデプロイする

```bash
npm run deploy
npm run url:full
```

`npm run deploy` はコマンドラインだけで完結します(公開設定は `appsscript.json` の
`webapp` セクションで宣言済みなので、画面でプルダウンを選ぶ必要はありません)。

`npm run url:full` は **Slack にそのまま貼れる URL** を表示します:

```
https://script.google.com/macros/s/AKfycb.../exec?secret=0a1b2c...
```

> **端末に秘密が表示されます。** 出力を貼り付け・共有しないでください。
> 画面共有中は `npm run url`(secret を伏せる)を使ってください。
> クリップボードへ直接送るのが安全です:
> ```bash
> npm run url:full | tail -1 | tr -d ' ' | pbcopy
> ```

### E. Slack に Request URL を登録する(あなたの手作業 ⑧)

**画面で設定するのが確実です**(実環境ではこちらで通しました):

1. https://api.slack.com/apps → 作ったアプリ → 左メニュー **Event Subscriptions**
2. **Enable Events** を **オン**
3. **Request URL** に `npm run url:full` の URL を貼る(上のクリップボード経由が安全)
4. 数秒で **Verified ✓** になるのを確認
5. **Subscribe to bot events** を開く → **`Add Bot User Event`** → `reaction_added` を追加
6. **Save Changes**
7. 上部に出る **「Reinstall your app」** を押して許可

> ⚠ **手順 5 は必須です。** マニフェスト①には `event_subscriptions` を入れていないため
> (アプリ作成時点では GAS の URL が無く、URL 検証で弾かれるため)、
> **`reaction_added` は最初 "No events added yet." の状態です。**
> ここを飛ばすと Verified ✓ になっても 📥 を押して何も起きません。

<details>
<summary>マニフェストで設定する場合(任意)</summary>

`slack-app-manifest.with-events.yml` の `request_url:` の 1 行だけを
`npm run url:full` の出力に置き換え、**App Manifest → YAML** タブに貼って Save。
**書き換えたマニフェストをコミットしないでください**(秘密を含む URL になります)。
</details>

---

## clasp でどこまで CLI 化できたか

| 作業 | CLI 化 | 備考 |
|---|---|---|
| コードの反映 | ✅ `npm run push` | 手コピペ不要 |
| Web App の公開設定(全員/自分として実行) | ✅ `appsscript.json` | 画面でプルダウンを選ぶ必要なし |
| OAuth スコープの宣言 | ✅ `appsscript.json` | 外部接続 1 つだけに最小化 |
| デプロイ | ✅ `npm run deploy` | |
| Web App URL の取得 | ✅ `npm run url:full` | `?secret=` 付きで出力 |
| スクリプト プロパティの設定 | ⚠ 半自動 | **API が存在しない**ため、`.env.local` → 使い捨て `.gs` → エディタで 1 回実行、という経路にした |
| **初回の OAuth 認可** | ❌ 不可 | Google の仕様。エディタで 1 回関数を実行して許可する必要がある |
| **Apps Script API の有効化** | ❌ 不可 | ユーザー設定のトグル。1 回だけ |
| **Google ログイン** | ❌ 不可 | `npm run login` からブラウザで認証 |
| Slack App の作成 | ⚠ 半自動 | マニフェスト貼り付けで 1 手。Slack の CLI/API はアプリ作成に別途トークンが要り、かえって手数が増えるため採用せず |

**スクリプト プロパティについて**: Apps Script API にはスクリプト プロパティを外部から
設定するエンドポイントがありません(`clasp run` は使えますが、GCP プロジェクトの差し替えと
OAuth クライアント作成が必要で、プロパティ 9 件を手で打つより手間が増えます)。
そのため「ローカルの `.env.local` から使い捨ての `.gs` を生成 → push → 1 回実行 → 削除」
という経路にしています。**あなたの操作は「エディタで関数を 1 回実行」だけ**です。

---

## スクリプト プロパティ

必須 7 件。`.env.local` から `npm run props:push` で一括設定されます。

| キー | 値 | 出どころ |
|---|---|---|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token | 人間が入力 |
| `NOTION_API_TOKEN` | Internal Integration Token | 人間が入力 |
| `NOTION_TASK_DATABASE_ID` | タスクDB の ID | 人間が入力 |
| `NOTION_ASSIGNEE_USER_ID` | 担当者の Notion UUID | `.env.example` に設定済み |
| `ALLOWED_SLACK_USER_ID` | `U0BHT8ZB4` | `.env.example` に設定済み |
| `TARGET_REACTION` | `inbox_tray` | `.env.example` に設定済み |
| `TARGET_CHANNEL_ID` | `C06F5DJ74UU` | `.env.example` に設定済み |

任意(既定値あり): `REQUEST_SECRET`(**設定推奨**) / `TARGET_CHANNEL_NAME` /
`TITLE_BODY_LENGTH` / `NOTION_STATUS_VALUE` / `NOTION_ASSIGNEE_NAME` / `NOTION_VERSION` /
`PROP_TITLE` / `PROP_STATUS` / `PROP_ASSIGNEE` / `PROP_TEXT` / `PROP_SLACK_URL` /
`TEST_MESSAGE_URL`(テスト用)

---

## Slack App の必要スコープ(最小)

マニフェストに書いてある **3 つだけ**です。

| スコープ | 何に使うか | 無いとどうなるか |
|---|---|---|
| `reactions:read` | `reaction_added` イベントの購読 | イベント購読を登録できない |
| `channels:history` | `conversations.history` / `.replies` で本文取得 | `missing_scope` で本文が取れない |
| `users:read` | `users.info` で投稿者の表示名 | 投稿者が `U…` の ID 表記のまま |

これ以上は付けません:
- `chat.getPermalink` は**追加スコープ不要**(Bot がチャンネルに居ればよい)
- `chat:write` は不要(Slack へは何も書き込まない)
- `channels:read` は不要(チャンネル表示名は `TARGET_CHANNEL_NAME` で持つ)
- `#6-attracting` は**パブリック**なので `groups:history` は不要
  (将来プライベート化するなら `groups:history` に読み替えが必要)

---

## 入力と出力の例

### 入力 ①: URL verification(登録時に 1 回だけ来る)

```json
{
  "token": "Jhj5dZrVaK7ZwHHjRyZWjbDl",
  "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P",
  "type": "url_verification"
}
```

応答(`Content-Type: text/plain`、ステータス 200):

```
3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P
```

> この応答は**他のスクリプト プロパティを検証する前**に返しています。
> トークン類が未入力でも URL 登録だけは通るので、切り分けが楽になります。

### 入力 ②: 📥 が押されたとき(`reaction_added`)

```json
{
  "type": "event_callback",
  "event_id": "Ev01ABCDEFGH",
  "team_id": "T0BHT8ZAA",
  "event": {
    "type": "reaction_added",
    "user": "U0BHT8ZB4",
    "reaction": "inbox_tray",
    "item": {
      "type": "message",
      "channel": "C06F5DJ74UU",
      "ts": "1753800000.123456"
    },
    "event_ts": "1753800005.000100"
  }
}
```

### 出力: Notion `pages.create` に送る中身

本文が「新規整備士の獲得数が\n先週比で落ちている。要因分析したい。」の場合:

```json
{
  "parent": { "database_id": "<NOTION_TASK_DATABASE_ID>" },
  "properties": {
    "名前": {
      "title": [{ "text": { "content": "Slack｜須原弘之｜新規整備士の獲得数が 先週比で落ちている。要因分析したい。" } }]
    },
    "ステータス": { "status": { "name": "INBOX" } },
    "担当者": {
      "people": [{ "object": "user", "id": "101ad74a-c85a-4070-89d3-b37cd3c2c4af" }]
    },
    "テキスト": {
      "rich_text": [{ "text": { "content": "【Slack本文】\n新規整備士の獲得数が\n先週比で落ちている。要因分析したい。\n\n【投稿者】須原弘之\n【チャンネル】#6-attracting(C06F5DJ74UU)\n【Slackリンク】https://<workspace>.slack.com/archives/C06F5DJ74UU/p1753800000123456\n【リアクション】:inbox_tray:\n【登録日時】2026-07-30 15:04:05 JST" } }]
    },
    "Slackリンク": { "url": "https://<workspace>.slack.com/archives/C06F5DJ74UU/p1753800000123456" }
  }
}
```

Notion 上での見え方:

| 名前 | ステータス | 担当者 | 対応日 | 締切日 | Slackリンク |
|---|---|---|---|---|---|
| Slack｜須原弘之｜新規整備士の獲得数が 先週比で… | INBOX | 須原弘之 | (空欄) | (空欄) | (元メッセージへ) |

補足:
- タイトルの本文部分は**改行・連続空白を半角スペース1個に潰し**、40字を超えたときだけ末尾に `…` を付けます。
- 本文が 2000 字を超える場合、Notion の rich_text 上限に合わせて**分割して全文**を保持します(切り捨てません)。

---

## 何をスキップするか(門番の順番)

上から順に判定し、1つでも外れたら Notion を一切触らずに終了します。

| # | 条件 | 外れたときのログ |
|---|---|---|
| 0 | `REQUEST_SECRET` 設定時、URL の `?secret=` が一致 | `[deny] REQUEST_SECRET が一致しません` |
| 1 | `event.type` が `reaction_added` | `skip: event.type=…` |
| 2 | リアクションが `inbox_tray` | `skip: reaction=eyes(対象は inbox_tray)` |
| 3 | 押した人が `U0BHT8ZB4` | `skip: user=U9999(許可は U0BHT8ZB4 のみ)` |
| 4 | `item.type` が `message`(ファイル等は対象外) | `skip: item.type=file` |
| 5 | `item.channel` が `C06F5DJ74UU` | `skip: channel=C0OTHER(対象は C06F5DJ74UU)` |
| 6 | 同じ `event_id` を処理済みでない | `skip: event_id=… は処理済み(Slack の再送)` |
| 7 | 同じ「Slackリンク」が Notion に無い | `skip: 同じ Slackリンクが既に登録済み(page id=…)` |

肌色バリアント(`inbox_tray::skin-tone-3` 等)は `inbox_tray` として扱います。
スレッド返信に押した場合も拾えます(`conversations.history` が空なら `conversations.replies` を見る)。

---

## 制約と、その回避策

GAS 由来の避けられない制約が 2 つあります。**知らずに運用すると事故るので明記します。**

### 1. Slack の署名検証ができない

GAS の `doPost(e)` は **HTTP ヘッダを読めません**(`e` には `postData` / `parameter` しか無い)。
Slack が送る `X-Slack-Signature` / `X-Slack-Request-Timestamp` にアクセスできないため、
**署名検証は原理的に不可能**です。代わりに:

- Web App の URL(`?secret=` 付き)を**共有しない**。
- `REQUEST_SECRET` を設定する(C-4)。
- 万一 URL が漏れても、門番 3(押した人が `U0BHT8ZB4` のみ)と門番 7(重複排除)があるため、
  作れるのは「本人が押した実在メッセージ 1 件」に限られます。

### 2. Slack の 3 秒ルールとイベント再送

Slack は **3 秒以内に 200 が返らないとイベントを再送**します。このスクリプトは Slack API を
3 本 + Notion API を 2〜3 本呼ぶので、3 秒を超えることがあります。そこで
**「速く返す」のではなく「再送されても二重登録しない」**方向で解いています。

| 層 | 仕組み | 効く場面 |
|---|---|---|
| ロック | `LockService` のスクリプトロック | 再送が同時到着したときの競合 |
| キャッシュ | `event_id` を 1 時間記憶 | Slack の再送(最長 5 分程度) |
| Notion | 「Slackリンク」完全一致で検索 | 後日の押し直し・キャッシュ失効後 |

想定外のエラー時は **500 を返して Slack に再送させます**(握り潰して 200 を返すと、
押したリアクションが黙って消えるため)。三重の重複排除があるので再送は安全です。

---

## 実環境テスト手順

Slack を経由しない順に進めると、どこで壊れているかが必ず特定できます。
**手順 1・2 は Slack の Request URL 登録(E)より前に実行できます。**

### 手順 1: `testConfig` — 設定の健康診断(Slack 経路不要)

GAS エディタで **`testConfig`** を実行。
`----- 要対応なし。testDryRun() に進んでください。 -----` が出れば OK。

確認される内容: 必須プロパティ7件 / 共有シークレットの設定有無と値の妥当性 /
Slack 認証 / 対象チャンネルの読み取り可否 / Notion DB の取得 /
5 つのプロパティの名前と型 / 「ステータス」に `INBOX` 選択肢があるか。

### 手順 2: `testDryRun` — 書き込まずに通す

1. `#6-attracting` に**テストとわかる文面**で 1 件投稿し、`…` → **リンクをコピー**。
   (`testRegister` で実際に Notion に登録されるので、あとで判別できる文面にする)
2. GAS エディタ左の **⚙ プロジェクトの設定** → **スクリプト プロパティ** →
   **プロパティを追加** で 1 行足します。

   | 左の入力欄(プロパティ) | 右の入力欄(値) |
   |---|---|
   | `TEST_MESSAGE_URL` | コピーした Slack リンク |

   > ⚠ **入力欄のラベル自体が「プロパティ」「値」なので間違えやすい箇所です。**
   > 左に**キー名**(`TEST_MESSAGE_URL`)、右に**URL** を入れます。
   > 逆に入れると `[NG] スクリプト プロパティ TEST_MESSAGE_URL に ... 設定してください` が出ます。
   > 既存の 9 件(`SLACK_BOT_TOKEN` など)と同じ並びに見えるかを目安にしてください。

   → **スクリプト プロパティを保存**

3. エディタに戻り **`testDryRun`** を実行。

実行ログに **Notion へ送る予定の JSON がそのまま出ます**。
タイトル・担当者・テキストの中身をここで目視確認してください。Notion には何も書き込まれません。

### 手順 3: `testRegister` — 実際に 1 件登録

エディタで **`testRegister`** を実行 → Notion に 1 件増えることを確認。

**続けてもう一度 `testRegister` を実行**してください。
ログが `skip: 同じ Slackリンクが既に登録済み(page id=…)` になれば、**重複判定が効いています**。

### 手順 4: Slack 本番経路

| # | やること | 期待 |
|---|---|---|
| 1 | `#6-attracting` のメッセージに 📥 | Notion に 1 件増える |
| 2 | 同じメッセージの 📥 を外してもう一度押す | 増えない(重複判定) |
| 3 | 別の絵文字(👀 など)を押す | 増えない |
| 4 | 他の人に 📥 を押してもらう | 増えない |
| 5 | 別チャンネルで 📥 を押す | 増えない |

各ケースの結果は GAS の **「実行数」画面**でログを見れば理由まで分かります。

> テストが終わったら `TEST_MESSAGE_URL` は消してよいです。

---

## トラブルシュート(発生しやすい順)

まず見るのは GAS の **「実行数(Executions)」** 画面です。`doPost` の行を開くとログが読めます。

### ① GAS の URL verification が通らない(Slack が Verified にならない)

上から順に確認してください。

| 確認 | 対処 |
|---|---|
| デプロイしたか | `npm run deploy` を実行。`@HEAD` はテスト用で Slack からは使えません |
| URL は `/exec` か | `/dev` は不可。`npm run url:full` の出力をそのまま使う |
| `?secret=` を付けたか | `REQUEST_SECRET` 設定時は必須。GAS ログに `[deny] REQUEST_SECRET が一致しません` が出ていれば確定 |
| `?secret=` の値が一致しているか | `.env.local` の値と GAS のスクリプト プロパティが同じか確認 |
| 公開設定が「全員」か | `appsscript.json` の `webapp.access` が `ANYONE_ANONYMOUS` であること。手でデプロイした場合は「アクセスできるユーザー: 全員」 |
| 初回認可を済ませたか | エディタで 1 回関数を実行して許可(C-7)。未認可だと Web App が動きません |
| GAS に実行履歴が 1 件も無い | Slack からリクエストが届いていない = 上記のどれか |

### ② Slack イベントが来ない(Verified なのに反応しない)

| 確認 | 対処 |
|---|---|
| `reaction_added` を購読したか | Event Subscriptions → Subscribe to **bot** events(user events ではない) |
| スコープ追加後に再インストールしたか | Slack App を **Reinstall** |
| Bot がチャンネルに居るか | `#6-attracting` で `/invite @inbox-to-notion` |
| 昨日まで動いていたのに止まった | 「新しいデプロイ」で URL が変わった可能性(→「コードを直すとき」) |

### ③ Slack API でメッセージが読めない

GAS ログのエラー文言で判定します。

| エラー | 対処 |
|---|---|
| `not_in_channel` | `#6-attracting` で `/invite @inbox-to-notion` |
| `missing_scope` | ログの `needed=` を見てスコープ追加 → Reinstall |
| `invalid_auth` / `not_authed` | `SLACK_BOT_TOKEN` が誤り。`xoxb-` 始まりの Bot Token か確認 |
| `channel_not_found` | `TARGET_CHANNEL_ID` が誤り、または Bot 未招待 |
| `Slack メッセージを取得できません` | 上記のいずれか。まず `testConfig` を実行して切り分ける |

### ④ Notion DB が読めない

| エラー | 対処 |
|---|---|
| `HTTP 401` | `NOTION_API_TOKEN` が誤り |
| `HTTP 404` | **DB にインテグレーションを「接続」していない**(最頻出)、または DB ID が誤り |
| `Notion DB に「○○」プロパティがありません` | プロパティ名の不一致。ログ末尾に**実際の名前一覧**が出るので照合。DB 側を直すか `PROP_*` で上書き |
| `Notion の「ステータス」は … 型ですが` | ステータス/選択/テキストのいずれかに変更 |

### ⑤ Notion の `pages.create` で失敗する

| エラー | 対処 |
|---|---|
| `validation_error` + ステータス関連 | 「ステータス」に **`INBOX` の選択肢が無い**。Notion 側に追加(`testConfig` が warn で教えます) |
| `validation_error` + 担当者関連 | `NOTION_ASSIGNEE_USER_ID` が誤り。`testListNotionUsers` を実行して UUID を取り直す |
| `HTTP 400` でプロパティ名が出る | その名前のプロパティが DB に無い、または型が違う |

### ⑥ 重複判定が効かない(同じものが 2 件できる)

「Slackリンク」が**完全一致**でなければ別物として登録されます。

| 確認 | 対処 |
|---|---|
| 手で作った行の URL に `?thread_ts=…` や末尾スラッシュが付いていないか | スクリプトは必ず `chat.getPermalink` の形式を使うため、手入力の URL とは一致しません |
| `PROP_SLACK_URL` を変えていないか | プロパティ名を変えたら `PROP_SLACK_URL` も更新が必要 |
| `Slackリンク` の型が URL か | テキスト型だと URL フィルタが効きません |
| 2 件とも同時刻に作られたか | ロック取得に失敗した可能性。GAS ログに `スクリプトロックを取得できませんでした` が無いか確認 |

### その他

| エラー | 対処 |
|---|---|
| `スクリプト プロパティが未設定です: …` | 列挙されたキーを設定(`.env.local` を直して C-6〜C-8) |
| clasp が `User has not enabled the Apps Script API` | C-1 のトグルを ON |
| `npm run url` が「バージョン付きのデプロイが見つかりません」 | 先に `npm run deploy` |
| 認可ダイアログで「このアプリは確認されていません」 | 自分で作ったプロジェクトなので「詳細」→「(名前)に移動」で進めてよい |

---

## コードを直すとき

```bash
npm run push     # コードを GAS に反映(この時点ではまだ公開版は変わらない)
npm run deploy   # 新しいバージョンをデプロイ
```

⚠ **`clasp deploy` は毎回新しいデプロイを作り、URL が変わります。**
URL が変わると Slack の Request URL を貼り直す必要があります。**URL を保ちたい場合**は、
既存のデプロイIDを指定して更新してください。

```bash
npm run deployments                        # デプロイID(AKfycb…)を確認
npx clasp deploy --deploymentId <既存のID> # 同じURLのまま新バージョンを公開
```

GAS エディタから行う場合は
**デプロイ → デプロイを管理 → 鉛筆アイコン → バージョン「新バージョン」→ デプロイ**。
(「新しいデプロイ」を押すと URL が変わります)

---

## この仕組みが持っていない機能

正直に書いておきます。必要になったら拡張してください。

- 📥 を**外しても** Notion のページは消えません(`reaction_removed` は購読していません)。
- スレッドの親子関係・添付ファイル・画像は Notion に持っていきません(本文テキストと permalink のみ)。
- 対象チャンネルは 1 つだけです(複数にするなら `TARGET_CHANNEL_ID` をカンマ区切り対応にする改修が必要)。
- Slack 側への成否通知はしません(`chat:write` を付けない判断のため)。結果は GAS の実行ログで見ます。
