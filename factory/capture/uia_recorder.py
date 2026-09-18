from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

from factory.adapters.base import ApplicationAdapter


class UIAFrameRecorder:
    """Window-native recorder for unattended UIA applications."""

    def __init__(self, adapter: ApplicationAdapter, capture_fps: int = 5, output_fps: int = 30):
        self.adapter = adapter
        self.capture_fps = capture_fps
        self.output_fps = output_fps
        self.output: Path | None = None
        self.frame_dir: Path | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.error: Exception | None = None
        self.captured_frames = 0

    def start(self, output: Path, rect: list[int] | None = None, window_title: str = "") -> None:
        if self.thread is not None:
            raise RuntimeError("Recorder is already running")
        self.output = output.resolve()
        self.frame_dir = self.output.parent / f"{self.output.stem}_frames"
        if self.frame_dir.exists():
            raise FileExistsError(f"Frame directory already exists and will not be overwritten: {self.frame_dir}")
        self.frame_dir.mkdir(parents=True)
        self.stop_event.clear()
        self.pause_event.clear()
        self.captured_frames = 0
        self.thread = threading.Thread(target=self._capture_loop, name="tutorial-uia-recorder", daemon=True)
        self.thread.start()
        time.sleep(0.4)

    def _capture_loop(self) -> None:
        assert self.frame_dir is not None
        interval = 1.0 / self.capture_fps
        index = 1
        try:
            while not self.stop_event.is_set():
                if self.pause_event.is_set():
                    self.stop_event.wait(0.1)
                    continue
                target = self.frame_dir / f"frame_{index:06d}.png"
                self.adapter.capture(target)
                index += 1
                self.captured_frames += 1
                self.stop_event.wait(interval)
        except Exception as exc:
            self.error = exc
            self.stop_event.set()

    def pause(self) -> None:
        self.pause_event.set()
        time.sleep(0.15)

    def resume(self) -> None:
        self.pause_event.clear()
        time.sleep(0.25)

    def elapsed(self) -> float:
        return self.captured_frames / float(self.capture_fps)

    def stop(self) -> None:
        thread, self.thread = self.thread, None
        if thread is None:
            return
        self.stop_event.set()
        thread.join(timeout=15)
        if thread.is_alive():
            raise RuntimeError("UIA frame recorder did not stop")
        if self.error:
            raise RuntimeError(f"UIA frame recording failed: {self.error}")
        assert self.output is not None and self.frame_dir is not None
        frames = sorted(self.frame_dir.glob("frame_*.png"))
        if len(frames) < 2:
            raise RuntimeError(f"UIA frame recorder captured only {len(frames)} frames")
        ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
        self.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-framerate", str(self.capture_fps), "-i", str(self.frame_dir / "frame_%06d.png"),
            "-vf", f"fps={self.output_fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", str(self.output),
        ], check=True)
