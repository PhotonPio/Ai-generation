#!/usr/bin/env bash
set -e

echo ""
echo "========================================="
echo "  AI Video Generator — Local Launcher"
echo "========================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 is not installed."
  echo "   Install it from https://python.org then re-run this script."
  exit 1
fi

# Create venv if missing
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "📦 Installing dependencies..."
pip install -q -r requirements.txt

# Check for ffmpeg
if ! command -v ffmpeg &>/dev/null; then
  echo ""
  echo "⚠️  ffmpeg not found. Video rendering will fail."
  echo "   Mac:   brew install ffmpeg"
  echo "   Linux: sudo apt install ffmpeg"
  echo ""
fi

# Check for Ollama
if ! command -v ollama &>/dev/null; then
  echo ""
  echo "⚠️  Ollama not found. Script generation will use fallback mode."
  echo "   Install from https://ollama.com then run: ollama pull llama3:8b"
  echo ""
else
  # Start Ollama in background if not running
  if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo "🦙 Starting Ollama in background..."
    ollama serve &>/dev/null &
    sleep 2
  fi
fi

echo ""
echo "🚀 Starting backend on http://localhost:8000 ..."
echo "🌐 Opening browser..."
echo ""
echo "   Press Ctrl+C to stop."
echo ""

# Open browser after a short delay
(sleep 2 && python3 -c "import webbrowser; webbrowser.open('http://localhost:8000')" ) &

cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
