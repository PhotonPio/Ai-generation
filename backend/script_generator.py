from __future__ import annotations

"""Script generation utilities backed by local Ollama models."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from langdetect import detect

try:
    from .config import get_settings
except ImportError:  # pragma: no cover
    from config import get_settings


STYLE_PROMPTS: dict[str, str] = {
    "educational": "clear, factual, and explanatory with simple transitions",
    "storytelling": "narrative, emotionally engaging, and scene-driven",
    "documentary": "neutral, evidence-based, and cinematic in tone",
    "fun": "playful, energetic, and easy to follow",
}


@dataclass
class ScenePlan:
    """Describes one script scene before rendering.

    Attributes:
        index: 1-based scene index.
        narration: Narration text for the scene.
        visual_description: Prompt used for visual generation.
    """

    index: int
    narration: str
    visual_description: str


@dataclass
class ScriptPackage:
    """Script generation result package.

    Attributes:
        scenes: Parsed list of generated scenes.
        language: Detected ISO language code.
        style: Style selected for this script.
        model: Ollama model used for generation.
        outline: High-level outline text from stage 1.
    """

    scenes: list[ScenePlan]
    language: str
    style: str
    model: str
    outline: str


class ScriptGenerator:
    """Generate script scenes with a two-stage local LLM workflow."""

    def __init__(self, model: str | None = None, ollama_url: str | None = None, style: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.ollama_model
        self.ollama_url = (ollama_url or settings.ollama_url).rstrip("/")
        self.style = style or settings.default_style

    def _target_scene_count(self, total_minutes: int, scene_seconds: int, max_scenes: int = 300) -> int:
        """Calculate bounded scene count for the requested runtime."""

        total_seconds = max(total_minutes, 1) * 60
        estimate = max(total_seconds // max(scene_seconds, 1), 1)
        return min(estimate, max_scenes)

    def _ask_ollama(self, prompt: str, timeout: int = 180) -> str:
        """Query local Ollama and return the plain response text."""

        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        return str(response.json().get("response", "")).strip()

    def _normalize_style(self, style: str) -> str:
        """Normalize style to supported values with a safe fallback."""

        normalized = (style or "educational").strip().lower()
        return normalized if normalized in STYLE_PROMPTS else "educational"

    def _detect_language(self, prompt: str) -> str:
        """Detect language from input prompt; fallback to English on failure."""

        try:
            lang = detect(prompt)
            return lang if lang else "en"
        except Exception:
            return "en"

    def generate_scene_script(
        self,
        prompt: str,
        total_minutes: int,
        scene_seconds: int,
        *,
        style: str | None = None,
        max_scenes: int = 300,
    ) -> ScriptPackage:
        """Generate an outline first, then a detailed structured script.

        Args:
            prompt: User prompt describing the target video topic.
            total_minutes: Requested video length in minutes.
            scene_seconds: Requested scene duration baseline.
            style: Script style override.
            max_scenes: Hard cap for scene count.

        Returns:
            ScriptPackage containing scenes plus metadata.
        """

        style_name = self._normalize_style(style or self.style)
        language = self._detect_language(prompt)
        scene_count = self._target_scene_count(total_minutes, scene_seconds, max_scenes=max_scenes)

        style_directive = STYLE_PROMPTS[style_name]
        outline_prompt = (
            "You are a video scripting planner. "
            f"Generate a concise numbered outline with {scene_count} bullet points. "
            f"Write in language code '{language}'. "
            f"Tone: {style_directive}. "
            f"Topic: {prompt}"
        )

        try:
            outline = self._ask_ollama(outline_prompt, timeout=180)
        except Exception:
            outline = self._fallback_outline(prompt, scene_count)

        scene_prompt = (
            "You are a documentary and storytelling script engine. "
            "Return ONLY strict JSON object with key 'scenes' where each item has: "
            "'narration' and 'visual_description'. "
            f"Generate exactly {scene_count} scenes in language '{language}'. "
            f"Style must be {style_name} ({style_directive}). "
            "Use this outline as structure:\n"
            f"{outline}\n"
            "No markdown, no commentary."
        )

        try:
            output = self._ask_ollama(scene_prompt, timeout=240)
            parsed = self._parse_output(output)
        except Exception:
            parsed = []

        if not parsed:
            parsed = self._fallback_scene_script(prompt=prompt, scene_count=scene_count, style=style_name)

        return ScriptPackage(
            scenes=parsed,
            language=language,
            style=style_name,
            model=self.model,
            outline=outline,
        )

    def _parse_output(self, output: str) -> list[ScenePlan]:
        """Extract strict JSON payload and parse scene items."""

        match = re.search(r"\{.*\}", output, flags=re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []

        scenes_raw = data.get("scenes", [])
        parsed: list[ScenePlan] = []
        for idx, item in enumerate(scenes_raw, start=1):
            narration = str(item.get("narration", "")).strip()
            visual = str(item.get("visual_description", "")).strip()
            if narration and visual:
                parsed.append(ScenePlan(index=idx, narration=narration, visual_description=visual))
        return parsed

    def _fallback_outline(self, prompt: str, scene_count: int) -> str:
        """Return deterministic outline when Ollama is unavailable."""

        return "\n".join(
            [f"{i}. {prompt} - key concept {i}" for i in range(1, scene_count + 1)]
        )

    def _fallback_scene_script(self, prompt: str, scene_count: int, style: str) -> list[ScenePlan]:
        """Return deterministic scene script fallback for offline mode."""

        style_hint = STYLE_PROMPTS.get(style, STYLE_PROMPTS["educational"])
        base = f"Narrated {style} video about: {prompt}."
        scenes: list[ScenePlan] = []
        for i in range(1, scene_count + 1):
            scenes.append(
                ScenePlan(
                    index=i,
                    narration=(
                        f"Scene {i}. {base} This segment follows a {style_hint} approach and moves the story forward."
                    ),
                    visual_description=(
                        f"Cinematic 16:9 frame for scene {i}: {prompt}, {style} tone, highly detailed composition."
                    ),
                )
            )
        return scenes

    def save_script_manifest(self, package: ScriptPackage, destination: Path) -> None:
        """Persist generated script package to disk."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scene_count": len(package.scenes),
            "language": package.language,
            "style": package.style,
            "model": package.model,
            "outline": package.outline,
            "scenes": [
                {
                    "index": s.index,
                    "narration": s.narration,
                    "visual_description": s.visual_description,
                }
                for s in package.scenes
            ],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
