"""Free-demo admission settings; defaults never enable remote inference."""
import hashlib
import hmac
import ipaddress
import os
from dataclasses import dataclass


def _positive(name: str, default: int) -> int:
    value = int(os.getenv(name, '').strip() or default)
    if value <= 0:
        raise ValueError(f'{name} must be a positive integer')
    return value


def _enabled(name: str) -> bool:
    value = os.getenv(name, '').strip().lower()
    if value not in ('', 'false', '0', 'true', '1'):
        raise ValueError(f'{name} must be true or false')
    return value in ('true', '1')


@dataclass(frozen=True)
class Settings:
    provider_calls_enabled: bool
    sarvam_enabled: bool
    rate_limit_secret: str
    max_upload_bytes: int
    jobs_per_ip_day: int
    jobs_global_day: int
    chats_per_ip_minute: int
    chats_per_ip_day: int
    chats_per_job_day: int
    chats_global_day: int

    @classmethod
    def from_env(cls):
        enabled = _enabled('ENABLE_PROVIDER_CALLS')
        secret = os.getenv('RATE_LIMIT_SECRET', '').strip()
        if enabled and len(secret) < 32:
            raise ValueError('RATE_LIMIT_SECRET must contain at least 32 characters when providers are enabled')
        return cls(
            enabled, _enabled('ENABLE_SARVAM'), secret,
            min(_positive('MAX_UPLOAD_MB', 25), 25) * 1024 * 1024,
            min(_positive('JOBS_PER_IP_DAY', 2), 2), min(_positive('JOBS_GLOBAL_DAY', 15), 15),
            min(_positive('CHATS_PER_IP_MINUTE', 2), 2), min(_positive('CHATS_PER_IP_DAY', 30), 30),
            min(_positive('CHATS_PER_JOB_DAY', 5), 5), min(_positive('CHATS_GLOBAL_DAY', 60), 60),
        )


def require_provider_calls(sarvam: bool = False) -> None:
    settings = Settings.from_env()
    if not settings.provider_calls_enabled:
        raise RuntimeError('Provider calls are disabled. Configure verified free-only access before enabling processing.')
    if sarvam and not settings.sarvam_enabled:
        raise RuntimeError('Hinglish transcription is disabled until Sarvam access is explicitly approved.')


def client_key(host: str | None, secret: str) -> str:
    if not host or not secret:
        raise ValueError('A connection address and rate-limit secret are required')
    address = ipaddress.ip_address(host)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return hmac.new(secret.encode(), address.compressed.encode(), hashlib.sha256).hexdigest()


PROVIDER_QUOTA_MESSAGE = ("The free AI providers this demo runs on are at their limit right now, so it cannot take "
                          "more work at the moment. It uses free tiers only.")


class LimitExceeded(Exception):
    def __init__(self, retry_after: int, message: str = 'Demo usage limit reached. Please try again later.'):
        self.retry_after = max(1, retry_after)
        super().__init__(message)


def _count(n: int, one: str, many: str) -> str:
    return f'{n} {one if n == 1 else many}'


def limit_message(scope: str, settings: Settings) -> str:
    """Plain explanation for a visitor who hit a limit; scope is a usage_counters scope or 'busy_<slot>'."""
    messages = {
        'jobs_global_day': f"Today's free demo capacity is used up. Minutes runs on free cloud and AI tiers, so the whole "
                           f"site gets {_count(settings.jobs_global_day, 'analysis', 'analyses')} a day, and they are all "
                           "taken. It resets at midnight UTC. Meanwhile you can explore the Evaluation and How it works "
                           "pages, or run it yourself from GitHub.",
        'jobs_ip_day': f"You've used your {_count(settings.jobs_per_ip_day, 'free analysis', 'free analyses')} for today. "
                       "Each visitor gets a small share so everyone can try it; it resets at midnight UTC.",
        'chats_ip_minute': f"That's {_count(settings.chats_per_ip_minute, 'question', 'questions')} this minute, the most "
                           "the free tier allows. Wait a moment and ask again.",
        'chats_ip_day': f"You've asked your {_count(settings.chats_per_ip_day, 'free question', 'free questions')} for "
                        "today. It resets at midnight UTC.",
        'chats_job_day': f"This recording has had its {_count(settings.chats_per_job_day, 'free question', 'free questions')} "
                         "for today. It resets at midnight UTC.",
        'chats_global_day': f"Today's free question capacity is used up: the whole site gets "
                            f"{_count(settings.chats_global_day, 'question', 'questions')} a day on free AI tiers. "
                            "It resets at midnight UTC.",
        'busy_processing': "Another visitor's recording is being analysed right now. The free tier runs one at a time, "
                           "so please try again in a minute.",
        'busy_chat': "Another question is being answered right now. The free tier answers one at a time, so please "
                     "try again in a few seconds.",
    }
    return messages.get(scope, 'Demo usage limit reached. Please try again later.')


class JobUnavailable(Exception):
    pass


class JobBusy(Exception):
    pass
