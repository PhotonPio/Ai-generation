from __future__ import annotations

"""Script generation utilities backed by local Ollama models."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import importlib.util

_HAS_LANGDETECT = importlib.util.find_spec("langdetect") is not None
if _HAS_LANGDETECT:
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
    search_keywords: list[str] | None = None


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
    title: str
    hook: str
    outro: str


def validate_script_structure(script: dict[str, object]) -> tuple[bool, str]:
    """Validate generated script payload before pipeline stages continue."""

    scenes = script.get("scenes")
    if not isinstance(script.get("title"), str) or not str(script.get("title", "")).strip():
        return False, "Missing title"
    if not isinstance(script.get("hook"), str) or not str(script.get("hook", "")).strip():
        return False, "Missing hook"
    if not isinstance(script.get("outro"), str) or not str(script.get("outro", "")).strip():
        return False, "Missing outro"
    if not isinstance(scenes, list):
        return False, "Scenes must be a list"
    if len(scenes) < 5 or len(scenes) > 10:
        return False, "Scenes must contain 5-10 items"

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            return False, f"Scene {index} is invalid"
        narration = str(scene.get("narration", "")).strip()
        word_count = len(narration.split())
        if word_count < 30 or word_count > 80:
            return False, f"Scene {index} narration must have 30-80 words"
        visual_description = str(scene.get("visual_description", "")).strip()
        if not visual_description:
            return False, f"Scene {index} missing visual_description"
        scene_number = int(scene.get("scene_number", 0) or 0)
        if scene_number != index:
            return False, f"Scene number mismatch for scene {index}"
        duration = int(scene.get("duration_seconds", 0) or 0)
        if duration <= 0:
            return False, f"Scene {index} missing duration_seconds"
        keywords = scene.get("search_keywords")
        if not isinstance(keywords, list) or len([k for k in keywords if str(k).strip()]) == 0:
            return False, f"Scene {index} missing search keywords"

    return True, "ok"


class ScriptGenerator:
    """Generate script scenes with a two-stage local LLM workflow."""

    def __init__(self, model: str | None = None, ollama_url: str | None = None, style: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.ollama_model
        self.ollama_url = (ollama_url or settings.ollama_url).rstrip("/")
        self.style = style or settings.default_style

    def _target_scene_count(self, total_minutes: int, scene_seconds: int, max_scenes: int = 10) -> int:
        """Calculate bounded scene count for the requested runtime."""

        total_seconds = max(total_minutes, 1) * 60
        estimate = max(total_seconds // max(scene_seconds, 1), 1)
        return max(5, min(estimate, min(max_scenes, 10)))

    def _ask_ollama(self, prompt: str, timeout: int = 180) -> str:
        """Query local Ollama and return the plain response text."""

        payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode("utf-8")
        request = Request(
            f"{self.ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("Failed to query Ollama") from exc
        return str(body.get("response", "")).strip()

    def _normalize_style(self, style: str) -> str:
        """Normalize style to supported values with a safe fallback."""

        normalized = (style or "educational").strip().lower()
        return normalized if normalized in STYLE_PROMPTS else "educational"

    def _detect_language(self, prompt: str) -> str:
        """Detect language from input prompt; fallback to English on failure."""

        if not _HAS_LANGDETECT:
            return "en"
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
            "Return ONLY strict JSON object in this format: "
            "{title, hook, scenes:[{scene_number,narration,visual_description,search_keywords,duration_seconds}], outro}. "
            f"Generate exactly {scene_count} scenes in language '{language}'. "
            f"Style must be {style_name} ({style_directive}). "
            "Every narration MUST be 30-80 words. Every scene MUST have 3-5 search_keywords tuned for stock media search. "
            "Use this outline as structure:\n"
            f"{outline}\n"
            "No markdown, no commentary."
        )

        parsed_script: dict[str, object] = {}
        for _ in range(3):
            try:
                output = self._ask_ollama(scene_prompt, timeout=240)
                parsed_script = self._parse_output(output, scene_seconds)
            except Exception:
                parsed_script = {}
            valid, _message = validate_script_structure(parsed_script)
            if valid:
                break

        if not parsed_script or not validate_script_structure(parsed_script)[0]:
            parsed_script = self._fallback_scene_script(
                prompt=prompt,
                scene_count=scene_count,
                style=style_name,
                scene_seconds=scene_seconds,
            )

        valid, message = validate_script_structure(parsed_script)
        if not valid:
            raise RuntimeError(f"Script validation failed: {message}")

        parsed = [
            ScenePlan(
                index=int(item["scene_number"]),
                narration=str(item["narration"]),
                visual_description=str(item["visual_description"]),
                search_keywords=[str(k) for k in item.get("search_keywords", [])],
            )
            for item in parsed_script["scenes"]
        ]

        return ScriptPackage(
            scenes=parsed,
            language=language,
            style=style_name,
            model=self.model,
            outline=outline,
            title=str(parsed_script.get("title", "")),
            hook=str(parsed_script.get("hook", "")),
            outro=str(parsed_script.get("outro", "")),
        )

    def _parse_output(self, output: str, scene_seconds: int) -> dict[str, object]:
        """Extract strict JSON payload and parse scene items."""

        match = re.search(r"\{.*\}", output, flags=re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

        payload: dict[str, object] = {
            "title": str(data.get("title", "")).strip(),
            "hook": str(data.get("hook", "")).strip(),
            "outro": str(data.get("outro", "")).strip(),
            "scenes": [],
        }
        for idx, item in enumerate(data.get("scenes", []), start=1):
            payload["scenes"].append(  # type: ignore[union-attr]
                {
                    "scene_number": int(item.get("scene_number", idx) or idx),
                    "narration": str(item.get("narration", "")).strip(),
                    "visual_description": str(item.get("visual_description", "")).strip(),
                    "search_keywords": item.get("search_keywords", []),
                    "duration_seconds": int(item.get("duration_seconds", scene_seconds) or scene_seconds),
                }
            )
        return payload

    def _fallback_outline(self, prompt: str, scene_count: int) -> str:
        """Return deterministic outline when Ollama is unavailable."""

        return "\n".join(
            [f"{i}. {prompt} - key concept {i}" for i in range(1, scene_count + 1)]
        )

    def _fallback_scene_script(self, prompt: str, scene_count: int, style: str, scene_seconds: int) -> dict[str, object]:
        """Return deterministic scene script fallback for offline mode."""

        style_hint = STYLE_PROMPTS.get(style, STYLE_PROMPTS["educational"])
        scenes: list[dict[str, object]] = []
        for i in range(1, scene_count + 1):
            narration = (
                f"Scene {i} introduces a core angle of {prompt} using a {style} tone with clear context and examples. "
                "It explains why this moment matters, connects with the previous idea, and sets up the next visual beat "
                "to keep pacing coherent and engaging for viewers."
            )
            scenes.append(
                {
                    "scene_number": i,
                    "narration": narration,
                    "visual_description": f"Cinematic 16:9 frame for scene {i}: {prompt}, {style_hint}, realistic detail.",
                    "search_keywords": [f"{prompt} scene {i}", f"{prompt} cinematic", "technology background"],
                    "duration_seconds": scene_seconds,
                }
            )
        return {
            "title": f"{prompt.title()} Explained",
            "hook": f"Let us break down {prompt} in a fast, visual journey.",
            "scenes": scenes,
            "outro": f"That concludes this guide to {prompt} with practical takeaways.",
        }

    def save_script_manifest(self, package: ScriptPackage, destination: Path) -> None:
        """Persist generated script package to disk."""

        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scene_count": len(package.scenes),
            "language": package.language,
            "style": package.style,
            "model": package.model,
            "outline": package.outline,
            "title": package.title,
            "hook": package.hook,
            "outro": package.outro,
            "scenes": [
                {
                    "index": s.index,
                    "scene_number": s.index,
                    "narration": s.narration,
                    "visual_description": s.visual_description,
                    "search_keywords": s.search_keywords or [],
                }
                for s in package.scenes
            ],
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
