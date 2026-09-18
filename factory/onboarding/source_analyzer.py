from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FRAMEWORK_PATTERNS = {
    "qt": (r"\bPySide6\b", r"\bPyQt6\b", r"\bPyQt5\b", r"\bQApplication\b"),
    "gradio": (r"\bgradio\b", r"\bgr\.Blocks\b", r"\bgr\.Interface\b"),
    "browser": (r"\bFlask\b", r"\bFastAPI\b", r"<html[ >]"),
    "electron": (r"\bBrowserWindow\b", r"\belectron\b"),
    "tkinter": (r"\btkinter\b", r"\bTk\("),
}

QT_CONTROL_TYPES = {
    "QPushButton": "Button",
    "QToolButton": "Button",
    "QComboBox": "ComboBox",
    "QLineEdit": "Edit",
    "QTextEdit": "Edit",
    "QPlainTextEdit": "Edit",
    "QSpinBox": "Spinner",
    "QDoubleSpinBox": "Spinner",
    "QCheckBox": "CheckBox",
    "QRadioButton": "RadioButton",
    "QTabWidget": "Tab",
    "QListWidget": "List",
}


@dataclass(frozen=True)
class SourceAnalysis:
    source_root: Path
    framework: str
    entrypoint: Path | None
    python: Path | None
    window_title: str | None
    controls: dict[str, dict[str, Any]]
    output_directories: list[Path]
    workflow: dict[str, Any]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": str(self.source_root),
            "framework": self.framework,
            "entrypoint": str(self.entrypoint) if self.entrypoint else None,
            "python": str(self.python) if self.python else None,
            "window_title": self.window_title,
            "controls": self.controls,
            "output_directories": [str(path) for path in self.output_directories],
            "workflow": self.workflow,
            "evidence": self.evidence,
        }


