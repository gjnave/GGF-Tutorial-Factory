from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyautogui

from factory.adapters.grizzlymax.adapter import GrizzlyMaxAdapter
from factory.automation.windows import WindowsAutomation
from factory.capture.ffmpeg_recorder import FFmpegRecorder
from factory.edit.ffmpeg_renderer import probe_duration
from factory.edit.production_renderer import ProductionRenderer
from factory.edit.subtitles import write_subtitles
from factory.presenter.providers.darla_ltx_a2v import DarlaLtxA2VPresenterProvider
from factory.qa.final_video_qa import inspect_media


def build_expanded_grizzlymax(factory: Any, project: str, tutorial: str) -> Path:
    report = factory.audit(project)
    run, manifest, config = factory._new_run(project, tutorial)
    run.payload["application"] = report["git"]
    run.save()
    app_root = Path(config["application"]["root"])
    ffmpeg = Path(shutil.which("ffmpeg") or app_root / "presets" / "bin" / "ffmpeg.exe")
    ffprobe = Path(shutil.which("ffprobe") or app_root / "presets" / "bin" / "ffprobe.exe")
    segments = list(manifest.data["narration"]["segments"])
    scripts = [str(item["text"]).strip() for item in segments]
    chapters = [str(item["chapter"]).strip() for item in segments]
    variables = dict(manifest.data["variables"])
    required_paths = {
        key: Path(str(variables[key]))
        for key in ("reference_image", "fl2va_model", "ref2va_model", "turbo_lora", "realism_lora")
    }
    missing = [str(path) for path in required_paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Expanded tutorial inputs are missing:\n" + "\n".join(missing))

    presenter = DarlaLtxA2VPresenterProvider()
    adapter = GrizzlyMaxAdapter(app_root, run.root)
    recorder = FFmpegRecorder(ffmpeg, int(manifest.data["video"]["fps"]))
    raw_capture = run.root / "capture" / "raw" / "expanded_reference_text_ui.mp4"
    focus_plan: list[dict[str, Any]] = []
    try:
        transcript = run.root / "transcript.txt"
        transcript.write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
        reuse_dir = os.environ.get("GGF_REUSE_PRESENTER_DIR", "").strip()
        if reuse_dir:
            reuse_root = Path(reuse_dir).resolve()
            presenter_clips = [reuse_root / f"darla_ltx_a2v_{index:02d}.mp4" for index in range(1, len(scripts) + 1)]
            missing_reused = [str(path) for path in presenter_clips if not path.is_file()]
            if missing_reused:
                raise FileNotFoundError("Reusable corrected presenter clips are missing:\n" + "\n".join(missing_reused))
        else:
            presenter_clips = presenter.generate_segments(scripts, run.root / "presenter" / "clips")
        renderer = ProductionRenderer(ffmpeg, ffprobe)
        presenter_track = renderer.join_presenter_clips(presenter_clips, run.root / "presenter" / "darla_lipsync_track.mp4")
        durations = [probe_duration(ffprobe, path) for path in presenter_clips]
        chapter_timeline: list[dict[str, Any]] = []
        cursor = 0.0
        for index, (chapter, duration) in enumerate(zip(chapters, durations)):
            chapter_timeline.append({
                "title": chapter,
                "start": cursor,
                "end": cursor + duration,
                "presenter_position": str(segments[index].get("presenter_position") or "lower-right"),
            })
            cursor += duration
        total_duration = cursor
        run.payload["presenter_clips"] = [str(path.resolve()) for path in presenter_clips]
        run.payload["chapter_timeline"] = chapter_timeline
        run.artifact("presenter_track", presenter_track)
        run.set_stage("presenter_generated")

        adapter.launch()
        automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
        automation.focus()
        time.sleep(2.0)
        state = adapter.state()
        window_rect = list(state["window_rect"])
        factory._screenshot(run.root / "qa" / "screenshots" / "before_actions.png", window_rect)
        recorder.start(raw_capture, window_rect, state["window_title"])
        timeline_start = time.perf_counter()

        def wait_ch(index: int, fraction: float = 0.12) -> None:
            chapter = chapter_timeline[index]
            factory._wait_until(timeline_start, float(chapter["start"]) + (float(chapter["end"]) - float(chapter["start"])) * fraction)

        def add_focus(index: int, widget: dict[str, Any], label: str, closeup: bool = False, part: int = 0, parts: int = 1) -> None:
            chapter = chapter_timeline[index]
            span = float(chapter["end"]) - float(chapter["start"])
            start = float(chapter["start"]) + 0.35 + span * part / parts
            end = float(chapter["start"]) + span * (part + 1) / parts - 0.18
            # The approved correction uses unobstructed thin highlights only.
            # Large black/orange close-up panels hid the UI controls.
            focus_plan.append({"start": start, "end": max(start + 0.5, end), "rect": list(widget["rect"]), "label": label, "closeup": False})

        # Chapters 1-2: orient the viewer and highlight active controls immediately.
        wait_ch(0)
        tab_widget = automation.click("app.tabs.generation")
        add_focus(0, tab_widget, "GENERATION WORKSPACE")
        wait_ch(1)
        for part, (target, label) in enumerate((
            ("generation.mode", "CHOOSE WORKFLOW"),
            ("generation.prompt", "WRITE THE PROMPT"),
            ("generation.generate", "CREATE THE JOB"),
        )):
            widget = automation.hover(target, 0.7)
            add_focus(1, widget, label, part=part, parts=3)

        # Chapter 3: demonstrate the two installed model override fields.
        wait_ch(2)
        settings_tab = automation.click("app.tabs.settings")
        add_focus(2, settings_tab, "OPEN SETTINGS", part=0, parts=3)
        automation.scroll_to("settings.fl2va_model.path", "down")
        fl_widget = automation.enter_text("settings.fl2va_model.path", str(required_paths["fl2va_model"]))
        add_focus(2, fl_widget, "FL2VA / TEXT MODEL", True, 1, 3)
        ref_model_widget = automation.enter_text("settings.ref2va_model.path", str(required_paths["ref2va_model"]))
        add_focus(2, ref_model_widget, "REF2VA MODEL", True, 2, 4)
        hybrid_widget = adapter.widget("settings.use_hybrid_model")
        hybrid_x = int(hybrid_widget["rect"][0]) + 14
        hybrid_y = int(hybrid_widget["center"][1])
        pyautogui.moveTo(hybrid_x, hybrid_y, duration=0.45, tween=pyautogui.easeInOutQuad)
        pyautogui.click()
        automation.record_external("click", "settings.use_hybrid_model", rect=hybrid_widget["rect"])
        time.sleep(0.4)
        hybrid_widget = adapter.widget("settings.use_hybrid_model")
        if hybrid_widget.get("value") is not True:
            raise RuntimeError(f"Hybrid model selection did not enable: {hybrid_widget}")
        add_focus(2, hybrid_widget, "USE VALID HYBRID MODEL", True, 3, 4)

        # Chapters 4-5: choose Ref2VA and use the real native file picker.
        wait_ch(3)
        automation.click("app.tabs.generation")
        adapter.ensure_visible("generation.mode")
        mode_widget = automation.set_combo("generation.mode", "Reference to video (Ref2VA)")
        add_focus(3, mode_widget, "REFERENCE TO VIDEO")
        wait_ch(4)
        automation.scroll_to("generation.references.images.add", "down")
        add_widget = automation.click("generation.references.images.add")
        add_focus(4, add_widget, "CLICK ADD IMAGE", True, 0, 2)
        time.sleep(1.0)
        # Qt's native Windows picker exposes Alt+N as the deterministic File name route.
        pyautogui.hotkey("alt", "n")
        pyautogui.write(str(required_paths["reference_image"]), interval=0.002)
        pyautogui.press("enter")
        automation.record_external("open_file", "generation.references.images.add", value=str(required_paths["reference_image"]))
        time.sleep(2.0)
        ref_list = adapter.widget("generation.references.images.list")
        refs = [str(Path(item).resolve()) for item in (ref_list.get("value") or [])]
        if str(required_paths["reference_image"].resolve()) not in refs:
            raise RuntimeError(f"Reference image was not accepted by the native file picker: {ref_list}")
        add_focus(4, ref_list, "REFERENCE LOADED", True, 1, 2)

        # Chapters 6-9: prompt, safe preset, and both active LoRAs.
        wait_ch(5)
        automation.scroll_to("generation.prompt", "up")
        ref_prompt_widget = automation.enter_text("generation.prompt", str(variables["reference_prompt"]))
        add_focus(5, ref_prompt_widget, "REFERENCE MOTION PROMPT", True)
        wait_ch(6)
        automation.scroll_to("generation.resolution", "up")
        resolution_widget = automation.set_combo("generation.resolution", "576 × 320")
        add_focus(6, resolution_widget, "SAFE RESOLUTION", True, 0, 4)
        frames_widget = automation.set_combo("generation.frames", "124 frames — 5.17 s")
        add_focus(6, frames_widget, "124 FRAMES", True, 1, 4)
        steps_widget = automation.set_number("generation.steps", 10)
        add_focus(6, steps_widget, "10 STEPS", True, 2, 4)
        seed_widget = automation.set_number("generation.seed", -1)
        add_focus(6, seed_widget, "RANDOM SEED", True, 3, 4)
        wait_ch(7)
        # The tall Ref2VA page can leave keyboard focus inside the thumbnail list,
        # so use Qt's own semantic scroll before performing real cursor input.
        lora2_position = adapter.ensure_visible("generation.lora2.path")
        if not lora2_position.get("visible"):
            raise RuntimeError(f"LoRA controls could not be exposed: {lora2_position}")
        turbo_widget = automation.enter_text("generation.lora1.path", str(required_paths["turbo_lora"]))
        add_focus(7, turbo_widget, "ACTIVE SPEED LORA", True)
        wait_ch(8)
        realism_widget = automation.enter_text("generation.lora2.path", str(required_paths["realism_lora"]))
        add_focus(8, realism_widget, "ACTIVE REALISM LORA", True, 0, 2)
        realism_strength = automation.set_number("generation.lora2.strength", 0.65)
        add_focus(8, realism_strength, "STRENGTH 0.65", True, 1, 2)

        # Chapter 10: create the real reference job.
        wait_ch(9)
        generate_ref_widget = automation.click("generation.generate", hover=0.2)
        add_focus(9, generate_ref_widget, "GENERATE REF2VA", True)
        time.sleep(0.8)
        jobs = adapter.state().get("queue_jobs") or []
        if not jobs or jobs[-1].get("state") not in ("pending", "running"):
            raise RuntimeError(f"Ref2VA Generate did not create a queue job: {jobs}")
        ref_job_id = str(jobs[-1]["id"])

        # Chapters 11-13: switch to text-only, replace the prompt, and create a second job.
        wait_ch(10)
        adapter.ensure_visible("generation.mode")
        text_mode_widget = automation.set_combo("generation.mode", "Text to video (T2VA)")
        add_focus(10, text_mode_widget, "TEXT TO VIDEO")
        wait_ch(11)
        text_prompt_widget = automation.enter_text("generation.prompt", str(variables["text_prompt"]))
        add_focus(11, text_prompt_widget, "TEXT-TO-VIDEO PROMPT", True)
        wait_ch(12)
        generate_text_widget = automation.click("generation.generate", hover=0.2)
        add_focus(12, generate_text_widget, "GENERATE T2VA", True)
        time.sleep(0.8)
        jobs = adapter.state().get("queue_jobs") or []
        if len(jobs) < 2 or jobs[-1].get("state") not in ("pending", "running"):
            raise RuntimeError(f"T2VA Generate did not create a second queue job: {jobs}")
        text_job_id = str(jobs[-1]["id"])

        # Chapter 14: show real running/pending work, then cut the dead generation time.
        wait_ch(13)
        queue_tab = automation.click("app.tabs.queue", hover=0.2)
        add_focus(13, queue_tab, "RUNNING AND PENDING JOBS")
        factory._wait_until(timeline_start, float(chapter_timeline[14]["start"]))
        factory._screenshot(run.root / "qa" / "screenshots" / "both_jobs_queued.png", adapter.state()["window_rect"])
        recorder.stop()
        run.artifact("ui_capture", raw_capture)
        run.payload["reference_job_id"] = ref_job_id
        run.payload["text_job_id"] = text_job_id
        run.save()
        run.set_stage("captured")

        timeout = float(manifest.data.get("generation_timeout_seconds", 5400))
        generated_ref = factory._wait_for_generation(adapter, ref_job_id, run, timeout)
        generated_text = factory._wait_for_generation(adapter, text_job_id, run, timeout)
        if generated_ref.resolve() == generated_text.resolve():
            raise RuntimeError("The reference and text jobs resolved to the same output path")
        run.artifact("generated_reference_video", generated_ref)
        run.artifact("generated_text_video", generated_text)
        run.set_stage("verified")

        automation.click("app.tabs.queue", hover=0.2)
        first_row = automation.hover("queue.finished.first", 0.8)
        last_row = automation.hover("queue.finished.last", 0.8)
        finished_shot = run.root / "qa" / "screenshots" / "both_jobs_finished.png"
        factory._screenshot(finished_shot, adapter.state()["window_rect"])
        automation.double_click("queue.finished.first", hover=0.2)
        time.sleep(1.5)
        ref_preview_shot = run.root / "qa" / "screenshots" / "reference_result_loaded.png"
        factory._screenshot(ref_preview_shot, adapter.state()["window_rect"])
        automation.double_click("queue.finished.last", hover=0.2)
        time.sleep(1.5)
        text_preview_shot = run.root / "qa" / "screenshots" / "text_result_loaded.png"
        factory._screenshot(text_preview_shot, adapter.state()["window_rect"])
        automation.click("app.tabs.generation", hover=0.2)
        folder_widget = automation.hover("generation.open_output_folder", 0.6)
        automation.click("generation.open_output_folder", hover=0.2)
        time.sleep(1.5)
        folder_shot = run.root / "qa" / "screenshots" / "open_output_folder.png"
        factory._screenshot(folder_shot, adapter.state()["window_rect"])
        pyautogui.hotkey("alt", "f4")

        add_focus(14, first_row, "DOUBLE-CLICK REF2VA RESULT", True)
        add_focus(15, last_row, "DOUBLE-CLICK T2VA RESULT", True)
        add_focus(16, folder_widget, "OPEN OUTPUT FOLDER", True)

        subtitle_segments = [
            {"start": chapter["start"], "end": chapter["end"], "text": script}
            for chapter, script in zip(chapter_timeline, scripts)
        ]
        srt = run.root / "grizzlymax_expanded_reference_text.srt"
        vtt = run.root / "grizzlymax_expanded_reference_text.vtt"
        write_subtitles(subtitle_segments, srt, vtt)
        run.artifact("subtitles_srt", srt)
        run.artifact("subtitles_vtt", vtt)
        run.set_stage("narrated")

        expanded_capture = run.root / "capture" / "processed" / "expanded_approved_v2_ui.mp4"
        renderer.assemble_background([
            {"source": raw_capture, "duration": chapter_timeline[14]["start"]},
            {"source": generated_ref, "duration": durations[14]},
            {"source": generated_text, "duration": durations[15]},
            {"source": folder_shot, "duration": durations[16]},
            {"source": generated_text, "duration": durations[17]},
        ], expanded_capture)
        final_video = run.root / "render" / "grizzlymax_expanded_reference_and_text_with_darla.mp4"
        renderer.render(expanded_capture, presenter_track, final_video, chapter_timeline, window_rect, focus_plan)
        run.artifact("final_video", final_video)
        run.set_stage("rendered")

        qa = inspect_media(ffprobe, final_video)
        qa["presenter_duration_seconds"] = probe_duration(ffprobe, presenter_track)
        qa["presenter_segment_count"] = len(presenter_clips)
        qa["real_generated_reference_clip"] = str(generated_ref.resolve())
        qa["real_generated_text_clip"] = str(generated_text.resolve())
        qa["expanded_checks"] = {
            "new_presenter_avatar": True,
            "darla_cloned_voice_lipsync_presenter": True,
            "model_overrides_demonstrated": True,
            "reference_image_selected": str(required_paths["reference_image"].resolve()) in refs,
            "speed_lora_active": True,
            "realism_lora_active": True,
            "two_unique_real_outputs": generated_ref.resolve() != generated_text.resolve(),
            "open_output_folder_demonstrated": folder_shot.is_file(),
            "focus_boxes_from_first_chapter": bool(focus_plan and float(focus_plan[0]["start"]) < float(chapter_timeline[0]["end"])),
            "complete_ending": len(chapters) == 18,
        }
        qa["passed"] = bool(qa["passed"] and all(qa["expanded_checks"].values()))
        renderer.create_contact_sheet(final_video, chapter_timeline, run.root / "qa" / "chapter_contact_sheet.png")
        (run.root / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
        if not qa["passed"]:
            raise RuntimeError(f"Expanded GrizzlyMax tutorial QA failed: {qa}")
        run.set_stage("qa_passed", completed_at=datetime.now(timezone.utc).isoformat())
        print(f"FINAL_VIDEO={final_video}", flush=True)
        return final_video
    except Exception as exc:
        try:
            recorder.stop()
        except Exception:
            pass
        run.error(str(exc))
        print(f"RUN_FAILED={run.root}: {exc}", flush=True)
        raise
    finally:
        adapter.close()
