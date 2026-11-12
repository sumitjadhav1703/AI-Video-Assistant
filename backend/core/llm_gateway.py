"""Explicit, budgeted generation routes with no proxy or hidden retries."""
import json
import logging
import math
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from ..usage_limits import require_provider_calls
from . import provider_budget

MAX_TRANSCRIPT_CHARS = 40000
_OPERATION = ContextVar('provider_operation', default=None)
_KEYS = {'groq': 'GROQ_API_KEY', 'gemini': 'GEMINI_API_KEY', 'nvidia_nim': 'NVIDIA_API_KEY', 'openrouter': 'OPENROUTER_API_KEY', 'meta': 'META_API_KEY'}
_FIXED_MODELS = {'nvidia_nim': 'nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b', 'meta': 'meta/muse-spark-1.3'}
TASKS = ('title', 'summary', 'extract', 'chat')
# Reasoning that cannot be switched off spends small output caps: Meta needs ~350 tokens for a title.
_MIN_OUTPUT_TOKENS = {'meta': 512}
MAX_ROUTES = 8
_BASES = {'groq': 'https://api.groq.com/openai/v1', 'nvidia_nim': 'https://integrate.api.nvidia.com/v1', 'openrouter': 'https://openrouter.ai/api/v1', 'meta': 'https://api.meta.ai/v1'}
_ORDER = {'groq': 0, 'nvidia_nim': 1, 'openrouter': 2, 'gemini': 3, 'meta': 4}


@dataclass(frozen=True)
class Route:
    alias: str
    tier: str
    provider: str
    model: str
    api_key_env: str
    verified_free: bool
    input_limit_tokens: int
    rpm: int
    tpm: int
    rpd: int
    input_price_per_million: str | None = None
    output_price_per_million: str | None = None


def validate_transcript(transcript: str) -> None:
    if not isinstance(transcript, str) or len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise ValueError('Transcript exceeds the 40,000 character limit.')


def assert_private_runtime() -> None:
    from langchain_core.globals import get_debug, get_verbose
    if get_debug() or get_verbose():
        raise ValueError('Debug prompt logging must be disabled for private content')
    for name in ('LANGCHAIN_TRACING', 'LANGCHAIN_TRACING_V2', 'LANGSMITH_TRACING'):
        if os.getenv(name, '').strip().lower() not in ('', 'false', '0'):
            raise ValueError('Remote tracing must be disabled before processing private content')


@contextmanager
def operation_scope(job_id: str, *, owner: bool = False, allow_paid: bool = False, local_owner: bool = False):
    if not isinstance(job_id, str) or not job_id.strip() or len(job_id) > 200:
        raise ValueError('A bounded operation identity is required')
    assert_private_runtime()
    current = _OPERATION.get()
    if current is not None and current['job_id'] != job_id:
        raise RuntimeError('Cannot replace an active operation identity')
    from langsmith import tracing_context
    if any(type(flag) is not bool for flag in (owner, allow_paid, local_owner)) or ((allow_paid or local_owner) and not owner):
        raise ValueError('Owner-only provider access requires an owner grant')
    if current is not None and any(flag and not current[name] for name, flag in
                                   (('owner', owner), ('allow_paid', allow_paid), ('local_owner', local_owner))):
        raise RuntimeError('Cannot elevate an active operation grant')
    token = _OPERATION.set(current or {'job_id': job_id, 'owner': owner, 'allow_paid': allow_paid,
                                       'local_owner': local_owner, 'failed': {}})
    try:
        with tracing_context(enabled=False):
            yield
    finally:
        _OPERATION.reset(token)


def current_operation() -> str:
    job_id = _OPERATION.get()
    if job_id is None:
        raise RuntimeError('Provider calls require a durable operation scope')
    return job_id['job_id']


def owner_paid_operation() -> bool:
    operation = _OPERATION.get() or {}
    return bool(operation.get('owner') and operation.get('allow_paid'))


def local_owner_operation() -> bool:
    return (_OPERATION.get() or {}).get('local_owner', False)


