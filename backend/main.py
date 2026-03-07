from __future__ import annotations

"""FastAPI backend for the local AI video generation pipeline."""

import asyncio
import cProfile
import json
import pstats
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette import status
from werkzeug.utils import secure_filename

try:
    from .config import get_settings
    from .image_generator import ALLOWED_EXTENSIONS, UPLOADS_DIR, ImageGenerator
    from .scene_builder import Scene, SceneBuilder
    from .script_generator import ScenePlan, ScriptGenerator, ScriptPackage
    from .video_renderer import VideoRenderer
    from .voice_generator import DEFAULT_VOICE, VOICE_PRESETS, VoiceGenerator
except ImportError:  # pragma: no cover
    from config import get_settings
    from image_generator import ALLOWED_EXTENSIONS, UPLOADS_DIR, ImageGenerator
    from scene_builder import Scene, SceneBuilder
    from script_generator import ScenePlan, ScriptGenerator, ScriptPackage
    from video_renderer import VideoRenderer
    from voice_generator import DEFAULT_VOICE, VOICE_PRESETS, VoiceGenerator

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROJECTS_DIR = OUTPUT_DIR / "projects"
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg"}

app = FastAPI(title="AI Video Generator", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic(auto_error=False)

jobs: dict[str, dict[str, Any]] = {}
job_logs: dict[str, list[str]] = {}
lock = threading.Lock()


def _project_dir(job_id: str) -> Path:
    """Return absolute project directory for job id."""

    return PROJECTS_DIR / job_id


def _auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    """Enforce optional HTTP Basic auth from environment settings."""

    if not settings.auth_enabled:
        return
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Auth required")
    if credentials.username != settings.api_user or credentials.password != settings.api_pass:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")


def _log(job_id: str, message: str) -> None:
    """Store in-memory job log entries for websocket streaming."""

    with lock:
        job_logs.setdefault(job_id, []).append(message)


def _update_job(job_id: str, **kwargs: object) -> None:
    """Update in-memory and on-disk job state atomically."""

    with lock:
        jobs[job_id].update(kwargs)
        project_dir = _project_dir(job_id)
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "job.json").write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")


def _phase_timeout(job_id: str) -> int:
    """Return timeout seconds configured for the given job."""

    with lock:
        job = jobs.get(job_id, {})
    return int(job.get("timeout_seconds", settings.job_timeout_seconds))


def _record_phase_timing(job_id: str, phase: str, elapsed_seconds: float) -> None:
    """Store per-phase timing metrics in job state."""

    with lock:
        timings = dict(jobs.get(job_id, {}).get("phase_times", {}))
        timings[phase] = round(elapsed_seconds, 2)
    _update_job(job_id, phase_times=timings)


def _run_with_timeout(job_id: str, phase: str, func) -> None:
    """Run a phase with hard timeout and metric recording."""

    timeout_seconds = _phase_timeout(job_id)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            _update_job(job_id, status="failed", message=f"{phase.title()} timed out after {timeout_seconds}s")
            _log(job_id, f"{phase} timed out after {timeout_seconds}s")
            return
    _record_phase_timing(job_id, phase, time.perf_counter() - started)


def _count_scenes_from_script(job_id: str) -> int:
    """Return scene count from persisted script manifest."""

    script_file = _project_dir(job_id) / "script.json"
    if not script_file.exists():
        return 0
    data = json.loads(script_file.read_text(encoding="utf-8"))
    return int(data.get("scene_count", len(data.get("scenes", []))))


def _phase_completed(job_id: str, phase: str) -> bool:
    """Check whether phase artifacts are already present for resume mode."""

    project_dir = _project_dir(job_id)
    if phase == "script":
        return (project_dir / "script.json").exists()
    scene_count = _count_scenes_from_script(job_id)
    if phase == "images":
        return scene_count > 0 and len(list((project_dir / "images").glob("scene*.png"))) >= scene_count
    if phase == "audio":
        return scene_count > 0 and len(list((project_dir / "audio").glob("scene*.wav"))) >= scene_count
    if phase == "render":
        return (project_dir / "video.mp4").exists()
    return False


def _next_phase_to_run(job_id: str) -> str:
    """Return the first incomplete phase for resume."""

    for phase in ("script", "images", "audio", "render"):
        if not _phase_completed(job_id, phase):
            return phase
    return "done"


