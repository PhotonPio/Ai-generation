from __future__ import annotations

import asyncio
from pathlib import Path

from ..image_generator import ImageGenerator
from ..scene_builder import Scene


class MediaService:
    def __init__(self, generator: ImageGenerator) -> None:
        self.generator = generator

    def generate(self, scenes: list[Scene], output_dir: Path, steps: int | None, seed: int | None, max_workers: int = 5) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            return asyncio.run(self.generator.generate_images_async(scenes, output_dir, max_workers=max_workers, steps=steps, seed=seed))
        except RuntimeError:
            return self.generator.generate_images_parallel(scenes, output_dir, max_workers=max_workers, steps=steps, seed=seed)