def _routes() -> list[Route]:
    try:
        raw = json.loads(os.getenv('LLM_ROUTES_JSON', '[]'))
    except (TypeError, ValueError):
        raise ValueError('LLM_ROUTES_JSON must contain a route list') from None
    if not isinstance(raw, list) or not raw or len(raw) > MAX_ROUTES:
        raise ValueError('Configure explicit verified free model routes before generation')
    result = []
    for item in raw:
        if not isinstance(item, dict) or not set(Route.__annotations__) - {'input_price_per_million', 'output_price_per_million'} <= set(item) or set(item) - set(Route.__annotations__):
            raise ValueError('Model route fields are incomplete or unsupported')
        route = Route(**item)
        if any(not isinstance(getattr(route, name), str) for name in ('alias', 'tier', 'provider', 'model', 'api_key_env')):
            raise ValueError('Model route identifiers must be strings')
        if (not isinstance(route.alias, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', route.alias)
                or route.tier not in ('economy', 'strong') or route.provider not in _KEYS
                or type(route.verified_free) is not bool or route.api_key_env != _KEYS[route.provider]
                or not isinstance(route.model, str) or not route.model.startswith(route.provider + '/')
                or not re.fullmatch(r'[a-zA-Z0-9_./:-]+', route.model) or route.model.endswith('/')
                or any(type(getattr(route, name)) is not int or getattr(route, name) <= 0
                       for name in ('input_limit_tokens', 'rpm', 'tpm', 'rpd'))):
            raise ValueError('Model routes require exact supported providers and verified free budgets')
        ensure_route_compatible(route)
        if any(existing.alias == route.alias for existing in result):
            raise ValueError('Model route aliases must be unique')
        if any(existing.provider == route.provider and (existing.rpm, existing.tpm, existing.rpd) !=
               (route.rpm, route.tpm, route.rpd) for existing in result):
            raise ValueError('Routes on one provider must share provider budget ceilings')
        result.append(route)
    return sorted(result, key=lambda route: _ORDER[route.provider])


def ensure_route_compatible(route) -> None:
    if route.provider == 'groq':
        if (route.api_key_env != _KEYS['groq']
                or not re.fullmatch(r'groq/(?:[A-Za-z0-9][A-Za-z0-9_.-]*/)*[A-Za-z0-9][A-Za-z0-9_.-]*', route.model)):
            raise ValueError('Groq routes require a provider model ID and the expected key')
    if route.provider == 'gemini' and not re.fullmatch(
        r'gemini/gemini-(?:flash-latest|[0-9]+\.[0-9]+-flash(?:-lite)?(?:-[A-Za-z0-9-]+)?)', route.model,
    ):
        raise ValueError('Gemini generation requires an explicit Flash model')
    # OpenRouter also enforces max_price 0 on every request, so only ':free' variants can bill nothing.
    if route.provider == 'openrouter' and not re.fullmatch(r'openrouter/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:free', route.model):
        raise ValueError('OpenRouter routes require a :free model')
    if route.provider in _FIXED_MODELS and route.model != _FIXED_MODELS[route.provider]:
        raise ValueError('Unsupported fixed provider model')
    if route.provider == 'meta' and route.verified_free:
        raise ValueError('Meta route must be marked paid')
    if route.provider in _BASES and os.getenv('OPENAI_CUSTOM_HEADERS'):
        raise ValueError('Unset OPENAI_CUSTOM_HEADERS before using generation')


def _messages(value) -> list[BaseMessage]:
    from .guardrails import sanitize_text
    if isinstance(value, str):
        messages = [HumanMessage(content=value)]
    elif hasattr(value, 'to_messages'):
        messages = value.to_messages()
    elif isinstance(value, (list, tuple)) and all(isinstance(message, BaseMessage) for message in value):
        messages = value
    else:
        raise ValueError('Gateway accepts text or text chat messages only')
    clean = []
    for message in messages:
        if (not isinstance(message.content, str) or message.type not in ('system', 'human', 'ai')
                or (isinstance(message, AIMessage) and (message.tool_calls or message.invalid_tool_calls
                                                       or message.additional_kwargs.get('function_call')))):
            raise ValueError('Gateway accepts plain text messages without tool calls')
        clean.append(type(message)(content=sanitize_text(message.content)))
    return clean


def _transient(error: Exception) -> bool:
    name = type(error).__name__.lower()
    status = getattr(error, 'status_code', None)
    if status in (408, 429):
        return True
    if any(word in name for word in ('quota', 'budget', 'guardrail', 'refusal', 'contentpolicy', 'contextwindow')):
        return False
    if type(status) is int:
        return 500 <= status <= 599
    return isinstance(error, (ConnectionError, TimeoutError)) or name in ('apiconnectionerror', 'apitimeouterror', 'timeoutexception', 'connecttimeout', 'readtimeout')


def private_litellm():
    os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
    os.environ['LITELLM_TELEMETRY'] = 'False'
    os.environ['LITELLM_LOG'] = 'CRITICAL'
    import litellm

    litellm.telemetry = False
    litellm.set_verbose = False
    litellm.suppress_debug_info = True
    litellm.turn_off_message_logging = True
    litellm.redact_messages_in_exceptions = True
    litellm.expose_router_debug_in_errors = False
    for name in ('LiteLLM', 'LiteLLM Router'):
        logging.getLogger(name).disabled = True
    for name in ('fallbacks', 'context_window_fallbacks', 'content_policy_fallbacks', 'default_fallbacks',
                 '_async_success_callback', '_async_failure_callback'):
        setattr(litellm, name, [])
    litellm.model_alias_map = {}
    litellm.callbacks = []
    litellm.success_callback = []
    litellm.failure_callback = []
    return litellm


def _invoke_route(route: Route, messages, temperature: float, timeout: float, max_output_tokens: int = 1024):
    ensure_route_compatible(route)
    litellm = private_litellm()
    api_key = os.getenv(route.api_key_env, '').strip()
    if not api_key:
        raise ValueError('Configured model route credentials are missing')
    params = {'model': route.model, 'api_key': api_key, 'timeout': timeout, 'max_retries': 0}
    api_base = _BASES.get(route.provider)
    if api_base:
        # The compatibility path uses the fixed host and a zero-retry OpenAI client.
        params.update(model='openai/' + route.model.split('/', 1)[1], api_base=api_base)
    router = litellm.Router(model_list=[{'model_name': route.alias, 'litellm_params': params}],
                           num_retries=0, max_fallbacks=0, fallbacks=[], context_window_fallbacks=[],
                           content_policy_fallbacks=[], disable_cooldowns=True, timeout=timeout)
    roles = {'human': 'user', 'ai': 'assistant', 'system': 'system'}
    payload = [{'role': roles[message.type], 'content': message.content} for message in messages]
    options = {'model': route.alias, 'messages': payload, 'temperature': temperature,
               'max_tokens': max_output_tokens, 'stream': False}
    if route.provider == 'groq' and '/gpt-oss-' in route.model:
        # Default reasoning spends small output caps (e.g. the 128-token title) and returns empty content.
        options['reasoning_effort'] = 'low'
    elif route.provider == 'nvidia_nim':
        options['extra_body'] = {'chat_template_kwargs': {'enable_thinking': False}}
    elif route.provider == 'openrouter':
        options['extra_body'] = {'provider': {'allow_fallbacks': False, 'max_price': {'prompt': 0, 'completion': 0, 'request': 0}},
                                 'reasoning': {'enabled': False}}
    elif route.provider == 'gemini':
        # Every gateway caller parses JSON; without native JSON mode Gemini answers chat in prose.
        options['response_format'] = {'type': 'json_object'}
        if route.model.startswith('gemini/gemini-2.5-'):
            # 2.5 thinking spends the output cap (a 128-token title came back as 'Here is the JSON').
            options['reasoning_effort'] = 'disable'
    elif route.provider == 'meta':
        options.pop('max_tokens')
        options.update(max_completion_tokens=max_output_tokens, reasoning_effort='minimal')
    import httpx
    from litellm.llms.custom_httpx.http_handler import HTTPHandler
    from openai import OpenAI, Omit

    model_id = route.model.split('/', 1)[1]
    base = httpx.URL(api_base) if api_base else None
    expected_host = base.host if base else 'generativelanguage.googleapis.com'
    expected_paths = ({base.path + '/chat/completions'} if base else
                      {f'/{version}/models/{model_id}:generateContent' for version in ('v1', 'v1alpha', 'v1beta')})
    sent = False
    retry_after_header = None
    wire_status = None

    def read_response(response):
        nonlocal retry_after_header, wire_status
        wire_status = response.status_code
        if wire_status == 429:
            retry_after_header = response.headers.get('Retry-After', '')

    def check_request(request):
        nonlocal sent
        if (sent or request.method != 'POST' or request.url.scheme != 'https' or request.url.host != expected_host
                or request.url.port not in (None, 443) or request.url.path not in expected_paths or request.url.query):
            raise ValueError('Generation transport rejected an extra request or unexpected destination')
        sent = True

    # Bound wire requests even if a native adapter attempts to continue a response.
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout,
                      event_hooks={'request': [check_request], 'response': [read_response]}) as http_client:
        if api_base:
            client = OpenAI(api_key=api_key, base_url=api_base, http_client=http_client,
                            timeout=timeout, max_retries=0, organization='', project='', admin_api_key='',
                            default_headers={'OpenAI-Organization': Omit(), 'OpenAI-Project': Omit()})
        else:
            client = HTTPHandler(client=http_client)
        try:
            result = router.completion(**options, client=client)
        except Exception:
            # LiteLLM can discard Retry-After and infer a different status from the body.
            if wire_status is not None and 300 <= wire_status < 500:
                raise _ProviderHTTPError(wire_status, retry_after_header or '') from None
            raise
    choice, usage = result.choices[0], result.usage
    message = choice.message
    if getattr(message, 'tool_calls', None) or getattr(message, 'function_call', None):
        raise ValueError('Generation provider returned tool calls')
    tokens = ({'input_tokens': usage.prompt_tokens, 'output_tokens': usage.completion_tokens,
               'total_tokens': usage.total_tokens} if usage else None)
    return AIMessage(content=message.content or '', additional_kwargs={'refusal': getattr(message, 'refusal', None)},
                     response_metadata={'finish_reason': choice.finish_reason}, usage_metadata=tokens)


