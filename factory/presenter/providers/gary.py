from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from factory.edit.ffmpeg_renderer import probe_duration
from factory.presenter.base import PresenterProvider
from factory.voice.providers.firered_clone import FireRedVoiceCloneProvider


class GaryPresenterProvider(PresenterProvider):
    """Local Gary presenter using the supplied motion reference and cloned voice."""

    def __init__(
        self,
        reference_video: Path = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\gary\gary_reference.mp4"),
        driving_image: Path = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\gary\gary_driving_reference.jpg"),
    ):
        self.reference_video = reference_video.resolve()
        self.driving_image = driving_image.resolve()
        self.voice = FireRedVoiceCloneProvider()
        self.ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
        self.ffprobe = Path(shutil.which("ffprobe") or "ffprobe")

    def generate_presenter_clip(self, script: str, output_path: Path) -> Path:
        audio = self.voice.synthesize_many([script], output_path.parent / "voice")[0]
        return self._compose(audio, output_path)

    def generate_segments(self, scripts: list[str], output_dir: Path) -> list[Path]:
        audio_files = self.voice.synthesize_many(scripts, output_dir / "voice")
        return [
            self._compose(audio, output_dir / f"gary_{index:02d}.mp4")
            for index, audio in enumerate(audio_files, 1)
        ]

    def _compose(self, audio: Path, output_path: Path) -> Path:
        if not self.reference_video.is_file():
            raise FileNotFoundError(self.reference_video)
        duration = probe_duration(self.ffprobe, audio)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-stream_loop", "-1", "-i", str(self.reference_video), "-i", str(audio),
            "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", "scale=512:512:force_original_aspect_ratio=increase,crop=512:512,fps=24,format=yuv420p",
            "-af", "aresample=48000",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(output_path),
        ]
        subprocess.run(command, check=True)
        if not output_path.is_file() or output_path.stat().st_size < 10_000:
            raise RuntimeError(f"Gary presenter composition failed: {output_path}")
        return output_path
