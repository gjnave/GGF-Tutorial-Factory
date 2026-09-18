from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STAGES = (
    "planned", "rehearsed", "captured", "verified", "narrated",
    "presenter_generated", "edited", "rendered", "qa_passed", "failed",
)


@dataclass
class RunState:
    root: Path
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.root / "run.json"

    @classmethod
    def create(cls, runs_root: Path, project: str, tutorial: str) -> "RunState":
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        run_root = runs_root / f"{stamp}_{project}_{tutorial}"
        suffix = 2
        while run_root.exists():
            run_root = runs_root / f"{stamp}_{project}_{tutorial}_{suffix:03d}"
            suffix += 1
        for rel in (
            "app", "storyboard", "capture/raw", "capture/processed", "screenshots",
            "narration", "presenter", "generated_examples", "timeline", "render",
            "qa/screenshots", "logs", "state",
        ):
            (run_root / rel).mkdir(parents=True, exist_ok=True)
        state = cls(run_root, {
            "run_id": run_root.name,
            "project": project,
            "tutorial": tutorial,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stage": "planned",
            "scenes": {},
            "artifacts": {},
            "errors": [],
        })
        state.save()
        return state

    @classmethod
    def load(cls, root: Path) -> "RunState":
        return cls(root, json.loads((root / "run.json").read_text(encoding="utf-8")))

    def set_stage(self, stage: str, **extra: Any) -> None:
        if stage not in STAGES:
            raise ValueError(f"Unknown run stage: {stage}")
        self.payload["stage"] = stage
        self.payload.update(extra)
        self.payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def artifact(self, name: str, path: Path) -> None:
        self.payload.setdefault("artifacts", {})[name] = str(path.resolve())
        self.save()

    def error(self, message: str) -> None:
        self.payload.setdefault("errors", []).append({
            "time": datetime.now(timezone.utc).isoformat(), "message": message,
        })
        self.payload["stage"] = "failed"
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.payload, indent=2), encoding="utf-8")