class _ProviderHTTPError(Exception):
    def __init__(self, status: int, header: str):
        super().__init__('Generation provider returned an HTTP error')
        self.status_code = status
        self.headers = {'retry-after': header}


def _retry_after(error):
    headers = getattr(getattr(error, 'response', None), 'headers', {}) or {}
    value = headers.get('retry-after', '') or (getattr(error, 'headers', None) or {}).get('retry-after', '')
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return max(1, min(86400, math.ceil(seconds)))
    except (ValueError, TypeError):
        pass
    try:
        date = parsedate_to_datetime(value)
        return max(1, min(86400, math.ceil((date - datetime.now(timezone.utc)).total_seconds())))
    except (ValueError, TypeError, OverflowError):
        return 60


class _UnusableOutput(ValueError):
    """Empty, truncated, refused or unparseable output: try the next route."""


class GuardedChat(Runnable):
    def __init__(self, routes: list[Route], temperature: float, max_output_tokens: int, validate=None):
        self.routes = routes
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.validate = validate

    def with_validator(self, validate):
        """Copy whose routes must also return content accepted by validate(content), else fall back."""
        return GuardedChat(self.routes, self.temperature, self.max_output_tokens, validate)

    def _output_cap(self, route):
        return min(1024, max(self.max_output_tokens, _MIN_OUTPUT_TOKENS.get(route.provider, 0)))

    def invoke(self, input, config=None, **kwargs) -> AIMessage:
        from .guardrails import sanitize_text
        require_provider_calls()
        assert_private_runtime()
        job_id = current_operation()
        callbacks = (config or {}).get('callbacks')
        has_callbacks = bool(callbacks) if isinstance(callbacks, (list, tuple)) else bool(
            callbacks and (getattr(callbacks, 'handlers', []) or getattr(callbacks, 'inheritable_handlers', [])))
        if kwargs or has_callbacks:
            raise ValueError('Gateway does not accept unreviewed request options or callbacks')
        messages = _messages(input)
        # UTF-8 bytes bound text tokens conservatively without downloading tokenizers.
        input_tokens = input_token_bound(messages)
        deadline = time.monotonic() + 60
        operation = _OPERATION.get()
        eligible = []
        retry_delays = []
        mixed_failure = False
        for route in self.routes:
            if not _eligible(route, operation):
                continue
            identity = (route.provider, route.model)
            if identity not in operation['failed']:
                eligible.append(route)
            else:
                retry_at = operation['failed'][identity]
                remaining_cooldown = retry_at - time.monotonic() if retry_at is not None else 0
                if remaining_cooldown <= 0:
                    mixed_failure = True
                else:
                    retry_delays.append(math.ceil(remaining_cooldown))
        for index, route in enumerate(eligible):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Generation deadline exceeded')
            try:
                output_cap = self._output_cap(route)
                attempt_id = provider_budget.reserve_attempt(job_id, route, input_tokens, output_tokens=output_cap)
            except provider_budget.RouteQuotaExceeded as error:
                retry_delays.append(error.retry_after)
                continue
            except provider_budget.RequestContextExceeded:
                mixed_failure = True
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Generation deadline exceeded')
            started = time.monotonic()
            try:
                routes_left = len(eligible) - index
                timeout = min(12, remaining / routes_left) if routes_left > 1 else remaining
                response = _invoke_route(route, messages, self.temperature, timeout, output_cap)
                if (not isinstance(response, AIMessage) or not isinstance(response.content, str)
                        or not response.content.strip() or response.tool_calls or response.invalid_tool_calls
                        or response.additional_kwargs.get('refusal')
                        or response.response_metadata.get('finish_reason') in ('content_filter', 'refusal', 'tool_calls', 'error')):
                    raise _UnusableOutput('Generation provider returned unsupported content')
                if self.validate is not None:
                    try:
                        self.validate(response.content)
                    except (ValueError, TypeError):
                        raise _UnusableOutput('Generation provider returned invalid structured output') from None
            except Exception as error:
                if type(attempt_id) is int:
                    provider_budget.record_attempt_result(attempt_id, 'failed', max(0, int((time.monotonic() - started) * 1000)))
                if isinstance(error, _UnusableOutput):
                    mixed_failure = True
                    continue
                if _transient(error):
                    identity = (route.provider, route.model)
                    if getattr(error, 'status_code', None) == 429:
                        delay = _retry_after(error)
                        provider_budget.record_route_cooldown(route, delay)
                        operation['failed'][identity] = time.monotonic() + delay
                        retry_delays.append(delay)
                    else:
                        operation['failed'][identity] = None
                        mixed_failure = True
                    continue
                # Auth, bad request, model removed: this route is broken for the job, so skip it from now on
                # and try the next one rather than failing the job.
                operation['failed'][(route.provider, route.model)] = None
                mixed_failure = True
                continue
            if type(attempt_id) is int:
                usage = getattr(response, 'usage_metadata', None) or {}
                provider_budget.record_attempt_result(attempt_id, 'success', max(0, int((time.monotonic() - started) * 1000)),
                                                      input_tokens=usage.get('input_tokens'), output_tokens=usage.get('output_tokens'))
            if time.monotonic() > deadline:
                raise RuntimeError('Generation deadline exceeded')
            safe_usage = ({name: response.usage_metadata[name] for name in ('input_tokens', 'output_tokens', 'total_tokens')}
                          if response.usage_metadata else None)
            return AIMessage(content=sanitize_text(response.content), usage_metadata=safe_usage,
                             response_metadata={'alias': route.alias, 'provider': route.provider,
                                                'model': route.model, 'tier': route.tier})
        if retry_delays and not mixed_failure:
            raise provider_budget.RouteQuotaExceeded(min(retry_delays))
        raise RuntimeError('No eligible generation route')


