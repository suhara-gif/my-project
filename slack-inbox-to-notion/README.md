# Slack 📥 → Notion INBOX (slack-inbox-to-notion)

Slack のメッセージに **📥(`:inbox_tray:`)** を押すと、その内容が **Notion のタスクDB に
「INBOX」ステータスで 1 件登録**される仕組みです。あとで整理する前提の「とりあえず放り込む」入口。

- 方式: **Slack Events API → Google Apps Script(Web App) → Notion API**
- Workflow Builder は使いません(有料プラン依存・分岐が書けないため)。
- Zapier / Make など課金前提の外部自動化も使いません。
- カスタムエージェントも使いません。動くのは GAS のスクリプト 1 本だけです。

## 動きの全体像

```
Slack #6-attracting のメッセージに 📥 を押す
        ↓ Slack Events API (reaction_added)
GAS Web App  doPost()
        ↓  ① 4つの門番(リアクション/押した人/チャンネル/メッセージ種別)で弾く
        ↓  ② Slack API で 本文・投稿者・permalink を取得
        ↓  ③ Notion に同じ「Slackリンク」が無いか確認(重複判定)
        ↓  ④ 無ければ pages.create
Notion タスクDB に INBOX として 1 件
```

## 構成ファイル

| ファイル | 役割 |
|---|---|
| `slack_inbox_to_notion.gs` | 本体。これ 1 枚を GAS プロジェクトに貼る。 |
| `.env.example` | スクリプト プロパティに入れる項目の雛形(placeholder のみ)。 |
| `README.md` | この文書。セットアップ・テスト・切り分け。 |

> **秘密情報はコードに書きません。** トークン類はすべて GAS の
> 「プロジェクトの設定 → スクリプト プロパティ」に人間が入力します。
> `.env.example` は「何を入れるか」の一覧であって、GAS からは読み込まれません。

---

## セットアップ

### A. Notion 側

1. タスクDB に以下のプロパティがあることを確認します(名前は完全一致)。

   | プロパティ名 | 型 | 用途 |
   |---|---|---|
   | `名前` | タイトル | `Slack｜{投稿者}｜{本文先頭40字}` |
   | `ステータス` | ステータス(または選択) | `INBOX` を入れる |
   | `担当者` | ユーザー(または選択/テキスト) | 須原弘之 |
   | `テキスト` | テキスト | Slack本文全文 + メタ情報 |
   | `Slackリンク` | URL | 元メッセージの permalink。**重複判定キー** |

   「ステータス」に **`INBOX` という選択肢**を作っておいてください(無いと Notion 側で弾かれます)。
   `対応日` `締切日` `プロジェクトDB` はスクリプトが触らないので空欄のままになります。

2. https://www.notion.so/profile/integrations で内部インテグレーションを作成し、
   **Internal Integration Token**(`ntn_` 始まり)を控えます。
3. タスクDB のページを開き、右上 `…` → **接続 → 作成したインテグレーション名** を選びます。
   **この接続を忘れると API から 404 になります**(最頻出のつまずき)。
4. DB の URL から **データベースID**(32桁の16進)を控えます。
   `https://www.notion.so/<workspace>/<★ここ★>?v=...`

### B. Slack App 側

1. https://api.slack.com/apps → **Create New App → From scratch**。ワークスペースを選択。
2. **OAuth & Permissions → Bot Token Scopes** に、次の **3 つだけ**追加します。

   | スコープ | 何に使うか | 無いとどうなるか |
   |---|---|---|
   | `reactions:read` | `reaction_added` イベントの購読 | イベント購読を登録できない |
   | `channels:history` | `conversations.history` / `.replies` で本文取得 | `missing_scope` で本文が取れない |
   | `users:read` | `users.info` で投稿者の表示名 | 投稿者が `U…` の ID 表記のまま |

   **これ以上は付けません。** 特に:
   - `chat.getPermalink` は**追加スコープ不要**(Bot がチャンネルに居ればよい)。
   - `chat:write` は不要(このスクリプトは Slack に何も書き込みません)。
   - `channels:read` は不要(チャンネル表示名は `TARGET_CHANNEL_NAME` で固定するため)。
   - `#6-attracting` は**パブリック**チャンネルなので `groups:history` は不要です。
     (将来プライベート化するなら `groups:history` に読み替えが必要)

3. **Install to Workspace** し、**Bot User OAuth Token**(`xoxb-` 始まり)を控えます。
4. Slack で `#6-attracting` を開き、**`/invite @アプリ名`** で Bot を招待します。
   招待しないと `not_in_channel` になります。

### C. GAS 側

