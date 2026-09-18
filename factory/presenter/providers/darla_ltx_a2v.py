"""Darla presenter clips generated with LTX 2.5's native audio-to-video pipeline.

The FireRed clone is generated before LTX and supplied through ``--audio-path``.
LTX conditions facial motion on that audio and writes it into the result.  Do not
replace, stretch, or mux narration after this provider has run.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import time
import hashlib
import json
import re
from pathlib import Path

from factory.edit.ffmpeg_renderer import has_audio_stream, probe_duration
from factory.presenter.base import PresenterProvider
from factory.voice.providers.firered_clone import FireRedVoiceCloneProvider


class DarlaLtxA2VPresenterProvider(PresenterProvider):
    """Create Darla motion and lip sync from FireRed-cloned narration."""

    PROMPT_TEXT = (
        "A seventy-year-old Idaho man was arrested after allegedly striking a "
        "pro-Trump counter-protester."
    )
    # A 21-second / 505-frame native proof is stable on the local RTX 4090
    # when its standard (non-streaming) transformer path is used.  Keep each
    # A2V invocation near that practical boundary, then join original embedded
    # AV streams without changing narration, rate, pitch, or lip-sync conditioning.
    MAX_WORDS_PER_NATIVE_CLIP = 80

    def __init__(self, fps: int = 24, seed: int = 250901):
        self.fps = fps
        self.seed = seed
        self.factory_root = Path(r"D:\\ggf-tools\\GGF-Tutorial-Factory")
        self.ltx_root = Path(r"D:\\apps2review\\ltx25\\New folder\\LTX-2")
        self.python = self.ltx_root / ".venv" / "Scripts" / "python.exe"
        self.model_root = self.ltx_root / "models" / "ltx-2.5"
        self.avatar = self.factory_root / "assets" / "presenters" / "darla" / "darla_avatar.png"
        self.voice = FireRedVoiceCloneProvider(
            prompt_audio=self.factory_root / "assets" / "presenters" / "darla" / "darla_voice_reference_short.wav",
            prompt_text=self.PROMPT_TEXT,
        )
        self.ffmpeg = Path(shutil.which("ffmpeg") or "ffmpeg")
        self.ffprobe = Path(shutil.which("ffprobe") or "ffprobe")

    @property
    def paths(self) -> dict[str, Path]:
        return {
            "transformer": self.model_root / "diffusion_models" / "ltx-2.5-22b-distilled-transformer-bf16.safetensors",
            "text_encoder": self.model_root / "text_encoders" / "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
            "video_vae": self.model_root / "vae" / "ltx-2.5-video-vae-conv-bf16.safetensors",
            "audio_vae": self.model_root / "vae" / "ltx-2.5-audio-vae-bf16.safetensors",
            "duration_head": self.model_root / "model_patches" / "ltx-2.5-duration-head-bf16.safetensors",
            "spatial_upsampler": self.model_root / "latent_upscale_models" / "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
            "distilled_lora": self.model_root / "loras" / "ltx-2.5-22b-distilled-lora-450-bf16.safetensors",
        }

    def _validate_installation(self) -> None:
        required = [self.python, self.avatar, *self.paths.values()]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError("LTX A2V presenter requirements are missing:\\n" + "\\n".join(missing))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _frames_for_audio(self, audio: Path) -> int:
        seconds = probe_duration(self.ffprobe, audio)
        # LTX requires 8*k+1 frames; round up so no clone speech is discarded.
        return max(81, int(math.ceil((seconds * self.fps - 1) / 8.0) * 8 + 1))

    def _stereo_for_ltx(self, clone: Path) -> Path:
        """LTX A2V expects two audio channels; duplicate mono without resampling or tempo changes."""
        stereo = clone.with_name(clone.stem + ".stereo.wav")
        subprocess.run(
            [str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(clone),
             "-ac", "2", "-c:a", "pcm_s16le", str(stereo)],
            check=True,
        )
        if not stereo.is_file() or probe_duration(self.ffprobe, stereo) + 0.01 < probe_duration(self.ffprobe, clone):
            raise RuntimeError(f"Stereo preparation failed for cloned Darla narration: {clone}")
        return stereo

    def _pad_for_ltx_shape(self, stereo: Path, frames: int) -> Path:
        """Pad only trailing silence so the audio latent exactly matches 8*k+1 frames."""
        target = frames / self.fps
        padded = stereo.with_name(stereo.stem + ".padded.wav")
        subprocess.run(
            [str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-i", str(stereo),
             "-af", f"apad=whole_dur={target:.9f},atrim=duration={target:.9f}",
             "-ac", "2", "-c:a", "pcm_s16le", str(padded)],
            check=True,
        )
        padded_duration = probe_duration(self.ffprobe, padded)
        if abs(padded_duration - target) > 0.03:
            raise RuntimeError(f"LTX audio padding did not match frame duration: {padded_duration:.3f}s vs {target:.3f}s")
        return padded

    def _generate(self, source_voice: Path, audio: Path, output: Path, index: int, frames: int) -> Path:
        duration = probe_duration(self.ffprobe, audio)
        p = self.paths
        output.parent.mkdir(parents=True, exist_ok=True)
        log = output.with_suffix(".ltx-a2v.log")
        command = [
            str(self.python), "-m", "ltx_pipelines.a2vid_two_stage",
            "--transformer-path", str(p["transformer"]), "--text-encoder-path", str(p["text_encoder"]),
            "--video-vae-path", str(p["video_vae"]), "--audio-vae-path", str(p["audio_vae"]),
            "--duration-head-path", str(p["duration_head"]), "--spatial-upsampler-path", str(p["spatial_upsampler"]),
            "--distilled-lora", str(p["distilled_lora"]), "1.0",
            "--image", str(self.avatar), "0", "1.0", "--audio-path", str(audio),
            "--audio-max-duration", f"{duration:.3f}",
            "--prompt", "A professional news presenter sits naturally behind the stationary Get Going Fast box. She looks at the camera, speaks clearly, uses subtle natural hand and body movements, and maintains realistic facial expression. Locked camera, realistic studio lighting.",
            "--height", "512", "--width", "512", "--num-frames", str(frames), "--frame-rate", str(self.fps),
            "--num-inference-steps", "30", "--a2v-guidance-scale", "3.0", "--seed", str(self.seed + index),
            "--quantization", "fp8-cast", "--offload", "cpu", "--output-path", str(output),
        ]
        env = os.environ.copy()
        pipeline_src = self.ltx_root / "packages" / "ltx-pipelines" / "src"
        env["PYTHONPATH"] = str(pipeline_src) + os.pathsep + env.get("PYTHONPATH", "")
        # Prefer the documented CPU streaming path.  On this RTX 4090, a
        # torch_cpu.dll access violation or invalid-storage error means that
        # streaming weights are unstable; retry the exact native part once in
        # a fresh standard-GPU process rather than altering its conditioned audio.
        result = None
        transient = "Attempted to access the data pointer on an invalid python storage"
        selected_offload = "cpu"
        for attempt, offload_mode in enumerate(("cpu", "none"), 1):
            command[command.index("--offload") + 1] = offload_mode
            with log.open("w", encoding="utf-8") as stream:
                stream.write("COMMAND=" + subprocess.list2cmdline(command) + "\\n")
                stream.write(f"ATTEMPT={attempt}\\n")
                stream.write(f"OFFLOAD={offload_mode}\\n")
                result = subprocess.run(command, cwd=self.ltx_root, env=env, stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode == 0:
                selected_offload = offload_mode
                break
            detail = log.read_text(encoding="utf-8", errors="replace")
            windows_access_violation = result.returncode in {-1073741819, 3221225477}
            if offload_mode != "cpu" or (transient not in detail and not windows_access_violation):
                break
            time.sleep(1.0)
        if result is None or result.returncode:
            raise RuntimeError(f"LTX audio-to-video failed for presenter segment {index}; see {log}")
        if not output.is_file() or output.stat().st_size < 10000 or not has_audio_stream(self.ffprobe, output):
            raise RuntimeError(f"LTX A2V did not produce a valid audio/video presenter clip: {output}")
        rendered_duration = probe_duration(self.ffprobe, output)
        if rendered_duration + 0.08 < duration:
            raise RuntimeError(f"LTX A2V clipped clone audio ({duration:.3f}s -> {rendered_duration:.3f}s): {output}")
        provenance = {
            "segment": index,
            "source_darla_voice": str(source_voice.resolve()),
            "source_darla_voice_sha256": self._sha256(source_voice),
            "conditioned_audio": str(audio.resolve()),
            "conditioned_audio_sha256": self._sha256(audio),
            "frames": frames,
            "fps": self.fps,
            "offload_mode": selected_offload,
            "conditioned_audio_duration": duration,
            "ltx_output": str(output.resolve()),
            "ltx_output_duration": rendered_duration,
            "post_generation_audio_replacement": False,
        }
        output.with_suffix(".provenance.json").write_text(
            json.dumps(provenance, indent=2), encoding="utf-8"
        )
        return output

    @classmethod
    def _split_script_for_native_a2v(cls, script: str) -> list[str]:
        """Split narration only at sentence/word boundaries for short LTX clips."""
        words = script.split()
        if len(words) <= cls.MAX_WORDS_PER_NATIVE_CLIP:
            return [script.strip()]
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\\s+", script.strip()) if item.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_words = 0
        for sentence in sentences:
            sentence_words = sentence.split()
            while sentence_words:
                remaining = cls.MAX_WORDS_PER_NATIVE_CLIP - current_words
                if remaining <= 0:
                    chunks.append(" ".join(current))
                    current, current_words = [], 0
                    remaining = cls.MAX_WORDS_PER_NATIVE_CLIP
                take = sentence_words[:remaining]
                current.extend(take)
                current_words += len(take)
                sentence_words = sentence_words[remaining:]
                if sentence_words or current_words >= cls.MAX_WORDS_PER_NATIVE_CLIP:
                    chunks.append(" ".join(current))
                    current, current_words = [], 0
        if current:
            chunks.append(" ".join(current))
        return chunks or [script.strip()]

    def _join_native_parts(self, parts: list[Path], output: Path, script: str) -> Path:
        """Concatenate native LTX AV streams without replacing or retiming audio."""
        if len(parts) == 1:
            shutil.copy2(parts[0], output)
        else:
            concat_file = output.with_suffix(".native-parts.txt")
            concat_file.write_text(
                "".join(f"file '{part.resolve().as_posix()}'\\n" for part in parts),
                encoding="utf-8",
            )
            subprocess.run(
                [str(self.ffmpeg), "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(concat_file), "-c", "copy", str(output)],
                check=True,
            )
        if not output.is_file() or output.stat().st_size < 10000 or not has_audio_stream(self.ffprobe, output):
            raise RuntimeError(f"Native Darla part join did not produce a valid AV clip: {output}")
        part_duration = sum(probe_duration(self.ffprobe, part) for part in parts)
        output_duration = probe_duration(self.ffprobe, output)
        if abs(output_duration - part_duration) > 0.2:
            raise RuntimeError(f"Native Darla join changed timeline duration: {part_duration:.3f}s -> {output_duration:.3f}s")
        part_provenance = []
        for part in parts:
            provenance_path = part.with_suffix(".provenance.json")
            if provenance_path.is_file():
                part_provenance.append(json.loads(provenance_path.read_text(encoding="utf-8")))
        output.with_suffix(".provenance.json").write_text(json.dumps({
            "script": script,
            "native_parts": [str(part.resolve()) for part in parts],
            "native_part_provenance": part_provenance,
            "output_duration": output_duration,
            "post_generation_audio_replacement": False,
            "audio_joined_only_from_native_ltx_parts": True,
        }, indent=2), encoding="utf-8")
        return output

    def _generate_script(self, script: str, output_path: Path, index: int) -> Path:
        self._validate_installation()
        chunks = self._split_script_for_native_a2v(script)
        part_dir = output_path.parent / "native-parts" / output_path.stem
        part_dir.mkdir(parents=True, exist_ok=True)
        voices = self.voice.synthesize_many(chunks, part_dir / "voice", name_prefix="darla_voice")
        parts: list[Path] = []
        for part_index, (chunk, clone) in enumerate(zip(chunks, voices), 1):
            stereo = self._stereo_for_ltx(clone)
            frames = self._frames_for_audio(stereo)
            part_output = part_dir / f"part_{part_index:02d}.mp4"
            # A distinct deterministic seed makes adjacent native pieces look
            # naturally alive while retaining reproducible reruns.
            parts.append(self._generate(
                clone, self._pad_for_ltx_shape(stereo, frames), part_output,
                index * 100 + part_index, frames,
            ))
        return self._join_native_parts(parts, output_path, script)

    def generate_presenter_clip(self, script: str, output_path: Path, index: int = 1) -> Path:
        return self._generate_script(script, output_path, index)

    def generate_segments(self, scripts: list[str], output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            self._generate_script(script, output_dir / f"darla_ltx_a2v_{index:02d}.mp4", index)
            for index, script in enumerate(scripts, 1)
        ]
