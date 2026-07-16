import hmac
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .jobs import run_job, STEPS
from .core.rag_engine import load_rag_chain, ask_question
from .core.vector_store import delete_vector_store

load_dotenv()

# Cap uploads so an oversized file gets a clean 413 instead of exhausting the
# instance. 16kHz mono streaming keeps memory flat, but a multi-hour file still
# means a long run and many STT calls, so the ceiling stays modest.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
_COPY_CHUNK = 1024 * 1024  # 1MB reads keep the copy itself memory-flat

# Shared secret for the destructive /admin/cleanup endpoint. When unset the
# endpoint refuses every call, so cleanup is opt-in via the Render dashboard.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="AI Video Assistant", lifespan=lifespan)


def allowed_origins() -> list[str]:
    """
    Never wide open in production. FRONTEND_ORIGIN is a comma-separated list of
    exact origins (the deployed Streamlit URL); local dev falls back to Streamlit's
    default port only when the variable is absent.
    """
    raw = os.getenv("FRONTEND_ORIGIN", "").strip()
    if not raw:
        return ["http://localhost:8501"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    youtube_url: str | None = Form(default=None),
    language: str = Form(default="english"),
    file: UploadFile | None = File(default=None),
):
    """
    Start a run. Accepts EITHER a youtube_url or an uploaded file — a local file
    path is meaningless once the frontend and backend are on different machines.

    Returns a job_id immediately; the pipeline runs in the background. A full run
    takes minutes, which no single HTTP request should be holding open.
    """
    if not youtube_url and file is None:
        raise HTTPException(400, "Provide either youtube_url or file.")
    if youtube_url and file is not None:
        raise HTTPException(400, "Provide only one of youtube_url or file, not both.")

    job_id = uuid.uuid4().hex
    is_upload = file is not None

    if is_upload:
        suffix = os.path.splitext(file.filename or "")[1] or ".bin"
        fd, source = tempfile.mkstemp(suffix=suffix)
        # Stream to disk in bounded reads, aborting the moment the running total
        # crosses the cap — never buffer the whole upload in memory, and never
        # write an oversized file to disk.
        total = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := await file.read(_COPY_CHUNK):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB} MB). Trim it or upload audio-only.")
                    out.write(chunk)
        except HTTPException:
            os.remove(source)
            raise
    else:
        source = youtube_url

    db.create_job(job_id, language)
    background_tasks.add_task(run_job, job_id, source, language, is_upload)

    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return {
        "job_id": job_id,
        "status": job["status"],
        "step": job["step"],
        "steps": STEPS,
        "error": job["error"],
    }


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job["status"] == "error":
        raise HTTPException(500, job["error"] or "Job failed.")
    if job["status"] != "done":
        raise HTTPException(409, f"Job is not finished (status: {job['status']}).")

    return {
        "job_id": job_id,
        "title": job["title"],
        "transcript": job["transcript"],
        "summary": job["summary"],
        "action_items": job["action_items"],
        "key_decisions": job["key_decisions"],
        "open_questions": job["open_questions"],
    }


@app.post("/jobs/{job_id}/chat")
def job_chat(job_id: str, body: ChatRequest):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job["status"] != "done":
        raise HTTPException(409, "Job is not finished — nothing to chat with yet.")
    if not body.question.strip():
        raise HTTPException(400, "Question is empty.")

    # The chain is rebuilt from this job's own collection on every request, so it
    # survives a restart and can never read another job's vectors.
    chain = load_rag_chain(job_id)
    answer = ask_question(chain, body.question.strip())
    return {"job_id": job_id, "answer": answer}


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    delete_vector_store(job_id)
    db.delete_job_row(job_id)
    return {"job_id": job_id, "deleted": True}


@app.post("/admin/cleanup")
def admin_cleanup(
    older_than_days: int = 7,
    x_admin_token: str | None = Header(default=None),
):
    """
    Purge jobs older than `older_than_days` (their DB row + pgvector collection).
    Orphaned data accumulates when a session is closed without the normal release
    (e.g. a browser killed before the unload DELETE flushes). Gated behind
    ADMIN_TOKEN so it is never publicly callable.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(503, "Cleanup is disabled — set ADMIN_TOKEN to enable it.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Invalid or missing admin token.")
    if older_than_days < 0:
        raise HTTPException(400, "older_than_days must be >= 0.")

    job_ids = db.job_ids_older_than(older_than_days)
    deleted = 0
    for jid in job_ids:
        # Vectors first (best-effort — a job that failed before RAG has no
        # collection), then the row. One bad job never stalls the sweep.
        try:
            delete_vector_store(jid)
        except Exception as e:
            print(f"cleanup: could not drop vectors for {jid}: {e}")
        db.delete_job_row(jid)
        deleted += 1

    return {"deleted": deleted, "older_than_days": older_than_days}
