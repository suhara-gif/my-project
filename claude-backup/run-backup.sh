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
# macOS(BSD userland / bash 3.2)と Linux(GNU)の両対応。flock/mapfile/date -Is は不使用。
set -euo pipefail

# ---- 再帰ガード ------------------------------------------------------------
# ②で起動する claude -p の SessionEnd フックがまた run-backup.sh を呼ぶ無限ループを防ぐ。
if [ -n "${CLAUDE_BACKUP_RUNNING:-}" ]; then
  exit 0
fi

# ---- 設定ファイル読み込み -------------------------------------------------
# SessionEnd フックも launchd/cron も、シェルの ~/.zshrc 等を読まない。両方で
# 環境変数を効かせるため、設定ファイル(KEY=VALUE 形式)があればここで読み込む。
CONFIG_FILE="${CLAUDE_BACKUP_CONFIG:-$HOME/.claude/backup/config}"
# shellcheck disable=SC1090  # ユーザー設定ファイルのパスは可変
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

# ---- 設定(環境変数で上書き可) -------------------------------------------
SRC_DIR="${CLAUDE_BACKUP_SRC:-$HOME/.claude}"
STATE_DIR="${CLAUDE_BACKUP_STATE:-$HOME/.claude/backup}"
RETAIN_LOCAL="${CLAUDE_BACKUP_RETAIN_LOCAL:-5}"     # ローカルに残すアーカイブ世代数
DEST_FOLDER="${CLAUDE_BACKUP_DEST_FOLDER:-ClaudeBackups}"
# マシン識別。複数PCが同じ Drive/Notion を共有しても混ざらないよう、保存先サブ
# フォルダと台帳エントリを分ける。config で CLAUDE_BACKUP_MACHINE="母艦" 等に上書き可。
MACHINE="${CLAUDE_BACKUP_MACHINE:-$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)}"
# Notion MCP サーバー名(`claude mcp list` の表示名に合わせる)。台帳記録に使用。
NOTION_MCP="${CLAUDE_BACKUP_NOTION_MCP:-Notion}"
NOTION_LEDGER="${CLAUDE_BACKUP_NOTION_LEDGER:-Claudeバックアップ台帳}"
# 作成済み台帳DBのURL(空なら名前で検索/無ければ新規作成)
NOTION_LEDGER_URL="${CLAUDE_BACKUP_NOTION_LEDGER_URL:-https://app.notion.com/p/3a76063ad84541f5b0323508e3b2ee05}"
ENCRYPT_RECIPIENT="${CLAUDE_BACKUP_AGE_RECIPIENT:-}" # 設定すると age で暗号化
MIN_INTERVAL_SEC="${CLAUDE_BACKUP_MIN_INTERVAL:-1800}" # 直近実行からこの秒数未満ならスキップ
LOG_FILE="${CLAUDE_BACKUP_LOG:-$STATE_DIR/backup.log}"

# ---- 準備 -----------------------------------------------------------------
mkdir -p "$STATE_DIR"

# 移植性のあるタイムスタンプ(BSD/GNU 両対応)
ts() { date +"%Y-%m-%dT%H:%M:%S%z"; }
log() { echo "$(ts) $*" | tee -a "$LOG_FILE" >&2; }

# ロックは mkdir のアトミック性で実現(flock 非依存)。古いロックは引き継ぐ。
LOCK_DIR="$STATE_DIR/.lock"
cleanup() { rm -rf "$LOCK_DIR" "${WORK:-}"; }
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  if [ -f "$LOCK_DIR/pid" ] && kill -0 "$(cat "$LOCK_DIR/pid" 2>/dev/null)" 2>/dev/null; then
    log "[skip] 別のバックアップが実行中"
    exit 0
  fi
  log "[info] 古いロックを回収"
  rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR"
fi
echo "$$" >"$LOCK_DIR/pid"
trap cleanup EXIT
WORK=""

# 直近実行からの最小間隔チェック(SessionEnd が連発しても無駄打ちしない)
LAST_FILE="$STATE_DIR/.last_run"
if [ -f "$LAST_FILE" ]; then
  last=$(cat "$LAST_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$((now - last))" -lt "$MIN_INTERVAL_SEC" ]; then
    log "[skip] 直近 ${MIN_INTERVAL_SEC}s 以内に実行済み"
    exit 0
  fi
