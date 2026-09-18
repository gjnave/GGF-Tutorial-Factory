from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from factory.adapters.base import ApplicationAdapter


class GrizzlyMaxAdapter(ApplicationAdapter):
    def __init__(self, app_root: Path, run_root: Path):
        self.app_root = app_root.resolve()
        self.run_root = run_root.resolve()
        self.port = self._free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.process: subprocess.Popen[str] | None = None

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @property
    def python(self) -> Path:
        return self.app_root / "environments" / ".minimax_h3_int4" / "python.exe"

    def launch(self) -> None:
        if not self.python.is_file():
            raise FileNotFoundError(f"GrizzlyMax Python environment not found: {self.python}")
        factory_root = Path(__file__).resolve().parents[3]
        env = os.environ.copy()
        env["GGF_TUTORIAL_MODE"] = "1"
        env["GGF_TUTORIAL_RUN_DIR"] = str(self.run_root)
        command = [
            str(self.python), "-m", "factory.adapters.grizzlymax.tutorial_host",
            "--app-root", str(self.app_root), "--run-dir", str(self.run_root),
            "--port", str(self.port),
        ]
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self.process = subprocess.Popen(command, cwd=factory_root, env=env, creationflags=flags)
        deadline = time.time() + 45
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"GrizzlyMax tutorial host exited with {self.process.returncode}")
            try:
                if self.get("/health").get("ok"):
                    return
            except Exception:
                time.sleep(0.25)
        raise TimeoutError("Timed out waiting for the GrizzlyMax tutorial bridge")

    def get(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(self.base_url + path, timeout=4) as response:
            return json.loads(response.read().decode("utf-8"))

    def widget(self, semantic_id: str) -> dict[str, Any]:
        from urllib.parse import quote
        return self.get("/v1/widget/" + quote(semantic_id, safe=""))

    def ensure_visible(self, semantic_id: str) -> dict[str, Any]:
        from urllib.parse import quote
        return self.get("/v1/ensure-visible/" + quote(semantic_id, safe=""))

    def state(self) -> dict[str, Any]:
        return self.get("/v1/state")

    def close(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        # Ask the dedicated tutorial host to close without touching any other GrizzlyMax instance.
        import ctypes
        state = self.state()
        hwnd = int(state["window_handle"])
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)