def _load_script(job_id: str) -> tuple[list[ScenePlan], dict[str, Any]]:
    """Load stored script manifest and return scene plans + metadata."""

    data = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    plans = [
        ScenePlan(index=s["index"], narration=s["narration"], visual_description=s["visual_description"])
        for s in data.get("scenes", [])
    ]
    return plans, data


def _scenes_from_plans(
    plans: list[ScenePlan],
    scene_seconds: int,
    *,
    style: str,
    auto_scene_duration: bool,
) -> list[Scene]:
    """Build render scenes from script plans with style-aware duration logic."""

    worker_count = settings.max_workers_cpu
    return SceneBuilder().build(
        plans,
        scene_seconds,
        style=style,
        auto_scene_duration=auto_scene_duration,
        parallel=True,
        max_workers=worker_count,
    )


def _phase_script(job_id: str, prompt: str, minutes: int, scene_seconds: int, model: str, style: str, max_scenes: int) -> None:
    """Generate script and pause job in approval state."""

    try:
        _update_job(job_id, status="generating", phase="script", progress=5, message="Generating script…")
        _log(job_id, "Starting two-stage script generation")
        script_gen = ScriptGenerator(model=model, style=style)
        package = script_gen.generate_scene_script(prompt, minutes, scene_seconds, style=style, max_scenes=max_scenes)
        if not package.scenes:
            raise RuntimeError("No scenes generated for prompt")
        script_gen.save_script_manifest(package, _project_dir(job_id) / "script.json")
        _update_job(
            job_id,
            status="awaiting_approval",
            phase="script",
            progress=15,
            language=package.language,
            style=package.style,
            model=package.model,
            message="Script ready — review and approve to continue.",
        )
        _log(job_id, f"Script phase complete: {len(package.scenes)} scenes ({package.language})")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Script error: {exc}")
        _log(job_id, f"Script phase failed: {exc}")


def _phase_images(job_id: str) -> None:
    """Generate images for each scene and pause for approval."""

    try:
        plans, script = _load_script(job_id)
        job = jobs[job_id]
        scenes = _scenes_from_plans(
            plans,
            int(job["scene_seconds"]),
            style=str(job.get("style", "educational")),
            auto_scene_duration=bool(job.get("auto_scene_duration", False)),
        )
        if not scenes:
            raise RuntimeError("No scenes to render images")

        image_gen = ImageGenerator(job_id=job_id, clear_cache=bool(job.get("clear_cache", False)))
        _update_job(job_id, status="generating", phase="images", progress=18, message="Generating images…")
        _log(job_id, "Image generation started")

        image_gen.generate_images_parallel(
            scenes,
            _project_dir(job_id) / "images",
            max_workers=settings.max_workers_cpu,
            steps=int(job.get("steps", settings.sd_steps)),
            seed=job.get("seed"),
        )

        thumbs = image_gen.generate_thumbnail_variants(
            scenes[0].visual_prompt,
            _project_dir(job_id) / "thumbnails",
        )

        _update_job(
            job_id,
            status="awaiting_approval",
            phase="images",
            progress=50,
            thumbnail_options=[f"/jobs/{job_id}/thumbnails/{p.name}" for p in thumbs],
            message="Images ready — review and approve to continue.",
        )
        _log(job_id, "Image phase complete")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Image error: {exc}")
        _log(job_id, f"Image phase failed: {exc}")


def _phase_audio(job_id: str) -> None:
    """Generate narration tracks for each scene and pause for approval."""

    try:
        plans, _ = _load_script(job_id)
        job = jobs[job_id]
        scenes = _scenes_from_plans(
            plans,
            int(job["scene_seconds"]),
            style=str(job.get("style", "educational")),
            auto_scene_duration=bool(job.get("auto_scene_duration", False)),
        )
        language = str(job.get("language", "en"))
        voice = str(job.get("voice", DEFAULT_VOICE))

        voice_gen = VoiceGenerator(
            job_id=job_id,
            voice=voice,
            language=language,
            clear_cache=bool(job.get("clear_cache", False)),
        )

        _update_job(job_id, status="generating", phase="audio", progress=52, message="Generating audio…")
        _log(job_id, "Audio generation started")
        voice_gen.generate_audio_parallel(scenes, _project_dir(job_id) / "audio", max_workers=settings.max_workers_cpu)
        _update_job(job_id, status="awaiting_approval", phase="audio", progress=70, message="Audio ready — review and approve to render.")
        _log(job_id, "Audio phase complete")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Audio error: {exc}")
        _log(job_id, f"Audio phase failed: {exc}")


