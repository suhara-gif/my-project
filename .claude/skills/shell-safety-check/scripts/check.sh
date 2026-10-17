#!/usr/bin/env bash
#
# check.sh — claude-backup のシェル不変条件を機械的に検証するゲート。
#
# CLAUDE.md の「壊しやすい間違い」と「品質バー」を、目視ではなく実行可能な
# チェックに落としたもの。SKILL.md（shell-safety-check）から呼ばれる。
# claude-backup/*.sh を変更したらコミット前に走らせ、出力を読む。
#
# 使い方:
#   .claude/skills/shell-safety-check/scripts/check.sh          # 静的チェック一式
#   .claude/skills/shell-safety-check/scripts/check.sh --dry-run # + 破壊しないダミー実走(9)
#
# 移植性: macOS(bash 3.2 / BSD)と Linux(GNU)の両方で動く形のみ使用。
#
# 注: このスクリプトは複数チェックを最後まで走らせて結果を集計するゲートなので、
#     途中失敗で止まる `set -e` は意図的に使わない(代わりに fail カウンタで集計)。
set -uo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# ---- リポジトリルートへ移動(BSD/GNU 両対応。realpath/readlink -f は不使用) ----
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$ROOT" ]; then
  # git 外で呼ばれた場合: このスクリプトから 4 階層上がリポジトリルート
  ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
fi
cd "$ROOT"

TARGET="claude-backup"
RB="$TARGET/run-backup.sh"

fail=0
warn=0
pass() { printf '  [ok]   %s\n' "$1"; }
bad()  { printf '  [FAIL] %s\n' "$1"; fail=$((fail + 1)); }
note() { printf '  [warn] %s\n' "$1"; warn=$((warn + 1)); }
hdr()  { printf '\n== %s\n' "$1"; }

if [ ! -d "$TARGET" ]; then
  echo "[error] $TARGET が見つからない(リポジトリルート: $ROOT)"
  exit 2
fi

