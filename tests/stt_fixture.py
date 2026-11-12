"""Shared offline STT route: tests that patch provider adapters still need a configured chain."""
from unittest.mock import patch

from backend.core.audio_budget import AudioProfile

GROQ = AudioProfile('groq', 'whisper-large-v3-turbo', 'GROQ_API_KEY', True, 10, 100, 3600, 7200)


def groq_chain(*profiles):
    return patch('backend.core.transcriber.audio_budget.profiles_for_language', return_value=list(profiles) or [GROQ])
