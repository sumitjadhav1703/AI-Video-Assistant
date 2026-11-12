import glob
import math
import os
import re
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit

import yt_dlp

from ..core.telemetry import duration, local_size, metric

# Groq rejects uploads over 25MB. At 16kHz mono 16-bit (32 KB/s), a 5-minute
# chunk is ~9.6MB, which leaves comfortable headroom.
CHUNK_MINUTES = 5

# The ffmpeg binary. It ships in the Docker image (see Dockerfile) and pydub/yt-dlp
# already rely on it; resolve from PATH with a plain-name fallback.
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"
# Media demuxers only. Manifest demuxers such as concat can open other local files.
INPUT_FORMATS = "aac,aiff,amr,asf,avi,caf,flac,flv,matroska,webm,mov,mp3,mpeg,mpegts,ogg,wav,wv"


BOT_CHECK_MESSAGE = (
    "YouTube blocked this download. Upload an audio or video file you have permission to use."
)


def _is_bot_check(err: Exception) -> bool:
    text = str(err).lower()
    return "confirm you" in text and "bot" in text


class MediaValidationError(ValueError):
    """Safe media validation message for users."""


def _max_seconds() -> float:
    value = float(os.getenv("MAX_MEDIA_SECONDS", "").strip() or "600")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("MAX_MEDIA_SECONDS must be finite and positive.")
    return min(value, 120)


def _validate_duration(value) -> None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        raise MediaValidationError("Media duration is unknown.") from None
    if not math.isfinite(duration) or duration <= 0 or duration > _max_seconds():
        raise MediaValidationError("Media duration is invalid or exceeds the limit.")


def validate_youtube_url(url: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc not in
            {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}):
        raise ValueError("Only HTTPS YouTube URLs are supported.")
    query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=64)
    if parts.path == "/playlist" or "list" in query:
        raise ValueError("Playlists are not supported.")
    if parts.netloc == "youtu.be":
        video_ids = [parts.path.removeprefix("/")]
    elif parts.path == "/watch":
        video_ids = query.get("v", [])
    else:
        match = re.fullmatch(r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", parts.path)
        video_ids = [match[1]] if match else []
    if len(video_ids) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_ids[0]):
        raise ValueError("Provide a URL for a single YouTube video.")
    if os.getenv("ENABLE_YOUTUBE", "false").lower() != "true":
        raise ValueError("YouTube downloads are disabled.")
    return f"https://www.youtube.com/watch?v={video_ids[0]}"


