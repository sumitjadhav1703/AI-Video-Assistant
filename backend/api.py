import os
import tempfile
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
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
