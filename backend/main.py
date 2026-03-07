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
from scene_builder import SceneBuilder, Scene
from script_generator import ScriptGenerator, ScenePlan
from video_renderer import VideoRenderer
from voice_generator import VoiceGenerator, VOICE_PRESETS, DEFAULT_VOICE

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROJECTS_DIR = OUTPUT_DIR / "projects"

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg"}

app = Flask(__name__)
CORS(app)

jobs: dict[str, dict] = {}
lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _project_dir(job_id: str) -> Path:
    return PROJECTS_DIR / job_id


def _update_job(job_id: str, **kwargs: object) -> None:
    with lock:
        jobs[job_id].update(kwargs)
        (_project_dir(job_id) / "job.json").write_text(
            json.dumps(jobs[job_id], indent=2), encoding="utf-8"
        )


def _load_script(job_id: str) -> list[ScenePlan]:
    data = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    return [
        ScenePlan(index=s["index"], narration=s["narration"], visual_description=s["visual_description"])
        for s in data["scenes"]
    ]


def _scenes_from_plans(plans: list[ScenePlan], scene_seconds: int) -> list[Scene]:
    return SceneBuilder().build(plans, scene_seconds)


# ── Pipeline phases ───────────────────────────────────────────────────────────

def _phase_script(job_id: str, prompt: str, minutes: int, scene_seconds: int) -> None:
    try:
        _update_job(job_id, status="generating", phase="script", progress=5, message="Generating script…")
        script_gen = ScriptGenerator(model="llama3")
        plans = script_gen.generate_scene_script(prompt, minutes, scene_seconds)
        script_gen.save_script_manifest(plans, _project_dir(job_id) / "script.json")
        _update_job(job_id, status="awaiting_approval", phase="script", progress=15,
                    message="Script ready — review and approve to continue.")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Script error: {exc}")


def _phase_images(job_id: str) -> None:
    try:
        plans = _load_script(job_id)
        job = jobs[job_id]
        scene_seconds = job["scene_seconds"]
        scenes = _scenes_from_plans(plans, scene_seconds)
        image_gen = ImageGenerator()
        total = len(scenes)
        for i, scene in enumerate(scenes, start=1):
            _update_job(job_id, status="generating", phase="images",
                        progress=15 + int((i / total) * 35),
                        message=f"Fetching image {i}/{total}…")
            image_path = _project_dir(job_id) / "images" / f"scene{scene.index:03d}.png"
            image_gen.generate_scene_image(scene, image_path)
        _update_job(job_id, status="awaiting_approval", phase="images", progress=50,
                    message="Images ready — review and approve to continue.")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Image error: {exc}")


def _phase_audio(job_id: str) -> None:
    try:
        plans = _load_script(job_id)
        job = jobs[job_id]
        voice = job.get("voice", DEFAULT_VOICE)
        scene_seconds = job["scene_seconds"]
        scenes = _scenes_from_plans(plans, scene_seconds)
        voice_gen = VoiceGenerator(voice=voice)
        total = len(scenes)
        for i, scene in enumerate(scenes, start=1):
            _update_job(job_id, status="generating", phase="audio",
                        progress=50 + int((i / total) * 20),
                        message=f"Generating narration {i}/{total}…")
            audio_path = _project_dir(job_id) / "audio" / f"scene{scene.index:03d}.wav"
            voice_gen.generate_scene_audio(scene, audio_path)
        _update_job(job_id, status="awaiting_approval", phase="audio", progress=70,
                    message="Audio ready — review and approve to render.")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Audio error: {exc}")


