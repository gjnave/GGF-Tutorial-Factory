from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .control_map import CONTROL_ATTRIBUTES, TAB_TITLES


def _nested_attr(root: Any, path: str) -> Any:
    value = root
    for part in path.split("."):
        value = getattr(value, part)
    return value


class BridgeRuntime:
    def __init__(self, window: Any, qt: Any):
        self.window = window
        self.qt = qt

    def resolve(self, semantic_id: str) -> tuple[Any, int | None]:
        if semantic_id in TAB_TITLES:
            title = TAB_TITLES[semantic_id]
            for index in range(self.window.tabs.count()):
                if self.window.tabs.tabText(index) == title:
                    return self.window.tabs.tabBar(), index
            raise KeyError(semantic_id)
        return _nested_attr(self.window, CONTROL_ATTRIBUTES[semantic_id]), None

    def describe(self, semantic_id: str) -> dict[str, Any]:
        if semantic_id in ("queue.finished.first", "queue.finished.last"):
            tree = self.window.finished_tree
            item_index = 0 if semantic_id.endswith("first") else tree.topLevelItemCount() - 1
            item = tree.topLevelItem(item_index)
            if item is None:
                raise KeyError("The finished queue has no first item")
            rect = tree.visualItemRect(item)
            top_left = tree.viewport().mapToGlobal(rect.topLeft())
            return {
                "id": semantic_id,
                "type": "QTreeWidgetItem",
                "enabled": bool(tree.isEnabled()),
                "visible": bool(tree.isVisible() and not rect.isEmpty()),
                "rect": [top_left.x(), top_left.y(), rect.width(), rect.height()],
                "center": [top_left.x() + rect.width() // 2, top_left.y() + rect.height() // 2],
                "value": [item.text(column) for column in range(tree.columnCount())],
            }
        widget, tab_index = self.resolve(semantic_id)
        if tab_index is None:
            rect = widget.rect()
            top_left = widget.mapToGlobal(rect.topLeft())
            width, height = rect.width(), rect.height()
            visible = bool(widget.isVisible())
            enabled = bool(widget.isEnabled())
        else:
            rect = widget.tabRect(tab_index)
            top_left = widget.mapToGlobal(rect.topLeft())
            width, height = rect.width(), rect.height()
            visible = bool(widget.isVisible())
            enabled = bool(widget.isTabEnabled(tab_index))
        result: dict[str, Any] = {
            "id": semantic_id,
            "type": type(widget).__name__ if tab_index is None else "QTabBarTab",
            "enabled": enabled,
            "visible": visible,
            "rect": [top_left.x(), top_left.y(), width, height],
            "center": [top_left.x() + width // 2, top_left.y() + height // 2],
        }
        if tab_index is not None:
            result.update(value=self.window.tabs.tabText(tab_index), selected=self.window.tabs.currentIndex() == tab_index)
            return result
        if isinstance(widget, self.qt.QComboBox):
            result.update(value=widget.currentText(), values=[widget.itemText(i) for i in range(widget.count())])
        elif isinstance(widget, (self.qt.QSpinBox, self.qt.QDoubleSpinBox)):
            result["value"] = widget.value()
        elif isinstance(widget, self.qt.QPlainTextEdit):
            result["value"] = widget.toPlainText()
        elif isinstance(widget, self.qt.QLineEdit):
            result["value"] = widget.text()
        elif isinstance(widget, self.qt.QCheckBox):
            result["value"] = widget.isChecked()
        elif isinstance(widget, self.qt.QListWidget):
            result["value"] = [widget.item(i).data(self.qt.Qt.ItemDataRole.UserRole) for i in range(widget.count())]
        elif hasattr(widget, "text"):
            result["value"] = widget.text()
        return result

    def app_state(self) -> dict[str, Any]:
        rect = self.window.frameGeometry()
        return {
            "application": "GrizzlyMax",
            "tutorial_mode": os.environ.get("GGF_TUTORIAL_MODE") == "1",
            "window_title": self.window.windowTitle(),
            "window_handle": int(self.window.winId()),
            "window_rect": [rect.x(), rect.y(), rect.width(), rect.height()],
            "current_tab": self.window.tabs.tabText(self.window.tabs.currentIndex()),
            "status": self.window.status.text(),
            "queue_jobs": [
                {
                    "id": item.get("id"), "state": item.get("state"),
                    "phase": item.get("phase"), "progress": item.get("progress"),
                    "output": item.get("output"), "prompt": item.get("prompt"),
                    "error": item.get("error"), "log_tail": item.get("log_tail"),
                    "actual_seed": item.get("actual_seed"),
                }
                for item in self.window.queue_jobs
            ],
        }


class Request:
    def __init__(self, path: str):
        self.path = path
        self.event = threading.Event()
        self.result: Any = None
        self.error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    app_root = Path(args.app_root).resolve()
    run_dir = Path(args.run_dir).resolve()
    state_dir = run_dir / "state"
    output_dir = run_dir / "generated_examples"
    state_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    # The generation helper uses this canonical directory for isolated temporary
    # work even when the final output belongs to the Tutorial Factory run.
    (app_root / "output").mkdir(parents=True, exist_ok=True)
    os.environ["GGF_TUTORIAL_MODE"] = "1"
    sys.path.insert(0, str(app_root))

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QListWidget, QPlainTextEdit, QSpinBox
    import helpers.minimax_h3_gui as gui

    gui.PRESET_DIR = state_dir
    gui.DEFAULT_OUTPUT_DIR = output_dir
    gui.LORA_STATE_FILE = state_dir / "minimax_h3_loras.json"
    gui.QUEUE_FILE = state_dir / "minimax_h3_queue.json"
    gui.APP_UPDATE_STATE = state_dir / "minimax_h3_update_state.json"

    app = QApplication(sys.argv[:1])
    app.setApplicationName("MiniMax H3 INT4 Standalone - Tutorial Mode")
    window = gui.MainWindow()
    window.setWindowTitle("MiniMax H3 INT4 Standalone - Tutorial Mode")
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    # Stable aliases for indexed/custom widgets used by the full walkthrough.
    window.generation_scroll = window._main_scroll_pages[0]
    ref_image_buttons = {button.text(): button for button in window.ref_images.findChildren(gui.QPushButton)}
    window.tutorial_ref_images_add = ref_image_buttons.get("Add…")
    window.tutorial_ref_images_preview = ref_image_buttons.get("Preview")
    if window.tutorial_ref_images_add is None or window.tutorial_ref_images_preview is None:
        raise RuntimeError("Ref2VA image controls were not found")
    for index, (row, strength) in enumerate(window.lora_rows, 1):
        setattr(window, f"tutorial_lora{index}_path", row.edit)
        setattr(window, f"tutorial_lora{index}_strength", strength)
        browse_buttons = [button for button in row.findChildren(gui.QPushButton) if button.text().startswith("Browse")]
        if not browse_buttons:
            raise RuntimeError(f"LoRA {index} Browse button was not found")
        setattr(window, f"tutorial_lora{index}_browse", browse_buttons[0])

    # Expose stable semantic names to Windows accessibility without altering GrizzlyMax source.
    safe_button = None
    for button in window.findChildren(gui.QPushButton):
        if button.text() == "Safe BAT preset":
            safe_button = button
            break
    if safe_button is None:
        raise RuntimeError("Safe BAT preset button was not found")
    window.safe_preset_button = safe_button
    for semantic_id, path in CONTROL_ATTRIBUTES.items():
        try:
            _nested_attr(window, path).setAccessibleName(semantic_id)
        except Exception:
            pass

    class QtTypes:
        pass
    qt = QtTypes()
    qt.QCheckBox, qt.QComboBox = QCheckBox, QComboBox
    qt.QDoubleSpinBox, qt.QLineEdit = QDoubleSpinBox, QLineEdit
    qt.QListWidget, qt.QPlainTextEdit, qt.QSpinBox, qt.Qt = QListWidget, QPlainTextEdit, QSpinBox, Qt
    bridge = BridgeRuntime(window, qt)
    requests: queue.Queue[Request] = queue.Queue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_GET(self) -> None:
            req = Request(self.path)
            requests.put(req)
            if not req.event.wait(3.0):
                self.send_error(504, "Qt bridge timed out")
                return
            if req.error:
                self.send_error(404, req.error)
                return
            body = json.dumps(req.result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    threading.Thread(target=server.serve_forever, name="ggf-tutorial-bridge", daemon=True).start()

    def serve_requests() -> None:
        while True:
            try:
                req = requests.get_nowait()
            except queue.Empty:
                return
            try:
                path = urllib.parse.urlparse(req.path).path
                if path == "/health":
                    req.result = {"ok": True, "application": "GrizzlyMax", "tutorial_mode": True}
                elif path == "/v1/state":
                    req.result = bridge.app_state()
                elif path == "/v1/widgets":
                    ids = list(TAB_TITLES) + list(CONTROL_ATTRIBUTES)
                    req.result = {item: bridge.describe(item) for item in ids}
                elif path.startswith("/v1/widget/"):
                    semantic_id = urllib.parse.unquote(path[len("/v1/widget/"):])
                    req.result = bridge.describe(semantic_id)
                elif path.startswith("/v1/ensure-visible/"):
                    semantic_id = urllib.parse.unquote(path[len("/v1/ensure-visible/"):])
                    widget, tab_index = bridge.resolve(semantic_id)
                    if tab_index is not None:
                        raise KeyError("Tab controls do not need scrolling")
                    window.generation_scroll.ensureWidgetVisible(widget, 80, 180)
                    app.processEvents()
                    req.result = bridge.describe(semantic_id)
                else:
                    raise KeyError(path)
            except Exception as exc:
                req.error = str(exc)
            finally:
                req.event.set()

    timer = QTimer()
    timer.setInterval(25)
    timer.timeout.connect(serve_requests)
    timer.start()
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    code = app.exec()
    server.shutdown()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
