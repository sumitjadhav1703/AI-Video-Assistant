"""Durable, pessimistic reservations: ambiguous provider attempts are never refunded."""
import json
import os
from decimal import Decimal, InvalidOperation
from collections import defaultdict

from ..usage_limits import LimitExceeded

BUDGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS provider_operation_budgets (
    job_id TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    input_tokens BIGINT NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens BIGINT NOT NULL DEFAULT 0 CHECK (output_tokens >= 0)
);
CREATE TABLE IF NOT EXISTS provider_attempts (
    id BIGSERIAL PRIMARY KEY,
    job_id TEXT NOT NULL,
    route_alias TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE provider_attempts ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'reserved';
ALTER TABLE provider_attempts ADD COLUMN IF NOT EXISTS elapsed_ms BIGINT;
ALTER TABLE provider_attempts ADD COLUMN IF NOT EXISTS reported_input_tokens BIGINT;
ALTER TABLE provider_attempts ADD COLUMN IF NOT EXISTS reported_output_tokens BIGINT;
ALTER TABLE provider_attempts ADD COLUMN IF NOT EXISTS estimated_cost NUMERIC NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0);
CREATE TABLE IF NOT EXISTS provider_route_cooldowns (
    route_alias TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    until_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (route_alias, provider, model)
);
CREATE INDEX IF NOT EXISTS provider_attempts_window ON provider_attempts(provider, created_at);
"""


class RouteQuotaExceeded(LimitExceeded):
    """A route or provider is unavailable without exhausting the job budget."""


class JobBudgetExceeded(ValueError):
    """A lifetime job budget cannot be renewed by waiting or retrying."""


class RequestContextExceeded(ValueError):
    """A single provider request exceeds its configured context."""


def provider_limits(route) -> tuple[int, int, int]:
    """Use the strictest configured account ceiling across all operations."""
    from .embedding_routes import configured_embedding_routes

    limits = [(route.rpm, route.tpm, route.rpd)]
    try:
        routes = json.loads(os.getenv('LLM_ROUTES_JSON', '[]'))
        if not isinstance(routes, list):
            raise ValueError()
        for item in routes:
            if not isinstance(item, dict):
                raise ValueError()
            if item.get('provider') == route.provider:
                limits.append(tuple(item[name] for name in ('rpm', 'tpm', 'rpd')))
        if 'EMBEDDING_ROUTES_JSON' in os.environ:
            limits.extend((embedding.rpm, embedding.tpm, embedding.rpd)
                          for embedding in configured_embedding_routes() if embedding.provider == route.provider)
        elif route.provider == 'gemini' and os.getenv('ENABLE_GEMINI_EMBEDDINGS', '').strip().lower() == 'true':
            limits.append(tuple(int(os.environ['GEMINI_EMBEDDINGS_' + name]) for name in ('RPM', 'TPM', 'RPD')))
        if any(type(value) is not int or value <= 0 for ceiling in limits for value in ceiling):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('Configured shared provider ceilings are invalid') from None
    return tuple(min(ceiling[index] for ceiling in limits) for index in range(3))


def _lock(cur):
    cur.execute('SELECT id FROM usage_guard WHERE id=1 FOR UPDATE')
    if cur.fetchone() is None:
        raise RuntimeError('Usage guard is missing')


def _job_usage(cur, job_id):
    cur.execute('SELECT attempts,input_tokens,output_tokens FROM provider_operation_budgets WHERE job_id=%s', (job_id,))
    return cur.fetchone() or {'attempts': 0, 'input_tokens': 0, 'output_tokens': 0}


def _check_job(used, attempts, input_tokens, output_tokens):
    if used['attempts'] + attempts > 24 or used['input_tokens'] + input_tokens > 60000 or used['output_tokens'] + output_tokens > 12000:
        raise JobBudgetExceeded('This recording exceeds the job processing budget. Start a new job with a shorter recording.')


def _check_provider(cur, route, requests, tokens):
    rpm, tpm, rpd = provider_limits(route)
    cur.execute("""SELECT
        COUNT(*) FILTER (WHERE created_at > clock_timestamp() - INTERVAL '60 seconds') AS rpm,
        COALESCE(SUM(input_tokens+output_tokens) FILTER
            (WHERE created_at > clock_timestamp() - INTERVAL '60 seconds'),0) AS tpm,
        COUNT(*) FILTER (WHERE created_at >= date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS rpd
        FROM provider_attempts WHERE provider=%s
        AND created_at >= LEAST(clock_timestamp() - INTERVAL '60 seconds',
            date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')""", (route.provider,))
    used = cur.fetchone()
    if used['rpm'] + requests > rpm or used['tpm'] + tokens > tpm or used['rpd'] + requests > rpd:
        raise RouteQuotaExceeded(60 if used['rpd'] + requests <= rpd else 86400)


def _check_cooldown(cur, route):
    cur.execute("""SELECT CEIL(EXTRACT(EPOCH FROM (until_at-clock_timestamp())))::integer AS seconds
                FROM provider_route_cooldowns WHERE route_alias=%s AND provider=%s AND model=%s
                AND until_at > clock_timestamp()""", (route.alias, route.provider, getattr(route, 'model', '')))
    row = cur.fetchone()
    if row:
        raise RouteQuotaExceeded(row['seconds'])


def record_route_cooldown(route, retry_after: int) -> None:
    from ..db import connect
    if type(retry_after) is not int or not 1 <= retry_after <= 86400:
        raise ValueError('Invalid route cooldown')
    with connect() as conn, conn.cursor() as cur:
        _lock(cur)
        cur.execute("""INSERT INTO provider_route_cooldowns(route_alias,provider,model,until_at)
                    VALUES (%s,%s,%s,clock_timestamp() + %s * INTERVAL '1 second')
                    ON CONFLICT (route_alias,provider,model) DO UPDATE
                    SET until_at=GREATEST(provider_route_cooldowns.until_at, EXCLUDED.until_at)""",
                    (route.alias, route.provider, getattr(route, 'model', ''), retry_after))
        conn.commit()


def _paid_cost(cur, job_id, route, input_tokens, output_tokens):
    if getattr(route, 'verified_free', True):
        return Decimal(0)
    try:
        prices = [Decimal(getattr(route, name)) for name in ('input_price_per_million', 'output_price_per_million')]
        if any(not price.is_finite() for price in prices) or prices[0] < Decimal('1.25') or prices[1] < Decimal('4.25'):
            raise ValueError()
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('Paid route requires reviewed pricing at or above the published price') from None
    cost = (prices[0] * input_tokens + prices[1] * output_tokens) / 1000000
    cost = cost.quantize(Decimal('0.000001'), rounding='ROUND_CEILING')
    cur.execute("""SELECT COUNT(*) FILTER (WHERE job_id=%s AND provider='meta') AS job_attempts,
        COALESCE(SUM(estimated_cost) FILTER (WHERE job_id=%s),0) AS job_cost,
        COALESCE(SUM(estimated_cost) FILTER (WHERE created_at >=
          date_trunc('day', clock_timestamp() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'),0) AS day_cost
        FROM provider_attempts""", (job_id, job_id))
    used = cur.fetchone()
    if used['job_attempts'] >= 1 or used['job_cost'] + cost > Decimal('0.01') or used['day_cost'] + cost > Decimal('0.05'):
        raise RouteQuotaExceeded(86400)
    return cost


def _validate_attempt(job_id, route, input_tokens, output_tokens):
    if not job_id or type(input_tokens) is not int or type(output_tokens) is not int or min(input_tokens, output_tokens) < 0:
        raise ValueError('Invalid operation reservation')
    if input_tokens + output_tokens > route.input_limit_tokens:
        raise RequestContextExceeded('Request exceeds configured model context budget')


def reserve_attempt(job_id: str, route, input_tokens: int, output_tokens: int = 1024) -> int:
    from ..db import connect
    _validate_attempt(job_id, route, input_tokens, output_tokens)
    with connect() as conn, conn.cursor() as cur:
        _lock(cur)
        _check_job(_job_usage(cur, job_id), 1, input_tokens, output_tokens)
        _check_cooldown(cur, route)
        _check_provider(cur, route, 1, input_tokens + output_tokens)
        cost = _paid_cost(cur, job_id, route, input_tokens, output_tokens)
        cur.execute('INSERT INTO provider_operation_budgets(job_id) VALUES (%s) ON CONFLICT DO NOTHING', (job_id,))
        cur.execute('''UPDATE provider_operation_budgets SET attempts=attempts+1,
                    input_tokens=input_tokens+%s,output_tokens=output_tokens+%s WHERE job_id=%s''',
                    (input_tokens, output_tokens, job_id))
        cur.execute('''INSERT INTO provider_attempts(job_id,route_alias,provider,input_tokens,output_tokens,estimated_cost)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING id''', (job_id, route.alias, route.provider, input_tokens, output_tokens, cost))
        attempt_id = cur.fetchone()['id']
        conn.commit()
        return attempt_id


def forecast_attempts(job_id: str, attempts: list[tuple], *, generation_stages=()) -> dict[str, int]:
    """Check mandatory calls and one available free route per generation stage."""
    from ..db import connect
    inputs = outputs = 0
    providers = defaultdict(lambda: [None, 0, 0])
    for route, input_tokens, output_tokens in attempts:
        try:
            _validate_attempt(job_id, route, input_tokens, output_tokens)
        except RequestContextExceeded:
            raise JobBudgetExceeded('This recording exceeds the configured model context. Use a shorter recording.') from None
        inputs += input_tokens
        outputs += output_tokens
        group = providers[route.provider]
        group[0], group[1], group[2] = route, group[1] + 1, group[2] + input_tokens + output_tokens
    with connect() as conn, conn.cursor() as cur:
        _lock(cur)
        for route, _, _ in attempts:
            _check_cooldown(cur, route)
        for route, requests, tokens in providers.values():
            _check_provider(cur, route, requests, tokens)
        count = len(attempts)
        for routes, input_tokens, output_tokens in generation_stages:
            failure = None
            for route in routes:
                if not getattr(route, 'verified_free', True):
                    continue
                try:
                    _validate_attempt(job_id, route, input_tokens, output_tokens)
                    _check_cooldown(cur, route)
                    group = providers[route.provider]
                    _check_provider(cur, route, group[1] + 1, group[2] + input_tokens + output_tokens)
                except (RouteQuotaExceeded, RequestContextExceeded) as error:
                    failure = error
                    continue
                group[0], group[1], group[2] = route, group[1] + 1, group[2] + input_tokens + output_tokens
                inputs += input_tokens
                outputs += output_tokens
                count += 1
                break
            else:
                if isinstance(failure, RouteQuotaExceeded):
                    raise failure
                raise JobBudgetExceeded('This recording exceeds the configured model context. Use a shorter recording.')
        _check_job(_job_usage(cur, job_id), count, inputs, outputs)
    return {'attempts': count, 'input_tokens': inputs, 'output_tokens': outputs}


def record_attempt_result(attempt_id: int, status: str, elapsed_ms: int, *,
                          input_tokens: int | None = None, output_tokens: int | None = None) -> None:
    """Store only bounded metadata; actual usage never refunds the reservation."""
    from ..db import connect
    if (type(attempt_id) is not int or attempt_id <= 0 or status not in ('success', 'failed')
            or type(elapsed_ms) is not int or elapsed_ms < 0
            or any(value is not None and (type(value) is not int or value < 0) for value in (input_tokens, output_tokens))):
        raise ValueError('Invalid provider attempt metadata')
    with connect() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE provider_attempts SET status=%s,elapsed_ms=%s,
                    reported_input_tokens=%s,reported_output_tokens=%s WHERE id=%s AND status='reserved'""",
                    (status, elapsed_ms, input_tokens, output_tokens, attempt_id))
        if cur.rowcount != 1:
            raise RuntimeError('Provider reservation metadata is missing or already completed')
        conn.commit()
