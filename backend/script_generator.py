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
    estimated_duration: float


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
            "narration, image_description, and estimated_duration. Ensure narration is concise and timed for one scene. "
            f"Generate exactly {scene_count} scenes for this request: {prompt}"
        )

        cmd = [
            "ollama",
            "run",
            self.model,
            instruction,
        ]

        for _ in range(2):
            try:
                output = subprocess.check_output(cmd, text=True)
            except subprocess.CalledProcessError:
                continue

            parsed = self._parse_ollama_output(
                output,
                expected_scene_count=scene_count,
                scene_seconds=scene_seconds,
            )
            if parsed:
                return parsed

        return self._fallback_scene_script(prompt=prompt, scene_count=scene_count, scene_seconds=scene_seconds)

    def _strip_code_fences(self, output: str) -> str:
        cleaned = output.strip()
        if not cleaned.startswith("```"):
            return cleaned

        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    def _parse_ollama_output(self, output: str, expected_scene_count: int, scene_seconds: int) -> list[ScenePlan]:
        cleaned = self._strip_code_fences(output)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return []

        payload = cleaned[start : end + 1]
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []

        scenes = data.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            return []

        normalized = self._normalize_scenes(
            scenes=scenes,
            expected_scene_count=expected_scene_count,
            scene_seconds=scene_seconds,
        )

        parsed: list[ScenePlan] = []
        for idx, item in enumerate(normalized, start=1):
            parsed.append(
                ScenePlan(
                    index=idx,
                    narration=item["narration"],
                    visual_description=item["image_description"],
                    estimated_duration=item["estimated_duration"],
                )
            )
        return parsed

    def _normalize_scenes(self, scenes: list[dict], expected_scene_count: int, scene_seconds: int) -> list[dict[str, str | float]]:
        parsed: list[dict[str, str | float]] = []
        for item in scenes:
            if not isinstance(item, dict):
                continue
            narration = str(item.get("narration", "")).strip()
            visual = str(item.get("image_description") or item.get("visual_description") or "").strip()
            if narration and not visual:
                visual = f"Cinematic documentary image illustrating: {narration}"

            duration_value = item.get("estimated_duration")
            try:
                duration = float(duration_value)
            except (TypeError, ValueError):
                duration = float(scene_seconds)

            if narration and visual:
                parsed.append(
                    {
                        "narration": narration,
                        "image_description": visual,
                        "estimated_duration": max(duration, 1.0),
                    }
                )

        if len(parsed) < expected_scene_count:
            for i in range(len(parsed) + 1, expected_scene_count + 1):
                parsed.append(
                    {
                        "narration": f"Scene {i}. Continuation of the story.",
                        "image_description": f"Cinematic documentary illustration for scene {i}.",
                        "estimated_duration": float(scene_seconds),
                    }
                )
        elif len(parsed) > expected_scene_count:
            parsed = parsed[:expected_scene_count]

        return parsed

    def _fallback_scene_script(self, prompt: str, scene_count: int, scene_seconds: int) -> list[ScenePlan]:
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
                    estimated_duration=float(scene_seconds),
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
                    "estimated_duration": scene.estimated_duration,
                }
                for scene in scenes
            ],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
