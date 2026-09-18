from __future__ import annotations

from pathlib import Path

from ..base import PresenterProvider


class NonePresenterProvider(PresenterProvider):
    def generate_presenter_clip(self, script: str, output_path: Path) -> Path | None:
        return None

