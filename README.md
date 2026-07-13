# AI Video Assistant 🎬

AI Video Assistant is an intelligent pipeline that takes a YouTube URL or an uploaded audio/video file, transcribes it, generates summaries, extracts actionable items, and provides a RAG (Retrieval-Augmented Generation) chat interface to converse with the transcript.

The system is designed with a microservices architecture, separating a robust FastAPI backend from an interactive Streamlit frontend.

---

## 🏗️ Architecture Flow

```mermaid
graph TD
    %% Frontend Components
    subgraph Frontend [Streamlit App]
        UI[User Interface]
        Chat[RAG Chat Interface]
        UI -->|Upload File or YouTube URL| API_Start[POST /jobs]
        UI -->|Poll Status| API_Status[GET /jobs/{job_id}]
        UI -->|Fetch Results| API_Result[GET /jobs/{job_id}/result]
        Chat -->|Ask Question| API_Chat[POST /jobs/{job_id}/chat]
    end

    %% Backend Components
    subgraph Backend [FastAPI Backend]
        API[API Gateway]
        JobManager[Background Job Manager]
        AudioProc[Audio Processor & Chunking]
        Transcriber[Transcriber Router]
        LLM[Summarizer & Extractor]
        RAG[RAG Engine]

        API_Start --> API
        API_Status --> API
        API_Result --> API
        API_Chat --> API

        API --> JobManager
        JobManager --> AudioProc
        JobManager --> Transcriber
        JobManager --> LLM
        JobManager --> RAG
    end

    %% External Services
    subgraph External APIs
        YT[YouTube]
        Groq[Groq API - English Whisper]
        Sarvam[Sarvam API - Hinglish]
        Mistral[Mistral AI - LLM & Embeddings]
        Neon[(Neon Serverless Postgres)]
    end

    %% Data Flow
    AudioProc -.->|yt-dlp| YT
    Transcriber -.->|English| Groq
    Transcriber -.->|Hinglish| Sarvam
    LLM -.->|Mistral-small-latest| Mistral
    RAG -.->|Mistral-embed| Mistral
    JobManager -->|Status/Results| Neon
    RAG -->|pgvector chunks| Neon
```

---

## ✨ Features

- **Multi-Source Input:** Process public YouTube videos or directly upload audio/video files.
- **Dual-Language Transcription:** Support for English (via Groq Whisper) and Hinglish (via Sarvam AI).
- **Automated Insights:** Automatically generates a suitable title, comprehensive summary, action items, key decisions, and open questions.
- **Interactive RAG Chat:** Chat directly with the context of your meeting/video using Mistral AI.
- **Isolated Jobs:** Every job receives isolated processing and isolated vector storage to prevent context contamination.

---

## 🛠️ Technology Stack

### Backend
- **Framework:** FastAPI, Uvicorn
- **Audio Processing:** yt-dlp, pydub, ffmpeg
- **AI/LLM:** LangChain LCEL, Mistral AI (LLM & Embeddings), Groq (STT), Sarvam (STT)
- **Database & Vectors:** Neon (Serverless Postgres), pgvector, SQLAlchemy

### Frontend
- **Framework:** Streamlit

---

## ⚙️ Prerequisites

Before you start, make sure you have the following API keys and services available:
1. **Mistral API Key** - For embeddings and chat generation.
2. **Groq API Key** - For lightning-fast English transcription (using Whisper).
3. **Sarvam API Key** - For Hinglish speech-to-text.
4. **Neon Postgres Database** - A connection string (`DATABASE_URL`) to a database with the `pgvector` extension enabled.

*Note: For the backend to process audio, `ffmpeg` must be installed on your system. Docker handles this natively.*

---

## 🚀 Setup & Installation

### 1. Environment Configuration

Copy the example environment file and fill in your actual credentials.
**Never commit your `.env` file to version control.**

```bash
cp .env.example .env
```

Ensure `.env` contains:
- `MISTRAL_API_KEY`
- `GROQ_API_KEY`
- `SARVAM_API_KEY`
- `DATABASE_URL`
- `FRONTEND_ORIGIN` (Optional for local dev, needed for production CORS)
- `YT_DLP_COOKIES_PATH` (Optional, path to cookies to mitigate YouTube rate-limiting)

### 2. Backend Setup (Docker recommended)

The easiest way to run the backend locally with all system dependencies (like `ffmpeg`) is using Docker.

```bash
# Build the Docker image
docker build -t ai-video-backend .

# Run the container (reads from your .env file)
docker run -p 8000:8000 --env-file .env ai-video-backend
```

*Alternatively, run natively:*
```bash
cd backend
pip install -r requirements.txt
# Ensure ffmpeg is installed via your OS package manager
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Frontend Setup

In a separate terminal, install and run the Streamlit frontend.

```bash
cd frontend
pip install -r requirements.txt

# Run the Streamlit app
streamlit run app.py
```

*Note: The frontend expects the backend to be running at `http://localhost:8000` by default, or configured via `.streamlit/secrets.toml`.*

---

## ☁️ Deployment Strategy

This architecture is optimized for free-tier cloud deployment:

- **Backend:** Deploy the FastAPI app using the provided `Dockerfile` to a service like **Render** or Railway. The long-running nature of processing videos utilizes asynchronous background tasks to prevent HTTP timeouts.
- **Frontend:** Deploy the Streamlit app to **Streamlit Community Cloud** (requires setting the `BACKEND_URL` in Streamlit's secrets).
- **Database:** **Neon** Serverless Postgres perfectly handles the relational states and vector storage via `pgvector`.

---

## ⚠️ Known Limitations & Notes

- **YouTube Throttling:** Downloading from YouTube via datacenter IPs may fail with bot-detection. Using a `cookies.txt` file (configured via `YT_DLP_COOKIES_PATH`) mitigates this but does not guarantee success.
- **Ephemeral Storage:** Audio files are heavily chunked to fit API payload limits (e.g., Groq's 25MB cap) and are immediately deleted post-transcription. No raw audio is persistently stored.
