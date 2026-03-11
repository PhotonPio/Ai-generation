from __future__ import annotations

"""Centralized configuration for the AI video pipeline.

All runtime options can be overridden via environment variables.
"""

import importlib.util
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
_HAS_PYDANTIC_SETTINGS = importlib.util.find_spec("pydantic_settings") is not None

if _HAS_PYDANTIC and _HAS_PYDANTIC_SETTINGS:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

        api_user: str = Field(default="admin", alias="API_USER")
        api_pass: str = Field(default="changeme", alias="API_PASS")
        auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
        ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
        ollama_model: str = Field(default="llama3:8b", alias="OLLAMA_MODEL")
        default_style: str = Field(default="educational", alias="DEFAULT_STYLE")
        default_language: str = Field(default="en", alias="DEFAULT_LANGUAGE")
        default_voice: str = Field(default="en_US-lessac-medium", alias="DEFAULT_VOICE")
        output_dir: Path = Field(default=Path("backend/output"), alias="OUTPUT_DIR")
        projects_dir: Path = Field(default=Path("backend/output/projects"), alias="PROJECTS_DIR")
        transition_style: str = Field(default="kenburns", alias="TRANSITION_STYLE")
        scene_media_mode: str = Field(default="auto", alias="SCENE_MEDIA_MODE")
        pexels_video_quality: str = Field(default="hd", alias="PEXELS_VIDEO_QUALITY")
        video_width: int = Field(default=1920, alias="VIDEO_WIDTH")
        video_height: int = Field(default=1080, alias="VIDEO_HEIGHT")
        video_preset: str = Field(default="slow", alias="VIDEO_PRESET")
        video_crf: int = Field(default=18, alias="VIDEO_CRF")
        transition_seconds: float = Field(default=1.0, alias="TRANSITION_SECONDS")
        kenburns_zoom_factor: float = Field(default=1.2, alias="KENBURNS_ZOOM_FACTOR")
        max_workers_cpu: int = Field(default=4, alias="MAX_WORKERS_CPU")
        max_workers_gpu: int = Field(default=8, alias="MAX_WORKERS_GPU")
        sd_steps: int = Field(default=20, alias="SD_STEPS")
        sd_model: str = Field(default="runwayml/stable-diffusion-v1-5", alias="SD_MODEL")
        a1111_url: str = Field(default="http://127.0.0.1:7860/sdapi/v1/txt2img", alias="A1111_URL")
        enable_clip_scoring: bool = Field(default=False, alias="ENABLE_CLIP_SCORING")
        clip_threshold: float = Field(default=0.25, alias="CLIP_THRESHOLD")
        clip_retries: int = Field(default=2, alias="CLIP_RETRIES")
        max_scenes: int = Field(default=300, alias="MAX_SCENES")
        clear_cache_default: bool = Field(default=False, alias="CLEAR_CACHE_DEFAULT")
        job_timeout_seconds: int = Field(default=900, alias="JOB_TIMEOUT_SECONDS")

else:
    def _env_bool(name: str, default: bool) -> bool:
        return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

    @dataclass
    class Settings:
        api_user: str = os.getenv("API_USER", "admin")
        api_pass: str = os.getenv("API_PASS", "changeme")
        auth_enabled: bool = _env_bool("AUTH_ENABLED", True)
        ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
        ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3:8b")
        default_style: str = os.getenv("DEFAULT_STYLE", "educational")
        default_language: str = os.getenv("DEFAULT_LANGUAGE", "en")
        default_voice: str = os.getenv("DEFAULT_VOICE", "en_US-lessac-medium")
        output_dir: Path = Path(os.getenv("OUTPUT_DIR", "backend/output"))
        projects_dir: Path = Path(os.getenv("PROJECTS_DIR", "backend/output/projects"))
        transition_style: str = os.getenv("TRANSITION_STYLE", "kenburns")
        scene_media_mode: str = os.getenv("SCENE_MEDIA_MODE", "auto")
        pexels_video_quality: str = os.getenv("PEXELS_VIDEO_QUALITY", "hd")
        video_width: int = int(os.getenv("VIDEO_WIDTH", "1920"))
        video_height: int = int(os.getenv("VIDEO_HEIGHT", "1080"))
        video_preset: str = os.getenv("VIDEO_PRESET", "slow")
        video_crf: int = int(os.getenv("VIDEO_CRF", "18"))
        transition_seconds: float = float(os.getenv("TRANSITION_SECONDS", "1.0"))
        kenburns_zoom_factor: float = float(os.getenv("KENBURNS_ZOOM_FACTOR", "1.2"))
        max_workers_cpu: int = int(os.getenv("MAX_WORKERS_CPU", "4"))
        max_workers_gpu: int = int(os.getenv("MAX_WORKERS_GPU", "8"))
        sd_steps: int = int(os.getenv("SD_STEPS", "20"))
        sd_model: str = os.getenv("SD_MODEL", "runwayml/stable-diffusion-v1-5")
        a1111_url: str = os.getenv("A1111_URL", "http://127.0.0.1:7860/sdapi/v1/txt2img")
        enable_clip_scoring: bool = _env_bool("ENABLE_CLIP_SCORING", False)
        clip_threshold: float = float(os.getenv("CLIP_THRESHOLD", "0.25"))
        clip_retries: int = int(os.getenv("CLIP_RETRIES", "2"))
        max_scenes: int = int(os.getenv("MAX_SCENES", "300"))
        clear_cache_default: bool = _env_bool("CLEAR_CACHE_DEFAULT", False)
        job_timeout_seconds: int = int(os.getenv("JOB_TIMEOUT_SECONDS", "900"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
