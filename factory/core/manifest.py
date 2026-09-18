from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TutorialManifest:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "TutorialManifest":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Manifest root must be a mapping: {path}")
        for key in ("title", "application", "video", "scenes"):
            if key not in payload:
                raise ValueError(f"Manifest is missing '{key}': {path}")
        return cls(path=path, data=payload)

    @property
    def title(self) -> str:
        return str(self.data["title"])

    @property
    def scenes(self) -> list[dict[str, Any]]:
        scenes = self.data.get("scenes") or []
        if not isinstance(scenes, list):
            raise ValueError("Manifest 'scenes' must be a list")
        return scenes

