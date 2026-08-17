#!/usr/bin/env bash
# セッション肥大化ガード (UserPromptSubmit フック)
#
# 目的:
#   セッションが伸びるほど、毎ターン読み直すコンテキストが増える。閾値を超えたら
#   「区切って新セッションへ」と促す。
#
# 指標(2段構え):
#   ① 直近ターンの cache_read_input_tokens — **毎ターン読み直している量そのもの**。
#      transcript の message.usage から取得。これが本命。
#   ② 取れなければエントリ数(行数)へフォールバック。
#
#   ①は transcript の内部形式に依存する。公式ドキュメントは「エントリ形式は内部仕様で
#   バージョン間で変わる。直接パースするスクリプトは壊れる」と明記しているため、
#   **壊れたら黙って②へ落ちる**設計にしてある。②は wc -l だけなので形式変更に強い。
#
# 方針:
#   - **ブロックしない。** 警告のみ。作業を止めるのは壊れる側。
#   - 何も取れなければ黙って通す(fail-open)。フックの不調で作業が止まらないこと。
#
# 閾値:
#   実測の目安 — 本フックを作ったセッションは 420 エントリ / cache_read 約72万トークン
#   だった。既定値はそこから置いた**暫定値**。表示を見て環境変数で調整すること。
#
# 移植性: macOS(bash 3.2 / BSD)と Linux(GNU)の双方に存在する構成のみ使用。
set -euo pipefail

WARN_CTX="${CLAUDE_SESSION_WARN_CTX_TOKENS:-400000}"
LOUD_CTX="${CLAUDE_SESSION_LOUD_CTX_TOKENS:-700000}"
WARN_AT="${CLAUDE_SESSION_WARN_ENTRIES:-300}"
LOUD_AT="${CLAUDE_SESSION_LOUD_ENTRIES:-600}"

payload="$(cat)"

# transcript_path は全フック共通の入力フィールド
transcript="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
[ -n "$transcript" ] || exit 0
[ -f "$transcript" ] || exit 0

is_num() {
  case "${1:-}" in
    '' | *[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

msg=''

# ① 本命: 直近ターンで読み直しているコンテキスト量
ctx="$(grep '"cache_read_input_tokens"' "$transcript" 2>/dev/null \
        | tail -1 \
        | jq -r '.message.usage.cache_read_input_tokens // empty' 2>/dev/null || true)"

if is_num "$ctx" && [ "$ctx" -gt 0 ]; then
  k=$((ctx / 1000))
  if [ "$ctx" -ge "$LOUD_CTX" ]; then
    msg="⚠ このセッションは毎ターン約 ${k}K トークンのコンテキストを読み直しています。区切りがつく作業なら、成果をコミット/保存して新しいセッションへ移すことを強く推奨します。"
  elif [ "$ctx" -ge "$WARN_CTX" ]; then
    msg="このセッションは毎ターン約 ${k}K トークンを読み直しています。区切りがついたら新しいセッションに移すと、1ターンあたりの消費を抑えられます。"
  fi
else
  # ② フォールバック: エントリ数(形式変更に強い)
  entries="$(wc -l < "$transcript" 2>/dev/null | tr -d ' ' || true)"
  if is_num "$entries"; then
    if [ "$entries" -ge "$LOUD_AT" ]; then
      msg="⚠ このセッションは ${entries} エントリです。毎ターンのコンテキスト再読込が積み上がっています。区切りがつく作業なら、成果をコミット/保存して新しいセッションへ移すことを強く推奨します。"
    elif [ "$entries" -ge "$WARN_AT" ]; then
      msg="このセッションは ${entries} エントリです。区切りがついたら新しいセッションに移すと、1ターンあたりの消費を抑えられます。"
    fi
  fi
fi

[ -n "$msg" ] || exit 0

# systemMessage はユーザーに表示される(全フック共通の出力フィールド)
jq -n --arg m "$msg" '{systemMessage: $m}'
