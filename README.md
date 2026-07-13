<div align="center">

# 🎬 AI Video Assistant

**Transform your audio, video, and YouTube links into actionable insights with the power of LLMs & RAG.**

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=Streamlit&logoColor=white)](https://streamlit.io/)
[![Mistral](https://img.shields.io/badge/Mistral_AI-000?style=for-the-badge&logo=mistral)](https://mistral.ai/)
[![Neon](https://img.shields.io/badge/Neon-00E599?style=for-the-badge&logo=postgresql&logoColor=black)](https://neon.tech/)

</div>

AI Video Assistant is an intelligent pipeline that takes a YouTube URL or an uploaded audio/video file, transcribes it, generates summaries, extracts actionable items, and provides a RAG (Retrieval-Augmented Generation) chat interface to converse with the transcript.
The system is designed with a microservices architecture, separating a robust FastAPI backend from an interactive Streamlit frontend.

---

## 🏗️ Architecture Flow

```mermaid
flowchart TD
    %% Styling
    classDef frontend fill:#FF4B4B,stroke:#333,stroke-width:2px,color:#fff,rx:5px,ry:5px
    classDef backend fill:#005571,stroke:#333,stroke-width:2px,color:#fff,rx:5px,ry:5px
    classDef external fill:#2c3e50,stroke:#333,stroke-width:2px,color:#fff,rx:5px,ry:5px
    classDef database fill:#00E599,stroke:#333,stroke-width:2px,color:#000,rx:5px,ry:5px
    classDef apiEndpoint fill:#f39c12,stroke:#333,stroke-width:2px,color:#fff,rx:5px,ry:5px

    %% Nodes
    subgraph Frontend_App ["📱 Streamlit Frontend App"]
        direction TB
        UI["🖥️ User Interface"]:::frontend
        Chat["💬 RAG Chat Interface"]:::frontend
    end

    subgraph Backend_App ["⚙️ FastAPI Backend"]
        direction TB
        API_Start["🚀 POST /jobs"]:::apiEndpoint
        API_Status["⏳ GET /jobs/{id}"]:::apiEndpoint
        API_Result["✅ GET /jobs/{id}/result"]:::apiEndpoint
        API_Chat["💬 POST /jobs/{id}/chat"]:::apiEndpoint

        Gateway["🔌 API Gateway"]:::backend
        JobManager["📋 Job Manager"]:::backend
        AudioProc["🎵 Audio Processor"]:::backend
        Transcriber["✍️ Transcriber"]:::backend
        LLMEngine["🧠 LLM Engine"]:::backend
        RAGEngine["🔍 RAG Engine"]:::backend
    end

    subgraph External_Services ["🌐 External APIs & Services"]
        direction TB
        YT["▶️ YouTube"]:::external
        Groq["⚡ Groq API (English)"]:::external
        Sarvam["🗣️ Sarvam API (Hinglish)"]:::external
        Mistral["🤖 Mistral AI (LLM & Embed)"]:::external
        Neon[("🐘 Neon Postgres (pgvector)")]:::database
    end

    %% Connections
    UI -->|"Upload/URL"| API_Start
    UI -->|"Poll Status"| API_Status
    UI -->|"Fetch Results"| API_Result
    Chat -->|"Ask Question"| API_Chat

    API_Start --> Gateway
    API_Status --> Gateway
    API_Result --> Gateway
    API_Chat --> Gateway

    Gateway --> JobManager
    JobManager --> AudioProc
    JobManager --> Transcriber
    JobManager --> LLMEngine
    JobManager --> RAGEngine

    AudioProc -.->|"yt-dlp"| YT
    Transcriber -.->|"Whisper"| Groq
    Transcriber -.->|"Speech-to-Text"| Sarvam
    LLMEngine -.->|"Summarize/Extract"| Mistral
    RAGEngine -.->|"Embeddings"| Mistral
    JobManager -->|"Status/Results"| Neon
    RAGEngine <-->|"Vector Chunks"| Neon
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
