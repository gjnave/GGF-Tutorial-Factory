from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import yaml

from factory.adapters.registry import create_adapter
from factory.core.profile import ApplicationProfile
from factory.llm.base import LLMProvider
from factory.llm.registry import resolve_llm_provider
from factory.onboarding.llm_planner import (
    apply_safe_selector_repairs,
    propose_rehearsal_repair,
    propose_tutorial,
    refine_tutorial,
)
from factory.onboarding.service import _title_pattern, onboard_application
from factory.onboarding.source_analyzer import SourceAnalysis, SourceAnalyzer


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _ask(prompt: str, default: str = "", input_fn: Callable[[str], str] = input) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input_fn(f"{prompt}{suffix}: ").strip()
    return answer or default


def _creative_inputs(analysis: SourceAnalysis) -> list[str]:
    inferred = list(analysis.workflow.get("input_controls") or [])
    preferred = [
        item for item in inferred
        if any(word in item.lower() for word in ("prompt", "lyrics", "tags", "description", "text", "input"))
        and not any(word in item.lower() for word in ("output", "model", "path", "console"))
    ]
    if preferred:
        return preferred[:3]
    editable = [
        item for item in inferred
        if analysis.controls.get(item, {}).get("control_type") == "Edit"
        and not any(word in item.lower() for word in ("output", "model", "console", "log"))
    ]
    if not editable:
        editable = [
            key for key, selector in analysis.controls.items()
            if selector.get("control_type") == "Edit"
            and not any(word in key.lower() for word in ("output", "model", "console", "log"))
        ]
    return editable[:3]


def _example_default(control_id: str) -> str:
    name = control_id.lower()
    if "tag" in name:
        return "uplifting electronic pop, warm synths, steady beat, bright vocals, polished mix"
    if "lyric" in name:
        return "[Verse]\nA new idea starts to glow\nStep by step we make it go\n\n[Chorus]\nBuild it clear and build it bright\nTurn the plan into the light"
    if "prompt" in name or "description" in name:
        return "Create a polished first result that clearly demonstrates the application's main workflow."
    return "Tutorial Factory example"


