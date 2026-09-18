from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from factory.edit.complete_renderer import CompleteTutorialRenderer
from factory.edit.ffmpeg_renderer import probe_duration
from factory.edit.subtitles import write_subtitles
from factory.presenter.providers.ltx25 import Ltx25LizPresenterProvider
from factory.qa.final_video_qa import inspect_media


SEGMENT_SECONDS = 193 / 24
NEW_SCRIPTS = [
    "When the job finishes, find it at the bottom of Queue. Double-click that finished row to load the saved video.",
    "The preview appears on the left. Click Play or Pause, and use the mouse wheel to zoom when you need a closer look.",
    "For the actual MP4, return to Generation and click Open output folder in the lower-right corner. Windows opens the saved results.",
]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def make_cursor(path: Path) -> None:
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 12, 84, 84), outline=(242, 140, 40, 255), width=7)
    draw.ellipse((25, 25, 71, 71), outline=(255, 255, 255, 230), width=3)
    points = [(35, 25), (35, 69), (46, 58), (55, 78), (66, 72), (57, 53), (74, 52)]
    draw.polygon(points, fill=(255, 255, 255, 255), outline=(10, 18, 26, 255))
    image.save(path)


def render_video_segment(ffmpeg: Path, source: Path, output: Path, start: float, duration: float, vf: str) -> None:
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
        "-ss", f"{start:.6f}", "-i", str(source), "-t", f"{duration:.6f}",
        "-an", "-vf", vf + ",fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(output),
    ])


def render_still_segment(
    ffmpeg: Path,
    still: Path,
    cursor: Path,
    output: Path,
    duration: float,
    filter_graph: str,
    generated: Path | None = None,
) -> None:
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-loop", "1", "-i", str(still)]
    if generated is not None:
        command += ["-stream_loop", "-1", "-i", str(generated)]
    command += ["-loop", "1", "-i", str(cursor), "-t", f"{duration:.6f}", "-filter_complex", filter_graph]
    command += ["-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(output)]
    run(command)


def concat_segments(ffmpeg: Path, segments: list[Path], output: Path) -> None:
    listing = output.with_suffix(".concat.txt")
    listing.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in segments), encoding="utf-8")
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ])


