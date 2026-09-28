"""動画からフレームを切り出す(ffmpeg/ffprobe を使用)。

Claude の API は動画を直接受け取らないため、フレーム画像 + (任意で)文字起こしに分解して渡す。
冒頭のフック判定が最重要なので、最初の3秒は密に、それ以降は疎に切り出す。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
         "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout
    info = json.loads(out)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": float(info.get("format", {}).get("duration", 0) or 0),
        "width": v.get("width"),
        "height": v.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", [])),
    }


def sample_times(duration: float, *, head_sec: float = 3.0, head_step: float = 0.5, body_step: float = 2.0, max_frames: int = 40) -> list[float]:
    """冒頭は head_step 秒刻み、以降は body_step 秒刻み。上限を超えたら本編側を間引く。"""
    head = [round(t * head_step, 2) for t in range(int(min(head_sec, duration) / head_step) + 1)]
    body = []
    t = head_sec + body_step
    while t < duration:
        body.append(round(t, 2))
        t += body_step
    room = max_frames - len(head)
    if len(body) > room > 0:
        stride = len(body) / room
        body = [body[int(i * stride)] for i in range(room)]
    return head + body[: max(room, 0)]


def extract_frames(video: Path, out_dir: Path, times: list[float], *, width: int = 540) -> list[tuple[float, Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for t in times:
        p = out_dir / f"f_{t:07.2f}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(video),
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4", str(p)],
            check=True,
        )
        if p.exists():
            frames.append((t, p))
    return frames


def scene_cut_times(video: Path, *, threshold: float = 0.3) -> list[float]:
    """シーン切り替わり時刻(テンポ = cuts_per_10s の実測に使う)。LLM の目測より正確。"""
    proc = subprocess.run(
        ["ffmpeg", "-i", str(video), "-filter:v", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    times = []
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            try:
                times.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                continue
    return times
