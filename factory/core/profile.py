from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _expanded(value: str) -> str:
    return os.path.expandvars(value)


@dataclass(frozen=True)
class ApplicationProfile:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ApplicationProfile":
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Application profile root must be a mapping: {path}")
        for key in ("profile_version", "application", "adapter", "launch", "controls"):
            if key not in payload:
                raise ValueError(f"Application profile is missing '{key}': {path}")
        if int(payload["profile_version"]) != 1:
            raise ValueError(f"Unsupported application profile version: {payload['profile_version']}")
        if not isinstance(payload["controls"], dict):
            raise ValueError("Application profile controls must be a mapping")
        return cls(path=path.resolve(), data=payload)

    @property
    def name(self) -> str:
        return str(self.data["application"]["name"])

    @property
    def slug(self) -> str:
        return str(self.data["application"].get("slug") or self.path.parent.name)

    @property
    def source_root(self) -> Path:
        return Path(_expanded(str(self.data["application"]["source_root"]))).resolve()

    @property
    def adapter_kind(self) -> str:
        return str(self.data["adapter"]["kind"])

    @property
    def driver_path(self) -> Path:
        value = self.data["adapter"].get("driver") or "driver.py"
        path = Path(_expanded(str(value)))
        return (path if path.is_absolute() else self.path.parent / path).resolve()

    @property
    def launch_command(self) -> list[str]:
        command = self.data["launch"].get("command") or []
        if not isinstance(command, list) or not command:
            raise ValueError("launch.command must be a non-empty list")
        return [_expanded(str(item)) for item in command]

    @property
    def launch_cwd(self) -> Path:
        value = self.data["launch"].get("cwd") or self.source_root
        return Path(_expanded(str(value))).resolve()

    @property
    def window_title_re(self) -> str:
        return str(self.data["launch"].get("window_title_re") or f".*{self.name}.*")

    @property
    def controls(self) -> dict[str, dict[str, Any]]:
        return self.data["controls"]

    @property
    def output_specs(self) -> list[dict[str, Any]]:
        outputs = self.data.get("outputs") or []
        return outputs if isinstance(outputs, list) else []
