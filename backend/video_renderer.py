from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

from scene_builder import Scene


class VideoRenderer:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.segment_dir = output_root / "segments"
        self.video_dir = output_root / "video"
        self.subtitles_dir = output_root / "subtitles"
        self.thumbnail_dir = output_root / "thumbnails"
        self.music_dir = output_root / "music"
        self.music_asset_dirs = [
            Path(__file__).resolve().parent / "assets" / "music_loops",
            Path(__file__).resolve().parent.parent / "assets" / "music_loops",
        ]

    def render_segments(self, scenes: list[Scene], images: list[Path], audios: list[Path]) -> list[Path]:
        self.segment_dir.mkdir(parents=True, exist_ok=True)
        segments: list[Path] = []

        for scene, image_path, audio_path in zip(scenes, images, audios):
            seg_path = self.segment_dir / f"scene{scene.index:03d}.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-i",
                str(audio_path),
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                "-vf",
                "scale=1280:720,format=yuv420p",
                str(seg_path),
            ]
            subprocess.check_call(cmd)
            segments.append(seg_path)

        return segments

    def concatenate(self, segments: list[Path], final_output: Path) -> Path:
        self.video_dir.mkdir(parents=True, exist_ok=True)
        file_list = self.segment_dir / "concat.txt"
        file_list.write_text(
            "\n".join([f"file '{seg.resolve().as_posix()}'" for seg in segments]),
            encoding="utf-8",
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(file_list),
            "-c",
            "copy",
            str(final_output),
        ]
        subprocess.check_call(cmd)
        return final_output

    def create_subtitles(self, scenes: list[Scene], subtitle_path: Path) -> Path:
        subtitle_path.parent.mkdir(parents=True, exist_ok=True)
        current = 0.0
        lines: list[str] = []
        for idx, scene in enumerate(scenes, start=1):
            start = self._fmt_srt_time(current)
            duration = max(float(scene.estimated_duration), 0.0)
            end = self._fmt_srt_time(current + duration)
            text = (getattr(scene, "narration_text", None) or scene.narration).strip()
            lines.extend([str(idx), f"{start} --> {end}", text, ""])
            current += duration
        subtitle_path.write_text("\n".join(lines), encoding="utf-8")
        return subtitle_path

    def burn_subtitles(self, video_path: Path, subtitle_path: Path, output_path: Path) -> Path:
        escaped_subtitle_path = subtitle_path.resolve().as_posix().replace(":", "\\:").replace("'", "\\'")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"subtitles='{escaped_subtitle_path}'",
            "-c:a",
            "copy",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def generate_background_music(self, total_seconds: int, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if total_seconds <= 0:
            raise ValueError("total_seconds must be positive")

        available_loops = self._find_music_loops()
        if available_loops:
            loop_path = random.choice(available_loops)
            cmd = [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(loop_path),
                "-t",
                str(total_seconds),
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anoisesrc=color=pink:amplitude=0.02",
                "-t",
                str(total_seconds),
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]

        subprocess.check_call(cmd)
        return output_path

    def mix_music(self, narration_video: Path, music_audio: Path, output_path: Path) -> Path:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(narration_video),
            "-i",
            str(music_audio),
            "-filter_complex",
            "[1:a]volume=0.15[music];[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def create_thumbnail(self, video_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            "00:00:05",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            str(output_path),
        ]
        subprocess.check_call(cmd)
        return output_path

    def write_manifest(self, payload: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fmt_srt_time(self, seconds: float) -> str:
        millis = int(round((seconds - int(seconds)) * 1000))
        seconds_int = int(seconds)
        if millis == 1000:
            seconds_int += 1
            millis = 0
        hrs = seconds_int // 3600
        mins = (seconds_int % 3600) // 60
        secs = seconds_int % 60
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

    def _find_music_loops(self) -> list[Path]:
        loops: list[Path] = []
        for base_dir in self.music_asset_dirs:
            if not base_dir.exists():
                continue
            loops.extend(sorted(base_dir.glob("*.wav")))
        return loops