fi

if [ ! -d "$SRC_DIR" ]; then
  log "[error] バックアップ元が見つからない: $SRC_DIR"
  exit 0
fi

# ---- ① アーカイブ作成(秘密情報を除外) ----------------------------------
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
ARCHIVE="$WORK/claude-backup-$STAMP.tar.gz"

# 除外: トークン/認証情報、再生成可能で巨大な領域(プラグイン・キャッシュ・
# シェルスナップショット・テレメトリ)、ロック・ログ。BSD/GNU 両対応の単純パターン。
# CLAUDE_BACKUP_EXTRA_EXCLUDES に空白区切りで追加除外パターンを渡せる。
EXTRA_EXCLUDES="${CLAUDE_BACKUP_EXTRA_EXCLUDES:-}"
# shellcheck disable=SC2086  # EXTRA_EXCLUDES は意図的に単語分割する
tar czf "$ARCHIVE" \
  --exclude='.claude.json' \
  --exclude='*token*' \
  --exclude='*credential*' \
  --exclude='*.key' \
  --exclude='*/backup/.lock' \
  --exclude='*/backup/backup.log' \
  --exclude='*/cache/*' \
  --exclude='*/node_modules/*' \
  --exclude='*/plugins/*' \
  --exclude='*/statsig/*' \
  --exclude='*/shell-snapshots/*' \
  $EXTRA_EXCLUDES \
  -C "$(dirname "$SRC_DIR")" "$(basename "$SRC_DIR")"

# ---- 任意: age で暗号化 ---------------------------------------------------
UPLOAD="$ARCHIVE"
if [ -n "$ENCRYPT_RECIPIENT" ] && command -v age >/dev/null 2>&1; then
  age -r "$ENCRYPT_RECIPIENT" -o "$ARCHIVE.age" "$ARCHIVE"
  UPLOAD="$ARCHIVE.age"
  log "[info] age で暗号化: $(basename "$UPLOAD")"
fi

SIZE="$(du -h "$UPLOAD" | cut -f1 | tr -d '[:space:]')"
log "[info] アーカイブ作成: $(basename "$UPLOAD") ($SIZE)"

# ---- ② バイナリアップロード(決定的・LLM非依存) --------------------------
# 実ファイル転送は専用手段で行う。MCP/LLM はバイナリ非対応のため使わない。
#   優先1) CLAUDE_BACKUP_LOCAL_SYNC_DIR → そこへ cp(Google Drive/Box の
#          デスクトップ同期フォルダを指せば自動でクラウド同期。追加ツール不要)
#   優先2) rclone + CLAUDE_BACKUP_RCLONE_REMOTE → rclone copy でリモートへ転送
#   どちらも無ければローカル保持のみ(データは失わない)+ 設定を促す警告
LOCAL_SYNC_DIR="${CLAUDE_BACKUP_LOCAL_SYNC_DIR:-}"
RCLONE_REMOTE="${CLAUDE_BACKUP_RCLONE_REMOTE:-}"
BASENAME="$(basename "$UPLOAD")"
# マシンごとにサブフォルダを分ける(複数PCが同じ Drive を共有しても混ざらない)
DEST_PATH="$DEST_FOLDER/$MACHINE"
UPLOAD_LINK=""
UPLOAD_OK=0

if [ -n "$LOCAL_SYNC_DIR" ]; then
  if mkdir -p "$LOCAL_SYNC_DIR/$DEST_PATH" && cp "$UPLOAD" "$LOCAL_SYNC_DIR/$DEST_PATH/"; then
    UPLOAD_OK=1
    UPLOAD_LINK="$LOCAL_SYNC_DIR/$DEST_PATH/$BASENAME"
    log "[ok] 同期フォルダへ配置(自動クラウド同期): $UPLOAD_LINK"
  else
    log "[warn] 同期フォルダへのコピー失敗: $LOCAL_SYNC_DIR"
  fi
