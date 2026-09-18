from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyautogui
import yaml

from factory.actions.executor import TutorialActionExecutor
from factory.actions.schema import TutorialAction, load_actions
from factory.adapters.registry import create_adapter
from factory.automation.windows import WindowsAutomation
from factory.capture.ffmpeg_recorder import FFmpegRecorder
from factory.capture.uia_recorder import UIAFrameRecorder
from factory.core.profile import ApplicationProfile
from factory.core.run_state import RunState
from factory.edit.ffmpeg_renderer import probe_duration
from factory.edit.production_renderer import ProductionRenderer
from factory.edit.subtitles import write_subtitles
from factory.presenter.registry import create_presenter
from factory.qa.final_video_qa import inspect_media


class GenericTutorialFactory:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def project_root(self, project: str) -> Path:
        return self.root / "projects" / project

    def load_profile(self, project: str) -> ApplicationProfile:
        return ApplicationProfile.load(self.project_root(project) / "app.yaml")

    def load_tutorial(self, project: str, tutorial: str) -> tuple[Path, dict[str, Any]]:
        path = self.project_root(project) / "tutorials" / tutorial / "tutorial.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("title", "video", "narration", "actions", "scenes"):
            if key not in payload:
                raise ValueError(f"Tutorial is missing '{key}': {path}")
        return path, payload

    def audit(self, project: str) -> dict[str, Any]:
        profile = self.load_profile(project)
        source = profile.source_root
        status = ""
        commit = None
        branch = None
        if (source / ".git").exists():
            status = subprocess.run(["git", "-C", str(source), "status", "--porcelain=v1"], capture_output=True, text=True).stdout.strip()
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or None
            branch = subprocess.run(["git", "-C", str(source), "branch", "--show-current"], capture_output=True, text=True).stdout.strip() or None
        report = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "application": profile.name,
            "profile": str(profile.path),
            "source_root": str(source),
            "framework": profile.data["application"].get("framework"),
            "adapter": profile.adapter_kind,
            "launch_command": profile.launch_command,
            "launch_ready": Path(profile.launch_command[0]).is_file(),
            "control_count": len(profile.controls),
            "outputs": profile.output_specs,
            "git": {"branch": branch, "commit": commit, "dirty": bool(status), "status": status.splitlines()},
            "source_modified_by_factory": False,
        }
        (self.project_root(project) / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    def _new_run(self, project: str, tutorial: str, profile: ApplicationProfile, tutorial_path: Path) -> RunState:
        run = RunState.create(self.root / "runs", project, tutorial)
        for source, destination in (
            (profile.path, run.root / "app" / "app.yaml"),
            (self.project_root(project) / "discovery.json", run.root / "app" / "discovery.json"),
            (self.project_root(project) / "audit.json", run.root / "app" / "audit.json"),
            (tutorial_path, run.root / "tutorial_manifest.yaml"),
        ):
            if source.is_file():
                shutil.copy2(source, destination)
        llm_audit = self.project_root(project) / "llm"
        if llm_audit.is_dir():
            shutil.copytree(llm_audit, run.root / "app" / "llm", dirs_exist_ok=True)
        for name in ("driver.py", "driver-manifest.json", "driver-validation.json"):
            source = self.project_root(project) / name
            if source.is_file():
                shutil.copy2(source, run.root / "app" / name)
        return run

    @staticmethod
    def _screenshot(path: Path, rect: list[int]) -> None:
        x, y, width, height = [int(value) for value in rect]
        screen_width, screen_height = pyautogui.size()
        x, y = max(0, x), max(0, y)
        width, height = min(width, screen_width - x), min(height, screen_height - y)
        path.parent.mkdir(parents=True, exist_ok=True)
        last_error: OSError | None = None
        for _ in range(4):
            try:
                pyautogui.screenshot(region=(x, y, width, height)).save(path)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.75)
        raise OSError(f"Screen capture failed after retries: {last_error}")

    @staticmethod
    def _adapter_screenshot(adapter: Any, path: Path, rect: list[int]) -> None:
        try:
            adapter.capture(path)
        except NotImplementedError:
            GenericTutorialFactory._screenshot(path, rect)

    @staticmethod
    def _schedule_actions(raw_actions: list[dict[str, Any]], chapters: list[dict[str, Any]]) -> list[TutorialAction]:
        scheduled: list[dict[str, Any]] = []
        for raw in raw_actions:
            item = dict(raw)
            if item.get("at") is None and item.get("chapter") is not None:
                index = int(item.pop("chapter")) - 1
                if index < 0 or index >= len(chapters):
                    raise ValueError(f"Action chapter is out of range: {raw}")
                item["at"] = float(chapters[index]["start"]) + float(item.pop("offset", 0.5))
            scheduled.append(item)
        scheduled.sort(key=lambda item: float(item.get("at") or 0.0))
        return load_actions(scheduled)

    def rehearse(self, project: str, tutorial: str) -> Path:
        self.audit(project)
        profile = self.load_profile(project)
        tutorial_path, payload = self.load_tutorial(project, tutorial)
        run = self._new_run(project, tutorial, profile, tutorial_path)
        adapter = create_adapter(profile, run.root)
        try:
            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json")
            automation.focus()
            time.sleep(1.0)
            capture = lambda path, rect: self._adapter_screenshot(adapter, path, rect)
            capture(run.root / "qa" / "screenshots" / "rehearsal_before.png", adapter.state()["window_rect"])
            provisional = [{"start": index * 8.0, "end": (index + 1) * 8.0} for index, _ in enumerate(payload["narration"]["segments"])]
            actions = self._schedule_actions(payload["actions"], provisional)
            executor = TutorialActionExecutor(
                adapter, automation, capture, run.root / "qa" / "screenshots", rehearsal=True,
            )
            executor.execute_all(actions)
            capture(run.root / "qa" / "screenshots" / "rehearsal_after.png", adapter.state()["window_rect"])
            run.set_stage("rehearsed")
            print(f"REHEARSAL_RUN={run.root}", flush=True)
            return run.root
        except Exception as exc:
            run.error(str(exc))
            raise
        finally:
            adapter.close()

    def build(self, project: str, tutorial: str, reuse_run: Path | None = None) -> Path:
        audit = self.audit(project)
        profile = self.load_profile(project)
        tutorial_path, payload = self.load_tutorial(project, tutorial)
        run = self._new_run(project, tutorial, profile, tutorial_path)
        run.payload["application_audit"] = audit
        run.save()
        ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
        ffprobe = Path(shutil.which("ffprobe") or "ffprobe")
        scripts = [str(item["text"]).strip() for item in payload["narration"]["segments"]]
        presenter_config = dict(payload.get("presenter") or {"provider": "gary"})
        presenter_name = str(presenter_config.get("provider") or "gary").strip().lower()
        presenter_slug = "darla" if presenter_name in {"darla", "ltx25_darla"} else presenter_name
        presenter = create_presenter(presenter_config)
        adapter = create_adapter(profile, run.root)
        recorder: Any = UIAFrameRecorder(adapter, capture_fps=5, output_fps=int(payload["video"].get("fps", 30)))
        raw_capture = run.root / "capture" / "raw" / "application_ui.mp4"
        try:
            if reuse_run is not None:
                reusable_clip_patterns = {
                    "darla": "darla_ltx_a2v_*.mp4",
                    "gary": "gary_*.mp4",
                    "liz": "liz_*.mp4",
                    "ltx25_liz": "liz_*.mp4",
                }
                clip_pattern = reusable_clip_patterns.get(presenter_slug, f"{presenter_slug}_*.mp4")
                source_clips = sorted((reuse_run.resolve() / "presenter" / "clips").glob(clip_pattern))
                if len(source_clips) != len(scripts):
                    raise RuntimeError(f"Reusable presenter count mismatch: expected {len(scripts)}, found {len(source_clips)}")
                clips = []
                for source_clip in source_clips:
                    destination = run.root / "presenter" / "clips" / source_clip.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_clip, destination)
                    for sidecar_suffix in (".provenance.json", ".ltx-a2v.log"):
                        source_sidecar = source_clip.with_suffix(sidecar_suffix)
                        if source_sidecar.is_file():
                            shutil.copy2(source_sidecar, destination.with_suffix(sidecar_suffix))
                    clips.append(destination)
                run.payload["reused_presenter_from"] = str(reuse_run.resolve())
                run.save()
            else:
                clips = presenter.generate_segments(scripts, run.root / "presenter" / "clips")
            renderer = ProductionRenderer(ffmpeg, ffprobe)
            presenter_track = renderer.join_presenter_clips(clips, run.root / "presenter" / "presenter_track.mp4")
            durations = [probe_duration(ffprobe, path) for path in clips]
            chapters: list[dict[str, Any]] = []
            cursor = 0.0
            for source, duration in zip(payload["narration"]["segments"], durations):
                chapter = {
                    "title": str(source["chapter"]), "start": cursor, "end": cursor + duration,
                    "presenter_position": str(source.get("presenter_position") or "lower-right"),
                }
                chapters.append(chapter)
                cursor += duration
            actions = self._schedule_actions(payload["actions"], chapters)
            transcript = run.root / "transcript.txt"
            transcript.write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
            subtitles = [
                {"start": chapter["start"], "end": chapter["end"], "text": script}
                for chapter, script in zip(chapters, scripts)
            ]
            srt, vtt = run.root / f"{project}_{tutorial}.srt", run.root / f"{project}_{tutorial}.vtt"
            write_subtitles(subtitles, srt, vtt)
            run.set_stage("presenter_generated")

            adapter.launch()
            automation = WindowsAutomation(adapter, run.root / "timeline" / "actions.json", clock=recorder.elapsed)
            automation.focus()
            time.sleep(1.0)
            state = adapter.state()
            window_rect = list(state["window_rect"])
            capture = lambda path, rect: self._adapter_screenshot(adapter, path, rect)
            capture(run.root / "qa" / "screenshots" / "before_actions.png", window_rect)
            recorder.start(raw_capture, window_rect, state["window_title"])
            executor = TutorialActionExecutor(
                adapter, automation, capture, run.root / "qa" / "screenshots",
                on_long_wait_start=recorder.pause, on_long_wait_end=recorder.resume,
            )
            result_media = executor.execute_all(actions)
            while recorder.elapsed() < cursor:
                if recorder.error:
                    raise RuntimeError(f"UI recording failed while completing the narration timeline: {recorder.error}")
                time.sleep(0.1)
            recorder.stop()
            run.artifact("ui_capture", raw_capture)
            run.set_stage("captured")
            if result_media:
                run.artifact("result_media", result_media)
            run.set_stage("verified")
            focuses = [
                {
                    "start": float(event["time"]),
                    "end": float(event["time"]) + float(event.get("duration", 2.0)),
                    "rect": event.get("rect"),
                    "label": (
                        ("CLICK  >  " if event.get("visual_action") in {"click", "double_click"} else "LOOK HERE  >  ")
                        + str(event.get("target") or "").replace("ui.", "").replace("_", " ").title()
                    ),
                    "closeup": bool(event.get("closeup", False)),
                }
                for event in automation.events
                if event.get("rect") and event.get("action") == "visual_focus"
            ]
            final = run.root / "render" / f"{project}_{tutorial}_with_{presenter_slug}.mp4"
            renderable_result = result_media if result_media and result_media.suffix.lower() in {
                ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg",
                ".mp4", ".mov", ".mkv", ".webm", ".avi",
            } else None
            result_start = chapters[-1]["start"] if renderable_result else None
            renderer.render(raw_capture, presenter_track, final, chapters, window_rect, focuses, renderable_result, result_start)
            run.artifact("presenter_track", presenter_track)
            run.artifact("final_video", final)
            run.artifact("subtitles_srt", srt)
            run.artifact("subtitles_vtt", vtt)
            run.set_stage("rendered")
            qa = inspect_media(ffprobe, final, min_duration=15.0, max_duration=900.0)
            contact_sheet = run.root / "qa" / "chapter_contact_sheet.png"
            renderer.create_contact_sheet(final, chapters, contact_sheet)
            unsafe_targets = {
                str(item.get("target")) for item in payload["actions"]
                if item.get("action") in {"click", "operation"} and bool(item.get("unsafe", False))
            }
            clicked_targets = {
                str(event.get("target")) for event in automation.events if event.get("action") in {"click", "operation"}
            }
            verification = dict(payload.get("verification") or {})
            requires_new_output = bool(verification.get("requires_new_output", True))
            required_operations = {str(item) for item in verification.get("required_operations", [])}
            operation_events = {
                str(event.get("target")): event
                for event in automation.events
                if event.get("action") == "operation"
            }
            operations_verified = all(
                name in operation_events
                and isinstance(operation_events[name].get("result"), dict)
                and bool(operation_events[name]["result"].get("verified", False))
                for name in required_operations
            )
            result_resolved = result_media.resolve() if result_media else None
            acceptance_checks = {
                "real_workflow_clicked": bool(
                    (unsafe_targets or required_operations)
                    and unsafe_targets.issubset(clicked_targets)
                    and required_operations.issubset(clicked_targets)
                ),
                "required_operations_verified": operations_verified,
                "new_output_identified": (not requires_new_output) or bool(
                    result_resolved and result_resolved.is_file()
                    and str(result_resolved).lower() not in executor.output_baseline
                    and result_resolved.stat().st_mtime >= executor.started_wall
                ),
                "new_output_minimum_size": (not requires_new_output) or bool(
                    result_resolved and result_resolved.stat().st_size >= 1000
                ),
                "generic_action_executor": True,
                "presenter_created": len(clips) == len(scripts),
            }
            visual_checks = {
                "contact_sheet_created": contact_sheet.is_file() and contact_sheet.stat().st_size > 1000,
                "chapter_cards_present": len(chapters) == len(scripts) and len(chapters) >= 3,
                "focus_highlights_present": bool(focuses),
                "dead_time_capture_paused": (
                    not any(item.get("action") == "wait_for_output" for item in payload["actions"])
                    or any(item.get("action") == "wait_for_output" for item in automation.events)
                ),
            }
            qa.update({
                "application": profile.name,
                "profile_generated_from_source": bool(profile.data.get("discovery", {}).get("generated_from_source")),
                "adapter": profile.adapter_kind,
                "persistent_application_driver_used": profile.adapter_kind in {"project-driver", "grizzlymax"},
                "action_schema_version": int(payload.get("schema_version", 1)),
                "actions_executed": len(automation.events),
                "chapters": chapters,
                "presenter_provider": presenter_name,
                "contact_sheet": str(contact_sheet.resolve()),
                "acceptance_checks": acceptance_checks,
                "visual_qa": visual_checks,
            })
            qa["passed"] = bool(qa["passed"] and all(acceptance_checks.values()) and all(visual_checks.values()))
            (run.root / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
            if not qa["passed"]:
                raise RuntimeError(f"Final video QA failed: {qa}")
            run.set_stage("qa_passed", completed_at=datetime.now(timezone.utc).isoformat())
            print(f"FINAL_VIDEO={final}", flush=True)
            return final
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
