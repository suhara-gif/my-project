# CLAUDE.md を割るときは、規則の適用範囲とファイルの読み込み契機を一致させる

- 日付: 2026-08-10
- 種別: 設計判断
- 触れたファイル: CLAUDE.md、.claude/rules/shell-kits.md、.github/workflows/shellcheck.yml

## 問題

CLAUDE.md が 196 行に達し(上限200行)、分割が必要になった。当初案は「シェル関連の規則を
`claude-backup/CLAUDE.md` に移す」というディレクトリ階層での分割だった。

この案には欠陥があった。**移す規則は `second-brain/*.sh` にも適用される**のに、
`claude-backup/CLAUDE.md` はそのディレクトリのファイルを読んだときにしか読み込まれない。
`second-brain/lib.sh` を編集するモデルには規則が届かない。

## 文脈

なぜ非自明だったか: ディレクトリ名(`claude-backup/`)と規則の名前(「claude-backup の
壊しやすい間違い」)が一致していたため、置き場所が自明に見えた。実際の適用範囲は
ディレクトリ境界と一致していなかった。

証拠は CI にあった。`.github/workflows/shellcheck.yml` は `claude-backup/*.sh` と
`second-brain/*.sh` の**両方**を対象にしている。規則9 も `second-brain/lib.sh` の
`sb_resolve_claude` を基準として参照している。つまり規則は最初から2キットに跨っていた。
(CLAUDE.md 本文は「CI は `claude-backup/*.sh` に対する shellcheck」と書いており、
これ自体が実態と食い違っていた。分割のついでに修正した。)

## 解法と、その理由

`.claude/rules/shell-kits.md` に `paths:` フロントマターで
`claude-backup/**/*.sh` と `second-brain/**/*.sh` の両方を指定した。1ファイルで
2キットを覆えるのは path-scoped ルールだけで、ディレクトリ階層の CLAUDE.md では
どちらか一方にしか置けない。

`@path` インポートは検討して外した。公式ドキュメントに「imports helps organization but
doesn't reduce context, since imported files load at launch」とあり、
**行数は減るが常時課金は減らない**。分割の目的を達成しない。

キットを跨いで効く規則(プロンプトに専門家ペルソナを付けない)はルート CLAUDE.md に残した。
これは `.sh` だけでなく `fable5-agent-system/**/*.py` の `system_prompt_template` と
`.claude/commands/*.md` にも適用されるため、シェル用ルールに入れると適用範囲が縮む。

## うまくいかなかったこと

- 移動後の欠落チェックを `grep -Fqx "$line"` で書いたところ、`- [ ] ...` のような
  ハイフン始まりの行が grep のオプションとして解釈され、18行が偽の「欠落」として報告された。
  `grep -Fqx -- "$line"` で解消。**検証スクリプト自体が壊れていると、検証したつもりになる。**
  結果は 63行中 60行が完全一致、残り3行は意図した書き換えだった。

## 抽出したルール / ヒューリスティック

**規則をファイルに割るときは、ディレクトリ名ではなく「その規則が実際に適用されるファイル集合」で
置き場所を決める。** 適用範囲がディレクトリ境界を跨ぐなら `.claude/rules/` の `paths:` を使う
(ディレクトリごとの CLAUDE.md では片側にしか届かない)。適用範囲を確かめる一次資料は CI 設定
— CI が何を対象にしているかが、その規則が誰に効くべきかを示す。

残る制約: path-scoped ルールと入れ子 CLAUDE.md は `/compact` 後に自動再注入されず、
対象ファイルを次に読んだときに再読込される。常時読ませたい規則をここに置いてはいけない。

## 関連

- [20260810-decision-rules-must-outlive-the-session.md](20260810-decision-rules-must-outlive-the-session.md)