def _phase_render(job_id: str) -> None:
    """Render final video outputs from scene assets."""

    start = time.perf_counter()
    try:
        plans, script = _load_script(job_id)
        job = jobs[job_id]
        scenes = _scenes_from_plans(
            plans,
            int(job["scene_seconds"]),
            style=str(job.get("style", "educational")),
            auto_scene_duration=bool(job.get("auto_scene_duration", False)),
        )
        if not scenes:
            raise RuntimeError("Cannot render: no scenes available")

        project_dir = _project_dir(job_id)
        renderer = VideoRenderer(project_dir)

        images = [project_dir / "images" / f"scene{s.index:03d}.png" for s in scenes]
        audios = [project_dir / "audio" / f"scene{s.index:03d}.wav" for s in scenes]

        _update_job(job_id, status="generating", phase="render", progress=75, message="Rendering video segments…")
        transition_style = str(job.get("transition_style", settings.transition_style))
        segments = renderer.render_segments(scenes, images, audios, transition_style=transition_style)

        raw_video = project_dir / "video_raw.mp4"
        renderer.concatenate(segments, raw_video)

        _update_job(job_id, status="generating", phase="render", progress=88, message="Adding subtitles and music…")
        subtitle_file = project_dir / "subtitles.srt"
        renderer.create_subtitles(scenes, subtitle_file)

        subtitled_video = project_dir / "video_sub.mp4"
        renderer.burn_subtitles(raw_video, subtitle_file, subtitled_video)

        music_file = project_dir / "music.wav"
        total_seconds = int(sum(s.estimated_duration for s in scenes))
        script_text = " ".join([s.narration for s in scenes[:3]])
        renderer.generate_background_music(total_seconds=total_seconds, output_path=music_file, script_text=script_text)

        final_video = project_dir / "video.mp4"
        renderer.mix_music(subtitled_video, music_file, final_video)

        thumbnail = project_dir / "thumbnail.jpg"
        renderer.create_thumbnail(final_video, thumbnail)

        renderer.write_manifest(
            {
                "job_id": job_id,
                "prompt": job.get("prompt", ""),
                "minutes": job.get("minutes", 0),
                "scene_seconds": job.get("scene_seconds", 0),
                "voice": job.get("voice", DEFAULT_VOICE),
                "language": job.get("language", "en"),
                "style": job.get("style", "educational"),
                "model": job.get("model", settings.ollama_model),
                "scene_count": len(scenes),
                "video": str(final_video.relative_to(BASE_DIR)),
                "thumbnail": str(thumbnail.relative_to(BASE_DIR)),
                "thumbnail_options": [
                    str(p.relative_to(BASE_DIR)) for p in sorted((project_dir / "thumbnails").glob("*.png"))
                ],
                "subtitle": str(subtitle_file.relative_to(BASE_DIR)),
                "created_at": int(time.time()),
                "render_seconds": round(time.perf_counter() - start, 2),
                "phase_times": dict(job.get("phase_times", {})),
                "total_seconds": round(sum(float(v) for v in dict(job.get("phase_times", {})).values()), 2),
            },
            project_dir / "manifest.json",
        )

        _update_job(
            job_id,
            status="completed",
            phase="render",
            progress=100,
            message="Completed",
            download_url=f"/download/{job_id}",
            manifest_url=f"/manifest/{job_id}",
        )
        _log(job_id, "Render phase complete")
    except Exception as exc:
        _update_job(job_id, status="failed", message=f"Render error: {exc}")
        _log(job_id, f"Render phase failed: {exc}")


def _start_thread(target, *, phase: str | None = None, timeout_job_id: str | None = None, **kwargs: object) -> None:
    """Start pipeline phase in daemon thread with timeout wrapper."""

    if phase and timeout_job_id:
        def _runner() -> None:
            _run_with_timeout(timeout_job_id, phase, lambda: target(**kwargs))

        threading.Thread(
            target=_runner,
            daemon=True,
        ).start()
        return
    threading.Thread(target=target, kwargs=kwargs, daemon=True).start()


