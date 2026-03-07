from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from scene_builder import Scene

# ---------------------------------------------------------------------------
# Voice presets
# Each preset maps to a voice on each supported backend.
# edge-tts is free and requires no API key — it is always tried first.
# ElevenLabs / OpenAI TTS are used if their API keys are set in the environment.
# ---------------------------------------------------------------------------
VOICE_PRESETS: dict[str, dict[str, str]] = {
    "narrator": {
        "label": "Narrator (American Male)",
        "edge": "en-US-GuyNeural",
        "openai": "onyx",
        "elevenlabs": "29vD33N1CtxCmqQRPOHJ",  # Drew
    },
    "storyteller": {
        "label": "Storyteller (British Male)",
        "edge": "en-GB-RyanNeural",
        "openai": "fable",
        "elevenlabs": "VR6AewLTigWG4xSOukaG",  # Arnold
    },
    "documentary": {
        "label": "Documentary (American Female)",
        "edge": "en-US-AriaNeural",
        "openai": "alloy",
        "elevenlabs": "EXAVITQu4vr4xnSDxMaL",  # Bella
    },
    "female_warm": {
        "label": "Female Warm (American)",
        "edge": "en-US-JennyNeural",
        "openai": "nova",
        "elevenlabs": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    },
    "british_female": {
        "label": "British Female",
        "edge": "en-GB-SoniaNeural",
        "openai": "shimmer",
        "elevenlabs": "AZnzlk1XvdvUeBnXmlld",  # Domi
    },
    "australian": {
        "label": "Australian Male",
        "edge": "en-AU-WilliamNeural",
        "openai": "echo",
        "elevenlabs": "CYw3kZ02Hs0563khs1Fj",  # Dave
    },
}

DEFAULT_VOICE = "narrator"


class VoiceGenerator:
    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        piper_model_path: str = "models/en_US-lessac-medium.onnx",
    ) -> None:
        self.voice = voice if voice in VOICE_PRESETS else DEFAULT_VOICE
        self.piper_model_path = Path(piper_model_path)
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")

    def generate_scene_audio(self, scene: Scene, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        text = scene.narration

        if self.elevenlabs_key and self._generate_with_elevenlabs(text, output_path):
            return output_path

        if self.openai_key and self._generate_with_openai(text, output_path):
            return output_path

        if self._generate_with_edge_tts(text, output_path):
            return output_path

        if self.piper_model_path.exists() and self._generate_with_piper(text, output_path):
            return output_path

        if self._generate_with_espeak(text, output_path):
            return output_path

        raise RuntimeError("All TTS backends failed for scene audio.")

    # ── ElevenLabs ──────────────────────────────────────────────────────────

    def _generate_with_elevenlabs(self, text: str, output_path: Path) -> bool:
        voice_id = VOICE_PRESETS[self.voice]["elevenlabs"]
        try:
            import requests

            response = requests.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.elevenlabs_key,
                    "Content-Type": "application/json",
                },
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                timeout=60,
            )
            response.raise_for_status()
            mp3_path = output_path.with_suffix(".mp3")
            mp3_path.write_bytes(response.content)
            return self._mp3_to_wav(mp3_path, output_path)
        except Exception:
            return False

    # ── OpenAI TTS ───────────────────────────────────────────────────────────

    def _generate_with_openai(self, text: str, output_path: Path) -> bool:
        voice = VOICE_PRESETS[self.voice]["openai"]
        try:
            import requests

            response = requests.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "tts-1-hd", "input": text, "voice": voice},
                timeout=60,
            )
            response.raise_for_status()
            mp3_path = output_path.with_suffix(".mp3")
            mp3_path.write_bytes(response.content)
            return self._mp3_to_wav(mp3_path, output_path)
        except Exception:
            return False

    # ── edge-tts (free, Microsoft Neural voices) ────────────────────────────

    def _generate_with_edge_tts(self, text: str, output_path: Path) -> bool:
        edge_voice = VOICE_PRESETS[self.voice]["edge"]
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

    # ── Piper (local model fallback) ─────────────────────────────────────────

    def _generate_with_piper(self, text: str, output_path: Path) -> bool:
        cmd = [
            "bash",
            "-lc",
            f"echo {self._shell_quote(text)} | piper --model {self.piper_model_path} --output_file {output_path}",
        ]
        try:
            subprocess.check_output(cmd, text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except subprocess.CalledProcessError:
            return False

    # ── espeak (last-resort fallback) ────────────────────────────────────────

    def _generate_with_espeak(self, text: str, output_path: Path) -> bool:
        try:
            subprocess.check_output(["espeak", "-w", str(output_path), text], text=True)
            return output_path.exists() and output_path.stat().st_size > 0
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _mp3_to_wav(self, mp3_path: Path, wav_path: Path) -> bool:
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
        return "'" + text.replace("'", "'\\''") + "'"
