from __future__ import annotations

from pathlib import Path

from factory.adapters.base import ApplicationAdapter
from factory.adapters.grizzlymax.adapter import GrizzlyMaxAdapter
from factory.adapters.uia import WindowsUIAAdapter
from factory.core.profile import ApplicationProfile


def create_adapter(profile: ApplicationProfile, run_root: Path) -> ApplicationAdapter:
    kind = profile.adapter_kind.lower()
    if kind == "project-driver":
        from factory.drivers.loader import load_project_driver
        return load_project_driver(profile, run_root)
    if kind == "grizzlymax":
        return GrizzlyMaxAdapter(profile.source_root, run_root)
    if kind in {"uia", "qt-uia", "browser-uia", "electron-uia", "windows-uia"}:
        return WindowsUIAAdapter(profile, run_root)
    raise ValueError(f"Unsupported application adapter kind: {kind}")
