from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from factory.core.profile import ApplicationProfile
from factory.drivers.base import ApplicationDriver
from factory.drivers.qt_bridge_host import run_qt_driver_host


class QtBridgeDriver(ApplicationDriver):
    """Factory-side client for a generated driver running in the Qt process."""

    CAPABILITIES: dict[str, dict[str, Any]] = {}
    REQUEST_TIMEOUT_SECONDS = 7200

    def __init__(self, profile: ApplicationProfile, run_root: Path):
        self.profile = profile
        self.run_root = run_root.resolve()
        self.process: subprocess.Popen[Any] | None = None
        self.port = self._free_port()
        self.token = os.urandom(24).hex()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._log_handle: Any | None = None

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def capabilities(self) -> dict[str, dict[str, Any]]:
        capabilities = json.loads(json.dumps(self.CAPABILITIES))
        manifest_path = self.profile.path.parent / "driver-manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validation = manifest.get("capability_validation") or {}
            for name, status in validation.items():
                if name in capabilities:
                    capabilities[name]["verified"] = bool((status or {}).get("passed", False))
        return capabilities

    def _request(self, operation: str, **payload: Any) -> Any:
        body = json.dumps({"operation": operation, **payload}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command", data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Tutorial-Driver-Token": self.token},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Qt driver bridge HTTP {exc.code}: {detail}") from exc
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "Qt driver bridge operation failed"))
        return result.get("result")

    def launch(self) -> None:
        if self.process is not None:
            raise RuntimeError("Application is already launched")
        driver_path = self.profile.driver_path
        python = Path(self.profile.launch_command[0]).resolve()
        log_path = self.run_root / "logs" / "driver-host.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("w", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        factory_root = Path(__file__).resolve().parents[2]
        prior_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(factory_root), str(self.profile.source_root), prior_pythonpath) if item
        )
        command = [
            str(python), str(driver_path), "--factory-qt-driver-host",
            "--port", str(self.port), "--token", self.token,
        ]
        self.process = subprocess.Popen(
            command, cwd=self.profile.launch_cwd, env=env,
            stdout=self._log_handle, stderr=subprocess.STDOUT,
        )
        deadline = time.time() + float(self.profile.data["launch"].get("timeout_seconds", 180))
        last_error = ""
        while time.time() < deadline:
            if self.process.poll() is not None:
                self._log_handle.flush()
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise RuntimeError(f"Generated Qt driver host exited with code {self.process.returncode}:\n{tail}")
            try:
                self._request("health")
                return
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.35)
        self._log_handle.flush()
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
        raise TimeoutError(
            f"Generated Qt driver host did not become ready: {last_error}\n"
            f"Driver host log tail:\n{tail or '[no host output]'}"
        )

    def state(self) -> dict[str, Any]:
        return dict(self._request("state") or {})

    def widget(self, semantic_id: str) -> dict[str, Any]:
        selector = self.profile.controls.get(semantic_id)
        if selector is None:
            raise KeyError(f"Unknown semantic control: {semantic_id}")
        return dict(self._request("widget", semantic_id=semantic_id, selector=selector) or {})

    def focus_window(self) -> None:
        state = self.state()
        handle = int(state["window_handle"])
        ctypes.windll.user32.ShowWindow(handle, 3)
        ctypes.windll.user32.SetForegroundWindow(handle)
        time.sleep(0.4)

    def capture(self, path: Path) -> Path:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._request("capture", path=str(path))
        if not path.is_file() or path.stat().st_size < 1:
            raise RuntimeError(f"Qt driver capture was not created: {path}")
        return path

    def execute_operation(self, name: str, value: Any = None, **kwargs: Any) -> Any:
        capability = self.capabilities().get(name)
        if capability is None:
            raise KeyError(f"Generated driver does not expose operation: {name}")
        if not bool(capability.get("verified", False)) and not bool(kwargs.pop("allow_unverified", False)):
            raise RuntimeError(f"Generated driver operation is not verified: {name}")
        result = self._request("semantic_operation", name=name, value=value, args=kwargs)
        if isinstance(result, dict) and result.get("error"):
            detail = str(result.get("error"))
            trace = str(result.get("traceback") or "").strip()
            raise RuntimeError(f"Generated driver operation failed ({name}): {detail}" + (f"\n{trace}" if trace else ""))
        return result

    def output_snapshot(self) -> set[str]:
        snapshot: set[str] = set()
        for spec in self.profile.output_specs:
            directory = Path(os.path.expandvars(str(spec.get("directory") or ""))).resolve()
            pattern = str(spec.get("glob") or "*.*")
            if directory.is_dir():
                snapshot.update(str(path.resolve()).lower() for path in directory.glob(pattern) if path.is_file())
        return snapshot

    def wait_for_output(
        self, timeout: float, newer_than: float | None = None,
        baseline: set[str] | None = None, stable_seconds: float = 3.0, min_bytes: int = 1,
    ) -> Path:
        baseline = {item.lower() for item in (baseline or set())}
        deadline = time.time() + timeout
        observed: dict[str, tuple[int, float]] = {}
        while time.time() <= deadline:
            candidates: list[Path] = []
            for spec in self.profile.output_specs:
                directory = Path(os.path.expandvars(str(spec.get("directory") or ""))).resolve()
                pattern = str(spec.get("glob") or "*.*")
                if directory.is_dir():
                    candidates.extend(path for path in directory.glob(pattern) if path.is_file())
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            for path in candidates:
                resolved = str(path.resolve()).lower()
                stat = path.stat()
                if resolved in baseline or stat.st_size < min_bytes or (newer_than and stat.st_mtime < newer_than):
                    continue
                previous = observed.get(resolved)
                if previous and previous[0] == stat.st_size and time.time() - previous[1] >= stable_seconds:
                    return path.resolve()
                observed[resolved] = (stat.st_size, previous[1] if previous and previous[0] == stat.st_size else time.time())
            time.sleep(0.5)
        raise TimeoutError("No new stable application output was detected")

    def show_output(self, path: Path | None = None) -> Path:
        if path is None:
            path = self.wait_for_output(timeout=0)
        capabilities = self.capabilities()
        preview_operation = next(
            (name for name in ("preview_output", "preview_result", "show_output") if name in capabilities),
            None,
        )
        if preview_operation is None:
            raise RuntimeError("Generated driver does not expose a preview/show-output capability")
        self.execute_operation(preview_operation, str(path))
        return path.resolve()

    def close(self) -> None:
        if self.process is None:
            return
        try:
            self._request("close")
        except Exception:
            pass
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self._log_handle is not None:
            self._log_handle.close()
        self.process = None