def build_plan(
    project: str,
    name: str,
    analysis: SourceAnalysis,
    goal: str,
    input_values: dict[str, str],
    timeout_seconds: int,
    output_directory: Path | None = None,
    llm_proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow = analysis.workflow
    generate = workflow.get("generate_control")
    if not generate:
        raise RuntimeError("The Qt analyzer could not identify the action that starts the workflow")
    resolved_output = output_directory or (analysis.output_directories[0] if analysis.output_directories else None)
    if resolved_output is None:
        raise RuntimeError("The Qt analyzer could not identify an output directory")
    reasoning = {
        "provider": "deterministic",
        "app_summary": "Deterministic Qt source discovery selected the primary workflow.",
        "workflow_why": "Selected from Qt control labels, signal connections, and callback data flow.",
        "success_condition": "A new stable output file is created after the run starts.",
        "narration": {},
    }
    if llm_proposal:
        selected = llm_proposal.get("selected_workflow") or {}
        reasoning = {
            "provider": "qwen_local",
            "app_summary": llm_proposal.get("app_summary") or reasoning["app_summary"],
            "workflow_why": selected.get("why") or reasoning["workflow_why"],
            "success_condition": selected.get("success_condition") or reasoning["success_condition"],
            "confidence": llm_proposal.get("confidence"),
            "normalization_warnings": llm_proposal.get("normalization_warnings") or [],
            "proposed_actions": selected.get("planned_actions") or [],
            "compiler_ready": bool(llm_proposal.get("compiler_ready")),
            "compiler_blockers": llm_proposal.get("compiler_blockers") or [],
            "narration": llm_proposal.get("narration") or {},
        }
    return {
        "plan_version": 1,
        "project": project,
        "application": name,
        "goal": goal,
        "framework": "qt",
        "reasoning": reasoning,
        "launch": {
            "python": str(analysis.python) if analysis.python else None,
            "entrypoint": str(analysis.entrypoint) if analysis.entrypoint else None,
            "window_title": analysis.window_title,
        },
        "workflow": {
            "inputs": [
                {"control": control, "value": value, "reason": "Read by the inferred generation handler"}
                for control, value in input_values.items()
            ],
            "generate_control": generate,
            "output_control": workflow.get("output_control"),
            "output_control_read_only": bool(
                analysis.controls.get(str(workflow.get("output_control") or ""), {}).get("read_only")
            ),
            "result_control": workflow.get("result_control"),
            "output_directory": str(resolved_output.resolve()),
            "completion": {
                "require_new_output": True,
                "newer_than": "run_start",
                "stable_seconds": 5,
                "min_bytes": 1000,
                "timeout_seconds": timeout_seconds,
            },
        },
        "safety": {
            "real_workflow_will_run": True,
            "source_files_modified_by_factory": False,
            "approved": False,
        },
    }


def plan_text(plan: dict[str, Any]) -> str:
    flow = plan["workflow"]
    reasoning = plan.get("reasoning") or {}
    lines = [
        "=" * 72,
        "PROPOSED TUTORIAL PLAN",
        "=" * 72,
        f"Application: {plan['application']}",
        f"Goal: {plan['goal']}",
        f"Framework: Python Qt",
        f"Launcher: {plan['launch']['python']} {plan['launch']['entrypoint']}",
        f"Planning: {reasoning.get('provider', 'deterministic')}",
        f"What the app does: {reasoning.get('app_summary', '')}",
        f"Why this workflow: {reasoning.get('workflow_why', '')}",
        f"Expected success: {reasoning.get('success_condition', '')}",
        f"Compiler ready: {reasoning.get('compiler_ready', True)}",
        "",
        "Real workflow:",
    ]
    proposed_actions = reasoning.get("proposed_actions") or []
    if proposed_actions:
        lines.append("  Qwen action outline:")
        for item in proposed_actions:
            target = f" {item.get('target')}" if item.get("target") else ""
            lines.append(f"    - {item.get('action')}{target}: {item.get('purpose')}")
        lines.append("  Deterministically compiled execution:")
    for index, item in enumerate(flow["inputs"], 1):
        preview = str(item["value"]).replace("\n", " / ")
        lines.append(f"  {index}. Enter {item['control']}: {preview}")
    lines.extend([
        f"  {len(flow['inputs']) + 1}. Click {flow['generate_control']}",
        f"  {len(flow['inputs']) + 2}. Wait for a NEW stable output in {flow['output_directory']}",
        f"  {len(flow['inputs']) + 3}. Verify the new file is at least {flow['completion']['min_bytes']} bytes",
    ])
    if flow.get("result_control"):
        lines.append(f"  {len(flow['inputs']) + 4}. Demonstrate the result with {flow['result_control']}")
    lines.extend([
        "  Final. Create Gary narration, render approved V2 visuals, and run QA.",
        "",
        "Rehearsal enters the example values and validates the Generate control,",
        "but it does not start the expensive workflow.",
        "=" * 72,
    ])
    return "\n".join(lines)


def compile_plan(plan: dict[str, Any]) -> dict[str, Any]:
    flow = plan["workflow"]
    inputs = list(flow["inputs"])
    narration = ((plan.get("reasoning") or {}).get("narration") or {})
    input_narration = {
        str(item.get("control")): str(item.get("text") or "")
        for item in narration.get("input_segments") or []
    }
    actions: list[dict[str, Any]] = [{"action": "launch", "chapter": 1, "offset": 0.2}]
    segments = [{
        "chapter": f"1. Welcome to {plan['application']}",
        "text": narration.get("welcome") or f"Welcome to {plan['application']}. We will perform a real workflow and verify a newly created result.",
    }]
    chapter = 2
    for item in inputs:
        label = item["control"].removeprefix("ui.").replace("_", " ").title()
        segments.append({
            "chapter": f"{chapter}. {label}",
            "text": input_narration.get(item["control"]) or f"Enter the example {label.lower()} shown here. This is meaningful input for the approved tutorial workflow.",
        })
        actions.extend([
            {"action": "hover", "target": item["control"], "chapter": chapter, "offset": 0.7, "duration": 1.0, "closeup": True},
            {"action": "type", "target": item["control"], "value": item["value"], "chapter": chapter, "offset": 2.0, "closeup": True},
            {"action": "verify", "target": item["control"], "value": item["value"], "chapter": chapter, "offset": 3.2},
        ])
        chapter += 1
    output_control = flow.get("output_control")
    segments.append({
        "chapter": f"{chapter}. Generate the result",
        "text": narration.get("generate") or "Review the output location, then click the highlighted Generate control. Tutorial Factory records the real application while it works.",
    })
    if output_control:
        actions.append(
            {"action": "hover", "target": output_control, "chapter": chapter, "offset": 0.4, "duration": 0.8, "closeup": True}
        )
        if flow.get("output_control_read_only"):
            actions.append(
                {"action": "capture", "target": output_control, "value": "output_location", "chapter": chapter, "offset": 1.1}
            )
        else:
            actions.append(
                {"action": "type", "target": output_control, "value": flow["output_directory"], "chapter": chapter, "offset": 1.1, "closeup": True}
            )
    actions.extend([
        {"action": "hover", "target": flow["generate_control"], "chapter": chapter, "offset": 2.2, "duration": 1.0, "closeup": True},
        {"action": "click", "target": flow["generate_control"], "chapter": chapter, "offset": 3.4, "duration": 0.8, "closeup": True, "unsafe": True},
        {"action": "capture", "value": "generation_started", "chapter": chapter, "offset": 4.4},
    ])
    chapter += 1
    completion = flow["completion"]
    segments.append({
        "chapter": f"{chapter}. Verify the new output",
        "text": narration.get("verify") or "The long processing wait is removed from the tutorial. The factory accepts only a new, stable output created after this run started.",
    })
    actions.extend([
        {"action": "wait_for_output", "chapter": chapter, "offset": 0.4, **completion, "require_new": True},
        {"action": "dismiss_dialog", "value": "OK", "chapter": chapter, "offset": 1.0, "duration": 0.8, "optional": True},
    ])
    result_control = flow.get("result_control")
    if result_control:
        actions.extend([
            {"action": "wait_for", "target": result_control, "chapter": chapter, "offset": 1.5, "timeout_seconds": 30},
            {"action": "hover", "target": result_control, "chapter": chapter, "offset": 2.1, "duration": 1.0, "closeup": True},
            {"action": "click", "target": result_control, "chapter": chapter, "offset": 3.3, "duration": 0.8, "closeup": True, "optional": True},
        ])
    actions.extend([
        {"action": "capture", "value": "new_output_verified", "chapter": chapter, "offset": 4.2},
        {"action": "show_output", "chapter": chapter, "offset": 4.8, "duration": 2.0, "open": False},
    ])
    segments.append({
        "chapter": f"{chapter + 1}. Finished result",
        "text": narration.get("finished") or "The real newly created result is verified and included in the finished tutorial. The final MP4 and QA report are saved together in the run folder.",
    })
    return {
        "schema_version": 1,
        "title": f"{plan['application']}: {plan['goal']}",
        "application": {"profile": "app.yaml"},
        "video": {"width": 1920, "height": 1080, "fps": 30, "production_style": "approved-v2"},
        "presenter": {"provider": "gary"},
        "narration": {"segments": segments},
        "actions": actions,
        "scenes": [{"id": f"chapter-{index}", "goal": item["chapter"]} for index, item in enumerate(segments, 1)],
        "approved_plan": "approved-plan.json",
    }


def validate_controls(
    factory_root: Path, project: str, control_ids: list[str],
    input_fn: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    profile = ApplicationProfile.load(factory_root / "projects" / project / "app.yaml")
    adapter = create_adapter(profile, factory_root / "runs" / "_validation" / project)
    report: dict[str, Any] = {"project": project, "controls": {}, "passed": False}
    try:
        adapter.launch()
        if bool(getattr(adapter, "launch_attention_required", False)):
            titles = list(getattr(adapter, "blocking_window_titles", []))
            print("\nApplication setup/attention is required before validation.")
            print("Open window(s): " + ", ".join(titles))
            if input_fn is None:
                report["attention_required"] = titles
                return report
            options = adapter.attention_options() if hasattr(adapter, "attention_options") else []
            handled = False
            if options:
                print("Choose the visible application dialog action:")
                for index, option in enumerate(options, 1):
                    print(f"  {index}. {option}")
                print("  M. Handle the dialog manually in the application")
                choice = _ask("Dialog choice", "M", input_fn)
                if choice.isdigit():
                    selected = int(choice)
                    if selected < 1 or selected > len(options):
                        raise ValueError("Dialog choice is out of range")
                    adapter.choose_attention_option(options[selected - 1])
                    report["attention_choice"] = options[selected - 1]
                    handled = True
                else:
                    named = next((option for option in options if option.lower() == choice.lower()), None)
                    if named:
                        adapter.choose_attention_option(named)
                        report["attention_choice"] = named
                        handled = True
            if not handled:
                input_fn(
                    "Complete the visible dialog in the application itself, then press Enter here (pressing Enter alone does not answer the dialog): "
                )
            adapter.reacquire_application_window()
        if hasattr(adapter, "focus_window"):
            adapter.focus_window()
        report["window_title"] = adapter.state().get("window_title")
        for control_id in control_ids:
            try:
                widget = adapter.widget(control_id)
                report["controls"][control_id] = {
                    "passed": True,
                    "name": widget.get("name"),
                    "value": widget.get("value"),
                    "enabled": widget.get("enabled"),
                    "control_type": widget.get("control_type"),
                    "rect": widget.get("rect"),
                }
            except Exception as exc:
                report["controls"][control_id] = {"passed": False, "error": str(exc)}
        report["passed"] = all(item["passed"] for item in report["controls"].values())
        return report
    finally:
        adapter.close()


def _prepare_clean_resume_output(project_root: Path, input_fn: Callable[[str], str]) -> None:
    plan_path = project_root / "approved-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    old_output = Path(plan["workflow"]["output_directory"]).resolve()
    if not old_output.is_dir() or not any(path.is_file() for path in old_output.glob("*.*")):
        return
    default = old_output.with_name(old_output.name + "-new")
    new_output = Path(_ask("Previous output folder is not clean. New output folder", str(default), input_fn)).resolve()
    if new_output.exists() and any(path.is_file() for path in new_output.glob("*.*")):
        raise RuntimeError(f"The replacement output folder is not clean: {new_output}")
    history = project_root / "history" / datetime.now().strftime("%Y%m%d_%H%M%S")
    history.mkdir(parents=True, exist_ok=False)
    for relative in ("approved-plan.json", "approved-plan.txt", "app.yaml", "tutorials/getting-started/tutorial.yaml"):
        source = project_root / relative
        destination = history / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    plan["workflow"]["output_directory"] = str(new_output)
    for item in plan["workflow"]["inputs"]:
        if Path(str(item["value"])).resolve() == old_output:
            item["value"] = str(new_output)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (project_root / "approved-plan.txt").write_text(plan_text(plan) + "\n", encoding="utf-8")
    profile_path = project_root / "app.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile["outputs"] = [{"directory": str(new_output), "glob": "*.*"}]
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tutorial_path = project_root / "tutorials" / "getting-started" / "tutorial.yaml"
    tutorial_path.write_text(yaml.safe_dump(compile_plan(plan), sort_keys=False, allow_unicode=True), encoding="utf-8")


def _refresh_incomplete_profile(project_root: Path, analysis: SourceAnalysis) -> None:
    history = project_root / "history" / datetime.now().strftime("%Y%m%d_%H%M%S")
    history.mkdir(parents=True, exist_ok=False)
    for name in ("app.yaml", "discovery.json", "control-validation.json"):
        source = project_root / name
        if source.is_file():
            shutil.copy2(source, history / name)
    profile_path = project_root / "app.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if analysis.window_title:
        profile["launch"]["window_title_re"] = _title_pattern(analysis.window_title)
    profile["launch"]["timeout_seconds"] = max(int(profile["launch"].get("timeout_seconds", 0)), 120)
    profile["controls"] = analysis.controls
    if analysis.output_directories:
        profile["outputs"] = [{"directory": str(path), "glob": "*.*"} for path in analysis.output_directories]
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (project_root / "discovery.json").write_text(json.dumps(analysis.to_dict(), indent=2), encoding="utf-8")


def _latest_failed_run(factory_root: Path, project: str) -> Path | None:
    candidates = list((factory_root / "runs").glob(f"*_{project}_getting-started*"))
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def _rehearse_with_repair(
    factory: Any,
    factory_root: Path,
    project: str,
    provider: LLMProvider | None,
) -> Path:
    try:
        return factory.rehearse(project, "getting-started")
    except Exception as exc:
        if provider is None:
            raise
        print("\nRehearsal failed. Asking local Qwen for a bounded selector repair...")
        project_root = factory_root / "projects" / project
        repair = propose_rehearsal_repair(
            provider,
            project_root=project_root,
            error=exc,
            failed_run=_latest_failed_run(factory_root, project),
        )
        repaired = apply_safe_selector_repairs(project_root, repair)
        if repaired < 1:
            raise RuntimeError(f"Rehearsal failed and Qwen proposed no safe applicable selector repair: {exc}") from exc
        print(f"Applied {repaired} schema-validated selector repair(s); retrying rehearsal once...")
        return factory.rehearse(project, "getting-started")


def run_guided(factory_root: Path, input_fn: Callable[[str], str] = input) -> Path | None:
    print("\nGGF Tutorial Factory - Guided Qt Tutorial\n")
    source = Path(_ask("Source folder", input_fn=input_fn)).resolve()
    analysis = SourceAnalyzer().analyze(source)
    if analysis.framework != "qt":
        raise RuntimeError(f"This milestone supports Python Qt/PySide/PyQt only; detected {analysis.framework}")
    name = _ask("Application name", analysis.window_title or source.name, input_fn)
    project = _ask("Short project id", _slug(name), input_fn)
    project_root = factory_root / "projects" / project
    provider, llm_status = resolve_llm_provider(factory_root)
    if provider:
        print(
            f"Local Qwen reasoning ready: {llm_status.model} at {llm_status.endpoint} "
            f"(context {llm_status.context_limit or 'unknown'}, structured via {llm_status.structured_json})."
        )
    else:
        print(f"Local Qwen unavailable; deterministic fallback remains active. {llm_status.detail}")
    approved_path = project_root / "approved-plan.json"
    if project_root.exists():
        if approved_path.is_file():
            resume = _ask("Approved project already exists. Resume rehearsal and build? (Y/N)", "Y", input_fn).lower()
            if not resume.startswith("y"):
                return None
            _prepare_clean_resume_output(project_root, input_fn)
            from factory.core.generic_factory import GenericTutorialFactory
            factory = GenericTutorialFactory(factory_root)
            print("\nRehearsing approved tutorial (Generate will not run)...")
            rehearsal = _rehearse_with_repair(factory, factory_root, project, provider)
            print(f"REHEARSAL_PASSED={rehearsal}")
            print("\nExecuting real workflow and building final tutorial...")
            final = factory.build(project, "getting-started")
            print("\nSUCCESS")
            print(f"FINAL_MP4={final}")
            print(f"OUTPUT_FOLDER={final.parent}")
            if _ask("Open Output Folder? (Y/N)", "Y", input_fn).lower().startswith("y"):
                os.startfile(final.parent)
            return final
        resume = _ask("Incomplete discovery exists. Resume onboarding? (Y/N)", "Y", input_fn).lower()
        if not resume.startswith("y"):
            return None
        existing = ApplicationProfile.load(project_root / "app.yaml")
        command = existing.launch_command
        analysis = replace(
            analysis, python=Path(command[0]), entrypoint=Path(command[1]),
            window_title=analysis.window_title or name,
        )
        _refresh_incomplete_profile(project_root, analysis)
    else:
        python_override = analysis.python
        runtime_ok = False
        if python_override and python_override.is_file():
            runtime_ok = subprocess.run(
                [str(python_override), "-c", "import importlib.util,sys; sys.exit(0 if any(importlib.util.find_spec(x) for x in ('PySide6','PyQt6','PyQt5')) else 1)"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ).returncode == 0
        if not runtime_ok:
            python_override = Path(_ask("Python executable containing the app's Qt dependency", input_fn=input_fn)).resolve()
        entrypoint_override = analysis.entrypoint
        if entrypoint_override is None:
            entrypoint_override = Path(_ask("Qt application entrypoint", input_fn=input_fn)).resolve()
        title_override = analysis.window_title or _ask("Application window title", name, input_fn)
        analysis = replace(analysis, python=python_override, entrypoint=entrypoint_override, window_title=title_override)
        project_root = onboard_application(
            factory_root, source, name, project,
            python_override=python_override, entrypoint_override=entrypoint_override, window_title_override=title_override,
        )
    llm_proposal: dict[str, Any] | None = None
    if provider:
        print("\nLocal Qwen is interpreting the compact source/control/callback evidence...")
        try:
            llm_proposal = propose_tutorial(provider, analysis, name, project_root)
            unresolved = [str(item) for item in llm_proposal.get("unresolved_questions") or [] if str(item).strip()]
            if unresolved:
                print("\nQwen needs only these unresolved user decisions:")
                answers = {question: _ask(question, input_fn=input_fn) for question in unresolved}
                llm_proposal = refine_tutorial(provider, analysis, name, project_root, llm_proposal, answers)
            print("Qwen proposed a tutorial goal and workflow. The proposal will be shown for approval.")
        except Exception as exc:
            failure = {
                "failed_at": datetime.now().astimezone().isoformat(),
                "error": str(exc),
                "fallback": "deterministic",
            }
            llm_root = project_root / "llm"
            llm_root.mkdir(parents=True, exist_ok=True)
            (llm_root / "planning-failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
            print(f"Qwen planning failed; continuing with deterministic onboarding: {exc}")
    goal = str((llm_proposal or {}).get("recommended_goal") or f"Create a first result with {name}")
    workflow = dict(analysis.workflow)
    selected_workflow = (llm_proposal or {}).get("selected_workflow") or {}
    if llm_proposal and not llm_proposal.get("compiler_ready", False):
        print("Qwen's preferred workflow needs capabilities outside the current deterministic compiler.")
        for blocker in llm_proposal.get("compiler_blockers") or []:
            print(f"  - {blocker}")
        print("The deterministic fallback will ask for a directly executable workflow instead.")
        selected_workflow = {}
    if selected_workflow:
        for key in ("generate_control", "output_control", "result_control"):
            if selected_workflow.get(key):
                workflow[key] = selected_workflow[key]
        proposed_inputs = [
            item.get("control") for item in selected_workflow.get("input_controls") or [] if item.get("control")
        ]
        if proposed_inputs:
            workflow["input_controls"] = proposed_inputs
        analysis = replace(analysis, workflow=workflow)
    manually_selected_action = False
    if not workflow.get("generate_control"):
        candidates = [
            key for key, selector in analysis.controls.items()
            if selector.get("control_type") == "Button"
            and any(word in key.lower() for word in ("process", "generate", "render", "export", "save", "batch", "swap", "start", "run"))
        ]
        if not candidates:
            candidates = [key for key, selector in analysis.controls.items() if selector.get("control_type") == "Button"]
        print("\nThe source does not uniquely identify the workflow action.")
        for index, candidate in enumerate(candidates, 1):
            label = analysis.controls[candidate].get("label") or analysis.controls[candidate].get("title") or ""
            print(f"  {index}. {candidate}" + (f" - {label}" if label else ""))
        choice = int(_ask("Which action should this tutorial run", "1", input_fn))
        if choice < 1 or choice > len(candidates):
            raise ValueError("Workflow action selection is out of range")
        workflow["generate_control"] = candidates[choice - 1]
        analysis = replace(analysis, workflow=workflow)
        manually_selected_action = True
    if manually_selected_action:
        candidates = [
            key for key, selector in analysis.controls.items()
            if selector.get("control_type") == "Edit"
            and not any(word in key.lower() for word in ("search", "seek", "console", "log", "output"))
        ]
        print("\nSelect any text/path inputs required before that action.")
        for index, candidate in enumerate(candidates, 1):
            label = analysis.controls[candidate].get("label") or analysis.controls[candidate].get("help_text") or ""
            print(f"  {index}. {candidate}" + (f" - {label}" if label else ""))
        raw = _ask("Input numbers separated by commas, or 0 for none", "0", input_fn)
        indexes = [] if raw == "0" else [int(item.strip()) for item in raw.split(",") if item.strip()]
        if any(index < 1 or index > len(candidates) for index in indexes):
            raise ValueError("Input control selection is out of range")
        creative = [candidates[index - 1] for index in indexes]
    else:
        creative = list(workflow.get("input_controls") or []) if selected_workflow else _creative_inputs(analysis)
        creative = [item for item in creative if item in analysis.controls][:3]
    primary_required = creative + [str(workflow.get("generate_control"))]
    optional_controls = [item for item in (workflow.get("output_control"), workflow.get("result_control")) if item]
    required = list(dict.fromkeys(primary_required + optional_controls))
    print("\nLaunching the application to validate inferred controls...")
    validation = validate_controls(factory_root, project, list(dict.fromkeys(required)), input_fn=input_fn)
    failed_primary = [
        key for key in primary_required
        if not validation["controls"].get(key, {}).get("passed", False)
    ]
    failed_optional = [
        key for key in optional_controls
        if not validation["controls"].get(key, {}).get("passed", False)
    ]
    validation["required_controls"] = list(dict.fromkeys(primary_required))
    validation["optional_controls"] = list(dict.fromkeys(optional_controls))
    validation["optional_failures"] = failed_optional
    validation["passed"] = not failed_primary
    (project_root / "control-validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    if failed_primary:
        raise RuntimeError("Required controls could not be validated: " + ", ".join(failed_primary))
    if failed_optional:
        print("Optional demonstration controls were not visible and will be omitted: " + ", ".join(failed_optional))
        for key in ("output_control", "result_control"):
            if workflow.get(key) in failed_optional:
                workflow[key] = None
        analysis = replace(analysis, workflow=workflow)
    proposed_values = {
        str(item.get("control")): str(item.get("example_value") or "")
        for item in selected_workflow.get("input_controls") or []
    }
    values = {}
    for control in creative:
        proposed_value = proposed_values.get(control, "")
        values[control] = proposed_value or _ask(f"Example value for {control}", _example_default(control), input_fn)
    inferred_output = str(selected_workflow.get("output_directory") or "")
    output_control = workflow.get("output_control")
    if output_control and analysis.controls.get(output_control, {}).get("read_only"):
        live_value = str(validation["controls"].get(output_control, {}).get("value") or "").strip()
        if live_value and Path(live_value).is_absolute():
            inferred_output = live_value
    if not inferred_output:
        inferred_output = str(analysis.output_directories[0]) if analysis.output_directories else ""
    if not inferred_output:
        output_directory = Path(_ask("Folder where this workflow creates its result", inferred_output, input_fn)).resolve()
    else:
        output_directory = Path(inferred_output).resolve()
    profile_path = project_root / "app.yaml"
    profile_payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile_payload["outputs"] = [{"directory": str(output_directory), "glob": "*.*"}]
    profile_path.write_text(yaml.safe_dump(profile_payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    timeout = 3600
    plan = build_plan(
        project, name, analysis, goal, values, timeout,
        output_directory=output_directory, llm_proposal=llm_proposal,
    )
    while True:
        print("\n" + plan_text(plan))
        decision = _ask("Approve, edit answers, or reject? (A/E/R)", "A", input_fn).lower()
        if decision.startswith("a"):
            break
        if decision.startswith("r"):
            print(f"Plan rejected. Discovery remains at: {project_root}")
            return None
        plan["goal"] = _ask("Tutorial goal", str(plan["goal"]), input_fn)
        for item in plan["workflow"]["inputs"]:
            item["value"] = _ask(f"Example value for {item['control']}", str(item["value"]), input_fn)
        plan["workflow"]["completion"]["timeout_seconds"] = int(_ask(
            "Maximum generation wait in seconds", str(plan["workflow"]["completion"]["timeout_seconds"]), input_fn
        ))
    safe = _ask("Approve running this real workflow now? (Y/N)", "N", input_fn).lower()
    if not safe.startswith("y"):
        print(f"Approved plan saved, but real execution was not authorized: {project_root}")
        return None
    plan["safety"]["approved"] = True
    (project_root / "approved-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    (project_root / "approved-plan.txt").write_text(plan_text(plan) + "\n", encoding="utf-8")
    tutorial_root = project_root / "tutorials" / "getting-started"
    tutorial_root.mkdir(parents=True, exist_ok=True)
    (tutorial_root / "tutorial.yaml").write_text(yaml.safe_dump(compile_plan(plan), sort_keys=False, allow_unicode=True), encoding="utf-8")

    from factory.core.generic_factory import GenericTutorialFactory
    factory = GenericTutorialFactory(factory_root)
    print("\nRehearsing approved tutorial (Generate will not run)...")
    rehearsal = _rehearse_with_repair(factory, factory_root, project, provider)
    print(f"REHEARSAL_PASSED={rehearsal}")
    print("\nExecuting real workflow and building final tutorial...")
    final = factory.build(project, "getting-started")
    print("\nSUCCESS")
    print(f"FINAL_MP4={final}")
    print(f"OUTPUT_FOLDER={final.parent}")
    if _ask("Open Output Folder? (Y/N)", "Y", input_fn).lower().startswith("y"):
        os.startfile(final.parent)
    return final
