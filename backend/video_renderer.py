from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scene_builder import Scene


class VideoRenderer:
    """Renders all video artifacts for a single job inside its project_dir."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.segment_dir = project_dir / "segments"

    def render_segments(self, scenes: list[Scene], images: list[Path], audios: list[Path]) -> list[Path]:
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        segments: list[Path] = []

        for scene, image_path, audio_path in zip(scenes, images, audios):
            seg_path = self.segment_dir / f"scene{scene.index:03d}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(image_path),
                "-i", str(audio_path),
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-vf", "scale=1280:720,format=yuv420p",
                str(seg_path),
            ]
            subprocess.check_call(cmd)
            segments.append(seg_path)

        return segments

    def concatenate(self, segments: list[Path], final_output: Path) -> Path:
        final_output.parent.mkdir(parents=True, exist_ok=True)
        file_list = self.segment_dir / "concat.txt"
        file_list.write_text("\n".join([f"file '{seg.name}'" for seg in segments]), encoding="utf-8")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(file_list),
            "-c", "copy",
            str(final_output),
        ]
        subprocess.check_call(cmd, cwd=self.segment_dir)
        return final_output

    def create_subtitles(self, scenes: list[Scene], subtitle_path: Path) -> Path:
        subtitle_path.parent.mkdir(parents=True, exist_ok=True)
        current = 0.0
        lines: list[str] = []
        for idx, scene in enumerate(scenes, start=1):
            start = self._fmt_srt_time(current)
            end = self._fmt_srt_time(current + scene.estimated_duration)
            lines.extend([str(idx), f"{start} --> {end}", scene.narration, ""])
            current += scene.estimated_duration
        subtitle_path.write_text("\n".join(lines), encoding="utf-8")
        return subtitle_path

    def burn_subtitles(self, video_path: Path, subtitle_path: Path, output_path: Path) -> Path:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"subtitles={subtitle_path}",
            "-c:a", "copy",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def generate_background_music(self, total_seconds: int, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=220:duration={total_seconds}",
            "-filter:a", "volume=0.06",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def mix_music(self, narration_video: Path, music_audio: Path, output_path: Path) -> Path:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(narration_video),
            "-i", str(music_audio),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.18[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:v", "copy",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def create_thumbnail(self, video_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-ss", "00:00:05", "-vframes", "1", str(output_path)]
        subprocess.check_call(cmd)
        return output_path

    def write_manifest(self, payload: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fmt_srt_time(self, seconds: float) -> str:
        millis = int((seconds - int(seconds)) * 1000)
        seconds_int = int(seconds)
        hrs = seconds_int // 3600
        mins = (seconds_int % 3600) // 60
        secs = seconds_int % 60
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"
