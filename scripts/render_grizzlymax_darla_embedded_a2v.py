"""Render the approved GrizzlyMax capture with native LTX Darla A2V clips."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from factory.edit.ffmpeg_renderer import has_audio_stream, probe_duration
from factory.edit.production_renderer import ProductionRenderer
from factory.qa.final_video_qa import inspect_media


ROOT = Path(r"D:\ggf-tools\GGF-Tutorial-Factory")
SOURCE = ROOT / "runs" / "2026-09-09_130121_grizzlymax_expanded-reference-text-workflows"


def action_rects() -> dict[str, list[int]]:
    events = json.loads((SOURCE / "timeline" / "actions.json").read_text(encoding="utf-8"))
    return {str(event["target"]): list(event["rect"]) for event in events if event.get("rect")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("presenter", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    presenter = args.presenter
    out = args.output or ROOT / "runs" / f"{datetime.now():%Y-%m-%d_%H%M%S}_grizzlymax_darla_embedded_a2v"
    ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
    ffprobe = Path(shutil.which("ffprobe") or "ffprobe")
    manifest = yaml.safe_load((ROOT / "projects" / "grizzlymax" / "tutorials" / "expanded-reference-text-workflows" / "tutorial.yaml").read_text(encoding="utf-8"))
    segments = manifest["narration"]["segments"]
    clips = [presenter / f"darla_ltx_a2v_{index:02d}.mp4" for index in range(1, len(segments) + 1)]
    provenance = [presenter / f"darla_ltx_a2v_{index:02d}.provenance.json" for index in range(1, len(segments) + 1)]
    missing = [str(path) for path in [*clips, *provenance] if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing supplied-audio native LTX presenter artifacts:\n" + "\n".join(missing))
    if not all(has_audio_stream(ffprobe, clip) for clip in clips):
        raise RuntimeError("A native LTX A2V presenter clip has no embedded audio stream")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in provenance]
    if any(record.get("post_generation_audio_replacement") is not False for record in records):
        raise RuntimeError("An input presenter provenance record permits post-generation audio replacement")
    durations = [probe_duration(ffprobe, clip) for clip in clips]
    out.mkdir(parents=True, exist_ok=False)
    renderer = ProductionRenderer(ffmpeg, ffprobe)
    track = renderer.join_presenter_clips(clips, out / "presenter" / "darla_ltx_a2v_track.mp4")
    chapters, cursor = [], 0.0
    for item, clip_duration in zip(segments, durations):
        chapters.append({"title": str(item["chapter"]), "start": cursor, "end": cursor + clip_duration, "presenter_position": str(item.get("presenter_position") or "lower-right")})
        cursor += clip_duration
    labels = {
        0: [("app.tabs.generation", "GENERATION WORKSPACE")], 1: [("generation.mode", "CHOOSE WORKFLOW"), ("generation.prompt", "WRITE THE PROMPT"), ("generation.generate", "CREATE THE JOB")],
        2: [("settings.fl2va_model.path", "FL2VA / TEXT MODEL"), ("settings.ref2va_model.path", "REF2VA MODEL")], 3: [("generation.mode", "REFERENCE TO VIDEO")],
        4: [("generation.references.images.add", "CLICK ADD IMAGE")], 5: [("generation.prompt", "REFERENCE MOTION PROMPT")],
        6: [("generation.resolution", "SAFE RESOLUTION"), ("generation.frames", "124 FRAMES"), ("generation.steps", "10 STEPS")],
        7: [("generation.lora1.path", "ACTIVE SPEED LORA")], 8: [("generation.lora2.path", "ACTIVE REALISM LORA"), ("generation.lora2.strength", "STRENGTH 0.65")],
        9: [("generation.generate", "GENERATE REF2VA")], 10: [("generation.mode", "TEXT TO VIDEO")], 11: [("generation.prompt", "TEXT-TO-VIDEO PROMPT")],
        12: [("generation.generate", "GENERATE T2VA")], 13: [("app.tabs.queue", "RUNNING AND PENDING JOBS")],
        14: [("queue.finished.first", "DOUBLE-CLICK REF2VA RESULT")], 15: [("queue.finished.last", "DOUBLE-CLICK T2VA RESULT")], 16: [("generation.open_output_folder", "OPEN OUTPUT FOLDER")],
    }
    rect, focus = action_rects(), []
    for chapter_index, items in labels.items():
        for item_index, (target, label) in enumerate(items):
            span = float(chapters[chapter_index]["end"]) - float(chapters[chapter_index]["start"])
            start = float(chapters[chapter_index]["start"]) + 0.35 + span * item_index / len(items)
            end = float(chapters[chapter_index]["start"]) + span * (item_index + 1) / len(items) - 0.18
            if target in rect:
                focus.append({"start": start, "end": end, "rect": rect[target], "label": label, "closeup": False})
    raw = SOURCE / "capture" / "raw" / "expanded_reference_text_ui.mp4"
    ref = SOURCE / "generated_examples" / "minimax_h3_ref2va_int4_20260909_134226.mp4"
    text = SOURCE / "generated_examples" / "minimax_h3_int4_20260909_134250.mp4"
    folder = SOURCE / "qa" / "screenshots" / "open_output_folder.png"
    background = out / "capture" / "grizzlymax_ui.mp4"
    renderer.assemble_background([
        {"source": raw, "duration": float(chapters[14]["start"])}, {"source": ref, "duration": durations[14]},
        {"source": text, "duration": durations[15]}, {"source": folder, "duration": durations[16]}, {"source": text, "duration": durations[17]},
    ], background)
    final = out / "render" / "grizzlymax_expanded_reference_and_text_with_darla.mp4"
    renderer.render(background, track, final, chapters, [0, 0, 2560, 1440], focus)
    qa = inspect_media(ffprobe, final)
    qa.update({"native_ltx_a2v": True, "embedded_darla_audio_source": True, "post_generation_voice_replacement": False, "presenter_segments": len(clips), "presenter_clip_durations": durations, "presenter_provenance": records, "real_reference_output": str(ref), "real_text_output": str(text)})
    qa["passed"] = bool(qa["passed"] and qa["native_ltx_a2v"] and qa["embedded_darla_audio_source"] and qa["presenter_segments"] == 18)
    (out / "qa").mkdir(exist_ok=True)
    (out / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    renderer.create_contact_sheet(final, chapters, out / "qa" / "chapter_contact_sheet.png")
    if not qa["passed"]:
        raise RuntimeError(json.dumps(qa, indent=2))
    print(f"FINAL_VIDEO={final}")


if __name__ == "__main__":
    main()