# ---- 1. 構文チェック -------------------------------------------------------
hdr "1. 構文(bash -n)"
for f in "$TARGET"/*.sh; do
  if bash -n "$f" 2>/dev/null; then pass "$f"; else bad "構文エラー: $f"; fi
done

# ---- 2. shellcheck 警告ゼロ ------------------------------------------------
hdr "2. shellcheck 警告ゼロ"
if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck "$TARGET"/*.sh; then
    pass "shellcheck 警告なし"
  else
    bad "shellcheck 警告あり(上記)。新規 disable には理由コメントを併記すること"
  fi
else
  note "shellcheck 未インストールのためスキップ(CI では必須)。brew install shellcheck / apt-get install shellcheck"
fi

# ---- 3. GNU/bash4 依存の混入(コメント行は除外) --------------------------
hdr "3. GNU/bash4 依存の非混入"
gnuism="$(grep -nE '(mapfile|readarray|flock|realpath|readlink -f|declare -A|grep -P|sed -i[^ ]|date -d |date -Is)' "$TARGET"/*.sh \
  | grep -vE ':[0-9]+:[[:space:]]*#' || true)"
if [ -z "$gnuism" ]; then
  pass "GNU 専用機能はコード中に無し(BSD/GNU 両対応)"
else
  bad "GNU/bash4 専用機能がコードに混入(下記)。BSD/GNU 両対応の代替へ:"
  printf '%s\n' "$gnuism" | sed 's/^/         /'
fi

# ---- 4. データ保全の不変条件 ----------------------------------------------
hdr "4. データ保全(失敗経路でもローカル保持)"
if grep -qE 'UPLOAD_OK' "$RB" && grep -qE 'STATE_DIR' "$RB"; then
  # 転送失敗時に STATE_DIR へ cp する分岐が生きているか
  if grep -qE 'UPLOAD_OK.*-eq 0|UPLOAD_OK" -eq 0' "$RB" && grep -qE 'cp "\$UPLOAD" "\$STATE_DIR' "$RB"; then
    pass "UPLOAD_OK=0 分岐で STATE_DIR へ退避している"
  else
    note "UPLOAD_OK/STATE_DIR はあるが失敗時の cp 退避が読み取れない。目視確認すること"
  fi
else
  bad "UPLOAD_OK / STATE_DIR が見つからない。失敗経路でデータを失う恐れ"
fi

# ---- 5. 秘密の除外を弱めていない ------------------------------------------
hdr "5. 秘密の除外(.claude.json / *token* / *credential* / *.key)"
missing=""
for pat in '\.claude\.json' 'token' 'credential' '\.key'; do
  grep -qE "exclude=.*$pat" "$RB" || missing="$missing $pat"
done
if [ -z "$missing" ]; then
  pass "4 つの除外パターンが揃っている"
else
  bad "除外パターンが欠落:$missing  — 弱める変更は差し戻す(必要なら人間に確認)"
fi

# ---- 6. MCP 権限を広げていない / バイナリを LLM に渡していない -------------
hdr "6. claude -p の権限とバイナリ転送手段"
allow="$(grep -nE 'allowedTools' "$RB" || true)"
if [ -z "$allow" ]; then
  bad "--allowedTools が見つからない"
elif printf '%s\n' "$allow" | grep -qE '\-\-allowedTools "mcp__\$\{NOTION_MCP\}"'; then
  pass "--allowedTools は mcp__\${NOTION_MCP} の範囲に限定"
else
  bad "--allowedTools が想定の mcp__\${NOTION_MCP} を超えている疑い(下記)。広げる変更は人間に確認:"
  printf '%s\n' "$allow" | sed 's/^/         /'
fi
if grep -qE '(cp "\$UPLOAD"|rclone (copy|link))' "$RB"; then
  pass "実ファイル転送は cp / rclone に限定(MCP へバイナリを渡していない)"
else
  note "実ファイル転送の手段(cp/rclone)が読み取れない。目視確認すること"
fi

# ---- 7. SessionEnd 再帰ガード ---------------------------------------------
hdr "7. 再帰ガード(CLAUDE_BACKUP_RUNNING)"
guard_top="$(grep -nE 'if \[ -n "\$\{CLAUDE_BACKUP_RUNNING:-\}" \]' "$RB" || true)"
guard_child="$(grep -nE 'CLAUDE_BACKUP_RUNNING=1 .*"\$CLAUDE_BIN"|CLAUDE_BACKUP_RUNNING=1' "$RB" || true)"
if [ -n "$guard_top" ] && printf '%s\n' "$guard_child" | grep -q 'CLAUDE_BIN'; then
  pass "冒頭の早期 exit と、子起動時の CLAUDE_BACKUP_RUNNING=1 の両方がある"
else
  bad "再帰ガードが不完全。冒頭の早期 exit と子への CLAUDE_BACKUP_RUNNING=1 の両方が必須"
fi

# ---- 8. プロンプト・インジェクション対策 -----------------------------------
hdr "8. claude -p プロンプトは静的テンプレ + \${//} 置換"
if grep -qE 'TEMPLATE=\$\(cat <<' "$RB" && grep -qE 'PROMPT=\$\{PROMPT//@@' "$RB"; then
  pass "クォート付き heredoc テンプレ + @@PLACEHOLDER@@ の \${//} 置換で組んでいる"
else
  bad "プロンプトが静的テンプレ + \${//} 置換になっていない。素の変数展開での連結は注入/set -u クラッシュの恐れ"
fi

# ---- 9. 任意: 破壊しないダミー実走 ----------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  hdr "9. ダミー実走(--dry-run)"
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/.claude"
  echo hi >"$tmp/.claude/x"
  if CLAUDE_BACKUP_SRC="$tmp/.claude" CLAUDE_BACKUP_STATE="$tmp/state" \
       CLAUDE_BACKUP_MIN_INTERVAL=0 bash "$RB" >/dev/null 2>&1; then
    :
  fi
  if [ -f "$tmp/state/backup.log" ]; then
    tail_log="$(tail -n 8 "$tmp/state/backup.log")"
    printf '%s\n' "$tail_log" | sed 's/^/         /'
    # 転送先未設定でも [done] まで到達し、ローカルにアーカイブが残っていること
    if printf '%s\n' "$tail_log" | grep -qE '\[done\]' \
       && ls "$tmp/state"/claude-backup-*.tar.gz >/dev/null 2>&1; then
      pass "実走完了。失敗経路でもローカルにアーカイブが残った"
    else
      bad "実走でアーカイブのローカル保全が確認できない"
    fi
  else
    bad "実走のログが生成されなかった"
  fi
  rm -rf "$tmp"
fi

# ---- 集計 -----------------------------------------------------------------
hdr "結果"
printf '  FAIL=%d  WARN=%d\n' "$fail" "$warn"
if [ "$fail" -gt 0 ]; then
  echo "  => 不変条件を満たしていない。コミット前に上記 [FAIL] を解消すること。"
  echo "     判断に迷う場合は CLAUDE.md のエスカレーション規則に従い人間に確認。"
  exit 1
fi
if [ "$warn" -gt 0 ]; then
  echo "  => ハード不変条件は満たすが警告あり(上記 [warn] を確認)。"
fi
echo "  => OK"
exit 0
