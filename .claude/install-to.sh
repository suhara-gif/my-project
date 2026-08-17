#!/usr/bin/env bash
# セッション肥大化ガードを別のリポジトリへ導入/更新する
#
#   使い方:  bash .claude/install-to.sh ../gas-backup
#
# なぜインストーラなのか:
#   リモートセッション(claude.ai/モバイル)には個人設定 ~/.claude/settings.json が
#   届かない(実機で確認済み)。届くのはリポジトリ側の .claude/ だけ。したがって
#   カバーしたいリポジトリごとに配置が要る = 複製が生じる。
#   複製は必ずドリフトするので、**手でコピーせず、このスクリプトの再実行で同期**する。
#   このリポジトリ(my-project)の .claude/ を正本とする。
#
# 安全性:
#   - 既存 settings.json は**破壊しない**。フック配列に追記マージするだけ。
#   - 同名フックが既にあれば何もしない(冪等)。
#   - 上書き前に .bak を残す。
#
# 移植性: macOS(bash 3.2 / BSD)と Linux(GNU)の双方に存在する構成のみ使用。
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_REL='.claude/hooks/session-size-guard.sh'
# settings.json へ**リテラルとして**書き込む文字列。${CLAUDE_PROJECT_DIR:-.} は
# インストール時ではなく、フック実行時に Claude Code 側で展開されなければならない。
# 二重引用符にすると導入元のパスが焼き付いて導入先で壊れるため、単一引用符が正しい。
# shellcheck disable=SC2016
HOOK_CMD='bash "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/session-size-guard.sh" 2>/dev/null || true'

usage() {
  echo "使い方: bash .claude/install-to.sh <導入先リポジトリのパス>" >&2
  exit 2
}

[ "$#" -eq 1 ] || usage
DEST="$1"

[ -d "$DEST" ] || { echo "エラー: ディレクトリがありません: $DEST" >&2; exit 1; }
[ -d "$DEST/.git" ] || echo "警告: $DEST は git リポジトリに見えません。続行します。" >&2

command -v jq >/dev/null 2>&1 || { echo "エラー: jq が必要です。" >&2; exit 1; }

mkdir -p "$DEST/.claude/hooks"

# 1) フック本体をコピー(正本 → 導入先)
cp "$SRC_DIR/hooks/session-size-guard.sh" "$DEST/$HOOK_REL"
chmod +x "$DEST/$HOOK_REL"
echo "配置: $DEST/$HOOK_REL"

# 2) settings.json へフックを追記マージ
SETTINGS="$DEST/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  jq empty "$SETTINGS" 2>/dev/null || { echo "エラー: 既存の $SETTINGS が不正なJSONです。中断します。" >&2; exit 1; }

  # 重複判定: UserPromptSubmit 配下の全 command を平坦化して比較する。
  # (.hooks.UserPromptSubmit は「グループの配列」なので、一段掘ってから .hooks[] を見る)
  if jq -e --arg c "$HOOK_CMD" \
       '[(.hooks.UserPromptSubmit // [])[] | .hooks[]? | .command] | any(. == $c)' \
       "$SETTINGS" >/dev/null 2>&1; then
    echo "スキップ: フックは既に登録済みです（冪等）"
  else
    cp "$SETTINGS" "$SETTINGS.bak"
    tmp="$SETTINGS.tmp.$$"
    jq --arg c "$HOOK_CMD" \
      '.hooks //= {}
       | .hooks.UserPromptSubmit //= []
       | .hooks.UserPromptSubmit += [{
           hooks: [{
             type: "command",
             command: $c,
             timeout: 5,
             statusMessage: "セッション規模を確認中"
           }]
         }]' "$SETTINGS" > "$tmp"
    mv "$tmp" "$SETTINGS"
    echo "追記: $SETTINGS （元ファイルは $SETTINGS.bak に退避）"
  fi
else
  jq -n --arg c "$HOOK_CMD" \
    '{hooks: {UserPromptSubmit: [{
       hooks: [{
         type: "command",
         command: $c,
         timeout: 5,
         statusMessage: "セッション規模を確認中"
       }]
     }]}}' > "$SETTINGS"
  echo "新規作成: $SETTINGS"
fi

# 3) 正本の所在を書き残す(手編集を防ぐ)
cat > "$DEST/.claude/SOURCE.md" <<'EOF'
# このディレクトリの正本について

`hooks/session-size-guard.sh` と `settings.json` のフック登録は
**my-project リポジトリの `.claude/` が正本**です。

ここを直接編集しないでください。ドリフトします。
更新するときは my-project 側を直してから、そこで:

```sh
bash .claude/install-to.sh <このリポジトリのパス>
```

を再実行してください（冪等。既存の settings.json は破壊せず追記マージします）。

設計の背景・閾値の調整方法は my-project の `.claude/README.md` を参照。
EOF
echo "配置: $DEST/.claude/SOURCE.md"

echo
echo "完了。導入先で差分を確認してからコミットしてください:"
echo "  cd \"$DEST\" && git status && git diff"
