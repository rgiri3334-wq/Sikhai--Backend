# ============================================================
#  main.py — Sikai FastAPI Application
# ============================================================

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
import time

from config import settings
from utils.logger import setup_logging
from db.client import init_db
from services.cache import init_cache

# Route imports
from api.auth import router as auth_router
from api.courses import router as courses_router
from api.tutor import router as tutor_router
from api.quiz import router as quiz_router
from api.progress import router as progress_router


# ── Startup / Shutdown ──────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    await init_db()
    await init_cache()
    logger.success("✅ All systems ready — Sikai is live!")
    yield
    logger.info("👋 Shutting down Sikai...")


# ── App Instance ─────────────────────────────────────────────
app = FastAPI(
    title="सिकाइ Sikai API",
    description="Nepal's AI-powered learning platform — Backend API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Middleware ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Request Timing Middleware ─────────────────────────────────
@app.middleware("http")
async def add_process_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Process-Time"] = f"{duration}ms"
    if duration > 3000:
        logger.warning(f"⚠️  Slow request: {request.url.path} took {duration}ms")
    return response


# ── Global Error Handler ──────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."}
    )


# ── Routers ──────────────────────────────────────────────────
app.include_router(auth_router,     prefix="/api/v1/auth",     tags=["Auth"])
app.include_router(courses_router,  prefix="/api/v1/courses",  tags=["Courses"])
app.include_router(tutor_router,    prefix="/api/v1/tutor",    tags=["AI Tutor"])
app.include_router(quiz_router,     prefix="/api/v1/quiz",     tags=["Quiz"])
app.include_router(progress_router, prefix="/api/v1/progress", tags=["Progress"])


# ── Health Check ─────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "message": "नमस्ते! Sikai API is live 🇳🇵",
        "docs": "/docs"
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": settings.app_version}