def run_pipeline(
    job_id: str,
    prompt: str,
    minutes: int,
    scene_seconds: int,
    *,
    voice: str = DEFAULT_VOICE,
    model: str | None = None,
    style: str = "educational",
    language: str = "auto",
    transition_style: str = "kenburns",
    steps: int = 20,
    seed: int | None = None,
    clear_cache: bool = False,
    auto_scene_duration: bool = False,
    max_scenes: int = 300,
    profile: bool = False,
    timeout_seconds: int | None = None,
    resume: bool = False,
) -> None:
    """Run the complete pipeline synchronously for CLI/workflows."""

    project_dir = _project_dir(job_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    existing_job_file = project_dir / "job.json"
    existing_data: dict[str, Any] = {}
    if resume and existing_job_file.exists():
        existing_data = json.loads(existing_job_file.read_text(encoding="utf-8"))

    with lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "phase": existing_data.get("phase", "script"),
            "progress": int(existing_data.get("progress", 0)),
            "message": "Queued",
            "prompt": existing_data.get("prompt", prompt),
            "minutes": int(existing_data.get("minutes", minutes)),
            "scene_seconds": int(existing_data.get("scene_seconds", scene_seconds)),
            "voice": existing_data.get("voice", voice),
            "model": existing_data.get("model", model or settings.ollama_model),
            "style": existing_data.get("style", style),
            "language": existing_data.get("language", language),
            "transition_style": existing_data.get("transition_style", transition_style),
            "steps": int(existing_data.get("steps", steps)),
            "seed": existing_data.get("seed", seed),
            "clear_cache": bool(existing_data.get("clear_cache", clear_cache)),
            "auto_scene_duration": bool(existing_data.get("auto_scene_duration", auto_scene_duration)),
            "max_scenes": int(existing_data.get("max_scenes", max_scenes)),
            "timeout_seconds": int(existing_data.get("timeout_seconds", timeout_seconds or settings.job_timeout_seconds)),
            "phase_times": existing_data.get("phase_times", {}),
            "download_url": existing_data.get("download_url"),
            "manifest_url": existing_data.get("manifest_url"),
        }
        existing_job_file.write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")

    profiler: cProfile.Profile | None = cProfile.Profile() if profile else None
    if profiler:
        profiler.enable()

    start_phase = _next_phase_to_run(job_id) if resume else "script"
    if start_phase == "done":
        _update_job(job_id, status="completed", progress=100, message="Already completed")
        return

    phase_sequence: list[tuple[str, Any, tuple[Any, ...]]] = [
        ("script", _phase_script, (job_id, jobs[job_id]["prompt"], jobs[job_id]["minutes"], jobs[job_id]["scene_seconds"], jobs[job_id]["model"], jobs[job_id]["style"], jobs[job_id]["max_scenes"])),
        ("images", _phase_images, (job_id,)),
        ("audio", _phase_audio, (job_id,)),
        ("render", _phase_render, (job_id,)),
    ]
    start_index = [p[0] for p in phase_sequence].index(start_phase)
    for phase_name, phase_func, phase_args in phase_sequence[start_index:]:
        _run_with_timeout(job_id, phase_name, lambda f=phase_func, a=phase_args: f(*a))
        if jobs[job_id]["status"] == "failed":
            raise RuntimeError(jobs[job_id]["message"])

    if profiler:
        profiler.disable()
        profile_path = _project_dir(job_id) / "profile_stats.txt"
        with profile_path.open("w", encoding="utf-8") as handle:
            stats = pstats.Stats(profiler, stream=handle).sort_stats("cumulative")
            stats.print_stats()


@app.get("/health")
def health() -> dict[str, bool]:
    """Health endpoint for process checks."""

    return {"ok": True}


@app.get("/voices")
def voices(_: None = Depends(_auth)) -> dict[str, Any]:
    """Return available voice presets and defaults."""

    return {
        "voices": [{"id": k, "label": v["label"]} for k, v in VOICE_PRESETS.items()],
        "default": DEFAULT_VOICE,
        "default_voice_model": settings.default_voice,
    }


