from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np
import torch

from fireredtts3.core import FireRedTTS3


def load_pcm16(path: Path) -> tuple[torch.Tensor, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"Gary prompt WAV must be PCM16, got sample width {width}")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    audio = audio.reshape(-1, channels).T
    return torch.from_numpy(audio), rate


def save_pcm16(path: Path, audio: torch.Tensor, rate: int) -> None:
    values = audio.detach().cpu().float().numpy()
    if values.ndim == 1:
        values = values[None, :]
    interleaved = np.clip(values.T, -1.0, 1.0)
    pcm = (interleaved * 32767.0).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(values.shape[0])
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--prompt-audio", type=Path, required=True)
    parser.add_argument("--prompt-text", required=True)
    parser.add_argument("--requests", type=Path, required=True)
    args = parser.parse_args()

    requests = json.loads(args.requests.read_text(encoding="utf-8"))
    prompt_audio, prompt_rate = load_pcm16(args.prompt_audio)
    tts = FireRedTTS3(str(args.model_root), use_wetext=True, use_llm_tn=False)
    for item in requests:
        output = Path(item["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        audio, rate = tts.generate(
            language="English",
            prompt_text=args.prompt_text,
            prompt_audio=prompt_audio,
            prompt_audio_sr=prompt_rate,
            text=str(item["text"]),
            do_tn=True,
        )
        save_pcm16(output, audio, rate)
        print(f"GARY_VOICE={output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
