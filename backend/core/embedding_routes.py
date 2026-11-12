"""Fixed embedding spaces, conservative request bounds, and one wire call per reservation."""
import json
import math
import os
import re
import time
from dataclasses import dataclass

import httpx

from ..usage_limits import require_provider_calls
from .guardrails import sanitize_text
from .retrieval import RetrievalUnavailable

EMBEDDING_SPACES = {
    'openrouter-nemotron': ('nvidia/nemotron-3-embed-1b:free', 2048),
    'cloudflare-qwen': ('@cf/qwen/qwen3-embedding-0.6b', 1024),
    'gemini-embeddings': ('gemini-embedding-001', 768),
    'nvidia-nemotron': ('nvidia/nemotron-3.5-embed-1b', 2048),
}

_KEYS = {
    'openrouter': 'OPENROUTER_API_KEY',
    'cloudflare': 'CLOUDFLARE_WORKERS_AI_TOKEN',
    'gemini': 'GEMINI_API_KEY',
    'nvidia_nim': 'NVIDIA_API_KEY',
}
_LIMITS = ('rpm', 'tpm', 'rpd')
_CONFIG_FIELDS = {'id', 'verified_free', *_LIMITS}
MAX_TEXT_BYTES = 2048
_QUERY_INSTRUCTION = 'Given a question, retrieve relevant video transcript passages that answer it.'


class EmbeddingRouteUnavailable(RetrievalUnavailable):
    """The selected embedding route cannot serve the request."""


class EmbeddingRetryable(EmbeddingRouteUnavailable):
    """A transient or quota failure on the selected route."""


@dataclass(frozen=True)
class EmbeddingRoute:
    alias: str
    rpm: int
    tpm: int
    rpd: int

    @property
    def provider(self):
        return 'nvidia_nim' if self.alias == 'nvidia-nemotron' else self.alias.split('-', 1)[0]

    @property
    def model(self):
        return EMBEDDING_SPACES[self.alias][0]

    @property
    def dimension(self):
        return EMBEDDING_SPACES[self.alias][1]

    @property
    def batch_size(self):
        return 100 if self.provider == 'gemini' else 16

    @property
    def input_limit_tokens(self):
        return 60000

    @property
    def verified_free(self):
        return True

    @property
    def api_key_env(self):
        return _KEYS[self.provider]

    def credentials_ready(self):
        return bool(os.getenv(self.api_key_env, '').strip()) and (
            self.provider != 'cloudflare' or _cloudflare_account() is not None
        )

    def available(self):
        from .llm_gateway import local_owner_operation

        # Both Nemotron endpoints are NVIDIA trials. Render sets RENDER at runtime.
        if self.provider in ('openrouter', 'nvidia_nim') and os.getenv('RENDER'):
            return False
        return self.credentials_ready() and (self.provider != 'nvidia_nim' or local_owner_operation())


def _cloudflare_account():
    account_id = os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip()
    return account_id if re.fullmatch(r'[0-9a-fA-F]{32}', account_id) else None


def configured_embedding_routes() -> tuple[EmbeddingRoute, ...]:
    """Parse explicit config without checking credentials or enabling provider calls."""
    raw = os.getenv('EMBEDDING_ROUTES_JSON')
    if raw is None:
        if not all(os.getenv(name, '').strip().lower() == 'true' for name in (
            'ENABLE_GEMINI_EMBEDDINGS', 'GEMINI_EMBEDDINGS_VERIFIED_FREE'
        )):
            return ()
        try:
            limits = [int(os.environ[f'GEMINI_EMBEDDINGS_{name.upper()}']) for name in _LIMITS]
            if min(limits) <= 0:
                raise ValueError()
        except (ValueError, KeyError):
            raise ValueError('Explicit Gemini embedding account rate limits are required') from None
        return (EmbeddingRoute('gemini-embeddings', *limits),)
    try:
        items = json.loads(raw)
        if not isinstance(items, list) or len(items) > len(EMBEDDING_SPACES):
            raise ValueError()
        routes = []
        for item in items:
            if not isinstance(item, dict) or item.keys() != _CONFIG_FIELDS or item['verified_free'] is not True:
                raise ValueError()
            alias = item['id']
            if not isinstance(alias, str) or alias not in EMBEDDING_SPACES:
                raise ValueError()
            limits = [item[name] for name in _LIMITS]
            if any(type(limit) is not int or limit <= 0 for limit in limits):
                raise ValueError()
            routes.append(EmbeddingRoute(alias, *limits))
        aliases = {route.alias for route in routes}
        if [route.alias for route in routes] != [alias for alias in EMBEDDING_SPACES if alias in aliases]:
            raise ValueError()
    except (ValueError, RecursionError):
        raise ValueError('Invalid embedding route configuration') from None
    return tuple(routes)


