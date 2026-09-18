from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from factory.actions.schema import TutorialAction
from factory.adapters.base import ApplicationAdapter
from factory.automation.windows import WindowsAutomation


class TutorialActionExecutor:
    def __init__(
        self,
        adapter: ApplicationAdapter,
        automation: WindowsAutomation,
        screenshot: Callable[[Path, list[int]], None],
        screenshot_root: Path,
        rehearsal: bool = False,
        on_long_wait_start: Callable[[], None] | None = None,
        on_long_wait_end: Callable[[], None] | None = None,
    ):
        self.adapter = adapter
        self.automation = automation
        self.screenshot = screenshot
        self.screenshot_root = screenshot_root
        self.started = time.perf_counter()
        self.started_wall = time.time()
        self.last_output: Path | None = None
        self.rehearsal = rehearsal
        self.on_long_wait_start = on_long_wait_start
        self.on_long_wait_end = on_long_wait_end
        self.output_baseline = adapter.output_snapshot() if hasattr(adapter, "output_snapshot") else set()
        self.rehearsal_runtime_phase = False

    def execute_all(self, actions: list[TutorialAction]) -> Path | None:
        for action in actions:
            self._wait_until(action.at)
            try:
                if self.rehearsal and self.rehearsal_runtime_phase:
                    self.automation.record_external(
                        "rehearsal_runtime_skipped", action.target or action.kind, requested_action=action.kind,
                    )
                    continue
                result = self.execute(action)
                if action.target and isinstance(result, dict) and result.get("rect"):
                    self.automation.record_external(
                        "visual_focus", action.target,
                        scheduled_time=float(action.at or 0.0),
                        duration=max(2.0, action.duration),
                        rect=result["rect"],
                        visual_action=action.kind,
                        closeup=bool(action.args.get("closeup", action.kind in {"click", "double_click", "type", "select"})),
                    )
            except Exception as exc:
                if not bool(action.args.get("optional", False)):
                    raise
                self.automation.record_external(
                    "optional_action_skipped", action.target or action.kind,
                    requested_action=action.kind, reason=str(exc),
                )
        return self.last_output

    def _wait_until(self, at: float | None) -> None:
        if at is None:
            return
        while True:
            elapsed = (
                float(self.automation.clock())
                if callable(getattr(self.automation, "clock", None))
                else time.perf_counter() - self.started
            )
            remaining = at - elapsed
            if remaining <= 0:
                return
            time.sleep(min(0.1, remaining))

    def execute(self, action: TutorialAction) -> Any:
        kind, target = action.kind, action.target
        if self.rehearsal and kind != "operation" and bool(action.args.get("unsafe", False)):
            widget = self.automation.hover(self._target(target), duration=min(action.duration, 0.8))
            self.automation.record_external("rehearsal_unsafe_skipped", target or kind, requested_action=kind)
            return widget
        if self.rehearsal and kind in {"wait_for_output", "show_output", "dismiss_dialog"}:
            if kind == "wait_for_output":
                self.rehearsal_runtime_phase = True
            self.automation.record_external("rehearsal_runtime_skipped", target or kind, requested_action=kind)
            return None
        if kind == "launch":
            self.automation.record_external("launch")
            return self.adapter.state()
        if kind == "operation":
            operation = self._target(target)
            capability = (self.adapter.capabilities().get(operation) or {}) if hasattr(self.adapter, "capabilities") else {}
            if not capability:
                raise RuntimeError(f"Application driver does not expose semantic operation: {operation}")
            if self.rehearsal and (
                bool(capability.get("side_effect", False)) or bool(action.args.get("unsafe", False))
            ):
                self.automation.record_external(
                    "rehearsal_operation_skipped", operation, requested_action=kind,
                )
                return None
            if bool(capability.get("long_running", False)) and self.on_long_wait_start:
                self.on_long_wait_start()
            operation_args = action.args.get("operation_args") or {}
            if not isinstance(operation_args, dict):
                raise ValueError(f"operation_args must be a mapping for operation: {operation}")
            try:
                result = self.adapter.execute_operation(operation, action.value, **operation_args)
            finally:
                if bool(capability.get("long_running", False)) and self.on_long_wait_end:
                    self.on_long_wait_end()
            self.automation.record_external("operation", operation, value=action.value, result=result)
            focus_target = str(capability.get("focus_control") or "")
            return self.adapter.widget(focus_target) if focus_target else result
        if kind == "click":
            return self.automation.click(self._target(target), hover=action.duration)
        if kind == "double_click":
            return self.automation.double_click(self._target(target), hover=action.duration)
        if kind == "hover":
            return self.automation.hover(self._target(target), duration=action.duration)
        if kind == "type":
            return self.automation.enter_text(self._target(target), str(action.value or ""))
        if kind == "select":
            return self.automation.set_combo(self._target(target), str(action.value))
        if kind == "set_number":
            return self.automation.set_number(self._target(target), float(action.value))
        if kind == "scroll_to":
            return self.automation.scroll_to(self._target(target), str(action.value or "down"))
        if kind == "capture":
            name = str(action.value or target or f"capture_{len(self.automation.events) + 1}")
            path = self.screenshot_root / f"{name}.png"
            self.screenshot(path, self.adapter.state()["window_rect"])
            self.automation.record_external("capture", target or name, path=str(path.resolve()))
            return path
        if kind == "wait_for":
            return self._wait_for_control(self._target(target), action)
        if kind == "verify":
            return self._verify(self._target(target), action.value)
        if kind == "wait_for_output":
            newer_value = action.args.get("newer_than")
            newer_than = self.started_wall if newer_value == "run_start" else float(newer_value) if newer_value else None
            if self.on_long_wait_start:
                self.on_long_wait_start()
            try:
                self.last_output = self.adapter.wait_for_output(
                    timeout=float(action.args.get("timeout_seconds", 30)), newer_than=newer_than,
                    baseline=self.output_baseline if bool(action.args.get("require_new", True)) else None,
                    stable_seconds=float(action.args.get("stable_seconds", 3.0)),
                    min_bytes=int(action.args.get("min_bytes", 1)),
                )
            finally:
                if self.on_long_wait_end:
                    self.on_long_wait_end()
            self.automation.record_external("wait_for_output", target or "output", path=str(self.last_output.resolve()))
            return self.last_output
        if kind == "dismiss_dialog":
            result = self.adapter.dismiss_dialog(str(action.value or "OK")) if hasattr(self.adapter, "dismiss_dialog") else None
            self.automation.record_external("dismiss_dialog", target or "dialog", result=result)
            time.sleep(action.duration)
            return result
        if kind == "show_output":
            path = Path(str(action.value)).resolve() if action.value else self.last_output
            self.last_output = self.adapter.show_output(path)
            if bool(action.args.get("open", False)):
                os.startfile(self.last_output)
            self.automation.record_external("show_output", target or "output", path=str(self.last_output.resolve()))
            time.sleep(action.duration)
            return self.last_output
        if kind == "open_file":
            path = Path(str(action.value)).resolve()
            if not path.exists():
                raise FileNotFoundError(path)
            os.startfile(path)
            self.automation.record_external("open_file", target or "file", path=str(path))
            time.sleep(action.duration)
            return path
        raise AssertionError(kind)

    @staticmethod
    def _target(target: str | None) -> str:
        if not target:
            raise ValueError("This action requires a semantic target")
        return target

    def _wait_for_control(self, target: str, action: TutorialAction) -> dict[str, Any]:
        deadline = time.time() + float(action.args.get("timeout_seconds", 30))
        expected = action.value
        last: dict[str, Any] | None = None
        while time.time() < deadline:
            try:
                last = self.adapter.widget(target)
                if expected is None or last.get("value") == expected:
                    self.automation.record_external("wait_for", target, value=last.get("value"))
                    return last
            except Exception:
                pass
            time.sleep(0.3)
        raise TimeoutError(f"Control did not reach expected state: {target}, expected={expected!r}, last={last}")

    def _verify(self, target: str, expected: Any) -> dict[str, Any]:
        widget = self.adapter.widget(target)
        if expected is not None and widget.get("value") != expected:
            raise RuntimeError(f"Verification failed for {target}: expected {expected!r}, got {widget.get('value')!r}")
        self.automation.record_external("verify", target, value=widget.get("value"), rect=widget.get("rect"))
        return widget
