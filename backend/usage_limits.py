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
            min(_positive('JOBS_PER_IP_DAY', 1), 1), min(_positive('JOBS_GLOBAL_DAY', 5), 5),
            min(_positive('CHATS_PER_IP_MINUTE', 2), 2), min(_positive('CHATS_PER_IP_DAY', 20), 20),
            min(_positive('CHATS_PER_JOB_DAY', 3), 3), min(_positive('CHATS_GLOBAL_DAY', 15), 15),
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


class LimitExceeded(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, retry_after)
        super().__init__('Demo usage limit reached. Please try again later.')


class JobUnavailable(Exception):
    pass


class JobBusy(Exception):
    pass