def _role_prefix(query):
    return 'query: ' if query else 'passage: '


def _input_bound(route, sanitized, query):
    if len(sanitized) > route.batch_size:
        raise ValueError(f'Embedding batches are limited to {route.batch_size} documents')
    bounds = [len(text.encode('utf-8')) for text in sanitized]
    if any(not 1 <= bound <= MAX_TEXT_BYTES for bound in bounds):
        raise ValueError('Embedding input exceeds its conservative 2048-token bound')
    overhead = 0
    if route.provider in ('openrouter', 'nvidia_nim'):
        overhead = len(_role_prefix(query))
    elif route.provider == 'cloudflare' and query:
        # Workers AI formats the instruction and query before tokenizing.
        overhead = len(f'Instruct: {_QUERY_INSTRUCTION}\nQuery: ')
    return sum(bounds) + overhead * len(bounds)


def batch_input_bound(route, texts, query=False):
    return _input_bound(route, [sanitize_text(text) for text in texts], query)


def normalize_embedding(values, dimension):
    if not isinstance(values, list) or len(values) != dimension:
        raise ValueError('Embedding dimension does not match the selected space')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError('Embedding must contain finite numeric values')
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0 or not math.isfinite(norm):
        raise ValueError('Embedding has invalid magnitude')
    return [value / norm for value in values]


def _request(route, texts, query):
    token = os.getenv(route.api_key_env, '').strip()
    if not token:
        raise EmbeddingRouteUnavailable('Embedding route credentials are unavailable.')
    if route.provider == 'gemini':
        model = f'models/{route.model}'
        task = 'RETRIEVAL_QUERY' if query else 'RETRIEVAL_DOCUMENT'
        requests = [{
            'model': model,
            'content': {'parts': [{'text': text}]},
            'taskType': task,
            'outputDimensionality': route.dimension,
        } for text in texts]
        return (
            f'https://generativelanguage.googleapis.com/v1beta/{model}:batchEmbedContents',
            {'x-goog-api-key': token},
            {'requests': requests},
        )
    headers = {'Authorization': f'Bearer {token}'}
    if route.provider == 'cloudflare':
        account = _cloudflare_account()
        if account is None:
            raise EmbeddingRouteUnavailable('Embedding route credentials are unavailable.')
        body = {'queries': texts, 'instruction': _QUERY_INSTRUCTION} if query else {'documents': texts}
        return f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{route.model}', headers, body
    body = {'model': route.model, 'input': texts, 'encoding_format': 'float'}
    if route.provider == 'openrouter':
        body['input'] = [_role_prefix(query) + text for text in texts]
        body['provider'] = {'allow_fallbacks': False}
        return 'https://openrouter.ai/api/v1/embeddings', headers, body
    body.update(input_type='query' if query else 'passage', truncate='NONE')
    return 'https://integrate.api.nvidia.com/v1/embeddings', headers, body


