from __future__ import annotations

import subprocess
from pathlib import Path

from scene_builder import Scene


class VoiceGenerator:
    def __init__(self, model_path: str | Path = "models/en_US-lessac-medium.onnx") -> None:
        self.piper_model_path = Path(model_path)

    def generate_scene_audio(self, scene: Scene, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._generate_with_piper(scene.narration, output_path):
            return output_path

        if self._generate_with_espeak(scene.narration, output_path):
            return output_path

        raise RuntimeError("Failed to generate narration audio with Piper or espeak.")

    def _generate_with_piper(self, text: str, output_path: Path) -> bool:
        if not self.piper_model_path.exists():
            return False

        cmd = [
            "bash",
            "-lc",
            f"echo {self._shell_quote(text)} | piper --model {self.piper_model_path} --output_file {output_path}",
        ]
        try:
            subprocess.check_output(cmd, text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.CalledProcessError:
            return False

    def _generate_with_espeak(self, text: str, output_path: Path) -> bool:
        cmd = ["espeak", "-w", str(output_path), text]
        try:
            subprocess.check_output(cmd, text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.CalledProcessError:
            return False

    def _shell_quote(self, text: str) -> str:
        return "'" + text.replace("'", "'\\''") + "'"
