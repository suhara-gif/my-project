"""台本 + 素材 + ナレーションから動画を組み立てる(ffmpeg)。

Opus と TTS が作れるのは「台本」と「音声」まで。**映像素材は別途必要**。
ここでは素材ライブラリ(ファイル名に visual_tag を含む画像/動画)から各シーンの素材を選び、
見つからないシーンは「撮影/生成が必要なカット」として一覧で返して止める(黒画面で埋めて入稿しない)。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .script import VideoScript
from .tts import TTSProvider

VIDEO_EXT = {".mp4", ".mov", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SIZE = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}


@dataclass
class ResolvedScene:
    index: int
    asset: Path
    duration: float
    narration_wav: Path | None


class MissingAssetsError(RuntimeError):
    def __init__(self, missing: list[tuple[int, str, str]]):
        self.missing = missing
        lines = "\n".join(f"- シーン{i + 1} [{tag}] {visual}" for i, tag, visual in missing)
        super().__init__(f"素材が足りないシーンがあります(撮影または生成が必要):\n{lines}")


def find_asset(library: Path, tag: str) -> Path | None:
    cands = sorted(p for p in library.rglob("*") if p.suffix.lower() in VIDEO_EXT | IMAGE_EXT and tag in p.stem)
    return cands[0] if cands else None


def to_srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(script: VideoScript, durations: list[float]) -> str:
    out, t = [], 0.0
    n = 1
    for s, d in zip(script.scenes, durations):
        if s.on_screen_text:
            out.append(f"{n}\n{to_srt_time(t)} --> {to_srt_time(t + d)}\n{s.on_screen_text}\n")
            n += 1
        t += d
    return "\n".join(out)


def resolve(script: VideoScript, library: Path, tts: TTSProvider, work: Path) -> list[ResolvedScene]:
    missing, resolved = [], []
    for i, s in enumerate(script.scenes):
        asset = find_asset(library, s.visual_tag)
        if asset is None:
            missing.append((i, s.visual_tag, s.visual))
            continue
        wav, dur = None, s.duration_sec
        if s.narration:
            wav = work / f"narration_{i:02}.wav"
            # ナレーションが尺に収まらなければシーンを延ばす(早口で詰めるより自然)
            dur = max(dur, tts.synthesize(s.narration, wav) + 0.2)
        resolved.append(ResolvedScene(i, asset, dur, wav))
    if missing:
        raise MissingAssetsError(missing)
    return resolved


def render(script: VideoScript, scenes: list[ResolvedScene], work: Path, out: Path, *, font: str = "Noto Sans CJK JP") -> Path:
    w, h = SIZE[script.aspect_ratio]
    work.mkdir(parents=True, exist_ok=True)
    clips = []
    for sc in scenes:
        clip = work / f"scene_{sc.index:02}.mp4"
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,format=yuv420p"
        src = ["-loop", "1", "-t", f"{sc.duration:.2f}", "-i", str(sc.asset)] if sc.asset.suffix.lower() in IMAGE_EXT \
            else ["-stream_loop", "-1", "-t", f"{sc.duration:.2f}", "-i", str(sc.asset)]
        aud = ["-i", str(sc.narration_wav)] if sc.narration_wav else ["-f", "lavfi", "-t", f"{sc.duration:.2f}", "-i", "anullsrc=r=44100:cl=mono"]
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *src, *aud, "-map", "0:v", "-map", "1:a",
             "-vf", vf, "-af", f"apad,atrim=0:{sc.duration:.2f}", "-t", f"{sc.duration:.2f}",
             "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-ac", "1", str(clip)],
            check=True,
        )
        clips.append(clip)

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    srt = work / "subs.srt"
    srt.write_text(build_srt(script, [s.duration for s in scenes]), encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    style = f"FontName={font},FontSize=14,Outline=2,Alignment=2,MarginV=120"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-vf", f"subtitles={srt}:force_style='{style}'", "-c:v", "libx264", "-c:a", "aac", str(out)],
        check=True,
    )
    return out
