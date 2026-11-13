"""Safety rails for evaluation runs: forced environment, disposable-DB check and a socket allowlist."""
import ipaddress
import os
import socket
from contextlib import contextmanager
from urllib.parse import urlparse

from evaluation import config

EVAL_DB_NAME = 'ava_eval'
DEV_DB_PORT = 55432  # the developer's own ai-video-pgvector container; never touched


class NetworkBlocked(ConnectionError):
    """A connection outside the mode's allowlist was refused before any bytes were sent."""


class UnsafeDatabase(RuntimeError):
    """The configured database is not the disposable loopback evaluation database."""


def apply_environment(mode, env=os.environ, dotenv_path=config.ROOT / '.env'):
    """Prepare the process environment for the app under test.

    local:   loads the developer .env without overriding the shell, then forces paid routes off.
    offline: loads nothing and turns provider calls off entirely.
    """
    if mode == 'local':
        from dotenv import dotenv_values
        for key, value in dotenv_values(dotenv_path).items():
            if value is not None:
                env.setdefault(key, value)
    elif mode == 'offline':
        env['ENABLE_PROVIDER_CALLS'] = 'false'
    else:
        raise ValueError(f'unknown mode {mode!r}')
    env.update(config.FORCED_APP_ENV)
    # The production/dev DATABASE_URL from .env is never used; only EVAL_DATABASE_URL may be.
    env.pop('DATABASE_URL', None)
    if env.get('EVAL_DATABASE_URL'):
        env['DATABASE_URL'] = require_eval_database(env['EVAL_DATABASE_URL'])
    return env


def require_eval_database(url):
    parsed = urlparse(url)
    if parsed.hostname not in config.LOOPBACK_HOSTS:
        raise UnsafeDatabase('EVAL_DATABASE_URL must point at a loopback host.')
    if parsed.port == DEV_DB_PORT:
        raise UnsafeDatabase(f'Port {DEV_DB_PORT} is the developer database; use the disposable ava-eval-pg container.')
    if parsed.path.lstrip('/') != EVAL_DB_NAME:
        raise UnsafeDatabase(f'The evaluation database must be named {EVAL_DB_NAME!r}.')
    return url


def allowed_hosts(mode, *, judge=False):
    if mode == 'offline':
        return set(config.LOOPBACK_HOSTS)
    hosts = set(config.LOOPBACK_HOSTS) | set(config.APP_PROVIDER_HOSTS)
    if judge:
        hosts |= set(config.JUDGE_HOSTS)
    return hosts


def _is_loopback(address):
    try:
        return ipaddress.ip_address(address.split('%')[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def network_guard(hosts):
    """Refuse DNS lookups and TCP connects to anything outside `hosts` (plus loopback and Unix sockets)."""
    hosts = {h.lower() for h in hosts}
    resolved = set()
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_getaddrinfo(host, *args, **kwargs):
        name = host.decode() if isinstance(host, bytes) else host
        if name is None or _is_loopback(str(name)) or str(name).lower() in hosts:
            results = original_getaddrinfo(host, *args, **kwargs)
            resolved.update(r[4][0] for r in results)
            return results
        raise NetworkBlocked(f'Evaluation network guard refused a lookup of {name}.')

    def check(address):
        if isinstance(address, (str, bytes)):  # Unix domain socket
            return
        host = address[0]
        if _is_loopback(host) or host in resolved:
            return
        raise NetworkBlocked(f'Evaluation network guard refused a connection to {host}.')

    def guarded_connect(self, address):
        check(address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):
        check(address)
        return original_connect_ex(self, address)

    socket.getaddrinfo = guarded_getaddrinfo
    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


def redact(text, env=os.environ):
    """Remove any configured secret values from text before it is printed or written."""
    for key, value in env.items():
        if value and len(value) >= 8 and any(t in key for t in ('KEY', 'SECRET', 'TOKEN', 'PASSWORD')):
            text = text.replace(value, f'<{key}>')
    return text
