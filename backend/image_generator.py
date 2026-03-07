from __future__ import annotations

import base64
import io
import json
import subprocess
from pathlib import Path

import requests
from PIL import Image, ImageDraw

from scene_builder import Scene


class ImageGenerator:
    def __init__(self, sd_api_url: str = "http://127.0.0.1:7860") -> None:
        self.sd_api_url = sd_api_url.rstrip("/")

    def generate_scene_image(self, scene: Scene, output_path: Path, width: int = 1280, height: int = 720) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._generate_via_sd_api(scene.visual_prompt, output_path, width, height):
            return output_path

        if self._generate_via_diffusers_script(scene.visual_prompt, output_path, width, height):
            return output_path

        self._generate_fallback_image(scene, output_path, width, height)
        return output_path

    def _generate_via_sd_api(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        payload = {
            "prompt": prompt,
            "steps": 28,
            "cfg_scale": 7,
            "width": width,
            "height": height,
            "sampler_name": "DPM++ 2M",
        }
        try:
            response = requests.post(f"{self.sd_api_url}/sdapi/v1/txt2img", json=payload, timeout=180)
            response.raise_for_status()
            data = response.json()
            encoded = data.get("images", [""])[0]
            if not encoded:
                return False
            image_bytes = base64.b64decode(encoded.split(",")[0])
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image.save(output_path)
            return True
        except requests.RequestException:
            return False

    def _generate_via_diffusers_script(self, prompt: str, output_path: Path, width: int, height: int) -> bool:
        safe_prompt = json.dumps(prompt)
        script = (
            "from diffusers import StableDiffusionPipeline\n"
            "pipe=StableDiffusionPipeline.from_pretrained('runwayml/stable-diffusion-v1-5')\n"
            "pipe=pipe.to('cpu')\n"
            f"image=pipe({safe_prompt},height={height},width={width},num_inference_steps=20).images[0]\n"
            f"image.save(r'{output_path}')\n"
        )
        try:
            subprocess.check_output(["python", "-c", script], text=True)
            return output_path.exists()
        except subprocess.CalledProcessError:
            return False

    def _generate_fallback_image(self, scene: Scene, output_path: Path, width: int, height: int) -> None:
        image = Image.new("RGB", (width, height), color=(24, 24, 28))
        draw = ImageDraw.Draw(image)
        text = f"Scene {scene.index}\n{scene.visual_prompt[:180]}"
        draw.text((50, 80), text, fill=(220, 220, 220))
        image.save(output_path)