def _eligible(route: Route, operation) -> bool:
    if not os.getenv(route.api_key_env, '').strip():
        return False
    if route.provider == 'meta':
        if os.getenv('ENABLE_PAID_META', '').strip().lower() != 'true':
            return False
        # Public last resort stays inside provider_budget's paid caps (one attempt and $0.01 per job, $0.05 per day).
        if not ((operation['owner'] and operation['allow_paid']) or _flag('ENABLE_PUBLIC_PAID_FALLBACK')):
            return False
        if any(not isinstance(price, str) or not re.fullmatch(r'[0-9]{1,6}(?:\.[0-9]{1,6})?', price)
               for price in (route.input_price_per_million, route.output_price_per_million)):
            raise ValueError('Paid route prices must be bounded decimal strings')
        return True
    return route.verified_free and (route.provider != 'nvidia_nim' or operation['owner'] or _flag('ENABLE_NVIDIA_PUBLIC'))


def _flag(name: str) -> bool:
    return os.getenv(name, '').strip().lower() == 'true'


def _task_order(task: str | None, routes: list[Route]) -> list[Route]:
    """Preferred aliases for the task first, then every other route in default provider order."""
    if task is None:
        return routes
    if task not in TASKS:
        raise ValueError('Unsupported generation task')
    try:
        mapping = json.loads(os.getenv('LLM_TASK_ROUTES_JSON', '{}'))
    except (TypeError, ValueError):
        raise ValueError('LLM_TASK_ROUTES_JSON must map tasks to route aliases') from None
    known = {route.alias for route in _routes()}
    if (not isinstance(mapping, dict) or set(mapping) - set(TASKS)
            or any(not isinstance(aliases, list) or len(set(aliases)) != len(aliases)
                   or any(alias not in known for alias in aliases) for aliases in mapping.values())):
        raise ValueError('LLM_TASK_ROUTES_JSON must map known tasks to unique configured aliases')
    preferred = mapping.get(task, [])
    return sorted(routes, key=lambda route: (route.provider == 'meta',
                                             preferred.index(route.alias) if route.alias in preferred else len(preferred)))


