from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def overlay_animated_presenter(
    ffmpeg: Path,
    background: Path,
    presenter_track: Path,
    output: Path,
    chapters: list[dict[str, Any]],
) -> Path:
    """Replace a presenter layer while preserving an already-approved UI render."""
    y_expression = "668"
    for chapter in reversed(chapters):
        if str(chapter.get("presenter_position") or "lower-right") == "upper-right":
            y_expression = (
                f"if(between(t,{float(chapter['start']):.3f},{float(chapter['end']):.3f}),"
                f"128,{y_expression})"
            )
    graph = (
        "[1:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
        "pad=382:382:11:11:color=0xF28C28,setpts=PTS-STARTPTS[presenter];"
        f"[0:v][presenter]overlay=x=1518:y='{y_expression}':shortest=1:eof_action=pass[v];"
        "[1:a]loudnorm=I=-16:LRA=11:TP=-1.5[voice]"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(background), "-i", str(presenter_track),
        "-filter_complex", graph,
        "-map", "[v]", "-map", "[voice]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(output),
    ], check=True)
    if not output.is_file() or output.stat().st_size < 10_000:
        raise RuntimeError(f"Animated presenter overlay failed: {output}")
    return output
