from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from script_generator import ScriptGenerator


def test_valid_json_with_all_fields_parses_cleanly() -> None:
    generator = ScriptGenerator()
    output = (
        '{"scenes": ['
        '{"narration": "Scene one", "image_description": "A mountain", "estimated_duration": 8},'
        '{"narration": "Scene two", "image_description": "A river", "estimated_duration": 8}'
        ']}'
    )

    scenes = generator._parse_ollama_output(output, expected_scene_count=2, scene_seconds=8)

    assert len(scenes) == 2
    assert scenes[0].narration == "Scene one"
    assert scenes[0].visual_description == "A mountain"
    assert scenes[0].estimated_duration == 8


def test_missing_image_description_is_normalized() -> None:
    generator = ScriptGenerator()
    output = '{"scenes": [{"narration": "Desert walk", "estimated_duration": 7}]}'

    scenes = generator._parse_ollama_output(output, expected_scene_count=1, scene_seconds=8)

    assert len(scenes) == 1
    assert scenes[0].visual_description.startswith("Cinematic documentary image illustrating:")


def test_markdown_code_fences_are_stripped_before_parse() -> None:
    generator = ScriptGenerator()
    output = """```json
    {"scenes": [{"narration": "One", "image_description": "Visual", "estimated_duration": 8}]}
    ```"""

    scenes = generator._parse_ollama_output(output, expected_scene_count=1, scene_seconds=8)

    assert len(scenes) == 1
    assert scenes[0].narration == "One"


def test_invalid_json_retries_then_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    generator = ScriptGenerator()
    calls = {"count": 0}

    def fake_check_output(*args, **kwargs):  # noqa: ANN002, ANN003
        calls["count"] += 1
        return "not-json"

    monkeypatch.setattr(subprocess, "check_output", fake_check_output)

    scenes = generator.generate_scene_script("history", total_minutes=1, scene_seconds=10)

    assert calls["count"] == 2
    assert len(scenes) == 6
    assert scenes[0].narration.startswith("Scene 1.")


def test_scene_count_mismatch_is_handled_gracefully() -> None:
    generator = ScriptGenerator()
    output = (
        '{"scenes": ['
        + ",".join(
            f'{{"narration": "Scene {i}", "image_description": "Visual {i}", "estimated_duration": 8}}'
            for i in range(1, 11)
        )
        + "]}"
    )

    scenes = generator._parse_ollama_output(output, expected_scene_count=5, scene_seconds=8)

    assert len(scenes) == 5
    assert scenes[-1].narration == "Scene 5"


def test_missing_estimated_duration_defaults_to_scene_seconds() -> None:
    generator = ScriptGenerator()
    output = '{"scenes": [{"narration": "One", "image_description": "Visual"}]}'

    scenes = generator._parse_ollama_output(output, expected_scene_count=1, scene_seconds=9)

    assert len(scenes) == 1
    assert scenes[0].estimated_duration == 9
