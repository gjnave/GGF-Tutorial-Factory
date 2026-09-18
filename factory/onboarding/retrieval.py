from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from factory.onboarding.source_analyzer import SourceAnalysis


IGNORED_PARTS = {
    ".git", ".venv", "venv", "runtime", "node_modules", "models", "checkpoints",
    "build", "dist", "__pycache__", "dependencies", "site-packages",
}


def _control_score(control_id: str, selector: dict[str, Any], important: set[str]) -> int:
    score = 100 if control_id in important else 0
    if selector.get("control_type") in {"Button", "Edit", "ComboBox", "CheckBox", "Spinner"}:
        score += 15
    haystack = " ".join(str(selector.get(key) or "") for key in (
        "source_symbol", "title", "label", "tooltip", "help_text",
    )).lower()
    score += sum(8 for word in (
        "generate", "create", "render", "export", "save", "open", "play", "preview",
        "prompt", "input", "output", "result", "start", "run",
    ) if word in haystack)
    return score


def _source_candidates(analysis: SourceAnalysis) -> list[Path]:
    paths: list[Path] = []
    if analysis.entrypoint:
        paths.append(analysis.entrypoint)
    for item in analysis.workflow.get("signal_connections") or []:
        value = item.get("source_file")
        if value:
            paths.append(Path(value))
    for selector in analysis.controls.values():
        value = selector.get("source_file")
        if value:
            paths.append(Path(value))
    root = analysis.source_root
    ranked: list[tuple[int, Path]] = []
    high_signal = re.compile(
        r"\.connect\(|def\s+(?:generate|render|export|save|run|process|start|open|play)|"
        r"output|result|finished|completed|tooltip|placeholder",
        re.IGNORECASE,
    )
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name.lower() not in IGNORED_PARTS]
        for name in files:
            if not name.lower().endswith(".py"):
                continue
            path = Path(current) / name
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hits = len(high_signal.findall(text))
            if hits:
                ranked.append((hits, path))
    paths.extend(path for _, path in sorted(ranked, key=lambda item: item[0], reverse=True)[:16])
    unique: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if resolved.is_file() and resolved not in unique:
            unique.append(resolved)
    return unique[:24]


def _excerpt(path: Path, keywords: set[str], max_chars: int) -> dict[str, Any] | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    lowered = [line.lower() for line in lines]
    matches = [
        index for index, line in enumerate(lowered)
        if any(keyword and keyword.lower() in line for keyword in keywords)
    ]
    if not matches:
        matches = list(range(min(40, len(lines))))
    selected: set[int] = set()
    for index in matches[:40]:
        selected.update(range(max(0, index - 5), min(len(lines), index + 9)))
    blocks: list[str] = []
    previous = -2
    for index in sorted(selected):
        if index != previous + 1 and blocks:
            blocks.append("...")
        blocks.append(f"{index + 1}: {lines[index]}")
        previous = index
        if sum(len(item) + 1 for item in blocks) >= max_chars:
            break
    content = "\n".join(blocks)[:max_chars]
    if not content.strip():
        return None
    return {"file": str(path), "excerpt": content}


