from __future__ import annotations

import os
import re
import subprocess
import time
import ctypes
from pathlib import Path
from typing import Any

from pywinauto import Desktop

from factory.adapters.base import ApplicationAdapter
from factory.core.profile import ApplicationProfile


class WindowsUIAAdapter(ApplicationAdapter):
    """Generic semantic adapter for native Windows, Qt and Electron surfaces."""

    def __init__(self, profile: ApplicationProfile, run_root: Path):
        self.profile = profile
        self.run_root = run_root.resolve()
        self.process: subprocess.Popen[Any] | None = None
        self.window: Any | None = None
        self.launch_attention_required = False
        self.blocking_window_titles: list[str] = []
        self._existing_handles: set[int] = set()

    def launch(self) -> None:
        if self.process is not None:
            raise RuntimeError("Application is already launched")
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (self.profile.data["launch"].get("env") or {}).items()})
        command = self.profile.launch_command
        executable = Path(command[0])
        if executable.is_absolute() and not executable.is_file():
            raise FileNotFoundError(f"Application launcher does not exist: {executable}")
        existing_handles = {int(window.handle) for window in Desktop(backend="uia").windows() if window.handle is not None}
        self._existing_handles = existing_handles
        self.process = subprocess.Popen(command, cwd=self.profile.launch_cwd, env=env)
        deadline = time.time() + float(self.profile.data["launch"].get("timeout_seconds", 45))
        title_re = re.compile(self.profile.window_title_re, re.IGNORECASE)
        name_tokens = {
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", self.profile.name)
            if len(token) >= 4 and token.lower() not in {"guided", "application"}
        }
        fallback: list[Any] = []
        first_named_candidate: float | None = None
        dialog_actions = {"ok", "cancel", "yes", "no", "continue", "skip", "close", "accept", "decline"}
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Application exited during launch with code {self.process.returncode}")
            # Qt launchers may replace the initial process or spawn the GUI in a child.
            # Match the newly-created semantic window rather than assuming one PID.
            for window in Desktop(backend="uia").windows():
                title = window.window_text()
                if window.handle is None or int(window.handle) in existing_handles or not window.is_visible() or not window.is_enabled():
                    continue
                candidate = Desktop(backend="uia").window(handle=window.handle)
                if title_re.search(title or ""):
                    self.window = candidate
                    return
                if title and any(word in title.lower() for word in ("initial setup", "setup", "configuration", "provider")):
                    self.window = candidate
                    self.launch_attention_required = True
                    self.blocking_window_titles = [title]
                    return
                # A modal Qt question may have an application-specific title such
                # as "Load Last Workspace". Detect its semantic dialog buttons
                # immediately instead of waiting for the full application timeout.
                try:
                    button_titles = {
                        (button.window_text() or "").replace("&", "").strip().lower()
                        for button in candidate.descendants(control_type="Button")
                        if button.is_visible() and button.is_enabled()
                    }
                except Exception:
                    button_titles = set()
                if button_titles.intersection(dialog_actions):
                    self.window = candidate
                    self.launch_attention_required = True
                    self.blocking_window_titles = [title or "Untitled application dialog"]
                    return
                title_tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", title or "") if len(token) >= 4}
                overlap = name_tokens.intersection(title_tokens)
                required = 1 if len(name_tokens) <= 1 else 2
                if title and len(overlap) >= required:
                    fallback.append(candidate)
                    first_named_candidate = first_named_candidate or time.time()
            if fallback and first_named_candidate and time.time() - first_named_candidate >= 2.0:
                self.window = fallback[-1]
                self.detected_window_title = self.window.window_text()
                return
            time.sleep(0.3)
        visible_windows = [
            window for window in Desktop(backend="uia").windows()
            if window.handle is not None and int(window.handle) not in existing_handles and window.is_visible() and window.window_text()
        ]
        visible_titles = [window.window_text() for window in visible_windows]
        for window in visible_windows:
            title = window.window_text() or ""
            title_tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", title) if len(token) >= 4}
            required = 1 if len(name_tokens) <= 1 else 2
            if title_re.search(title) or len(name_tokens.intersection(title_tokens)) >= required:
                self.window = Desktop(backend="uia").window(handle=window.handle)
                self.detected_window_title = title
                return
        if visible_windows:
            self.window = Desktop(backend="uia").window(handle=visible_windows[0].handle)
            self.launch_attention_required = True
            self.blocking_window_titles = visible_titles
            return
        raise TimeoutError(
            f"Timed out waiting for window matching {self.profile.window_title_re!r}. "
            f"New visible windows: {visible_titles}"
        )

    def reacquire_application_window(self, timeout: float = 90.0) -> None:
        title_re = re.compile(self.profile.window_title_re, re.IGNORECASE)
        name_tokens = {
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", self.profile.name)
            if len(token) >= 4 and token.lower() not in {"guided", "application"}
        }
        deadline = time.time() + timeout
        while time.time() < deadline:
            for window in Desktop(backend="uia").windows():
                if window.handle is None or not window.is_visible() or not window.is_enabled():
                    continue
                title = window.window_text() or ""
                title_tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", title) if len(token) >= 4}
                required = 1 if len(name_tokens) <= 1 else 2
                if title_re.search(title) or len(name_tokens.intersection(title_tokens)) >= required:
                    self.window = Desktop(backend="uia").window(handle=window.handle)
                    self.launch_attention_required = False
                    self.detected_window_title = title
                    return
            time.sleep(0.5)
        raise TimeoutError("The main application window did not appear after setup was completed")

    def _require_window(self) -> Any:
        if self.window is None:
            raise RuntimeError("Application window is not available")
        return self.window

    def _activate_container(self, selector: dict[str, Any]) -> None:
        title = str(selector.get("container_title") or "").strip()
        if not title:
            return
        tab = self._require_window().child_window(title=title, control_type="TabItem")
        tab.wait("exists visible enabled ready", timeout=float(selector.get("timeout_seconds", 10)))
        wrapper = tab.wrapper_object()
        try:
            wrapper.select()
        except Exception:
            try:
                wrapper.invoke()
            except Exception:
                wrapper.click()
        time.sleep(0.25)

    def _resolve(self, semantic_id: str, require_enabled: bool = True) -> Any:
        selector = self.profile.controls.get(semantic_id)
        if selector is None:
            raise KeyError(f"Unknown semantic control: {semantic_id}")
        self._activate_container(selector)
        criteria: dict[str, Any] = {}
        if selector.get("title") is not None:
            criteria["title"] = str(selector["title"])
        if selector.get("title_re") is not None:
            criteria["title_re"] = str(selector["title_re"])
        if selector.get("auto_id") is not None:
            criteria["auto_id"] = str(selector["auto_id"])
        if selector.get("control_type") is not None:
            criteria["control_type"] = str(selector["control_type"])
        if selector.get("found_index") is not None:
            criteria["found_index"] = int(selector["found_index"])
        if selector.get("object_name") is not None:
            suffix = "." + str(selector["object_name"])
            expected_type = str(selector.get("control_type") or "")
            matches = [
                item for item in self._require_window().descendants()
                if str(item.element_info.automation_id or "").endswith(suffix)
                and (not expected_type or item.element_info.control_type == expected_type)
            ]
            if len(matches) != 1:
                raise RuntimeError(f"Qt objectName selector {semantic_id} matched {len(matches)} controls")
            control = matches[0]
            if not control.is_visible() or (require_enabled and not control.is_enabled()):
                raise RuntimeError(f"Control is not ready: {semantic_id}")
            return control
        if not criteria:
            raise ValueError(f"Control selector is empty: {semantic_id}")
        control = self._require_window().child_window(**criteria)
        wait_state = "exists visible enabled ready" if require_enabled else "exists visible"
        control.wait(wait_state, timeout=float(selector.get("timeout_seconds", 10)))
        return control.wrapper_object()

    def focus_window(self) -> None:
        window = self._require_window()
        try:
            window.maximize()
        except Exception:
            pass
        window.set_focus()

    def attention_options(self) -> list[str]:
        options: list[str] = []
        for control in self._require_window().descendants(control_type="Button"):
            try:
                title = (control.window_text() or "").replace("&", "").strip()
                if title and control.is_visible() and control.is_enabled() and title not in options:
                    options.append(title)
            except Exception:
                continue
        return options

    def choose_attention_option(self, title: str) -> None:
        button = self._require_window().child_window(
            title_re=rf"(?i)^&?{re.escape(title)}$", control_type="Button"
        )
        button.wait("exists visible enabled ready", timeout=10)
        wrapper = button.wrapper_object()
        try:
            wrapper.invoke()
        except Exception:
            wrapper.click()
        time.sleep(0.5)

    def invoke(self, semantic_id: str) -> dict[str, Any]:
        control = self._resolve(semantic_id)
        try:
            control.invoke()
        except Exception:
            control.click()
        time.sleep(0.25)
        return self.widget(semantic_id)

    def set_text(self, semantic_id: str, value: str) -> dict[str, Any]:
        control = self._resolve(semantic_id)
        try:
            control.set_edit_text(value)
        except Exception:
            control.iface_value.SetValue(value)
        time.sleep(0.25)
        return self.widget(semantic_id)

    def select_value(self, semantic_id: str, value: str) -> dict[str, Any]:
        control = self._resolve(semantic_id)
        control.select(value)
        time.sleep(0.25)
        return self.widget(semantic_id)

    @staticmethod
    def _rect(control: Any) -> list[int]:
        if hasattr(control, "wrapper_object"):
            control = control.wrapper_object()
        rect = control.rectangle()
        return [int(rect.left), int(rect.top), int(rect.width()), int(rect.height())]

    def widget(self, semantic_id: str) -> dict[str, Any]:
        selector = self.profile.controls[semantic_id]
        control = self._resolve(semantic_id, require_enabled=False)
        rect = self._rect(control)
        value: Any = control.window_text()
        try:
            value = control.iface_value.CurrentValue
        except Exception:
            pass
        values = list(selector.get("values") or [])
        return {
            "id": semantic_id,
            "name": control.window_text(),
            "value": value,
            "values": values,
            "rect": rect,
            "center": [rect[0] + rect[2] // 2, rect[1] + rect[3] // 2],
            "visible": bool(control.is_visible()),
            "enabled": bool(control.is_enabled()),
            "control_type": control.element_info.control_type,
        }

    def state(self) -> dict[str, Any]:
        window = self._require_window().wrapper_object()
        rect = self._rect(window)
        return {
            "window_handle": int(window.handle),
            "window_title": window.window_text(),
            "window_rect": rect,
            "process_id": int(window.process_id()),
            "framework": self.profile.data["application"].get("framework"),
        }

    def capture(self, path: Path) -> Path:
        import win32con
        import win32gui
        import win32ui
        from PIL import Image

        path.parent.mkdir(parents=True, exist_ok=True)
        window = self._require_window().wrapper_object()
        hwnd = int(window.handle)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width, height = right - left, bottom - top
        window_dc = win32gui.GetWindowDC(hwnd)
        source_dc = win32ui.CreateDCFromHandle(window_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        try:
            rendered = ctypes.windll.user32.PrintWindow(hwnd, memory_dc.GetSafeHdc(), 2)
            if not rendered:
                raise OSError(f"PrintWindow failed for handle {hwnd}")
            info = bitmap.GetInfo()
            bits = bitmap.GetBitmapBits(True)
            image = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
            image.save(path)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            memory_dc.DeleteDC()
            source_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, window_dc)
        return path

    def wait_for_output(
        self,
        timeout: float,
        newer_than: float | None = None,
        baseline: set[str] | None = None,
        stable_seconds: float = 3.0,
        min_bytes: int = 1,
    ) -> Path:
        deadline = time.time() + max(0.0, timeout)
        stable: dict[str, tuple[int, float]] = {}
        while True:
            candidates: list[Path] = []
            for spec in self.profile.output_specs:
                folder = Path(os.path.expandvars(str(spec["directory"]))).resolve()
                pattern = str(spec.get("glob") or "*")
                candidates.extend(path for path in folder.glob(pattern) if path.is_file())
            if newer_than is not None:
                candidates = [path for path in candidates if path.stat().st_mtime >= newer_than]
            if baseline:
                candidates = [path for path in candidates if str(path.resolve()).lower() not in baseline]
            candidates = [path for path in candidates if path.stat().st_size >= min_bytes]
            for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
                key = str(path.resolve()).lower()
                size = path.stat().st_size
                previous = stable.get(key)
                now = time.time()
                if previous is None or previous[0] != size:
                    stable[key] = (size, now)
                elif now - previous[1] >= stable_seconds:
                    return path
            if time.time() >= deadline:
                raise TimeoutError("No matching application output was found")
            time.sleep(1.0)

    def output_snapshot(self) -> set[str]:
        paths: set[str] = set()
        for spec in self.profile.output_specs:
            folder = Path(os.path.expandvars(str(spec["directory"]))).resolve()
            pattern = str(spec.get("glob") or "*")
            if folder.is_dir():
                paths.update(str(path.resolve()).lower() for path in folder.glob(pattern) if path.is_file())
        return paths

    def dismiss_dialog(self, button_title: str = "OK") -> dict[str, Any] | None:
        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            try:
                if not window.is_visible() or int(window.handle) == int(self._require_window().handle):
                    continue
                button = desktop.window(handle=window.handle).child_window(title_re=rf"(?i)^{re.escape(button_title)}$", control_type="Button")
                if button.exists(timeout=0.3):
                    wrapper = button.wrapper_object()
                    rect = self._rect(wrapper)
                    try:
                        wrapper.invoke()
                    except Exception:
                        wrapper.click()
                    return {"rect": rect, "title": window.window_text(), "button": button_title}
            except Exception:
                continue
        return None

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        if self.window is not None:
            try:
                self.window.close()
                process.wait(timeout=10)
                return
            except Exception:
                pass
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        finally:
            self.window = None
