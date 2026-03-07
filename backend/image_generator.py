from __future__ import annotations

import io
import os
import random
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from scene_builder import Scene

UPLOADS_DIR = Path(__file__).resolve().parent / "assets" / "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ImageGenerator:
    def __init__(self) -> None:
        self.pexels_key = os.getenv("PEXELS_API_KEY", "")
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "")
        self.unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY", "")

    def generate_scene_image(self, scene: Scene, output_path: Path, width: int = 1280, height: int = 720) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._use_uploaded_image(scene, output_path, width, height):
            return output_path

        if self.pexels_key and self._fetch_pexels(scene.visual_prompt, output_path, width, height):
            return output_path

        if self.pixabay_key and self._fetch_pixabay(scene.visual_prompt, output_path, width, height):
            return output_path

        if self.unsplash_key and self._fetch_unsplash(scene.visual_prompt, output_path, width, height):
            return output_path

        if self._fetch_picsum(output_path, width, height):
            return output_path

        self._generate_fallback_image(scene, output_path, width, height)
        return output_path

    def _use_uploaded_image(self, scene: Scene, output_path: Path, width: int, height: int) -> bool:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        uploads = sorted(
            f for f in UPLOADS_DIR.iterdir() if f.suffix.lower() in ALLOWED_EXTENSIONS
        )
        if not uploads:
            return False
        chosen = uploads[(scene.index - 1) % len(uploads)]
        try:
            img = Image.open(chosen).convert("RGB")
            img = img.resize((width, height), Image.LANCZOS)
            img.save(output_path)
            return True
        except Exception:
            return False

    def _fetch_pexels(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        query = self._extract_keywords(prompt)
        try:
            response = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": self.pexels_key},
                params={"query": query, "per_page": 5, "orientation": "landscape"},
                timeout=15,
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
            if not photos:
                return False
            photo = random.choice(photos)
            url = photo["src"].get("large2x") or photo["src"]["original"]
            return self._download_and_resize(url, output_path, width, height)
        except Exception:
            return False

    def _fetch_pixabay(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        query = self._extract_keywords(prompt)
        try:
            response = requests.get(
                "https://pixabay.com/api/",
                params={
                    "key": self.pixabay_key,
                    "q": query,
                    "image_type": "photo",
                    "orientation": "horizontal",
                    "per_page": 5,
                    "min_width": 1280,
                },
                timeout=15,
            )
            response.raise_for_status()
            hits = response.json().get("hits", [])
            if not hits:
                return False
            hit = random.choice(hits)
            url = hit.get("largeImageURL") or hit["webformatURL"]
            return self._download_and_resize(url, output_path, width, height)
        except Exception:
            return False

    def _fetch_unsplash(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        query = self._extract_keywords(prompt)
        try:
            response = requests.get(
                "https://api.unsplash.com/search/photos",
                headers={"Authorization": f"Client-ID {self.unsplash_key}"},
                params={"query": query, "per_page": 5, "orientation": "landscape"},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                return False
            photo = random.choice(results)
            url = photo["urls"].get("regular") or photo["urls"]["full"]
            return self._download_and_resize(url, output_path, width, height)
        except Exception:
            return False

    def _fetch_picsum(self, output_path: Path, width: int, height: int) -> bool:
        url = f"https://picsum.photos/{width}/{height}"
        return self._download_and_resize(url, output_path, width, height)

    def _download_and_resize(self, url: str, output_path: Path, width: int, height: int) -> bool:
        try:
            response = requests.get(
                url,
                timeout=20,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content)).convert("RGB")
            img = img.resize((width, height), Image.LANCZOS)
            img.save(output_path)
            return True
        except Exception:
            return False

    def _extract_keywords(self, prompt: str) -> str:
        return " ".join(prompt.split()[:10])

    def _generate_fallback_image(self, scene: Scene, output_path: Path, width: int, height: int) -> None:
        image = Image.new("RGB", (width, height), color=(24, 24, 28))
        draw = ImageDraw.Draw(image)
        text = f"Scene {scene.index}\n{scene.visual_prompt[:180]}"
        draw.text((50, 80), text, fill=(220, 220, 220))
        image.save(output_path)
