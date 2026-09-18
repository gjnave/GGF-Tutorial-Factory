from __future__ import annotations

import subprocess
from pathlib import Path

from factory.edit.ffmpeg_renderer import has_audio_stream, probe_duration


class CompleteTutorialRenderer:
    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def join_presenter_clips(self, clips: list[Path], output: Path) -> Path:
        if not clips:
            raise ValueError("At least one Liz presenter clip is required")
        output.parent.mkdir(parents=True, exist_ok=True)
        concat_file = output.with_suffix(".concat.txt")
        lines = []
        for clip in clips:
            escaped = clip.resolve().as_posix().replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-vf", "scale=512:512,fps=24,format=yuv420p",
            "-af", "aresample=48000",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
        ]
        subprocess.run(command, check=True)
        return output

    @staticmethod
    def _chapter_filters(segment_seconds: float, chapters: list[str]) -> str:
        filters = []
        for index, title in enumerate(chapters):
            start = index * segment_seconds
            end = (index + 1) * segment_seconds
            safe_title = title.replace("'", "").replace(":", " -")
            filters.extend([
                f"drawbox=x=38:y=38:w=650:h=72:color=0x0B121A@0.90:t=fill:enable='between(t,{start:.3f},{end:.3f})'",
                f"drawbox=x=38:y=38:w=650:h=72:color=0xF28C28@0.95:t=4:enable='between(t,{start:.3f},{end:.3f})'",
                f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='{safe_title}':x=66:y=58:fontsize=30:fontcolor=white:enable='between(t,{start:.3f},{end:.3f})'",
            ])
        return ",".join(filters)

    def render(
        self,
        ui_capture: Path,
        generated_clip: Path,
        presenter_track: Path,
        output: Path,
        chapters: list[str],
        segment_seconds: float,
        result_start: float,
    ) -> Path:
        total_duration = probe_duration(self.ffprobe, presenter_track)
        ui_duration = probe_duration(self.ffprobe, ui_capture)
        result_start = min(result_start, total_duration - segment_seconds)
        result_length = total_duration - result_start
        ui_keep = min(ui_duration, result_start)
        ui_pad = max(0.0, result_start - ui_keep)
        chapter_filters = self._chapter_filters(segment_seconds, chapters)

        graph = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"trim=duration={ui_keep:.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={ui_pad:.3f}[ui];"
            f"[1:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
            f"trim=duration={result_length:.3f},setpts=PTS-STARTPTS[result];"
            f"[ui][result]concat=n=2:v=1:a=0,trim=duration={total_duration:.3f},setpts=PTS-STARTPTS,"
            f"{chapter_filters},"
            f"drawbox=x=1518:y=668:w=382:h=382:color=0x0B121A@0.96:t=fill,"
            f"drawbox=x=1518:y=668:w=382:h=382:color=0xF28C28@0.95:t=5[background];"
            f"[2:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
            f"trim=duration={total_duration:.3f},setpts=PTS-STARTPTS[liz];"
            f"[background][liz]overlay=x=1529:y=679:shortest=1:eof_action=pass,fps=30[v];"
            f"[2:a]loudnorm=I=-16:LRA=11:TP=-1.5,apad=pad_dur={total_duration:.3f},"
            f"atrim=duration={total_duration:.3f}[liz_audio]"
        )
        audio_map = "[liz_audio]"
        if has_audio_stream(self.ffprobe, generated_clip):
            graph += (
                f";[1:a]atrim=duration={result_length:.3f},volume=0.16,"
                f"adelay={int(result_start * 1000)}:all=1[generated_audio];"
                f"[liz_audio][generated_audio]amix=inputs=2:duration=longest:dropout_transition=0,"
                f"atrim=duration={total_duration:.3f}[mixed]"
            )
            audio_map = "[mixed]"

        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-i", str(ui_capture), "-stream_loop", "-1", "-i", str(generated_clip),
            "-i", str(presenter_track), "-filter_complex", graph,
            "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{total_duration:.3f}",
            "-movflags", "+faststart", str(output),
        ]
        subprocess.run(command, check=True)
        return output
