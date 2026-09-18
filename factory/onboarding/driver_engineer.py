from __future__ import annotations

import ast
import json
import re
import shutil
import traceback
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.adapters.registry import create_adapter
from factory.core.profile import ApplicationProfile
from factory.llm.base import LLMProvider
from factory.llm.qwen_local import validate_schema
from factory.onboarding.retrieval import build_driver_retrieval_bundle, write_retrieval_bundle
from factory.onboarding.source_analyzer import SourceAnalysis, SourceAnalyzer


CAPABILITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "description", "parameters", "side_effect", "long_running", "focus_control"],
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "parameters": {"type": "array", "items": {"type": "string"}},
        "side_effect": {"type": "boolean"},
        "long_running": {"type": "boolean"},
        "focus_control": {"type": "string"},
    },
}

ARCHITECTURE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "app_understanding", "strategy", "rationale", "source_search_terms", "capabilities",
        "setup_policy", "operation_sequence", "incremental_tests", "requires_target_modification",
        "modification_reason",
    ],
    "properties": {
        "app_understanding": {"type": "string"},
        "strategy": {"type": "string", "enum": ["qt_inprocess_bridge", "qt_bridge_hybrid_uia", "uia", "win32_input"]},
        "rationale": {"type": "string"},
        "source_search_terms": {"type": "array", "items": {"type": "string"}},
        "capabilities": {"type": "array", "items": CAPABILITY_SCHEMA},
        "setup_policy": {"type": "string"},
        "operation_sequence": {"type": "array", "items": {"type": "string"}},
        "incremental_tests": {"type": "array", "items": {"type": "string"}},
        "requires_target_modification": {"type": "boolean"},
        "modification_reason": {"type": "string"},
    },
}

SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["driver_source", "implementation_summary", "known_limitations"],
    "properties": {
        "driver_source": {"type": "string"},
        "implementation_summary": {"type": "string"},
        "known_limitations": {"type": "array", "items": {"type": "string"}},
    },
}

