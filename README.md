# AI Video Generator

Generate narrated AI videos from a text prompt — fully local, no subscriptions.

## ⚡ Quick Start (3 steps)

**Step 1 — Install prerequisites (one time only)**

| Tool | Required | Install |
|------|----------|---------|
| Python 3.10+ | ✅ Yes | [python.org](https://python.org) |
| ffmpeg | ✅ Yes | `brew install ffmpeg` / `sudo apt install ffmpeg` / [ffmpeg.org](https://ffmpeg.org) |
| Ollama + llama3 | Recommended | [ollama.com](https://ollama.com) → then run `ollama pull llama3:8b` |

**Step 2 — Clone the repo**
```bash
git clone https://github.com/PhotonPio/Ai-generation.git
cd Ai-generation
```

**Step 3 — Launch**

Mac/Linux:
```bash
chmod +x start.sh
./start.sh
```

Windows: double-click `start.bat`

Your browser will open automatically at **http://localhost:8000**

---

## How It Works

1. Enter a topic and click **Generate Script**
2. Review and edit the generated scenes
3. Approve → images are generated for each scene
4. Approve → narration audio is generated
5. Approve → final MP4 video is rendered and available to download

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Backend not running" banner | Run `./start.sh` first |
| Script generation returns generic fallback | Install Ollama: `ollama pull llama3:8b` |
| Images are grey placeholder boxes | Set `PEXELS_API_KEY` or `PIXABAY_API_KEY` in a `.env` file, or install A1111 |
| Video render fails | Install ffmpeg |
| Port 8000 already in use | `lsof -ti:8000 \| xargs kill` then restart |

## Optional: Custom image sources

Create a `.env` file in the project root:
```env
PEXELS_API_KEY=your_key_here
PIXABAY_API_KEY=your_key_here
UNSPLASH_ACCESS_KEY=your_key_here
```

Free API keys: [pexels.com/api](https://pexels.com/api) · [pixabay.com/api/docs](https://pixabay.com/api/docs)
