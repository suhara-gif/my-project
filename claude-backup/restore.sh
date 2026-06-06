#!/usr/bin/env bash
#
# restore.sh — バックアップから ~/.claude を復元する。
#
# 使い方:
#   1) Notion の「Claudeバックアップ台帳」で復元したい時点の行を開き、
#      アーカイブリンクから .tar.gz(または .tar.gz.age)をダウンロードする。
#   2) このスクリプトにそのファイルパスを渡す:
#        ./restore.sh ~/Downloads/claude-backup-YYYYMMDD-HHMMSS.tar.gz
#      暗号化済みなら自動で age 復号を試みる(秘密鍵が必要)。
#
# 安全策: 既存の ~/.claude は上書き前に退避する。秘密情報(~/.claude.json)は
# バックアップに含まれないため、復元後に `claude login` で再認証すること。
set -euo pipefail

ARCHIVE="${1:-}"
TARGET="${CLAUDE_RESTORE_TARGET:-$HOME/.claude}"

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "usage: $0 <archive.tar.gz|.tar.gz.age>" >&2
  exit 1
fi

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
SRC="$ARCHIVE"

# age 暗号化アーカイブなら復号
if [[ "$ARCHIVE" == *.age ]]; then
  command -v age >/dev/null || { echo "age が必要です" >&2; exit 1; }
  KEY="${CLAUDE_RESTORE_AGE_KEY:-$HOME/.config/age/keys.txt}"
  age -d -i "$KEY" -o "$WORK/restore.tar.gz" "$ARCHIVE"
  SRC="$WORK/restore.tar.gz"
fi

# 中身を確認(展開前に一覧表示)
echo "== アーカイブ内容 =="
tar tzf "$SRC" | head -50
echo "...(先頭50件)"
read -r -p "上記を $TARGET に復元します。よろしいですか? [y/N] " ans
[[ "$ans" == [yY] ]] || { echo "中止"; exit 0; }

# 既存を退避
if [[ -d "$TARGET" ]]; then
  BAK="$TARGET.before-restore.$(date +%Y%m%d-%H%M%S)"
  mv "$TARGET" "$BAK"
  echo "既存を退避: $BAK"
fi

mkdir -p "$(dirname "$TARGET")"
tar xzf "$SRC" -C "$(dirname "$TARGET")"
echo "復元完了: $TARGET"
echo "※ 認証情報は含まれません。'claude login' で再ログインしてください。"
