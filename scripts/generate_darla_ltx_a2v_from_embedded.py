"""Generate Darla presenter clips from the Darla audio embedded in prior MP4s.

This deliberately has no voice-cloning, TTS, tempo, Wav2Lip, or post-mux path.
The supplied MP4 is decoded once to PCM (and duplicated to stereo for LTX), padded
only with trailing silence to the required 8*k+1 frame duration, then passed to
LTX's native A2V pipeline using ``--audio-path``.  The output MP4 is retained
unchanged after LTX writes it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(r"D:\ggf-tools\GGF-Tutorial-Factory")
LTX_ROOT = Path(r"D:\apps2review\ltx25\New folder\LTX-2")
SOURCE_CLIPS = ROOT / "runs" / "2026-09-09_172652_grizzlymax_expanded-reference-text-workflows" / "presenter" / "clips"
AVATAR = ROOT / "assets" / "presenters" / "darla" / "darla_avatar.png"
FPS = 24


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def duration(ffprobe: str, path: Path) -> float:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def has_audio(ffprobe: str, path: Path) -> bool:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def ltx_paths() -> dict[str, Path]:
    model = LTX_ROOT / "models" / "ltx-2.5"
    return {
        "python": LTX_ROOT / ".venv" / "Scripts" / "python.exe",
        "transformer": model / "diffusion_models" / "ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "text_encoder": model / "text_encoders" / "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "video_vae": model / "vae" / "ltx-2.5-video-vae-conv-bf16.safetensors",
        "audio_vae": model / "vae" / "ltx-2.5-audio-vae-bf16.safetensors",
        "duration_head": model / "model_patches" / "ltx-2.5-duration-head-bf16.safetensors",
        "spatial_upsampler": model / "latent_upscale_models" / "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "distilled_lora": model / "loras" / "ltx-2.5-22b-distilled-lora-450-bf16.safetensors",
    }


def extract_and_pad(ffmpeg: str, ffprobe: str, source: Path, audio_dir: Path, index: int) -> tuple[Path, int, float]:
    """Decode supplied embedded audio, then add trailing silence only when needed."""
    audio_dir.mkdir(parents=True, exist_ok=True)
    decoded = audio_dir / f"darla_embedded_{index:02d}.stereo.wav"
    padded = audio_dir / f"darla_embedded_{index:02d}.stereo.padded.wav"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-y", "-i", str(source),
        "-map", "0:a:0", "-vn", "-ac", "2", "-c:a", "pcm_s16le", str(decoded),
    ], check=True)
    original_duration = duration(ffprobe, decoded)
    frames = max(81, int(math.ceil((original_duration * FPS - 1) / 8.0) * 8 + 1))
    target_duration = frames / FPS
    # `apad` may append silence but never alters the decoded Darla samples.
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-y", "-i", str(decoded),
        "-af", f"apad=whole_dur={target_duration:.9f},atrim=duration={target_duration:.9f}",
        "-ac", "2", "-c:a", "pcm_s16le", str(padded),
    ], check=True)
    padded_duration = duration(ffprobe, padded)
    if padded_duration + 0.02 < original_duration or abs(padded_duration - target_duration) > 0.03:
        raise RuntimeError(f"Invalid Darla audio preparation for segment {index}: {original_duration:.3f}s -> {padded_duration:.3f}s")
    return padded, frames, target_duration


def generate(output_dir: Path, index: int) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    paths = ltx_paths()
    offload = os.environ.get("DARLA_LTX_OFFLOAD", "cpu").strip().lower()
    if offload not in {"cpu", "disk"}:
        raise ValueError("DARLA_LTX_OFFLOAD must be cpu or disk")
    required = [AVATAR, *paths.values()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing native LTX requirements:\n" + "\n".join(missing))
    source = SOURCE_CLIPS / f"darla_ltx25_clone_{index:02d}.mp4"
    if not source.is_file() or not has_audio(ffprobe, source):
        raise FileNotFoundError(f"Supplied Darla source clip/audio is missing: {source}")
    output_dir.mkdir(parents=True, exist_ok=True)
    audio, frames, target_duration = extract_and_pad(ffmpeg, ffprobe, source, output_dir / "audio", index)
    output = output_dir / f"darla_ltx_a2v_{index:02d}.mp4"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite an existing generated clip: {output}")
    command = [
        str(paths["python"]), "-m", "ltx_pipelines.a2vid_two_stage",
        "--transformer-path", str(paths["transformer"]), "--text-encoder-path", str(paths["text_encoder"]),
        "--video-vae-path", str(paths["video_vae"]), "--audio-vae-path", str(paths["audio_vae"]),
        "--duration-head-path", str(paths["duration_head"]), "--spatial-upsampler-path", str(paths["spatial_upsampler"]),
        "--distilled-lora", str(paths["distilled_lora"]), "1.0", "--image", str(AVATAR), "0", "1.0",
        "--audio-path", str(audio), "--audio-max-duration", f"{target_duration:.6f}",
        "--prompt", "Natural presenter motion: Darla sits behind the stationary Get Going Fast box, facing the camera with accurate speech motion, natural facial expressions, subtle hand and upper-body movement, locked camera, realistic studio lighting.",
        "--height", "512", "--width", "512", "--num-frames", str(frames), "--frame-rate", str(FPS),
        "--num-inference-steps", "30", "--a2v-guidance-scale", "3.0", "--seed", str(260900 + index),
        "--quantization", "fp8-cast", "--offload", offload, "--output-path", str(output),
    ]
    environment = os.environ.copy()
    pipeline_src = LTX_ROOT / "packages" / "ltx-pipelines" / "src"
    environment["PYTHONPATH"] = str(pipeline_src) + os.pathsep + environment.get("PYTHONPATH", "")
    log = output.with_suffix(".ltx-a2v.log")
    transient = "Attempted to access the data pointer on an invalid python storage"
    result = None
    for attempt in range(1, 5):
        with log.open("w", encoding="utf-8") as stream:
            stream.write("SOURCE_EMBEDDED_DARLA_MP4=" + str(source) + "\n")
            stream.write("SOURCE_SHA256=" + sha256(source) + "\n")
            stream.write("AUDIO_PATH=" + str(audio) + "\n")
            stream.write("AUDIO_SHA256=" + sha256(audio) + "\n")
            stream.write("COMMAND=" + subprocess.list2cmdline(command) + "\n")
            stream.write(f"ATTEMPT={attempt}\n")
            result = subprocess.run(command, cwd=LTX_ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            break
        detail = log.read_text(encoding="utf-8", errors="replace")
        windows_access_violation = result.returncode in {-1073741819, 3221225477}
        if (transient not in detail and not windows_access_violation) or attempt == 4:
            break
        time.sleep(3)
    if result is None or result.returncode:
        raise RuntimeError(f"Native LTX A2V failed for Darla segment {index}; see {log}")
    if not output.is_file() or output.stat().st_size < 10_000 or not has_audio(ffprobe, output):
        raise RuntimeError(f"Native LTX output is not a valid audio/video MP4: {output}")
    output_duration = duration(ffprobe, output)
    if abs(output_duration - target_duration) > 0.08:
        raise RuntimeError(f"LTX duration mismatch for segment {index}: {output_duration:.3f}s vs {target_duration:.3f}s")
    record = {
        "segment": index, "source_embedded_darla_mp4": str(source), "source_sha256": sha256(source),
        "conditioned_audio": str(audio), "conditioned_audio_sha256": sha256(audio), "frames": frames,
        "fps": FPS, "target_duration": target_duration, "ltx_output": str(output), "ltx_output_duration": output_duration,
        "post_generation_audio_replacement": False,
    }
    (output_dir / f"darla_ltx_a2v_{index:02d}.provenance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record), flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--only", type=int, default=0, help="Generate only a 1-based supplied Darla segment.")
    parser.add_argument("--from-index", type=int, default=1, help="First segment when generating a sequential remaining range.")
    args = parser.parse_args()
    indexes = [args.only] if args.only else list(range(args.from_index, 19))
    if any(index < 1 or index > 18 for index in indexes):
        raise ValueError("--only and --from-index must be from 1 to 18")
    for index in indexes:
        generate(args.output, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
