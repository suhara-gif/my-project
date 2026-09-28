"""ナレーション音声の生成(TTS)。

依頼時に名前の挙がった「3.8 Flash TTS」は、このリポジトリ作成時点で正式なモデルID・API仕様を
確認できていない([要確認])。存在しない ID を決め打ちで書かないよう、プロバイダは差し替え可能にし、
任意の CLI を呼べる CommandTTS を用意する。確定したら同じ Protocol を満たすクラスを足す。
"""

from __future__ import annotations

import shlex
import subprocess
import wave
from pathlib import Path
from typing import Protocol


class TTSProvider(Protocol):
    def synthesize(self, text: str, out_path: Path) -> float:
        """text を読み上げた音声を out_path(wav)に書き、秒数を返す。"""


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


class CommandTTS:
    """外部コマンドで TTS する。command は {text_file} と {out} を含むテンプレート。

    例: "my-tts --voice ja-JP-male --in {text_file} --out {out}"
    """

    def __init__(self, command: str):
        if "{text_file}" not in command or "{out}" not in command:
            raise ValueError("command には {text_file} と {out} が必要")
        self.command = command

    def synthesize(self, text: str, out_path: Path) -> float:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text_file = out_path.with_suffix(".txt")
        text_file.write_text(text, encoding="utf-8")
        cmd = self.command.format(text_file=shlex.quote(str(text_file)), out=shlex.quote(str(out_path)))
        subprocess.run(cmd, shell=True, check=True)
        return wav_duration(out_path)


class SilentTTS:
    """テスト・台本確認用。文字数から尺を見積もって無音 wav を作る(日本語 約7文字/秒)。"""

    def __init__(self, chars_per_sec: float = 7.0, rate: int = 16000):
        self.cps = chars_per_sec
        self.rate = rate

    def synthesize(self, text: str, out_path: Path) -> float:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dur = max(len(text) / self.cps, 0.3)
        n = int(dur * self.rate)
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"\x00\x00" * n)
        return dur
