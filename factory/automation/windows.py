from __future__ import annotations

import ctypes
import json
import time
from pathlib import Path
from typing import Any

import pyautogui


class WindowsAutomation:
    def __init__(self, adapter: Any, event_log: Path, clock: Any | None = None):
        self.adapter = adapter
        self.event_log = event_log
        self.started = time.perf_counter()
        self.clock = clock
        self.events: list[dict[str, Any]] = []
        # Keep PyAutoGUI's emergency corner failsafe, but move an inherited
        # corner-positioned cursor to a neutral point before the first action.
        x, y = pyautogui.position()
        width, height = pyautogui.size()
        if x <= 1 or y <= 1 or x >= width - 2 or y >= height - 2:
            ctypes.windll.user32.SetCursorPos(width // 2, height // 2)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.12

    def focus(self) -> None:
        if hasattr(self.adapter, "focus_window"):
            self.adapter.focus_window()
            time.sleep(0.5)
            return
        hwnd = int(self.adapter.state()["window_handle"])
        ctypes.windll.user32.ShowWindow(hwnd, 3)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.5)

    def _record(self, action: str, target: str, widget: dict[str, Any], **extra: Any) -> None:
        event = {
            "time": round(self._time(), 3),
            "action": action, "target": target, "rect": widget["rect"], **extra,
        }
        self.events.append(event)
        self.event_log.write_text(json.dumps(self.events, indent=2), encoding="utf-8")

    def record_external(self, action: str, target: str = "", **extra: Any) -> None:
        event = {
            "time": round(self._time(), 3),
            "action": action,
            "target": target,
            **extra,
        }
        self.events.append(event)
        self.event_log.write_text(json.dumps(self.events, indent=2), encoding="utf-8")

    def _time(self) -> float:
        return float(self.clock()) if self.clock is not None else time.perf_counter() - self.started

    def locate(self, semantic_id: str) -> dict[str, Any]:
        widget = self.adapter.widget(semantic_id)
        if not widget.get("visible") or not widget.get("enabled"):
            raise RuntimeError(f"Control is not ready: {semantic_id}: {widget}")
        return widget

    def click(self, semantic_id: str, hover: float = 0.45) -> dict[str, Any]:
        widget = self.locate(semantic_id)
        if hasattr(self.adapter, "invoke"):
            self._record("hover", semantic_id, widget)
            time.sleep(hover)
            current = self.adapter.invoke(semantic_id)
            self._record("click", semantic_id, current)
            return current
        x, y = widget["center"]
        pyautogui.moveTo(x, y, duration=0.55, tween=pyautogui.easeInOutQuad)
        self._record("hover", semantic_id, widget)
        time.sleep(hover)
        pyautogui.click()
        self._record("click", semantic_id, widget)
        time.sleep(0.35)
        return self.adapter.widget(semantic_id)

    def double_click(self, semantic_id: str, hover: float = 0.55) -> dict[str, Any]:
        widget = self.locate(semantic_id)
        if hasattr(self.adapter, "invoke"):
            self._record("hover", semantic_id, widget)
            time.sleep(hover)
            self.adapter.invoke(semantic_id)
            current = self.adapter.invoke(semantic_id)
            self._record("double_click", semantic_id, current)
            return current
        x, y = widget["center"]
        pyautogui.moveTo(x, y, duration=0.55, tween=pyautogui.easeInOutQuad)
        self._record("hover", semantic_id, widget)
        time.sleep(hover)
        pyautogui.doubleClick(interval=0.14)
        self._record("double_click", semantic_id, widget)
        time.sleep(0.5)
        return widget

    def hover(self, semantic_id: str, duration: float = 1.0) -> dict[str, Any]:
        widget = self.locate(semantic_id)
        if hasattr(self.adapter, "invoke"):
            self._record("hover", semantic_id, widget)
            time.sleep(duration)
            return self.adapter.widget(semantic_id)
        x, y = widget["center"]
        pyautogui.moveTo(x, y, duration=0.55, tween=pyautogui.easeInOutQuad)
        self._record("hover", semantic_id, widget)
        time.sleep(duration)
        return self.adapter.widget(semantic_id)

    def scroll_to(self, semantic_id: str, direction: str, max_steps: int = 18) -> dict[str, Any]:
        state = self.adapter.state()
        wx, wy, ww, wh = [int(v) for v in state["window_rect"]]
        anchor_x = wx + max(120, ww - 90)
        anchor_y = wy + wh // 2
        pyautogui.moveTo(anchor_x, anchor_y, duration=0.45, tween=pyautogui.easeInOutQuad)
        delta = -6 if direction == "down" else 6
        for _ in range(max_steps):
            widget = self.adapter.widget(semantic_id)
            x, y, width, height = [int(v) for v in widget["rect"]]
            if wx <= x + width and x <= wx + ww and wy + 135 <= y + height and y <= wy + wh - 95:
                self._record("scroll_into_view", semantic_id, widget, direction=direction)
                return widget
            pyautogui.scroll(delta)
            time.sleep(0.16)
        raise RuntimeError(f"Could not scroll {semantic_id} into view")

    def set_combo(self, semantic_id: str, value: str) -> dict[str, Any]:
        widget = self.locate(semantic_id)
        values = list(widget.get("values") or [])
        if value not in values:
            raise ValueError(f"{value!r} is not available for {semantic_id}: {values}")
        if hasattr(self.adapter, "select_value"):
            current = self.adapter.select_value(semantic_id, value)
            self._record("select", semantic_id, current, value=value)
            return current
        self.click(semantic_id)
        pyautogui.press("home")
        index = values.index(value)
        if index:
            pyautogui.press("down", presses=index, interval=0.08)
        pyautogui.press("enter")
        time.sleep(0.4)
        current = self.adapter.widget(semantic_id)
        self._record("select", semantic_id, current, value=value)
        if current.get("value") != value:
            raise RuntimeError(f"Selection verification failed for {semantic_id}: {current}")
        return current

    def enter_text(self, semantic_id: str, text: str) -> dict[str, Any]:
        if hasattr(self.adapter, "set_text"):
            current = self.adapter.set_text(semantic_id, text)
            self._record("enter_text", semantic_id, current, value=text)
            if current.get("value") != text:
                raise RuntimeError(f"Text verification failed for {semantic_id}")
            return current
        widget = self.click(semantic_id)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(text, interval=0.003)
        time.sleep(0.6)
        current = self.adapter.widget(semantic_id)
        self._record("enter_text", semantic_id, current, value=text)
        if current.get("value") != text:
            raise RuntimeError(f"Text verification failed for {semantic_id}")
        return current

    def set_number(self, semantic_id: str, value: float) -> dict[str, Any]:
        if hasattr(self.adapter, "set_text"):
            current = self.adapter.set_text(semantic_id, str(value))
            self._record("set_number", semantic_id, current, value=value)
            return current
        self.click(semantic_id)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.write(str(value), interval=0.08)
        pyautogui.press("enter")
        time.sleep(0.5)
        current = self.adapter.widget(semantic_id)
        self._record("set_number", semantic_id, current, value=value)
        if abs(float(current.get("value")) - float(value)) > 0.001:
            raise RuntimeError(f"Number verification failed for {semantic_id}: {current}")
        return current
