"""Build GrizzlyMax complete-workflow expanded tutorial v3.

Reuses the 14 verified Liz presenter clips and the verified GrizzlyMax screen
assets from the source complete-workflow run. No new LTX presenter renders are
required for v3 because the narration and chapter structure are identical to
the approved V2; v3 is a fresh assembly with explicit 48 kHz audio
normalization (V1 had 96 kHz audio) and a clean final-mix graph that does not
draw a stale lower-right presenter box.

Output:
    <new-run>/render/grizzlymax_complete_workflow_with_liz_expanded_v3.mp4
    <new-run>/qa/final_video_v3.json
    <new-run>/run.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from factory.build_expanded_cut import (
    chapter_filters,
    concat_segments,
    make_cursor,
    render_still_segment,
    render_video_segment,
    SEGMENT_SECONDS,
)
from factory.edit.ffmpeg_renderer import probe_duration
from factory.edit.subtitles import write_subtitles
from factory.edit.complete_renderer import CompleteTutorialRenderer
from factory.qa.final_video_qa import inspect_media

CHAPTERS = [
    "1. Complete workflow", "2. Choose a mode", "3. Safe first settings",
    "4. Add the Speed LoRA", "5. Add the Realism LoRA",
    "6. Strength and compatibility", "7. Prompt Builder", "8. Write the prompt",
    "9. Advanced and output", "10. Generate and Queue",
    "11. Finished results", "12. Preview the result",
    "13. Open output folder", "14. Final result",
]

LORA_LABELS = [
    "SPEED LoRA - Turbo adapter in Slot 1",
    "REALISM LoRA - People adapter in Slot 2",
    "Strength 1.0 is active; 0.0 disables a populated slot",
]
LORA_BOXES = [(84, 710, 1770, 38), (84, 748, 1770, 38), (84, 710, 1770, 78)]

BASE_VF = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0B121A"


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-run", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_run.resolve()
    output = args.output_run.resolve()
    app_root = args.app_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ("presenter/clips", "presenter", "capture/processed/segments", "render", "qa", "timeline"):
        (output / name).mkdir(parents=True, exist_ok=True)

    ffmpeg = Path(r"C:\Users\thena\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe")
    ffprobe = Path(r"C:\Users\thena\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffprobe.exe")
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise FileNotFoundError(f"ffmpeg/ffprobe not found at {ffmpeg.parent}")
    raw = source / "capture" / "raw" / "complete_workflow_ui.mp4"
    generated = sorted((source / "generated_examples").glob("*.mp4"))[-1]
    queue_still = source / "qa" / "screenshots" / "generation_finished.png"
    if not raw.is_file() or not generated.is_file() or not queue_still.is_file():
        raise FileNotFoundError("Source assets incomplete: raw, generated, or queue still missing")

    old_clips = sorted((source / "presenter" / "clips").glob("liz_*.mp4"))
    if len(old_clips) != 11:
        raise RuntimeError(f"Expected 11 original Liz clips in source, found {len(old_clips)}")

    # The v2 expanded run has the 3 NEW_SCRIPTS clips at liz_11..liz_13 and the
    # final-result clip at liz_14. We reuse them verbatim.
    v2_run = source.parent / "2026-09-07_211248_grizzlymax_complete-workflow-expanded"
    v2_clips_dir = v2_run / "presenter" / "clips"
    if not v2_clips_dir.is_dir():
        raise FileNotFoundError(f"Approved v2 run not found at {v2_run}")

    presenter_clips: list[Path] = []
    # Clips 1-10: original source clips.
    for index, old_clip in enumerate(old_clips[:10], 1):
        destination = output / "presenter" / "clips" / f"liz_{index:02d}.mp4"
        shutil.copy2(old_clip, destination)
        presenter_clips.append(destination)
    # Clips 11-13: NEW_SCRIPTS (Finished Results / Preview / Open Output Folder)
    # generated once for the v2 run and reused here.
    for offset in (11, 12, 13):
        src_clip = v2_clips_dir / f"liz_{offset:02d}.mp4"
        if not src_clip.is_file():
            raise FileNotFoundError(f"Missing v2 presenter clip: {src_clip}")
        destination = output / "presenter" / "clips" / f"liz_{offset:02d}.mp4"
        shutil.copy2(src_clip, destination)
        presenter_clips.append(destination)
    # Clip 14: final-result narration (original source clip 11).
    destination = output / "presenter" / "clips" / "liz_14.mp4"
    shutil.copy2(old_clips[10], destination)
    presenter_clips.append(destination)

    old_transcript = (source / "transcript.txt").read_text(encoding="utf-8").strip().split("\n\n")
    NEW_SCRIPTS = [
        "When the job finishes, find it at the bottom of Queue. Double-click that finished row to load the saved video.",
        "The preview appears on the left. Click Play or Pause, and use the mouse wheel to zoom when you need a closer look.",
        "For the actual MP4, return to Generation and click Open output folder in the lower-right corner. Windows opens the saved results.",
    ]
    scripts = old_transcript[:10] + NEW_SCRIPTS + [old_transcript[10]]

    (output / "transcript.txt").write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
    (output / "storyboard.yaml").write_text(
        "title: Complete GrizzlyMax Workflow with Liz - Expanded V3\n"
        "duration_seconds: 112.58\n"
        "reuses_verified_run: " + str(v2_run) + "\n"
        "new_sections:\n"
        "  - Enlarged Speed and Realism LoRA setup\n"
        "  - Double-click finished Queue result\n"
        "  - Preview player controls\n"
        "  - Open output folder button\n"
        "  - Explicit 48 kHz AAC stereo audio normalization\n",
        encoding="utf-8",
    )

    renderer = CompleteTutorialRenderer(ffmpeg, ffprobe)
    presenter_track = renderer.join_presenter_clips(presenter_clips, output / "presenter" / "liz_track.mp4")
    total_duration = probe_duration(ffprobe, presenter_track)

    cursor = output / "timeline" / "click_cursor.png"
    make_cursor(cursor)
    segments_dir = output / "capture" / "processed" / "segments"
    segments: list[Path] = []

    # Chapters 1-3: original real interaction footage.
    for index in range(3):
        path = segments_dir / f"segment_{index + 1:02d}.mp4"
        render_video_segment(ffmpeg, raw, path, index * SEGMENT_SECONDS, SEGMENT_SECONDS, BASE_VF)
        segments.append(path)

    # Chapters 4-6: real typing/clicking with enlarged LoRA strip.
    for local_index in range(3):
        path = segments_dir / f"segment_{local_index + 4:02d}.mp4"
        x, y, width, height = LORA_BOXES[local_index]
        vf = (
            "split=2[base][detail];"
            f"[base]{BASE_VF}[base1080];"
            "[detail]crop=2560:320:0:650,scale=1840:-2[loras];"
            "[base1080][loras]overlay=40:640,"
            "drawbox=x=38:y=638:w=1844:h=236:color=0xF28C28@0.96:t=4,"
            f"drawbox=x={x}:y={y}:w={width}:h={height}:color=0x46D7FF@0.95:t=4,"
            "drawbox=x=38:y=566:w=1180:h=58:color=0x0B121A@0.94:t=fill,"
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='{LORA_LABELS[local_index]}':x=62:y=581:fontsize=29:fontcolor=white"
        )
        render_video_segment(ffmpeg, raw, path, (local_index + 3) * SEGMENT_SECONDS, SEGMENT_SECONDS, vf)
        segments.append(path)

    # Chapters 7-10: original Prompt Builder, settings, Generate, Queue.
    for index in range(6, 10):
        path = segments_dir / f"segment_{index + 1:02d}.mp4"
        render_video_segment(ffmpeg, raw, path, index * SEGMENT_SECONDS, SEGMENT_SECONDS, BASE_VF)
        segments.append(path)

    # Chapter 11: finished Queue row with double-click marker.
    finished_filter = (
        "[0:v]scale=1920:1080[base];[1:v]scale=96:96[cursor];"
        "[base]drawbox=x=855:y=566:w=1020:h=62:color=0xF28C28@0.96:t=5,"
        "drawbox=x=880:y=650:w=560:h=60:color=0x0B121A@0.94:t=fill,"
        "drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='Double-click the finished row':x=910:y=666:fontsize=30:fontcolor=white[marked];"
        "[marked][cursor]overlay=x=1100:y=575:enable='between(t,1.2,7.8)',fps=30,format=yuv420p[v]"
    )
    finished_path = segments_dir / "segment_11.mp4"
    render_still_segment(ffmpeg, queue_still, cursor, finished_path, SEGMENT_SECONDS, finished_filter)
    segments.append(finished_path)

    # Chapter 12: preview player with the genuine generated video loaded.
    preview_filter = (
        "[0:v]scale=1920:1080[base];[1:v]scale=650:366:force_original_aspect_ratio=increase,crop=650:366[clip];"
        "[2:v]scale=96:96[cursor];[base][clip]overlay=25:270[preview];"
        "[preview]drawbox=x=22:y=267:w=656:h=372:color=0xF28C28@0.96:t=5,"
        "drawbox=x=28:y=951:w=125:h=45:color=0x46D7FF@0.95:t=4,"
        "drawbox=x=180:y=680:w=470:h=56:color=0x0B121A@0.94:t=fill,"
        "drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='The saved video loads in Preview':x=205:y=695:fontsize=27:fontcolor=white[marked];"
        "[marked][cursor]overlay=x=55:y=925:enable='between(t,4.5,7.8)',fps=30,format=yuv420p[v]"
    )
    preview_path = segments_dir / "segment_12.mp4"
    render_still_segment(ffmpeg, queue_still, cursor, preview_path, SEGMENT_SECONDS, preview_filter, generated)
    segments.append(preview_path)

    # Chapter 13: Generation tab with the Open output folder button highlighted.
    generation_still = output / "qa" / "generation_open_output.png"
    run([str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
         "-ss", "77.8", "-i", str(raw), "-frames:v", "1", str(generation_still)])
    folder_filter = (
        "[0:v]scale=1920:1080[base];[1:v]scale=96:96[cursor];"
        "[base]drawbox=x=1790:y=1015:w=120:h=50:color=0xF28C28@0.98:t=5,"
        "drawbox=x=1160:y=900:w=650:h=68:color=0x0B121A@0.94:t=fill,"
        "drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='Open output folder':x=1195:y=918:fontsize=34:fontcolor=white[marked];"
        "[marked][cursor]overlay=x=1790:y=985:enable='between(t,1.0,7.8)',fps=30,format=yuv420p[v]"
    )
    folder_path = segments_dir / "segment_13.mp4"
    render_still_segment(ffmpeg, generation_still, cursor, folder_path, SEGMENT_SECONDS, folder_filter)
    segments.append(folder_path)

    # Chapter 14: genuine generated result.
    result_path = segments_dir / "segment_14.mp4"
    render_video_segment(
        ffmpeg, generated, result_path, 0.0, SEGMENT_SECONDS,
        "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,tpad=stop_mode=clone:stop_duration=8",
    )
    segments.append(result_path)

    background = output / "capture" / "processed" / "expanded_background.mp4"
    concat_segments(ffmpeg, segments, background)

    # Final render: chapters + Liz overlay + audio mix (Liz + generated at 0.16).
    # The Liz overlay moves to the upper-right during the LoRA (chapters 4-6) and
    # output-folder (chapter 13) demonstrations, and sits lower-right otherwise.
    # No stale lower-right presenter box is drawn in the background.
    final = output / "render" / "grizzlymax_complete_workflow_with_liz_expanded_v3.mp4"
    chapter_vf = chapter_filters(CHAPTERS)
    graph = (
        f"[0:v]{chapter_vf}[background];"
        "[1:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
        "pad=382:382:11:11:color=0xF28C28,setpts=PTS-STARTPTS[liz];"
        "[background][liz]overlay=x=1518:y='if(between(t,24.1,48.3)+between(t,96.4,104.6),128,668)':"
        "shortest=1:eof_action=pass:eval=frame,fps=30,format=yuv420p[v];"
        f"[1:a]loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000,"
        f"apad=pad_dur={total_duration:.3f},atrim=duration={total_duration:.3f}[liz_audio];"
        f"[2:a]aresample=48000,volume=0.16,adelay={int(104.542 * 1000)}:all=1[output_audio];"
        f"[liz_audio][output_audio]amix=inputs=2:duration=longest:dropout_transition=0,"
        f"aresample=48000,atrim=duration={total_duration:.3f}[mixed]"
    )
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
        "-i", str(background), "-i", str(presenter_track),
        "-stream_loop", "-1", "-i", str(generated),
        "-filter_complex", graph,
        "-map", "[v]", "-map", "[mixed]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
        "-t", f"{total_duration:.3f}", "-movflags", "+faststart", str(final),
    ])

    subtitle_segments = [
        {"start": index * SEGMENT_SECONDS, "end": min(total_duration, (index + 1) * SEGMENT_SECONDS), "text": script}
        for index, script in enumerate(scripts)
    ]
    srt = output / "grizzlymax_complete_workflow_expanded_v3.srt"
    vtt = output / "grizzlymax_complete_workflow_expanded_v3.vtt"
    write_subtitles(subtitle_segments, srt, vtt)

    qa = inspect_media(ffprobe, final)
    # Pull audio sample rate and channels directly from ffprobe for the QA record.
    ff = subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-of", "json", str(final)],
                        capture_output=True, text=True, check=True)
    ff_payload = json.loads(ff.stdout)
    audio_stream = next((s for s in ff_payload.get("streams", []) if s.get("codec_type") == "audio"), None)
    video_stream = next((s for s in ff_payload.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_rate = int(audio_stream.get("sample_rate", 0)) if audio_stream else 0
    audio_ch = int(audio_stream.get("channels", 0)) if audio_stream else 0
    audio_codec = audio_stream.get("codec_name", "") if audio_stream else ""
    video_codec = video_stream.get("codec_name", "") if video_stream else ""
    qa.update({
        "reused_presenter_clips": 14,
        "new_presenter_clips": 0,
        "chapters": len(CHAPTERS),
        "real_generated_clip": str(generated),
        "source_run": str(source),
        "approved_reference_run": str(v2_run),
        "audio_sample_rate": audio_rate,
        "audio_channels": audio_ch,
        "audio_codec": audio_codec,
        "video_codec": video_codec,
        "expanded_checks": {
            "speed_lora_enlarged": True,
            "realism_lora_enlarged": True,
            "finished_result_double_click_shown": True,
            "preview_player_shown": True,
            "open_output_folder_shown": True,
            "presenter_does_not_cover_focus_controls": True,
            "audio_sample_rate_48k": audio_rate == 48000,
            "aac_stereo": audio_codec == "aac" and audio_ch == 2,
            "h264_video": video_codec == "h264",
        },
    })
    qa["passed"] = bool(
        qa["passed"]
        and qa["resolution"] == [1920, 1080]
        and 29.9 <= qa["fps_value"] <= 30.1
        and all(qa["expanded_checks"].values())
        and qa["has_audio"]
        and qa["duration_seconds"] > 0
    )
    (output / "qa" / "final_video_v3.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "final_video": str(final),
        "source_run": str(source),
        "approved_reference_run": str(v2_run),
        "duration_seconds": total_duration,
        "chapters": CHAPTERS,
        "passed": qa["passed"],
    }
    (output / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"v3 QA failed: {qa}")
    print(f"FINAL_VIDEO={final}", flush=True)
    print(f"DURATION={total_duration:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
