#!/usr/bin/env bash
#
# install.sh — セカンドブレイン・キットをローカルマシンの ~/.claude/second-brain/ へ
# 配置し、ループを有効化する:
#   - SessionEnd フック    … session-mine.sh(セッション採掘)
#   - 日次スケジュール      … compile.sh(夜間コンパイル / 安いモデル)
#   - 週次スケジュール      … lint.sh(点検)+ synthesize.sh(総合 / 賢いモデル)
#
# 実行は「あなたのローカルPC」で(守る/育てる対象はローカルの vault)。冪等。
# macOS は launchd、その他は cron を自動登録。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude/second-brain"
SETTINGS="$HOME/.claude/settings.json"

echo "== セカンドブレイン・キット インストール =="

# 1) キット一式を配置(スクリプト + lib + vault テンプレート + snippet)
mkdir -p "$DEST"
cp "$HERE"/lib.sh "$HERE"/*.sh "$DEST/"
cp "$HERE"/settings.snippet.json "$HERE"/project-CLAUDE.snippet.md "$DEST/" 2>/dev/null || true
rm -rf "$DEST/vault-template"
cp -R "$HERE/vault-template" "$DEST/vault-template"
chmod +x "$DEST"/*.sh
echo "[ok] キット配置: $DEST"

# 2) 設定ファイルの雛形(無ければ作成)。フックも launchd/cron も rc を読まないので、
#    環境変数はここ(KEY=VALUE)で効かせる。
CONFIG="$DEST/config"
if [ ! -f "$CONFIG" ]; then
  cat >"$CONFIG" <<'CONFIG_EOF'
# セカンドブレイン設定 (KEY=VALUE)。各スクリプトが起動時に読み込む。

# vault(Obsidian 保管庫 = ただのフォルダ)の場所。未設定なら ~/vault。
# SECOND_BRAIN_VAULT="$HOME/vault"

# モデル階層。ルーチン(採掘/コンパイル/lint)は安いモデル、週次総合だけ賢いモデル。
# CLI エイリアス(haiku/sonnet/opus)推奨。正確なモデルIDに縛られない。
# SECOND_BRAIN_MODEL_CHEAP="haiku"
# SECOND_BRAIN_MODEL_SMART="opus"

# セッション採掘の最小間隔(秒)。連発を無駄打ちしない。
# SECOND_BRAIN_MIN_INTERVAL="900"

# 単一同期系。書き込み後に git チェックポイントを打つ(1=有効, 0=無効)。
# SECOND_BRAIN_GIT="1"

# リサーチ機の既定失効日数(stale 知識が自己申告するように)。
# SECOND_BRAIN_RESEARCH_EXPIRE_DAYS="30"

# リサーチで許可する MCP サーバー名(空白区切り)。未設定なら claude mcp list から自動検出。
# SECOND_BRAIN_RESEARCH_MCP="Notion firecrawl"
CONFIG_EOF
  echo "[ok] 設定雛形を作成: $CONFIG"
else
  echo "[info] 既存の設定を保持: $CONFIG"
fi

# 2.5) claude CLI の実体パスを config に固定する(冪等)。
#      launchd/cron はログインシェルの PATH を引き継がないため、いま(PATH が
#      生きているインストール時)に解決して書き込んでおくのが最も確実。
if ! grep -q '^SECOND_BRAIN_CLAUDE_BIN=' "$CONFIG" 2>/dev/null; then
  if command -v claude >/dev/null 2>&1; then
    CLAUDE_PATH="$(command -v claude)"
    {
      echo ""
      echo "# claude CLI の実体パス(launchd/cron は PATH を引き継がないため明示)。install.sh が自動検出。"
      echo "SECOND_BRAIN_CLAUDE_BIN=\"$CLAUDE_PATH\""
    } >>"$CONFIG"
    echo "[ok] claude CLI を検出して config に固定: $CLAUDE_PATH"
  else
    echo "[warn] claude CLI が PATH に見つからない。スケジュール実行が全てスキップされます。"
    echo "       導入後に $CONFIG へ SECOND_BRAIN_CLAUDE_BIN=\"/path/to/claude\" を追記してください"
  fi
else
  echo "[info] SECOND_BRAIN_CLAUDE_BIN は設定済み"
fi

# 3) vault が無ければ初期化するか尋ねる
VAULT_PATH="${SECOND_BRAIN_VAULT:-$HOME/vault}"
# shellcheck disable=SC1090
[ -f "$CONFIG" ] && . "$CONFIG"
VAULT_PATH="${SECOND_BRAIN_VAULT:-$HOME/vault}"
if [ ! -f "$VAULT_PATH/INDEX.md" ]; then
  echo "[info] vault 未検出: $VAULT_PATH"
  echo "       初期化するには: $DEST/new-vault.sh \"$VAULT_PATH\""
else
  echo "[info] 既存 vault を検出: $VAULT_PATH"
fi

# 4) settings.json に SessionEnd フックをマージ
if command -v jq >/dev/null 2>&1; then
  tmp="$(mktemp)"
  if [ -f "$SETTINGS" ]; then base="$SETTINGS"; else echo '{}' >"$tmp.base"; base="$tmp.base"; fi
  jq --arg cmd "$DEST/session-mine.sh" '
    .hooks.SessionEnd = ((.hooks.SessionEnd // []) +
      [ { "hooks": [ { "type": "command", "command": $cmd } ] } ]
      | unique_by(.hooks[0].command) )
  ' "$base" >"$tmp"
  mv "$tmp" "$SETTINGS"
  echo "[ok] SessionEnd フックを $SETTINGS に追加"
else
  echo "[warn] jq 不在。settings.snippet.json を手動で $SETTINGS にマージしてください"
fi

# 5) スケジュール登録。macOS は launchd、その他は cron。
#    日次: 夜間コンパイル(02:15) / 週次: lint(日 03:15)・総合(日 04:15)
register_launchd() {
  # $1=label suffix, $2=script, $3=hour, $4=minute, [$5=weekday(0-6, 日=0) 省略で毎日]
  _label="com.claude.second-brain.$1"
  _plist="$HOME/Library/LaunchAgents/$_label.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  _cal="<key>Hour</key><integer>$3</integer><key>Minute</key><integer>$4</integer>"
  [ -n "${5:-}" ] && _cal="$_cal<key>Weekday</key><integer>$5</integer>"
  cat >"$_plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$_label</string>
  <key>ProgramArguments</key>
  <array><string>$DEST/$2</string></array>
  <key>StartCalendarInterval</key>
  <dict>$_cal</dict>
  <key>StandardErrorPath</key><string>$DEST/launchd.log</string>
  <key>StandardOutPath</key><string>$DEST/launchd.log</string>
</dict>
</plist>
PLIST_EOF
  launchctl unload "$_plist" 2>/dev/null || true
  if launchctl load "$_plist" 2>/dev/null; then
    echo "[ok] launchd 登録: $_label"
  else
    echo "[warn] launchctl load 失敗: $_plist を手動で読み込んでください"
  fi
}

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
  register_launchd compile   compile.sh    2 15
  register_launchd lint      lint.sh       3 15 0
  register_launchd synthesize synthesize.sh 4 15 0
elif command -v crontab >/dev/null 2>&1; then
  # 既存の second-brain 行を除いてから3行を追加(冪等)
  ( crontab -l 2>/dev/null | grep -v 'second-brain/\(compile\|lint\|synthesize\).sh' ; \
    echo "15 2 * * * $DEST/compile.sh >/dev/null 2>&1" ; \
    echo "15 3 * * 0 $DEST/lint.sh >/dev/null 2>&1" ; \
    echo "15 4 * * 0 $DEST/synthesize.sh >/dev/null 2>&1" ) | crontab -
  echo "[ok] cron 登録: 夜間コンパイル(02:15) / 週次lint(日03:15) / 週次総合(日04:15)"
else
  echo "[info] cron 不在。Windows はタスクスケジューラで compile/lint/synthesize を登録してください"
fi

cat <<NOTE

== 次の手順 ==
  1) vault 初期化(未作成なら):
       $DEST/new-vault.sh "$VAULT_PATH"
  2) raw/ に手持ちの素材を放り込む(文字起こし・ブックマーク・メモ・過去リサーチ)
  3) Claude Code を vault で開き /goal でバックフィル(README のバックフィル参照)
  4) リサーチ機を回す:  $DEST/research.sh "調べたい問い"
  5) 各プロジェクトの CLAUDE.md に project-CLAUDE.snippet.md の3行を追加

動作確認:
  $DEST/compile.sh ; tail -n 20 $DEST/second-brain.log
NOTE
echo "[done] インストール完了"
