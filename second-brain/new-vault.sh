#!/usr/bin/env bash
#
# new-vault.sh — セカンドブレインの保管庫(vault)の骨組みを作る。
#
#   raw/ entities/ concepts/ syntheses/ と INDEX.md・CLAUDE.md を用意し、
#   サンプルページを2枚置き、git を初期化する(単一同期系の保存点)。
#
# 使い方:
#   ./new-vault.sh [vault のパス]     # 省略時は $SECOND_BRAIN_VAULT か ~/vault
#
# 既存ファイルは上書きしない(あなたの vault を壊さない)。冪等。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/vault-template"

# 設定ファイルがあれば vault 既定値を拾う
CONFIG_FILE="${SECOND_BRAIN_CONFIG:-$HOME/.claude/second-brain/config}"
# shellcheck disable=SC1090
[ -f "$CONFIG_FILE" ] && . "$CONFIG_FILE"

VAULT="${1:-${SECOND_BRAIN_VAULT:-$HOME/vault}}"

echo "== セカンドブレイン vault 初期化: $VAULT =="

if [ ! -d "$TEMPLATE" ]; then
  echo "[error] テンプレートが見つからない: $TEMPLATE" >&2
  exit 1
fi

mkdir -p "$VAULT"

# テンプレートを再帰コピー(既存ファイルは温存)。cp -n は BSD/GNU 両対応。
# ディレクトリ構造を先に作ってからファイルを個別に -n でコピーする。
( cd "$TEMPLATE" && find . -type d ) | while IFS= read -r d; do
  mkdir -p "$VAULT/$d"
done
( cd "$TEMPLATE" && find . -type f ) | while IFS= read -r f; do
  if [ -e "$VAULT/$f" ]; then
    echo "[keep] 既存を温存: $f"
  else
    cp "$TEMPLATE/$f" "$VAULT/$f"
    echo "[ok]   配置: $f"
  fi
done

# git 初期化(単一同期系。iCloud/Dropbox 等と競合させず、保存点は git に一本化)
if command -v git >/dev/null 2>&1; then
  if [ ! -d "$VAULT/.git" ]; then
    ( cd "$VAULT" \
        && git init -q \
        && printf '%s\n' '.obsidian/workspace*.json' '.DS_Store' '.trash/' >.gitignore \
        && git add -A \
        && git -c user.name='second-brain' -c user.email='second-brain@localhost' \
             commit -q -m "セカンドブレイン vault を初期化" )
    echo "[ok]   git 初期化 + 初回コミット"
  else
    echo "[keep] 既存の git リポジトリを温存"
  fi
else
  echo "[warn] git 不在。単一同期系のため git 導入を強く推奨(vault はここで死ぬ)"
fi

cat <<NOTE

[done] vault 準備完了: $VAULT

次にやること:
  1) raw/ に手持ちの素材を放り込む(文字起こし・ブックマーク・メモ・過去リサーチ)
  2) Claude Code をこの vault で開き、/goal でバックフィル(README の「バックフィル」参照)
  3) ./install.sh でループ(セッション採掘・夜間コンパイル・週次lint/総合)を有効化
  4) 各プロジェクトの CLAUDE.md に project-CLAUDE.snippet.md の3行を追加

設定で vault のパスを固定するには ~/.claude/second-brain/config に:
  SECOND_BRAIN_VAULT="$VAULT"
NOTE
