# セカンドブレイン (second-brain)

Fable を「あなたのビジネスを内側まで知っている機械」に変えるための仕組みです。
同じモデルでも、**あなた固有の知識**に接地させると、コードはあなたの設計に沿い、
文章はあなたの声で、主張はあなたが所有するリサーチの上に立ちます。しかも
**ファイルが増えるほど毎回の実行が賢くなる**——知識は積み上がり続けるからです。

保管庫(vault)は **Obsidian で開くただの Markdown フォルダ**。人間はアプリで、
エージェントはフォルダで、同じ脳を見ます。プラグインもコネクタも不要です。
Obsidian は**アカウント不要の無料アプリ**で、無くてもシステムは完全に動きます
(グラフビューを見たい人だけ入れればよい)。スマホで読みたい人向けには、週次総合
だけを Notion にミラーする任意機能があります(下記)。

## なぜ効くか

最も賢いモデルでも、あなたを知らなければ平均的な仕事しか出せません。文脈が無いから
一般論を「推測」するのです。自分の知識ベースに挿すと、同じモデルが別物になります。
そして **raw/(素材)と compiled(まとめ)を分けたリンク型の wiki** は、検索型と違い、
大きくなるほど雑音ではなく強さが増えます——新しいページが web に接続し、周囲を強くする。

## 構造:4 つだけ(karpathy の「知識ベース=コードベース」)

Obsidian がエディタ、モデルがプログラマ、wiki がコード。ピースは 4 つ:

| ピース | 役割 |
|---|---|
| `raw/` | 取り込んだ素材を**無加工**で置く読み取り専用の履歴。**絶対に書き換えない**(地の真実) |
| `entities/` | 具体物 1 つ = 1 ページ(クライアント/競合/ツール/人物) |
| `concepts/` | 考え方 1 つ = 1 ページ(戦略/パターン/学び) |
| `INDEX.md` | 玄関。compiled ページを 1 行説明付きで列挙。開かずに「何があるか」を知る |

**書き込みルール 4 つ**: ①1 ファイル 1 レッスン(冒頭に 1 行サマリ) ②重複を作らず更新する
③間違いは削除する ④raw と compiled を常に分ける。
エージェントの仕事は**コンパイル**——raw を読み、entity/concept を更新・リンクする。

リンク `[[…]]` は知識グラフの辺。回答は全走査せず、リンクを辿って(クライアント→施策
→競合…)記憶のように歩きます。

## 構成ファイル

| ファイル | 役割 |
|---|---|
| `lib.sh` | 共通関数(設定読込・ログ・ロック・再帰ガード・git チェックポイント・claude 実行) |
| `new-vault.sh` | vault の骨組み(raw/entities/concepts/syntheses + INDEX/CLAUDE.md + サンプル)を作り git 初期化 |
| `session-mine.sh` | **SessionEnd フック**。終わったセッションを採掘し raw/sessions/ に日付きノート |
| `compile.sh` | **日次**。前回以降の raw を読み wiki を更新(安いモデル) |
| `lint.sh` | **週次**。矛盾・重複・切れリンク・孤立を点検/軽微修正(安いモデル) |
| `synthesize.sh` | **週次**。vault 横断で「今週の変化・ドリフト・注目」を 1 枚に(賢いモデル) |
| `research.sh` | リサーチ機。問いを小問に割り→並行調査→懐疑ゲート→検証済み日付きページ着地 |
| `install.sh` | ~/.claude/second-brain/ へ配置し、フックとスケジュールを有効化 |
| `settings.snippet.json` | SessionEnd フックの手動マージ用断片 |
| `project-CLAUDE.snippet.md` | 各プロジェクトの CLAUDE.md に貼る「knowledge」3 行 |
| `vault-template/` | new-vault.sh が配置する vault の雛形一式 |

## インストール(ローカルPCで実行)

> 育てる対象は**あなたのローカル vault** です。クラウドセッションではなくローカルで。

```bash
git clone <this-repo> && cd <this-repo>/second-brain
./install.sh
./new-vault.sh ~/vault      # まだ vault が無ければ
```

