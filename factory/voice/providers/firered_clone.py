from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


class FireRedVoiceCloneProvider:
    def __init__(
        self,
        install_root: Path = Path(r"D:\apps2review\firered-tts\FireRedTTS3"),
        prompt_audio: Path = Path(r"D:\ggf-tools\GGF-Tutorial-Factory\assets\presenters\gary\gary_voice_reference.wav"),
        prompt_text: str = (
            "Hey, my dudes, this is Gary from Get Going Fast. Or I should say that this is his voice clone. "
            "You're all the bomb and I love working with you. Get Going Fast is definitely the place for us all to be."
        ),
    ):
        self.install_root = install_root.resolve()
        self.python = self.install_root / ".venv" / "Scripts" / "python.exe"
        self.model_root = self.install_root / "pretrained_models"
        self.prompt_audio = prompt_audio.resolve()
        self.prompt_text = prompt_text

    def synthesize_many(
        self,
        scripts: list[str],
        output_dir: Path,
        *,
        name_prefix: str = "gary_voice",
        start_index: int = 1,
    ) -> list[Path]:
        required = (self.python, self.model_root, self.prompt_audio)
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError("Gary voice-clone requirements are missing:\n" + "\n".join(missing))
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = [
            output_dir / f"{name_prefix}_{index:02d}.wav"
            for index in range(start_index, start_index + len(scripts))
        ]
        requests = output_dir / f"{name_prefix}_requests.json"
        requests.write_text(
            json.dumps([{"text": text, "output": str(path.resolve())} for text, path in zip(scripts, outputs)], indent=2),
            encoding="utf-8",
        )
        worker = Path(__file__).with_name("firered_clone_worker.py")
        command = [
            str(self.python), str(worker),
            "--model-root", str(self.model_root),
            "--prompt-audio", str(self.prompt_audio),
            "--prompt-text", self.prompt_text,
            "--requests", str(requests),
        ]
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(self.install_root) + (os.pathsep + existing if existing else "")
        subprocess.run(command, cwd=self.install_root, env=env, check=True)
        missing_outputs = [str(path) for path in outputs if not path.is_file() or path.stat().st_size < 1000]
        if missing_outputs:
            raise RuntimeError("Gary voice cloning did not create valid outputs:\n" + "\n".join(missing_outputs))
        return outputs
