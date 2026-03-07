from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class ScenePlan:
    index: int
    narration: str
    visual_description: str


class ScriptGenerator:
    def __init__(self, model: str = "llama3", ollama_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")

    def _target_scene_count(self, total_minutes: int, scene_seconds: int) -> int:
        total_seconds = max(total_minutes, 1) * 60
        return max(total_seconds // max(scene_seconds, 1), 1)

    def generate_scene_script(self, prompt: str, total_minutes: int, scene_seconds: int) -> list[ScenePlan]:
        scene_count = self._target_scene_count(total_minutes, scene_seconds)
        instruction = (
            "You are a documentary and storytelling script engine. "
            "Return ONLY strict JSON with key 'scenes' containing an array of objects with fields: "
            "'narration' and 'visual_description'. No extra text, no markdown. "
            "Ensure narration is concise and timed for one scene. "
            f"Generate exactly {scene_count} scenes for this request: {prompt}"
        )

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={"model": self.model, "prompt": instruction, "stream": False},
                timeout=180,
            )
            response.raise_for_status()
            output = response.json().get("response", "")
            parsed = self._parse_output(output)
            if parsed:
                return parsed
        except Exception:
            pass

        return self._fallback_scene_script(prompt=prompt, scene_count=scene_count)

    def _parse_output(self, output: str) -> list[ScenePlan]:
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(output[start: end + 1])
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
        return [
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
            for i in range(1, scene_count + 1)
        ]

    def save_script_manifest(self, scenes: list[ScenePlan], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scene_count": len(scenes),
            "scenes": [
                {
                    "index": s.index,
                    "narration": s.narration,
                    "visual_description": s.visual_description,
                }
                for s in scenes
            ],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
