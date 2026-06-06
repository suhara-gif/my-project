#!/usr/bin/env bash
#
# install.sh — このキットをローカルマシンの ~/.claude/backup/ に配置し、
# SessionEnd フックと日次スケジュールを有効化する。
#
# 実行は「あなたのローカルPC」で行うこと(クラウドセッションではなくローカルの
# ~/.claude を守るのが目的)。冪等。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude/backup"
SETTINGS="$HOME/.claude/settings.json"

echo "== Claude バックアップ仕組み インストール =="

# 1) スクリプト配置
mkdir -p "$DEST"
cp "$HERE/run-backup.sh" "$HERE/restore.sh" "$DEST/"
chmod +x "$DEST/run-backup.sh" "$DEST/restore.sh"
echo "[ok] スクリプト配置: $DEST"

# 2) settings.json に SessionEnd フックをマージ
if command -v jq >/dev/null 2>&1; then
  tmp="$(mktemp)"
  if [[ -f "$SETTINGS" ]]; then base="$SETTINGS"; else echo '{}' >"$tmp.base"; base="$tmp.base"; fi
  jq --arg cmd "$HOME/.claude/backup/run-backup.sh" '
    .hooks.SessionEnd = ((.hooks.SessionEnd // []) +
      [ { "hooks": [ { "type": "command", "command": $cmd } ] } ]
      | unique_by(.hooks[0].command) )
  ' "$base" >"$tmp"
  mv "$tmp" "$SETTINGS"
  echo "[ok] SessionEnd フックを $SETTINGS に追加"
else
  echo "[warn] jq 不在。settings.snippet.json を手動で $SETTINGS にマージしてください"
fi

# 3) 日次スケジュール(保険)。macOS は launchd、その他は cron。
OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  # macOS: cron は非推奨(Full Disk Access が必要)なので launchd を使う
  PLIST="$HOME/Library/LaunchAgents/com.claude.backup.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat >"$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.claude.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>$HOME/.claude/backup/run-backup.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>$HOME/.claude/backup/launchd.log</string>
  <key>StandardOutPath</key><string>$HOME/.claude/backup/launchd.log</string>
</dict>
</plist>
PLIST_EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST" 2>/dev/null && echo "[ok] launchd 登録(毎日 09:30): $PLIST" \
    || echo "[warn] launchctl load 失敗。$PLIST を手動で読み込んでください"
elif command -v crontab >/dev/null 2>&1; then
  LINE="30 9 * * * $HOME/.claude/backup/run-backup.sh >/dev/null 2>&1"
  ( crontab -l 2>/dev/null | grep -v 'claude/backup/run-backup.sh' ; echo "$LINE" ) | crontab -
  echo "[ok] 日次 cron 登録(毎日 09:30)"
else
  echo "[info] cron 不在。Windows は タスクスケジューラで"
  echo "       毎日 ~/.claude/backup/run-backup.sh を実行する設定を追加してください"
fi

cat <<'NOTE'

== 次の設定(任意の環境変数を ~/.claude/settings.json の env か シェルに) ==
  CLAUDE_BACKUP_DEST=googledrive          # または box
  CLAUDE_BACKUP_DEST_FOLDER=ClaudeBackups
  CLAUDE_BACKUP_AGE_RECIPIENT=age1...      # 設定すると暗号化を有効化
  CLAUDE_BACKUP_MIN_INTERVAL=1800          # 連発時の最小間隔(秒)

初回は手動で動作確認:
  ~/.claude/backup/run-backup.sh ; tail -n 20 ~/.claude/backup/backup.log

Notion の「Claudeバックアップ台帳」DB は初回実行時に自動作成されます。
NOTE
echo "[done] インストール完了"
