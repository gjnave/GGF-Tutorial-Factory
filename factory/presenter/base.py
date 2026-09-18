from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PresenterProvider(ABC):
    @abstractmethod
    def generate_presenter_clip(self, script: str, output_path: Path) -> Path | None:
        raise NotImplementedError

