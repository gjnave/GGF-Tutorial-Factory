from __future__ import annotations

import subprocess
import time
import ctypes
from pathlib import Path


class FFmpegRecorder:
    def __init__(self, ffmpeg: Path, fps: int = 30):
        self.ffmpeg = ffmpeg
        self.fps = fps
        self.process: subprocess.Popen[bytes] | None = None

    def start(self, output: Path, rect: list[int], window_title: str = "") -> None:
        if self.process is not None:
            raise RuntimeError("Recorder is already running")
        x, y, width, height = [int(v) for v in rect]
        screen_width = int(ctypes.windll.user32.GetSystemMetrics(0))
        screen_height = int(ctypes.windll.user32.GetSystemMetrics(1))
        if x < 0:
            width += x
            x = 0
        if y < 0:
            height += y
            y = 0
        width = min(width, screen_width - x)
        height = min(height, screen_height - y)
        width -= width % 2
        height -= height % 2
        output.parent.mkdir(parents=True, exist_ok=True)
        # Capture the exact maximized app rectangle from the desktop. gdigrab's
        # title= mode intermittently loses Qt windows on Windows 11 (error 8).
        capture_args = [
            "-offset_x", str(x), "-offset_y", str(y),
            "-video_size", f"{width}x{height}", "-i", "desktop",
        ]
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "gdigrab", "-draw_mouse", "1", "-framerate", str(self.fps),
            *capture_args,
            "-an", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(output),
        ]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE)
        time.sleep(1.0)

    def stop(self) -> None:
        if self.process is None:
            return
        process, self.process = self.process, None
        if process.stdin:
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            except OSError:
                pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        if process.returncode not in (0, 255):
            raise RuntimeError(f"FFmpeg recording failed with exit code {process.returncode}")
