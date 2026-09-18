from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from factory.llm.base import LLMProvider
from factory.onboarding.retrieval import build_retrieval_bundle, write_retrieval_bundle
from factory.onboarding.source_analyzer import SourceAnalysis


STRING = {"type": "string"}
STRING_ARRAY = {"type": "array", "items": STRING}

INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "control": STRING,
        "example_value": STRING,
        "reason": STRING,
    },
    "required": ["control", "example_value", "reason"],
}

PLANNED_ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "launch", "click", "hover", "type", "select", "wait_for", "open_file",
                "capture", "verify", "wait_for_output", "show_output",
            ],
        },
        "target": STRING,
        "value": STRING,
        "purpose": STRING,
        "unsafe": {"type": "boolean"},
        "optional": {"type": "boolean"},
    },
    "required": ["action", "target", "value", "purpose", "unsafe", "optional"],
}

PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "app_summary": STRING,
        "recommended_goal": STRING,
        "confidence": {"type": "number"},
        "selected_workflow": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": STRING,
                "why": STRING,
                "generate_control": STRING,
                "input_controls": {"type": "array", "items": INPUT_SCHEMA},
                "output_control": STRING,
                "output_directory": STRING,
                "result_control": STRING,
                "success_condition": STRING,
                "safety_notes": STRING_ARRAY,
                "tutorial_steps": STRING_ARRAY,
                "planned_actions": {"type": "array", "items": PLANNED_ACTION_SCHEMA},
            },
            "required": [
                "title", "why", "generate_control", "input_controls", "output_control",
                "output_directory", "result_control", "success_condition", "safety_notes", "tutorial_steps",
                "planned_actions",
            ],
        },
        "alternative_workflows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": STRING, "description": STRING},
                "required": ["title", "description"],
            },
        },
        "unresolved_questions": STRING_ARRAY,
        "narration": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "welcome": STRING,
                "input_segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"control": STRING, "text": STRING},
                        "required": ["control", "text"],
                    },
                },
                "generate": STRING,
                "verify": STRING,
                "finished": STRING,
            },
            "required": ["welcome", "input_segments", "generate", "verify", "finished"],
        },
    },
    "required": [
        "app_summary", "recommended_goal", "confidence", "selected_workflow",
        "alternative_workflows", "unresolved_questions", "narration",
    ],
}

REPAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "diagnosis": STRING,
        "retry_recommended": {"type": "boolean"},
        "selector_repairs": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "control": STRING,
                    "title": STRING,
                    "auto_id": STRING,
                    "object_name": STRING,
                    "control_type": {
                        "type": "string",
                        "enum": ["", "Button", "Edit", "ComboBox", "Spinner", "CheckBox", "Text", "List", "TabItem", "MenuItem", "Slider"],
                    },
                    "found_index": {"type": "integer"},
                    "rationale": STRING,
                },
                "required": [
                    "control", "title", "auto_id", "object_name", "control_type", "found_index", "rationale",
                ],
            },
        },
    },
    "required": ["diagnosis", "retry_recommended", "selector_repairs"],
}