`install.sh` がやること:
1. キット一式を `~/.claude/second-brain/` へ配置
2. `~/.claude/settings.json` に SessionEnd フック(session-mine.sh)をマージ(jq 使用)
3. スケジュール登録: 夜間コンパイル(毎日 02:15)、週次 lint(日 03:15)、週次総合(日 04:15)
   ※ macOS は launchd、その他は cron

### 設定(環境変数 / `~/.claude/second-brain/config`)

| 変数 | 既定 | 説明 |
|---|---|---|
| `SECOND_BRAIN_VAULT` | `~/vault` | vault の場所 |
| `SECOND_BRAIN_MODEL_CHEAP` | `haiku` | ルーチン(採掘/コンパイル/lint)のモデル |
| `SECOND_BRAIN_MODEL_SMART` | `opus` | 週次総合・リサーチのモデル |
| `SECOND_BRAIN_MIN_INTERVAL` | `900` | セッション採掘の最小間隔(秒) |
| `SECOND_BRAIN_GIT` | `1` | 書き込み後に git チェックポイントを打つ |
| `SECOND_BRAIN_RESEARCH_EXPIRE_DAYS` | `30` | リサーチ結果の既定失効日数 |
| `SECOND_BRAIN_RESEARCH_MCP` | (自動検出) | リサーチで許可する MCP サーバー名(空白区切り)。未設定なら `claude mcp list` から検出 |
| `SECOND_BRAIN_CLAUDE_BIN` | (install 時に自動検出) | claude CLI の実体パス。**launchd/cron はログインシェルの PATH を引き継がない**ため、スケジュール実行で「claude CLI 不在」スキップが出る場合はここを確認 |
| `SECOND_BRAIN_NOTION_MIRROR` | `0` | `1` で週次総合を Notion にミラー(スマホ閲覧用の窓。テキストのみ) |
| `SECOND_BRAIN_NOTION_MCP` | `Notion` | ミラーに使う Notion MCP サーバー名(`claude mcp list` の表示名) |
| `SECOND_BRAIN_NOTION_PARENT` | `セカンドブレイン週次総合` | ミラー先の親ページ名(無ければ自動作成) |

## 使い方

### 1. goal でバックフィル(最初の一括投入)

`raw/` に手持ちを流し込んでから(古いチャット・ブックマーク・メモ・クライアント
フォルダ・過去リサーチ)、Claude Code を vault で開き `/goal` を使います。ゴールは
**判定役が読める証拠を要求**する形にするのがコツ:

> 「raw/ の全ファイルを compile し、entities/ と concepts/ を作成・更新して INDEX に
> 反映せよ。**各変更は before/after の diff で示す**こと。**出典(raw/)リンクの無い
> ページは信頼せずフラグを立てる**。全 raw にまとめページからの被リンクが付いたら完了。」

### 2. ループで生かし続ける

思い出したときだけ育つ脳は 3 週間で死にます。だから維持はスケジュールで回します
(install.sh が登録):

- **毎セッション後**: `session-mine.sh` が決定・ミス・パターンを raw/sessions/ に採掘
- **毎晩**: `compile.sh` が新 raw を wiki に反映(安いモデル=ルーチン階層)
- **毎週**: `lint.sh` が矛盾・重複・死リンクを狩る(腐り防止)
- **毎週**: `synthesize.sh` が横断で今週の総合を書く(**ここだけ賢いモデルが席に見合う**)

### 2.5 週次総合を Notion で読む(任意)

vault 本体はローカルの Markdown のまま(地の真実は動かさない)、**週次総合の1枚だけ**を
Notion にテキストで転記する閲覧用の窓です。config で有効化:

```
SECOND_BRAIN_NOTION_MIRROR="1"
```

`synthesize.sh` が総合を書き終えた後、Notion MCP 経由で親ページ
「セカンドブレイン週次総合」配下に「週次総合 YYYY-MM-DD」を作成します。
claude-backup の台帳と同じ作法で **MCP に渡すのはテキストのみ**。ミラーが失敗しても
vault 側は無傷で、次週に再試行されます。

### 3. リサーチ機を回す

```bash
~/.claude/second-brain/research.sh "自分のニッチで今週何が動いたか"
```

