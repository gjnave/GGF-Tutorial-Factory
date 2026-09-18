from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_ACTIONS = {
    "launch", "click", "double_click", "hover", "type", "select", "wait_for",
    "open_file", "capture", "verify", "wait_for_output", "show_output", "scroll_to", "set_number",
    "dismiss_dialog", "operation",
}


@dataclass(frozen=True)
class TutorialAction:
    kind: str
    target: str | None
    value: Any
    at: float | None
    duration: float
    args: dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "TutorialAction":
        if not isinstance(payload, dict):
            raise ValueError(f"Tutorial action must be a mapping: {payload!r}")
        kind = str(payload.get("action") or "").strip()
        if kind not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported tutorial action '{kind}'. Supported: {sorted(SUPPORTED_ACTIONS)}")
        target = payload.get("target")
        return cls(
            kind=kind,
            target=str(target) if target is not None else None,
            value=payload.get("value"),
            at=float(payload["at"]) if payload.get("at") is not None else None,
            duration=float(payload.get("duration", 0.8)),
            args={key: value for key, value in payload.items() if key not in {"action", "target", "value", "at", "duration"}},
        )


def load_actions(payload: list[dict[str, Any]]) -> list[TutorialAction]:
    if not isinstance(payload, list):
        raise ValueError("tutorial.actions must be a list")
    actions = [TutorialAction.from_mapping(item) for item in payload]
    scheduled = [item.at for item in actions if item.at is not None]
    if scheduled != sorted(scheduled):
        raise ValueError("Scheduled tutorial actions must be ordered by 'at' time")
    return actions
