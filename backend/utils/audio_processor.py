import glob
import os
import shutil
import subprocess
import tempfile

import yt_dlp

DOWNLOAD_DIR = 'downloades'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Groq rejects uploads over 25MB. At 16kHz mono 16-bit (32 KB/s), a 5-minute
# chunk is ~9.6MB, which leaves comfortable headroom.
CHUNK_MINUTES = 5

# The ffmpeg binary. It ships in the Docker image (see Dockerfile) and pydub/yt-dlp
# already rely on it; resolve from PATH with a plain-name fallback.
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _cookie_opts() -> dict:
    """
    yt-dlp will use a browser-exported cookies.txt if one is configured and present.
    This only reduces datacenter-IP blocking — it does not eliminate it. Downloads
    from Render will still fail intermittently with "Sign in to confirm you're not
    a bot". That is expected on a free datacenter IP, not a bug to chase.
    """
    path = os.getenv("YT_DLP_COOKIES_PATH")
    if path and os.path.exists(path):
        return {"cookiefile": path}
    return {}


BOT_CHECK_MESSAGE = (
    "YouTube blocked this download. It serves a \"Sign in to confirm you're not a bot\" "
    "challenge to cloud/datacenter IP ranges, which is what the hosted backend runs on. "
    "This is a restriction on YouTube's side, not a fault in the pipeline — the same URL "
    "downloads fine when the backend runs on a home/residential connection. "
    "Upload the audio or video file directly instead."
)


def _is_bot_check(err: Exception) -> bool:
    text = str(err).lower()
    return "confirm you" in text and "bot" in text


def download_youtube_audio(url :str) ->str:
    output_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info).replace(".webm", ".wav").replace(".m4a", ".wav")
    except yt_dlp.utils.DownloadError as err:
        # Surface the bot check as a plain explanation rather than a yt-dlp traceback;
        # the job's error field is rendered verbatim in the UI.
        if _is_bot_check(err):
            raise RuntimeError(BOT_CHECK_MESSAGE) from err
        raise
    return filename


def chunk_streaming(raw_path: str, chunk_minutes: int = CHUNK_MINUTES) -> tuple[list, str]:
    """
    Decode any audio/video file to 16kHz mono WAV and split it into fixed-length
    chunks in a single streaming ffmpeg pass. Returns (chunk_paths, chunk_dir).

    ffmpeg processes the input as a stream, so memory stays flat regardless of file
    length. This deliberately replaces the old pydub path (AudioSegment.from_file +
    from_wav), which loaded the entire decoded PCM into RAM twice and blew past
    Render's 512MB free tier on long recordings.
    """
    chunk_dir = tempfile.mkdtemp(prefix="avassist_chunks_")
    pattern = os.path.join(chunk_dir, "chunk_%03d.wav")

    cmd = [
        FFMPEG, "-y",
        "-i", raw_path,
        "-vn",                       # drop any video stream — only the audio track matters
        "-ac", "1",                  # mono
        "-ar", "16000",              # 16kHz — all Whisper/Sarvam consume
        "-f", "segment",
        "-segment_time", str(chunk_minutes * 60),
        "-reset_timestamps", "1",
        pattern,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as err:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        stderr = (err.stderr or b"").decode("utf-8", "replace").strip()
        tail = stderr.splitlines()[-1] if stderr else "unknown ffmpeg error"
        raise RuntimeError(f"Audio conversion failed: {tail}") from err

    chunks = sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.wav")))
    if not chunks:
        shutil.rmtree(chunk_dir, ignore_errors=True)
        raise RuntimeError("No audio was found in the uploaded file.")
    return chunks, chunk_dir


def process_input(source: str) -> tuple[list, list]:
    """
    Returns (chunks, artifacts). `artifacts` is every temp file/dir this created,
    for the caller to delete once transcription is done — audio is transient and
    is never persisted anywhere.
    """
    artifacts = []

    if source.startswith("http://") or source.startswith("https://"):
        print("Detected YouTube URL. Downloading audio...")
        raw_path = download_youtube_audio(source)
        artifacts.append(raw_path)
    else:
        print("Detected local file.")
        raw_path = source

    # Single streaming pass: decode to 16kHz mono and segment into chunks at once.
    print("Converting to 16kHz mono WAV and chunking...")
    chunks, chunk_dir = chunk_streaming(raw_path)
    artifacts.extend(chunks)
    artifacts.append(chunk_dir)
    print(f"Audio ready — {len(chunks)} chunk(s) created.")
    return chunks, artifacts


def cleanup(artifacts: list) -> None:
    """Delete transient audio. Best-effort: a missing path is not an error."""
    for path in artifacts:
        try:
            if not path or not os.path.exists(path):
                continue
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except OSError as e:
            print(f"Could not remove {path}: {e}")