class SourceAnalyzer:
    """Deterministic first-pass analyzer; no application-specific Python is emitted."""

    def analyze(self, source_root: Path) -> SourceAnalysis:
        root = source_root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        files = self._source_files(root)
        samples: dict[Path, str] = {}
        framework_scores = {key: 0 for key in FRAMEWORK_PATTERNS}
        for path in files:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            samples[path] = text
            for framework, patterns in FRAMEWORK_PATTERNS.items():
                framework_scores[framework] += sum(len(re.findall(pattern, text, re.IGNORECASE)) for pattern in patterns)
        framework = self._choose_framework(samples, framework_scores)
        entrypoint = self._entrypoint(root, samples, framework)
        python = self._python(root)
        window_title = self._window_title(samples, entrypoint)
        controls = self._qt_controls(samples) if framework == "qt" else self._web_controls(samples) if framework in {"gradio", "browser", "electron"} else {}
        outputs = self._outputs(root, samples)
        workflow = self._qt_workflow(samples, controls) if framework == "qt" else {}
        return SourceAnalysis(
            source_root=root,
            framework=framework,
            entrypoint=entrypoint,
            python=python,
            window_title=window_title,
            controls=controls,
            output_directories=outputs,
            workflow=workflow,
            evidence={
                "framework_scores": framework_scores,
                "source_files_scanned": len(samples),
                "entrypoint_reason": "GUI main guard and framework construction" if entrypoint else "not inferred",
                "control_count": len(controls),
            },
        )

    @staticmethod
    def _choose_framework(samples: dict[Path, str], scores: dict[str, int]) -> str:
        # Prefer an executable native entry point over aggregate repository counts.
        # Many products ship both a desktop UI and an optional Gradio/web UI.
        for text in samples.values():
            if "if __name__" in text and "QApplication(" in text:
                return "qt"
        for text in samples.values():
            if "if __name__" in text and re.search(r"\b(gr\.Blocks|gr\.Interface|gradio)\b", text):
                return "gradio"
        if any(path.name == "package.json" and "electron" in text.lower() for path, text in samples.items()):
            return "electron"
        return max(scores, key=scores.get) if any(scores.values()) else "windows-uia"

    @staticmethod
    def _source_files(root: Path) -> list[Path]:
        result: list[Path] = []
        ignored = {
            ".git", ".venv", "venv", "runtime", "node_modules", "models", "checkpoints",
            "build", "dist", "__pycache__", "dependencies", "site-packages",
        }
        for current, directories, files in os.walk(root):
            directories[:] = sorted(name for name in directories if name.lower() not in ignored)
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".json"}:
                    continue
                try:
                    if path.stat().st_size <= 2_000_000:
                        result.append(path)
                except OSError:
                    continue
                if len(result) >= 3000:
                    return result
        return result[:3000]

    @staticmethod
    def _entrypoint(root: Path, samples: dict[Path, str], framework: str) -> Path | None:
        ranked: list[tuple[int, Path]] = []
        for path, text in samples.items():
            score = 0
            if "if __name__" in text:
                score += 5
            if framework == "qt" and "QApplication(" in text:
                score += 8
            if framework in {"gradio", "browser"} and re.search(r"\.(launch|run)\(", text):
                score += 6
            if path.name.lower() in {"app.py", "main.py", "server.py"}:
                score += 2
            if score:
                ranked.append((score, path))
        return max(ranked, default=(0, None), key=lambda item: (item[0], -len(item[1].parts) if item[1] else 0))[1]

    @staticmethod
    def _python(root: Path) -> Path | None:
        for rel in (".venv/Scripts/python.exe", "venv/Scripts/python.exe", "runtime/Scripts/python.exe", "python/python.exe"):
            candidate = root / rel
            if candidate.is_file():
                return candidate.resolve()
        return None

    @staticmethod
    def _window_title(samples: dict[Path, str], entrypoint: Path | None) -> str | None:
        candidates: list[tuple[int, str]] = []
        for path, text in samples.items():
            values = re.findall(
                r"setWindowTitle\([^\n]*?translate\(\s*[rubfRUBF]*[\"'][^\"']+[\"']\s*,\s*[rubfRUBF]*[\"']([^\"']+)",
                text,
            )
            values += re.findall(r"setWindowTitle\(\s*[rubfRUBF]*[\"']([^\"']+)", text)
            for symbol in re.findall(r"setWindowTitle\(\s*(\w+)\s*\)", text):
                value = re.search(rf"^\s*{re.escape(symbol)}\s*=\s*[rubfRUBF]*[\"']([^\"']+)", text, re.MULTILINE)
                if value:
                    values.append(value.group(1))
            for value in values:
                score = 0
                lower_parts = {part.lower() for part in path.parts}
                if entrypoint and path.resolve() == entrypoint.resolve():
                    score += 30
                if path.stem.lower() in {"main_window", "mainwindow", "main_ui"}:
                    score += 20
                if "launcher" in lower_parts or "launcher" in path.stem.lower() or "launcher" in value.lower():
                    score -= 15
                if "test" in lower_parts or "tests" in lower_parts:
                    score -= 30
                score += min(10, len(value.split()))
                candidates.append((score, value))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        for text in samples.values():
            match = re.search(r"<title[^>]*>\s*([^<]+?)\s*</title>", text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _web_controls(samples: dict[Path, str]) -> dict[str, dict[str, Any]]:
        controls: dict[str, dict[str, Any]] = {}
        tag_types = {"button": "Button", "input": "Edit", "textarea": "Edit", "select": "ComboBox"}
        pattern = re.compile(r"<(button|input|textarea|select)\b([^>]*)>(.*?)</(?:button|textarea|select)>|<(input)\b([^>]*)/?>", re.IGNORECASE | re.DOTALL)
        for path, text in samples.items():
            for index, match in enumerate(pattern.finditer(text)):
                tag = (match.group(1) or match.group(4) or "input").lower()
                attrs = match.group(2) or match.group(5) or ""
                body = re.sub(r"<[^>]+>", " ", match.group(3) or "").strip()
                identifier = re.search(r"\b(?:id|name)=[\"']([^\"']+)", attrs, re.IGNORECASE)
                placeholder = re.search(r"\bplaceholder=[\"']([^\"']+)", attrs, re.IGNORECASE)
                key = identifier.group(1) if identifier else f"{tag}_{index + 1}"
                selector: dict[str, Any] = {
                    "control_type": tag_types[tag],
                    "source_file": str(path),
                    "source_symbol": key,
                }
                if identifier:
                    selector["auto_id"] = identifier.group(1)
                elif body:
                    selector["title"] = body
                elif placeholder:
                    selector["title"] = placeholder.group(1)
                else:
                    selector["found_index"] = index
                controls.setdefault(f"ui.{key}", selector)
        return controls

    @staticmethod
    def _qt_controls(samples: dict[Path, str]) -> dict[str, dict[str, Any]]:
        controls: dict[str, dict[str, Any]] = {}
        type_counts: dict[str, int] = {}
        assignment = re.compile(r"self\.(\w+)\s*=\s*(Q\w+)\(([^\n]*)")
        quoted = re.compile(r"^[rubfRUBF]*[\"']([^\"']*)[\"']")
        for path, text in samples.items():
            tab_containers: dict[str, tuple[str, str]] = {}
            for tab_match in re.finditer(
                r"self\.(\w+)\.setTabText\(\s*self\.\w+\.indexOf\(self\.(\w+)\)\s*,\s*"
                r"(?:QCoreApplication\.)?translate\(\s*[rubfRUBF]*[\"'][^\"']+[\"']\s*,\s*"
                r"[rubfRUBF]*[\"']([^\"']+)[\"']",
                text,
            ):
                tab_containers[tab_match.group(2)] = (tab_match.group(1), tab_match.group(3))
            parents: dict[str, str] = {}
            for parent_match in assignment.finditer(text):
                parent = re.match(r"\s*self\.(\w+)", parent_match.group(3))
                if parent:
                    parents[parent_match.group(1)] = parent.group(1)
            for match in assignment.finditer(text):
                symbol, qt_type, arguments = match.groups()
                control_type = QT_CONTROL_TYPES.get(qt_type)
                if not control_type:
                    continue
                index = type_counts.get(control_type, 0)
                type_counts[control_type] = index + 1
                selector: dict[str, Any] = {
                    "control_type": control_type,
                    "found_index": index,
                    "source_symbol": symbol,
                    "source_file": str(path),
                }
                label = quoted.search(arguments.strip())
                if label and label.group(1):
                    selector["title"] = label.group(1)
                    selector.pop("found_index", None)
                object_name = re.search(rf"self\.{re.escape(symbol)}\.setObjectName\(\s*[rubfRUBF]*[\"']([^\"']+)", text)
                if object_name:
                    selector["object_name"] = object_name.group(1)
                    selector.pop("found_index", None)
                placeholder = re.search(rf"self\.{re.escape(symbol)}\.setPlaceholderText\(\s*[rubfRUBF]*[\"']([^\"']+)", text)
                if placeholder:
                    selector["help_text"] = placeholder.group(1)
                tooltip = re.search(rf"self\.{re.escape(symbol)}\.setToolTip\(\s*[rubfRUBF]*[\"']([^\"']+)", text)
                if tooltip:
                    selector["tooltip"] = tooltip.group(1)
                display = re.search(
                    rf"self\.{re.escape(symbol)}\.setText\([^\n]*?translate\(\s*[rubfRUBF]*[\"'][^\"']+[\"']\s*,\s*[rubfRUBF]*[\"']([^\"']+)",
                    text,
                ) or re.search(rf"self\.{re.escape(symbol)}\.setText\(\s*[rubfRUBF]*[\"']([^\"']+)", text)
                if display:
                    selector["label"] = display.group(1)
                values = re.search(rf"self\.{re.escape(symbol)}\.addItems\(\s*\[([^\]]+)\]", text)
                if values:
                    selector["values"] = re.findall(r"[\"']([^\"']+)[\"']", values.group(1))
                if re.search(rf"self\.{re.escape(symbol)}\.setEnabled\(\s*False\s*\)", text):
                    selector["initially_enabled"] = False
                if re.search(rf"self\.{re.escape(symbol)}\.setReadOnly\(\s*True\s*\)", text):
                    selector["read_only"] = True
                ancestor = parents.get(symbol)
                visited: set[str] = set()
                while ancestor and ancestor not in visited:
                    visited.add(ancestor)
                    if ancestor in tab_containers:
                        tab_control, tab_title = tab_containers[ancestor]
                        selector["container_symbol"] = ancestor
                        selector["container_control"] = f"ui.{tab_control}"
                        selector["container_title"] = tab_title
                        break
                    ancestor = parents.get(ancestor)
                controls[f"ui.{symbol}"] = selector
        return controls

    @staticmethod
    def _qt_workflow(samples: dict[Path, str], controls: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Infer workflow roles from Qt signal connections and handler data flow."""
        connections: list[dict[str, str]] = []
        all_text = "\n".join(samples.values())
        for path, text in samples.items():
            for match in re.finditer(
                r"self\.(\w+)\.(clicked|triggered|activated|currentIndexChanged|textChanged)\.connect\(self\.(\w+)\)",
                text,
            ):
                connections.append({
                    "control": f"ui.{match.group(1)}",
                    "signal": match.group(2),
                    "handler": match.group(3),
                    "source_file": str(path),
                })

        def connected_score(control_id: str, words: tuple[str, ...]) -> int:
            symbol = control_id.removeprefix("ui.")
            score = sum(2 for word in words if word in symbol.lower())
            for item in connections:
                if item["control"] == control_id:
                    haystack = f"{item['handler']} {symbol}".lower()
                    score += sum(3 for word in words if word in haystack)
            selector = controls[control_id]
            haystack = " ".join(str(selector.get(key, "")) for key in ("title", "label", "tooltip", "help_text")).lower()
            score += sum(2 for word in words if word in haystack)
            return score

        buttons = [key for key, value in controls.items() if value.get("control_type") == "Button"]
        generate = max(buttons, key=lambda key: connected_score(key, ("generate", "create", "render", "run", "start")), default=None)
        if generate and connected_score(generate, ("generate", "create", "render", "run", "start")) == 0:
            generate = None
        result = max(buttons, key=lambda key: connected_score(key, ("play", "preview", "open", "result")), default=None)
        if result and connected_score(result, ("play", "preview", "open", "result")) == 0:
            result = None

        input_controls: list[str] = []
        if generate:
            handler = next((item["handler"] for item in connections if item["control"] == generate), "")
            body = ""
            if handler:
                body_match = re.search(
                    rf"\n\s*def\s+{re.escape(handler)}\s*\([^)]*\)\s*(?:->\s*[^:]+)?\s*:(.*?)(?=\n\s*def\s+\w+\s*\(|\Z)",
                    all_text,
                    re.DOTALL,
                )
                body = body_match.group(1) if body_match else ""
            for control_id, selector in controls.items():
                symbol = control_id.removeprefix("ui.")
                if selector.get("control_type") in {"Edit", "ComboBox", "Spinner", "CheckBox"} and re.search(
                    rf"self\.{re.escape(symbol)}\.(?:text|toPlainText|currentText|value|isChecked)\(\)", body
                ):
                    input_controls.append(control_id)
        if not input_controls:
            input_controls = [
                key for key, selector in controls.items()
                if selector.get("control_type") == "Edit" and not any(word in key.lower() for word in ("output", "console", "path"))
            ][:3]

        output_control = next((
            key for key in controls
            if any(word in key.lower() for word in ("output_dir", "output_path", ".out"))
            and not any(word in key.lower() for word in ("log", "console"))
            and controls[key].get("control_type") == "Edit"
        ), None)
        completion_controls = [
            key for key, selector in controls.items()
            if selector.get("initially_enabled") is False and selector.get("control_type") == "Button"
        ]
        return {
            "signal_connections": connections,
            "generate_control": generate,
            "input_controls": input_controls,
            "output_control": output_control,
            "result_control": result,
            "completion_controls": completion_controls,
            "success_text_detected": bool(re.search(r"(?:generation|render|export).{0,30}(?:complete|finished|success)", all_text, re.IGNORECASE)),
        }

    @staticmethod
    def _outputs(root: Path, samples: dict[Path, str]) -> list[Path]:
        candidates: list[Path] = []
        for text in samples.values():
            for chain in re.findall(
                r"(?:self\.)?root((?:\s*/\s*[rubfRUBF]*[\"'][^\"']+[\"']){1,4})",
                text,
            ):
                parts = re.findall(r"[\"']([^\"']+)[\"']", chain)
                if parts and parts[0].lower() in {"output", "outputs", "result", "results"}:
                    path = root.joinpath(*parts).resolve()
                    if path not in candidates:
                        candidates.append(path)
            for value in re.findall(r"[\"'](outputs?|results?|generated_examples)[/\\]?[\"']", text, re.IGNORECASE):
                path = (root / value).resolve()
                if path not in candidates:
                    candidates.append(path)
        for name in ("output", "outputs", "results"):
            path = root / name
            if path.is_dir() and path.resolve() not in candidates:
                candidates.append(path.resolve())
        return candidates[:8]


def write_analysis(path: Path, analysis: SourceAnalysis) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(analysis.to_dict(), indent=2), encoding="utf-8")
