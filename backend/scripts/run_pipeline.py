from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import _update_job, jobs, run_pipeline  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI video generation pipeline from CLI")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--minutes", type=int, default=3)
    parser.add_argument("--scene-seconds", type=int, default=8)
    args = parser.parse_args()

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "message": "Queued",
    }
    _update_job(job_id, message="Starting CLI pipeline")
    run_pipeline(job_id=job_id, prompt=args.prompt, minutes=args.minutes, scene_seconds=args.scene_seconds)
    print(f"Completed job: {job_id}")
    print(f"Download path: output/video/{job_id}_final.mp4")


if __name__ == "__main__":
    main()
