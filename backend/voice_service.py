from __future__ import annotations

from pathlib import Path

from ..scene_builder import Scene
from ..voice_generator import VoiceGenerator


class VoiceService:
    def __init__(self, generator: VoiceGenerator) -> None:
        self.generator = generator

    def generate(self, scenes: list[Scene], output_dir: Path, max_workers: int) -> list[Path]:
        return self.generator.generate_audio_parallel(scenes, output_dir, max_workers=max_workers)
