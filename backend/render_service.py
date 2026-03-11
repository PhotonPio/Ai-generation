from __future__ import annotations

from pathlib import Path

from ..scene_builder import Scene
from ..video_renderer import VideoRenderer


class RenderService:
    def __init__(self, renderer: VideoRenderer) -> None:
        self.renderer = renderer

    def render(self, scenes: list[Scene], images: list[Path], audios: list[Path], transition_style: str) -> list[Path]:
        return self.renderer.render_segments(scenes, images, audios, transition_style=transition_style)
