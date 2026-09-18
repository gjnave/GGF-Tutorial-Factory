from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyautogui

from factory import __version__
from factory.adapters.grizzlymax.adapter import GrizzlyMaxAdapter
from factory.automation.windows import WindowsAutomation
from factory.capture.ffmpeg_recorder import FFmpegRecorder
from factory.core.manifest import TutorialManifest
from factory.core.run_state import RunState
from factory.edit.ffmpeg_renderer import FFmpegRenderer, probe_duration
from factory.edit.complete_renderer import CompleteTutorialRenderer
from factory.edit.production_renderer import ProductionRenderer
from factory.edit.subtitles import write_subtitles
from factory.presenter.providers.ltx25 import Ltx25LizPresenterProvider
from factory.qa.final_video_qa import inspect_media
from factory.voice.providers.sapi import SapiVoiceProvider


class TutorialFactory:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def project_root(self, project: str) -> Path:
        return self.root / "projects" / project

    def load_app_config(self, project: str) -> dict[str, Any]:
        import yaml
        path = self.project_root(project) / "app.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    @staticmethod
    def _git(app_root: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(app_root), *args], capture_output=True, text=True, check=True,
        ).stdout.strip()

    def audit(self, project: str) -> dict[str, Any]:
        config = self.load_app_config(project)
        app_root = Path(config["application"]["root"])
        python = app_root / "environments" / ".minimax_h3_int4" / "python.exe"
        ffmpeg = Path(shutil.which("ffmpeg") or app_root / "presets" / "bin" / "ffmpeg.exe")
        ffprobe = Path(shutil.which("ffprobe") or app_root / "presets" / "bin" / "ffprobe.exe")
        models = []
        for path in sorted((app_root / "models" / "minimax_h3").rglob("*.safetensors")):
            models.append({"path": str(path), "bytes": path.stat().st_size})
        status = self._git(app_root, "status", "--porcelain=v1")
        report = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "factory_version": __version__,
            "application_root": str(app_root),
            "git": {
                "branch": self._git(app_root, "branch", "--show-current"),
                "commit": self._git(app_root, "rev-parse", "HEAD"),
                "dirty": bool(status),
                "status": status.splitlines(),
            },
            "runtime": {
                "grizzly_python": str(python), "grizzly_python_exists": python.is_file(),
                "ffmpeg": str(ffmpeg), "ffmpeg_exists": ffmpeg.is_file(),
                "ffprobe": str(ffprobe), "ffprobe_exists": ffprobe.is_file(),
                "obs": str(Path("C:/Program Files/obs-studio/bin/64bit/obs64.exe")),
                "obs_exists": Path("C:/Program Files/obs-studio/bin/64bit/obs64.exe").is_file(),
            },
            "models": models,
            "source_modified_by_factory": False,
        }
        report_path = self.project_root(project) / "audit.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    def _new_run(self, project: str, tutorial: str) -> tuple[RunState, TutorialManifest, dict[str, Any]]:
        project_root = self.project_root(project)
        manifest_path = project_root / "tutorials" / tutorial / "tutorial.yaml"
        manifest = TutorialManifest.load(manifest_path)
        config = self.load_app_config(project)
        run = RunState.create(self.root / "runs", project, tutorial)
        for source, destination in (
            (manifest_path, run.root / "tutorial_manifest.yaml"),
            (project_root / "tutorials" / tutorial / "storyboard.yaml", run.root / "storyboard.yaml"),
            (project_root / "app_knowledge.json", run.root / "app" / "app_knowledge.json"),
            (project_root / "audit.json", run.root / "app" / "audit.json"),
        ):
            if source.is_file():
                shutil.copy2(source, destination)
        return run, manifest, config

    def rehearse(self, project: str, tutorial: str) -> Path:
        if tutorial == "complete-workflow":
            return self._rehearse_complete_workflow(project, tutorial)
        self.audit(project)
        run, manifest, config = self._new_run(project, tutorial)
        adapter = GrizzlyMaxAdapter(Path(config["application"]["root"]), run.root)
        try:
            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
            automation.focus()
            # Let transient driver/overlay banners clear before a QA screenshot or recording.
            time.sleep(10.0)
            automation.click("app.tabs.generation")
            automation.set_combo("generation.mode", "Text to video (T2VA)")
            automation.click("generation.safe_preset")
            prompt = str(manifest.data["variables"]["prompt"])
            automation.enter_text("generation.prompt", prompt)
            self._verify_mvp_settings(adapter)
            self._screenshot(run.root / "qa" / "screenshots" / "rehearsal_ready.png", adapter.state()["window_rect"])
            run.set_stage("rehearsed")
            return run.root
        except Exception as exc:
            run.error(str(exc))
            raise
        finally:
            adapter.close()

    def _rehearse_complete_workflow(self, project: str, tutorial: str) -> Path:
        self.audit(project)
        run, manifest, config = self._new_run(project, tutorial)
        adapter = GrizzlyMaxAdapter(Path(config["application"]["root"]), run.root)
        try:
            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
            automation.focus()
            time.sleep(2.0)
            automation.click("app.tabs.generation")
            automation.set_combo("generation.mode", "Image / Continue Video (FL2VA)")
            automation.set_combo("generation.mode", "Reference to video (Ref2VA)")
            automation.set_combo("generation.mode", "Text to video (T2VA)")
            automation.scroll_to("generation.safe_preset", "down")
            automation.click("generation.safe_preset")
            turbo_lora = str(manifest.data["variables"]["turbo_lora"])
            realism_lora = str(manifest.data["variables"]["realism_lora"])
            automation.scroll_to("generation.lora1.path", "down")
            automation.enter_text("generation.lora1.path", turbo_lora)
            automation.enter_text("generation.lora2.path", realism_lora)
            automation.set_number("generation.lora2.strength", 0.0)
            automation.click("app.tabs.prompt_builder")
            time.sleep(2.0)
            automation.click("app.tabs.generation")
            automation.scroll_to("generation.prompt", "up")
            automation.enter_text("generation.prompt", str(manifest.data["variables"]["prompt"]))
            automation.scroll_to("generation.advanced.cfg", "down")
            automation.click("app.tabs.settings")
            time.sleep(1.0)
            automation.click("app.tabs.generation")
            self._verify_complete_settings(adapter, turbo_lora, realism_lora)
            self._screenshot(run.root / "qa" / "screenshots" / "complete_rehearsal_ready.png", adapter.state()["window_rect"])
            run.set_stage("rehearsed")
            print(f"COMPLETE_REHEARSAL_OK={run.root}", flush=True)
            return run.root
        except Exception as exc:
            run.error(str(exc))
            raise
        finally:
            adapter.close()

    @staticmethod
    def _verify_mvp_settings(adapter: GrizzlyMaxAdapter) -> None:
        expected = {
            "generation.mode": "Text to video (T2VA)",
            "generation.resolution": "576 × 320",
            "generation.frames": "124 frames — 5.17 s",
            "generation.steps": 10,
        }
        actual = {key: adapter.widget(key).get("value") for key in expected}
        if actual != expected:
            raise RuntimeError(f"MVP settings verification failed. Expected {expected}; got {actual}")

    @staticmethod
    def _screenshot(path: Path, rect: list[int]) -> None:
        x, y, width, height = [int(v) for v in rect]
        screen_width, screen_height = pyautogui.size()
        x = max(0, x)
        y = max(0, y)
        width = min(width, screen_width - x)
        height = min(height, screen_height - y)
        path.parent.mkdir(parents=True, exist_ok=True)
        last_error: OSError | None = None
        # ImageGrab can transiently fail while a freshly-launched Qt window is
        # claiming foreground focus.  Retrying keeps a momentary desktop race
        # from discarding an otherwise valid production run.
        for _ in range(5):
            try:
                pyautogui.screenshot(region=(x, y, width, height)).save(path)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(1.0)
        # On some Windows desktop sessions PIL's ImageGrab is unavailable even
        # though the same desktop remains capturable through FFmpeg gdigrab.
        # Keep capture deterministic by falling back to that proven recorder.
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg and width > 0 and height > 0:
            try:
                subprocess.run([
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "gdigrab", "-framerate", "1",
                    "-offset_x", str(x), "-offset_y", str(y),
                    "-video_size", f"{width}x{height}", "-i", "desktop",
                    "-frames:v", "1", str(path),
                ], check=True, timeout=20)
                if path.is_file() and path.stat().st_size > 1000:
                    return
            except (subprocess.SubprocessError, OSError):
                pass
        raise last_error or RuntimeError("screen grab failed")

    def build(self, project: str, tutorial: str) -> Path:
        if tutorial == "expanded-reference-text-workflows":
            from factory.core.grizzly_expanded import build_expanded_grizzlymax
            return build_expanded_grizzlymax(self, project, tutorial)
        if tutorial == "complete-workflow":
            return self._build_complete_workflow(project, tutorial)
        report = self.audit(project)
        run, manifest, config = self._new_run(project, tutorial)
        run.payload["application"] = report["git"]
        run.save()
        app_root = Path(config["application"]["root"])
        ffmpeg = Path(shutil.which("ffmpeg") or app_root / "presets" / "bin" / "ffmpeg.exe")
        ffprobe = Path(shutil.which("ffprobe") or app_root / "presets" / "bin" / "ffprobe.exe")
        adapter = GrizzlyMaxAdapter(app_root, run.root)
        recorder = FFmpegRecorder(ffmpeg, int(manifest.data["video"]["fps"]))
        raw_capture = run.root / "capture" / "raw" / "t2va_ui.mp4"
        try:
            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
            automation.focus()
            # Let transient driver/overlay banners clear before a QA screenshot or recording.
            time.sleep(10.0)
            state = adapter.state()
            self._screenshot(run.root / "qa" / "screenshots" / "before_actions.png", state["window_rect"])
            recorder.start(raw_capture, state["window_rect"], state["window_title"])
            automation.click("app.tabs.generation")
            automation.set_combo("generation.mode", "Text to video (T2VA)")
            automation.click("generation.safe_preset")
            self._verify_mvp_settings(adapter)
            prompt = str(manifest.data["variables"]["prompt"])
            automation.enter_text("generation.prompt", prompt)
            time.sleep(2.0)
            automation.click("generation.generate")
            time.sleep(2.0)
            started = adapter.state()
            jobs = started.get("queue_jobs") or []
            if not jobs or jobs[-1].get("state") not in ("pending", "running"):
                raise RuntimeError(f"Generate did not create a queue job: {started}")
            job_id = jobs[-1]["id"]
            run.payload["generation_job_id"] = job_id
            run.save()
            automation.click("app.tabs.queue")
            time.sleep(8.0)
            self._screenshot(run.root / "qa" / "screenshots" / "generation_started.png", adapter.state()["window_rect"])
            recorder.stop()
            run.artifact("ui_capture", raw_capture)
            run.set_stage("captured")
            generated = self._wait_for_generation(adapter, job_id, run, float(manifest.data.get("generation_timeout_seconds", 3600)))
            run.artifact("generated_example", generated)
            self._screenshot(run.root / "qa" / "screenshots" / "generation_finished.png", adapter.state()["window_rect"])
            run.set_stage("verified")

            narration_text = str(manifest.data["narration"]["text"]).strip()
            transcript = run.root / "transcript.txt"
            transcript.write_text(narration_text + "\n", encoding="utf-8")
            narration = SapiVoiceProvider(
                preferred_voice=str(manifest.data["voice"].get("preferred_voice", "zira")),
                rate=int(manifest.data["voice"].get("rate", 170)),
            ).synthesize(narration_text, run.root / "narration" / "final.wav")
            run.artifact("narration", narration)
            narration_duration = probe_duration(ffprobe, narration)
            subtitle_segments = self._subtitle_segments(manifest.data["narration"]["segments"], narration_duration)
            srt = run.root / "grizzlymax_first_t2va.srt"
            vtt = run.root / "grizzlymax_first_t2va.vtt"
            write_subtitles(subtitle_segments, srt, vtt)
            run.set_stage("narrated")

            final_video = run.root / "render" / "grizzlymax_first_t2va_tutorial.mp4"
            FFmpegRenderer(ffmpeg, ffprobe).render(raw_capture, generated, narration, final_video)
            run.artifact("final_video", final_video)
            run.artifact("subtitles_srt", srt)
            run.artifact("subtitles_vtt", vtt)
            run.set_stage("rendered")
            qa = inspect_media(ffprobe, final_video)
            (run.root / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
            if not qa["passed"]:
                raise RuntimeError(f"Final video QA failed: {qa}")
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

    @staticmethod
    def _wait_until(started: float, seconds: float) -> None:
        remaining = seconds - (time.perf_counter() - started)
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _verify_complete_settings(adapter: GrizzlyMaxAdapter, turbo_lora: str, realism_lora: str) -> None:
        expected = {
            "generation.mode": "Text to video (T2VA)",
            "generation.resolution": "576 × 320",
            "generation.frames": "124 frames — 5.17 s",
            "generation.steps": 10,
            "generation.seed": -1,
            "generation.lora1.path": turbo_lora,
            "generation.lora1.strength": 1.0,
            "generation.lora2.path": realism_lora,
            "generation.lora2.strength": 0.0,
        }
        actual = {key: adapter.widget(key).get("value") for key in expected}
        mismatches = {key: {"expected": expected[key], "actual": actual[key]} for key in expected if actual[key] != expected[key]}
        if mismatches:
            raise RuntimeError(f"Complete workflow settings verification failed: {mismatches}")

    def _build_complete_workflow(self, project: str, tutorial: str) -> Path:
        report = self.audit(project)
        run, manifest, config = self._new_run(project, tutorial)
        run.payload["application"] = report["git"]
        run.save()
        app_root = Path(config["application"]["root"])
        ffmpeg = Path(shutil.which("ffmpeg") or app_root / "presets" / "bin" / "ffmpeg.exe")
        ffprobe = Path(shutil.which("ffprobe") or app_root / "presets" / "bin" / "ffprobe.exe")
        segment_seconds = float(manifest.data["presenter"]["segment_seconds"])
        segments = list(manifest.data["narration"]["segments"])
        scripts = [str(item["text"]).strip() for item in segments]
        chapters = [str(item["chapter"]).strip() for item in segments]
        presenter_provider = Ltx25LizPresenterProvider(
            frames=int(manifest.data["presenter"].get("frames", 193)),
            fps=int(manifest.data["presenter"].get("fps", 24)),
            seed=int(manifest.data["presenter"].get("seed", 250901)),
        )
        presenter_clips: list[Path] = []
        adapter = GrizzlyMaxAdapter(app_root, run.root)
        recorder = FFmpegRecorder(ffmpeg, int(manifest.data["video"]["fps"]))
        raw_capture = run.root / "capture" / "raw" / "complete_workflow_ui.mp4"
        try:
            transcript = run.root / "transcript.txt"
            transcript.write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
            presenter_clips = presenter_provider.generate_segments(scripts, run.root / "presenter" / "clips")
            run.payload["presenter_clips"] = [str(path.resolve()) for path in presenter_clips]
            run.set_stage("presenter_generated")

            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
            automation.focus()
            time.sleep(2.0)
            state = adapter.state()
            self._screenshot(run.root / "qa" / "screenshots" / "before_actions.png", state["window_rect"])
            recorder.start(raw_capture, state["window_rect"], state["window_title"])
            timeline_start = time.perf_counter()

            # 0-8: orient the viewer in the real application.
            automation.click("app.tabs.generation")
            automation.hover("generation.mode", 1.2)
            automation.hover("generation.prompt", 1.0)
            self._wait_until(timeline_start, 8.0)

            # 8-16: visibly cycle through all three generation modes.
            automation.set_combo("generation.mode", "Image / Continue Video (FL2VA)")
            time.sleep(1.1)
            automation.set_combo("generation.mode", "Reference to video (Ref2VA)")
            time.sleep(1.1)
            automation.set_combo("generation.mode", "Text to video (T2VA)")
            self._wait_until(timeline_start, 16.0)

            # 16-24: set and point out the safe first-run controls.
            automation.scroll_to("generation.safe_preset", "down")
            automation.click("generation.safe_preset")
            automation.scroll_to("generation.resolution", "up")
            for target in ("generation.resolution", "generation.frames", "generation.steps", "generation.seed"):
                automation.hover(target, 0.65)
            self._wait_until(timeline_start, 24.0)

            turbo_lora = str(manifest.data["variables"]["turbo_lora"])
            realism_lora = str(manifest.data["variables"]["realism_lora"])
            if not Path(turbo_lora).is_file() or not Path(realism_lora).is_file():
                raise FileNotFoundError("The tutorial LoRA files are not installed")

            # 24-32: add the installed Turbo LoRA in slot one.
            automation.scroll_to("generation.lora1.path", "down")
            automation.hover("generation.lora1.browse", 0.8)
            automation.enter_text("generation.lora1.path", turbo_lora)
            automation.hover("generation.lora1.strength", 0.8)
            self._wait_until(timeline_start, 32.0)

            # 32-40: add Realism, then demonstrate disabling a populated slot with strength zero.
            automation.enter_text("generation.lora2.path", realism_lora)
            automation.set_number("generation.lora2.strength", 0.0)
            automation.hover("generation.lora2.path", 0.8)
            self._wait_until(timeline_start, 40.0)

            # 40-48: compare the enabled and disabled LoRA rows.
            automation.hover("generation.lora1.path", 1.2)
            automation.hover("generation.lora1.strength", 1.2)
            automation.hover("generation.lora2.path", 1.2)
            automation.hover("generation.lora2.strength", 1.2)
            self._wait_until(timeline_start, 48.0)

            # 48-56: show the integrated Prompt Builder, then return to Generation.
            automation.click("app.tabs.prompt_builder")
            time.sleep(5.0)
            automation.click("app.tabs.generation")
            self._wait_until(timeline_start, 56.0)

            # 56-64: enter the exact prompt and revisit the random-seed control.
            automation.scroll_to("generation.prompt", "up")
            prompt = str(manifest.data["variables"]["prompt"])
            automation.enter_text("generation.prompt", prompt)
            automation.hover("generation.seed", 0.8)
            self._wait_until(timeline_start, 61.0)

            # Finish chapter 8 with sampler controls, then hold Settings long enough
            # to read its output fields before chapter 10 begins.
            automation.scroll_to("generation.advanced.cfg", "down")
            automation.hover("generation.advanced.cfg", 0.4)
            automation.hover("generation.advanced.sampler", 0.4)
            automation.hover("generation.advanced.scheduler", 0.4)
            automation.click("app.tabs.settings", hover=0.15)
            time.sleep(2.0)
            automation.click("app.tabs.generation", hover=0.15)
            self._wait_until(timeline_start, 69.0)

            # Start the real job before chapter 10 so Queue remains readable for most
            # of its eight-second narration segment.
            self._verify_complete_settings(adapter, turbo_lora, realism_lora)
            automation.click("generation.generate", hover=0.15)
            time.sleep(0.6)
            started_state = adapter.state()
            jobs = started_state.get("queue_jobs") or []
            if not jobs or jobs[-1].get("state") not in ("pending", "running"):
                raise RuntimeError(f"Generate did not create a queue job: {started_state}")
            job_id = jobs[-1]["id"]
            run.payload["generation_job_id"] = job_id
            run.payload["demonstrated_settings"] = {
                "mode": "Text to video (T2VA)", "resolution": "576 × 320",
                "frames": 124, "steps": 10, "seed": -1,
                "turbo_lora": {"path": turbo_lora, "strength": 1.0},
                "realism_lora": {"path": realism_lora, "strength": 0.0},
            }
            run.save()
            automation.click("app.tabs.queue", hover=0.15)
            self._wait_until(timeline_start, 80.0)
            self._screenshot(run.root / "qa" / "screenshots" / "generation_started.png", adapter.state()["window_rect"])
            recorder.stop()
            run.artifact("ui_capture", raw_capture)
            run.set_stage("captured")

            generated = self._wait_for_generation(adapter, job_id, run, float(manifest.data.get("generation_timeout_seconds", 3600)))
            run.artifact("generated_example", generated)
            finished_shot = run.root / "qa" / "screenshots" / "generation_finished.png"
            self._screenshot(finished_shot, adapter.state()["window_rect"])
            run.set_stage("verified")

            # Approved V2 output chapters are now part of the standard build.
            automation.click("app.tabs.queue", hover=0.15)
            queue_widget = automation.hover("queue.finished.first", 1.0)
            self._screenshot(finished_shot, adapter.state()["window_rect"])
            automation.double_click("queue.finished.first", hover=0.25)
            time.sleep(2.0)
            preview_shot = run.root / "qa" / "screenshots" / "finished_item_preview.png"
            self._screenshot(preview_shot, adapter.state()["window_rect"])
            automation.click("app.tabs.generation", hover=0.15)
            automation.scroll_to("generation.open_output_folder", "down")
            folder_widget = automation.hover("generation.open_output_folder", 1.0)
            folder_shot = run.root / "qa" / "screenshots" / "open_output_folder.png"
            self._screenshot(folder_shot, adapter.state()["window_rect"])

            renderer = ProductionRenderer(ffmpeg, ffprobe)
            presenter_track = renderer.join_presenter_clips(presenter_clips, run.root / "presenter" / "liz_track.mp4")
            run.artifact("presenter_track", presenter_track)
            total_duration = probe_duration(ffprobe, presenter_track)
            chapter_timeline = [
                {
                    "title": chapter,
                    "start": index * segment_seconds,
                    "end": min(total_duration, (index + 1) * segment_seconds),
                    "presenter_position": str(segments[index].get("presenter_position") or "lower-right"),
                }
                for index, chapter in enumerate(chapters)
            ]
            subtitle_segments = [
                {"start": index * segment_seconds, "end": min(total_duration, (index + 1) * segment_seconds), "text": script}
                for index, script in enumerate(scripts)
            ]
            srt = run.root / "grizzlymax_complete_workflow.srt"
            vtt = run.root / "grizzlymax_complete_workflow.vtt"
            write_subtitles(subtitle_segments, srt, vtt)
            run.set_stage("narrated")

            expanded_capture = run.root / "capture" / "processed" / "approved_v2_ui.mp4"
            renderer.assemble_background([
                {"source": raw_capture, "duration": chapter_timeline[9]["end"]},
                {"source": finished_shot, "duration": segment_seconds},
                {"source": preview_shot, "duration": segment_seconds},
                {"source": folder_shot, "duration": segment_seconds},
            ], expanded_capture)
            event_rects: dict[str, list[int]] = {}
            for event in automation.events:
                if event.get("rect"):
                    event_rects[str(event.get("target"))] = list(event["rect"])
            focus_plan = [
                {"start": chapter_timeline[3]["start"] + 0.7, "end": chapter_timeline[3]["end"] - 0.3, "rect": event_rects.get("generation.lora1.path"), "label": "LOOK HERE  >  SPEED LORA", "closeup": True},
                {"start": chapter_timeline[4]["start"] + 0.7, "end": chapter_timeline[4]["end"] - 0.3, "rect": event_rects.get("generation.lora2.path"), "label": "LOOK HERE  >  REALISM LORA", "closeup": True},
                {"start": chapter_timeline[10]["start"] + 0.7, "end": chapter_timeline[10]["end"] - 0.3, "rect": queue_widget.get("rect"), "label": "DOUBLE-CLICK  >  FINISHED RESULT", "closeup": True},
                {"start": chapter_timeline[11]["start"] + 0.7, "end": chapter_timeline[11]["end"] - 0.3, "rect": [int(adapter.state()["window_rect"][0]) + 25, int(adapter.state()["window_rect"][1]) + 150, 760, 500], "label": "LOOK HERE  >  PREVIEW", "closeup": False},
                {"start": chapter_timeline[12]["start"] + 0.7, "end": chapter_timeline[12]["end"] - 0.3, "rect": folder_widget.get("rect"), "label": "CLICK  >  OPEN OUTPUT FOLDER", "closeup": True},
            ]
            final_video = run.root / "render" / "grizzlymax_complete_workflow_approved_v2_with_liz.mp4"
            renderer.render(
                expanded_capture, presenter_track, final_video, chapter_timeline,
                list(adapter.state()["window_rect"]), focus_plan, generated, chapter_timeline[13]["start"],
            )
            run.artifact("final_video", final_video)
            run.artifact("subtitles_srt", srt)
            run.artifact("subtitles_vtt", vtt)
            run.set_stage("rendered")
            qa = inspect_media(ffprobe, final_video)
            qa["presenter_duration_seconds"] = probe_duration(ffprobe, presenter_track)
            qa["presenter_segment_count"] = len(presenter_clips)
            qa["real_generated_clip"] = str(generated.resolve())
            qa["complete_tutorial_checks"] = {
                "liz_presenter_clips": len(presenter_clips) == len(segments),
                "turbo_lora_used": True,
                "disabled_realism_slot_demonstrated": True,
                "finished_output_demonstrated": finished_shot.is_file(),
                "preview_demonstrated": preview_shot.is_file(),
                "open_output_folder_demonstrated": folder_shot.is_file(),
                "approved_v2_renderer": True,
                "chapters": len(chapters) == 14,
            }
            qa["passed"] = bool(qa["passed"] and all(qa["complete_tutorial_checks"].values()))
            renderer.create_contact_sheet(final_video, chapter_timeline, run.root / "qa" / "chapter_contact_sheet.png")
            (run.root / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
            if not qa["passed"]:
                raise RuntimeError(f"Final complete tutorial QA failed: {qa}")
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

    @staticmethod
    def _wait_for_generation(adapter: GrizzlyMaxAdapter, job_id: str, run: RunState, timeout: float) -> Path:
        deadline = time.time() + timeout
        last_marker = None
        progress_path = run.root / "logs" / "generation_progress.jsonl"
        while time.time() < deadline:
            state = adapter.state()
            job = next((item for item in state.get("queue_jobs", []) if item.get("id") == job_id), None)
            if job is None:
                raise RuntimeError(f"Generation job disappeared: {job_id}")
            marker = (job.get("state"), job.get("phase"), job.get("progress"))
            with progress_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"time": time.time(), **job}) + "\n")
            if marker != last_marker:
                print(f"GENERATION state={marker[0]} phase={marker[1]} progress={marker[2]}", flush=True)
                last_marker = marker
            if job.get("state") == "finished":
                output = Path(str(job.get("output") or ""))
                if not output.is_file() or output.stat().st_size < 10000:
                    raise RuntimeError(f"Finished job output is missing or too small: {output}")
                return output
            if job.get("state") in ("failed", "cancelled"):
                raise RuntimeError(f"Generation {job.get('state')}: {job}")
            time.sleep(5.0)
        raise TimeoutError(f"Generation did not finish within {timeout:.0f} seconds")

    @staticmethod
    def _subtitle_segments(segments: list[dict[str, Any]], total_duration: float) -> list[dict[str, Any]]:
        word_counts = [max(1, len(str(item["text"]).split())) for item in segments]
        total_words = sum(word_counts)
        cursor = 0.0
        result = []
        for item, words in zip(segments, word_counts):
            duration = total_duration * words / total_words
            result.append({"start": cursor, "end": min(total_duration, cursor + duration), "text": item["text"]})
            cursor += duration
        return result
