"""Lag-compensated verification of the 18 Darla sections in the final render."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import correlate

RATE = 8000
SEGMENT = 8.375
SOURCE = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\runs\2026-09-09_172652_grizzlymax_expanded-reference-text-workflows\presenter\clips")
FINAL = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\runs\2026-09-10_grizzlymax_darla_embedded_a2v_final\render\grizzlymax_expanded_reference_and_text_with_darla.mp4")


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


final = decode(FINAL)
passed = True
for index in range(1, 19):
    source = decode(SOURCE / f"darla_ltx25_clone_{index:02d}.mp4")
    source -= source.mean()
    expected = int((index - 1) * SEGMENT * RATE)
    lo = max(0, expected - RATE // 2)
    hi = min(final.size, expected + source.size + RATE // 2)
    window = final[lo:hi].copy()
    window -= window.mean()
    values = correlate(window, source, mode="valid", method="fft")
    energy = np.sqrt(np.convolve(window * window, np.ones(source.size), mode="valid")) * np.linalg.norm(source)
    scores = np.divide(values, energy, out=np.zeros_like(values), where=energy > 0)
    best = int(np.argmax(scores))
    score = float(scores[best])
    offset_ms = ((lo + best) - expected) * 1000.0 / RATE
    ok = score >= 0.90 and abs(offset_ms) <= 500.0
    passed &= ok
    print(f"segment={index:02d} correlation={score:.6f} offset_ms={offset_ms:.3f} pass={str(ok).lower()}")
print(f"ALL_AUDIO_SECTIONS_PASS={str(passed).lower()}")
raise SystemExit(0 if passed else 1)
