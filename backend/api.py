import hmac
import hashlib
import re
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from starlette._utils import get_route_path
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.responses import JSONResponse

from . import db
from .jobs import run_job, STEPS, OWNER_EVALUATION_QUESTIONS
from .core.rag_engine import load_rag_chain, ask_question
from .core.audio_budget import profile_for_language
from .core.provider_budget import JobBudgetExceeded
from .core.reranker import load_ranker
from .core.retrieval import RetrievalUnavailable
from .core.guardrails import sanitize_text, GuardrailError
from .core.llm_gateway import operation_scope, get_llm
from .core.telemetry import metric
from .core.vector_store import get_embeddings
from .usage_limits import Settings, client_key, require_provider_calls, LimitExceeded, JobBusy, JobUnavailable

load_dotenv()
logger = logging.getLogger(__name__)
_COPY_CHUNK = 1024 * 1024
ADMIN_TOKEN = os.getenv('ADMIN_TOKEN', '').strip()
_UNAVAILABLE = 'Service is temporarily unavailable. Please try again later.'


def preflight_pipeline():
    get_llm()
    get_embeddings()
    load_ranker()


def demo_mode():
    mode = os.getenv('DEMO_LIVE_MODE', 'sample').strip().lower()
    if mode not in ('sample', 'invited', 'public'):
        raise ValueError('Invalid demo mode')
    return mode


def _job_secret():
    secret = os.getenv('JOB_TOKEN_SECRET', '').strip()
    if len(secret) < 32:
        raise ValueError('JOB_TOKEN_SECRET must be at least 32 characters')
    return secret.encode()


def _job_token(job_id, *, owner=False):
    expiry = str(int(time.time()) + 48 * 3600)
    payload = f'{expiry}.owner' if owner else expiry
    signature = hmac.new(_job_secret(), f'{job_id}.{payload}'.encode(), hashlib.sha256).hexdigest()
    return f'{payload}.{signature}'


def _job_audience(job_id, authorization):
    try:
        if not re.fullmatch(r'[0-9a-f]{32}', job_id) or not authorization.startswith('Bearer '):
            return None
        payload, signature = authorization[7:].rsplit('.', 1)
        owner = payload.endswith('.owner')
        expiry = payload.removesuffix('.owner')
        if not re.fullmatch(r'[0-9]{10}', expiry) or not re.fullmatch(r'[0-9a-f]{64}', signature):
            return None
        expected = hmac.new(_job_secret(), f'{job_id}.{payload}'.encode(), hashlib.sha256).hexdigest()
        if int(expiry) > int(time.time()) and hmac.compare_digest(signature, expected):
            return 'owner' if owner else 'demo'
    except (ValueError, OverflowError):
        pass
    return None


def _valid_owner_token(presented):
    token = os.getenv('OWNER_EVALUATION_TOKEN', '').strip()
    return bool(re.fullmatch(r'[A-Za-z0-9_-]{43,128}', token)
                and token not in (ADMIN_TOKEN, *(os.getenv(name, '').strip() for name in (
                    'JOB_TOKEN_SECRET', 'RATE_LIMIT_SECRET', 'DEMO_INVITE_CODE', 'ADMIN_TOKEN')))
                and hmac.compare_digest(presented.encode('latin-1'), token.encode('ascii')))


