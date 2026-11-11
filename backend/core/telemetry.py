"""Best-effort local metrics; values must never contain user content or identifiers."""
import logging
import os
import time
from contextlib import contextmanager

logger = logging.getLogger('uvicorn.error.metrics')


def metric(name, **values):
    try:
        fields = ' '.join(f'{key}={value}' for key, value in values.items())
        logger.info('metric=%s %s', name, fields)
    except Exception:
        pass  # Metrics must not alter processing or cleanup.


@contextmanager
def duration(stage):
    start = time.monotonic()
    status = 'failed'
    try:
        yield
        status = 'success'
    finally:
        metric('stage', stage=stage, status=status, elapsed_ms=round((time.monotonic() - start) * 1000))


def local_size(paths):
    try:
        return sum(os.path.getsize(path) for path in paths)
    except OSError:
        return None
