from __future__ import annotations

"""Image generation module with provider fallbacks, caching, and CLIP scoring."""

import hashlib
import io
import logging
import os
import random
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PIL import Image, ImageDraw
try:
    from tqdm import tqdm
except Exception:  # pragma: no cover - fallback when tqdm is unavailable
    def tqdm(it, **_):
        return it

try:
    from .config import get_settings
    from .scene_builder import Scene
except ImportError:  # pragma: no cover
    from config import get_settings
    from scene_builder import Scene

UPLOADS_DIR = Path(__file__).resolve().parent / "assets" / "uploads"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ImageGenerator:
    """Generate scene images via uploads, stock APIs, A1111, or fallback placeholder."""

    def __init__(self, job_id: str = "local", *, clear_cache: bool = False, prefer_uploaded_images: bool = False, scene_media_mode: str | None = None) -> None:
        settings = get_settings()
        self.job_id = job_id
        self.settings = settings
        self.prefer_uploaded_images = prefer_uploaded_images
        self.scene_media_mode = (scene_media_mode or settings.scene_media_mode or "auto").lower()

        self.pexels_key = os.getenv("PEXELS_API_KEY", "")
        self.pixabay_key = os.getenv("PIXABAY_API_KEY", "")
        self.unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY", "")
        self.a1111_url = settings.a1111_url

        self.cache_dir = settings.projects_dir / job_id / "cache" / "images"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if clear_cache or settings.clear_cache_default:
            for file in self.cache_dir.glob("*.png"):
                file.unlink(missing_ok=True)

        # Semaphore limits concurrent heavy generation calls.
        self.sd_semaphore = threading.Semaphore(2)

        self._clip_model = None
        self._clip_processor = None

        self.logger = logging.getLogger(__name__)

    def _cache_key(self, prompt: str, width: int, height: int, seed: int | None, steps: int) -> str:
        """Build deterministic cache key for generated image parameters."""

        payload = f"{prompt}|{width}|{height}|{seed}|{steps}|{self.a1111_url}|{self.settings.sd_model}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _copy_from_cache(self, cache_key: str, output_path: Path) -> bool:
        """Copy cached image to destination if present."""

        cache_file = self.cache_dir / f"{cache_key}.png"
        if not cache_file.exists():
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(cache_file.read_bytes())
        return True

    def _save_cache(self, cache_key: str, output_path: Path) -> None:
        """Persist generated image to cache."""

        cache_file = self.cache_dir / f"{cache_key}.png"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(output_path.read_bytes())

    def _init_clip(self) -> None:
        """Lazy-load CLIP model only when scoring is enabled."""

        if self._clip_model is not None and self._clip_processor is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        self._clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self._clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

    def _clip_score(self, prompt: str, image_path: Path) -> float:
        """Compute CLIP similarity score for prompt/image alignment."""

        if not self.settings.enable_clip_scoring:
            return 1.0

        try:
            self._init_clip()
            image = Image.open(image_path).convert("RGB")
            inputs = self._clip_processor(text=[prompt], images=image, return_tensors="pt", padding=True)
            outputs = self._clip_model(**inputs)
            logits = outputs.logits_per_image
            return float(logits.softmax(dim=1).max().item())
        except Exception:
            return 1.0

    def generate_scene_image(
        self,
        scene: Scene,
        output_path: Path,
        width: int = 1280,
        height: int = 720,
        *,
        steps: int | None = None,
        seed: int | None = None,
    ) -> Path:
        """Generate one scene image with cache + fallback chain."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        effective_steps = int(steps or self.settings.sd_steps)
        cache_key = self._cache_key(scene.visual_prompt, width, height, seed, effective_steps)

        if self._copy_from_cache(cache_key, output_path):
            return output_path

        retries = max(0, self.settings.clip_retries)
        scene_media_mode = self.scene_media_mode
        video_candidate_path = output_path.with_suffix(".mp4")
        for attempt in range(retries + 1):
            used_video = False
            created = (
                (self.prefer_uploaded_images and self._use_uploaded_image(scene, output_path, width, height))
                or (
                    self.pexels_key
                    and scene_media_mode in ("auto", "video")
                    and self._fetch_pexels_video(scene.visual_prompt, video_candidate_path, width, height)
                    and self._extract_frame_from_video(video_candidate_path, output_path)
                )
                or self._fetch_a1111(scene.visual_prompt, output_path, width, height, effective_steps, seed)
                or (
                    self.pexels_key
                    and scene_media_mode in ("auto", "photo")
                    and self._fetch_pexels(scene.visual_prompt, output_path, width, height)
                )
                or (self.pixabay_key and self._fetch_pixabay(scene.visual_prompt, output_path, width, height))
                or (self.unsplash_key and self._fetch_unsplash(scene.visual_prompt, output_path, width, height))
                or self._fetch_picsum(output_path, width, height)
            )
            if created and video_candidate_path.exists():
                scene.video_path = video_candidate_path
                used_video = True
            else:
                scene.video_path = None
            if not created:
                self._generate_fallback_image(scene, output_path, width, height)
                scene.video_path = None
            if not used_video:
                video_candidate_path.unlink(missing_ok=True)

            if self._clip_score(scene.visual_prompt, output_path) >= self.settings.clip_threshold:
                break
            if attempt == retries:
                break

        self._save_cache(cache_key, output_path)
        return output_path

    def generate_images_parallel(
        self,
        scenes: list[Scene],
        output_dir: Path,
        *,
        max_workers: int = 4,
        steps: int | None = None,
        seed: int | None = None,
    ) -> list[Path]:
        """Generate scene images in parallel with bounded worker pool."""

        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: list[Path] = [output_dir / f"scene{s.index:03d}.png" for s in scenes]

        def _task(scene: Scene, path: Path) -> Path:
            return self.generate_scene_image(scene, path, steps=steps, seed=seed)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_task, scene, path) for scene, path in zip(scenes, outputs)]
            for scene, future in tqdm(list(zip(scenes, futures)), desc="Images", disable=False):
                try:
                    future.result()
                except Exception as exc:
                    self.logger.error("Scene %s image generation failed: %s", scene.index, exc)

        return outputs

    def generate_thumbnail_variants(
        self,
        scene_prompt: str,
        output_dir: Path,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> list[Path]:
        """Generate three thumbnail prompt variants and return output paths."""

        variants = [
            ("cinematic", "cinematic thumbnail, high contrast, title-safe composition"),
            ("minimalist", "minimalist thumbnail, clean shapes, bold focal object"),
            ("vibrant", "vibrant thumbnail, saturated colors, energetic mood"),
        ]
        output_dir.mkdir(parents=True, exist_ok=True)

        outputs: list[Path] = []
        fake_scene = Scene(index=1, narration="", visual_prompt=scene_prompt, estimated_duration=8.0)

        for idx, (name, suffix) in enumerate(variants, start=1):
            path = output_dir / f"thumb_{idx:02d}_{name}.png"
            fake_scene.visual_prompt = f"{scene_prompt}, {suffix}"
            self.generate_scene_image(fake_scene, path, width=width, height=height)
            outputs.append(path)

        return outputs

    def _use_uploaded_image(self, scene: Scene, output_path: Path, width: int, height: int) -> bool:
        """Use user-uploaded images in a rotating sequence if available."""

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        uploads = sorted(f for f in UPLOADS_DIR.iterdir() if f.suffix.lower() in ALLOWED_EXTENSIONS)
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

    def _fetch_a1111(
        self,
        prompt: str,
        output_path: Path,
        width: int,
        height: int,
        steps: int,
        seed: int | None,
    ) -> bool:
        """Fetch image from AUTOMATIC1111 txt2img API."""

        payload = {
            "prompt": prompt,
            "steps": steps,
            "width": width,
            "height": height,
            "seed": int(seed) if seed is not None else -1,
        }
        try:
            with self.sd_semaphore:
                response = requests.post(self.a1111_url, json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            images = data.get("images", [])
            if not images:
                return False
            import base64

            raw = base64.b64decode(images[0])
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            img.save(output_path)
            return True
        except Exception:
            return False

    def _extract_frame_from_video(self, video_path: Path, output_path: Path) -> bool:
        """Extract a representative still frame from a local video clip."""

        try:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                str(output_path),
            ]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output_path.exists()
        except Exception:
            return False

    def _fetch_pexels_video(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        """Fetch a landscape mp4 video from Pexels and save to output path."""

        query = self._extract_keywords(prompt)
        try:
            response = requests.get(
                "https://api.pexels.com/v1/videos/search",
                headers={"Authorization": self.pexels_key},
                params={"query": query, "per_page": 5, "orientation": "landscape", "size": "medium"},
                timeout=20,
            )
            response.raise_for_status()
            videos = response.json().get("videos", [])
            if not videos:
                return False

            preferred_quality = str(getattr(self.settings, "pexels_video_quality", "hd")).lower()
            preferred_file = None
            fallback_file = None

            for video in videos:
                for video_file in video.get("video_files", []):
                    if video_file.get("file_type") != "video/mp4":
                        continue
                    if fallback_file is None:
                        fallback_file = video_file
                    if str(video_file.get("quality", "")).lower() == preferred_quality:
                        preferred_file = video_file
                        break
                if preferred_file is not None:
                    break

            selected = preferred_file or fallback_file
            if not selected or not selected.get("link"):
                return False

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(selected["link"], stream=True, timeout=60) as stream_response:
                stream_response.raise_for_status()
                with output_path.open("wb") as handle:
                    for chunk in stream_response.iter_content(chunk_size=8192):
                        if chunk:
                            handle.write(chunk)
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception:
            return False

    def _fetch_pexels(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        """Fetch image from Pexels."""

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
        """Fetch image from Pixabay."""

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
        """Fetch image from Unsplash."""

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
        """Fetch random placeholder image from Picsum."""

        url = f"https://picsum.photos/{width}/{height}"
        return self._download_and_resize(url, output_path, width, height)

    def _download_and_resize(self, url: str, output_path: Path, width: int, height: int) -> bool:
        """Download remote image and fit into target frame."""

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
        """Extract compact keyword query from freeform prompt."""

        return " ".join(prompt.split()[:12])

    def _generate_fallback_image(self, scene: Scene, output_path: Path, width: int, height: int) -> None:
        """Generate deterministic fallback image when all providers fail."""

        image = Image.new("RGB", (width, height), color=(24, 24, 28))
        draw = ImageDraw.Draw(image)
        text = f"Scene {scene.index}\n{scene.visual_prompt[:180]}"
        draw.text((50, 80), text, fill=(220, 220, 220))
        image.save(output_path)
