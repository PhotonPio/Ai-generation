from __future__ import annotations

"""Narration generation utilities with Piper-first multilingual support."""

import asyncio
import hashlib
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from tqdm import tqdm

try:
    from .config import get_settings
    from .scene_builder import Scene
except ImportError:  # pragma: no cover
    from config import get_settings
    from scene_builder import Scene

# Backward-compatible UI voice presets mapped to Piper model ids.
VOICE_PRESETS: dict[str, dict[str, str]] = {
    "narrator": {
        "label": "Narrator (American Male)",
        "edge": "en-US-GuyNeural",
        "piper": "en_US-lessac-medium",
    },
    "storyteller": {
        "label": "Storyteller (British Male)",
        "edge": "en-GB-RyanNeural",
        "piper": "en_GB-alan-medium",
    },
    "documentary": {
        "label": "Documentary (American Female)",
        "edge": "en-US-AriaNeural",
        "piper": "en_US-lessac-medium",
    },
    "female_warm": {
        "label": "Female Warm (American)",
        "edge": "en-US-JennyNeural",
        "piper": "en_US-lessac-medium",
    },
    "british_female": {
        "label": "British Female",
        "edge": "en-GB-SoniaNeural",
        "piper": "en_GB-alan-medium",
    },
    "australian": {
        "label": "Australian Male",
        "edge": "en-AU-WilliamNeural",
        "piper": "en_US-lessac-medium",
    },
}

LANG_TO_VOICE: dict[str, str] = {
    "en": "en_US-lessac-medium",
    "de": "de_DE-thorsten-medium",
    "fr": "fr_FR-upmc-medium",
    "es": "es_ES-sharvard-medium",
    "it": "it_IT-riccardo-x_low",
}

PIPER_RELEASE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEFAULT_VOICE = "narrator"