1. https://script.google.com で新規プロジェクトを作成。
2. `slack_inbox_to_notion.gs` の中身を丸ごと `コード.gs` に貼り付けて保存。
3. **プロジェクトの設定 → スクリプト プロパティ** に、下表の**必須7件**を入力。

   | キー | 例 / 値 |
   |---|---|
   | `SLACK_BOT_TOKEN` | `xoxb-…`(B-3 で控えたもの) |
   | `NOTION_API_TOKEN` | `ntn_…`(A-2 で控えたもの) |
   | `NOTION_TASK_DATABASE_ID` | A-4 の 32 桁 |
   | `NOTION_ASSIGNEE_USER_ID` | 須原弘之さんの Notion UUID(下記の調べ方) |
   | `ALLOWED_SLACK_USER_ID` | `U0BHT8ZB4` |
   | `TARGET_REACTION` | `inbox_tray` |
   | `TARGET_CHANNEL_ID` | `C06F5DJ74UU`(= `#6-attracting`) |

   任意項目(既定値があるので未設定でも動く)は `.env.example` を参照。
   `TARGET_CHANNEL_NAME=#6-attracting` は入れておくと Notion の「テキスト」が読みやすくなります。

   **さらに、共有シークレットを設定します**(次項 C-4)。

   **担当者の Notion ユーザーIDを調べる**: `NOTION_API_TOKEN` を入れた状態で、
   GAS エディタの関数選択から **`testListNotionUsers`** を実行 → 実行ログに
   「名前 <TAB> UUID」が並ぶので、須原弘之さんの UUID をコピーします。

4. **共有シークレットを設定する(推奨)**

   GAS は HTTP ヘッダを読めず Slack 署名検証ができません(→「制約」の項)。
   代わりに **Request URL に合言葉を付けて、Slack 以外からのリクエストを弾きます。**

   - **スクリプト プロパティ名: `REQUEST_SECRET`**
   - **URL に付けるクエリ名: `?secret=`**(この 2 つは別物です。**値だけが一致していれば OK**)

   手順:

   1. GAS エディタで関数 **`testGenerateSecret`** を実行します。
      実行ログにランダムな英数字 64 桁と、そのまま使える Request URL の形が出ます。
   2. その値を **スクリプト プロパティ `REQUEST_SECRET`** に貼ります。
   3. **同じ値**を、次の C-5 で控える Web App URL の末尾に `?secret=` として付けます
      (Slack に登録するのはこの「`?secret=` 付き」の URL です)。

   ```
   スクリプト プロパティ:
     REQUEST_SECRET = 8f3a1c...（testGenerateSecret が出した値）

   Slack に登録する Request URL:
     https://script.google.com/macros/s/AKfycb.../exec?secret=8f3a1c...
                                                    ~~~~~~~~~~~~~~~~~~
                                                    ↑ 同じ値を付ける
   ```

   注意:
   - **値に `&` `?` `#` `/` や空白を使わない**でください。URL のクエリとして壊れます。
     `testGenerateSecret` が出す値は英数字だけなので安全です。
   - この URL 自体が秘密になります。Slack の Request URL 欄以外に貼らないでください。
   - `REQUEST_SECRET` を設定したのに URL に `?secret=` を付け忘れると、
     **URL verification の時点で Verified になりません**(その場で気づけます)。
   - あとから値を変えるときは、**スクリプト プロパティと Slack の Request URL の両方**を
     更新してください。片方だけだと全イベントが `forbidden` で弾かれます。

5. **デプロイ → 新しいデプロイ → 種類: ウェブアプリ**
   - 次のユーザーとして実行: **自分**
   - アクセスできるユーザー: **全員**  ← ここが「全員」でないと Slack から叩けません
   - デプロイして表示される **`https://script.google.com/macros/s/…/exec`** を控えます
     (`/dev` の URL ではありません)。

### D. Slack にエンドポイントを登録

1. Slack App 管理画面 → **Event Subscriptions** → Enable Events を ON。
2. **Request URL** に、**C-5 の `…/exec` + C-4 の `?secret=…`** を貼ります。

   ```
   https://script.google.com/macros/s/<デプロイID>/exec?secret=<REQUEST_SECRET と同じ値>
   ```

   数秒で **Verified ✓** になれば URL verification 成功です。
   `?secret=` を付け忘れていると、ここで Verified になりません
   (GAS の実行ログに `[deny] REQUEST_SECRET が一致しません` が出ます)。

   > `REQUEST_SECRET` を設定していない場合は `?secret=` の無い `…/exec` をそのまま貼ります。

3. **Subscribe to bot events** に **`reaction_added`** を追加。
4. **Save Changes**。上部に再インストールを促すバナーが出たら **Reinstall** します。

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

