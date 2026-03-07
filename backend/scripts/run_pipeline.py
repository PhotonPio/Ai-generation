from __future__ import annotations

import argparse
import uuid

from main import run_pipeline, _update_job, jobs


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
    print(f"Download path: backend/output/video/{job_id}_final.mp4")


if __name__ == "__main__":
    main()
