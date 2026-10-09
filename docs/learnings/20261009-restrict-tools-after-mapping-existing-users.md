# 権限を絞る前に「そのツールを今使っている運用」と「別の書き込み経路」を洗い出す

- 日付: 2026-10-09
- 種別: 設計判断
- 触れたファイル: CLAUDE.md(progress-*.md 規約)、.claude/agents/up-verify-reviewer.md、.claude/commands/up-verify.md、
  (未適用の案) .claude/settings.json の permissions

## 問題
外部記事の「ハーネス」7要素を取り込む際、記事どおり「.env の Read を deny」「外部送信は承認制」を
入れようとした。初案では Slack 送信も止める候補にしていた。

## 文脈
- このリポジトリに `.env` は無く、秘密は環境変数から読む(meta-ads-autopilot/src/meta_autopilot/config.py:50)。
  さらに公式ドキュメント上、Read の deny は Bash の `cat .env` を止めない。記事の例はこの環境では効果がほぼ無い。
- 日次Routine(meta-ads-autopilot/ROUTINE_PROMPT.md:31)が `slack_send_message` で本人DMに送っている。
  Slack を deny すると毎朝の監視が黙って壊れる。
- Meta広告の一時停止は「許された唯一の書き込み」(meta-ads-autopilot/CLAUDE.md:12)。`ads_update_entity` を deny にすると、
  人が承認した緊急停止まで塞がる。一方で自動停止は Graph API 直叩き(pipeline.py:214)なので、MCP の deny では防げない。

## 解法と、その理由
- 送信・費用が動くツールを「使っている運用」と「同じ効果を持つ別経路」の2軸で洗ってから、deny / ask / 対象外に振り分けた。
  - 対象外: Slack 送信(Routine が使う)
  - ask: ads_update_entity / ads_activate_entity(人が承認すれば止められるように)
  - deny: Gmail の送信・返信・転送、キャンペーン作成・ブースト・テスト作成・削除系
- settings.json の変更は auto mode の分類器に自己改変として拒否されたため、案をファイルとして残し、本人の承認待ちにした。

## うまくいかなかったこと
- 記事の設定例をそのまま貼る初案。前提(.env がある、Read の deny で十分)がこの環境では成り立たなかった。
- 引き継ぎメモを「直下に progress.md」「マージ後に消す」とした初案。複数プロジェクトが同居するため並行ブランチで衝突し、
  マージ済みPRにはコミットできないため手順も実行不能だった(独立検品で指摘)。

## 抽出したルール / ヒューリスティック
ツールを deny/ask にする前に、(1) `grep -rn <ツール名>` で既存の Routine・スキル・エージェントの利用箇所を数え、
(2) 同じ効果を MCP 以外(API直叩き・スクリプト)で起こす経路を列挙する。(1) が1件でもあれば deny にしない。
(2) があるなら「deny で守れている」と書かない。

## 関連
- [20260817-promote-only-after-listing-assumptions.md](20260817-promote-only-after-listing-assumptions.md)