def _normalize_proposal(raw: dict[str, Any], analysis: SourceAnalysis) -> dict[str, Any]:
    proposal = json.loads(json.dumps(raw))
    selected = proposal["selected_workflow"]
    warnings: list[str] = []
    controls = analysis.controls
    generate = selected.get("generate_control")
    if generate not in controls or controls[generate].get("control_type") != "Button":
        fallback = analysis.workflow.get("generate_control") or ""
        warnings.append(f"Qwen generate control rejected: {generate!r}; deterministic fallback: {fallback!r}")
        selected["generate_control"] = fallback
    normalized_inputs = []
    for item in selected.get("input_controls") or []:
        control = item.get("control")
        if (
            control in controls
            and controls[control].get("control_type") in {"Edit", "ComboBox", "CheckBox", "Spinner"}
            and not controls[control].get("read_only")
        ):
            normalized_inputs.append(item)
        else:
            warnings.append(f"Qwen input control rejected: {control!r}")
    selected["input_controls"] = normalized_inputs
    output_control = selected.get("output_control") or ""
    if output_control and (
        output_control not in controls or controls[output_control].get("control_type") != "Edit"
    ):
        warnings.append(f"Qwen output_control rejected: {output_control!r}")
        selected["output_control"] = str(analysis.workflow.get("output_control") or "")
    result_control = selected.get("result_control") or ""
    if result_control and (
        result_control not in controls
        or controls[result_control].get("control_type") != "Button"
        or result_control == selected.get("generate_control")
    ):
        warnings.append(f"Qwen result_control rejected: {result_control!r}")
        fallback_result = analysis.workflow.get("result_control") or ""
        selected["result_control"] = fallback_result if fallback_result != selected.get("generate_control") else ""
    output = selected.get("output_directory") or ""
    if output:
        try:
            candidate = Path(output)
            if not candidate.is_absolute():
                candidate = analysis.source_root / candidate
            selected["output_directory"] = str(candidate.resolve())
        except OSError:
            selected["output_directory"] = ""
    if not selected.get("output_directory") and analysis.output_directories:
        selected["output_directory"] = str(analysis.output_directories[0])
    action_names = set(PLANNED_ACTION_SCHEMA["properties"]["action"]["enum"])
    targetless = {"launch", "capture", "wait_for_output", "show_output"}
    normalized_actions = []
    for item in selected.get("planned_actions") or []:
        item = dict(item)
        action = str(item.get("action") or "")
        target = str(item.get("target") or "")
        if action not in action_names:
            warnings.append(f"Qwen action rejected: {action!r}")
            continue
        if action not in targetless and target not in controls:
            warnings.append(f"Qwen action target rejected: {action} {target!r}")
            continue
        if action == "launch":
            item["target"] = ""
            item["value"] = ""
        if action == "click" and target == selected.get("generate_control"):
            item["unsafe"] = True
        if action == "wait_for_output":
            item["target"] = ""
            item["value"] = str(selected.get("output_directory") or "")
        normalized_actions.append(item)
    selected["planned_actions"] = normalized_actions
    compiler_blockers: list[str] = []
    generate_seen = False
    if not selected.get("generate_control"):
        compiler_blockers.append("No valid output-generating control was selected.")
    for item in normalized_actions:
        if item["action"] == "click" and item.get("target") == selected.get("generate_control"):
            generate_seen = True
            continue
        if not generate_seen and (
            item["action"] == "open_file" or (item["action"] == "click" and item.get("target"))
        ):
            compiler_blockers.append(
                f"Pre-generation {item['action']} on {item.get('target')} requires navigation not supported by the current compiler."
            )
    if normalized_actions and not generate_seen:
        compiler_blockers.append("The action outline does not click the selected generation control.")
    normalized_questions = []
    for question in proposal.get("unresolved_questions") or []:
        lower = str(question).lower()
        user_decision = any(word in lower for word in (
            "tutorial", "teach", "workflow", "demonstrate", "example", "prompt", "input", "media", "file", "path", "loaded", "source", "safe", "acceptable",
        ))
        technical_check = any(word in lower for word in (
            "gpu", "vram", "cuda", "installed", "environment", "dependency", "file dialog", "model loaded",
        ))
        if user_decision and not technical_check:
            normalized_questions.append(str(question))
        else:
            warnings.append(f"Qwen technical/non-user question deferred to deterministic validation: {question!r}")
    proposal["unresolved_questions"] = normalized_questions
    proposal["compiler_ready"] = not compiler_blockers
    proposal["compiler_blockers"] = compiler_blockers
    proposal["normalization_warnings"] = warnings
    return proposal


def propose_tutorial(
    provider: LLMProvider,
    analysis: SourceAnalysis,
    application_name: str,
    project_root: Path,
) -> dict[str, Any]:
    llm_root = project_root / "llm"
    bundle = build_retrieval_bundle(analysis)
    write_retrieval_bundle(llm_root / "retrieval.json", bundle)
    raw = provider.complete_json(
        task="onboarding_plan",
        system=(
            "You are the reasoning layer for a deterministic Windows tutorial factory. Analyze only the supplied "
            "compact Qt discovery and source excerpts. Propose one safe, meaningful beginner tutorial that produces "
            "a real new output. Use only control ids present in deterministic_discovery.controls. Do not invent UI "
            "execution details, timestamps, files, or selectors. Prefer the actual signal/callback and output evidence. "
            "planned_actions must use the supplied action vocabulary and existing semantic control ids. Choose a workflow "
            "that the deterministic executor can rehearse from the initially launched main window and that creates a new "
            "verifiable output; avoid workflows dominated by native file dialogs or controls from an unopened secondary "
            "window. unresolved_questions may contain only user intent, example-input, or safety decisions that cannot be "
            "deduced from source; do not ask the user technical questions that rehearsal can answer. Return the proposal "
            "by calling the required function. Narration must be concise spoken tutorial language."
        ),
        payload={"application_name": application_name, "retrieval": bundle},
        schema=PROPOSAL_SCHEMA,
        audit_dir=llm_root / "decisions",
    )
    normalized = _normalize_proposal(raw, analysis)
    (llm_root / "proposal.json").write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return normalized


