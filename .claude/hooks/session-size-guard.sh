#!/usr/bin/env bash
# セッション肥大化ガード (UserPromptSubmit フック)
#
# 目的:
#   1セッションが長く伸びるほど、毎ターンのコンテキスト再読込と cache_write が
#   積み上がる。閾値を超えたら「区切って新セッションへ」と促す。
#
# 方針:
#   - **ブロックしない。** 警告を出すだけ。作業を止めるのは壊れる側。
#   - **トランスクリプト(JSONL)の中身は解析しない。** 公式ドキュメントに
#     「エントリ形式は内部仕様でバージョン間で変わる。直接パースするスクリプトは
#     壊れる」と明記されているため、行数のみ数える。1行=1エントリなので
#     形式が変わっても壊れない。
#   - 何か取れなければ黙って通す(fail-open)。フックの不調で作業が止まらないこと。
#
# 閾値の根拠:
#   **未検証の初期値。** 「何エントリで重いか」は実測していない。まず表示させ、
#   自分の使い方に合わせて下の環境変数で調整すること。
#
# 移植性: macOS(bash 3.2 / BSD)と Linux(GNU)の双方に存在する構成のみ使用。
set -euo pipefail

WARN_AT="${CLAUDE_SESSION_WARN_ENTRIES:-300}"
LOUD_AT="${CLAUDE_SESSION_LOUD_ENTRIES:-600}"

payload="$(cat)"

# transcript_path は全フック共通の入力フィールド
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
[ -n "$transcript" ] || exit 0
[ -f "$transcript" ] || exit 0

entries="$(wc -l < "$transcript" 2>/dev/null | tr -d ' ' || true)"
# 数値でなければ黙って通す
case "$entries" in
  '' | *[!0-9]*) exit 0 ;;
esac

if [ "$entries" -ge "$LOUD_AT" ]; then
  msg="⚠ このセッションは ${entries} エントリです。毎ターンのコンテキスト再読込と cache_write が積み上がっています。区切りがつく作業なら、成果をコミット/保存して新しいセッションへ移すことを強く推奨します。"
elif [ "$entries" -ge "$WARN_AT" ]; then
  msg="このセッションは ${entries} エントリです。区切りがついたら新しいセッションに移すと、1ターンあたりの消費を抑えられます。"
else
  exit 0
fi

# systemMessage はユーザーに表示される(全フック共通の出力フィールド)
jq -n --arg m "$msg" '{systemMessage: $m}'
