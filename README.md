# सिकाइ Sikai — Backend + AI/ML Layer

## Stack (Zero Microsoft, Ultra Low Cost)

| Layer         | Technology                        | Monthly Cost     |
|---------------|-----------------------------------|------------------|
| Runtime       | Python 3.11 + FastAPI             | Free             |
| Database      | PostgreSQL via Supabase            | Free (500MB)     |
| Cache         | Redis (Upstash free tier)         | Free (10k req/d) |
| AI Model      | Groq API (Llama 3.3 70B)          | ~$0–5/mo         |
| Embeddings    | Nomic Embed (via Ollama or API)   | Free             |
| Vector Search | pgvector (built into Supabase)    | Free             |
| Auth          | Supabase Auth (JWT)               | Free             |
| Storage       | Supabase Storage (audio/files)    | Free (1GB)       |
| Deploy        | Railway / Render                  | Free tier        |

## Project Structure

```
sikai-backend/
├── main.py                  # FastAPI app entry point
├── config.py                # Environment & settings
├── requirements.txt         # Dependencies
├── .env.example             # Environment variables template
│
├── api/                     # Route handlers
│   ├── auth.py              # Register, login, JWT
│   ├── courses.py           # Course CRUD + generation
│   ├── tutor.py             # AI tutor chat endpoint
│   ├── quiz.py              # Quiz generation + submission
│   └── progress.py         # User progress tracking
│
├── ai/                      # AI/ML core
│   ├── llm.py               # Groq LLM client + prompt engine
│   ├── course_engine.py     # Topic → full course generator
│   ├── tutor_engine.py      # Chat tutor with memory
│   ├── quiz_engine.py       # Quiz + assessment generator
│   └── prompts.py           # All system prompts (Nepal-tuned)
│
├── db/                      # Database layer
│   ├── client.py            # Supabase client
│   ├── models.py            # Pydantic models / schemas
│   └── queries.py           # SQL query helpers
│
├── services/                # Business logic
│   ├── cache.py             # Redis caching layer
│   ├── auth_service.py      # JWT + user session logic
│   └── progress_service.py  # Learning analytics
│
└── utils/
    ├── logger.py            # Structured logging
    └── helpers.py           # Shared utilities
```

## Quick Start

```bash
cd sikai-backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # Fill in your keys
uvicorn main:app --reload --port 8000
```

API Docs: http://localhost:8000/docs
