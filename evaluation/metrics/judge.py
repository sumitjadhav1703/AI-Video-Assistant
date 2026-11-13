"""Meta Model API judge for DeepEval with a hard spend cap.

Paid (standard tier, model muse-spark-1.3). Nothing here runs unless EVAL_ALLOW_PAID_JUDGE=1 and a
positive EVAL_JUDGE_BUDGET_USD are set. The API key is read from META_API_KEY and never logged,
echoed, written to disk or included in an exception message.
"""
import asyncio
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from deepeval.models import DeepEvalBaseLLM
from pydantic import BaseModel, ValidationError

from evaluation import config


class JudgeConfigError(RuntimeError):
    """The judge is not authorised or not configured; nothing was sent."""


class BudgetExceeded(RuntimeError):
    """The next call could push spend past the cap; it was not sent."""


class JudgeCallError(RuntimeError):
    """The provider call failed. The message never contains credentials."""


def _strip_fence(text):
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else ''
        text = text.rsplit('```', 1)[0]
    start, end = text.find('{'), text.rfind('}')
    return text[start:end + 1] if start >= 0 and end > start else text


def worst_case_cost(prompt_chars, max_output_tokens):
    # Pessimistic: assume 1 token per 3 characters of prompt (English averages ~4).
    return (math.ceil(prompt_chars / 3) * config.JUDGE_PRICE_INPUT
            + max_output_tokens * config.JUDGE_PRICE_OUTPUT) / 1_000_000


def actual_cost(usage, max_output_tokens, prompt_chars):
    if usage is None:
        return worst_case_cost(prompt_chars, max_output_tokens), None, None
    prompt_tokens = getattr(usage, 'prompt_tokens', None)
    completion = getattr(usage, 'completion_tokens', None) or 0
    details = getattr(usage, 'completion_tokens_details', None)
    reasoning = getattr(details, 'reasoning_tokens', None) or 0
    if prompt_tokens is None:
        return worst_case_cost(prompt_chars, max_output_tokens), None, None
    # Reasoning bills at the output rate; count it even if a provider reports it outside completion_tokens.
    output = max(completion, reasoning)
    return (prompt_tokens * config.JUDGE_PRICE_INPUT + output * config.JUDGE_PRICE_OUTPUT) / 1_000_000, prompt_tokens, output


