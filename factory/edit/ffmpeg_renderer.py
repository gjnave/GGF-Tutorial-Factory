from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe_duration(ffprobe: Path, media: Path) -> float:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def has_audio_stream(ffprobe: Path, media: Path) -> bool:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(media)],
        capture_output=True, text=True, check=True,
    )
    return bool(result.stdout.strip())


class FFmpegRenderer:
    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def render(self, ui_capture: Path, generated_clip: Path, narration: Path, output: Path) -> Path:
        narration_duration = probe_duration(self.ffprobe, narration)
        ui_duration = probe_duration(self.ffprobe, ui_capture)
        target_duration = max(60.0, min(120.0, narration_duration + 2.0))
        result_start = min(max(35.0, ui_duration - 2.0), target_duration - 10.0)
        result_length = max(6.0, target_duration - result_start)
        ui_keep = min(ui_duration, result_start)
        ui_pad = max(0.0, result_start - ui_keep)
        # Preserve the real UI capture, then loop the genuine generated result as the payoff.
        graph = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"trim=duration={ui_keep:.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={ui_pad:.3f},"
            f"drawbox=x=40:y=40:w=780:h=86:color=0xF28C28@0.78:t=fill:enable='between(t,0,4)',"
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='Create Your First Text-to-Video':x=72:y=64:fontsize=38:fontcolor=white:enable='between(t,0,4)',"
            f"drawbox=x=1510:y=105:w=410:h=130:color=0x0B121A@0.98:t=fill:enable='between(t,14,{result_start:.3f})',"
            f"drawbox=x=1510:y=105:w=410:h=130:color=0xF28C28@0.95:t=4:enable='between(t,14,{result_start:.3f})',"
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='Real job running in Queue':x=1538:y=154:fontsize=28:fontcolor=white:enable='between(t,14,{result_start:.3f})'[ui];"
            f"[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"trim=duration={result_length:.3f},setpts=PTS-STARTPTS,"
            f"drawbox=x=40:y=40:w=520:h=72:color=0xF28C28@0.78:t=fill:enable='between(t,0,4)',"
            f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='Your real generated result':x=70:y=60:fontsize=32:fontcolor=white:enable='between(t,0,4)'[result];"
            f"[ui][result]concat=n=2:v=1:a=0,trim=duration={target_duration:.3f},setpts=PTS-STARTPTS,fps=30[v];"
            f"[2:a]loudnorm=I=-16:LRA=11:TP=-1.5,apad=pad_dur={target_duration:.3f},atrim=duration={target_duration:.3f}[narration]"
        )
        audio_map = "[narration]"
        if has_audio_stream(self.ffprobe, generated_clip):
            graph += (
                f";[1:a]atrim=duration={result_length:.3f},"
                f"adelay={int(result_start * 1000)}|{int(result_start * 1000)},volume=0.22[generated_audio];"
                f"[narration][generated_audio]amix=inputs=2:duration=longest:dropout_transition=0,"
                f"atrim=duration={target_duration:.3f}[mixed]"
            )
            audio_map = "[mixed]"
        command = [
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-i", str(ui_capture), "-stream_loop", "-1", "-i", str(generated_clip), "-i", str(narration),
            "-filter_complex", graph, "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{target_duration:.3f}",
            "-movflags", "+faststart", str(output),
        ]
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True)
        return output
