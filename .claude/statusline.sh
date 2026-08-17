#!/usr/bin/env bash
# コンテキスト使用率を常時表示する statusline (任意・未接続)
#
# なぜこれが要るか:
#   セッションが膨らむ根本原因は「膨らんでいることが見えない」こと。
#   フックは閾値を超えたときしか鳴らないが、これは常に見える。
#
# 有効化(自分で選ぶこと。既存の statusline があれば上書きになる):
#   ~/.claude/settings.json に
#     { "statusLine": { "type": "command",
#                       "command": "<このファイルの絶対パス>" } }
#
#   リポジトリ側 .claude/settings.json に置くと、そのリポジトリを開いた
#   全セッションで個人設定を上書きしてしまうため、既定では接続していない。
#
# 使用フィールドは公式ドキュメントで確認済みのもののみ:
#   context_window.used_percentage / .context_window_size / .total_input_tokens
#
# 移植性: macOS(bash 3.2 / BSD)と Linux(GNU)の双方で動く構成のみ使用。
set -euo pipefail

payload="$(cat)"
pct="$(printf '%s' "$payload" | jq -r '.context_window.used_percentage // empty' 2>/dev/null || true)"

case "$pct" in
  '' | *[!0-9]*) exit 0 ;;
esac

# 10% 刻みのバー(bash 3.2 で動く形。seq や {1..n} の環境差を避ける)
filled=$((pct / 10))
bar=''
i=0
while [ "$i" -lt 10 ]; do
  if [ "$i" -lt "$filled" ]; then
    bar="${bar}#"
  else
    bar="${bar}."
  fi
  i=$((i + 1))
done

if [ "$pct" -ge 70 ]; then
  label='ctx!'
else
  label='ctx'
fi

printf '%s [%s] %s%%\n' "$label" "$bar" "$pct"
