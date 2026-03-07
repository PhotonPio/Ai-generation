from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI video generation pipeline from CLI")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--minutes", type=int, default=3)
    parser.add_argument("--scene-seconds", type=int, default=8)
    args = parser.parse_args()

    job_id = uuid.uuid4().hex[:12]
    run_pipeline(job_id=job_id, prompt=args.prompt, minutes=args.minutes, scene_seconds=args.scene_seconds)
    print(f"Completed job: {job_id}")
    print(f"Video path: backend/output/projects/{job_id}/video.mp4")


if __name__ == "__main__":
    main()