def _phase_render(job_id: str) -> None:
    try:
        plans = _load_script(job_id)
        job = jobs[job_id]
        scene_seconds = job["scene_seconds"]
        scenes = _scenes_from_plans(plans, scene_seconds)
        project_dir = _project_dir(job_id)
        renderer = VideoRenderer(project_dir)

        images = [project_dir / "images" / f"scene{s.index:03d}.png" for s in scenes]
        audios = [project_dir / "audio" / f"scene{s.index:03d}.wav" for s in scenes]

        _update_job(job_id, status="generating", phase="render", progress=75, message="Rendering video segments…")
        segments = renderer.render_segments(scenes, images, audios)
        raw_video = project_dir / "video_raw.mp4"
        renderer.concatenate(segments, raw_video)

        _update_job(job_id, status="generating", phase="render", progress=88, message="Adding subtitles and music…")
        subtitle_file = project_dir / "subtitles.srt"
        renderer.create_subtitles(scenes, subtitle_file)
        subtitled_video = project_dir / "video_sub.mp4"
        renderer.burn_subtitles(raw_video, subtitle_file, subtitled_video)

        music_file = project_dir / "music.wav"
        total_seconds = int(sum(s.estimated_duration for s in scenes))
        renderer.generate_background_music(total_seconds=total_seconds, output_path=music_file)
        final_video = project_dir / "video.mp4"
        renderer.mix_music(subtitled_video, music_file, final_video)

        thumbnail = project_dir / "thumbnail.jpg"
        renderer.create_thumbnail(final_video, thumbnail)
        renderer.write_manifest(
            {
                "job_id": job_id,
                "prompt": job.get("prompt", ""),
                "minutes": job.get("minutes", 0),
                "scene_seconds": scene_seconds,
                "voice": job.get("voice", DEFAULT_VOICE),
                "scene_count": len(scenes),
                "video": str(final_video.relative_to(BASE_DIR)),
                "thumbnail": str(thumbnail.relative_to(BASE_DIR)),
                "subtitle": str(subtitle_file.relative_to(BASE_DIR)),
                "created_at": int(time.time()),
            },
            project_dir / "manifest.json",
        )
        _update_job(job_id, status="completed", phase="render", progress=100,
                    message="Completed", download_url=f"/download/{job_id}",
                    manifest_url=f"/manifest/{job_id}")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Render error: {exc}")


def _start_thread(target, **kwargs) -> None:
    threading.Thread(target=target, kwargs=kwargs, daemon=True).start()


# ── Core endpoints ────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/voices", methods=["GET"])
def voices():
    return jsonify({
        "voices": [{"id": k, "label": v["label"]} for k, v in VOICE_PRESETS.items()],
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
            "job_id": job_id, "status": "queued", "phase": "script",
            "progress": 0, "message": "Queued",
            "prompt": prompt, "minutes": minutes,
            "scene_seconds": scene_seconds, "voice": voice,
            "download_url": None, "manifest_url": None,
        }
        (project_dir / "job.json").write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")

    _start_thread(_phase_script, job_id=job_id, prompt=prompt, minutes=minutes, scene_seconds=scene_seconds)
    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id: str):
    with lock:
        job = jobs.get(job_id)
    if not job:
        job_file = _project_dir(job_id) / "job.json"
        if job_file.exists():
            job = json.loads(job_file.read_text(encoding="utf-8"))
            with lock:
                jobs[job_id] = job
            return jsonify(job)
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ── Script review ─────────────────────────────────────────────────────────────

@app.route("/jobs/<job_id>/script", methods=["GET"])
def get_script(job_id: str):
    script_file = _project_dir(job_id) / "script.json"
    if not script_file.exists():
        return jsonify({"error": "Script not ready"}), 404
    return jsonify(json.loads(script_file.read_text(encoding="utf-8")))


@app.route("/jobs/<job_id>/script/approve", methods=["POST"])
def approve_script(job_id: str):
    """Accept optionally-edited scenes and kick off image generation."""
    payload = request.get_json(force=True) or {}
    scenes = payload.get("scenes")

    if scenes:
        # Save the (possibly user-edited) script back to disk
        plans = [
            ScenePlan(
                index=s.get("index", i + 1),
                narration=str(s.get("narration", "")).strip(),
                visual_description=str(s.get("visual_description", "")).strip(),
            )
            for i, s in enumerate(scenes)
        ]
        ScriptGenerator().save_script_manifest(plans, _project_dir(job_id) / "script.json")

    _update_job(job_id, status="generating", phase="images", progress=15, message="Starting image generation…")
    _start_thread(_phase_images, job_id=job_id)
    return jsonify({"ok": True})


