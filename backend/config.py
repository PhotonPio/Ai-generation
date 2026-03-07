from __future__ import annotations

"""Centralized configuration for the AI video pipeline.

All runtime options can be overridden via environment variables.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Attributes:
        api_user: Username for HTTP Basic authentication.
        api_pass: Password for HTTP Basic authentication.
        auth_enabled: Enables/disables API auth guard.
        ollama_url: Base URL for the local Ollama service.
        ollama_model: Default Ollama model used for script generation.
        default_style: Default writing style for generated scripts.
        default_language: UI/CLI fallback language when auto-detect is disabled.
        default_voice: Piper voice code used by default.
        output_dir: Root output directory for generated artifacts.
        projects_dir: Root projects directory for per-job outputs.
        transition_style: Default transition mode for rendered videos.
        transition_seconds: Transition duration for clip transitions.
        kenburns_zoom_factor: Zoom factor for ken-burns style effects.
        max_workers_cpu: Worker count for CPU machines.
        max_workers_gpu: Worker count for GPU machines.
        sd_steps: Default diffusion steps in preview mode.
        sd_model: Diffusion model id for diffusers fallback.
        a1111_url: AUTOMATIC1111 txt2img API endpoint.
        enable_clip_scoring: Enables CLIP-based scoring pass.
        clip_threshold: Minimum CLIP score accepted before retry.
        clip_retries: Number of regeneration retries for low CLIP score.
        max_scenes: Hard cap for scene count before chunking is applied.
        clear_cache_default: Clears cache at the beginning of each run.
        job_timeout_seconds: Hard timeout per phase execution.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