elif [ -n "$RCLONE_REMOTE" ] && command -v rclone >/dev/null 2>&1; then
  if rclone copy "$UPLOAD" "${RCLONE_REMOTE}:${DEST_PATH}/" >>"$LOG_FILE" 2>&1; then
    UPLOAD_OK=1
    UPLOAD_LINK="$(rclone link "${RCLONE_REMOTE}:${DEST_PATH}/${BASENAME}" 2>/dev/null || true)"
    [ -z "$UPLOAD_LINK" ] && UPLOAD_LINK="${RCLONE_REMOTE}:${DEST_PATH}/${BASENAME}"
    log "[ok] rclone でアップロード: $UPLOAD_LINK"
  else
    log "[warn] rclone アップロード失敗 (remote=$RCLONE_REMOTE)"
  fi
else
  log "[warn] クラウド転送手段が未設定。CLAUDE_BACKUP_LOCAL_SYNC_DIR か rclone を設定してください"
fi

# クラウド転送できなければローカル世代へ必ず退避(データ保全)
if [ "$UPLOAD_OK" -eq 0 ]; then
  cp "$UPLOAD" "$STATE_DIR/"
  UPLOAD_LINK="(ローカルのみ) $STATE_DIR/$BASENAME"
fi

# 転送成功時、フォルダ直下に「復元手順.txt」を最新化(データの隣に手順書を置く)
if [ "$UPLOAD_OK" -eq 1 ]; then
  README_TMP="$WORK/復元手順.txt"
  cat >"$README_TMP" <<'RM'
【Claude バックアップ】このフォルダについて

各PCの ~/.claude/(設定・スキル・コマンド・スケジュール定義など)の自動バックアップが、
マシン別サブフォルダに入っています。例) 母艦/  会社/  … 各 claude-backup-YYYYMMDD-HHMMSS.tar.gz

■ PCがクラッシュした時の復元手順
 1) 復元したいマシンのサブフォルダを開き、一番新しい claude-backup-*.tar.gz をダウンロード
 2) 新しいMacで復元スクリプトを取得して実行:
      git clone https://github.com/suhara-gif/my-project
      ~/my-project/claude-backup/restore.sh ~/Downloads/claude-backup-YYYYMMDD-HHMMSS.tar.gz
 3) 復元後に  claude login  で再認証(認証トークンはバックアップに含めていません)

■ スクリプト無しの手動復元
      mkdir -p ~/.claude
      tar xzf ~/Downloads/claude-backup-YYYYMMDD-HHMMSS.tar.gz -C ~/
      claude login

■ 詳しい台帳・手順(クラウド/スマホ可)
   Notion「Claude運用」: https://app.notion.com/p/37764afca07581e1bbe5c4d94b768a8d
   GitHub: https://github.com/suhara-gif/my-project (claude-backup/README.md)

※ 拡張子が .age のものは暗号化版:  age -d -i <鍵> file.age | tar xz -C ~/
RM
  if [ -n "$LOCAL_SYNC_DIR" ]; then
    cp "$README_TMP" "$LOCAL_SYNC_DIR/$DEST_FOLDER/" 2>/dev/null || true
  elif [ -n "$RCLONE_REMOTE" ]; then
    rclone copy "$README_TMP" "${RCLONE_REMOTE}:${DEST_FOLDER}/" >>"$LOG_FILE" 2>&1 || true
  fi
fi

# ---- ③ Notion 台帳へ記録(テキストのみ。MCP が得意な領域) -----------------
PREV_MANIFEST="$STATE_DIR/last-manifest.txt"
CUR_MANIFEST="$WORK/manifest.txt"
tar tzf "$ARCHIVE" | sort >"$CUR_MANIFEST"
DIFF="$(diff "$PREV_MANIFEST" "$CUR_MANIFEST" 2>/dev/null || true)"
STATUS_TEXT="成功"
[ "$UPLOAD_OK" -eq 0 ] && STATUS_TEXT="失敗(クラウド未転送・ローカル保持のみ)"

# claude CLI の解決。launchd/cron はログインシェルの PATH を引き継がないため、
# `command -v` だけではスケジュール実行時に見つからず台帳記録がスキップされる。
# 優先: config の CLAUDE_BACKUP_CLAUDE_BIN → PATH → 一般的な設置場所。
CLAUDE_BIN="${CLAUDE_BACKUP_CLAUDE_BIN:-}"
if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
  if command -v claude >/dev/null 2>&1; then
    CLAUDE_BIN="$(command -v claude)"
  else
    CLAUDE_BIN=""
    for _d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin" "$HOME/.npm-global/bin"; do
      if [ -x "$_d/claude" ]; then
        CLAUDE_BIN="$_d/claude"
        break
      fi
    done
  fi
