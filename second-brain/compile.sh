#!/usr/bin/env bash
#
# compile.sh — 夜間コンパイル(安いモデル)。前回以降に raw/ へ入った新素材を読み、
# entities/ と concepts/ のページを更新・リンクする。ルーチン作業=ルーチン階層。
#
# 発火: 日次スケジュール(install.sh が登録)。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh disable=SC1091
. "$HERE/lib.sh"

sb_guard
sb_load_config
sb_vault_ready

if ! sb_have_claude; then
  sb_log "[info] claude CLI 不在。コンパイルをスキップ"
  exit 0
fi

sb_lock compile

# 前回コンパイル以降に更新された raw/ ファイルだけを対象にしてコストを抑える。
MARKER="$STATE_DIR/.compile-marker"
if [ -f "$MARKER" ]; then
  CHANGED="$(find "$VAULT/raw" -type f -name '*.md' -newer "$MARKER" 2>/dev/null | sort || true)"
else
  CHANGED="$(find "$VAULT/raw" -type f -name '*.md' 2>/dev/null | sort || true)"
fi

if [ -z "$CHANGED" ]; then
  sb_log "[info] 新しい raw 素材なし。コンパイル不要"
  : >"$MARKER"; touch "$MARKER"
  exit 0
fi
COUNT="$(printf '%s\n' "$CHANGED" | grep -c . || true)"
sb_log "[info] コンパイル対象 raw: ${COUNT}件"

TEMPLATE=$(cat <<'EOF'
あなたはセカンドブレインのコンパイル係です。@@VAULT@@ の vault で作業します。
まず @@VAULT@@/CLAUDE.md と @@VAULT@@/INDEX.md を読み、書き込みルールに従うこと。

やること: 下記の「新しい raw 素材」を読み、そこから得られる具体物・考え方を
entities/ と concepts/ のページへ反映する(素材そのものは書き換えない)。

新しい raw 素材(このファイル群だけを対象にする):
@@CHANGED@@

厳守するルール:
- 1ファイル1レッスン。冒頭に1行サマリ。
- 重複ページを作らず、既存ページを更新する(update, not duplicate)。
- ページ間は [[wikilink]] で必ずつなぐ。
- 各ページには出典として raw/ の該当ファイルへのリンクを必ず残す。
- 新規ページを作ったら INDEX.md に1行(パス + 1行説明)を追記する。
- 変更は憶測でなく素材に根拠を置く。素材に無いことは書かない。
- 触っていいのは entities/ concepts/ INDEX.md のみ。raw/ は読み取り専用。

最後に、更新/新規/リンクしたページを箇条書きで1回だけ報告する。
EOF
)
CHANGED_LIST="$(printf '%s\n' "$CHANGED")"
PROMPT=$TEMPLATE
PROMPT=${PROMPT//@@VAULT@@/$VAULT}
PROMPT=${PROMPT//@@CHANGED@@/$CHANGED_LIST}

if sb_run_claude "$MODEL_CHEAP" "$PROMPT" \
      --allowedTools "Read" "Write" "Edit" "Glob" "Grep" >>"$LOG_FILE" 2>&1; then
  touch "$MARKER"
  sb_git_checkpoint "compile: raw ${COUNT}件を wiki に反映"
  sb_log "[ok] 夜間コンパイル完了 (${COUNT}件)"
else
  sb_log "[warn] 夜間コンパイルに失敗(マーカーは更新せず、次回再試行)"
fi
