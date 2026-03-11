from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

from image_generator import ImageGenerator
from scene_builder import SceneBuilder
from script_generator import ScriptGenerator
from video_renderer import VideoRenderer
from voice_generator import VoiceGenerator

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
OUTPUT_DIR = REPO_ROOT / "output"
JOBS_DIR = OUTPUT_DIR / "jobs"
VIDEO_OUTPUT = OUTPUT_DIR / "video"

app = Flask(__name__)
CORS(app)

jobs: dict[str, dict] = {}
lock = threading.Lock()


def _update_job(job_id: str, **kwargs: object) -> None:
    with lock:
        jobs[job_id].update(kwargs)
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")


def run_pipeline(job_id: str, prompt: str, minutes: int, scene_seconds: int) -> None:
    try:
        _update_job(job_id, status="running", progress=5, message="Generating script")

        script_gen = ScriptGenerator(model="llama3")
        scene_plans = script_gen.generate_scene_script(prompt, minutes, scene_seconds)
        script_gen.save_script_manifest(scene_plans, OUTPUT_DIR / f"script_{job_id}.json")

        _update_job(job_id, progress=20, message="Building scenes")
        scene_builder = SceneBuilder()
        scenes = scene_builder.build(scene_plans, scene_seconds)

        image_gen = ImageGenerator()
        voice_gen = VoiceGenerator(model_path=REPO_ROOT / "models" / "en_US-lessac-medium.onnx")
        renderer = VideoRenderer(OUTPUT_DIR)

        images: list[Path] = []
        audios: list[Path] = []

        total = len(scenes)
        for i, scene in enumerate(scenes, start=1):
            image_path = OUTPUT_DIR / "images" / f"scene{scene.index:03d}.png"
            audio_path = OUTPUT_DIR / "audio" / f"scene{scene.index:03d}.wav"

            _update_job(job_id, message=f"Generating image {i}/{total}", progress=min(20 + int((i / total) * 35), 55))
            image_gen.generate_scene_image(scene, image_path)
            images.append(image_path)

            _update_job(job_id, message=f"Generating narration {i}/{total}", progress=min(55 + int((i / total) * 20), 75))
            voice_gen.generate_scene_audio(scene, audio_path)
            audios.append(audio_path)

        _update_job(job_id, message="Rendering video segments", progress=80)
        segments = renderer.render_segments(scenes, images, audios)
        raw_video = VIDEO_OUTPUT / f"{job_id}_raw.mp4"
        renderer.concatenate(segments, raw_video)

        _update_job(job_id, message="Generating subtitles and music", progress=90)
        subtitle_file = OUTPUT_DIR / "subtitles" / f"{job_id}.srt"
        renderer.create_subtitles(scenes, subtitle_file)

        subtitled_video = VIDEO_OUTPUT / f"{job_id}_subtitled.mp4"
        renderer.burn_subtitles(raw_video, subtitle_file, subtitled_video)

        music_file = OUTPUT_DIR / "music" / f"{job_id}.wav"
        total_seconds = int(sum(scene.estimated_duration for scene in scenes))
        renderer.generate_background_music(total_seconds=total_seconds, output_path=music_file)

        final_video = VIDEO_OUTPUT / f"{job_id}_final.mp4"
        renderer.mix_music(subtitled_video, music_file, final_video)

        thumbnail = OUTPUT_DIR / "thumbnails" / f"{job_id}.jpg"
        renderer.create_thumbnail(final_video, thumbnail)

        renderer.write_manifest(
            {
                "job_id": job_id,
                "prompt": prompt,
                "minutes": minutes,
                "scene_seconds": scene_seconds,
                "scene_count": len(scenes),
                "video": str(final_video.relative_to(REPO_ROOT)),
                "thumbnail": str(thumbnail.relative_to(REPO_ROOT)),
                "subtitle": str(subtitle_file.relative_to(REPO_ROOT)),
                "created_at": int(time.time()),
            },
            JOBS_DIR / f"{job_id}_manifest.json",
        )

        _update_job(
            job_id,
            status="completed",
            progress=100,
            message="Completed",
            download_url=f"/download/{job_id}",
            manifest_url=f"/manifest/{job_id}",
        )
    except Exception as exc:  # noqa: BLE001
        _update_job(job_id, status="failed", progress=100, message=f"Failed: {exc}")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(force=True)
    prompt = str(payload.get("prompt", "")).strip()
    minutes = int(payload.get("minutes", 5))
    scene_seconds = int(payload.get("scene_seconds", 8))

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_OUTPUT.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex[:12]
    with lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "download_url": None,
            "manifest_url": None,
        }

    thread = threading.Thread(
        target=run_pipeline,
        kwargs={"job_id": job_id, "prompt": prompt, "minutes": minutes, "scene_seconds": scene_seconds},
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})




@app.route("/schema-check", methods=["POST"])
def schema_check():
    payload = request.get_json(force=True)
    prompt = str(payload.get("prompt", "")).strip()
    minutes = int(payload.get("minutes", 5))
    scene_seconds = int(payload.get("scene_seconds", 8))

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    script_gen = ScriptGenerator(model="llama3")
    scenes = script_gen.generate_scene_script(prompt, minutes, scene_seconds)
    return jsonify(
        {
            "prompt": prompt,
            "minutes": minutes,
            "scene_seconds": scene_seconds,
            "scene_count": len(scenes),
            "scenes": [
                {
                    "index": scene.index,
                    "narration": scene.narration,
                    "image_description": scene.visual_description,
                    "estimated_duration": scene.estimated_duration,
                }
                for scene in scenes
            ],
        }
    )

@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    with lock:
        job = jobs.get(job_id)
    if not job:
        job_file = JOBS_DIR / f"{job_id}.json"
        if job_file.exists():
            return jsonify(json.loads(job_file.read_text(encoding="utf-8")))
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id: str):
    target = VIDEO_OUTPUT / f"{job_id}_final.mp4"
    if not target.exists():
        return jsonify({"error": "Video not ready"}), 404
    return send_file(target, mimetype="video/mp4", as_attachment=True)


@app.route("/manifest/<job_id>", methods=["GET"])
def manifest(job_id: str):
    target = JOBS_DIR / f"{job_id}_manifest.json"
    if not target.exists():
        return jsonify({"error": "Manifest not ready"}), 404
    return send_file(target, mimetype="application/json")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
