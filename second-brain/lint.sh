#!/usr/bin/env bash
#
# lint.sh — 週次 lint(安いモデル)。矛盾・重複ページ・切れたリンクを狩る。
# グラフを綺麗に保つループ。放置された wiki は腐るから存在する。
#
# 発火: 週次スケジュール(install.sh が登録)。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh disable=SC1091
. "$HERE/lib.sh"

sb_guard
sb_load_config
sb_vault_ready

if ! sb_have_claude; then
  sb_log "[info] claude CLI 不在。lint をスキップ"
  exit 0
fi

sb_lock lint
DATE="$(sb_date)"
REPORT="$VAULT/raw/maintenance/lint-$DATE.md"

TEMPLATE=$(cat <<'EOF'
あなたはセカンドブレインの lint 係です。@@VAULT@@ の vault を点検します。
対象は compiled ページ(entities/ concepts/ syntheses/)と INDEX.md。raw/ は素材なので
点検対象だが書き換えない。

検出する:
1. 矛盾 — 2つのページが両立しない主張をしている
2. 重複 — 同じ具体物/考え方が別ページに分裂している
3. 切れたリンク — [[wikilink]] の先のページが存在しない
4. 孤立ページ — どこからもリンクされていない compiled ページ
5. INDEX 欠落 — INDEX.md に載っていない compiled ページ / 実体のない INDEX 行

安全な自動修正だけ行う(慎重に):
- 明らかな切れたリンクの修正(綴り違い・リネーム跡)
- INDEX.md への欠落行の追記
それ以外(矛盾・重複の統合など人間判断が要るもの)は修正せず、報告に残す。

報告を @@REPORT@@ に Write する:
  ---
  type: maintenance
  date: @@DATE@@
  summary: 週次 lint 結果
  ---
  # 週次 lint @@DATE@@
  ## 自動修正した項目
  ## 要人間判断(矛盾/重複/孤立)
  ## 切れたリンク・INDEX 差分
各項目に対象ページへの [[link]] を添える。触っていいのは compiled ページ・INDEX・
@@REPORT@@ のみ。
EOF
)
PROMPT=$TEMPLATE
PROMPT=${PROMPT//@@VAULT@@/$VAULT}
PROMPT=${PROMPT//@@REPORT@@/$REPORT}
PROMPT=${PROMPT//@@DATE@@/$DATE}

if sb_run_claude "$MODEL_CHEAP" "$PROMPT" \
      --allowedTools "Read" "Write" "Edit" "Glob" "Grep" >>"$LOG_FILE" 2>&1; then
  sb_git_checkpoint "lint: 週次点検 $DATE"
  sb_log "[ok] 週次 lint 完了 → $REPORT"
else
  sb_log "[warn] 週次 lint に失敗"
fi
