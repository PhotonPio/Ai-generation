from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScenePlan:
    index: int
    narration: str
    visual_description: str


class ScriptGenerator:
    def __init__(self, model: str = "llama3", ollama_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.ollama_url = ollama_url

    def _target_scene_count(self, total_minutes: int, scene_seconds: int) -> int:
        total_seconds = max(total_minutes, 1) * 60
        return max(total_seconds // max(scene_seconds, 1), 1)

    def generate_scene_script(self, prompt: str, total_minutes: int, scene_seconds: int) -> list[ScenePlan]:
        scene_count = self._target_scene_count(total_minutes, scene_seconds)
        instruction = (
            "You are a documentary and storytelling script engine. "
            "Return strict JSON with key 'scenes' containing an array of objects with fields: "
            "narration and visual_description. Ensure narration is concise and timed for one scene. "
            f"Generate exactly {scene_count} scenes for this request: {prompt}"
        )

        cmd = [
            "ollama",
            "run",
            self.model,
            instruction,
        ]

        try:
            output = subprocess.check_output(cmd, text=True)
            parsed = self._parse_ollama_output(output)
            if parsed:
                return parsed
        except (subprocess.CalledProcessError, OSError):
            pass

        return self._fallback_scene_script(prompt=prompt, scene_count=scene_count)

    def _parse_ollama_output(self, output: str) -> list[ScenePlan]:
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []

        payload = output[start : end + 1]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []

        scenes = data.get("scenes", [])
        parsed: list[ScenePlan] = []
        for idx, item in enumerate(scenes, start=1):
            narration = str(item.get("narration", "")).strip()
            visual = str(item.get("visual_description", "")).strip()
            if narration and visual:
                parsed.append(ScenePlan(index=idx, narration=narration, visual_description=visual))
        return parsed

    def _fallback_scene_script(self, prompt: str, scene_count: int) -> list[ScenePlan]:
        base = f"Narrated explainer about: {prompt}."
        scenes: list[ScenePlan] = []
        for i in range(1, scene_count + 1):
            scenes.append(
                ScenePlan(
                    index=i,
                    narration=(
                        f"Scene {i}. {base} This section advances the story with historical context, "
                        "key events, analysis, and transition to the next part."
                    ),
                    visual_description=(
                        f"Cinematic documentary illustration for scene {i}: {prompt}, dramatic lighting, "
                        "high detail, 16:9 composition."
                    ),
                )
            )
        return scenes

    def save_script_manifest(self, scenes: list[ScenePlan], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scene_count": len(scenes),
            "scenes": [
                {
                    "index": scene.index,
                    "narration": scene.narration,
                    "visual_description": scene.visual_description,
                }
                for scene in scenes
            ],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