# ── Image review ──────────────────────────────────────────────────────────────

@app.route("/jobs/<job_id>/images", methods=["GET"])
def get_images(job_id: str):
    script = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    images = []
    for scene in script["scenes"]:
        n = scene["index"]
        fname = f"scene{n:03d}.png"
        path = _project_dir(job_id) / "images" / fname
        images.append({
            "scene": n,
            "narration": scene["narration"],
            "url": f"/jobs/{job_id}/images/{n}" if path.exists() else None,
        })
    return jsonify({"images": images})


@app.route("/jobs/<job_id>/images/<int:scene_n>", methods=["GET"])
def serve_image(job_id: str, scene_n: int):
    path = _project_dir(job_id) / "images" / f"scene{scene_n:03d}.png"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return send_file(path, mimetype="image/png")


@app.route("/jobs/<job_id>/images/<int:scene_n>/replace", methods=["POST"])
def replace_image(job_id: str, scene_n: int):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if Path(file.filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Invalid image type"}), 400
    from PIL import Image
    import io
    img = Image.open(file.stream).convert("RGB").resize((1280, 720))
    dest = _project_dir(job_id) / "images" / f"scene{scene_n:03d}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return jsonify({"ok": True, "url": f"/jobs/{job_id}/images/{scene_n}"})


@app.route("/jobs/<job_id>/images/approve", methods=["POST"])
def approve_images(job_id: str):
    _update_job(job_id, status="generating", phase="audio", progress=50, message="Starting audio generation…")
    _start_thread(_phase_audio, job_id=job_id)
    return jsonify({"ok": True})


# ── Audio review ──────────────────────────────────────────────────────────────

@app.route("/jobs/<job_id>/audio", methods=["GET"])
def get_audio(job_id: str):
    script = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    audio_list = []
    for scene in script["scenes"]:
        n = scene["index"]
        path = _project_dir(job_id) / "audio" / f"scene{n:03d}.wav"
        audio_list.append({
            "scene": n,
            "narration": scene["narration"],
            "url": f"/jobs/{job_id}/audio/{n}" if path.exists() else None,
        })
    return jsonify({"audio": audio_list})


@app.route("/jobs/<job_id>/audio/<int:scene_n>", methods=["GET"])
def serve_audio(job_id: str, scene_n: int):
    path = _project_dir(job_id) / "audio" / f"scene{scene_n:03d}.wav"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return send_file(path, mimetype="audio/wav")


@app.route("/jobs/<job_id>/audio/<int:scene_n>/replace", methods=["POST"])
def replace_audio(job_id: str, scene_n: int):
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    ext = Path(file.filename).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        return jsonify({"error": "Invalid audio type"}), 400
    dest = _project_dir(job_id) / "audio" / f"scene{scene_n:03d}.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if ext == ".wav":
        file.save(str(dest))
    else:
        import subprocess, tempfile
        tmp = Path(tempfile.mktemp(suffix=ext))
        file.save(str(tmp))
        subprocess.check_call(["ffmpeg", "-y", "-i", str(tmp), str(dest)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.unlink(missing_ok=True)
    return jsonify({"ok": True, "url": f"/jobs/{job_id}/audio/{scene_n}"})


@app.route("/jobs/<job_id>/audio/approve", methods=["POST"])
def approve_audio(job_id: str):
    _update_job(job_id, status="generating", phase="render", progress=70, message="Starting render…")
    _start_thread(_phase_render, job_id=job_id)
    return jsonify({"ok": True})


# ── Download / manifest ───────────────────────────────────────────────────────

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
    file.save(str(UPLOADS_DIR / safe_name))
    return jsonify({"filename": safe_name, "url": f"/uploads/{safe_name}"}), 201


@app.route("/uploads", methods=["GET"])
def list_uploads():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        {"filename": f.name, "url": f"/uploads/{f.name}", "size": f.stat().st_size}
        for f in sorted(UPLOADS_DIR.iterdir())
        if f.suffix.lower() in ALLOWED_EXTENSIONS
    ]
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
