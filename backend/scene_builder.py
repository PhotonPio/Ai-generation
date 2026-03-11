from __future__ import annotations

from dataclasses import dataclass

from script_generator import ScenePlan


@dataclass
class Scene:
    index: int
    narration: str
    visual_prompt: str
    estimated_duration: float


class SceneBuilder:
    def __init__(self, min_scene_seconds: int = 6) -> None:
        self.min_scene_seconds = min_scene_seconds

    def build(self, scene_plans: list[ScenePlan], scene_seconds: int) -> list[Scene]:
        duration = max(scene_seconds, self.min_scene_seconds)
        scenes: list[Scene] = []
        for plan in scene_plans:
            scenes.append(
                Scene(
                    index=plan.index,
                    narration=plan.narration,
                    visual_prompt=plan.visual_description,
                    estimated_duration=max(float(plan.estimated_duration), float(duration)),
                )
            )
        return scenes
