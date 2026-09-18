from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from factory.adapters.grizzlymax.adapter import GrizzlyMaxAdapter
from factory.capture.ffmpeg_recorder import FFmpegRecorder
from factory.voice.providers.sapi import SapiVoiceProvider


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    smoke_root = root / "logs" / f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    (smoke_root / "state").mkdir(parents=True, exist_ok=True)
    (smoke_root / "generated_examples").mkdir(parents=True, exist_ok=True)
    app_root = Path(r"D:\ggf-apps\grizzly-max\MiniMax_H3_Standalone_app")
    ffmpeg = Path(shutil.which("ffmpeg") or app_root / "presets" / "bin" / "ffmpeg.exe")
    ffprobe = Path(shutil.which("ffprobe") or app_root / "presets" / "bin" / "ffprobe.exe")
    adapter = GrizzlyMaxAdapter(app_root, smoke_root)
    capture = smoke_root / "window_capture.mp4"
    try:
        adapter.launch()
        state = adapter.state()
        recorder = FFmpegRecorder(ffmpeg)
        recorder.start(capture, state["window_rect"], state["window_title"])
        time.sleep(3.0)
        recorder.stop()
    finally:
        adapter.close()
    voice = SapiVoiceProvider(preferred_voice="zira", rate=170).synthesize(
        "GGF Tutorial Factory narration test.", smoke_root / "narration.wav"
    )
    probe = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(capture)],
        capture_output=True, text=True, check=True,
    )
    report = {"capture": str(capture), "voice": str(voice), "media": json.loads(probe.stdout)}
    (smoke_root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"SMOKE_OK={smoke_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