上記イベント(本文が「新規整備士の獲得数が\n先週比で落ちている。要因分析したい。」の場合)で、
実際に組み立てられる payload です。

```json
{
  "parent": { "database_id": "00000000000000000000000000000000" },
  "properties": {
    "名前": {
      "title": [{ "text": { "content": "Slack｜須原弘之｜新規整備士の獲得数が 先週比で落ちている。要因分析したい。" } }]
    },
    "ステータス": { "status": { "name": "INBOX" } },
    "担当者": {
      "people": [{ "object": "user", "id": "00000000-0000-0000-0000-000000000000" }]
    },
    "テキスト": {
      "rich_text": [{ "text": { "content": "【Slack本文】\n新規整備士の獲得数が\n先週比で落ちている。要因分析したい。\n\n【投稿者】須原弘之\n【チャンネル】#6-attracting(C06F5DJ74UU)\n【Slackリンク】https://apty.slack.com/archives/C06F5DJ74UU/p1753800000123456\n【リアクション】:inbox_tray:\n【登録日時】2026-07-30 15:04:05 JST" } }]
    },
    "Slackリンク": { "url": "https://apty.slack.com/archives/C06F5DJ74UU/p1753800000123456" }
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

この方式には GAS 由来の避けられない制約が 2 つあります。**知らずに運用すると事故るので明記します。**

### 1. Slack の署名検証ができない

GAS の `doPost(e)` は **HTTP ヘッダを読めません**(`e` には `postData` / `parameter` しか無い)。
Slack が送る `X-Slack-Signature` / `X-Slack-Request-Timestamp` にアクセスできないため、
**署名検証は原理的に不可能**です。代わりに:

- Web App の URL(`/exec`)を**共有しない**。
- スクリプト プロパティ `REQUEST_SECRET` を設定し、Request URL に `?secret=…` を付ける(上記 C-4 / D-2)。
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

## テスト手順

Slack を経由しない順に進めると、どこで壊れているかが必ず特定できます。

### 手順 1: 設定の健康診断(Slack 不要)

GAS エディタで関数 **`testConfig`** を選んで実行します(初回は権限承認のダイアログが出ます)。
実行ログに `----- 要対応なし。testDryRun() に進んでください。 -----` が出れば OK。

確認される内容: 必須プロパティ7件 / **共有シークレット `REQUEST_SECRET` の設定有無と、
値に URL を壊す文字が入っていないか** / Slack 認証 / 対象チャンネルの読み取り可否 /
Notion DB の取得 / 5 つのプロパティの名前と型 / 「ステータス」に `INBOX` 選択肢があるか。

`REQUEST_SECRET` 未設定なら `[warn]` が出ます(動作はしますが、URL を知られると誰でも叩けます)。

### 手順 2: 書き込まずに通す(dry-run)

1. `#6-attracting` の適当なメッセージで「リンクをコピー」。
2. スクリプト プロパティに `TEST_MESSAGE_URL` = その URL を追加。
3. 関数 **`testDryRun`** を実行。

実行ログに **Notion へ送る予定の JSON がそのまま出ます**。
タイトル・担当者・テキストの中身をここで目視確認してください。Notion には何も書き込まれません。

### 手順 3: 実際に 1 件登録する

関数 **`testRegister`** を実行 → Notion に 1 件増えることを確認。

**続けてもう一度 `testRegister` を実行**してください。
ログが `skip: 同じ Slackリンクが既に登録済み(page id=…)` になれば、**重複判定が効いています**。

### 手順 4: Slack から本番の経路で

1. `#6-attracting` のメッセージに 📥 を押す → Notion に 1 件増える。
2. **同じメッセージの 📥 を外してもう一度押す** → 増えない(重複判定)。
3. **別の絵文字**(👀 など)を押す → 増えない。
4. **他の人**に 📥 を押してもらう → 増えない。
5. **別チャンネル**で 📥 を押す → 増えない。

各ケースの結果は GAS の **「実行数」画面**でログを見れば理由まで分かります。

> テストが終わったら `TEST_MESSAGE_URL` は消してよいです。

---

## 失敗時の切り分け

まず見るのは GAS の **「実行数(Executions)」** 画面です。`doPost` の行を開くとログが読めます。
**実行が 1 行も無い = Slack から届いていない**(下表の A)。**実行はあるがログが `skip:` = 門番で弾かれた**(B)。

### A. GAS に実行履歴がまったく無い

