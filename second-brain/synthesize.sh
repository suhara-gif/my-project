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
