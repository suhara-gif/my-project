#!/usr/bin/env bash
#
# run-backup.sh — Claude Code / Cowork のローカルデータを自動バックアップする。
#
# 仕組み:
#   ①(このスクリプト = 機械的に確実)
#       ~/.claude/ を tar で固める。秘密情報(OAuthトークン等)は除外し、
#       必要なら age/gpg で暗号化する。
#   ②(claude -p = 知的判定)
#       ヘッドレス Claude が前回からの差分を判定・要約し、
#       実体アーカイブを Google Drive(または Box)へアップロード、
#       「いつ・何が変わった・どこに保存したか」を Notion 台帳に1行記録する。
#
# 想定トリガ: ~/.claude/settings.json の SessionEnd フック、および日次 cron/launchd。
# 冪等・多重起動安全(ロックファイルあり)。失敗してもセッションは止めない。
set -euo pipefail

# ---- 設定(環境変数で上書き可) -------------------------------------------
SRC_DIR="${CLAUDE_BACKUP_SRC:-$HOME/.claude}"
STATE_DIR="${CLAUDE_BACKUP_STATE:-$HOME/.claude/backup}"
RETAIN_LOCAL="${CLAUDE_BACKUP_RETAIN_LOCAL:-5}"     # ローカルに残すアーカイブ世代数
DEST="${CLAUDE_BACKUP_DEST:-googledrive}"           # googledrive | box
DEST_FOLDER="${CLAUDE_BACKUP_DEST_FOLDER:-ClaudeBackups}"
NOTION_LEDGER="${CLAUDE_BACKUP_NOTION_LEDGER:-Claudeバックアップ台帳}"
ENCRYPT_RECIPIENT="${CLAUDE_BACKUP_AGE_RECIPIENT:-}" # 設定すると age で暗号化
MIN_INTERVAL_SEC="${CLAUDE_BACKUP_MIN_INTERVAL:-1800}" # 直近実行からこの秒数未満ならスキップ
LOG_FILE="${CLAUDE_BACKUP_LOG:-$STATE_DIR/backup.log}"

# ---- 準備 -----------------------------------------------------------------
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/.lock"
if ! flock -n 9; then
  echo "$(date -Is) [skip] 別のバックアップが実行中" >>"$LOG_FILE"
  exit 0
fi

log() { echo "$(date -Is) $*" | tee -a "$LOG_FILE" >&2; }

# 直近実行からの最小間隔チェック(SessionEnd が連発しても無駄打ちしない)
LAST_FILE="$STATE_DIR/.last_run"
if [[ -f "$LAST_FILE" ]]; then
  last=$(cat "$LAST_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if (( now - last < MIN_INTERVAL_SEC )); then
    log "[skip] 直近 ${MIN_INTERVAL_SEC}s 以内に実行済み"
    exit 0
  fi
fi

if [[ ! -d "$SRC_DIR" ]]; then
  log "[error] バックアップ元が見つからない: $SRC_DIR"
  exit 0
fi

# ---- ① アーカイブ作成(秘密情報を除外) ----------------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ARCHIVE="$WORK/claude-backup-$STAMP.tar.gz"

# 除外: トークン/認証情報、巨大で再現可能なキャッシュ類、ロック・ログ
tar czf "$ARCHIVE" \
  --exclude='.claude.json' \
  --exclude='*token*' \
  --exclude='*credential*' \
  --exclude='*.key' \
  --exclude='backup/.lock' \
  --exclude='backup/backup.log' \
  --exclude='**/cache/**' \
  --exclude='**/node_modules/**' \
  -C "$(dirname "$SRC_DIR")" "$(basename "$SRC_DIR")"

# ---- 任意: age で暗号化 ---------------------------------------------------
UPLOAD="$ARCHIVE"
if [[ -n "$ENCRYPT_RECIPIENT" ]] && command -v age >/dev/null 2>&1; then
  age -r "$ENCRYPT_RECIPIENT" -o "$ARCHIVE.age" "$ARCHIVE"
  UPLOAD="$ARCHIVE.age"
  log "[info] age で暗号化: $(basename "$UPLOAD")"
fi

SIZE="$(du -h "$UPLOAD" | cut -f1)"
log "[info] アーカイブ作成: $(basename "$UPLOAD") ($SIZE)"

# ---- ② Claude に判定・アップロード・台帳記録を委譲 ------------------------
# claude が無い/失敗してもローカルアーカイブは残るのでデータは失われない。
PREV_MANIFEST="$STATE_DIR/last-manifest.txt"
CUR_MANIFEST="$WORK/manifest.txt"
tar tzf "$ARCHIVE" | sort >"$CUR_MANIFEST"
DIFF="$(diff "$PREV_MANIFEST" "$CUR_MANIFEST" 2>/dev/null || true)"

if command -v claude >/dev/null 2>&1; then
  PROMPT=$(cat <<EOF
あなたはバックアップ実行エージェントです。次を順に実行してください。
1. ローカルファイル「$UPLOAD」を $DEST の「$DEST_FOLDER」フォルダにアップロードする。
   フォルダが無ければ作成する。アップロード後の共有/参照リンクを取得する。
2. Notion の「$NOTION_LEDGER」という名前のデータベースを探す。無ければ作成する
   (プロパティ: 日時=date, 種別=select[フルバックアップ/設定変更/スケジュール変更],
    変更サマリ=rich_text, 変更ファイル=rich_text, アーカイブリンク=url,
    サイズ=rich_text, 状態=select[成功/失敗])。
3. 下記の差分を読み、人間が読める変更サマリと種別を判定する。
   --- 前回からのファイル差分 ---
   ${DIFF:-（差分なし／初回）}
   --- ここまで ---
4. 台帳に1行追加する: 日時=今、種別=判定結果、変更サマリ=要約、
   変更ファイル=差分の対象、アーカイブリンク=手順1のリンク、サイズ=$SIZE、状態=成功。
失敗した場合は状態=失敗で記録し、理由を変更サマリに書く。簡潔に。
EOF
)
  if claude -p "$PROMPT" \
        --allowedTools "mcp__notion,mcp__googledrive,mcp__box,Read" \
        >>"$LOG_FILE" 2>&1; then
    log "[ok] アップロード&台帳記録 完了"
  else
    log "[warn] Claude 経由の退避/記録に失敗。ローカルアーカイブは保持: $UPLOAD"
    cp "$UPLOAD" "$STATE_DIR/"   # 最低限ローカルに退避
  fi
else
  log "[warn] claude CLI 不在。ローカルアーカイブのみ保持"
  cp "$UPLOAD" "$STATE_DIR/"
fi

# ---- 後始末: マニフェスト更新・ローカル世代数の制限・実行時刻記録 --------
cp "$CUR_MANIFEST" "$PREV_MANIFEST"
date +%s >"$LAST_FILE"

# STATE_DIR に退避したローカルアーカイブを RETAIN_LOCAL 世代まで
mapfile -t old < <(ls -1t "$STATE_DIR"/claude-backup-*.tar.gz* 2>/dev/null | tail -n +"$((RETAIN_LOCAL + 1))")
for f in "${old[@]:-}"; do [[ -n "$f" ]] && rm -f "$f" && log "[info] 古いローカル世代を削除: $(basename "$f")"; done

log "[done] バックアップ完了 ($STAMP)"