問いを 3〜5 の小問に割り、**実務者レイヤー(socials)**と**一次情報(web)**を使い分け、
全主張を「請求書(主張+出典+日付)」化し、**懐疑エージェントが攻撃**して生き残りだけを
**期限付き・日付き・出典付き**ページとして raw/research/ に着地させます。使えるツールは
このマシンで有効なもの(WebSearch/WebFetch、有効なら X / Firecrawl / ScrapeCreators /
Perplexity 等の MCP)に依存し、無いものは使いません。

### 4. すべてのプロジェクトに配線する

各プロジェクトの `CLAUDE.md` に `project-CLAUDE.snippet.md` の 3 行を足すだけ:

```markdown
## knowledge
- before starting, read the relevant pages from ~/vault/entities/ and ~/vault/concepts/
- start from INDEX.md and follow links; open only the pages the trail points at (never sweep the folder)
- ground every claim about our business, clients or audience in a vault page, and cite it
```

これで marketing/content/coding/client work の出力が、汎用ペルソナではなく
**あなたの実データ**に接地します。逆向きに、vault 自体が製品にもなります——リサーチ
ページは記事に、concept ページは講座に、client ページは事例に。

## お金を燃やさない読み方(重要)

コンテキストウィンドウは高価な部屋で、入るものは全部トークンで課金されます。

- `CLAUDE.md` は毎回自動で読まれる**常時課金の税**。**200 行以内**に保ち、知識を
  含めず vault を指すだけにする。
- それ以外は**都度課金**: INDEX → リンク辿り → 必要なページだけ開く。**全走査は禁止**。
- 大きな問いは**サブエージェント**に委譲し、別コンテキストで数十ページ読ませ、
  結論だけ 1 段落で受け取る。高価な部屋には決定だけを置く。

だから維持ループは**安いモデル**が既定で、賢いモデルは週次総合とリサーチだけです。

## vault が死ぬ最大要因:同期の競合

**単一の同期系に一本化**してください。iCloud/Dropbox とエージェントの書き込みが
かち合うと conflicted copy とフォルダ崩れが起きます。保存点は **git** に一本化
(`new-vault.sh` が初期化済み、各ループが書き込み後に自動コミット)。

## the card(順番どおりコピー)

1. vault を作る: `raw/ entities/ concepts/ INDEX.md`(`./new-vault.sh`)
2. 4 つのルールを CLAUDE.md に書く(1 レッスン/更新優先/間違いは削除/raw は触らない)
3. 手持ちを raw/ に投入(文字起こし・ブックマーク・メモ・クライアントフォルダ)
4. `/goal` で証拠付き・停止条件付きのバックフィル
5. ループを仕込む(`./install.sh`: 採掘フック・夜間コンパイル・週次 lint・週次総合)
6. 週次リサーチ(`./research.sh`: 割る→懐疑が攻撃→生き残りを日付きページに)
7. 各プロジェクトの CLAUDE.md に knowledge 3 行

## 対応プラットフォーム

macOS(BSD userland / bash 3.2)と Linux(GNU)の両対応。`flock` / `mapfile` /
`date -Is` は不使用。週次/日次スケジュールは macOS では launchd、それ以外は cron を
`install.sh` が自動登録します。

## 前提ツール

- `claude` CLI(ループとリサーチが使用。無い場合はスキップし、素材は失われない)
- `git`(単一同期系。強く推奨)、`jq`(install のフックマージ用)、`cron`/`launchd`
- 任意: リサーチ用の MCP(X / Firecrawl / ScrapeCreators / Perplexity など)

## 設計上の割り切り

- モデルは入れ替わっても **vault は生き残る**。書き込まれたフィードバックが、
  誰が運転しても毎週賢くする。
- 素材(raw)は決して書き換えない。まとめは raw の上でだけ賢くなる。
- `claude` が無い/失敗しても素材は失わない。ループは黙ってスキップする。
- 最小版は 1 時間: フォルダ 1 つ、自分のビジネスについて 10 ファイル、そして
  「まずそれを読め」と告げるだけ。出力が残りを教えてくれます。
