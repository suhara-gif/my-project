#!/usr/bin/env bash
#
# research.sh — リサーチ機。1つの問いを 3〜5 の小問に割り、並行に調べ、
# 全主張を「請求書(claim + 出典 + 日付)」化し、懐疑エージェントが攻撃して
# 生き残りだけを、期限付きの日付きページとして vault/raw/research/ に着地させる。
#
# 使い方:
#   ./research.sh "調べたい問い"
#
# 使うツールはこのマシンで有効なものに依存する(WebSearch/WebFetch と、有効なら
# 各種 MCP: X, Firecrawl, ScrapeCreators, Perplexity など)。無いものは黙って使わない。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh disable=SC1091
. "$HERE/lib.sh"

sb_guard
sb_load_config
sb_vault_ready

QUESTION="${1:-}"
if [ -z "$QUESTION" ]; then
  echo "usage: $0 \"調べたい問い\"" >&2
  exit 1
fi
if ! sb_have_claude; then
  sb_log "[error] claude CLI 不在。リサーチには claude が必要"
  exit 1
fi

sb_lock research
DATE="$(sb_date)"; STAMP="$(sb_stamp)"
OUT="$VAULT/raw/research/$STAMP.md"

# 既定の失効までの日数(AIの助言は半年前でもしばしば有害。stale は自己申告させる)。
EXPIRE_DAYS="${SECOND_BRAIN_RESEARCH_EXPIRE_DAYS:-30}"

# リサーチ記憶(任意。python3 が無ければ黙ってスキップ)。同じ・似た問いを
# 過去に調べていないか軽くチェックし、見つかれば参考情報として渡す。
MEMORY_HELPER="$HERE/research_memory.py"
PRIOR=""
if command -v python3 >/dev/null 2>&1 && [ -f "$MEMORY_HELPER" ]; then
  CHECK_RESULT="$(python3 "$MEMORY_HELPER" check "$STATE_DIR" "$QUESTION" 2>/dev/null || true)"
  if [ -n "$CHECK_RESULT" ]; then
    IFS=$'\t' read -r _ PQ_SCORE PQ_DATE PQ_QUESTION PQ_PATH PQ_SUMMARY <<<"$CHECK_RESULT"
    sb_log "[info] 類似の過去リサーチあり(品質${PQ_SCORE} / ${PQ_DATE}): ${PQ_QUESTION}"
    PRIOR="過去の関連リサーチ(参考。鵜呑みにせず今回も独立に再検証すること):
- ${PQ_DATE} 「${PQ_QUESTION}」品質${PQ_SCORE}
  要約: ${PQ_SUMMARY}
  全文: ${PQ_PATH}"
  fi
fi

TEMPLATE=$(cat <<'EOF'
あなたはリサーチ機です。次の問いを、鵜呑みにせず検証して調べます。
問い: 「@@QUESTION@@」
基準日: @@DATE@@
@@PRIOR@@

手順:
1. 問いを 3〜5 個の小問に割る。
2. 小問ごとに、使える手段を使い分けて調べる:
   - 実務者レイヤー(今まさに何が動き、何が壊れ、何が効くか)は socials 寄りの情報源。
     有効な MCP(X, ScrapeCreators/last30days, YouTube 文字起こし等)があれば使う。
   - ドキュメント・価格・一次情報は web(WebSearch / WebFetch、有効なら Firecrawl や
     Perplexity)で。
   - 有効でないツールは使わない(存在しない情報源を捏造しない)。
3. 見つけた事実は全て「請求書」にする: 主張 / 出典URL / 日付。
4. 懐疑ゲート(重要): 各主張を自分で攻撃し、殺そうとする。単一ソースの誇張は
   「単一ソース・要検証」と明示。矛盾は両論併記。生き残った主張だけを採用する。
   ※ 別コンテキストの新鮮な目の方が自己レビューより強い。可能ならサブエージェントに
     検証を委ね、結論だけ受け取る。
5. 検証済みの知見を @@OUT@@ に Write する:
   ---
   type: research
   date: @@DATE@@
   question: "@@QUESTION@@"
   expires: @@DATE@@ + @@EXPIRE_DAYS@@日
   summary: <1行>
   ---
   # リサーチ: @@QUESTION@@
   ## 検証済みの知見(生き残り)
     - 各行に [主張] — 出典URL(日付)を付す
   ## 単一ソース・要検証
   ## 矛盾・未解決
   ## 出典一覧(URL + 取得日)
   古くなったら自己申告できるよう expires を必ず入れる。触るのは @@OUT@@ のみ。
EOF
)
PROMPT=$TEMPLATE
PROMPT=${PROMPT//@@QUESTION@@/$QUESTION}
PROMPT=${PROMPT//@@DATE@@/$DATE}
PROMPT=${PROMPT//@@OUT@@/$OUT}
PROMPT=${PROMPT//@@EXPIRE_DAYS@@/$EXPIRE_DAYS}
PROMPT=${PROMPT//@@PRIOR@@/$PRIOR}

sb_log "[info] リサーチ開始: $QUESTION"

# allowedTools を組み立てる。許可形式は「mcp__<サーバー名>」単位なので(裸の
# mcp__ はワイルドカードにならない)、設定済み MCP サーバーを列挙して個別に許可する。
# SECOND_BRAIN_RESEARCH_MCP(空白区切りのサーバー名)があればそれを優先、
# 無ければ `claude mcp list` から自動検出する。
ALLOWED="Read Write Glob Grep WebSearch WebFetch Task"
MCP_SERVERS="${SECOND_BRAIN_RESEARCH_MCP:-}"
if [ -z "$MCP_SERVERS" ]; then
  # sb_have_claude(冒頭で実行済み)が CLAUDE_BIN を解決している
  MCP_SERVERS="$("$CLAUDE_BIN" mcp list 2>/dev/null \
    | sed -n 's/^\([A-Za-z0-9_-][A-Za-z0-9_-]*\):.*/\1/p' | sort -u | tr '\n' ' ')"
fi
for _srv in $MCP_SERVERS; do
  ALLOWED="$ALLOWED mcp__$_srv"
done
[ -n "$MCP_SERVERS" ] && sb_log "[info] MCP を許可: $MCP_SERVERS"

# shellcheck disable=SC2086  # ALLOWED は意図的に単語分割する(ツール名は空白を含まない)
if sb_run_claude "$MODEL_SMART" "$PROMPT" \
      --allowedTools $ALLOWED \
      >>"$LOG_FILE" 2>&1; then
  if [ -f "$OUT" ]; then
    sb_git_checkpoint "research: $QUESTION"
    sb_log "[ok] リサーチ着地 → $OUT"
    if command -v python3 >/dev/null 2>&1 && [ -f "$MEMORY_HELPER" ]; then
      python3 "$MEMORY_HELPER" record "$STATE_DIR" "$QUESTION" "$OUT" 2>/dev/null || true
    fi
    echo "$OUT"
  else
    sb_log "[warn] リサーチは走ったがページ未作成"
  fi
else
  sb_log "[warn] リサーチに失敗"
fi
