"""Media metadata and content hashes used by collections."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _rate(value: str) -> float:
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def probe_video(path: str | Path) -> dict[str, Any]:
    media_path = Path(path)
    if not media_path.is_file() or media_path.stat().st_size == 0:
        raise ValueError(f"Video is missing or empty: {media_path}")
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate:format=duration,size",
        "-of", "json", str(media_path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe is required for collection extraction") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe could not read {media_path}: {exc.stderr.strip()}") from exc
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    if not streams:
        raise ValueError(f"No video stream found in {media_path}")
    stream = streams[0]
    return {
        "duration": float(payload["format"]["duration"]),
        "size": int(payload["format"]["size"]),
        "fps": _rate(stream["avg_frame_rate"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "codec": stream.get("codec_name"),
    }