class VoiceGenerator:
    """Generate narration tracks with Piper/Edge/espeak fallback and caching."""

    def __init__(
        self,
        job_id: str,
        voice: str = DEFAULT_VOICE,
        language: str = "en",
        *,
        clear_cache: bool = False,
    ) -> None:
        settings = get_settings()
        self.job_id = job_id
        self.settings = settings
        self.language = language or "en"

        # Voice may be a preset id or explicit piper model code.
        self.voice = voice.strip() if voice else ""

        self.models_dir = Path(__file__).resolve().parent / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)

        self.cache_dir = settings.projects_dir / job_id / "cache" / "audio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if clear_cache or settings.clear_cache_default:
            for file in self.cache_dir.glob("*.wav"):
                file.unlink(missing_ok=True)

    def _resolve_voice_model(self) -> str:
        """Resolve requested voice preset to a concrete Piper model id."""

        if not self.voice:
            return LANG_TO_VOICE.get(self.language[:2], self.settings.default_voice)
        if self.voice in VOICE_PRESETS:
            return VOICE_PRESETS[self.voice]["piper"]
        if "_" in self.voice and "-" in self.voice:
            return self.voice
        return LANG_TO_VOICE.get(self.language[:2], self.settings.default_voice)

    def _model_path(self, model_id: str) -> Path:
        """Return local model file path for a Piper voice id."""

        return self.models_dir / f"{model_id}.onnx"

    def _download_voice_if_missing(self, model_id: str) -> Path:
        """Download Piper ONNX model when not already present."""

        target = self._model_path(model_id)
        if target.exists():
            return target

        url = f"{PIPER_RELEASE_BASE}/{model_id}/{model_id}.onnx"
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()

        total = int(response.headers.get("content-length", 0))
        with target.open("wb") as handle:
            for chunk in tqdm(response.iter_content(chunk_size=8192), total=max(total // 8192, 1), disable=True):
                if chunk:
                    handle.write(chunk)
        return target

    def _cache_key(self, text: str, voice_model: str) -> str:
        """Build deterministic audio cache key."""

        payload = f"{voice_model}|{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _copy_from_cache(self, cache_key: str, output_path: Path) -> bool:
        """Restore cached wav if present."""

        source = self.cache_dir / f"{cache_key}.wav"
        if not source.exists():
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output_path)
        return True

    def _save_cache(self, cache_key: str, output_path: Path) -> None:
        """Store wav artifact in cache."""

        target = self.cache_dir / f"{cache_key}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_path, target)

    def generate_scene_audio(self, scene: Scene, output_path: Path) -> Path:
        """Generate narration for one scene."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = scene.narration.strip()
        voice_model = self._resolve_voice_model()
        cache_key = self._cache_key(text, voice_model)

        if self._copy_from_cache(cache_key, output_path):
            return output_path

        if self._generate_with_piper(text, output_path, voice_model):
            self._save_cache(cache_key, output_path)
            return output_path

        if self._generate_with_edge_tts(text, output_path):
            self._save_cache(cache_key, output_path)
            return output_path

        if self._generate_with_espeak(text, output_path):
            self._save_cache(cache_key, output_path)
            return output_path

        if self._generate_silent_fallback(text, output_path):
            self._save_cache(cache_key, output_path)
            return output_path

        raise RuntimeError("All free TTS backends failed for scene audio.")

    def generate_audio_parallel(self, scenes: list[Scene], output_dir: Path, *, max_workers: int = 4) -> list[Path]:
        """Generate all scene audio clips in parallel."""

        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = [output_dir / f"scene{s.index:03d}.wav" for s in scenes]

        def _task(scene: Scene, path: Path) -> Path:
            return self.generate_scene_audio(scene, path)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_task, scene, path) for scene, path in zip(scenes, outputs)]
            for future in tqdm(futures, desc="Audio", disable=True):
                future.result()
        return outputs

    def transcribe_audio(self, input_audio: Path) -> str:
        """Transcribe external audio via open-source Whisper model."""

        import whisper

        model = whisper.load_model("base")
        result = model.transcribe(str(input_audio))
        return str(result.get("text", "")).strip()

    def _generate_with_piper(self, text: str, output_path: Path, voice_model: str) -> bool:
        """Generate audio with Piper CLI using requested voice model."""

        try:
            model_path = self._download_voice_if_missing(voice_model)
        except Exception:
            model_path = self._model_path(voice_model)

        if not model_path.exists():
            return False

        cmd = [
            "bash",
            "-lc",
            f"echo {self._shell_quote(text)} | piper --model {model_path} --output_file {output_path}",
        ]
        try:
            subprocess.check_output(cmd, text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.CalledProcessError:
            return False

    def _generate_with_edge_tts(self, text: str, output_path: Path) -> bool:
        """Generate speech with free edge-tts as secondary fallback."""

        preset = VOICE_PRESETS.get(self.voice, VOICE_PRESETS[DEFAULT_VOICE])
        edge_voice = preset["edge"]
        try:
            import edge_tts

            async def _run() -> None:
                communicate = edge_tts.Communicate(text, edge_voice)
                await communicate.save(str(mp3_path))

            mp3_path = output_path.with_suffix(".mp3")
            asyncio.run(_run())
            return self._mp3_to_wav(mp3_path, output_path)
        except Exception:
            return False

    def _generate_with_espeak(self, text: str, output_path: Path) -> bool:
        """Generate speech with espeak as final offline fallback."""

        try:
            subprocess.check_output(["espeak", "-w", str(output_path), text], text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False

    def _mp3_to_wav(self, mp3_path: Path, wav_path: Path) -> bool:
        """Convert temporary MP3 to WAV via ffmpeg."""

        try:
            subprocess.check_call(
                ["ffmpeg", "-y", "-i", str(mp3_path), str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            mp3_path.unlink(missing_ok=True)
            return wav_path.exists() and wav_path.stat().st_size > 0
        except Exception:
            return False

    def _shell_quote(self, text: str) -> str:
        """Escape single quotes for shell-safe echo piping."""

        return "'" + text.replace("'", "'\\''") + "'"

    def _generate_silent_fallback(self, text: str, output_path: Path) -> bool:
        """Generate short silent WAV as last-resort offline fallback."""

        # Approximate spoken duration from word count (~145 wpm).
        duration = max(1.0, len(text.split()) / 2.4)
        try:
            subprocess.check_call(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r=22050:cl=mono",
                    "-t",
                    str(duration),
                    str(output_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False
