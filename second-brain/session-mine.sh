#!/usr/bin/env bash
#
# session-mine.sh — SessionEnd フック。終わったばかりのセッションを採掘し、
# 決定・ミス・確認できたパターンを vault/raw/sessions/ に日付きノートとして残す。
#
# 「やった仕事」がファイリング作業なしに記憶になる。素材(raw)としてまず着地させ、
# 夜間の compile.sh が entities/concepts へ昇格させる(raw=地の真実は書き換えない)。
#
# 発火: ~/.claude/settings.json の SessionEnd フック。標準入力に
#       {"transcript_path": "...", "session_id": "...", "cwd": "..."} 等が来る。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh disable=SC1091
. "$HERE/lib.sh"

sb_guard          # 子セッション(claude -p)からの再帰発火を弾く
sb_load_config

# フック入力(JSON)を受け取り transcript_path を取り出す。jq が無ければ sed。
HOOK_INPUT="$(cat 2>/dev/null || true)"
extract() {
  _key="$1"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$HOOK_INPUT" | jq -r ".$_key // empty" 2>/dev/null
  else
    printf '%s' "$HOOK_INPUT" \
      | sed -n "s/.*\"$_key\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" | head -1
  fi
}
TRANSCRIPT="$(extract transcript_path)"
CWD="$(extract cwd)"

sb_vault_ready

# 連発スキップ(1セッションで複数回発火しても無駄打ちしない)
if sb_too_soon session; then
  sb_log "[skip] 直近 ${MIN_INTERVAL_SEC}s 以内に採掘済み"
  exit 0
fi

if ! sb_have_claude; then
  sb_log "[info] claude CLI 不在。セッション採掘をスキップ"
  exit 0
fi
if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  sb_log "[info] transcript が読めない(path=$TRANSCRIPT)。採掘をスキップ"
  exit 0
fi

sb_lock session
DATE="$(sb_date)"; STAMP="$(sb_stamp)"
OUT="$VAULT/raw/sessions/$STAMP.md"

# 静的テンプレ(クォート付き heredoc = 展開しない)+ ${//} 安全置換。
TEMPLATE=$(cat <<'EOF'
あなたはセッションの採掘係です。下記の会話トランスクリプトを読み、後で役立つ
「記憶」だけを抽出して1枚の Markdown ノートに保存してください。創作はしない。

トランスクリプト(JSONL): @@TRANSCRIPT@@
作業ディレクトリ: @@CWD@@

抽出対象(あれば):
- 下した決定と、その理由
- 捕まえたミス/落とし穴と、正しいやり方
- 確認できたパターン・事実・好み(声/方針/アーキテクチャ)
- 次回に持ち越すべき未解決事項

ルール:
- 出力先ファイルは必ず @@OUT@@ に Write する(他は触らない)。
- 冒頭に YAML フロントマターを付ける:
  ---
  type: session
  date: @@DATE@@
  source: @@TRANSCRIPT@@
  summary: <1行サマリ>
  ---
- 本文は箇条書きで簡潔に。各項目は1行1レッスン。
- 抽出すべきものが無ければ「本セッションに保存価値のある記憶なし」とだけ書く。
- これは raw(素材)であって結論ではない。断定を盛らず、起きたことだけを書く。
EOF
)
PROMPT=$TEMPLATE
PROMPT=${PROMPT//@@TRANSCRIPT@@/$TRANSCRIPT}
PROMPT=${PROMPT//@@CWD@@/$CWD}
PROMPT=${PROMPT//@@OUT@@/$OUT}
PROMPT=${PROMPT//@@DATE@@/$DATE}

if sb_run_claude "$MODEL_CHEAP" "$PROMPT" \
      --allowedTools "Read" "Write" >>"$LOG_FILE" 2>&1; then
  sb_mark session
  if [ -f "$OUT" ]; then
    sb_git_checkpoint "session: $STAMP を採掘"
    sb_log "[ok] セッション採掘 → $OUT"
  else
    sb_log "[info] 保存価値のある記憶なし(ノート未作成)"
  fi
else
  sb_log "[warn] セッション採掘に失敗"
fi
