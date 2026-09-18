from __future__ import annotations

from pathlib import Path

import pyttsx3

from ..base import VoiceProvider


class SapiVoiceProvider(VoiceProvider):
    def __init__(self, preferred_voice: str = "", rate: int = 172):
        self.preferred_voice = preferred_voice.lower().strip()
        self.rate = rate

    def synthesize(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        engine = pyttsx3.init("sapi5")
        engine.setProperty("rate", self.rate)
        if self.preferred_voice:
            for voice in engine.getProperty("voices"):
                if self.preferred_voice in (voice.name or "").lower():
                    engine.setProperty("voice", voice.id)
                    break
        engine.save_to_file(text, str(output_path))
        engine.runAndWait()
        engine.stop()
        if not output_path.is_file() or output_path.stat().st_size < 1000:
            raise RuntimeError(f"Narration was not produced: {output_path}")
        return output_path

