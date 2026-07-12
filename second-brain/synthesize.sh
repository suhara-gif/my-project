#!/usr/bin/env bash
#
# synthesize.sh — 週次の総合(賢いモデル)。vault 全体を横断で読み、今週の変化・
# ドリフト・注目に値するものを1枚に書く。プレミアムモデルが席に見合う唯一のパス。
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
  sb_log "[info] claude CLI 不在。総合をスキップ"
  exit 0
fi

sb_lock synthesize
DATE="$(sb_date)"
OUT="$VAULT/syntheses/週次-$DATE.md"

# 直近7日で更新されたページを手掛かりとして渡す(全走査は避ける)。
RECENT="$(find "$VAULT/entities" "$VAULT/concepts" "$VAULT/raw" -type f -name '*.md' \
            -mtime -7 2>/dev/null | sort || true)"
[ -z "$RECENT" ] && RECENT="(直近7日の更新なし。INDEX から俯瞰して判断すること)"

TEMPLATE=$(cat <<'EOF'
あなたはセカンドブレインの総合(synthesis)係です。@@VAULT@@ の vault 全体を
横断的に読み、今週の1枚を書きます。まず INDEX.md を起点に、リンクを辿って
必要なページだけ開くこと(フォルダ全走査はしない)。

手掛かり(直近7日で動いたページ):
@@RECENT@@

書くこと(@@OUT@@ に Write):
  ---
  type: synthesis
  date: @@DATE@@
  summary: 今週の総合
  ---
  # 週次総合 @@DATE@@
  ## 今週変わったこと
  ## ドリフトしているもの(古くなりつつある前提・矛盾の芽)
  ## 注目に値するもの(次に効きそうな一手・掘るべき問い)
  ## 横断で見えたつながり
各洞察には根拠ページへの [[link]] を必ず添える。断定より、リンクで辿れる根拠を優先。
新しい概念に昇格すべきものがあれば concepts/ に1ページ作り、INDEX に1行足してよい。
触っていいのは concepts/ syntheses/ INDEX.md のみ。raw/ は読み取り専用。
EOF
)
PROMPT=$TEMPLATE
PROMPT=${PROMPT//@@VAULT@@/$VAULT}
PROMPT=${PROMPT//@@RECENT@@/$RECENT}
PROMPT=${PROMPT//@@OUT@@/$OUT}
PROMPT=${PROMPT//@@DATE@@/$DATE}

if sb_run_claude "$MODEL_SMART" "$PROMPT" \
      --allowedTools "Read" "Write" "Edit" "Glob" "Grep" >>"$LOG_FILE" 2>&1; then
  sb_git_checkpoint "synthesis: 週次総合 $DATE"
  sb_log "[ok] 週次総合 完了 → $OUT"
else
  sb_log "[warn] 週次総合に失敗"
fi

# ---- 任意: 週次総合を Notion にミラー(スマホ閲覧用の窓) -------------------
# vault 本体はローカルの Markdown のまま(地の真実)。Notion には読み物として
# 週次総合1枚だけをテキストで複製する。claude-backup の台帳と同じく MCP に渡すのは
# テキストのみで、ミラーが失敗しても vault 側には一切影響しない。既定オフ。
NOTION_MIRROR="${SECOND_BRAIN_NOTION_MIRROR:-0}"
NOTION_MCP="${SECOND_BRAIN_NOTION_MCP:-Notion}"
NOTION_PARENT="${SECOND_BRAIN_NOTION_PARENT:-セカンドブレイン週次総合}"

if [ "$NOTION_MIRROR" = "1" ] && [ -f "$OUT" ]; then
  BODY="$(cat "$OUT")"
  MIRROR_TEMPLATE=$(cat <<'EOF'
あなたは転記係です。下記の週次総合を Notion にミラーしてください(内容の改変・要約はしない)。
1. 「@@PARENT@@」という名前のページを検索する。無ければトップレベルに作成する。
2. その配下にサブページ「週次総合 @@DATE@@」を作成する(同名が既にあれば内容を置き換える)。
3. 本文として下記 Markdown をそのまま転記する([[リンク]] 表記はテキストのまま残してよい)。
--- 本文ここから ---
@@BODY@@
--- 本文ここまで ---
EOF
)
  MIRROR_PROMPT=$MIRROR_TEMPLATE
  MIRROR_PROMPT=${MIRROR_PROMPT//@@PARENT@@/$NOTION_PARENT}
  MIRROR_PROMPT=${MIRROR_PROMPT//@@DATE@@/$DATE}
  # BODY は最後に置換する(本文中に @@...@@ 風の文字列があっても誤置換しない)
  MIRROR_PROMPT=${MIRROR_PROMPT//@@BODY@@/$BODY}
  if sb_run_claude "$MODEL_CHEAP" "$MIRROR_PROMPT" \
        --allowedTools "mcp__${NOTION_MCP}" >>"$LOG_FILE" 2>&1; then
    sb_log "[ok] Notion にミラー: $NOTION_PARENT / 週次総合 $DATE"
  else
    sb_log "[warn] Notion ミラーに失敗(vault 側は無傷。次週に再試行)"
  fi
fi
