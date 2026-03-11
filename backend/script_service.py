from __future__ import annotations

from pathlib import Path

from ..script_generator import ScriptGenerator, ScriptPackage, validate_script_structure


class ScriptService:
    def __init__(self, model: str, style: str) -> None:
        self.generator = ScriptGenerator(model=model, style=style)

    def generate(self, prompt: str, minutes: int, scene_seconds: int, max_scenes: int, destination: Path) -> ScriptPackage:
        package = self.generator.generate_scene_script(prompt, minutes, scene_seconds, style=self.generator.style, max_scenes=max_scenes)
        payload = {
            "title": package.title,
            "hook": package.hook,
            "scenes": [
                {
                    "scene_number": s.index,
                    "narration": s.narration,
                    "visual_description": s.visual_description,
                    "search_keywords": s.search_keywords or [],
                    "duration_seconds": scene_seconds,
                }
                for s in package.scenes
            ],
            "outro": package.outro,
        }
        valid, message = validate_script_structure(payload)
        if not valid:
            raise RuntimeError(f"Script validation failed: {message}")
        self.generator.save_script_manifest(package, destination)
        return package
