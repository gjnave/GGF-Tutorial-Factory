"""Generate native LTX 2.5 audio-conditioned Darla clips from any tutorial YAML."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from factory.presenter.providers.darla_ltx_a2v import DarlaLtxA2VPresenterProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tutorial", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--only", type=int, default=0, help="Generate one 1-based narration segment for validation.")
    args = parser.parse_args()
    tutorial_path = args.tutorial.resolve()
    output_root = args.output.resolve()
    data = yaml.safe_load(tutorial_path.read_text(encoding="utf-8"))
    scripts = [str(item["text"]).strip() for item in data["narration"]["segments"]]
    if not scripts or any(not script for script in scripts):
        raise ValueError("The tutorial must contain non-empty narration.segments text entries")
    provider = DarlaLtxA2VPresenterProvider()
    if args.only:
        index = args.only
        if index < 1 or index > len(scripts):
            raise ValueError(f"--only must be from 1 to {len(scripts)}")
        output = output_root / f"darla_ltx_a2v_{index:02d}.mp4"
        print(f"A2V_SEGMENT={index} OUTPUT={output}", flush=True)
        provider.generate_presenter_clip(scripts[index - 1], output, index=index)
        return 0
    for index, output in enumerate(provider.generate_segments(scripts, output_root), 1):
        print(f"A2V_SEGMENT={index} OUTPUT={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
