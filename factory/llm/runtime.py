from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


class LocalQwenRuntime:
    """Own the local reasoning server for one Tutorial Factory session."""

    def __init__(self, config: dict[str, Any], factory_root: Path):
        self.config = config
        self.factory_root = factory_root.resolve()
        self.process: subprocess.Popen[Any] | None = None
        self._log_handle: Any | None = None

    @property
    def endpoint(self) -> str:
        return str(self.config.get("endpoint") or "http://127.0.0.1:28084/v1").rstrip("/")

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.endpoint.removesuffix("/v1") + "/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    @staticmethod
    def _config_value(app_root: Path, key: str) -> str:
        script = app_root / "scripts" / "print-config.js"
        result = subprocess.run(
            ["node", str(script), key], cwd=app_root, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def ensure_started(self, timeout_seconds: float = 600) -> bool:
        if self.available():
            return False
        app_root = Path(str(self.config.get("runtime_root") or "")).resolve()
        llama = app_root / "runtime" / "llama.cpp" / "llama-server.exe"
        if not llama.is_file():
            raise FileNotFoundError(f"Tutorial Factory's local reasoning engine is not installed: {llama}")
        model_file = Path(self._config_value(app_root, "modelFile"))
        model = self._config_value(app_root, "model")
        context = self._config_value(app_root, "context")
        if not model_file.is_file():
            raise FileNotFoundError(f"Tutorial Factory's local reasoning model is missing: {model_file}")
        log_path = self.factory_root / "logs" / "local-reasoning.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_handle = log_path.open("a", encoding="utf-8", errors="replace")
        command = [
            str(llama), "-m", str(model_file), "--alias", model,
            "--host", "127.0.0.1", "--port", "28084", "-ngl", "999", "-c", context,
            "--jinja", "--reasoning", "off", "--reasoning-format", "none",
            "--parallel", "1", "--cont-batching",
        ]
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.process = subprocess.Popen(
            command, cwd=app_root, stdout=self._log_handle, stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Local reasoning engine exited with code {self.process.returncode}; see {log_path}")
            if self.available():
                return True
            time.sleep(2)
        raise TimeoutError(f"Local reasoning engine did not become ready; see {log_path}")

    def release(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def audit(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "started_by_factory": self.process is not None,
            "available": self.available(),
        }
