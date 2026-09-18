from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from factory.edit.ffmpeg_renderer import has_audio_stream, probe_duration


VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class ProductionRenderer:
    """Standard approved-V2 renderer used by every application profile."""

    def __init__(self, ffmpeg: Path, ffprobe: Path):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def join_presenter_clips(self, clips: list[Path], output: Path) -> Path:
        if not clips:
            raise ValueError("At least one presenter clip is required")
        output.parent.mkdir(parents=True, exist_ok=True)
        listing = output.with_suffix(".concat.txt")
        listing.write_text(
            "".join(f"file '{clip.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for clip in clips),
            encoding="utf-8",
        )
        subprocess.run([
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-vf", "scale=512:512,fps=24,format=yuv420p,setpts=PTS-STARTPTS",
            "-af", "aresample=48000:async=1:first_pts=0,asetpts=PTS-STARTPTS",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
        ], check=True)
        return output

    def assemble_background(self, segments: list[dict[str, Any]], output: Path) -> Path:
        """Create a dead-time-free UI track from real captures and verified stills."""
        output.parent.mkdir(parents=True, exist_ok=True)
        segment_dir = output.parent / f"{output.stem}_segments"
        if segment_dir.exists():
            raise FileExistsError(f"Background segment directory already exists: {segment_dir}")
        segment_dir.mkdir(parents=True)
        rendered: list[Path] = []
        for index, item in enumerate(segments, 1):
            source = Path(item["source"]).resolve()
            duration = float(item["duration"])
            target = segment_dir / f"segment_{index:03d}.mp4"
            if source.suffix.lower() in VIDEO_SUFFIXES:
                input_args = ["-i", str(source)]
            else:
                input_args = ["-loop", "1", "-i", str(source)]
            subprocess.run([
                str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", *input_args,
                "-t", f"{duration:.3f}", "-an",
                "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,tpad=stop_mode=clone:stop_duration={duration:.3f},trim=duration={duration:.3f},fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(target),
            ], check=True)
            rendered.append(target)
        listing = output.with_suffix(".concat.txt")
        listing.write_text("".join(f"file '{item.resolve().as_posix()}'\n" for item in rendered), encoding="utf-8")
        subprocess.run([
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing), "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(output),
        ], check=True)
        return output

    @staticmethod
    def _escape_drawtext(text: str) -> str:
        return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "")

    def _chapter_filters(self, chapters: list[dict[str, Any]]) -> list[str]:
        filters: list[str] = []
        for chapter in chapters:
            start, end = float(chapter["start"]), float(chapter["end"])
            title = self._escape_drawtext(str(chapter["title"]))
            filters.extend([
                f"drawbox=x=38:y=38:w=720:h=72:color=0x0B121A@0.92:t=fill:enable='between(t,{start:.3f},{end:.3f})'",
                f"drawbox=x=38:y=38:w=720:h=72:color=0xF28C28@0.96:t=4:enable='between(t,{start:.3f},{end:.3f})'",
                f"drawtext=fontfile='C\\:/Windows/Fonts/segoeui.ttf':text='{title}':x=66:y=58:fontsize=30:fontcolor=white:enable='between(t,{start:.3f},{end:.3f})'",
            ])
        return filters

    def _focus_filters(self, focuses: list[dict[str, Any]], window_rect: list[int]) -> list[str]:
        wx, wy, ww, wh = [float(value) for value in window_rect]
        scale = min(1920.0 / ww, 1080.0 / wh)
        pad_x, pad_y = (1920.0 - ww * scale) / 2.0, (1080.0 - wh * scale) / 2.0
        filters: list[str] = []
        for focus in focuses:
            rect = focus.get("rect")
            if not rect or len(rect) != 4:
                continue
            width = min(1920, max(30, int(float(rect[2]) * scale) + 18))
            height = min(1080, max(30, int(float(rect[3]) * scale) + 18))
            raw_x = int((float(rect[0]) - wx) * scale + pad_x) - 9
            raw_y = int((float(rect[1]) - wy) * scale + pad_y) - 9
            x = min(max(0, raw_x), 1920 - width)
            y = min(max(0, raw_y), 1080 - height)
            start = max(0.0, float(focus.get("start", focus.get("time", 0.0))) - 0.3)
            end = float(focus.get("end", start + float(focus.get("duration", 2.0))))
            label = self._escape_drawtext(str(focus.get("label") or ""))
            filters.extend([
                f"drawbox=x={x}:y={y}:w={width}:h={height}:color=0xF28C28@0.24:t=fill:enable='between(t,{start:.3f},{end:.3f})'",
                f"drawbox=x={x}:y={y}:w={width}:h={height}:color=0xF28C28@1.0:t=6:enable='between(t,{start:.3f},{end:.3f})'",
            ])
            if label:
                label_y = max(120, y - 48)
                filters.extend([
                    f"drawbox=x={x}:y={label_y}:w={max(180, min(520, len(label) * 19 + 42))}:h=42:color=0x0B121A@0.94:t=fill:enable='between(t,{start:.3f},{end:.3f})'",
                    f"drawtext=fontfile='C\\:/Windows/Fonts/segoeuib.ttf':text='{label}':x={x + 16}:y={label_y + 10}:fontsize=22:fontcolor=white:enable='between(t,{start:.3f},{end:.3f})'",
                ])
        return filters

    @staticmethod
    def _scaled_focus_rect(rect: list[int], window_rect: list[int]) -> tuple[int, int, int, int]:
        wx, wy, ww, wh = [float(value) for value in window_rect]
        scale = min(1920.0 / ww, 1080.0 / wh)
        pad_x, pad_y = (1920.0 - ww * scale) / 2.0, (1080.0 - wh * scale) / 2.0
        width = min(1920, max(20, int(float(rect[2]) * scale)))
        height = min(1080, max(20, int(float(rect[3]) * scale)))
        raw_x = int((float(rect[0]) - wx) * scale + pad_x)
        raw_y = int((float(rect[1]) - wy) * scale + pad_y)
        x = min(max(0, raw_x), 1920 - width)
        y = min(max(0, raw_y), 1080 - height)
        return x, y, width, height

    @staticmethod
    def _closeup_has_content(image: Image.Image) -> bool:
        sample = image.convert("L").resize((64, 64), Image.Resampling.BILINEAR)
        histogram = sample.histogram()
        total = sum(histogram) or 1
        near_black_fraction = sum(histogram[:18]) / total
        return near_black_fraction < 0.82

    def _prepare_closeups(
        self,
        ui_capture: Path,
        focuses: list[dict[str, Any]],
        window_rect: list[int],
        output_root: Path,
    ) -> list[dict[str, Any]]:
        closeups: list[dict[str, Any]] = []
        output_root.mkdir(parents=True, exist_ok=True)
        ui_duration = probe_duration(self.ffprobe, ui_capture)
        font_path = Path(r"C:\Windows\Fonts\segoeuib.ttf")
        font = ImageFont.truetype(str(font_path), 27) if font_path.is_file() else ImageFont.load_default()
        for index, focus in enumerate((item for item in focuses if item.get("closeup") and item.get("rect")), 1):
            timestamp = min(max(0.0, float(focus["start"])), max(0.0, ui_duration - 0.1))
            full_frame = output_root / f"focus_{index:02d}_frame.png"
            subprocess.run([
                str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}",
                "-i", str(ui_capture), "-frames:v", "1",
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black",
                str(full_frame),
            ], check=True)
            x, y, width, height = self._scaled_focus_rect(list(focus["rect"]), window_rect)
            margin_x, margin_y = max(25, width // 12), max(25, height)
            crop_box = (
                max(0, x - margin_x), max(0, y - margin_y),
                min(1920, x + width + margin_x), min(1080, y + height + margin_y),
            )
            with Image.open(full_frame) as source:
                crop = source.convert("RGB").crop(crop_box)
                if not self._closeup_has_content(crop):
                    continue
                crop.thumbnail((1000, 215), Image.Resampling.LANCZOS)
            panel = Image.new("RGB", (1040, 280), "#0b121a")
            px, py = (1040 - crop.width) // 2, 52 + (215 - crop.height) // 2
            panel.paste(crop, (px, py))
            draw = ImageDraw.Draw(panel)
            draw.rectangle((2, 2, 1037, 277), outline="#f28c28", width=6)
            draw.text((18, 13), str(focus.get("label") or "LOOK HERE"), fill="white", font=font)
            panel_path = output_root / f"focus_{index:02d}_panel.png"
            panel.save(panel_path)
            closeups.append({**focus, "panel": panel_path})
        return closeups

    @staticmethod
    def _presenter_y(chapters: list[dict[str, Any]]) -> str:
        expression = "668"
        for chapter in reversed(chapters):
            if str(chapter.get("presenter_position") or "lower-right") == "upper-right":
                expression = f"if(between(t,{float(chapter['start']):.3f},{float(chapter['end']):.3f}),128,{expression})"
        return expression

    def render(
        self,
        ui_capture: Path,
        presenter_track: Path,
        output: Path,
        chapters: list[dict[str, Any]],
        window_rect: list[int],
        focuses: list[dict[str, Any]],
        result_media: Path | None = None,
        result_start: float | None = None,
    ) -> Path:
        total = probe_duration(self.ffprobe, presenter_track)
        ui_duration = probe_duration(self.ffprobe, ui_capture)
        visual_filters = self._chapter_filters(chapters) + self._focus_filters(focuses, window_rect)
        filter_chain = ",".join(visual_filters)
        if filter_chain:
            filter_chain = "," + filter_chain
        inputs = ["-i", str(ui_capture), "-i", str(presenter_track)]
        result_is_video = bool(result_media and result_media.suffix.lower() in VIDEO_SUFFIXES)
        start = min(float(result_start if result_start is not None else max(0.0, total - 8.0)), max(0.0, total - 1.0))
        if result_media:
            inputs += ["-stream_loop", "-1", "-i", str(result_media)] if result_is_video else ["-i", str(result_media)]
        closeups = self._prepare_closeups(ui_capture, focuses, window_rect, output.parent / "closeups")
        closeup_start_index = 3 if result_media else 2
        for closeup in closeups:
            inputs += ["-loop", "1", "-i", str(closeup["panel"])]
        if result_is_video:
            keep = min(ui_duration, start)
            padding = max(0.0, start - keep)
            result_length = total - start
            base = (
                f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"trim=duration={keep:.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={padding:.3f}[ui];"
                f"[2:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,trim=duration={result_length:.3f},setpts=PTS-STARTPTS[result];"
                f"[ui][result]concat=n=2:v=1:a=0,trim=duration={total:.3f},setpts=PTS-STARTPTS{filter_chain}[base]"
            )
        else:
            padding = max(0.0, total - ui_duration)
            base = (
                f"[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"trim=duration={min(ui_duration, total):.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={padding:.3f},"
                f"trim=duration={total:.3f}{filter_chain}[base]"
            )
        base_label = "base"
        closeup_graph = ""
        for index, closeup in enumerate(closeups):
            next_label = f"base_closeup_{index}"
            closeup_graph += (
                f";[{base_label}][{closeup_start_index + index}:v]overlay=x=38:y=760:"
                f"enable='between(t,{float(closeup['start']):.3f},{float(closeup['end']):.3f})':eof_action=pass[{next_label}]"
            )
            base_label = next_label
        presenter_y = self._presenter_y(chapters)
        graph = (
            base
            + closeup_graph
            + f";[1:v]scale=360:360:force_original_aspect_ratio=increase,crop=360:360,"
              f"pad=382:382:11:11:color=0xF28C28,trim=duration={total:.3f},setpts=PTS-STARTPTS[presenter];"
              f"[{base_label}][presenter]overlay=x=1518:y='{presenter_y}':shortest=1:eof_action=pass,fps=30[v];"
              f"[1:a]loudnorm=I=-16:LRA=11:TP=-1.5,apad=pad_dur={total:.3f},atrim=duration={total:.3f}[voice]"
        )
        audio_map = "[voice]"
        if result_media and has_audio_stream(self.ffprobe, result_media):
            source_index = 2
            delay = int(start * 1000)
            graph += (
                f";[{source_index}:a]volume=0.12,adelay={delay}:all=1,atrim=duration={total:.3f}[result_audio];"
                f"[voice][result_audio]amix=inputs=2:duration=longest:dropout_transition=0,atrim=duration={total:.3f}[mixed]"
            )
            audio_map = "[mixed]"
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", *inputs,
            "-filter_complex", graph, "-map", "[v]", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", f"{total:.3f}", "-movflags", "+faststart", str(output),
        ], check=True)
        return output

    def create_contact_sheet(self, video: Path, chapters: list[dict[str, Any]], output: Path) -> Path:
        frames: list[Path] = []
        output.parent.mkdir(parents=True, exist_ok=True)
        frame_dir = output.parent / "chapter_frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        for index, chapter in enumerate(chapters, 1):
            timestamp = (float(chapter["start"]) + float(chapter["end"])) / 2.0
            frame = frame_dir / f"chapter_{index:02d}.png"
            subprocess.run([
                str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}",
                "-i", str(video), "-frames:v", "1", "-vf", "scale=480:270", str(frame),
            ], check=True)
            frames.append(frame)
        columns = 3
        rows = math.ceil(len(frames) / columns)
        sheet = Image.new("RGB", (columns * 480, rows * 310), "#0b121a")
        draw = ImageDraw.Draw(sheet)
        for index, (frame, chapter) in enumerate(zip(frames, chapters)):
            x, y = (index % columns) * 480, (index // columns) * 310
            with Image.open(frame) as image:
                sheet.paste(image.convert("RGB"), (x, y))
            draw.text((x + 12, y + 278), str(chapter["title"]), fill="white")
        sheet.save(output)
        return output
