from __future__ import annotations

"""Video rendering pipeline using MoviePy effects and FFmpeg finalization."""

import json
import random
import shutil
import subprocess
from pathlib import Path

from moviepy import AudioFileClip, ImageClip, vfx

try:
    from .config import get_settings
    from .scene_builder import Scene
except ImportError:  # pragma: no cover
    from config import get_settings
    from scene_builder import Scene


THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "calm": ("space", "meditation", "history", "nature", "slow"),
    "epic": ("war", "battle", "empire", "cosmic", "adventure"),
    "uplifting": ("education", "innovation", "science", "future", "success"),
}


class VideoRenderer:
    """Renders all video artifacts for a single job inside its project directory."""

    def __init__(self, project_dir: Path) -> None:
        self.settings = get_settings()
        self.project_dir = project_dir
        self.segment_dir = project_dir / "segments"
        self.music_dir = Path(__file__).resolve().parent / "assets" / "music"

    def _ffmpeg_base_cmd(self) -> list[str]:
        """Return common ffmpeg args with reduced noise for cleaner logs."""

        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]

    def _apply_zoom_effect(self, clip: ImageClip, scene: Scene, transition_style: str) -> ImageClip:
        """Apply transition style-specific image motion effects."""

        style = (transition_style or self.settings.transition_style).lower()
        if style == "none":
            return clip

        # Add stronger zoom for longer sentences as a simple emphasis heuristic.
        long_sentence = max((len(sent.split()) for sent in scene.narration.split(".")), default=0) > 22
        zoom_factor = self.settings.kenburns_zoom_factor + (0.08 if long_sentence else 0.0)

        if style in {"kenburns", "fade"}:
            return clip.with_effects([vfx.Resize(lambda t: 1 + (zoom_factor - 1) * (t / max(scene.estimated_duration, 1.0)))])

        return clip

    def render_segments(
        self,
        scenes: list[Scene],
        images: list[Path],
        audios: list[Path],
        *,
        transition_style: str = "kenburns",
        transition_seconds: float | None = None,
    ) -> list[Path]:
        """Render one MP4 per scene with optional moviepy visual effects."""

        self.segment_dir.mkdir(parents=True, exist_ok=True)
        segments: list[Path] = []

        for scene, image_path, audio_path in zip(scenes, images, audios):
            seg_path = self.segment_dir / f"scene{scene.index:03d}.mp4"
            try:
                base = ImageClip(str(image_path)).with_duration(scene.estimated_duration)
                effected = self._apply_zoom_effect(base, scene, transition_style)
                with AudioFileClip(str(audio_path)) as audio_clip:
                    video = effected.with_audio(audio_clip).with_fps(24)
                    video.write_videofile(
                        str(seg_path),
                        codec="libx264",
                        audio_codec="aac",
                        fps=24,
                        preset="veryfast",
                        logger=None,
                    )
            except Exception:
                # FFmpeg fallback keeps backward compatibility on constrained systems.
                cmd = [
                    *self._ffmpeg_base_cmd(),
                    "-loop",
                    "1",
                    "-i",
                    str(image_path),
                    "-i",
                    str(audio_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
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
                subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            segments.append(seg_path)

        # Optional fade transitions are produced as an extra stitched intermediate.
        if transition_style == "fade" and len(segments) > 1:
            transition_seconds = transition_seconds or self.settings.transition_seconds
            faded_path = self.project_dir / "video_faded.mp4"
            self._stitch_with_fades(segments, faded_path, transition_seconds)
            return [faded_path]

        return segments

    def _stitch_with_fades(self, segments: list[Path], output_path: Path, fade_seconds: float) -> Path:
        """Create one clip with crossfade transitions via ffmpeg xfade chain."""

        if len(segments) == 1:
            shutil.copy2(segments[0], output_path)
            return output_path

        # Build a simple xfade filter graph for adjacent clips.
        inputs: list[str] = []
        for segment in segments:
            inputs.extend(["-i", str(segment)])

        offsets: list[float] = []
        elapsed = 0.0
        for segment in segments[:-1]:
            duration = self._probe_duration(segment)
            elapsed += max(0.1, duration - fade_seconds)
            offsets.append(elapsed)

        filter_parts: list[str] = []
        for idx in range(len(segments) - 1):
            left = f"[{idx}:v]" if idx == 0 else f"[v{idx}]"
            right = f"[{idx+1}:v]"
            out = f"[v{idx+1}]" if idx < len(segments) - 2 else "[vout]"
            filter_parts.append(
                f"{left}{right}xfade=transition=fade:duration={fade_seconds}:offset={offsets[idx]}{out}"
            )

        cmd = [
            *self._ffmpeg_base_cmd(),
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-an",
            str(output_path),
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path

    def _probe_duration(self, path: Path) -> float:
        """Read media duration in seconds using ffprobe."""

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        try:
            return float(out)
        except Exception:
            return 0.0

    def concatenate(self, segments: list[Path], final_output: Path) -> Path:
        """Concatenate segments with ffmpeg concat demuxer."""

        final_output.parent.mkdir(parents=True, exist_ok=True)
        file_list = self.segment_dir / "concat.txt"
        file_list.write_text("\n".join([f"file '{seg.name}'" for seg in segments]), encoding="utf-8")

        cmd = [
            *self._ffmpeg_base_cmd(),
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
        subprocess.check_call(cmd, cwd=self.segment_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return final_output

    def create_subtitles(self, scenes: list[Scene], subtitle_path: Path) -> Path:
        """Write SRT subtitles from scene narration and durations."""

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
        """Burn subtitles into final video; fallback to copy if libass is missing."""

        cmd = [
            *self._ffmpeg_base_cmd(),
            "-i",
            str(video_path),
            "-vf",
            f"subtitles={subtitle_path}",
            "-c:a",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Graceful fallback: keep render alive even when subtitle burn fails.
            subprocess.check_call(
                [*self._ffmpeg_base_cmd(), "-i", str(video_path), "-c", "copy", str(output_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return output_path

    def choose_music_track(self, script_text: str) -> Path | None:
        """Pick a background track matching coarse script theme keywords."""

        self.music_dir.mkdir(parents=True, exist_ok=True)
        tracks = sorted([p for p in self.music_dir.glob("*.mp3")])
        if not tracks:
            return None

        first_sentence = script_text.split(".")[0].lower()
        bucket = "calm"
        for theme, keywords in THEME_KEYWORDS.items():
            if any(keyword in first_sentence for keyword in keywords):
                bucket = theme
                break

        themed = [track for track in tracks if bucket in track.stem.lower()]
        choices = themed if themed else tracks
        return random.choice(choices)

    def generate_background_music(self, total_seconds: int, output_path: Path, script_text: str = "") -> Path:
        """Create music track by selecting bundled asset or fallback sine tone."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        selected = self.choose_music_track(script_text)
        if selected:
            # Trim/loop selected track to target duration.
            cmd = [
                *self._ffmpeg_base_cmd(),
                "-stream_loop",
                "-1",
                "-i",
                str(selected),
                "-t",
                str(total_seconds),
                "-c",
                "copy",
                str(output_path),
            ]
            subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return output_path

        cmd = [
            *self._ffmpeg_base_cmd(),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:duration={total_seconds}",
            "-filter:a",
            "volume=0.06",
            str(output_path),
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path

    def mix_music(self, narration_video: Path, music_audio: Path, output_path: Path) -> Path:
        """Mix narration and background music at 15% music volume."""

        cmd = [
            *self._ffmpeg_base_cmd(),
            "-i",
            str(narration_video),
            "-i",
            str(music_audio),
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.15[a]",
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            str(output_path),
        ]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path

    def create_thumbnail(self, video_path: Path, output_path: Path) -> Path:
        """Extract a representative frame for thumbnail preview."""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [*self._ffmpeg_base_cmd(), "-i", str(video_path), "-ss", "00:00:05", "-vframes", "1", str(output_path)]
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return output_path

    def write_manifest(self, payload: dict, path: Path) -> None:
        """Write structured job manifest JSON file."""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _fmt_srt_time(self, seconds: float) -> str:
        """Convert floating-point seconds to SRT timestamp format."""

        millis = int((seconds - int(seconds)) * 1000)
        seconds_int = int(seconds)
        hrs = seconds_int // 3600
        mins = (seconds_int % 3600) // 60
        secs = seconds_int % 60
        return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"
