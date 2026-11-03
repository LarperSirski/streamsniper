"""Shared helpers for organizing stream recordings and metadata."""
import json
import logging
import shutil
import subprocess
from uuid import uuid4
from pathlib import Path

from config import VIDEO_EXTENSIONS


def write_stream_metadata(folder: Path, video_id: str, fallback_title: str) -> None:
    info_files = list(folder.glob(f"*{video_id}*.info.json"))
    metadata = {}
    if info_files:
        try:
            metadata = json.loads(info_files[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logging.exception("Could not read stream info JSON: %s", info_files[0])

    title = metadata.get("title") or fallback_title or "Live stream"
    description = metadata.get("description") or ""
    contents = f"Title: {title}\n\nDescription:\n{description}\n"
    try:
        (folder / "stream-info.txt").write_text(contents, encoding="utf-8")
    except OSError:
        logging.exception("Could not write stream metadata in %s", folder)


def find_recording_file(folder: Path, video_id: str, extensions: set[str]):
    matches = [
        path for path in folder.glob(f"*{video_id}*")
        if path.is_file() and path.suffix.lower() in extensions
    ]
    return max(matches, key=lambda path: path.stat().st_mtime, default=None)


def recover_partial_recording(partial_path: Path) -> Path:
    if partial_path.suffix.lower() != ".part":
        raise ValueError("Select a yt-dlp .part recording to recover.")

    output_path = partial_path.with_suffix("")
    if output_path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("The partial file does not have a supported video extension.")
    if output_path.exists():
        raise FileExistsError(f"A video already exists at {output_path}.")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg is required to recover this partial recording.")

    temporary_output = output_path.with_name(
        f"{output_path.stem}.recovery-{uuid4().hex[:8]}{output_path.suffix}"
    )
    result = subprocess.run(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "+genpts",
            "-i", str(partial_path), "-map", "0", "-c", "copy",
            "-movflags", "+faststart", "-n", str(temporary_output),
        ],
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if result.returncode != 0 or not temporary_output.exists():
        temporary_output.unlink(missing_ok=True)
        details = result.stderr.strip()[-1000:]
        raise RuntimeError(details or "FFmpeg could not recover the partial recording.")

    try:
        temporary_output.rename(output_path)
    except OSError:
        temporary_output.unlink(missing_ok=True)
        raise
    return output_path