def get_llm(temperature: float = 0.3, *, tier: str = 'economy', max_output_tokens: int = 1024,
            task: str | None = None) -> Runnable:
    require_provider_calls()
    assert_private_runtime()
    if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 1024:
        raise ValueError('Generation output ceiling must be between 1 and 1024 tokens')
    if tier not in ('economy', 'strong') or not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError('Unsupported generation tier or temperature')
    operation = _OPERATION.get() or {'owner': False, 'allow_paid': False}
    routes = [route for route in _routes() if route.tier == tier and _eligible(route, operation)]
    if not routes:
        raise ValueError('No eligible generation route configured for the requested tier')
    return GuardedChat(_task_order(task, routes), temperature, max_output_tokens)


def input_token_bound(messages) -> int:
    return sum(len(message.content.encode('utf-8')) + 64 for message in messages) + 64


def plain_schema(schema: type[BaseModel]) -> dict:
    """JSON schema without '$defs' references or metadata titles, which models echo back as fields."""
    raw = schema.model_json_schema()
    defs = raw.pop('$defs', {})

    def clean(node, in_properties=False):
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            return clean(defs[node['$ref'].rsplit('/', 1)[-1]])
        return {key: clean(value, key == 'properties') for key, value in node.items()
                if in_properties or not (key == 'title' and isinstance(value, str))}
    return clean(raw)


