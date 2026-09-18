from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import pyautogui

from factory.adapters.grizzlymax.adapter import GrizzlyMaxAdapter
from factory.automation.windows import WindowsAutomation
from factory.capture.ffmpeg_recorder import FFmpegRecorder


def _try_screenshot(path: Path, region: tuple[int, int, int, int] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            pyautogui.screenshot(region=region).save(path)
            return
        except OSError:
            time.sleep(1.0)
    print(f"SCREENSHOT_SKIPPED={path}", flush=True)


def _prepare_isolated_run(source_run: Path, output_run: Path) -> Path:
    output_run.mkdir(parents=True, exist_ok=False)
    state_dir = output_run / "state"
    media_dir = output_run / "generated_examples"
    capture_dir = output_run / "capture" / "raw"
    qa_dir = output_run / "qa" / "screenshots"
    for path in (state_dir, media_dir, capture_dir, qa_dir, output_run / "timeline"):
        path.mkdir(parents=True, exist_ok=True)

    source_queue = json.loads((source_run / "state" / "minimax_h3_queue.json").read_text(encoding="utf-8"))
    jobs = list(source_queue.get("jobs") or [])
    finished = next((job for job in reversed(jobs) if job.get("state") == "finished"), None)
    if finished is None:
        raise RuntimeError("The source tutorial run has no finished queue item")
    source_media = Path(str(finished.get("output", "")))
    if not source_media.is_file():
        candidates = sorted((source_run / "generated_examples").glob("*.mp4"))
        if not candidates:
            raise FileNotFoundError("The source tutorial run has no generated MP4")
        source_media = candidates[-1]
    copied_media = media_dir / source_media.name
    shutil.copy2(source_media, copied_media)
    finished["output"] = str(copied_media.resolve())
    source_queue["jobs"] = [finished]
    (state_dir / "minimax_h3_queue.json").write_text(json.dumps(source_queue, indent=2), encoding="utf-8")
    (state_dir / "minimax_h3_loras.json").write_text(
        json.dumps({"version": 1, "loras": [{"path": "", "strength": 1.0} for _ in range(3)]}, indent=2),
        encoding="utf-8",
    )
    return copied_media


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-run", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()

    source_run = args.source_run.resolve()
    output_run = args.output_run.resolve()
    app_root = args.app_root.resolve()
    _prepare_isolated_run(source_run, output_run)

    ffmpeg = app_root / "presets" / "bin" / "ffmpeg.exe"
    adapter = GrizzlyMaxAdapter(app_root, output_run)
    recorder = FFmpegRecorder(ffmpeg, 30)
    raw_capture = output_run / "capture" / "raw" / "finished_outputs_and_folder.mp4"
    try:
        adapter.launch()
        automation = WindowsAutomation(adapter, output_run / "timeline" / "output_actions.json")
        automation.focus()
        time.sleep(2.0)
        state = adapter.state()
        x, y, width, height = [int(value) for value in state["window_rect"]]
        _try_screenshot(output_run / "qa" / "screenshots" / "before_output_actions.png", (x, y, width, height))
        recorder.start(raw_capture, state["window_rect"], state["window_title"])

        automation.click("app.tabs.queue")
        time.sleep(2.0)
        automation.hover("queue.finished.first", 1.5)
        automation.double_click("queue.finished.first")
        time.sleep(5.0)
        _try_screenshot(output_run / "qa" / "screenshots" / "finished_item_preview.png", (x, y, width, height))

        automation.click("app.tabs.generation")
        time.sleep(1.0)
        automation.hover("generation.open_output_folder", 1.2)
        automation.click("generation.open_output_folder")
        time.sleep(2.0)
        pyautogui.hotkey("alt", "tab")
        time.sleep(4.0)
        _try_screenshot(output_run / "qa" / "screenshots" / "output_folder_open.png")
        recorder.stop()
        print(f"SUPPLEMENTAL_CAPTURE={raw_capture}", flush=True)
        return 0
    finally:
        try:
            recorder.stop()
        except Exception:
            pass
        active_title = str(pyautogui.getActiveWindowTitle() or "")
        if "explorer" in active_title.lower() or "generated_examples" in active_title.lower():
            pyautogui.hotkey("alt", "f4")
            time.sleep(0.5)
        adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
