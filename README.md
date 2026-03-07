# ai-video-generator

Complete open-source pipeline for generating up to 30-minute narrated videos from a single text prompt using free local tools only.

## Features

- Public static frontend (`frontend/`) deployable on GitHub Pages.
- Python backend (`backend/`) for orchestration.
- Script generation with local Ollama (Llama 3 or Mistral).
- Image generation with Stable Diffusion (AUTOMATIC1111 API or Diffusers fallback).
- Voice narration with Piper TTS (espeak fallback).
- Video assembly with FFmpeg.
- Optional subtitles, background music, and thumbnail generation.
- GitHub Actions workflow for CPU-based rendering and artifact upload.

## Repository Structure

```text
ai-video-generator/
├── README.md
├── requirements.txt
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── backend/
│   ├── main.py
│   ├── script_generator.py
│   ├── scene_builder.py
│   ├── image_generator.py
│   ├── voice_generator.py
│   ├── video_renderer.py
│   ├── models/
│   ├── assets/
│   ├── output/
│   │   ├── images/
│   │   ├── audio/
│   │   ├── segments/
│   │   ├── subtitles/
│   │   ├── music/
│   │   ├── thumbnails/
│   │   ├── video/
│   │   └── jobs/
│   └── scripts/
│       └── run_pipeline.py
└── .github/
    └── workflows/
        └── render.yml
```

## End-to-end Flow

1. User enters prompt + length in frontend.
2. Frontend calls `POST /generate`.
3. Backend creates a render job:
   - generates scene script
   - builds scene plan
   - generates one image per scene
   - generates one narration audio per scene
   - renders scene video clips
   - concatenates final MP4
   - creates subtitles + music + thumbnail
4. Frontend polls `GET /status/<job_id>`.
5. User downloads final video from `GET /download/<job_id>`.

---

## Prerequisites

### 1) Python
- Python 3.10+ recommended.

### 2) FFmpeg
- Linux: `sudo apt-get install -y ffmpeg`
- macOS: `brew install ffmpeg`
- Windows: install from official FFmpeg builds and add to `PATH`.

### 3) Ollama (LLM)
Install Ollama and pull a free model:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
# OR
ollama pull mistral
```

### 4) Stable Diffusion
Use either option:

#### Option A: AUTOMATIC1111 WebUI API (recommended)
- Install and run AUTOMATIC1111 with `--api` flag.
- Ensure endpoint is available at `http://127.0.0.1:7860/sdapi/v1/txt2img`.

#### Option B: Diffusers fallback
- Backend will attempt to run Stable Diffusion v1.5 on CPU if API is unavailable.
- First run downloads model weights.

### 5) Piper TTS
Download Piper binary and an ONNX voice model (example):
- `backend/models/en_US-lessac-medium.onnx`

If Piper is unavailable, pipeline falls back to `espeak`.

---

## Installation

```bash
git clone <your-repo-url> ai-video-generator
cd ai-video-generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install optional TTS fallback:

```bash
sudo apt-get install -y espeak
```

---

## Run Backend

```bash
cd backend
python main.py
```

Backend runs on `http://localhost:8000`.

## Run Frontend Locally

From repository root:

```bash
python -m http.server 5500
```

Open `http://localhost:5500/frontend/`.

---

## Generate a Video

Example prompt:

> Create a 30 minute documentary about the fall of the Roman Empire.

In UI:
1. Enter prompt
2. Select 30 minutes
3. Click **Generate Video**
4. Wait for progress to reach 100%
5. Download MP4

Output files:
- images: `backend/output/images/scene001.png`
- narration: `backend/output/audio/scene001.wav`
- final video: `backend/output/video/<job_id>_final.mp4`
- subtitles: `backend/output/subtitles/<job_id>.srt`

---

## CLI Rendering

```bash
python backend/scripts/run_pipeline.py \
  --prompt "Create a 10 minute educational video about black holes" \
  --minutes 10 \
  --scene-seconds 8
```

---

## GitHub Pages Deployment (Frontend)

1. Push repository to GitHub.
2. In GitHub repo settings, enable **Pages** from branch (e.g. `main`) and folder `/frontend`.
3. Configure backend URL for deployed page by editing `frontend/app.js` default `API_BASE` or setting `localStorage.apiBase` in browser.

---

## GitHub Actions Rendering

Workflow: `.github/workflows/render.yml`

- Trigger manually (`workflow_dispatch`)
- Inputs: prompt, minutes, scene_seconds
- Installs Python + FFmpeg + dependencies
- Runs CLI pipeline
- Uploads generated MP4 as artifact

> Note: GitHub-hosted runners are CPU-only and can be slow for long renders.

---

## Example Prompts

- "Create a 30 minute documentary about the fall of the Roman Empire."
- "Create a 20 minute narrated explainer on climate tipping points."
- "Create a 15 minute storytelling video about Ada Lovelace and early computing."

---

## Test / Health Commands

```bash
python -m py_compile backend/*.py backend/scripts/run_pipeline.py
python backend/main.py
curl http://localhost:8000/health
```

---

## Notes on 30-minute Generation

For 30 minutes at 8 seconds per scene:
- total seconds: `1800`
- total scenes: `225`

This is computationally heavy on CPU-only systems. For best results:
- run Stable Diffusion on GPU
- pre-download models
- choose 10-second scene durations to reduce scene count