fi

if [ -n "$CLAUDE_BIN" ]; then
  DIFF_TEXT="${DIFF:-（差分なし／初回）}"
  # 静的テンプレ(クォート付き heredoc = 一切展開しない)+ ${//} 安全置換。
  # 置換値は再展開されないため $ や $(...) を含んでも set -u クラッシュ/注入なし。
  TEMPLATE=$(cat <<'EOF'
あなたはバックアップ台帳の記録係です。ファイルのアップロードは済んでいるので
記録のみ行ってください(アップロードはしない)。
1. Notion の台帳データベース(@@LEDGER_URL@@ があればそれを、無ければ
   名前「@@LEDGER@@」で検索)を開く。見つからなければ作成する
   (プロパティ: エントリ=title, 日時=date, マシン=rich_text, 種別=select[フルバックアップ/
    設定変更/スケジュール変更], 変更サマリ=rich_text, 変更ファイル=rich_text,
    アーカイブリンク=url, サイズ=rich_text, 状態=select[成功/失敗])。
   「マシン」プロパティが無ければ rich_text で追加してから進める。
2. 下記の差分を読み、人間が読める変更サマリと種別を判定する。
   --- 前回からのファイル差分 ---
   @@DIFF@@
   --- ここまで ---
3. 台帳に1行追加する: エントリ=「@@MACHINE@@ @@STAMP@@」、日時=今、マシン=@@MACHINE@@、
   種別=判定結果、変更サマリ=要約、変更ファイル=差分の対象、
   アーカイブリンク=「@@LINK@@」、サイズ=@@SIZE@@、状態=@@STATUS@@。簡潔に。
EOF
)
  PROMPT=$TEMPLATE
  PROMPT=${PROMPT//@@LEDGER_URL@@/$NOTION_LEDGER_URL}
  PROMPT=${PROMPT//@@LEDGER@@/$NOTION_LEDGER}
  PROMPT=${PROMPT//@@MACHINE@@/$MACHINE}
  PROMPT=${PROMPT//@@STAMP@@/$STAMP}
  PROMPT=${PROMPT//@@SIZE@@/$SIZE}
  PROMPT=${PROMPT//@@LINK@@/$UPLOAD_LINK}
  PROMPT=${PROMPT//@@STATUS@@/$STATUS_TEXT}
  PROMPT=${PROMPT//@@DIFF@@/$DIFF_TEXT}
  # CLAUDE_BACKUP_RUNNING=1 を子に渡し、子セッションの SessionEnd で再帰しないようにする
  if PATH="$(dirname "$CLAUDE_BIN"):$PATH" CLAUDE_BACKUP_RUNNING=1 "$CLAUDE_BIN" -p "$PROMPT" \
        --allowedTools "mcp__${NOTION_MCP}" \
        >>"$LOG_FILE" 2>&1; then
    log "[ok] Notion 台帳に記録 ($STATUS_TEXT)"
  else
    log "[warn] Notion 台帳への記録に失敗。アーカイブは保全済み: $UPLOAD_LINK"
  fi
else
  log "[info] claude CLI 不在。台帳記録はスキップ(アーカイブは保全済み: $UPLOAD_LINK)"
fi

# ---- 後始末: マニフェスト更新・ローカル世代数の制限・実行時刻記録 --------
cp "$CUR_MANIFEST" "$PREV_MANIFEST"
date +%s >"$LAST_FILE"

# STATE_DIR に退避したローカルアーカイブを RETAIN_LOCAL 世代まで(mapfile 不使用)
# shellcheck disable=SC2012  # ファイル名は制御されたタイムスタンプで、mtime順(-t)が必要
ls -1t "$STATE_DIR"/claude-backup-*.tar.gz* 2>/dev/null | tail -n +"$((RETAIN_LOCAL + 1))" | while IFS= read -r f; do
  [ -n "$f" ] && rm -f "$f" && log "[info] 古いローカル世代を削除: $(basename "$f")"
done

log "[done] バックアップ完了 ($STAMP)"