def download_youtube_audio(url: str) -> str:
    url = validate_youtube_url(url)
    max_bytes = int(os.getenv("MAX_DOWNLOAD_MB", "").strip() or "25") * 1024 * 1024
    if max_bytes <= 0:
        raise ValueError("MAX_DOWNLOAD_MB must be positive.")
    directory = tempfile.mkdtemp(prefix="avassist_download_")

    def limit_download(status):
        if (status.get("downloaded_bytes") or 0) > max_bytes:
            raise MediaValidationError("Download exceeds the size limit.")

    opts = {
        "format": "bestaudio[protocol=https]/best[protocol=https]",
        "outtmpl": os.path.join(directory, "%(id)s.%(ext)s"),
        "allowed_extractors": ["youtube"],
        "quiet": True, "noplaylist": True, "max_filesize": max_bytes,
        "socket_timeout": 15, "retries": 0, "fragment_retries": 0,
        "progress_hooks": [limit_download],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or info.get("_type") in ("playlist", "multi_video") or info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise MediaValidationError("Playlists and live streams are not supported.")
            _validate_duration(info.get("duration"))
            if (info.get("filesize") or info.get("filesize_approx") or 0) > max_bytes:
                raise MediaValidationError("Download exceeds the size limit.")
            info = ydl.process_ie_result(info, download=True)
            downloads = info.get("requested_downloads") or []
            filename = downloads[0].get("filepath") if downloads else None
            filename = filename or ydl.prepare_filename(info)
            if (os.path.commonpath([directory, os.path.realpath(filename)]) != directory
                    or not os.path.isfile(filename) or os.path.getsize(filename) > max_bytes):
                raise MediaValidationError("Downloaded media is missing or exceeds the size limit.")
            return filename
    except Exception as err:
        cleanup([directory])
        if isinstance(err, yt_dlp.utils.DownloadError) and _is_bot_check(err):
            raise MediaValidationError(BOT_CHECK_MESSAGE) from None
        raise


def chunk_streaming(raw_path: str, chunk_minutes: int = CHUNK_MINUTES) -> tuple[list, str]:
    """
    Decode any audio/video file to 16kHz mono WAV and split it into fixed-length
    chunks in a single streaming ffmpeg pass. Returns (chunk_paths, chunk_dir).

    ffmpeg processes the input as a stream, so memory stays flat regardless of file
    length. This deliberately replaces the old pydub path (AudioSegment.from_file +
    from_wav), which loaded the entire decoded PCM into RAM twice and blew past
    Render's 512MB free tier on long recordings.
    """
    raw_path = os.path.abspath(raw_path)
    try:
        probe = subprocess.run(
            [FFPROBE, "-v", "error", "-protocol_whitelist", "file,pipe",
             "-format_whitelist", INPUT_FORMATS, "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", raw_path],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, stdin=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        raise MediaValidationError("The media is corrupt or uses an unsupported format.") from None
    _validate_duration(probe.stdout.decode("utf-8", "replace").strip())
    chunk_dir = tempfile.mkdtemp(prefix="avassist_chunks_")
    pattern = os.path.join(chunk_dir, "chunk_%03d.wav")

    cmd = [
        FFMPEG, "-v", "error", "-nostats", "-y",
        "-protocol_whitelist", "file,pipe",
        "-format_whitelist", INPUT_FORMATS,
        "-i", raw_path,
        "-t", str(_max_seconds()),
        "-vn",                       # drop any video stream — only the audio track matters
        "-ac", "1",                  # mono
        "-ar", "16000",              # 16kHz — all Whisper/Sarvam consume
        "-f", "segment",
        "-segment_time", str(chunk_minutes * 60),
        "-reset_timestamps", "1",
        pattern,
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=max(60, _max_seconds() * 2), stdin=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        cleanup([chunk_dir])
        raise MediaValidationError("The media could not be decoded as audio.") from None

    except Exception:
        cleanup([chunk_dir])
        raise

    chunks = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))
    if not chunks:
        cleanup([chunk_dir])
        raise MediaValidationError("No audio was found in the uploaded file.")
    return chunks, chunk_dir


def process_input(source: str) -> tuple[list, list]:
    """
    Returns (chunks, artifacts). `artifacts` is every temp file/dir this created,
    for the caller to delete once transcription is done — audio is transient and
    is never persisted anywhere.
    """
    artifacts = []
    try:
        if "://" in source:
            with duration("youtube_download"):
                raw_path = download_youtube_audio(source)
            artifacts.append(os.path.dirname(raw_path))
        else:
            raw_path = source
        size = local_size([raw_path])
        if size is not None:
            metric("input", local_file_bytes=size)
        with duration("audio_conversion"):
            chunks, chunk_dir = chunk_streaming(raw_path)
        artifacts.extend(chunks)
        artifacts.append(chunk_dir)
        size = local_size(chunks)
        if size is not None:
            metric("decoded_audio", wav_file_bytes=size, audio_chunks=len(chunks))
        return chunks, artifacts
    except Exception:
        cleanup(artifacts)
        raise


def cleanup(artifacts: list) -> None:
    """Delete transient audio. Best-effort: a missing path is not an error."""
    for path in artifacts:
        try:
            if not path or not os.path.exists(path):
                continue
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except FileNotFoundError:
            continue
        except OSError:
            metric("audio_cleanup", status="failed")
