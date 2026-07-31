# 運用メモ — Slack 📥 → Notion INBOX

セットアップは完了しています。**日々の使い方はこれだけ**です。
(構築手順・トラブルシュートは [README.md](README.md) を参照)

## 使い方

**Slack の `#6-attracting` でメッセージに 📥(`:inbox_tray:`)を押す。**
それだけで Notion のタスクDBに **INBOX** で 1 件入ります。

登録されるもの:

| Notion のプロパティ | 中身 |
|---|---|
| 名前 | `Slack｜{投稿者}｜{本文先頭40字}` |
| ステータス | `INBOX` |
| 担当者 | 須原弘之 |
| テキスト | Slack本文全文 / 投稿者 / チャンネル / Slackリンク / リアクション名 / 登録日時(JST) |
| Slackリンク | 元メッセージへのリンク(クリックで飛べる) |
| 対応日・締切日・プロジェクトDB | 空欄(あとで自分で埋める) |

**登録後は朝レビューで仕分ける**、という前提の入口です。INBOX に溜めて、
あとでステータス・対応日・締切日・プロジェクトを付けて整理します。

## 使えるチャンネルを増やす / 減らす

**`inbox-to-notion` を招待したチャンネルなら、パブリックでもプライベートでもどこでも使えます。**

```
増やす: そのチャンネルで  /invite @inbox-to-notion
減らす: そのチャンネルで  /remove @inbox-to-notion
```

**これだけです。** GAS 側の設定変更もデプロイも要りません。
Slack は Bot が参加していないチャンネルのイベントを送ってこないので、
**招待するかどうかがそのまま「有効/無効」のスイッチ**になります。

> 特定チャンネルだけに絞りたくなったら、スクリプト プロパティ `TARGET_CHANNEL_ID` に
> チャンネルIDをカンマ区切りで入れます(空 = 限定なし)。

## 覚えておくこと

- **押せるのは須原弘之さん(`U0BHT8ZB4`)だけ。** 他の人が押しても登録されません。
  これが実質の安全弁なので、`ALLOWED_SLACK_USER_ID` は安易に広げないこと。
- **同じメッセージは 1 回だけ。** 📥 を外してもう一度押しても増えません
  (「Slackリンク」の完全一致で判定しているため)。
- **📥 を外しても Notion のページは消えません。** 不要なら Notion 側で削除してください。
- **📥 以外の絵文字では登録されません。**
- スレッドの返信に押しても拾えます。
- ファイルやキャンバスに押した場合は対象外です(メッセージ本体に押してください)。

## 動かなくなったら

まず **GAS の実行ログ**を見ます。

1. https://script.google.com → **Slack INBOX to Notion** を開く
2. 左メニューの **実行数(Executions)**
3. `doPost` の行を開くとログが読める

| ログ | 意味 |
|---|---|
| 実行履歴が 1 件も無い | Slack から届いていない → Slack App の Event Subscriptions を確認 |
| `skip: ...` | 届いているが門番で弾かれた。理由がそのまま書いてあります |
| `[deny] REQUEST_SECRET が一致しません` | Request URL の `?secret=` がずれている |
| 赤いエラー行 | メッセージに原因と対処が書いてあります → README の「トラブルシュート」へ |

## 止めたいとき

**一時的に止める(おすすめ)**

Slack App 管理画面 → **Event Subscriptions** → **Enable Events** を **オフ**
→ Slack がイベントを送らなくなります。戻すのはオンにするだけ。

**完全に止める**

GAS エディタ → **デプロイ → デプロイを管理** → 対象デプロイの **アーカイブ**
→ Web App の URL が無効になります。

どちらの場合も **Notion に既に入っているタスクは消えません。**

## 設定を変えたいとき

`~/my-project/slack-inbox-to-notion/` で:

```bash
open -e .env.local        # 値を編集
npm run env:check         # 確認(値は表示されません)
npm run props:push        # GAS へ反映
# → GAS エディタで setupPropertiesFromEnvLocal を 1 回実行
npm run props:clean       # 後片付け
```

コードを直した場合は、そのあと **同じ URL のまま**再デプロイします:

```bash
npm run deployments                        # デプロイID(AKfycb…)を確認
npx clasp deploy --deploymentId <既存のID> # URL を変えずに新バージョンを公開
```

> `npm run deploy` だけだと**新しい URL が発行され、Slack の Request URL を
> 貼り直す必要が出ます。** URL を保ちたいときは上の `--deploymentId` を使ってください。

## 変えるとしたら

- **対象チャンネルを増やす** … いまは 1 チャンネルのみ。`TARGET_CHANNEL_ID` を
  カンマ区切り対応にする改修が必要です。
- **押せる人を増やす** … `ALLOWED_SLACK_USER_ID` も同様に複数対応の改修が必要です。
- **📥 を外したら Notion からも消す** … `reaction_removed` の購読と削除処理の追加が必要です。
- **Slack に成否を返信する** … `chat:write` スコープの追加が必要です
  (現在はスコープ最小化のため付けていません)。
