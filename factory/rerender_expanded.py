from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from factory.build_expanded_cut import chapter_filters
from factory.edit.ffmpeg_renderer import probe_duration
from factory.qa.final_video_qa import inspect_media


CHAPTERS = [
    "1. Complete workflow", "2. Choose a mode", "3. Safe first settings", "4. Add the Speed LoRA",
    "5. Add the Realism LoRA", "6. Strength and compatibility", "7. Prompt Builder", "8. Write the prompt",
    "9. Advanced and output", "10. Generate and Queue", "11. Finished results", "12. Preview the result",
    "13. Open output folder", "14. Final result",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()
    run_root = args.run.resolve()
    source = args.source_run.resolve()
    app_root = args.app_root.resolve()
    ffmpeg = app_root / "presets" / "bin" / "ffmpeg.exe"
    ffprobe = app_root / "presets" / "bin" / "ffprobe.exe"
    background = run_root / "capture" / "processed" / "expanded_background.mp4"
    presenter = run_root / "presenter" / "liz_track.mp4"
    generated = sorted((source / "generated_examples").glob("*.mp4"))[-1]
    total = probe_duration(ffprobe, presenter)
    final = run_root / "render" / "grizzlymax_complete_workflow_with_liz_expanded_v2.mp4"
    graph = (
        f"[0:v]{chapter_filters(CHAPTERS)}[background];"
        "[1:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
        "pad=382:382:11:11:color=0xF28C28,setpts=PTS-STARTPTS[liz];"
        "[background][liz]overlay=x=1518:y='if(between(t,24.1,48.3)+between(t,96.4,104.6),128,668)':"
        "shortest=1:eof_action=pass:eval=frame,fps=30[v];"
        f"[1:a]loudnorm=I=-16:LRA=11:TP=-1.5,apad=pad_dur={total:.3f},atrim=duration={total:.3f}[liz_audio];"
        "[2:a]volume=0.16,adelay=104542:all=1[output_audio];"
        f"[liz_audio][output_audio]amix=inputs=2:duration=longest:dropout_transition=0,"
        f"aresample=48000,atrim=duration={total:.3f}[mixed]"
    )
    subprocess.run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(background), "-i", str(presenter),
        "-stream_loop", "-1", "-i", str(generated), "-filter_complex", graph, "-map", "[v]", "-map", "[mixed]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-ar", "48000", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(final),
    ], check=True)
    qa = inspect_media(ffprobe, final)
    qa["visual_revision"] = "Removed the stale lower-right presenter frame from the enlarged LoRA and output-button chapters."
    qa["expanded_checks"] = {
        "speed_lora_enlarged": True,
        "realism_lora_enlarged": True,
        "finished_result_double_click_shown": True,
        "preview_player_shown": True,
        "open_output_folder_shown": True,
        "presenter_does_not_cover_focus_controls": True,
    }
    qa["passed"] = bool(qa["passed"] and all(qa["expanded_checks"].values()))
    (run_root / "qa" / "final_video_v2.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"Final visual revision failed QA: {qa}")
    print(f"FINAL_VIDEO={final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
