from __future__ import annotations

"""Scene planning utilities for turning script text into timed scene segments."""

import math
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

_HAS_NLTK = importlib.util.find_spec("nltk") is not None
if _HAS_NLTK:
    import nltk

try:
    from .script_generator import ScenePlan
except ImportError:  # pragma: no cover - supports running as flat scripts
    from script_generator import ScenePlan


STYLE_DURATION_BIAS: dict[str, float] = {
    "educational": 1.0,
    "storytelling": 1.1,
    "documentary": 1.15,
    "fun": 0.9,
}


@dataclass
class Scene:
    """One renderable scene.

    Attributes:
        index: 1-based scene index.
        narration: Narration text for this scene.
        visual_prompt: Prompt sent to image generation.
        estimated_duration: Planned scene duration in seconds.
    """

    index: int
    narration: str
    visual_prompt: str
    estimated_duration: float


class SceneBuilder:
    """Transforms script scenes into render scenes with optional smart timing."""

    def __init__(self, min_scene_seconds: int = 5, max_scene_seconds: int = 15) -> None:
        self.min_scene_seconds = min_scene_seconds
        self.max_scene_seconds = max_scene_seconds

    def _estimate_duration(self, text: str, scene_seconds: int, style: str) -> float:
        """Estimate scene duration from sentence complexity and style."""

        words = len(text.split())
        base = max(scene_seconds, self.min_scene_seconds)
        complexity_boost = min(words / 30.0, 1.6)
        style_bias = STYLE_DURATION_BIAS.get(style, 1.0)
        seconds = base * complexity_boost * style_bias
        return float(max(self.min_scene_seconds, min(self.max_scene_seconds, math.ceil(seconds))))

    def _group_short_sentences(self, text: str) -> str:
        """Group short sentence fragments into denser narration blocks."""

        if _HAS_NLTK:
            try:
                sentences = nltk.sent_tokenize(text)
            except LookupError:
                sentences = [s.strip() for s in text.split(".") if s.strip()]
        else:
            # Offline-safe fallback when NLTK data is unavailable.
            sentences = [s.strip() for s in text.split(".") if s.strip()]

        if not sentences:
            return text

        grouped: list[str] = []
        bucket: list[str] = []

        for sentence in sentences:
            if len(sentence.split()) < 8:
                bucket.append(sentence)
                continue
            if bucket:
                grouped.append(" ".join(bucket))
                bucket = []
            grouped.append(sentence)

        if bucket:
            grouped.append(" ".join(bucket))

        return " ".join(grouped)

    def _build_one(self, plan: ScenePlan, scene_seconds: int, style: str, auto_scene_duration: bool) -> Scene:
        """Create one scene object from a source scene plan."""

        narration = self._group_short_sentences(plan.narration)
        duration = float(scene_seconds)
        if auto_scene_duration:
            duration = self._estimate_duration(narration, scene_seconds, style)
        return Scene(
            index=plan.index,
            narration=narration,
            visual_prompt=plan.visual_description,
            estimated_duration=duration,
        )

    def build(
        self,
        scene_plans: list[ScenePlan],
        scene_seconds: int,
        *,
        style: str = "educational",
        auto_scene_duration: bool = False,
        parallel: bool = True,
        max_workers: int = 4,
    ) -> list[Scene]:
        """Build render-ready scenes from script plans.

        Args:
            scene_plans: Input scene plans.
            scene_seconds: Baseline seconds per scene.
            style: Script style to influence duration heuristic.
            auto_scene_duration: Enables dynamic 5-15 second duration planning.
            parallel: Enables ThreadPoolExecutor preprocessing.
            max_workers: Max workers used when parallel is enabled.

        Returns:
            List of scene objects sorted by source index.
        """

        if not scene_plans:
            return []

        if not parallel or len(scene_plans) < 2:
            scenes = [
                self._build_one(plan, scene_seconds, style, auto_scene_duration)
                for plan in scene_plans
            ]
            return sorted(scenes, key=lambda s: s.index)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._build_one, plan, scene_seconds, style, auto_scene_duration)
                for plan in scene_plans
            ]
            scenes = [future.result() for future in futures]

        return sorted(scenes, key=lambda s: s.index)