@app.post("/generate")
async def generate(payload: dict[str, Any], _: None = Depends(_auth)) -> JSONResponse:
    """Create a new generation job and start script phase asynchronously."""

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        return JSONResponse({"error": "Prompt is required"}, status_code=400)

    minutes = int(payload.get("minutes", 5))
    scene_seconds = int(payload.get("scene_seconds", 8))
    voice = str(payload.get("voice", DEFAULT_VOICE))
    model = str(payload.get("model", settings.ollama_model))
    style = str(payload.get("style", settings.default_style)).lower()
    language = str(payload.get("language", "auto"))
    transition_style = str(payload.get("transition_style", settings.transition_style)).lower()
    steps = int(payload.get("steps", settings.sd_steps))
    seed = payload.get("seed")
    clear_cache = bool(payload.get("clear_cache", False))
    auto_scene_duration = bool(payload.get("auto_scene_duration", False))
    max_scenes = int(payload.get("max_scenes", settings.max_scenes))
    timeout_seconds = int(payload.get("timeout_seconds", settings.job_timeout_seconds))

    job_id = uuid.uuid4().hex[:12]
    project_dir = _project_dir(job_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    with lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "phase": "script",
            "progress": 0,
            "message": "Queued",
            "prompt": prompt,
            "minutes": minutes,
            "scene_seconds": scene_seconds,
            "voice": voice,
            "model": model,
            "style": style,
            "language": language,
            "transition_style": transition_style,
            "steps": steps,
            "seed": seed,
            "clear_cache": clear_cache,
            "auto_scene_duration": auto_scene_duration,
            "max_scenes": max_scenes,
            "timeout_seconds": timeout_seconds,
            "phase_times": {},
            "download_url": None,
            "manifest_url": None,
        }
        (project_dir / "job.json").write_text(json.dumps(jobs[job_id], indent=2), encoding="utf-8")

    _start_thread(
        _phase_script,
        phase="script",
        timeout_job_id=job_id,
        job_id=job_id,
        prompt=prompt,
        minutes=minutes,
        scene_seconds=scene_seconds,
        model=model,
        style=style,
        max_scenes=max_scenes,
    )
    _log(job_id, "Job queued")
    return JSONResponse({"job_id": job_id})