def build_retrieval_bundle(analysis: SourceAnalysis, char_budget: int = 45000) -> dict[str, Any]:
    workflow = analysis.workflow
    important = {
        str(item) for item in (
            workflow.get("generate_control"), workflow.get("output_control"), workflow.get("result_control"),
            *(workflow.get("input_controls") or []), *(workflow.get("completion_controls") or []),
        ) if item
    }
    ordered_controls = sorted(
        analysis.controls.items(),
        key=lambda item: (_control_score(item[0], item[1], important), item[0]),
        reverse=True,
    )[:140]
    compact_controls = [
        {"id": control_id, **{
            key: value for key, value in selector.items()
            if key in {"control_type", "title", "label", "tooltip", "help_text", "values", "initially_enabled", "read_only", "container_title", "source_symbol", "source_file"}
        }}
        for control_id, selector in ordered_controls
    ]
    keywords = {
        "connect(", "output", "result", "complete", "finish", "success", "error",
        "generate", "render", "export", "save", "open", "play", "preview",
    }
    keywords.update(str(item.get("handler") or "") for item in workflow.get("signal_connections") or [])
    keywords.update(str(selector.get("source_symbol") or "") for _, selector in ordered_controls[:60])
    excerpts: list[dict[str, Any]] = []
    used = 0
    for path in _source_candidates(analysis):
        remaining = char_budget - used
        if remaining <= 1000:
            break
        item = _excerpt(path, keywords, min(9000, remaining))
        if item:
            excerpts.append(item)
            used += len(item["excerpt"])
    return {
        "retrieval_version": 1,
        "application": {
            "source_root": str(analysis.source_root),
            "framework": analysis.framework,
            "entrypoint": str(analysis.entrypoint) if analysis.entrypoint else "",
            "python": str(analysis.python) if analysis.python else "",
            "window_title": analysis.window_title or "",
            "output_directories": [str(path) for path in analysis.output_directories],
        },
        "deterministic_discovery": {
            "workflow": workflow,
            "controls": compact_controls,
            "evidence": analysis.evidence,
        },
        "relevant_source_excerpts": excerpts,
        "retrieval_stats": {
            "repository_files_sent": len(excerpts),
            "source_excerpt_characters": used,
            "controls_sent": len(compact_controls),
            "repository_sent_wholesale": False,
        },
    }


def write_retrieval_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")


def build_driver_retrieval_bundle(
    analysis: SourceAnalysis, search_terms: list[str], char_budget: int = 50000,
) -> dict[str, Any]:
    """Retrieve source specifically for driver engineering without sending the repository wholesale."""
    terms = {str(item).strip().lower() for item in search_terms if str(item).strip()}
    terms.update({
        "qapplication", "mainwindow", "qfiledialog", "clicked.connect", "outputfolder",
        "processing", "finished", "selected", "load", "save", "preview",
    })
    ranked: list[tuple[int, Path]] = []
    root = analysis.source_root.resolve()
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name.lower() not in IGNORED_PARTS]
        for name in files:
            if not name.lower().endswith(".py"):
                continue
            path = Path(current) / name
            try:
                if path.stat().st_size > 1_500_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            score = sum(min(12, text.count(term)) for term in terms if term)
            if analysis.entrypoint and path.resolve() == analysis.entrypoint.resolve():
                score += 50
            if score:
                ranked.append((score, path.resolve()))
    excerpts: list[dict[str, Any]] = []
    used = 0
    for _, path in sorted(ranked, key=lambda item: (-item[0], str(item[1])))[:24]:
        remaining = char_budget - used
        if remaining < 1000:
            break
        item = _excerpt(path, terms, min(12000, remaining))
        if item:
            excerpts.append(item)
            used += len(item["excerpt"])
    return {
        "retrieval_version": 1,
        "purpose": "application_driver_engineering",
        "application": {
            "source_root": str(root),
            "framework": analysis.framework,
            "entrypoint": str(analysis.entrypoint) if analysis.entrypoint else "",
            "python": str(analysis.python) if analysis.python else "",
            "window_title": analysis.window_title or "",
            "output_directories": [str(path) for path in analysis.output_directories],
        },
        "controls": [
            {"id": control_id, **selector}
            for control_id, selector in analysis.controls.items()
            if any(term in (control_id + " " + str(selector.get("label") or "") + " " + str(selector.get("tooltip") or "")).lower()
                   for term in terms)
        ][:120],
        "workflow": analysis.workflow,
        "requested_search_terms": sorted(terms),
        "relevant_source_excerpts": excerpts,
        "retrieval_stats": {
            "repository_files_sent": len(excerpts),
            "source_excerpt_characters": used,
            "repository_sent_wholesale": False,
        },
    }
