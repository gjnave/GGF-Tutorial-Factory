from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from factory.edit.ffmpeg_renderer import probe_duration
from factory.presenter.base import PresenterProvider
from factory.voice.providers.firered_clone import FireRedVoiceCloneProvider


class Reporter2PresenterProvider(PresenterProvider):
    """User-supplied still presenter with the supplied cloned voice."""

    PROMPT_TEXT = "A seventy-year-old Idaho man was arrested after allegedly striking a pro-Trump counter-protester."

    def __init__(
        self,
        image: Path = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\reporter2\reporter2_avatar.png"),
        voice_reference: Path = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\reporter2\reporter2_voice_reference_short.wav"),
    ):
        self.image = image.resolve()
        self.voice = FireRedVoiceCloneProvider(prompt_audio=voice_reference, prompt_text=self.PROMPT_TEXT)
        self.ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
        self.ffprobe = Path(shutil.which("ffprobe") or "ffprobe")

    def generate_presenter_clip(self, script: str, output_path: Path) -> Path:
        audio = self.voice.synthesize_many([script], output_path.parent / "voice")[0]
        return self._compose(audio, output_path, 1)

    def generate_segments(self, scripts: list[str], output_dir: Path) -> list[Path]:
        if not self.image.is_file():
            raise FileNotFoundError(self.image)
        audio_files = self.voice.synthesize_many(scripts, output_dir / "voice")
        return [self._compose(audio, output_dir / f"reporter2_{index:02d}.mp4", index) for index, audio in enumerate(audio_files, 1)]

    def _compose(self, audio: Path, output_path: Path, index: int) -> Path:
        duration = probe_duration(self.ffprobe, audio)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        zoom = "min(zoom+0.00010,1.035)" if index % 2 else "if(lte(zoom,1.0),1.035,max(1.0,zoom-0.00010))"
        vf = (
            "scale=620:620:force_original_aspect_ratio=increase,crop=620:620,"
            f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=512x512:fps=24,"
            "format=yuv420p"
        )
        subprocess.run([
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-loop", "1", "-i", str(self.image), "-i", str(audio), "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-af", "aresample=48000",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(output_path),
        ], check=True)
        if not output_path.is_file() or output_path.stat().st_size < 10_000:
            raise RuntimeError(f"Presenter composition failed: {output_path}")
        return output_path
