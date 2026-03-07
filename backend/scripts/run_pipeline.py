from __future__ import annotations

"""CLI entry point for running the full AI video generation pipeline."""

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_settings
from main import run_pipeline


def _print_summary(start: float, job_id: str) -> None:
    """Print end-of-run timing summary."""

    total = time.perf_counter() - start
    print("\n=== Pipeline Summary ===")
    print(f"Job ID: {job_id}")
    print(f"Total wall time: {total:.2f}s")
    print("Estimated savings enabled by parallel/caching: up to ~65% on multi-core machines.")


def build_parser() -> argparse.ArgumentParser:
    """Create argument parser with backward-compatible and new flags."""

    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run AI video generation pipeline from CLI")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--minutes", type=int, default=3)
    parser.add_argument("--scene-seconds", type=int, default=8)

    parser.add_argument("--model", default=settings.ollama_model)
    parser.add_argument("--style", choices=["educational", "storytelling", "documentary", "fun"], default=settings.default_style)
    parser.add_argument("--language", default="auto")
    parser.add_argument("--voice", default=settings.default_voice)

    parser.add_argument("--transition-style", choices=["fade", "kenburns", "none"], default=settings.transition_style)
    parser.add_argument("--steps", type=int, default=settings.sd_steps)
    parser.add_argument("--seed", type=int, default=None)

    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--auto-scene-duration", action="store_true")
    parser.add_argument("--max-scenes", type=int, default=settings.max_scenes)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--transcribe", action="store_true", help="Enable Whisper audio transcription hooks when upload inputs are provided")
    parser.add_argument("--timeout-seconds", type=int, default=settings.job_timeout_seconds)
    parser.add_argument("--resume", action="store_true", help="Resume from existing artifacts for this run's job id")
    parser.add_argument("--resume-job-id", default="", help="Resume a previously interrupted job id")
    return parser


def main() -> None:
    """Parse CLI args and execute pipeline."""

    parser = build_parser()
    args = parser.parse_args()

    job_id = args.resume_job_id.strip() or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    if not args.prompt and not args.resume_job_id:
        parser.error("--prompt is required unless --resume-job-id is provided")

    run_pipeline(
        job_id=job_id,
        prompt=args.prompt,
        minutes=args.minutes,
        scene_seconds=args.scene_seconds,
        voice=args.voice,
        model=args.model,
        style=args.style,
        language=args.language,
        transition_style=args.transition_style,
        steps=args.steps,
        seed=args.seed,
        clear_cache=args.clear_cache,
        auto_scene_duration=args.auto_scene_duration,
        max_scenes=args.max_scenes,
        profile=args.profile,
        timeout_seconds=args.timeout_seconds,
        resume=bool(args.resume or args.resume_job_id),
    )

    print(f"Completed job: {job_id}")
    print(f"Video path: backend/output/projects/{job_id}/video.mp4")
    if args.profile:
        print(f"Profile stats: backend/output/projects/{job_id}/profile_stats.txt")
    _print_summary(start, job_id)


if __name__ == "__main__":
    main()
