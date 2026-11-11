import os
import requests
from groq import Groq
from pydub import AudioSegment

from ..usage_limits import require_provider_calls
from .llm_gateway import validate_transcript, current_operation
from . import audio_budget
from .telemetry import duration as duration_metric, metric

# Sarvam's sync STT-translate API rejects audio longer than 30s.
# We slice each chunk into 25s pieces (with a 5s safety margin) before sending.
SARVAM_PIECE_SECONDS = 25


SARVAM_STT_TRANSLATE_URL = "https://api.sarvam.ai/speech-to-text-translate"

# Groq caps uploads at 25MB. utils.audio_processor normalizes every source to
# 16kHz mono and chunks at 5 minutes (~9.6MB), which keeps us under that ceiling.


def transcribe_chunk_groq(chunk_path: str) -> str:
    from .guardrails import sanitize_text
    segments = _groq_segments(chunk_path)
    return sanitize_text(' '.join((item.get('text', '') if isinstance(item, dict) else item.text) for item in segments))


def _send_to_sarvam(piece_path: str) -> str:
    profile = audio_budget.profile_for_language('hinglish')
    duration = _wav_duration_ms(piece_path)
    audio_budget.reserve_audio_attempt(current_operation(), profile, duration)
    with open(piece_path, 'rb') as f:
        response = requests.post(
            SARVAM_STT_TRANSLATE_URL,
            headers={'api-subscription-key': os.environ[profile.keyenv]},
            files={'file': (os.path.basename(piece_path), f, 'audio/wav')},
            data={'model': profile.model, 'with_diarization': 'false'}, timeout=120,
        )
    if not response.ok:
        response.raise_for_status()
    return response.json().get('transcript', '')


def transcribe_chunk_sarvam(chunk_path: str) -> str:
    from .guardrails import sanitize_text
    audio_budget.profile_for_language('hinglish')
    segments = _sarvam_segments(chunk_path, _wav_duration_ms(chunk_path))
    return sanitize_text(' '.join(segment['text'] for segment in segments))


def transcribe_chunk(chunk_path: str, language: str = "english") -> str:
    """
    Route one chunk to Groq or Sarvam depending on language choice.
    - english  → Groq (hosted whisper-large-v3-turbo)
    - hinglish → Sarvam (translates to English while transcribing)
    """
    if language == "hinglish":
        return transcribe_chunk_sarvam(chunk_path)
    if language == "english":
        return transcribe_chunk_groq(chunk_path)
    raise ValueError("Unsupported transcription language")


def transcribe_all(chunks: list, language: str = "english") -> str:
    from .guardrails import sanitize_text
    return sanitize_text(' '.join(segment['text'] for segment in transcribe_segments(chunks, language)))


def _wav_duration_ms(path):
    import wave
    with wave.open(path, 'rb') as wav:
        rate = wav.getframerate()
        return (wav.getnframes() * 1000 + rate - 1) // rate


def _groq_segments(path):
    profile = audio_budget.profile_for_language('english')
    duration = _wav_duration_ms(path)
    audio_budget.reserve_audio_attempt(current_operation(), profile, duration)
    client = Groq(api_key=os.environ[profile.keyenv], timeout=60, max_retries=0)
    with open(path, 'rb') as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()), model=profile.model,
            response_format='verbose_json', timestamp_granularities=['segment'],
        )
    return result.segments if hasattr(result, 'segments') else result.get('segments', [])


def _sarvam_segments(path, duration):
    require_provider_calls(sarvam=True)
    if not os.getenv('SARVAM_API_KEY', '').strip():
        raise RuntimeError('SARVAM_API_KEY is not set')
    with open(path, 'rb') as audio_file:
        audio = AudioSegment.from_wav(audio_file)
    result = []
    for i, start in enumerate(range(0, duration, SARVAM_PIECE_SECONDS * 1000)):
        piece_path = f'{path}_sv_{i}.wav'
        try:
            with open(piece_path, 'wb') as piece_file:
                audio[start:min(start + SARVAM_PIECE_SECONDS * 1000, duration)].export(piece_file, format='wav')
            text = _send_to_sarvam(piece_path)
            if not isinstance(text, str) or not text.strip():
                raise ValueError('Transcription returned empty text.')
            result.append({'text': text.strip(), 'start_ms': start, 'end_ms': min(start + SARVAM_PIECE_SECONDS * 1000, duration), 'timing_precision': 'piece'})
            validate_transcript(' '.join(segment['text'] for segment in result))
        finally:
            if os.path.exists(piece_path):
                os.remove(piece_path)
    return result


def transcribe_segments(chunks: list[str], language: str = 'english') -> list[dict]:
    import math
    if language not in ('english', 'hinglish'):
        raise ValueError('Unsupported transcription language')
    offset = 0
    segments = []
    for path in chunks:
        duration = _wav_duration_ms(path)
        if duration <= 0:
            raise ValueError('Audio duration must be positive.')
        if language == 'hinglish':
            with duration_metric('stt_chunk'):
                current = _sarvam_segments(path, duration)
        else:
            current = []
            previous_end = 0
            with duration_metric("stt_chunk"):
                groq_segments = _groq_segments(path)
            for item in groq_segments or []:
                get = item.get if isinstance(item, dict) else lambda key: getattr(item, key, None)
                text, start, end = get('text'), get('start'), get('end')
                if not isinstance(text, str) or not text.strip() or isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end):
                    raise ValueError('Invalid transcription segment.')
                if start < previous_end or end < start or end * 1000 > duration:
                    raise ValueError('Invalid transcription timestamps.')
                start_ms, end_ms = round(start * 1000), round(end * 1000)
                previous_end = end
                current.append({'text': text.strip(), 'start_ms': start_ms, 'end_ms': end_ms, 'timing_precision': 'segment'})
        if not current:
            raise ValueError('Transcription returned empty text.')
        for segment in current:
            segment['start_ms'] += offset
            segment['end_ms'] += offset
        segments.extend(current)
        metric("stt_chunk", audio_duration_ms=duration, segments=len(current))
        validate_transcript(' '.join(s['text'] for s in segments))
        offset += duration
    if not segments:
        raise ValueError('Transcription returned empty text.')
    return segments
