# ai-video-generator

Zero-cost, open-source system for generating long-form narrated videos (up to 30 minutes) from a single prompt.

It uses only free/local tools:
- **LLM**: Ollama (Llama 3 or Mistral)
- **Image generation**: Stable Diffusion via AUTOMATIC1111 API (or Diffusers CPU fallback)
- **Narration**: Piper TTS (or espeak fallback)
- **Rendering**: FFmpeg

---

## Features

- Public web interface in plain HTML/CSS/JS (GitHub Pages compatible)
- Modular Python backend pipeline
- Scene-based long-form video generation
- Auto subtitles (SRT + burned subtitles)
- Background music synthesis
- Thumbnail output
- Downloadable MP4 output
- GitHub Actions workflow for CPU rendering + artifact upload

---

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
│   └── scripts/
│       └── run_pipeline.py
├── models/
├── assets/
├── output/
│   ├── images/
│   ├── audio/
│   ├── segments/
│   ├── subtitles/
│   ├── music/
│   ├── thumbnails/
│   ├── video/
│   └── jobs/
├── scripts/
└── .github/
    └── workflows/
        └── render.yml
```

---

## End-to-end Pipeline

1. User opens frontend and enters prompt + length
2. `POST /generate` starts backend job
3. Backend pipeline:
   - script generation
   - scene planning
   - image generation
   - narration generation
   - segment rendering
   - video concatenation
   - subtitle creation/burning
   - music mixing
4. Final MP4 created at `output/video/<job_id>_final.mp4`
5. User downloads from `GET /download/<job_id>`

---

## Installation

## 1) Python
Install Python 3.10+.

## 2) FFmpeg

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ffmpeg
```

## 3) Ollama + LLM model

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3
# or
ollama pull mistral
```

## 4) Stable Diffusion option A (recommended)
Run AUTOMATIC1111 WebUI with API enabled:

```bash
./webui.sh --api
```

Expected endpoint:
`http://127.0.0.1:7860/sdapi/v1/txt2img`

## 5) TTS
- Recommended: install Piper and place model at `models/en_US-lessac-medium.onnx`
- Fallback: install espeak

```bash
sudo apt-get install -y espeak
```

## 6) Project dependencies

```bash
git clone <your-repo-url> ai-video-generator
cd ai-video-generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running the System

### Start backend

```bash
cd backend
python main.py
```

Backend URL: `http://localhost:8000`

### Start frontend

```bash
# from repo root
python -m http.server 5500
```

Frontend URL: `http://localhost:5500/frontend/`

---

## Web usage

1. Enter prompt (example: *Create a 30 minute documentary about the fall of the Roman Empire.*)
2. Select minutes (up to 30)
3. Click **Generate Video**
4. Wait for progress completion
5. Download MP4

---

## CLI usage

```bash
python backend/scripts/run_pipeline.py \
  --prompt "Create a 10 minute educational video about black holes" \
  --minutes 10 \
  --scene-seconds 8
```

Outputs:
- Images: `output/images/scene001.png`
- Audio: `output/audio/scene001.wav`
- Video: `output/video/<job_id>_final.mp4`
- Subtitles: `output/subtitles/<job_id>.srt`

---

## GitHub Pages (frontend deployment)

1. Push repository to GitHub
2. Open **Settings → Pages**
3. Deploy from branch folder `frontend/`
4. If backend is remote, set:
   - `localStorage.apiBase = 'https://your-backend-url'`

---

## GitHub Actions rendering

Workflow file: `.github/workflows/render.yml`

- Trigger manually with `workflow_dispatch`
- Inputs: prompt, minutes, scene_seconds
- Installs ffmpeg + dependencies
- Runs CLI pipeline
- Uploads generated MP4/SRT/thumbnail as artifact

> CPU-only runners are slow for 30-minute jobs; consider longer scene lengths (10s) for fewer scenes.

---

## Suggested prompts

- Create a 30 minute documentary about the fall of the Roman Empire.
- Create a 25 minute narrated explainer about black holes and event horizons.
- Create a 20 minute educational video about the history of vaccines.
- Create a 15 minute storytelling video about Ada Lovelace.

---

## Test commands

```bash
python -m py_compile backend/*.py backend/scripts/run_pipeline.py
python backend/scripts/run_pipeline.py --prompt "Create a 1 minute explainer about tectonic plates" --minutes 1 --scene-seconds 10
```

---

## Notes for 30-minute generation

At 8s scene duration:
- 30 minutes = 1800 seconds
- ~225 scenes

For faster generation on low-resource machines:
- increase scene length to 10s+
- pre-download models
- use GPU for Stable Diffusion when possible