def structured_messages(system_prompt: str, text: str, schema: type[BaseModel]):
    from .guardrails import sanitize_text
    from langchain_core.messages import SystemMessage
    instruction = (system_prompt + '\nReturn only one JSON object holding the data itself (never the schema), '
                   'using exactly these fields: ' + json.dumps(plain_schema(schema), separators=(',', ':')))
    return [SystemMessage(content=instruction), HumanMessage(content=sanitize_text(text))]


def strip_json_fence(content: str) -> str:
    """Model JSON without a Markdown fence or a prose preamble ('Here is the JSON: {...}')."""
    content = re.sub(r'\A\s*```(?:json)?\s*\n(.*?)\n\s*```\s*\Z', r'\1', content, flags=re.DOTALL).strip()
    start, end = content.find('{'), content.rfind('}')
    if not content.startswith('{') and 0 <= start < end:
        return content[start:end + 1]
    return content


def structured_call(system_prompt: str, text: str, schema: type[BaseModel], *, temperature: float = 0.3,
                    max_output_tokens: int = 1024, task: str | None = None, check=None):
    """Schema-valid result; a route whose output fails the schema or check falls back to the next route."""
    def parse(content):
        parsed = schema.model_validate_json(strip_json_fence(content))
        if check is not None:
            check(parsed)
        return parsed

    assert_private_runtime()
    llm = get_llm(temperature, max_output_tokens=max_output_tokens, task=task).with_validator(parse)
    result = llm.invoke(structured_messages(system_prompt, text, schema))
    try:
        return parse(result.content)
    except ValueError:
        raise ValueError('Generation returned invalid structured output') from None
