"""Durable, conservative limits for explicitly approved STT accounts."""
import json
import os
import re
from dataclasses import dataclass

from ..usage_limits import LimitExceeded, require_provider_calls

AUDIO_SCHEMA = '''
CREATE TABLE IF NOT EXISTS audio_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    duration_ms BIGINT NOT NULL CHECK (duration_ms > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS audio_attempts_window ON audio_attempts(provider, created_at);
'''


@dataclass(frozen=True)
class AudioProfile:
    provider: str
    model: str
    keyenv: str
    verified_free: bool
    rpm: int
    rpd: int
    audio_seconds_hour: int
    audio_seconds_day: int


_KEYS = {'groq': 'GROQ_API_KEY', 'sarvam': 'SARVAM_API_KEY', 'gemini': 'GEMINI_API_KEY', 'meta': 'META_API_KEY'}
MAX_PROFILES = 8


def _flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() == 'true'


def _configured_profiles() -> list[AudioProfile]:
    try:
        profiles = json.loads(os.getenv('STT_PROFILES_JSON', '[]'))
        if not isinstance(profiles, list) or not profiles or len(profiles) > MAX_PROFILES:
            raise ValueError()
        result, seen = [], set()
        for item in profiles:
            if not isinstance(item, dict) or set(item) != set(AudioProfile.__annotations__):
                raise ValueError()
            profile = AudioProfile(**item)
            # Meta is the only paid route and must say so; every other profile is an attested free account.
            if (profile.provider not in _KEYS or (profile.provider, profile.model) in seen or
                profile.keyenv != _KEYS[profile.provider] or
                not isinstance(profile.model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', profile.model) or
                profile.verified_free is not (profile.provider != 'meta') or
                any(type(getattr(profile, key)) is not int or getattr(profile, key) <= 0
                    for key in ('rpm', 'rpd', 'audio_seconds_hour', 'audio_seconds_day'))):
                raise ValueError()
            seen.add((profile.provider, profile.model))
            result.append(profile)
        return result
    except (TypeError, ValueError, KeyError):
        raise ValueError('Explicit verified-free transcription profile is required') from None


def profiles_for_language(language: str, *, owner_paid: bool = False) -> list[AudioProfile]:
    """Ordered fallback chain: configured order, credentials present, paid Meta last and opt-in only."""
    if language not in ('english', 'hinglish'):
        raise ValueError('Unsupported transcription language')
    require_provider_calls(sarvam=language == 'hinglish')
    paid_ok = _flag('ENABLE_PAID_META') and (owner_paid or _flag('ENABLE_PUBLIC_PAID_FALLBACK'))
    chain = [p for p in _configured_profiles()
             if (p.provider == 'sarvam') == (language == 'hinglish')
             and os.getenv(p.keyenv, '').strip() and (p.provider != 'meta' or paid_ok)]
    chain.sort(key=lambda p: p.provider == 'meta')
    if not chain:
        raise ValueError('Explicit verified-free transcription profile is required')
    return chain


def profile_for_language(language: str) -> AudioProfile:
    return profiles_for_language(language)[0]


def reserve_audio_attempt(job_id: str, profile: AudioProfile, duration_ms: int) -> int:
    from ..db import connect
    if not isinstance(job_id, str) or not job_id.strip() or type(duration_ms) is not int or duration_ms <= 0:
        raise ValueError('Invalid audio reservation')
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM usage_guard WHERE id=1 FOR UPDATE')
        if cur.fetchone() is None:
            raise RuntimeError('Usage guard is missing')
        cur.execute('''SELECT
            COUNT(*) FILTER (WHERE created_at > clock_timestamp() - INTERVAL '60 seconds') AS rpm,
            COUNT(*) FILTER (WHERE created_at > clock_timestamp() - INTERVAL '24 hours') AS rpd,
            COALESCE(SUM(duration_ms) FILTER (WHERE created_at > clock_timestamp() - INTERVAL '1 hour'), 0) AS hour_ms,
            COALESCE(SUM(duration_ms), 0) AS day_ms
            FROM audio_attempts WHERE provider=%s AND model=%s AND created_at > clock_timestamp() - INTERVAL '24 hours' ''',
                    (profile.provider, profile.model))
        used = cur.fetchone()
        if used['rpd'] + 1 > profile.rpd or used['day_ms'] + duration_ms > profile.audio_seconds_day * 1000:
            raise LimitExceeded(86400)
        if used['hour_ms'] + duration_ms > profile.audio_seconds_hour * 1000:
            raise LimitExceeded(3600)
        if used['rpm'] + 1 > profile.rpm:
            raise LimitExceeded(60)
        cur.execute('INSERT INTO audio_attempts(job_id,provider,model,duration_ms) VALUES (%s,%s,%s,%s) RETURNING id',
                    (job_id, profile.provider, profile.model, duration_ms))
        result = cur.fetchone()['id']
        conn.commit()
        return result
