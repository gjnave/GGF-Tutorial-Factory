from __future__ import annotations

import datetime as dt
import subprocess
import time
from pathlib import Path

from ..base import PresenterProvider


class Ltx25LizPresenterProvider(PresenterProvider):
    """Generate short, consistently framed Liz presenter clips with the installed LTX 2.5 venv."""

    def __init__(
        self,
        ltx_root: Path = Path(r"D:\apps2review\ltx25\New folder\LTX-2"),
        base_image: Path = Path(r"D:\liz\ltx25\liz_medium_512.png"),
        frames: int = 193,
        fps: int = 24,
        seed: int = 250901,
        offload: str = "disk",
    ):
        self.ltx_root = ltx_root
        self.base_image = base_image
        self.frames = frames
        self.fps = fps
        self.seed = seed
        self.offload = offload
        self.python = ltx_root / ".venv" / "Scripts" / "python.exe"
        self.timing_log = Path(r"D:\liz\ltx25\logs\render-times.tsv")

    @staticmethod
    def _ascii(text: str) -> str:
        return (
            text.replace("\u2014", "-")
            .replace("\u2013", "-")
            .replace("\u2011", "-")
            .replace("\u2019", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
        )

    def prompt_for(self, text: str) -> str:
        spoken = self._ascii(text)
        return (
            "Use the provided start image as the first frame. Tight close-up portrait of Liz, "
            "a warm friendly GetGoingFast helper woman, centered in frame, face clearly visible, "
            "looking toward camera. She smiles and says in the same warm southern female voice, "
            f"\"{spoken}\" Her mouth articulates clearly while she speaks and she blinks naturally. "
            "A luminous galaxy swirls and slowly rotates behind her with glowing pink hearts, "
            "shimmering ribbons of light, sparkling stars, purple and magenta nebula clouds, and "
            "golden motes. Static locked camera, head mostly stable, identity consistent, soft "
            "friendly expression, clean face, no scene cut, no background noise."
        )

    def _validate_install(self) -> None:
        required = [
            self.python,
            self.base_image,
            self.ltx_root / r"models\ltx-2.5\diffusion_models\ltx-2.5-22b-distilled-transformer-bf16.safetensors",
            self.ltx_root / r"models\ltx-2.5\text_encoders\gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
            self.ltx_root / r"models\ltx-2.5\vae\ltx-2.5-video-vae-conv-bf16.safetensors",
            self.ltx_root / r"models\ltx-2.5\vae\ltx-2.5-audio-vae-bf16.safetensors",
            self.ltx_root / r"models\ltx-2.5\model_patches\ltx-2.5-duration-head-bf16.safetensors",
            self.ltx_root / r"models\ltx-2.5\latent_upscale_models\ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError("LTX 2.5 distilled requirements are missing:\n" + "\n".join(missing))

    def generate_presenter_clip(self, script: str, output_path: Path) -> Path:
        self._validate_install()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.python), "-m", "ltx_pipelines.distilled",
            "--transformer-path", r"models\ltx-2.5\diffusion_models\ltx-2.5-22b-distilled-transformer-bf16.safetensors",
            "--text-encoder-path", r"models\ltx-2.5\text_encoders\gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
            "--video-vae-path", r"models\ltx-2.5\vae\ltx-2.5-video-vae-conv-bf16.safetensors",
            "--audio-vae-path", r"models\ltx-2.5\vae\ltx-2.5-audio-vae-bf16.safetensors",
            "--duration-head-path", r"models\ltx-2.5\model_patches\ltx-2.5-duration-head-bf16.safetensors",
            "--spatial-upsampler-path", r"models\ltx-2.5\latent_upscale_models\ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
            "--height", "512", "--width", "512",
            "--num-frames", str(self.frames), "--frame-rate", str(self.fps),
            "--seed", str(self.seed), "--offload", self.offload, "--quantization", "fp8-cast",
            "--image", str(self.base_image), "0", "1.0",
            "--prompt", self.prompt_for(script), "--output-path", str(output_path),
        ]
        last_log = output_path.with_suffix(".attempt1.log")
        last_returncode = 1
        for attempt in (1, 2):
            log_path = output_path.with_suffix(f".attempt{attempt}.log")
            last_log = log_path
            print(f"LTX25_DISTILLED_RENDER_START={output_path.name} attempt={attempt}", flush=True)
            started = time.time()
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                process = subprocess.run(command, cwd=self.ltx_root, stdout=log, stderr=subprocess.STDOUT, text=True)
            elapsed = round(time.time() - started, 1)
            last_returncode = process.returncode
            self.timing_log.parent.mkdir(parents=True, exist_ok=True)
            with self.timing_log.open("a", encoding="utf-8") as handle:
                stamp = dt.datetime.now().replace(microsecond=0).isoformat()
                handle.write(f"ggf-tutorial-{output_path.stem}-attempt{attempt}\t{self.frames}\t512x512\t{elapsed}\t{process.returncode}\t{stamp}\n")
            if process.returncode == 0 and output_path.is_file() and output_path.stat().st_size >= 10000:
                print(f"LTX25_DISTILLED_RENDER_OK={output_path.name} elapsed={elapsed}s bytes={output_path.stat().st_size}", flush=True)
                return output_path
            print(f"LTX25_DISTILLED_RENDER_RETRY={output_path.name} failed_attempt={attempt} log={log_path}", flush=True)
        raise RuntimeError(f"LTX 2.5 distilled render failed after two attempts: {output_path.name}; log={last_log}; rc={last_returncode}")

    def generate_segments(self, scripts: list[str], output_dir: Path) -> list[Path]:
        clips = []
        for index, script in enumerate(scripts, 1):
            clips.append(self.generate_presenter_clip(script, output_dir / f"liz_{index:02d}.mp4"))
        return clips
