from __future__ import annotations

from pathlib import Path


def _stamp(seconds: float, vtt: bool = False) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def write_subtitles(segments: list[dict], srt_path: Path, vtt_path: Path) -> None:
    srt_lines: list[str] = []
    vtt_lines = ["WEBVTT", ""]
    for index, segment in enumerate(segments, 1):
        start, end, text = float(segment["start"]), float(segment["end"]), str(segment["text"])
        srt_lines += [str(index), f"{_stamp(start)} --> {_stamp(end)}", text, ""]
        vtt_lines += [f"{_stamp(start, True)} --> {_stamp(end, True)}", text, ""]
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")