def refine_tutorial(
    provider: LLMProvider,
    analysis: SourceAnalysis,
    application_name: str,
    project_root: Path,
    proposal: dict[str, Any],
    answers: dict[str, str],
) -> dict[str, Any]:
    bundle = json.loads((project_root / "llm" / "retrieval.json").read_text(encoding="utf-8"))
    raw = provider.complete_json(
        task="onboarding_plan_refinement",
        system=(
            "Revise the existing Tutorial Factory proposal using the user's answers. Keep all controls and planned "
            "actions grounded in the supplied deterministic discovery. Use the exact response schema, retain a real "
            "new-output success condition, and leave unresolved_questions empty unless a material user decision still "
            "cannot be made. Return the revised proposal through the required function."
        ),
        payload={
            "application_name": application_name,
            "retrieval": bundle,
            "existing_proposal": proposal,
            "user_answers": answers,
        },
        schema=PROPOSAL_SCHEMA,
        audit_dir=project_root / "llm" / "decisions",
    )
    normalized = _normalize_proposal(raw, analysis)
    normalized["onboarding_answers"] = answers
    (project_root / "llm" / "proposal.json").write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return normalized


def propose_rehearsal_repair(
    provider: LLMProvider,
    *,
    project_root: Path,
    error: Exception,
    failed_run: Path | None,
) -> dict[str, Any]:
    profile = yaml.safe_load((project_root / "app.yaml").read_text(encoding="utf-8")) or {}
    plan = json.loads((project_root / "approved-plan.json").read_text(encoding="utf-8"))
    failure_context: dict[str, Any] = {
        "error_type": type(error).__name__,
        "error": str(error),
        "controls": profile.get("controls") or {},
        "approved_plan": plan,
        "failed_run": str(failed_run) if failed_run else "",
    }
    if failed_run:
        for relative in ("run.json", "timeline/actions.json"):
            path = failed_run / relative
            if path.is_file():
                failure_context[relative] = json.loads(path.read_text(encoding="utf-8"))
    repair = provider.complete_json(
        task="rehearsal_repair",
        system=(
            "Diagnose a failed deterministic Qt tutorial rehearsal. You may only propose selector-field repairs for "
            "existing semantic controls. Never propose commands, code execution, application actions, output reuse, "
            "or safety bypasses. Leave unused selector values empty and found_index at -1. Recommend retry only when "
            "the evidence supports a bounded selector correction. Return the repair through the required function."
        ),
        payload=failure_context,
        schema=REPAIR_SCHEMA,
        audit_dir=project_root / "llm" / "decisions",
    )
    path = project_root / "llm" / "latest-repair.json"
    path.write_text(json.dumps(repair, indent=2, ensure_ascii=False), encoding="utf-8")
    return repair


def apply_safe_selector_repairs(project_root: Path, repair: dict[str, Any]) -> int:
    if not repair.get("retry_recommended"):
        return 0
    path = project_root / "app.yaml"
    profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    controls = profile.get("controls") or {}
    pending: list[tuple[str, dict[str, Any]]] = []
    allowed = {"title", "auto_id", "object_name", "control_type", "found_index"}
    for item in repair.get("selector_repairs") or []:
        control = str(item.get("control") or "")
        if control not in controls:
            continue
        updates: dict[str, Any] = {}
        for key in allowed:
            value = item.get(key)
            if key == "found_index":
                if isinstance(value, int) and value >= 0:
                    updates[key] = value
            elif isinstance(value, str) and value.strip():
                updates[key] = value.strip()
        if updates:
            pending.append((control, updates))
    if not pending:
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    history = project_root / "history" / f"{stamp}_qwen-selector-repair"
    history.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, history / "app.before.yaml")
    (history / "repair.json").write_text(json.dumps(repair, indent=2), encoding="utf-8")
    for control, updates in pending:
        controls[control].update(updates)
        if any(key in updates for key in ("title", "auto_id", "object_name")):
            controls[control].pop("found_index", None)
        elif "found_index" in updates:
            for key in ("title", "auto_id", "object_name"):
                if not controls[control].get(key):
                    controls[control].pop(key, None)
    path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return len(pending)