@app.get("/status/{job_id}")
def status_endpoint(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Return current state for a job id."""

    with lock:
        job = jobs.get(job_id)
    if not job:
        job_file = _project_dir(job_id) / "job.json"
        if job_file.exists():
            job = json.loads(job_file.read_text(encoding="utf-8"))
            with lock:
                jobs[job_id] = job
            return JSONResponse(job)
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse(job)


@app.post("/jobs/{job_id}/resume")
def resume_job(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Resume interrupted job from the first incomplete phase."""

    job_file = _project_dir(job_id) / "job.json"
    if not job_file.exists():
        return JSONResponse({"error": "Job not found"}, status_code=404)

    data = json.loads(job_file.read_text(encoding="utf-8"))
    with lock:
        jobs[job_id] = data

    next_phase = _next_phase_to_run(job_id)
    if next_phase == "done":
        _update_job(job_id, status="completed", progress=100, message="Already completed")
        return JSONResponse({"ok": True, "phase": "done"})

    _update_job(job_id, status="generating", phase=next_phase, message=f"Resuming {next_phase} phase…")
    if next_phase == "script":
        _start_thread(
            _phase_script,
            phase="script",
            timeout_job_id=job_id,
            job_id=job_id,
            prompt=str(data.get("prompt", "")),
            minutes=int(data.get("minutes", 5)),
            scene_seconds=int(data.get("scene_seconds", 8)),
            model=str(data.get("model", settings.ollama_model)),
            style=str(data.get("style", settings.default_style)),
            max_scenes=int(data.get("max_scenes", settings.max_scenes)),
        )
    elif next_phase == "images":
        _start_thread(_phase_images, phase="images", timeout_job_id=job_id, job_id=job_id)
    elif next_phase == "audio":
        _start_thread(_phase_audio, phase="audio", timeout_job_id=job_id, job_id=job_id)
    else:
        _start_thread(_phase_render, phase="render", timeout_job_id=job_id, job_id=job_id)
    return JSONResponse({"ok": True, "phase": next_phase})


@app.websocket("/ws/jobs/{job_id}/logs")
async def ws_job_logs(websocket: WebSocket, job_id: str) -> None:
    """Stream incremental job logs to frontend clients."""

    await websocket.accept()
    cursor = 0
    try:
        while True:
            await asyncio.sleep(1.0)
            with lock:
                logs = job_logs.get(job_id, [])
                job = jobs.get(job_id)
            if cursor < len(logs):
                batch = logs[cursor:]
                cursor = len(logs)
                await websocket.send_json({"logs": batch, "job": job})
            elif job and job.get("status") in {"failed", "completed"}:
                await websocket.send_json({"logs": [], "job": job})
                break
    except WebSocketDisconnect:
        return


@app.get("/jobs/{job_id}/script")
def get_script(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Return generated script manifest."""

    script_file = _project_dir(job_id) / "script.json"
    if not script_file.exists():
        return JSONResponse({"error": "Script not ready"}, status_code=404)
    return JSONResponse(json.loads(script_file.read_text(encoding="utf-8")))


@app.post("/jobs/{job_id}/script/approve")
async def approve_script(job_id: str, payload: dict[str, Any], _: None = Depends(_auth)) -> JSONResponse:
    """Save optional edited script and trigger image generation phase."""

    scenes = payload.get("scenes")
    if scenes:
        plans = [
            ScenePlan(
                index=s.get("index", i + 1),
                narration=str(s.get("narration", "")).strip(),
                visual_description=str(s.get("visual_description", "")).strip(),
            )
            for i, s in enumerate(scenes)
        ]
        metadata = jobs.get(job_id, {})
        package = ScriptPackage(
            scenes=plans,
            language=str(metadata.get("language", "en")),
            style=str(metadata.get("style", "educational")),
            model=str(metadata.get("model", settings.ollama_model)),
            outline="Edited by user",
        )
        ScriptGenerator().save_script_manifest(package, _project_dir(job_id) / "script.json")

    _update_job(job_id, status="generating", phase="images", progress=15, message="Starting image generation…")
    _start_thread(_phase_images, phase="images", timeout_job_id=job_id, job_id=job_id)
    _log(job_id, "Script approved")
    return JSONResponse({"ok": True})


@app.get("/jobs/{job_id}/images")
def get_images(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Return image review manifest for all scenes."""

    script = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    images = []
    for scene in script.get("scenes", []):
        n = scene["index"]
        fname = f"scene{n:03d}.png"
        path = _project_dir(job_id) / "images" / fname
        images.append(
            {
                "scene": n,
                "narration": scene["narration"],
                "url": f"/jobs/{job_id}/images/{n}" if path.exists() else None,
            }
        )
    thumbs = sorted((_project_dir(job_id) / "thumbnails").glob("*.png"))
    return JSONResponse({"images": images, "thumbnails": [f"/jobs/{job_id}/thumbnails/{p.name}" for p in thumbs]})


@app.get("/jobs/{job_id}/images/{scene_n}")
def serve_image(job_id: str, scene_n: int, _: None = Depends(_auth)) -> FileResponse:
    """Serve one scene image."""

    path = _project_dir(job_id) / "images" / f"scene{scene_n:03d}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/png")


@app.get("/jobs/{job_id}/thumbnails/{filename}")
def serve_thumbnail(job_id: str, filename: str, _: None = Depends(_auth)) -> FileResponse:
    """Serve generated thumbnail variant."""

    path = _project_dir(job_id) / "thumbnails" / secure_filename(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="image/png")


@app.post("/jobs/{job_id}/images/{scene_n}/replace")
async def replace_image(job_id: str, scene_n: int, file: UploadFile = File(...), _: None = Depends(_auth)) -> JSONResponse:
    """Replace one generated scene image from uploaded file."""

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": "Invalid image type"}, status_code=400)

    from PIL import Image

    raw = await file.read()
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        Path(tmp.name).write_bytes(raw)
        img = Image.open(tmp.name).convert("RGB").resize((1280, 720))
        dest = _project_dir(job_id) / "images" / f"scene{scene_n:03d}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    return JSONResponse({"ok": True, "url": f"/jobs/{job_id}/images/{scene_n}"})


@app.get("/jobs/{job_id}/preview")
def preview(job_id: str, _: None = Depends(_auth)) -> FileResponse:
    """Serve a 10-second preview clip when intermediate video exists."""

    raw = _project_dir(job_id) / "video_raw.mp4"
    final = _project_dir(job_id) / "video.mp4"
    source = raw if raw.exists() else final
    if not source.exists():
        raise HTTPException(status_code=404, detail="Preview not ready")

    preview_path = _project_dir(job_id) / "preview.mp4"
    import subprocess

    subprocess.check_call(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-t", "10", "-c", "copy", str(preview_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return FileResponse(preview_path, media_type="video/mp4")


@app.post("/jobs/{job_id}/images/approve")
def approve_images(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Approve image stage and trigger audio generation."""

    _update_job(job_id, status="generating", phase="audio", progress=50, message="Starting audio generation…")
    _start_thread(_phase_audio, phase="audio", timeout_job_id=job_id, job_id=job_id)
    _log(job_id, "Images approved")
    return JSONResponse({"ok": True})


@app.get("/jobs/{job_id}/audio")
def get_audio(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Return audio review manifest for all scenes."""

    script = json.loads((_project_dir(job_id) / "script.json").read_text(encoding="utf-8"))
    audio_list = []
    for scene in script.get("scenes", []):
        n = scene["index"]
        path = _project_dir(job_id) / "audio" / f"scene{n:03d}.wav"
        audio_list.append(
            {
                "scene": n,
                "narration": scene["narration"],
                "url": f"/jobs/{job_id}/audio/{n}" if path.exists() else None,
            }
        )
    return JSONResponse({"audio": audio_list})


@app.get("/jobs/{job_id}/audio/{scene_n}")
def serve_audio(job_id: str, scene_n: int, _: None = Depends(_auth)) -> FileResponse:
    """Serve one narration wav file."""

    path = _project_dir(job_id) / "audio" / f"scene{scene_n:03d}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="audio/wav")


@app.post("/jobs/{job_id}/audio/{scene_n}/replace")
async def replace_audio(job_id: str, scene_n: int, file: UploadFile = File(...), _: None = Depends(_auth)) -> JSONResponse:
    """Replace one narration clip and normalize to wav format."""

    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        return JSONResponse({"error": "Invalid audio type"}, status_code=400)

    dest = _project_dir(job_id) / "audio" / f"scene{scene_n:03d}.wav"
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = await file.read()

    if ext == ".wav":
        dest.write_bytes(raw)
        return JSONResponse({"ok": True, "url": f"/jobs/{job_id}/audio/{scene_n}"})

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp_file:
        tmp = Path(tmp_file.name)
    try:
        tmp.write_bytes(raw)
        import subprocess

        subprocess.check_call(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), str(dest)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        tmp.unlink(missing_ok=True)

    return JSONResponse({"ok": True, "url": f"/jobs/{job_id}/audio/{scene_n}"})


@app.post("/jobs/{job_id}/audio/approve")
def approve_audio(job_id: str, _: None = Depends(_auth)) -> JSONResponse:
    """Approve audio stage and trigger render phase."""

    _update_job(job_id, status="generating", phase="render", progress=70, message="Starting render…")
    _start_thread(_phase_render, phase="render", timeout_job_id=job_id, job_id=job_id)
    _log(job_id, "Audio approved")
    return JSONResponse({"ok": True})


@app.get("/download/{job_id}")
def download(job_id: str, _: None = Depends(_auth)) -> FileResponse:
    """Download final mp4 artifact for job."""

    target = _project_dir(job_id) / "video.mp4"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(target, media_type="video/mp4", filename="video.mp4")


@app.get("/manifest/{job_id}")
def manifest(job_id: str, _: None = Depends(_auth)) -> FileResponse:
    """Return manifest json for job."""

    target = _project_dir(job_id) / "manifest.json"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Manifest not ready")
    return FileResponse(target, media_type="application/json")


@app.post("/upload")
async def upload_image(file: UploadFile = File(...), _: None = Depends(_auth)) -> JSONResponse:
    """Upload source photo for rotating scene image mode."""

    if not file.filename:
        return JSONResponse({"error": "No filename"}, status_code=400)
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JSONResponse({"error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}, status_code=400)

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(file.filename)
    target = UPLOADS_DIR / safe_name
    target.write_bytes(await file.read())
    return JSONResponse({"filename": safe_name, "url": f"/uploads/{safe_name}"}, status_code=201)


@app.get("/uploads")
def list_uploads(_: None = Depends(_auth)) -> JSONResponse:
    """List uploaded source photos."""

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        {"filename": f.name, "url": f"/uploads/{f.name}", "size": f.stat().st_size}
        for f in sorted(UPLOADS_DIR.iterdir())
        if f.suffix.lower() in ALLOWED_EXTENSIONS
    ]
    return JSONResponse({"uploads": files})


@app.get("/uploads/{filename}")
def serve_upload(filename: str, _: None = Depends(_auth)) -> FileResponse:
    """Serve previously uploaded source photo."""

    target = UPLOADS_DIR / secure_filename(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)


@app.delete("/uploads/{filename}")
def delete_upload(filename: str, _: None = Depends(_auth)) -> JSONResponse:
    """Delete uploaded source photo."""

    target = UPLOADS_DIR / secure_filename(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink(missing_ok=True)
    return JSONResponse({"deleted": target.name})
