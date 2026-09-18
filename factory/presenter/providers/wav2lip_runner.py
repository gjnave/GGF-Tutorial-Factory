"""Small isolated runner for the Tutorial Factory Wav2Lip environment."""

from __future__ import annotations

import argparse
from pathlib import Path

from lipsync import LipSync
import lipsync.models as lipsync_models
import torch


def _load_gan_checkpoint(checkpoint_path: str, device: str):
    """Accept the standard Wav2Lip-GAN checkpoint wrapper as well as raw weights."""
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    return checkpoint.get("state_dict", checkpoint)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--face", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument("--box", type=int, nargs=4, metavar=("Y1", "Y2", "X1", "X2"))
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # face-alignment opportunistically calls torch.compile on recent PyTorch.
    # This isolated environment intentionally has no C++ compiler, and eager
    # execution is sufficient for a short static-presenter clip.
    torch.compile = lambda model, *unused_args, **unused_kwargs: model
    # The bundled package expects a raw state dictionary.  The standard GAN
    # checkpoint used by Tutorial Factory wraps it in ``state_dict``.
    lipsync_models._load = _load_gan_checkpoint
    sync = LipSync(
        checkpoint_path=str(Path(args.checkpoint).resolve()),
        # The dedicated lip-sync virtual environment currently ships CPU-only
        # PyTorch.  LipSync accepts the explicit CPU device and loads the CUDA
        # checkpoint through its safe map-location branch.
        device="cpu",
        fps=args.fps,
        pads=[0, 14, 0, 0],
        wav2lip_batch_size=32,
        ffmpeg_loglevel="warning",
        save_cache=False,
        box=args.box or [-1, -1, -1, -1],
    )
    sync.sync(str(Path(args.face).resolve()), str(Path(args.audio).resolve()), str(output.resolve()))
    if not output.is_file() or output.stat().st_size < 10_000:
        raise RuntimeError(f"Lip-sync did not create a usable video: {output}")
    print(f"LIPSYNC_VIDEO={output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
