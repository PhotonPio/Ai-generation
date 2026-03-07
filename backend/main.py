from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

from image_generator import ImageGenerator, UPLOADS_DIR, ALLOWED_EXTENSIONS
from scene_builder import SceneBuilder
from script_generator import ScriptGenerator
from video_renderer import VideoRenderer
from voice_generator import VoiceGenerator, VOICE_PRESETS, DEFAULT_VOICE

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROJECTS_DIR = OUTPUT_DIR / "projects"

app = Flask(__name__)
CORS(app)

jobs: dict[str, dict] = {}
lock = threading.Lock()


def _project_dir(job_id: str) -> Path:
    return PROJECTS_DIR / job_id


def _update_job(job_id: str, **kwargs: object) -> None:
    with lock:
        jobs[job_id].update(kwargs)
        (_project_dir(job_id) / "job.json").write_text(
            json.dumps(jobs[job_id], indent=2), encoding="utf-8"
        )


def run_pipeline(job_id: str, prompt: str, minutes: int, scene_seconds: int, voice: str) -> None:
    project_dir = _project_dir(job_id)

    _update_job(job_id, status="running", progress=5, message="Generating script")

    script_gen = ScriptGenerator(model="llama3")
    scene_plans = script_gen.generate_scene_script(prompt, minutes, scene_seconds)
    script_gen.save_script_manifest(scene_plans, project_dir / "script.json")

    _update_job(job_id, progress=20, message="Building scenes")
    scene_builder = SceneBuilder()
    scenes = scene_builder.build(scene_plans, scene_seconds)

    image_gen = ImageGenerator()
    voice_gen = VoiceGenerator(voice=voice)
    renderer = VideoRenderer(project_dir)

    images: list[Path] = []
    audios: list[Path] = []

    total = len(scenes)
    for i, scene in enumerate(scenes, start=1):
        image_path = project_dir / "images" / f"scene{scene.index:03d}.png"
        audio_path = project_dir / "audio" / f"scene{scene.index:03d}.wav"

        _update_job(job_id, message=f"Fetching image {i}/{total}", progress=min(20 + int((i / total) * 35), 55))
        image_gen.generate_scene_image(scene, image_path)
        images.append(image_path)

        _update_job(job_id, message=f"Generating narration {i}/{total}", progress=min(55 + int((i / total) * 20), 75))
        voice_gen.generate_scene_audio(scene, audio_path)
        audios.append(audio_path)

    _update_job(job_id, message="Rendering video segments", progress=80)
    segments = renderer.render_segments(scenes, images, audios)
    raw_video = project_dir / "video_raw.mp4"
    renderer.concatenate(segments, raw_video)

    _update_job(job_id, message="Generating subtitles and music", progress=90)
    subtitle_file = project_dir / "subtitles.srt"
    renderer.create_subtitles(scenes, subtitle_file)

    subtitled_video = project_dir / "video_sub.mp4"
    renderer.burn_subtitles(raw_video, subtitle_file, subtitled_video)

    music_file = project_dir / "music.wav"
    total_seconds = int(sum(scene.estimated_duration for scene in scenes))
    renderer.generate_background_music(total_seconds=total_seconds, output_path=music_file)

    final_video = project_dir / "video.mp4"
    renderer.mix_music(subtitled_video, music_file, final_video)

    thumbnail = project_dir / "thumbnail.jpg"
    renderer.create_thumbnail(final_video, thumbnail)

    renderer.write_manifest(
        {
            "job_id": job_id,
            "prompt": prompt,
            "minutes": minutes,
            "scene_seconds": scene_seconds,
            "voice": voice,
            "scene_count": len(scenes),
            "video": str(final_video.relative_to(BASE_DIR)),
            "thumbnail": str(thumbnail.relative_to(BASE_DIR)),
            "subtitle": str(subtitle_file.relative_to(BASE_DIR)),
            "created_at": int(time.time()),
        },
        project_dir / "manifest.json",
    )

    _update_job(
        job_id,
        status="completed",
        progress=100,
        message="Completed",
        download_url=f"/download/{job_id}",
        manifest_url=f"/manifest/{job_id}",
    )


# ── Core endpoints ────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/voices", methods=["GET"])
def voices():
    return jsonify({
        "voices": [
            {"id": k, "label": v["label"]}
            for k, v in VOICE_PRESETS.items()
        ],
        "default": DEFAULT_VOICE,
    })


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(force=True)
    prompt = str(payload.get("prompt", "")).strip()
    minutes = int(payload.get("minutes", 5))
    scene_seconds = int(payload.get("scene_seconds", 8))
    voice = str(payload.get("voice", DEFAULT_VOICE))
    if voice not in VOICE_PRESETS:
        voice = DEFAULT_VOICE

    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    job_id = uuid.uuid4().hex[:12]
    project_dir = _project_dir(job_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    with lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "voice": voice,
            "download_url": None,
            "manifest_url": None,
        }
        (project_dir / "job.json").write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")

    thread = threading.Thread(
        target=run_pipeline,
        kwargs={
            "job_id": job_id,
            "prompt": prompt,
            "minutes": minutes,
            "scene_seconds": scene_seconds,
            "voice": voice,
        },
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    with lock:
        job = jobs.get(job_id)
    if not job:
        job_file = _project_dir(job_id) / "job.json"
        if job_file.exists():
            return jsonify(json.loads(job_file.read_text(encoding="utf-8")))
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/download/<job_id>", methods=["GET"])
def download(job_id: str):
    target = _project_dir(job_id) / "video.mp4"
    if not target.exists():
        return jsonify({"error": "Video not ready"}), 404
    return send_file(target, mimetype="video/mp4", as_attachment=True)


@app.route("/manifest/<job_id>", methods=["GET"])
def manifest(job_id: str):
    target = _project_dir(job_id) / "manifest.json"
    if not target.exists():
        return jsonify({"error": "Manifest not ready"}), 404
    return send_file(target, mimetype="application/json")


# ── Photo upload endpoints ────────────────────────────────────────────────────

@app.route("/upload", methods=["POST"])
def upload_image():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(file.filename)
    dest = UPLOADS_DIR / safe_name
    file.save(str(dest))
    return jsonify({"filename": safe_name, "url": f"/uploads/{safe_name}"}), 201


@app.route("/uploads", methods=["GET"])
def list_uploads():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(UPLOADS_DIR.iterdir()):
        if f.suffix.lower() in ALLOWED_EXTENSIONS:
            files.append({
                "filename": f.name,
                "url": f"/uploads/{f.name}",
                "size": f.stat().st_size,
            })
    return jsonify({"uploads": files})


@app.route("/uploads/<filename>", methods=["GET"])
def serve_upload(filename: str):
    safe_name = secure_filename(filename)
    target = UPLOADS_DIR / safe_name
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(target)


@app.route("/uploads/<filename>", methods=["DELETE"])
def delete_upload(filename: str):
    safe_name = secure_filename(filename)
    target = UPLOADS_DIR / safe_name
    if not target.exists():
        return jsonify({"error": "File not found"}), 404
    target.unlink()
    return jsonify({"deleted": safe_name})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