| 症状 | 原因 | 対処 |
|---|---|---|
| Request URL が Verified にならない | デプロイのアクセス権が「全員」でない | デプロイを編集して「アクセスできるユーザー: 全員」 |
| 同上 | `/dev` の URL を貼っている | `/exec` の URL に差し替える |
| 同上 | `REQUEST_SECRET` を設定したのに URL に `?secret=` が無い | Request URL を `…/exec?secret=<REQUEST_SECRET と同じ値>` にする |
| 同上 | `?secret=` の値とプロパティの値がずれている | 両方を同じ値に揃える(`testGenerateSecret` で作り直すのが確実) |
| ログに `[deny] REQUEST_SECRET が一致しません` | 同上 | 同上 |
| Verified 済みだが反応しない | `reaction_added` を購読していない | Event Subscriptions → Subscribe to **bot** events に追加 |
| 同上 | スコープ追加後に再インストールしていない | Slack App を **Reinstall** |
| 昨日まで動いていたのに止まった | 「新しいデプロイ」を作って URL が変わった | 下記「コードを直すとき」を参照 |

### B. 実行履歴はあるが Notion に増えない

ログの `skip:` をそのまま読めば理由が出ます。

| ログ | 意味 | 対処 |
|---|---|---|
| `skip: reaction=…` | 別の絵文字だった | 📥(`:inbox_tray:`)を押す |
| `skip: user=…` | 押した人が許可外 | `ALLOWED_SLACK_USER_ID` を確認 |
| `skip: channel=…` | 別チャンネルだった | `TARGET_CHANNEL_ID` を確認 |
| `skip: item.type=file` | ファイルへのリアクション | メッセージ本体に押す |
| `skip: … 既に登録済み` | 正常。重複を弾いた | Notion 側の既存行を消せば再登録できる |

### C. エラーで落ちている

| エラー文言 | 原因 | 対処 |
|---|---|---|
| `Slack API … invalid_auth` | `SLACK_BOT_TOKEN` が誤り | `xoxb-` 始まりの Bot Token か確認 |
| `Slack API … not_in_channel` | Bot が未招待 | `#6-attracting` で `/invite @アプリ名` |
| `Slack API … missing_scope` | スコープ不足 | ログの `needed=` を見て追加 → Reinstall |
| `Notion API … HTTP 401` | `NOTION_API_TOKEN` が誤り | インテグレーションのトークンを再確認 |
| `Notion API … HTTP 404` | DB にインテグレーション未接続 / ID 誤り | DB の `…` → 接続 → インテグレーション名 |
| `Notion DB に「○○」プロパティがありません` | プロパティ名の不一致 | ログ末尾に**実際の名前一覧**が出るので照合。DB 側を直すか `PROP_*` で上書き |
| `Notion の「ステータス」は … 型ですが` | 型が想定外 | ステータス/選択/テキストのいずれかに変更 |
| `Notion API … validation_error` | `INBOX` 選択肢が無い / 担当者 UUID が誤り | `testConfig` の warn を確認、`testListNotionUsers` で UUID 再取得 |
| `スクリプト プロパティが未設定です: …` | 必須項目の入れ忘れ | 列挙されたキーを設定 |
| `スクリプトロックを取得できませんでした` | 同時実行の競合 | 放置でよい(Slack の再送で処理される) |

### D. Notion に同じものが 2 件できた

「Slackリンク」が完全一致でなければ別物として登録されます。次を確認してください。

- 手で作った行の「Slackリンク」に**末尾スラッシュや `?thread_ts=…` が付いていないか**。
  スクリプトは必ず `chat.getPermalink` が返す形式を使うので、手入力の URL とは一致しないことがあります。
- 重複判定は `Slackリンク` プロパティに対して行うので、**このプロパティ名を変えたら
  `PROP_SLACK_URL` も合わせて更新**してください。

---

## コードを直すとき(重要)

GAS はコードを保存しただけでは公開版に反映されません。かつ、
**「新しいデプロイ」を押すと URL が変わり、Slack 側の再設定が必要になります。**

URL を保ったまま更新する手順:

**デプロイ → デプロイを管理 → 対象の鉛筆アイコン → バージョン: 「新バージョン」 → デプロイ**

## この仕組みが持っていない機能

正直に書いておきます。必要になったら拡張してください。

- 📥 を**外しても** Notion のページは消えません(`reaction_removed` は購読していません)。
- スレッドの親子関係・添付ファイル・画像は Notion に持っていきません(本文テキストと permalink のみ)。
- 対象チャンネルは 1 つだけです(複数にするなら `TARGET_CHANNEL_ID` をカンマ区切り対応にする改修が必要)。
- Slack 側への成否通知はしません(`chat:write` を付けない判断のため)。結果は GAS の実行ログで見ます。
