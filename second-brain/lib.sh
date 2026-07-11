#!/usr/bin/env bash
#
# lib.sh — second-brain キット共通の関数と設定読み込み。
#
# 単体では実行しない。各ループスクリプトから source して使う。
# macOS(BSD userland / bash 3.2)と Linux(GNU)の両対応。
# flock / mapfile / date -Is といった GNU・bash4 専用機能は使わない。
# 注意: bash 3.2 は $( ) の閉じ括弧を単純スキャンで探すため、$(cat <<'EOF' ... ) の
# ヒアドキュメント内にシングルクォート(don't 等)やバッククォートを置くとパースが壊れる。
# プロンプトのテンプレート文にはこれらの文字を使わないこと。

# ---- 再帰ガード ------------------------------------------------------------
# ループが起動する `claude -p` の子セッションが、SessionEnd フック経由で
# 親スクリプトをまた呼ぶ無限ループを防ぐ。子には SECOND_BRAIN_RUNNING=1 を渡す。
sb_guard() {
  if [ -n "${SECOND_BRAIN_RUNNING:-}" ]; then
    exit 0
  fi
}

# ---- 設定読み込み ----------------------------------------------------------
# SessionEnd フックも launchd/cron も、シェルの ~/.zshrc 等を読まない。両方で
# 環境変数を効かせるため、設定ファイル(KEY=VALUE 形式)を明示的に読み込む。
sb_load_config() {
  CONFIG_FILE="${SECOND_BRAIN_CONFIG:-$HOME/.claude/second-brain/config}"
  # shellcheck disable=SC1090  # ユーザー設定ファイルのパスは可変
  [ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

  # vault の場所(Obsidian の保管庫 = ただのフォルダ)
  VAULT="${SECOND_BRAIN_VAULT:-$HOME/vault}"
  # モデル階層。ルーチン(コンパイル/lint)は安いモデル、週次の総合だけ賢いモデル。
  # 正確なモデルIDに縛られないよう CLI のエイリアス(haiku/sonnet/opus)を既定にする。
  # MODEL_CHEAP / MODEL_SMART は source 先スクリプトで参照する(lib 内では未使用)。
  # shellcheck disable=SC2034
  MODEL_CHEAP="${SECOND_BRAIN_MODEL_CHEAP:-haiku}"
  # shellcheck disable=SC2034
  MODEL_SMART="${SECOND_BRAIN_MODEL_SMART:-opus}"
  # キットの作業状態(ロック・ログ・マーカー)の置き場
  STATE_DIR="${SECOND_BRAIN_STATE:-$HOME/.claude/second-brain}"
  # セッション採掘が連発した時にスキップする最小間隔(秒)
  MIN_INTERVAL_SEC="${SECOND_BRAIN_MIN_INTERVAL:-900}"
  # 単一同期系(git チェックポイント)。iCloud等との競合を避けるため 1 を推奨。
  GIT_CHECKPOINT="${SECOND_BRAIN_GIT:-1}"
  LOG_FILE="${SECOND_BRAIN_LOG:-$STATE_DIR/second-brain.log}"

  mkdir -p "$STATE_DIR"
}

# ---- ログ / 日付(BSD・GNU 両対応) --------------------------------------
ts()       { date +"%Y-%m-%dT%H:%M:%S%z"; }
sb_log()   { echo "$(ts) $*" | tee -a "${LOG_FILE:-/dev/stderr}" >&2; }
sb_date()  { date +"%Y-%m-%d"; }
sb_stamp() { date +"%Y%m%d-%H%M%S"; }

# ---- ロック(mkdir のアトミック性。flock 非依存) -------------------------
# 引数: ロック名(ループ種別)。同種の多重起動だけを弾く。
sb_lock() {
  LOCK_DIR="$STATE_DIR/.lock-$1"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    if [ -f "$LOCK_DIR/pid" ] && kill -0 "$(cat "$LOCK_DIR/pid" 2>/dev/null)" 2>/dev/null; then
      sb_log "[skip] 別プロセスが実行中: $1"
      exit 0
    fi
    sb_log "[info] 古いロックを回収: $1"
    rm -rf "$LOCK_DIR"; mkdir "$LOCK_DIR"
  fi
  echo "$$" >"$LOCK_DIR/pid"
  # shellcheck disable=SC2064  # LOCK_DIR は今の値で固定して trap したい
  trap "rm -rf '$LOCK_DIR'" EXIT
}

# ---- 直近実行からの最小間隔チェック(連発を無駄打ちしない) ---------------
# 引数: マーカー名。間隔未満なら 1(=スキップ推奨)を返す。
sb_too_soon() {
  _marker="$STATE_DIR/.last-$1"
  if [ -f "$_marker" ]; then
    _last=$(cat "$_marker" 2>/dev/null || echo 0)
    _now=$(date +%s)
    if [ "$((_now - _last))" -lt "$MIN_INTERVAL_SEC" ]; then
      return 0
    fi
  fi
  return 1
}
sb_mark() { date +%s >"$STATE_DIR/.last-$1"; }

sb_have_claude() { command -v claude >/dev/null 2>&1; }

# ---- vault の存在確認 ------------------------------------------------------
sb_vault_ready() {
  if [ ! -d "$VAULT" ] || [ ! -f "$VAULT/INDEX.md" ]; then
    sb_log "[error] vault が未初期化: $VAULT — new-vault.sh を先に実行してください"
    exit 0
  fi
}

# ---- git チェックポイント(単一同期系の保存点) ---------------------------
# エージェントがファイルを書いた後に、明示的なタイミングだけでコミットする。
sb_git_checkpoint() {
  [ "$GIT_CHECKPOINT" = "1" ] || return 0
  command -v git >/dev/null 2>&1 || return 0
  [ -d "$VAULT/.git" ] || return 0
  ( cd "$VAULT" && git add -A \
      && { git diff --cached --quiet 2>/dev/null || git commit -q -m "$1"; } ) || true
}

# ---- claude -p を子として実行(再帰ガード付き) ---------------------------
# 使い方: sb_run_claude <model> <prompt> [追加の claude 引数...]
sb_run_claude() {
  _model="$1"; _prompt="$2"; shift 2
  SECOND_BRAIN_RUNNING=1 claude -p "$_prompt" --model "$_model" "$@"
}
