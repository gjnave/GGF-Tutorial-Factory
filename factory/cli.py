from __future__ import annotations

import argparse
import json
from pathlib import Path

from factory.core.orchestrator import TutorialFactory
from factory.core.generic_factory import GenericTutorialFactory
from factory.onboarding.service import onboard_application
from factory.onboarding.guided import run_guided
from factory.llm.registry import resolve_llm_provider
from factory.onboarding.driver_engineer import (
    repair_and_validate_project_driver,
    upgrade_project_to_generated_driver,
    validate_driver_launch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="GGF Tutorial Factory")
    parser.add_argument("command", choices=("guided", "onboard", "audit", "rehearse", "build", "profile", "llm-status", "driver-generate", "driver-repair", "driver-validate"))
    parser.add_argument("--project", default="grizzlymax")
    parser.add_argument("--tutorial", default="first-t2va")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--name")
    parser.add_argument("--reuse-run", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--entrypoint", type=Path)
    parser.add_argument("--window-title")
    parser.add_argument("--goal")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "llm-status":
        _, status = resolve_llm_provider(root)
        print(json.dumps(status.to_dict(), indent=2))
        return 0 if status.available else 2
    if args.command == "guided":
        final = run_guided(root)
        return 0 if final is not None else 2
    if args.command == "driver-generate":
        provider, status = resolve_llm_provider(root)
        if provider is None:
            raise RuntimeError(f"Local Qwen is required to generate a project driver: {status.detail}")
        goal = args.goal or "Teach the application's main successful workflow and create a new verifiable output."
        driver_path, report = upgrade_project_to_generated_driver(root, args.project, provider, goal)
        print(f"PROJECT_DRIVER={driver_path}")
        print(json.dumps(report, indent=2))
        return 0
    if args.command == "driver-repair":
        provider, status = resolve_llm_provider(root)
        if provider is None:
            raise RuntimeError(f"Local Qwen is required to repair a project driver: {status.detail}")
        report = repair_and_validate_project_driver(root, args.project, provider, max_attempts=3)
        print(json.dumps(report, indent=2))
        return 0 if report.get("passed") else 2
    if args.command == "driver-validate":
        report = validate_driver_launch(root, args.project)
        print(json.dumps(report, indent=2))
        return 0 if report.get("passed") else 2
    if args.command == "onboard":
        if args.source is None or not args.name:
            parser.error("onboard requires --source and --name")
        project_root = onboard_application(
            root, args.source, args.name, args.project if args.project != "grizzlymax" else None,
            python_override=args.python, entrypoint_override=args.entrypoint, window_title_override=args.window_title,
        )
        print(f"APPLICATION_PROFILE={project_root}")
        return 0
    profile_path = root / "projects" / args.project / "app.yaml"
    if not profile_path.is_file():
        raise FileNotFoundError(f"Unknown Tutorial Factory project: {args.project}")
    import yaml
    profile_payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    adapter_kind = str((profile_payload.get("adapter") or {}).get("kind") or "")
    generic = int(profile_payload.get("profile_version", 0)) == 1 and adapter_kind != "grizzlymax"
    factory = GenericTutorialFactory(root) if generic else TutorialFactory(root)
    if args.command == "profile":
        if not generic:
            print(json.dumps(profile_payload, indent=2))
        else:
            print(json.dumps(factory.load_profile(args.project).data, indent=2))
        return 0
    if args.command == "audit":
        print(json.dumps(factory.audit(args.project), indent=2))
    elif args.command == "rehearse":
        print(f"REHEARSAL_RUN={factory.rehearse(args.project, args.tutorial)}")
    else:
        if generic:
            factory.build(args.project, args.tutorial, reuse_run=args.reuse_run)
        else:
            factory.build(args.project, args.tutorial)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
