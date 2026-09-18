from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from factory.onboarding.source_analyzer import SourceAnalyzer, write_analysis


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _title_pattern(title: str) -> str:
    """Keep stable title text exact while allowing a discovered version suffix to drift."""
    version = re.search(r"\b\d+(?:\.\d+){1,3}\b", title)
    if not version:
        return re.escape(title)
    prefix = title[:version.start()].rstrip()
    return re.escape(prefix) + r".*"


def onboard_application(
    factory_root: Path,
    source: Path,
    name: str,
    project: str | None = None,
    python_override: Path | None = None,
    entrypoint_override: Path | None = None,
    window_title_override: str | None = None,
) -> Path:
    analysis = SourceAnalyzer().analyze(source)
    slug = project or _slug(name)
    project_root = factory_root.resolve() / "projects" / slug
    if project_root.exists():
        raise FileExistsError(f"Project profile already exists and will not be overwritten: {project_root}")
    project_root.mkdir(parents=True)
    write_analysis(project_root / "discovery.json", analysis)
    python = python_override.resolve() if python_override else analysis.python
    entrypoint = entrypoint_override.resolve() if entrypoint_override else analysis.entrypoint
    if python is None or entrypoint is None:
        raise RuntimeError("Minimal onboarding required: the analyzer could not infer a Python runtime and entrypoint")
    title = window_title_override or analysis.window_title or name
    adapter_kind = {
        "qt": "qt-uia",
        "gradio": "browser-uia",
        "browser": "browser-uia",
        "electron": "electron-uia",
    }.get(analysis.framework, "windows-uia")
    profile: dict[str, Any] = {
        "profile_version": 1,
        "application": {
            "name": name,
            "slug": slug,
            "source_root": str(analysis.source_root),
            "framework": analysis.framework,
        },
        "adapter": {
            "kind": adapter_kind,
            "semantic_primary": True,
            "vision_fallback": True,
        },
        "launch": {
            "command": [str(python), str(entrypoint)],
            "cwd": str(entrypoint.parent),
            "window_title_re": _title_pattern(title),
            "timeout_seconds": 120,
        },
        "controls": analysis.controls,
        "outputs": [
            {"directory": str(path), "glob": "*.*"}
            for path in analysis.output_directories
        ],
        "discovery": {
            "generated_from_source": True,
            "requires_rehearsal": True,
            "source_files_scanned": analysis.evidence["source_files_scanned"],
        },
    }
    (project_root / "app.yaml").write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _write_getting_started_tutorial(project_root, name, analysis.controls, analysis.output_directories)
    return project_root


def _write_getting_started_tutorial(
    project_root: Path,
    name: str,
    controls: dict[str, dict[str, Any]],
    output_directories: list[Path],
) -> None:
    def find(*needles: str, control_type: str | None = None) -> str | None:
        for semantic_id, selector in controls.items():
            haystack = " ".join((semantic_id, str(selector.get("title") or ""))).lower()
            if all(needle.lower() in haystack for needle in needles) and (
                control_type is None or selector.get("control_type") == control_type
            ):
                return semantic_id
        return None

    primary_input = find("tags") or find("prompt") or find("lyrics") or next(
        (key for key, value in controls.items() if value.get("control_type") in {"Edit", "ComboBox"}), None
    )
    output_control = find("output", "dir") or find("output")
    run_control = find("generate") or find("run") or find("start")
    preview_control = find("play") or find("preview") or find("open")
    if preview_control and controls[preview_control].get("initially_enabled") is False:
        preview_control = None
    selected = [item for item in (primary_input, output_control, run_control, preview_control) if item]
    actions: list[dict[str, Any]] = [{"action": "launch", "chapter": 1, "offset": 0.2}]
    chapter_by_target = {primary_input: 2, output_control: 3, run_control: 3, preview_control: 4}
    chapter_slots: dict[int, int] = {}
    for target in selected:
        chapter_number = chapter_by_target.get(target, 2)
        slot = chapter_slots.get(chapter_number, 0)
        chapter_slots[chapter_number] = slot + 1
        offset = 0.8 + slot * 2.6
        hover_action = {"action": "hover", "target": target, "chapter": chapter_number, "offset": offset, "duration": 1.5, "closeup": True}
        if target == preview_control:
            hover_action["optional"] = True
        actions.append(hover_action)
        actions.append({"action": "capture", "target": target, "value": target.replace(".", "_"), "chapter": chapter_number, "offset": min(6.0, offset + 1.7)})
    if output_directories:
        actions.extend([
            *([{"action": "hover", "target": output_control, "chapter": 4, "offset": 0.8, "duration": 1.5}] if output_control else []),
            {"action": "wait_for_output", "chapter": 4, "offset": 1.0, "timeout_seconds": 2},
            {"action": "show_output", "chapter": 4, "offset": 2.0, "duration": 2.0, "open": False},
        ])
    tutorial = {
        "schema_version": 1,
        "title": f"Getting Started with {name}",
        "application": {"profile": "app.yaml"},
        "video": {"width": 1920, "height": 1080, "fps": 30, "production_style": "approved-v2"},
        "presenter": {"provider": "gary"},
        "narration": {
            "segments": [
                {"chapter": f"1. Welcome to {name}", "text": f"Welcome to {name}. This tutorial uses the real installed application and shows the main path from setup to a finished result."},
                {"chapter": "2. Main input", "text": "Start with the main creative input. Use the visible labels and defaults as your guide, and change only the settings needed for your first project."},
                {"chapter": "3. Generate and save", "text": "Review the output location before starting. The highlighted action is where the application begins its work when your inputs are ready."},
                {"chapter": "4. Find the result", "text": "Finished files are saved in the highlighted output location. Tutorial Factory also verifies a real result file before completing the tutorial."},
            ]
        },
        "actions": actions,
        "scenes": [
            {"id": "welcome", "goal": "Orient the viewer in the real application."},
            {"id": "input", "goal": "Show the primary input."},
            {"id": "generate", "goal": "Show generation and output controls."},
            {"id": "result", "goal": "Show where a finished result is found."},
        ],
    }
    tutorial_root = project_root / "tutorials" / "getting-started"
    tutorial_root.mkdir(parents=True)
    (tutorial_root / "tutorial.yaml").write_text(
        yaml.safe_dump(tutorial, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
