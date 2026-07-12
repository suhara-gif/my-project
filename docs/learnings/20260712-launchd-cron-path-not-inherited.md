# launchd/cron はログインシェルの PATH を引き継がず、スケジュール実行だけ CLI が見つからない

- 日付: 2026-07-12
- 種別: バグ修正 / 移植性
- 触れたファイル: second-brain/lib.sh, second-brain/install.sh, second-brain/research.sh, claude-backup/run-backup.sh

## 問題

second-brain の初回スケジュール実行(02:15 コンパイル / 03:15 lint / 04:15 総合)が
すべて「claude CLI 不在。スキップ」で終わった。同じスクリプトの手動実行は成功して
いた(前夜 21:16 の手動 compile は `[ok]`)。

## 文脈

launchd(macOS)も cron(Linux)も、ジョブを**最小限の PATH**
(`/usr/bin:/bin` 程度)で起動し、`~/.zshrc` 等のログインシェル設定を読まない。
Homebrew(`/opt/homebrew/bin`)や `~/.local/bin` にある CLI は `command -v` で
見つからない。手動実行(ログインシェル)では常に成功するため、**初回のスケジュール
発火まで露見しない**のがこのバグの厄介さ。SessionEnd フックも同様に rc を読まない
(このリポジトリでは config ファイル方式で既に対処済みだったが、CLI の実体パスは
未対処だった)。

## 解法と、その理由

3 段フォールバックで実体パスを解決する方式にした:

1. **install 時に固定**: install.sh は PATH が生きているログインシェルで走るので、
   そこで `command -v claude` の結果を config に `SECOND_BRAIN_CLAUDE_BIN` として
   書き込む(冪等)。これが最も確実な層。
2. **実行時の PATH**: 通常のシェルから叩いた場合はそのまま `command -v` で解決。
3. **一般的な設置場所の走査**: `/opt/homebrew/bin` `/usr/local/bin` `~/.local/bin`
   `~/.npm-global/bin` を順に探す。config が無い・古い場合の保険。

実行時は解決済みの絶対パスで exec し、子プロセスの PATH にも実体のディレクトリを
前置する(CLI が内部で補助コマンドを呼ぶ場合に備える)。

**plist に `EnvironmentVariables` で PATH を直書きする案を退けた理由**:
(1) Linux の cron に効かない(同じバグが残る)、(2) install.sh を再実行すると
plist が再生成されて手当てが消える、(3) スケジューラごとに直すより、スクリプト側で
自立して解決する方が発火経路(フック/launchd/cron/手動)全部に一度で効く。

## うまくいかなかったこと

なし(ただし当初のコードは `command -v claude` 単独に依存しており、これは
「手動テストが通る=スケジュールでも動く」という誤った推定だった)。

## 抽出したルール / ヒューリスティック

- **launchd/cron/フックから外部 CLI を呼ぶスクリプトは、`command -v` 単独に依存して
  はならない**。config に固定した絶対パス → PATH → 既知の設置場所、の順で解決する。
- **スケジュール実行のテストは、手動実行の成功で代用できない**。macOS では
  `launchctl kickstart -k gui/$(id -u)/<label>` で launchd の実環境のまま即時発火
  させて検証する。
- 新しいキットに `claude -p` 委譲を足すときは、この解決関数(lib.sh の
  `sb_resolve_claude`)を使うか同等の 3 段フォールバックを実装する。

## 関連

- second-brain/lib.sh の `sb_resolve_claude()`(実装本体)