class SpendLedger:
    """Run-scoped hard cap plus a persistent cumulative ledger (counts and cost only, no content)."""

    def __init__(self, budget_usd, path=config.LEDGER_FILE, run_id=None):
        if not isinstance(budget_usd, (int, float)) or budget_usd <= 0:
            raise JudgeConfigError('A positive judge budget is required.')
        self.budget = float(budget_usd)
        self.path = Path(path)
        self.run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.spent = 0.0
        self.reserved = 0.0
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._lock = threading.Lock()

    def reserve(self, amount):
        with self._lock:
            if self.spent + self.reserved + amount > self.budget:
                raise BudgetExceeded(f'Judge budget ${self.budget:.2f} would be exceeded '
                                     f'(spent ${self.spent:.4f}, in flight ${self.reserved:.4f}, next up to ${amount:.4f}).')
            self.reserved += amount

    def settle(self, reserved, cost, input_tokens, output_tokens):
        with self._lock:
            self.reserved -= reserved
            self.spent += cost
            self.calls += 1
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0
            self._write(cost, input_tokens, output_tokens)

    def _write(self, cost, input_tokens, output_tokens):
        data = json.loads(self.path.read_text()) if self.path.exists() else {'total_usd': 0.0, 'calls': 0, 'runs': {}}
        data['total_usd'] = round(data['total_usd'] + cost, 6)
        data['calls'] += 1
        run = data['runs'].setdefault(self.run_id, {'usd': 0.0, 'calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                                                   'model': config.JUDGE_MODEL, 'budget_usd': self.budget})
        run['usd'] = round(run['usd'] + cost, 6)
        run['calls'] += 1
        run['input_tokens'] += input_tokens or 0
        run['output_tokens'] += output_tokens or 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def summary(self):
        return {'run_id': self.run_id, 'budget_usd': self.budget, 'spent_usd': round(self.spent, 6), 'calls': self.calls,
                'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens}


def require_judge_authorisation(env=os.environ):
    if env.get('EVAL_ALLOW_PAID_JUDGE') != '1':
        raise JudgeConfigError('Set EVAL_ALLOW_PAID_JUDGE=1 to allow paid Meta judge calls.')
    try:
        budget = float(env.get('EVAL_JUDGE_BUDGET_USD', ''))
    except ValueError:
        raise JudgeConfigError('Set EVAL_JUDGE_BUDGET_USD to a positive dollar cap.') from None
    if not budget > 0:
        raise JudgeConfigError('Set EVAL_JUDGE_BUDGET_USD to a positive dollar cap.')
    if not env.get('META_API_KEY', '').strip():
        raise JudgeConfigError('META_API_KEY is not set in the environment.')
    return budget


class MetaJudge(DeepEvalBaseLLM):
    """DeepEval custom model over Meta's OpenAI-compatible chat completions endpoint."""

    def __init__(self, ledger, *, client=None, model=config.JUDGE_MODEL, json_schema=True,
                 max_output_tokens=config.JUDGE_MAX_COMPLETION_TOKENS, reasoning_effort=config.JUDGE_REASONING_EFFORT):
        if model.endswith('-contributor'):
            raise JudgeConfigError('The contributor tier trains on submitted content; use the standard model.')
        self.ledger = ledger
        self._client = client
        self.model_id = model
        self.json_schema = json_schema
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.latencies_ms = []
        super().__init__(model)

    def load_model(self):
        if self._client is None:
            from openai import OpenAI
            key = os.environ.get('META_API_KEY', '').strip()
            if not key:
                raise JudgeConfigError('META_API_KEY is not set in the environment.')
            self._client = OpenAI(api_key=key, base_url=config.JUDGE_BASE_URL, max_retries=0,
                                  timeout=config.JUDGE_TIMEOUT_SECONDS)
        return self._client

    def get_model_name(self):
        return f'meta/{self.model_id}'

    def _complete(self, prompt, schema):
        messages = [{'role': 'user', 'content': prompt}]
        options = {'model': self.model_id, 'messages': messages, 'max_completion_tokens': self.max_output_tokens,
                   'reasoning_effort': self.reasoning_effort}
        if schema is not None:
            if self.json_schema:
                options['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': schema.__name__, 'schema': schema.model_json_schema(), 'strict': False}}
            else:
                messages[0]['content'] = (prompt + '\n\nReturn only a JSON object matching this JSON schema:\n'
                                          + json.dumps(schema.model_json_schema()))
        reserve = worst_case_cost(len(messages[0]['content']), self.max_output_tokens)
        self.ledger.reserve(reserve)
        started = time.perf_counter()
        response = None
        try:
            response = self.model.chat.completions.create(**options)
        except Exception as error:
            status = getattr(error, 'status_code', None)
            # A rejected request (4xx before generation) is not billed; anything else is charged pessimistically.
            charged = 0.0 if status is not None and 400 <= status < 500 and status != 429 else reserve
            self.ledger.settle(reserve, charged, None, None)
            if status == 400 and self.json_schema and schema is not None:
                self.json_schema = False  # provider rejected json_schema; fall back to prompt-confined JSON
                return self._complete(prompt, schema)
            raise JudgeCallError(f'Judge call failed: {type(error).__name__} status={status}') from None
        finally:
            self.latencies_ms.append(round((time.perf_counter() - started) * 1000))
        cost, input_tokens, output_tokens = actual_cost(getattr(response, 'usage', None), self.max_output_tokens,
                                                        len(messages[0]['content']))
        self.ledger.settle(reserve, cost, input_tokens, output_tokens)
        return (response.choices[0].message.content or '') if response.choices else ''

    def generate(self, prompt, schema: type[BaseModel] | None = None):
        text = self._complete(prompt, schema)
        if schema is None:
            return text
        for attempt in range(2):
            try:
                return schema.model_validate_json(_strip_fence(text))
            except (ValidationError, ValueError):
                if attempt:
                    raise JudgeCallError(f'Judge returned invalid JSON for {schema.__name__} after one retry.') from None
                text = self._complete(prompt + '\n\nYour previous reply was not valid JSON for the schema. '
                                               'Reply with the JSON object only.', schema)

    async def a_generate(self, prompt, schema: type[BaseModel] | None = None):
        return await asyncio.to_thread(self.generate, prompt, schema)

    def probe(self):
        """One tiny call: confirms auth, JSON-schema support and usage reporting. Costs well under $0.01."""
        class Probe(BaseModel):
            verdict: str

        result = self.generate('Reply with JSON {"verdict": "ok"}.', Probe)
        return {'model': self.get_model_name(), 'json_schema_supported': self.json_schema,
                'verdict': result.verdict, 'ledger': self.ledger.summary()}
