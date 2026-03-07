from __future__ import annotations

from pathlib import Path

import pytest

from backend.scene_builder import SceneBuilder
from backend.script_generator import ScenePlan, ScriptGenerator
from backend.voice_generator import VoiceGenerator


def test_script_generator_target_scene_count_respects_cap() -> None:
    gen = ScriptGenerator(model="llama3:8b")
    assert gen._target_scene_count(total_minutes=60, scene_seconds=5, max_scenes=300) == 300


def test_script_generator_fallback_language_and_style(monkeypatch: pytest.MonkeyPatch) -> None:
    gen = ScriptGenerator(model="llama3:8b", style="fun")
    monkeypatch.setattr(gen, "_ask_ollama", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    package = gen.generate_scene_script(
        prompt="Create a short explainer about solar eclipses",
        total_minutes=1,
        scene_seconds=8,
        style="fun",
        max_scenes=10,
    )
    assert package.style == "fun"
    assert package.language
    assert len(package.scenes) > 0


def test_scene_builder_auto_duration_bounds() -> None:
    plans = [
        ScenePlan(index=1, narration="Short sentence.", visual_description="A"),
        ScenePlan(index=2, narration="This is a much longer sentence designed to increase complexity in timing estimation.", visual_description="B"),
    ]
    scenes = SceneBuilder().build(plans, scene_seconds=8, auto_scene_duration=True, style="documentary")
    assert len(scenes) == 2
    for scene in scenes:
        assert 5 <= scene.estimated_duration <= 15


def test_voice_generator_resolve_model_from_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_VOICE", "en_US-lessac-medium")
    vg = VoiceGenerator(job_id="testjob", voice="", language="de")
    assert vg._resolve_voice_model().startswith("de_")


def test_image_cache_key_is_deterministic() -> None:
    pytest.importorskip("backend.image_generator")
    from backend.image_generator import ImageGenerator

    gen = ImageGenerator(job_id="cachetest")
    key1 = gen._cache_key("black hole", 1280, 720, seed=42, steps=20)
    key2 = gen._cache_key("black hole", 1280, 720, seed=42, steps=20)
    assert key1 == key2


def test_video_renderer_srt_time_format(tmp_path: Path) -> None:
    pytest.importorskip("moviepy")
    from backend.video_renderer import VideoRenderer

    vr = VideoRenderer(tmp_path)
    assert vr._fmt_srt_time(65.432) == "00:01:05,432"