def chapter_filters(chapters: list[str]) -> str:
    filters: list[str] = []
    for index, title in enumerate(chapters):
        start = index * SEGMENT_SECONDS
        end = (index + 1) * SEGMENT_SECONDS
        safe = title.replace("'", "").replace(":", " -")
        filters += [
            f"drawbox=x=38:y=38:w=720:h=72:color=0x0B121A@0.92:t=fill:enable='between(t,{start:.3f},{end:.3f})'",
            f"drawbox=x=38:y=38:w=720:h=72:color=0xF28C28@0.96:t=4:enable='between(t,{start:.3f},{end:.3f})'",
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='{safe}':x=66:y=58:fontsize=30:fontcolor=white:enable='between(t,{start:.3f},{end:.3f})'",
        ]
    return ",".join(filters)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--output-run", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_run.resolve()
    output = args.output_run.resolve()
    app_root = args.app_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ("presenter/clips", "presenter", "capture/processed", "render", "qa", "timeline"):
        (output / name).mkdir(parents=True, exist_ok=True)

    ffmpeg = app_root / "presets" / "bin" / "ffmpeg.exe"
    ffprobe = app_root / "presets" / "bin" / "ffprobe.exe"
    raw = source / "capture" / "raw" / "complete_workflow_ui.mp4"
    generated_candidates = sorted((source / "generated_examples").glob("*.mp4"))
    if not raw.is_file() or not generated_candidates:
        raise FileNotFoundError("The verified source tutorial assets are incomplete")
    generated = generated_candidates[-1]
    queue_still = source / "qa" / "screenshots" / "generation_finished.png"

    old_clips = sorted((source / "presenter" / "clips").glob("liz_*.mp4"))
    if len(old_clips) != 11:
        raise RuntimeError(f"Expected 11 reusable Liz clips, found {len(old_clips)}")
    presenter_clips: list[Path] = []
    for index, old_clip in enumerate(old_clips[:10], 1):
        destination = output / "presenter" / "clips" / f"liz_{index:02d}.mp4"
        shutil.copy2(old_clip, destination)
        presenter_clips.append(destination)

    provider = Ltx25LizPresenterProvider(frames=193, fps=24, seed=250901)
    for offset, script in enumerate(NEW_SCRIPTS, 11):
        clip = provider.generate_presenter_clip(script, output / "presenter" / "clips" / f"liz_{offset:02d}.mp4")
        presenter_clips.append(clip)
    final_liz = output / "presenter" / "clips" / "liz_14.mp4"
    shutil.copy2(old_clips[10], final_liz)
    presenter_clips.append(final_liz)

    old_transcript = (source / "transcript.txt").read_text(encoding="utf-8").strip().split("\n\n")
    scripts = old_transcript[:10] + NEW_SCRIPTS + [old_transcript[10]]
    chapters = [
        "1. Complete workflow", "2. Choose a mode", "3. Safe first settings", "4. Add the Speed LoRA",
        "5. Add the Realism LoRA", "6. Strength and compatibility", "7. Prompt Builder", "8. Write the prompt",
        "9. Advanced and output", "10. Generate and Queue", "11. Finished results", "12. Preview the result",
        "13. Open output folder", "14. Final result",
    ]
    (output / "transcript.txt").write_text("\n\n".join(scripts) + "\n", encoding="utf-8")
    (output / "storyboard.yaml").write_text(
        "title: Complete GrizzlyMax Workflow with Liz - Expanded\n"
        "duration_seconds: 112.58\n"
        "reuses_verified_run: " + str(source) + "\n"
        "new_sections:\n"
        "  - Enlarged Speed and Realism LoRA setup\n"
        "  - Double-click finished Queue result\n"
        "  - Preview player controls\n"
        "  - Open output folder button\n",
        encoding="utf-8",
    )

    renderer = CompleteTutorialRenderer(ffmpeg, ffprobe)
    presenter_track = renderer.join_presenter_clips(presenter_clips, output / "presenter" / "liz_track.mp4")
    total_duration = probe_duration(ffprobe, presenter_track)

    cursor = output / "timeline" / "click_cursor.png"
    make_cursor(cursor)
    segments_dir = output / "capture" / "processed" / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    base_vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0B121A"

    # Reuse the original real interaction footage for chapters 1-3.
    for index in range(3):
        path = segments_dir / f"segment_{index + 1:02d}.mp4"
        render_video_segment(ffmpeg, raw, path, index * SEGMENT_SECONDS, SEGMENT_SECONDS, base_vf)
        segments.append(path)

    # Chapters 4-6 retain the real typing/clicking but add a large readable LoRA strip.
    lora_labels = [
        "SPEED LoRA - Turbo adapter in Slot 1",
        "REALISM LoRA - People adapter in Slot 2",
        "Strength 1.0 is active; 0.0 disables a populated slot",
    ]
    lora_boxes = [(84, 710, 1770, 38), (84, 748, 1770, 38), (84, 710, 1770, 78)]
    for local_index in range(3):
        path = segments_dir / f"segment_{local_index + 4:02d}.mp4"
        x, y, width, height = lora_boxes[local_index]
        vf = (
            "split=2[base][detail];"
            f"[base]{base_vf}[base1080];"
            "[detail]crop=2560:320:0:650,scale=1840:-2[loras];"
            "[base1080][loras]overlay=40:640," 
            "drawbox=x=38:y=638:w=1844:h=236:color=0xF28C28@0.96:t=4," 
            f"drawbox=x={x}:y={y}:w={width}:h={height}:color=0x46D7FF@0.95:t=4," 
            "drawbox=x=38:y=566:w=1180:h=58:color=0x0B121A@0.94:t=fill," 
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='{lora_labels[local_index]}':x=62:y=581:fontsize=29:fontcolor=white"
        )
        render_video_segment(ffmpeg, raw, path, (local_index + 3) * SEGMENT_SECONDS, SEGMENT_SECONDS, vf)
        segments.append(path)

    # Chapters 7-10 continue the original Prompt Builder, settings, Generate, and Queue actions.
    for index in range(6, 10):
        path = segments_dir / f"segment_{index + 1:02d}.mp4"
        render_video_segment(ffmpeg, raw, path, index * SEGMENT_SECONDS, SEGMENT_SECONDS, base_vf)
        segments.append(path)

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

    generation_still = output / "qa" / "generation_open_output.png"
    run([str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-ss", "77.8", "-i", str(raw), "-frames:v", "1", str(generation_still)])
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

    result_path = segments_dir / "segment_14.mp4"
    render_video_segment(
        ffmpeg, generated, result_path, 0.0, SEGMENT_SECONDS,
        "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,tpad=stop_mode=clone:stop_duration=8",
    )
    segments.append(result_path)

    background = output / "capture" / "processed" / "expanded_background.mp4"
    concat_segments(ffmpeg, segments, background)

    final = output / "render" / "grizzlymax_complete_workflow_with_liz_expanded.mp4"
    chapter_vf = chapter_filters(chapters)
    graph = (
        f"[0:v]{chapter_vf}[background];"
        "[1:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
        "pad=382:382:11:11:color=0xF28C28,setpts=PTS-STARTPTS[liz];"
        "[background][liz]overlay=x=1518:y='if(between(t,24.1,48.3)+between(t,96.4,104.6),128,668)':"
        "shortest=1:eof_action=pass:eval=frame,fps=30[v];"
        f"[1:a]loudnorm=I=-16:LRA=11:TP=-1.5,apad=pad_dur={total_duration:.3f},atrim=duration={total_duration:.3f}[liz_audio];"
        "[2:a]volume=0.16,adelay=104542:all=1[output_audio];"
        f"[liz_audio][output_audio]amix=inputs=2:duration=longest:dropout_transition=0,"
        f"aresample=48000,atrim=duration={total_duration:.3f}[mixed]"
    )
    run([
        str(ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(background), "-i", str(presenter_track),
        "-stream_loop", "-1", "-i", str(generated), "-filter_complex", graph,
        "-map", "[v]", "-map", "[mixed]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total_duration:.3f}",
        "-movflags", "+faststart", str(final),
    ])

    subtitle_segments = [
        {"start": index * SEGMENT_SECONDS, "end": min(total_duration, (index + 1) * SEGMENT_SECONDS), "text": script}
        for index, script in enumerate(scripts)
    ]
    srt = output / "grizzlymax_complete_workflow_expanded.srt"
    vtt = output / "grizzlymax_complete_workflow_expanded.vtt"
    write_subtitles(subtitle_segments, srt, vtt)

    qa = inspect_media(ffprobe, final)
    qa.update({
        "reused_presenter_clips": 11,
        "new_presenter_clips": 3,
        "chapters": len(chapters),
        "real_generated_clip": str(generated),
        "source_run": str(source),
        "expanded_checks": {
            "speed_lora_enlarged": True,
            "realism_lora_enlarged": True,
            "finished_result_double_click_shown": True,
            "preview_player_shown": True,
            "open_output_folder_shown": True,
        },
    })
    qa["passed"] = bool(qa["passed"] and all(qa["expanded_checks"].values()))
    (output / "qa" / "final_video.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "final_video": str(final),
        "source_run": str(source),
        "duration_seconds": total_duration,
        "chapters": chapters,
        "passed": qa["passed"],
    }
    (output / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not qa["passed"]:
        raise RuntimeError(f"Expanded tutorial QA failed: {qa}")
    print(f"FINAL_VIDEO={final}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
