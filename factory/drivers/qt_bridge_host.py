from __future__ import annotations

import argparse
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def run_qt_driver_host(handler_factory: Callable[[Any], Any]) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--factory-qt-driver-host", action="store_true")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    args, _ = parser.parse_known_args()
    if not args.factory_qt_driver_host:
        raise RuntimeError("This entrypoint is reserved for Tutorial Factory")

    print("[factory-qt-host] importing PySide6", flush=True)
    from PySide6 import QtCore, QtGui, QtWidgets

    print("[factory-qt-host] creating QApplication", flush=True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    print("[factory-qt-host] creating generated handler", flush=True)
    handler = handler_factory(app)
    print("[factory-qt-host] entering generated create_window", flush=True)
    window = handler.create_window(app)
    print("[factory-qt-host] generated create_window returned", flush=True)
    handler.window = window
    window.show()

    class Dispatcher(QtCore.QObject):
        requested = QtCore.Signal(object)

        def __init__(self) -> None:
            super().__init__()
            self.requested.connect(self._execute, QtCore.Qt.ConnectionType.QueuedConnection)

        @staticmethod
        def _widget(selector: dict[str, Any]) -> Any:
            object_name = str(selector.get("object_name") or "")
            if not object_name:
                raise ValueError("Qt bridge controls require object_name")
            widget = None
            for top_level in QtWidgets.QApplication.topLevelWidgets():
                if top_level.objectName() == object_name:
                    widget = top_level
                    break
                widget = top_level.findChild(QtCore.QObject, object_name)
                if widget is not None:
                    break
            if widget is None:
                raise LookupError(f"Qt objectName was not found: {object_name}")
            return widget

        @staticmethod
        def _widget_state(widget: Any) -> dict[str, Any]:
            rect = widget.rect()
            origin = widget.mapToGlobal(rect.topLeft()) if hasattr(widget, "mapToGlobal") else QtCore.QPoint(0, 0)
            value: Any = ""
            for method in ("text", "currentText", "value", "isChecked", "count"):
                candidate = getattr(widget, method, None)
                if callable(candidate):
                    try:
                        value = candidate()
                        break
                    except Exception:
                        continue
            return {
                "name": str(getattr(widget, "text", lambda: "")() or "") if callable(getattr(widget, "text", None)) else "",
                "value": _json_safe(value),
                "visible": bool(widget.isVisible()),
                "enabled": bool(widget.isEnabled()),
                "rect": [origin.x(), origin.y(), rect.width(), rect.height()],
                "center": [origin.x() + rect.width() // 2, origin.y() + rect.height() // 2],
                "control_type": type(widget).__name__,
            }

        @QtCore.Slot(object)
        def _execute(self, holder: dict[str, Any]) -> None:
            request = holder["request"]
            try:
                operation = request.get("operation")
                if operation == "health":
                    result = {"ready": True}
                elif operation == "state":
                    geometry = window.frameGeometry()
                    result = {
                        "window_title": window.windowTitle(),
                        "window_handle": int(window.winId()),
                        "window_rect": [geometry.x(), geometry.y(), geometry.width(), geometry.height()],
                    }
                elif operation == "widget":
                    result = self._widget_state(self._widget(dict(request.get("selector") or {})))
                elif operation == "capture":
                    path = Path(str(request["path"])).resolve()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if not window.grab().save(str(path)):
                        raise RuntimeError(f"Qt could not save capture: {path}")
                    result = str(path)
                elif operation == "semantic_operation":
                    result = handler.execute(
                        str(request.get("name") or ""), request.get("value"), dict(request.get("args") or {})
                    )
                elif operation == "close":
                    window.close()
                    QtCore.QTimer.singleShot(0, app.quit)
                    result = {"closed": True}
                else:
                    raise ValueError(f"Unsupported bridge operation: {operation}")
                holder["response"] = {"ok": True, "result": _json_safe(result)}
            except Exception as exc:
                holder["response"] = {
                    "ok": False, "error": str(exc), "traceback": traceback.format_exc()[-12000:]
                }
            finally:
                holder["event"].set()

    dispatcher = Dispatcher()

    class RequestHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            if self.path != "/command" or self.headers.get("X-Tutorial-Driver-Token") != args.token:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                holder = {"request": request, "event": threading.Event(), "response": None}
                dispatcher.requested.emit(holder)
                if not holder["event"].wait(7200):
                    raise TimeoutError("Qt main-thread operation timed out")
                response = holder["response"]
                body = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

    print(f"[factory-qt-host] starting localhost bridge on port {args.port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), RequestHandler)
    thread = threading.Thread(target=server.serve_forever, name="tutorial-driver-http", daemon=True)
    thread.start()
    print("[factory-qt-host] bridge ready", flush=True)
    try:
        app.exec()
    finally:
        server.shutdown()
        server.server_close()