class RequestLimitsMiddleware:
    """Reject disabled inference and oversized bodies before multipart/JSON parsing."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = get_route_path(scope) if scope['type'] == 'http' else ''
        is_job = path == '/jobs' or path.startswith('/jobs/')
        if not is_job:
            return await self.app(scope, receive, send)

        async def no_store(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers', []).append((b'cache-control', b'no-store'))
            await send_original(message)

        send_original = send
        headers = scope.get('headers', [])
        def header(name):
            values = [v for k, v in headers if k.lower() == name]
            return values[0].decode('latin-1') if len(values) == 1 else ''

        owner_header = b'x-owner-evaluation'
        paid_header = b'x-owner-allow-paid'
        owner_requested = any(k.lower() == owner_header for k, _ in headers)
        paid_requested = any(k.lower() == paid_header for k, _ in headers)
        owner = owner_requested and _valid_owner_token(header(owner_header))
        allow_paid = owner and header(paid_header) == 'true'
        if path.startswith('/jobs/'):
            job_id = path.split('/')[2]
            audience = _job_audience(job_id, header(b'authorization'))
            if audience is None or (audience == 'owner' and not owner):
                return await JSONResponse({'detail': 'Job not found.'}, status_code=404)(scope, receive, no_store)
            if audience == 'demo' and (owner_requested or paid_requested):
                return await JSONResponse({'detail': 'Owner evaluation requires a new owner job.'}, status_code=403)(scope, receive, no_store)
        elif scope.get('method') == 'POST':
            if (owner_requested or paid_requested) and not owner:
                return await JSONResponse({'detail': 'Owner evaluation is unavailable.'}, status_code=403)(scope, receive, no_store)
            try:
                mode = demo_mode()
                _job_secret()
                invite = os.getenv('DEMO_INVITE_CODE', '').strip()
                if not owner and (mode == 'sample' or (mode == 'invited' and (len(invite) < 32 or not hmac.compare_digest(header(b'x-demo-invite').encode('latin-1'), invite.encode('utf-8'))))):
                    return await JSONResponse({'detail': 'Live processing is unavailable.'}, status_code=403)(scope, receive, no_store)
            except ValueError:
                return await JSONResponse({'detail': 'Live processing is unavailable.'}, status_code=503)(scope, receive, no_store)
        if path.startswith('/jobs/') and path.endswith('/chat') and scope.get('method') == 'POST':
            try:
                if demo_mode() == 'sample' and not owner:
                    return await JSONResponse({'detail': 'Live processing is unavailable.'}, status_code=403)(scope, receive, no_store)
            except ValueError:
                return await JSONResponse({'detail': 'Live processing is unavailable.'}, status_code=503)(scope, receive, no_store)
        protected = scope.get('method') == 'POST' and (path == '/jobs' or path.endswith('/chat'))
        if not protected:
            return await self.app(scope, receive, no_store)
        if paid_requested and not allow_paid:
            return await JSONResponse({'detail': 'Invalid paid evaluation opt-in.'}, status_code=400)(scope, receive, no_store)
        scope.setdefault('state', {}).update(owner_evaluation=owner, owner_allow_paid=allow_paid)
        send = no_store
        try:
            settings = Settings.from_env()
            require_provider_calls()
        except (ValueError, RuntimeError):
            return await JSONResponse({'detail': 'Processing is disabled until verified free-only provider access is configured.'}, status_code=503)(scope, receive, send)
        maximum = settings.max_upload_bytes + 64 * 1024 if path == '/jobs' and not owner else 8192
        lengths = [v for k, v in scope['headers'] if k == b'content-length']
        if lengths:
            try:
                length = int(lengths[0])
                if len(lengths) != 1 or length < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({'detail': 'Invalid content length.'}, status_code=400)(scope, receive, send)
            if length > maximum:
                return await JSONResponse({'detail': 'Request body is too large.'}, status_code=413)(scope, receive, send)
        if path == '/jobs' and not owner:
            try:
                preflight_pipeline()
            except (ValueError, RuntimeError):
                return await JSONResponse({'detail': 'Processing is disabled until verified free-only provider access is configured.'}, status_code=503)(scope, receive, send)
        received = 0
        body_started = body_finished = None

        async def bounded_receive():
            nonlocal received, body_started, body_finished
            if body_started is None:
                body_started = time.monotonic()
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > maximum:
                    raise HTTPException(413, 'Request body is too large.')
                if not message.get('more_body', False):
                    body_finished = time.monotonic()
            return message

        try:
            await self.app(scope, bounded_receive, send)
        finally:
            if path == '/jobs' and body_started is not None:
                metric('upload_body', bytes=received, complete=body_finished is not None,
                       elapsed_ms=round(((body_finished or time.monotonic()) - body_started) * 1000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    Settings.from_env()
    db.init_db()
    yield


app = FastAPI(title='AI Video Assistant', lifespan=lifespan)
app.add_middleware(RequestLimitsMiddleware)


_VALIDATION_MESSAGES = {
    ('body', 'question'): 'Enter a question with 1 to 1,000 characters.',
    ('body', 'tier'): 'Choose economy or strong.',
    ('body', 'language'): 'Choose english or hinglish.',
    ('body', 'file'): 'Provide an uploaded file.',
    ('body', 'youtube_url'): 'Provide the YouTube URL as text.',
    ('body', 'demo_acknowledged'): 'Use true or false for the privacy acknowledgement.',
    ('query', 'older_than_days'): 'Provide a whole number of days.',
}


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, error: RequestValidationError):
    # Pydantic errors can include the original input, exception context and input keys.
    details = []
    for item in error.errors():
        location = tuple(item.get('loc', ()))
        message = _VALIDATION_MESSAGES.get(location)
        details.append({
            'type': item['type'],
            'loc': list(location) if message else [],
            'msg': message or 'Check the request format and required fields.',
        })
    return JSONResponse({'detail': details}, status_code=422)


def allowed_origins() -> list[str]:
    raw = os.getenv('FRONTEND_ORIGIN', '').strip()
    return [o.strip() for o in raw.split(',') if o.strip()] if raw else ['http://localhost:5173']


app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_credentials=True,
                   allow_methods=['*'], allow_headers=['*'], expose_headers=['Retry-After'])


class ChatRequest(BaseModel):
    question: str = Field(max_length=1000)
    tier: Literal['economy', 'strong'] = 'economy'

    @field_validator('question', mode='before')
    @classmethod
    def question_not_blank(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError('Question is empty.')
        return value


def _database_call(function, *args):
    try:
        return function(*args)
    except LimitExceeded as error:
        raise HTTPException(429, str(error), headers={'Retry-After': str(error.retry_after)}) from None
    except JobUnavailable:
        raise HTTPException(404, 'Job not found.') from None
    except JobBusy:
        raise HTTPException(409, 'Job is active or not ready. Please try again later.') from None
    except Exception as error:
        logger.warning('database operation failed: %s', type(error).__name__)
        raise HTTPException(503, _UNAVAILABLE) from None


def _identity(request: Request, settings: Settings) -> str:
    # Proxy trust belongs in the ASGI server; never parse forwarding headers here.
    try:
        return client_key(request.client.host if request.client else None, settings.rate_limit_secret)
    except ValueError:
        raise HTTPException(503, _UNAVAILABLE) from None


def _release_slot(name, token):
    try:
        db.release_slot(name, token)
    except Exception as error:
        # Uncertain reservations remain occupied; do not risk overlapping workers.
        logger.warning('slot release failed: %s', type(error).__name__)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/ready')
def ready():
    _database_call(db.check_ready)
    return {'status': 'ok'}


@app.get('/demo-mode')
def get_demo_mode():
    try:
        mode = demo_mode()
        if mode != 'sample':
            require_provider_calls()
            _job_secret()
            if mode != 'invited' or len(os.getenv('DEMO_INVITE_CODE', '').strip()) >= 32:
                return {'mode': mode}
    except (ValueError, RuntimeError):
        pass
    return {'mode': 'sample'}


@app.post('/jobs')
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    youtube_url: str | None = Form(default=None),
    language: Literal['english', 'hinglish'] = Form(default='english'),
    file: UploadFile | None = File(default=None),
    demo_acknowledged: bool = Form(default=False),
):
    source = None
    token = None
    handed_off = False
    job_id = uuid.uuid4().hex
    form = await request.form()
    uploads = [value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)]
    try:
        settings = Settings.from_env()
        if not demo_acknowledged:
            raise HTTPException(422, 'Please acknowledge the privacy disclosure.')
        if request.state.owner_evaluation:
            if len(form.multi_items()) != 1 or set(form) != {'demo_acknowledged'} or uploads:
                raise HTTPException(400, 'Owner evaluation uses only the built-in synthetic transcript.')
            allow_paid = request.state.owner_allow_paid
            try:
                with operation_scope(job_id, owner=True, allow_paid=allow_paid):
                    preflight_pipeline()
            except (ValueError, RuntimeError):
                raise HTTPException(503, _UNAVAILABLE) from None
            job_capability = _job_token(job_id, owner=True)
            token = _database_call(db.admit_job, job_id, language, _identity(request, settings), settings)
            background_tasks.add_task(run_job, job_id, None, reservation_token=token, owner=True, allow_paid=allow_paid)
            handed_off = True
            return {'job_id': job_id, 'job_token': job_capability, 'status': 'queued',
                    'questions': OWNER_EVALUATION_QUESTIONS}
        if language != 'english' or youtube_url or file is None:
            raise HTTPException(400, 'Live demo accepts English file uploads only.')
        if len(uploads) > 1:
            raise HTTPException(400, 'Provide only one file.')
        try:
            require_provider_calls()
            profile_for_language(language)
        except (ValueError, RuntimeError):
            raise HTTPException(503, _UNAVAILABLE) from None
        job_capability = _job_token(job_id)
        token = _database_call(db.admit_job, job_id, language, _identity(request, settings), settings)
        fd, source = tempfile.mkstemp(suffix='.media')
        total = 0
        copy_started = time.monotonic()
        with os.fdopen(fd, 'wb') as out:
            while chunk := await file.read(_COPY_CHUNK):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(413, f'File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB).')
                out.write(chunk)
        metric('upload_copy', bytes=total, elapsed_ms=round((time.monotonic() - copy_started) * 1000))
        if not total:
            raise HTTPException(400, 'File is empty.')
        background_tasks.add_task(run_job, job_id, source, language, True, token)
        handed_off = True
        return {'job_id': job_id, 'job_token': job_capability, 'status': 'queued'}
    except HTTPException:
        raise
    except Exception as error:
        logger.warning('job admission failed: %s', type(error).__name__)
        raise HTTPException(503, _UNAVAILABLE) from None
    finally:
        if not handed_off:
            if file is not None and source:
                try:
                    os.remove(source)
                except OSError:
                    pass
            if token:
                try:
                    db.fail_job(job_id, 'Upload was interrupted. Please start a new job.')
                except Exception as error:
                    logger.warning('job failure update failed: %s', type(error).__name__)
                else:
                    _release_slot('processing', token)
        for uploaded in uploads:
            await uploaded.close()


@app.get('/jobs/{job_id}')
def job_status(job_id: str):
    job = _database_call(db.get_job_status, job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    return {'job_id': job_id, 'status': job['status'], 'step': job['step'], 'steps': STEPS, 'error': job['error']}


@app.get('/jobs/{job_id}/result')
def job_result(job_id: str):
    job = _database_call(db.get_job, job_id)
    if not job:
        raise HTTPException(404, 'Job not found.')
    if job['status'] == 'error':
        raise HTTPException(500, job['error'] or 'Job failed.')
    if job['status'] == 'interrupted':
        raise HTTPException(409, job['error'] or db.INTERRUPTED_MESSAGE)
    if job['status'] != 'done':
        raise HTTPException(409, 'Job is not finished.')
    try:
        return {'job_id': job_id, **{key: sanitize_text(job[key]) for key in (
            'title', 'transcript', 'summary', 'action_items', 'key_decisions', 'open_questions')}}
    except (GuardrailError, TypeError):
        raise HTTPException(503, _UNAVAILABLE) from None


@app.post('/jobs/{job_id}/chat')
def job_chat(job_id: str, body: ChatRequest, request: Request):
    owner = request.state.owner_evaluation
    if owner and body.question not in OWNER_EVALUATION_QUESTIONS:
        raise HTTPException(422, 'Choose a question supplied with the owner evaluation job.')
    try:
        question = sanitize_text(body.question)
    except GuardrailError:
        raise HTTPException(422, 'Question could not be processed.') from None
    if body.tier != 'economy' and not owner:
        raise HTTPException(422, 'Only economy is available in the live demo.')
    settings = Settings.from_env()
    token = _database_call(db.reserve_chat, job_id, _identity(request, settings), settings)
    try:
        with operation_scope(job_id, owner=owner, allow_paid=request.state.owner_allow_paid):
            chain = load_rag_chain(job_id, body.tier)
            result = ask_question(chain, question)
        citations = [{key: (sanitize_text(c[key]) if key == 'text' else c[key]) for key in ('chunk_id', 'text', 'start_ms', 'end_ms', 'timing_precision')} for c in result['citations']]
        retrieval = result.get('retrieval', {})
        model = result.get('model', {})
        return {'job_id': job_id, 'answer': sanitize_text(result['answer']), 'abstained': result['abstained'], 'citations': citations,
                'retrieval': {k: retrieval[k] for k in ('version', 'tokenization_version', 'dense_count', 'sparse_count', 'fused_count', 'final_count') if k in retrieval} if isinstance(retrieval, dict) else retrieval,
                'model': {k: model[k] for k in ('tier', 'alias', 'provider', 'model', 'route_alias') if k in model} if isinstance(model, dict) else model}
    except LimitExceeded as error:
        raise HTTPException(429, str(error), headers={'Retry-After': str(error.retry_after)}) from None
    except JobBudgetExceeded:
        raise HTTPException(409, 'This job has reached its processing budget. Start a new job with a shorter recording.') from None
    except RetrievalUnavailable:
        raise HTTPException(503, 'This session cannot be searched. Please create a new session.') from None
    except Exception as error:
        logger.warning('chat failed: %s', type(error).__name__)
        raise HTTPException(503, _UNAVAILABLE) from None
    finally:
        _release_slot('chat', token)


@app.delete('/jobs/{job_id}')
def delete_job(job_id: str):
    _database_call(db.delete_job, job_id)
    return {'job_id': job_id, 'deleted': True}


@app.post('/admin/cleanup')
def admin_cleanup(older_than_days: int = 1, x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(503, 'Cleanup is disabled — set ADMIN_TOKEN to enable it.')
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode('latin-1'), ADMIN_TOKEN.encode('utf-8')):
        raise HTTPException(401, 'Invalid or missing admin token.')
    if older_than_days < 0:
        raise HTTPException(400, 'older_than_days must be >= 0.')
    deleted = 0
    failed = False
    for job_id in _database_call(db.job_ids_older_than, older_than_days):
        try:
            _database_call(db.delete_job, job_id)
            deleted += 1
        except HTTPException as error:
            if error.status_code not in (404, 409):
                failed = True
    if failed:
        raise HTTPException(503, 'Cleanup was incomplete. Please retry.')
    return {'deleted': deleted, 'older_than_days': older_than_days}
