from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def inspect_media(ffprobe: Path, path: Path, min_duration: float = 20.0, max_duration: float = 900.0) -> dict[str, Any]:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    video = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in payload.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(payload.get("format", {}).get("duration", 0.0))
    checks = {
        "opens": bool(video), "has_audio": bool(audio), "duration_seconds": duration,
        "duration_in_mvp_range": min_duration <= duration <= max_duration,
        "resolution": [int(video.get("width", 0)), int(video.get("height", 0))] if video else [0, 0],
        "frame_rate": video.get("avg_frame_rate") if video else None,
    }
    rate = str(checks["frame_rate"] or "0/1").split("/")
    fps = float(rate[0]) / max(1.0, float(rate[1]))
    checks["fps_value"] = fps
    checks["passed"] = bool(
        checks["opens"] and checks["has_audio"] and checks["duration_in_mvp_range"]
        and checks["resolution"] == [1920, 1080] and 29.9 <= fps <= 30.1
    )
    return checks
