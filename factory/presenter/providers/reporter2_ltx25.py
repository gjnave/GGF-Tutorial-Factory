from __future__ import annotations

from pathlib import Path

from factory.presenter.providers.ltx25 import Ltx25LizPresenterProvider


class Ltx25Reporter2PresenterProvider(Ltx25LizPresenterProvider):
    """Reporter 2 rendered with the same synchronized LTX 2.5 path as approved Liz."""

    def __init__(self, frames: int = 193, fps: int = 24, seed: int = 250901):
        super().__init__(
            base_image=Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\reporter2\reporter2_avatar.png"),
            frames=frames,
            fps=fps,
            seed=seed,
        )

    def prompt_for(self, text: str) -> str:
        spoken = self._ascii(text)
        return (
            "Use the provided start image as the first frame. Tight close-up portrait of the same "
            "friendly Get Going Fast woman, centered, face clearly visible, looking toward camera. "
            "She smiles and speaks in one clear, confident, natural female presenter voice, saying exactly, "
            f"\"{spoken}\" Her mouth articulates every word clearly in synchronization with the speech. "
            "She blinks naturally with subtle head motion. Preserve her identity, hairstyle, clothing, skin tone, "
            "the table, and the Get Going Fast box. Static locked camera, stable face, no scene cut, no music, "
            "no background noise, no extra speech."
        )

    def generate_segments(self, scripts: list[str], output_dir: Path) -> list[Path]:
        clips = []
        for index, script in enumerate(scripts, 1):
            clips.append(self.generate_presenter_clip(script, output_dir / f"reporter2_ltx_{index:02d}.mp4"))
        return clips
