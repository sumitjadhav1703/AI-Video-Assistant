import logging
import time

from .utils.audio_processor import process_input, cleanup, MediaValidationError
from .core.transcriber import transcribe_segments
from .core.chunks import prepare_documents
from .core.guardrails import sanitize_text
from .core.llm_gateway import operation_scope
from .core.summarizer import summarize, generate_title, preflight_processing
from .core.extractor import extract_findings
from .core.rag_engine import build_rag_chain
from .db import delete_vector_store
from . import db
from .usage_limits import require_provider_calls, LimitExceeded
from .core.provider_budget import JobBudgetExceeded
from .core.telemetry import duration, metric

logger = logging.getLogger(__name__)

# Step names double as the frontend's progress labels.
STEPS = ["audio", "transcript", "title", "summary", "extract", "rag"]
OWNER_EVALUATION_QUESTIONS = (
    'How many seats are in the pilot?',
    'Who will verify the rollback checklist?',
    'What is the pilot budget?',
)
_OWNER_EVALUATION_SCRIPT = (
    'The pilot will start with twelve seats on Monday. The release team decided to keep the existing dashboard available during the pilot.',
    'The operations team will verify the rollback checklist on Friday. The support team will prepare a troubleshooting guide before the pilot starts.',
    'The team will review error counts after the first week. The support coverage for the second week is still undecided.',
)


def run_job(job_id: str, source: str | None, language: str = "english", is_upload: bool = False,
            reservation_token: str | None = None, *, owner: bool = False, allow_paid: bool = False,
            local_owner: bool = False) -> None:
    """
    Run the full pipeline for one job, recording progress in Postgres as it goes.
    Invoked from a FastAPI BackgroundTask — never inside a request/response cycle,
    since a full run takes minutes and Render would time the request out.
    """
    artifacts = []
    rag_started = False
    terminal_recorded = False
    started = time.monotonic()
    try:
        if owner and (source is not None or is_upload or language != 'english'):
            raise ValueError('Owner evaluation uses only the built-in synthetic transcript.')
        if (allow_paid or local_owner) and not owner:
            raise ValueError('This provider access requires owner evaluation.')
        require_provider_calls(sarvam=language == "hinglish")
        if not owner:
            db.set_step(job_id, "audio")
            with duration("media_processing"):
                chunks, artifacts = process_input(source)

        with operation_scope(job_id, owner=owner, allow_paid=allow_paid, local_owner=local_owner):
            db.set_step(job_id, "transcript")
            if owner:
                segments = [{'text': text, 'start_ms': None, 'end_ms': None, 'timing_precision': 'unknown'}
                            for text in _OWNER_EVALUATION_SCRIPT]
            else:
                with duration("transcription"):
                    segments = transcribe_segments(chunks, language)
            transcript = sanitize_text(' '.join(segment['text'].strip() for segment in segments if segment['text'].strip()))
            documents = prepare_documents(segments, job_id)
            metric("transcript", segments=len(segments), chunks=len(documents))
            preflight_processing(transcript, documents)

            db.set_step(job_id, "title")
            with duration("title"):
                title = generate_title(transcript)

            db.set_step(job_id, "summary")
            with duration("summary"):
                summary = summarize(transcript)

            db.set_step(job_id, "extract")
            with duration("extract"):
                findings = extract_findings(transcript)

            db.set_step(job_id, "rag")
            rag_started = True
            with duration("embedding_indexing"):
                build_rag_chain(transcript, job_id, documents=documents)
            metric("index", vectors=len(documents))

            db.finish_job(job_id, {
                "title": title,
                "transcript": transcript,
                "summary": summary,
                "action_items": findings["action_items"],
                "key_decisions": findings["key_decisions"],
                "open_questions": findings["open_questions"],
            })
            terminal_recorded = True
            metric("time_to_result", elapsed_ms=round((time.monotonic() - started) * 1000))

    except Exception as error:
        logger.warning('job failed: %s', type(error).__name__)
        message = str(error) if isinstance(error, (MediaValidationError, JobBudgetExceeded, LimitExceeded)) else 'Processing failed. Please start a new job later.'
        try:
            db.fail_job(job_id, message)
        except Exception as update_error:
            logger.warning('job failure update failed: %s', type(update_error).__name__)
        else:
            terminal_recorded = True
            # A lost commit acknowledgment can leave a completed job with a published index.
            if rag_started:
                try:
                    delete_vector_store(job_id)
                except Exception as cleanup_error:
                    logger.warning('partial vector cleanup failed: %s', type(cleanup_error).__name__)

    finally:
        # Audio is transient by design: processed, then discarded. Nothing audio
        # related is ever written to the database or to durable storage.
        if is_upload and source:
            artifacts.append(source)
        try:
            cleanup(artifacts)
        finally:
            if reservation_token and terminal_recorded:
                try:
                    db.release_slot('processing', reservation_token)
                except Exception as release_error:
                    # Keep an uncertain reservation busy; only explicit recovery may clear it.
                    logger.warning('processing slot release failed: %s', type(release_error).__name__)
            logger.info('job finished elapsed_seconds=%.3f', time.monotonic() - started)
