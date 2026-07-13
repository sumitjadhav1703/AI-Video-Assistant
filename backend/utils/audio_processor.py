import yt_dlp
from pydub import AudioSegment
import os

DOWNLOAD_DIR = 'downloades'
os.makedirs(DOWNLOAD_DIR,exist_ok = True)

# Groq rejects uploads over 25MB. At 16kHz mono 16-bit (32 KB/s), a 5-minute
# chunk is ~9.6MB, which leaves comfortable headroom.
CHUNK_MINUTES = 5


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



def convert_to_wav(input_path: str) -> str:
    """Convert any audio/video file to 16kHz mono WAV format using pydub."""
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000) #16khz
    audio.export(output_path, format="wav")
    return output_path



def chunk_audio(wav_path : str , chunk_minutes : int = CHUNK_MINUTES) -> list:
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000

    chunks = []

    for i, start in enumerate(range(0,len(audio),chunk_ms)):
        chunk = audio[start : start + chunk_ms]
        chunk_path = f"{wav_path}_chunk_{i}.wav"
        chunk.export(chunk_path , format = "wav")

        chunks.append(chunk_path)

    return chunks

def process_input(source: str) -> tuple[list, list]:
    """
    Returns (chunks, artifacts). `artifacts` is every temp file this created,
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

    # Both paths normalize through the same conversion. yt-dlp hands back whatever
    # sample rate the source used (often 44.1kHz stereo), which at 10 minutes is
    # ~105MB per chunk — far over Groq's 25MB cap. 16kHz mono is also all Whisper
    # consumes, so nothing is lost by downsampling here.
    print("Converting to 16kHz mono WAV...")
    wav_path = convert_to_wav(raw_path)
    artifacts.append(wav_path)

    print("Chunking audio...")
    chunks = chunk_audio(wav_path)
    artifacts.extend(chunks)
    print(f"Audio ready — {len(chunks)} chunk(s) created.")
    return chunks, artifacts


def cleanup(artifacts: list) -> None:
    """Delete transient audio. Best-effort: a missing file is not an error."""
    for path in artifacts:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError as e:
            print(f"Could not remove {path}: {e}")
