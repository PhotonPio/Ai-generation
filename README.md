# AI Video Generator (Local, Free, Open Source)

End-to-end local pipeline that generates narrated videos from one prompt using open-source models and tools.

## New Features

- FastAPI backend with HTTP Basic auth (`API_USER` / `API_PASS`) and WebSocket live logs.
- Two-stage script generation (outline -> scene JSON) with selectable Ollama model.
- Style controls: `educational`, `storytelling`, `documentary`, `fun`.
- Multi-language flow with language auto-detection (`langdetect`) and multilingual Piper voice mapping.
- MoviePy transitions and Ken Burns-style motion (`--transition-style fade|kenburns|none`).
- 3 thumbnail variants per job (`cinematic`, `minimalist`, `vibrant`) and frontend thumbnail picker.
- Theme-based CC0 music selection from `backend/assets/music` with 15% background mix.
- Parallel scene processing for script prep, image generation, and audio generation.
- Scene/image/audio cache reuse via SHA-256 keys.
- Optional dynamic scene duration (`--auto-scene-duration`) and max scene cap (`--max-scenes`).
- Optional profiling (`--profile`) to generate `profile_stats.txt`.
- Added unit tests under `tests/`.

## Repository Layout

```text
backend/
  main.py
  config.py
  script_generator.py
  scene_builder.py
  image_generator.py
  voice_generator.py
  video_renderer.py
  scripts/run_pipeline.py
  assets/music/
frontend/
requirements.txt
.github/workflows/render.yml
tests/test_pipeline.py
```

## Requirements

- Python 3.10+
- FFmpeg + ffprobe
- espeak (fallback TTS)
- Optional local services/models:
  - Ollama (`llama3:8b`, `mistral`, etc.)
  - AUTOMATIC1111 API (`--api`) for best image quality
  - Piper CLI + voice files (auto-download supported)

Install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

All major options are in `backend/config.py` and overridable via env vars.

Key env vars:

- `API_USER`, `API_PASS`, `AUTH_ENABLED`
- `OLLAMA_URL`, `OLLAMA_MODEL`
- `DEFAULT_STYLE`, `DEFAULT_VOICE`
- `TRANSITION_STYLE`, `TRANSITION_SECONDS`
- `MAX_WORKERS_CPU`, `MAX_WORKERS_GPU`
- `SD_STEPS`, `SD_MODEL`, `A1111_URL`
- `ENABLE_CLIP_SCORING`, `CLIP_THRESHOLD`, `CLIP_RETRIES`
- `MAX_SCENES`

## Run Backend (FastAPI)

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

Frontend (static):

```bash
python -m http.server 5500
# open http://localhost:5500/frontend/
```

## CLI Usage

```bash
python backend/scripts/run_pipeline.py \
  --prompt "Create a 5-minute educational video about black holes" \
  --minutes 5 \
  --scene-seconds 8 \
  --model llama3:8b \
  --style educational \
  --language auto \
  --voice en_US-lessac-medium \
  --transition-style kenburns \
  --steps 20 \
  --auto-scene-duration \
  --max-scenes 300
```

Additional flags:

- `--seed <int>`: reproducible image generation seed.
- `--clear-cache`: clear image/audio cache before run.
- `--profile`: save cProfile stats to project output.
- `--transcribe`: enables Whisper hooks for audio-driven flows.

## Frontend Improvements

- Model/style/language/transition options.
- Per-phase progress bars.
- Live log streaming via `/ws/jobs/{job_id}/logs`.
- Thumbnail options panel.
- 10-second preview playback during render (`/jobs/{job_id}/preview`).

## Security

HTTP Basic auth is enabled by default.

- Default (change immediately): `admin` / `changeme`
- Disable only in trusted local environments:

```bash
export AUTH_ENABLED=false
```

## Performance Tips

- Enable A1111 with optimized launch flags (`--opt-sdp-attention` recommended).
- Keep `--transition-style kenburns` for good quality/perf balance.
- Use `--steps 20` for preview runs.
- Use `--clear-cache` only when needed; caching can save major rerun time.

## Benchmarks (Expected)

On multi-core CPU with caching and parallel workers enabled:

- Image + audio stage wall-time reduction: ~50-70%.
- End-to-end rerun speedup (same prompt): often >60% due to cache hits.

## Multi-language Notes

- Prompt language is auto-detected.
- Voice defaults mapped by language (e.g. `en`, `de`, `fr`, `es`).
- Subtitles are emitted in the same narration language.

## Music Setup

Place CC0 `.mp3` tracks in `backend/assets/music/`.
Suggested naming: `calm_*`, `epic_*`, `uplifting_*` so theme matcher can prioritize tracks.

## Tests

```bash
pytest -q
```

Included tests cover:

- scene count cap logic
- style/language script package behavior
- dynamic scene duration bounds
- language-to-voice mapping
- deterministic image cache keys
- SRT time formatting