DRIVER_REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["diagnosis", "retry_recommended", "replacements"],
    "properties": {
        "diagnosis": {"type": "string"},
        "retry_recommended": {"type": "boolean"},
        "replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["old", "new", "reason"],
                "properties": {
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


def _safe_generated_source(source: str) -> str:
    source = source.strip()
    if source.startswith("```"):
        source = re.sub(r"^```(?:python)?\s*", "", source)
        source = re.sub(r"\s*```$", "", source)
    tree = ast.parse(source)
    allowed_imports = {
        "__future__", "os", "sys", "time", "traceback", "pathlib", "typing", "json", "functools",
        "qdarktheme", "cv2", "PySide6", "factory.core.profile", "factory.drivers.qt_bridge",
        "factory.drivers.qt_bridge_host",
    }
    blocked_calls = {"eval", "exec", "compile", "__import__", "remove", "unlink", "rmdir", "rmtree", "system", "popen"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            if not (name in allowed_imports or name.startswith("app.") or name.startswith("PySide6.")):
                raise ValueError(f"Generated driver import is not allowed: {name}")
        if isinstance(node, ast.Call):
            function = node.func
            name = function.id if isinstance(function, ast.Name) else function.attr if isinstance(function, ast.Attribute) else ""
            if name.lower() in blocked_calls:
                raise ValueError(f"Generated driver contains blocked call: {name}")
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    if "create_driver" not in functions or not classes:
        raise ValueError("Generated driver must define at least one class and create_driver")
    if "run_qt_driver_host" not in source or "QtBridgeDriver" not in source:
        raise ValueError("Generated Qt driver must use the bounded Tutorial Factory Qt bridge")
    return source.rstrip() + "\n"


def propose_driver_architecture(
    provider: LLMProvider, analysis: SourceAnalysis, project_root: Path, goal: str,
) -> dict[str, Any]:
    if hasattr(provider, "timeout_seconds"):
        provider.timeout_seconds = max(int(provider.timeout_seconds), 900)
    relevant_words = {
        "face", "target", "input", "swap", "process", "output", "save", "preview",
        "media", "video", "image", "find", "record", "play",
    }
    relevant_controls = [
        (key, selector) for key, selector in analysis.controls.items()
        if any(word in (key + " " + str(selector.get("label") or "") + " " + str(selector.get("tooltip") or "")).lower()
               for word in relevant_words)
    ][:100]
    compact = {
        "application": {
            "source_root": str(analysis.source_root),
            "entrypoint": str(analysis.entrypoint) if analysis.entrypoint else "",
            "python": str(analysis.python) if analysis.python else "",
            "window_title": analysis.window_title or "",
            "output_directories": [str(path) for path in analysis.output_directories],
        },
        "framework": analysis.framework,
        "workflow": analysis.workflow,
        "controls": [
            {"id": key, **{field: value for field, value in selector.items() if field in {
                "control_type", "object_name", "label", "tooltip", "read_only", "container_title", "source_file",
            }}}
            for key, selector in relevant_controls
        ],
        "goal": goal,
        "previous_failure": "Generic UI Automation lost reliable application-window access after launch.",
    }
    system = """You are Tutorial Factory's application-driver architect. Determine the strongest deterministic automation strategy for this Python Qt app. Prefer an in-process localhost Qt bridge when source-aware widget/callback access is more reliable than UIA. The driver is permanent application automation, not a tutorial. Expose at most 10 concise user-meaningful capabilities for the requested goal. Keep every prose field under 300 characters, source_search_terms under 20 items, and incremental_tests under 10 items. Do not propose target-source edits unless unavoidable. Do not propose arbitrary machine access. Return only the required schema."""
    original_output_tokens = getattr(provider, "max_output_tokens", None)
    if original_output_tokens is not None:
        provider.max_output_tokens = min(int(original_output_tokens), 2400)
    try:
        result = provider.complete_json(
            task="driver-architecture", system=system, payload=compact, schema=ARCHITECTURE_SCHEMA,
            audit_dir=project_root / "llm" / "driver-decisions",
        )
    finally:
        if original_output_tokens is not None:
            provider.max_output_tokens = original_output_tokens
    (project_root / "driver-architecture.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def generate_project_driver(
    provider: LLMProvider, analysis: SourceAnalysis, project_root: Path, goal: str,
) -> tuple[Path, dict[str, Any]]:
    architecture_path = project_root / "driver-architecture.json"
    if architecture_path.is_file():
        architecture = json.loads(architecture_path.read_text(encoding="utf-8"))
        validate_schema(architecture, ARCHITECTURE_SCHEMA)
    else:
        architecture = propose_driver_architecture(provider, analysis, project_root, goal)
    if architecture["requires_target_modification"]:
        raise RuntimeError(
            "Qwen says target-source modification is required. It was not applied automatically: "
            + architecture["modification_reason"]
        )
    terms = list(architecture["source_search_terms"])
    terms.extend(item["name"] for item in architecture["capabilities"])
    bundle = build_driver_retrieval_bundle(analysis, terms)
    write_retrieval_bundle(project_root / "llm" / "driver-retrieval.json", bundle)
    contract = {
        "required_factory_class": "Subclass factory.drivers.qt_bridge.QtBridgeDriver",
        "required_factory_function": "create_driver(profile, run_root)",
        "required_host_entry": "if __name__ == '__main__': run_qt_driver_host(lambda app: Host(app))",
        "host_contract": {
            "constructor": "Host(app)",
            "create_window": "create_window(app) -> real QMainWindow",
            "execute": "execute(name, value, args) -> JSON-serializable result",
            "window_assignment": "The bridge assigns handler.window after create_window returns",
        },
        "rules": [
            "Use only direct source-aware Qt calls and application imports shown in evidence.",
            "The driver file runs from the project folder while cwd and sys.path include the target source root.",
            "Do not modify or delete target files.",
            "Do not launch subprocesses, shells, network clients, or arbitrary commands.",
            "Handle startup deterministically in memory, preferably by suppressing restore prompts in tutorial mode.",
            "CAPABILITIES must be a class dict keyed by architecture capability names; each value includes description, verified=False, side_effect, long_running, focus_control.",
            "Expose each capability through Host.execute.",
            "For worker-driven loads, use a nested QEventLoop/QTimer predicate wait so Qt signals continue processing.",
            "Raise clear exceptions when prerequisites are missing.",
        ],
    }
    system = """You are Tutorial Factory's bounded application-driver engineer. Generate one self-contained Python driver file using the supplied bridge contract and only source APIs evidenced in the retrieval bundle. The factory-side class must be deterministic. The host-side code runs inside the real application's Python/Qt process. Implement the requested semantic capabilities, not raw tutorial narration. The code is AST checked and any unsafe imports, deletion, shell, subprocess, eval, or exec will be rejected. Return only the schema."""
    cached_decisions = sorted(
        (project_root / "llm" / "driver-decisions").glob("*_driver-source/decision.json"),
        key=lambda path: path.stat().st_mtime, reverse=True,
    )
    if cached_decisions:
        generated = json.loads(cached_decisions[0].read_text(encoding="utf-8"))
        validate_schema(generated, SOURCE_SCHEMA)
    else:
        if hasattr(provider, "timeout_seconds"):
            provider.timeout_seconds = max(int(provider.timeout_seconds), 1800)
        generated = provider.complete_json(
            task="driver-source", system=system,
            payload={"goal": goal, "architecture": architecture, "bridge_contract": contract, "source_bundle": bundle},
            schema=SOURCE_SCHEMA, audit_dir=project_root / "llm" / "driver-decisions",
        )
    source = _safe_generated_source(generated["driver_source"])
    driver_path = project_root / "driver.py"
    if driver_path.is_file():
        history = project_root / "history" / datetime.now().strftime("%Y%m%d_%H%M%S") / "generated-driver"
        history.mkdir(parents=True, exist_ok=False)
        shutil.copy2(driver_path, history / "driver.py")
        manifest = project_root / "driver-manifest.json"
        if manifest.is_file():
            shutil.copy2(manifest, history / "driver-manifest.json")
    driver_path.write_text(source, encoding="utf-8")
    manifest = {
        "driver_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "qwen_local",
        "source_root": str(analysis.source_root),
        "source_fingerprint": analysis.evidence.get("git_commit") or analysis.evidence.get("source_fingerprint") or "",
        "strategy": architecture["strategy"],
        "rationale": architecture["rationale"],
        "goal": goal,
        "capabilities": architecture["capabilities"],
        "capability_validation": {},
        "incremental_tests": architecture["incremental_tests"],
        "implementation_summary": generated["implementation_summary"],
        "known_limitations": generated["known_limitations"],
        "target_source_modified": False,
    }
    (project_root / "driver-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return driver_path, manifest


def validate_driver_launch(factory_root: Path, project: str) -> dict[str, Any]:
    project_root = factory_root / "projects" / project
    profile = ApplicationProfile.load(project_root / "app.yaml")
    driver = create_adapter(profile, factory_root / "runs" / "_driver_validation" / project)
    report: dict[str, Any] = {"project": project, "checks": {}, "passed": False}
    try:
        driver.launch()
        state = driver.state()
        report["checks"]["launch"] = {"passed": True, "state": state}
        capture = project_root / "driver-validation-launch.png"
        driver.capture(capture)
        report["checks"]["capture"] = {"passed": capture.is_file(), "path": str(capture)}
        report["capabilities"] = driver.capabilities()
        report["passed"] = all(item["passed"] for item in report["checks"].values())
    except Exception as exc:
        report["error"] = str(exc)
        report["exception_type"] = type(exc).__name__
        report["traceback"] = traceback.format_exc()[-12000:]
    finally:
        driver.close()
    report["validated_at"] = datetime.now(timezone.utc).isoformat()
    (project_root / "driver-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _repair_source_evidence(
    project_root: Path, driver_source: str, failure: dict[str, Any], max_chars: int = 30000,
) -> list[dict[str, Any]]:
    """Retrieve small source excerpts for imported target modules implicated in a failure."""
    failure_text = json.dumps(failure, ensure_ascii=False).lower()
    startup_failure = any(
        term in failure_text for term in ("create_window", "did not become ready", "driver host exited")
    )
    payload = yaml.safe_load((project_root / "app.yaml").read_text(encoding="utf-8")) or {}
    source_root = Path(str((payload.get("application") or {}).get("source_root") or ""))
    if not source_root.is_dir():
        return []
    imports: list[tuple[str, list[str]]] = []
    for match in re.finditer(r"^\s*from\s+([A-Za-z_]\w*(?:\.\w+)*)\s+import\s+([^\n]+)", driver_source, re.MULTILINE):
        module = match.group(1)
        if module.startswith(("factory.", "PySide6.", "pathlib", "typing")):
            continue
        symbols = [part.strip().split()[0] for part in match.group(2).split(",") if part.strip()]
        imports.append((module, symbols))
    terms: set[str] = set()
    if startup_failure:
        terms.update({
            "class MainWindow", "def __init__", "load_last_workspace", "exec_()",
            "QInputDialog", "QMessageBox", "QDialog",
        })
    stopwords = {
        "driver", "factory", "error", "failure", "operation", "validation", "traceback",
        "project", "window", "source", "generated", "capability", "python", "attribute",
        "passed", "required", "result", "without", "before", "after", "calls", "failed",
    }
    failure_tokens = re.findall(r"[A-Za-z_]\w{3,}", json.dumps(failure, ensure_ascii=False))
    terms.update(token for token in failure_tokens if token.lower() not in stopwords)
    terms.update(
        part for token in failure_tokens for part in token.split("_")
        if len(part) >= 4 and part.lower() not in stopwords
    )
    priority_terms = {
        token for token in failure_tokens
        if "_" in token or any(character.isupper() for character in token[1:])
    }
    candidates: list[tuple[int, Path, int, int, list[str]]] = []
    for module, symbols in imports:
        module_path = source_root.joinpath(*module.split("."))
        paths = [module_path.with_suffix(".py")]
        if module_path.is_dir():
            paths.extend(module_path / f"{symbol}.py" for symbol in symbols)
            paths.append(module_path / "__init__.py")
        module_terms = terms | set(symbols)
        for path in dict.fromkeys(paths):
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for index, line in enumerate(lines):
                if not any(term in line for term in module_terms):
                    continue
                is_priority = any(term in line for term in priority_terms)
                padding_before, padding_after = (40, 50) if is_priority else (10, 22)
                start, end = max(0, index - padding_before), min(len(lines), index + padding_after)
                block = "\n".join(lines[start:end])
                score = sum(12 for term in priority_terms if term in block)
                score += sum(1 for term in module_terms if term in block)
                score += sum(
                    100 for term in priority_terms
                    if f"class {term}" in block or f"def {term}" in block
                )
                candidates.append((score, path, start, end, lines))
    candidates.sort(key=lambda item: (-item[0], str(item[1]).lower(), item[2]))
    evidence: list[dict[str, Any]] = []
    used = 0
    selected: list[tuple[Path, int, int]] = []
    for _score, path, start, end, lines in candidates:
        if any(path == prior_path and start < prior_end and end > prior_start for prior_path, prior_start, prior_end in selected):
            continue
        excerpt = "\n".join(f"{number + 1}: {lines[number]}" for number in range(start, end))
        if used + len(excerpt) > max_chars:
            remaining = max_chars - used
            if remaining < 500:
                break
            excerpt = excerpt[:remaining]
        evidence.append({"file": str(path), "lines": [start + 1, end], "excerpt": excerpt})
        selected.append((path, start, end))
        used += len(excerpt)
        if used >= max_chars:
            break
    return evidence


def repair_project_driver(
    provider: LLMProvider, project_root: Path, failure: dict[str, Any], max_replacements: int = 5,
) -> dict[str, Any]:
    driver_path = project_root / "driver.py"
    source = driver_path.read_text(encoding="utf-8")
    source_evidence = _repair_source_evidence(project_root, source, failure)
    contract = {
        "startup": "Host.create_window must suppress blocking startup dialogs before MainWindow construction when source evidence proves them.",
        "bridge_lifecycle": (
            "The bridge calls handler_factory(app), then Host.create_window(app), and only after create_window returns "
            "does it start the localhost HTTP server. A host-readiness timeout therefore means import/create_window "
            "blocked or failed; Host.execute has not run yet."
        ),
        "dispatch": (
            "Host(app) must initialize its semantic-operation implementation without expecting profile or run_root "
            "arguments that handler_factory does not provide. After create_window, operations must use the real QMainWindow."
        ),
        "return": "Host.execute returns JSON-serializable Python data, not a JSON-encoded string.",
        "safety": "No target edits, deletion, shell, subprocess, arbitrary network, eval, or exec.",
        "source_evidence": (
            "Use the supplied selective target-source excerpts as authoritative. Prefer a small in-memory monkeypatch "
            "of the exact blocking startup method or dialog call over retrying a synchronous constructor."
        ),
    }
    original_output_tokens = getattr(provider, "max_output_tokens", None)
    original_timeout = getattr(provider, "timeout_seconds", None)
    if original_output_tokens is not None:
        provider.max_output_tokens = min(int(original_output_tokens), 1800)
    if original_timeout is not None:
        provider.timeout_seconds = max(int(original_timeout), 1200)
    try:
        repair = provider.complete_json(
            task="driver-repair", system=(
                "You repair one generated application driver using exact bounded string replacements. "
                "Return at most 5 replacements. Each old string must appear exactly once in the supplied source. "
                "Fix only the reported failure and directly related initialization defects. "
                "For a readiness timeout, use the supplied host lifecycle and startup evidence; do not blame "
                "Host.execute because it cannot run before the server is ready. If replacements are present, "
                "retry_recommended must be true. Return only the schema."
            ),
            payload={
                "failure": failure,
                "contract": contract,
                "relevant_target_source_excerpts": source_evidence,
                "driver_source": source,
            },
            schema=DRIVER_REPAIR_SCHEMA, audit_dir=project_root / "llm" / "driver-decisions",
        )
    finally:
        if original_output_tokens is not None:
            provider.max_output_tokens = original_output_tokens
        if original_timeout is not None:
            provider.timeout_seconds = original_timeout
    replacements = list(repair.get("replacements") or [])
    if not replacements:
        return repair
    if len(replacements) > max_replacements:
        raise ValueError(f"Qwen proposed too many driver replacements: {len(replacements)}")
    patched = source
    for item in replacements:
        old, new = str(item["old"]), str(item["new"])
        if not old or patched.count(old) != 1:
            raise ValueError("Qwen driver repair old text must match exactly once")
        patched = patched.replace(old, new, 1)
    patched = _safe_generated_source(patched)
    history = project_root / "history" / datetime.now().strftime("%Y%m%d_%H%M%S") / "driver-repair"
    history.mkdir(parents=True, exist_ok=False)
    shutil.copy2(driver_path, history / "driver.py")
    driver_path.write_text(patched, encoding="utf-8")
    (project_root / "llm" / "latest-driver-repair.json").write_text(
        json.dumps(repair, indent=2), encoding="utf-8"
    )
    return repair


def _candidate_driver_profile(original: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(original))
    current_adapter = dict(updated.get("adapter") or {})
    fallback = dict(current_adapter.get("fallback") or {}) if current_adapter.get("kind") == "project-driver" else current_adapter
    updated["adapter"] = {
        "kind": "project-driver",
        "driver": "driver.py",
        "automation_strategy": manifest["strategy"],
        "fallback": fallback or {"kind": "qt-uia", "semantic_primary": True, "vision_fallback": True},
    }
    updated.setdefault("driver", {})
    updated["driver"].update({
        "manifest": "driver-manifest.json",
        "capabilities": [item["name"] for item in manifest["capabilities"]],
        "last_successful_validation": None,
    })
    return updated


def repair_and_validate_project_driver(
    factory_root: Path, project: str, provider: LLMProvider, max_attempts: int = 3,
) -> dict[str, Any]:
    """Temporarily enable, validate, and bounded-repair an existing generated driver.

    The original profile is always restored unless launch and capture validation pass.
    """
    project_root = factory_root / "projects" / project
    profile_path = project_root / "app.yaml"
    driver_path = project_root / "driver.py"
    manifest_path = project_root / "driver-manifest.json"
    if not driver_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Generated driver artifacts do not exist for project: {project}")
    original = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = _candidate_driver_profile(original, manifest)
    history = project_root / "history" / datetime.now().strftime("%Y%m%d_%H%M%S") / "driver-repair-validation"
    history.mkdir(parents=True, exist_ok=False)
    shutil.copy2(profile_path, history / "app.yaml")
    shutil.copy2(driver_path, history / "driver.py")
    reports: list[dict[str, Any]] = []
    passed = False
    profile_path.write_text(yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True), encoding="utf-8")
    try:
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            report = validate_driver_launch(factory_root, project)
            report["attempt"] = attempt
            reports.append(report)
            if report.get("passed"):
                passed = True
                candidate["driver"]["last_successful_validation"] = report["validated_at"]
                manifest["last_successful_validation"] = report["validated_at"]
                manifest["launch_validation"] = report
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                profile_path.write_text(yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True), encoding="utf-8")
                break
            if attempt >= max_attempts:
                break
            repair = repair_project_driver(provider, project_root, report)
            report["qwen_repair"] = repair
            if not repair.get("replacements"):
                break
    finally:
        if not passed:
            profile_path.write_text(yaml.safe_dump(original, sort_keys=False, allow_unicode=True), encoding="utf-8")
    series = {
        "project": project,
        "passed": passed,
        "attempts": reports,
        "profile_enabled": passed,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    (project_root / "driver-validation-series.json").write_text(json.dumps(series, indent=2), encoding="utf-8")
    return series


def upgrade_project_to_generated_driver(
    factory_root: Path, project: str, provider: LLMProvider, goal: str,
) -> tuple[Path, dict[str, Any]]:
    project_root = factory_root / "projects" / project
    profile_path = project_root / "app.yaml"
    original = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile = ApplicationProfile.load(profile_path)
    analysis = replace(
        SourceAnalyzer().analyze(profile.source_root),
        python=Path(profile.launch_command[0]), entrypoint=Path(profile.launch_command[1]),
        window_title=profile.name,
    )
    driver_path, manifest = generate_project_driver(provider, analysis, project_root, goal)
    report = repair_and_validate_project_driver(factory_root, project, provider, max_attempts=3)
    if not report.get("passed"):
        raise RuntimeError(
            "Generated driver failed bounded launch validation; the working adapter profile was restored. "
            + json.dumps(report, indent=2)[-12000:]
        )
    return driver_path, report