def _vectors(route, payload, count):
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('Invalid embedding response')
    if route.provider == 'gemini':
        vectors = [entry['values'] for entry in payload['embeddings']]
    elif route.provider == 'cloudflare':
        if payload['success'] is not True:
            raise ValueError('Invalid embedding response')
        result = payload['result']
        vectors = result['data']
        if result.get('shape', [count, route.dimension]) != [count, route.dimension]:
            raise ValueError('Invalid embedding response shape')
    else:
        if payload['model'] != route.model:
            raise ValueError('Embedding response model mismatch')
        indexed = {}
        for entry in payload['data']:
            index = entry['index']
            if type(index) is not int or not 0 <= index < count or index in indexed:
                raise ValueError('Invalid embedding response index')
            indexed[index] = entry['embedding']
        vectors = [indexed[index] for index in range(count)]
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError('Embedding response count mismatch')
    return [normalize_embedding(vector, route.dimension) for vector in vectors]


def _reported_input(route, payload):
    key = 'usageMetadata' if route.provider == 'gemini' else 'usage'
    usage = payload.get(key)
    key = 'promptTokenCount' if route.provider == 'gemini' else 'prompt_tokens'
    reported = usage.get(key) if isinstance(usage, dict) else None
    return reported if type(reported) is int and 0 <= reported < 2**63 else None


def _openrouter_response(url, headers, body):
    from .llm_gateway import private_litellm
    litellm = private_litellm()
    from litellm.llms.custom_httpx.http_handler import HTTPHandler

    sent = False
    response = None

    def check_request(request):
        nonlocal sent
        if (sent or request.method != 'POST' or str(request.url) != url
                or request.headers.get('Authorization') != headers['Authorization']
                or json.loads(request.content) != body):
            raise ValueError('OpenRouter embedding transport rejected an unexpected request')
        sent = True

    def capture_response(received):
        nonlocal response
        response = received

    with httpx.Client(timeout=60, transport=httpx.HTTPTransport(retries=0), trust_env=False,
                      event_hooks={'request': [check_request], 'response': [capture_response]}) as client:
        try:
            litellm.embedding(model='openrouter/' + body['model'], input=body['input'],
                              encoding_format=body['encoding_format'], api_base=url.removesuffix('/embeddings'),
                              api_key=headers['Authorization'].removeprefix('Bearer '),
                              extra_body={'provider': body['provider']}, timeout=60, num_retries=0, max_retries=0,
                              client=HTTPHandler(client=client))
        except Exception:
            if response is not None:
                response.raise_for_status()
            raise
        if response is None:
            raise ValueError('OpenRouter embedding response did not use the guarded transport')
    return response


def embed_batch(route, texts, query=False):
    """Send one bounded batch through a currently configured, verified-free route."""
    from . import provider_budget
    from .llm_gateway import _retry_after, _transient, assert_private_runtime, current_operation

    require_provider_calls()
    assert_private_runtime()
    if not isinstance(route, EmbeddingRoute) or route not in configured_embedding_routes() or not route.available():
        raise EmbeddingRouteUnavailable('Embedding route is unavailable.')
    if not texts:
        return []
    sanitized = [sanitize_text(text) for text in texts]
    bound = _input_bound(route, sanitized, query)
    url, headers, body = _request(route, sanitized, query)
    attempt = provider_budget.reserve_attempt(current_operation(), route, bound, output_tokens=0)

    started = time.monotonic()
    try:
        if route.provider == 'openrouter':
            response = _openrouter_response(url, headers, body)
        else:
            with httpx.Client(timeout=60, transport=httpx.HTTPTransport(retries=0), trust_env=False) as client:
                response = client.post(url, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
        vectors = _vectors(route, payload, len(sanitized))
    except Exception as error:
        provider_budget.record_attempt_result(attempt, 'failed', max(0, int((time.monotonic() - started) * 1000)))
        status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        if status == 429:
            provider_budget.record_route_cooldown(route, _retry_after(error))
        if status in (408, 429) or (status is not None and status >= 500) or isinstance(error, httpx.TransportError) or _transient(error):
            raise EmbeddingRetryable('Embedding provider is temporarily unavailable.') from None
        raise EmbeddingRouteUnavailable('Embedding provider request failed.') from None
    provider_budget.record_attempt_result(
        attempt, 'success', max(0, int((time.monotonic() - started) * 1000)),
        input_tokens=_reported_input(route, payload), output_tokens=0,
    )
    return vectors
