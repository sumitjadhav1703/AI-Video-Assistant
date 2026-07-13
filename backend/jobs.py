import traceback

from .utils.audio_processor import process_input, cleanup
from .core.transcriber import transcribe_all
from .core.summarizer import summarize, generate_title
from .core.extractor import extract_action_items, extract_key_decisions, extract_questions
from .core.rag_engine import build_rag_chain
from . import db

# Step names double as the frontend's progress labels.
STEPS = ["audio", "transcript", "title", "summary", "extract", "rag"]


def run_job(job_id: str, source: str, language: str = "english", is_upload: bool = False) -> None:
    """
    Run the full pipeline for one job, recording progress in Postgres as it goes.
    Invoked from a FastAPI BackgroundTask — never inside a request/response cycle,
    since a full run takes minutes and Render would time the request out.
    """
    artifacts = []
    try:
        db.set_step(job_id, "audio")
        chunks, artifacts = process_input(source)

        db.set_step(job_id, "transcript")
        transcript = transcribe_all(chunks, language)

        db.set_step(job_id, "title")
        title = generate_title(transcript)

        db.set_step(job_id, "summary")
        summary = summarize(transcript)

        db.set_step(job_id, "extract")
        action_items = extract_action_items(transcript)
        decisions = extract_key_decisions(transcript)
        questions = extract_questions(transcript)

        db.set_step(job_id, "rag")
        build_rag_chain(transcript, job_id)

        db.finish_job(job_id, {
            "title": title,
            "transcript": transcript,
            "summary": summary,
            "action_items": action_items,
            "key_decisions": decisions,
            "open_questions": questions,
        })

    except Exception as e:
        traceback.print_exc()
        db.fail_job(job_id, str(e))

    finally:
        # Audio is transient by design: processed, then discarded. Nothing audio
        # related is ever written to the database or to durable storage.
        if is_upload and source:
            artifacts.append(source)
        cleanup(artifacts)
