from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ApplicationAdapter(ABC):
    """Semantic boundary between Tutorial Factory and an application UI."""

    @abstractmethod
    def launch(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def state(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def widget(self, semantic_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def capture(self, path: Path) -> Path:
        raise NotImplementedError("This adapter does not provide window-native capture")

    def wait_for_output(
        self, timeout: float, newer_than: float | None = None,
        baseline: set[str] | None = None, stable_seconds: float = 3.0, min_bytes: int = 1,
    ) -> Path:
        raise NotImplementedError("This adapter does not expose output discovery")

    def show_output(self, path: Path | None = None) -> Path:
        if path is None:
            path = self.wait_for_output(timeout=0)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path
