import sys
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sikai")

from config import settings
from db.client import init_db
from services.cache import init_cache
from api.auth import router as auth_router
from api.courses import router as courses_router
from api.tutor import router as tutor_router
from api.quiz import router as quiz_router
from api.progress import router as progress_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"Starting {settings.app_name} v{settings.app_version}")
    await init_db()
    await init_cache()
    log.info("✅ All systems ready!")
    yield
    log.info("Shutting down...")


app = FastAPI(
    title="सिकाइ Sikai API",
    version=settings.app_version,
    docs_url="/docs",
    lifespan=lifespan,
)

# ── CORS — allow ALL origins ───────────────────────────────────────
# Security is handled by JWT tokens, not CORS origin restrictions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Force CORS headers on EVERY response including errors ──────────
@app.middleware("http")
async def cors_and_timing(request: Request, call_next):
    # Handle preflight OPTIONS immediately
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            content={},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS,PATCH",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            },
        )

    start = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - start) * 1000, 2)

    # Force CORS headers on every response
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["X-Process-Time"] = f"{ms}ms"
    return response


# ── Global error handler with CORS headers ─────────────────────────
@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    import traceback
    log.error(f"Error [{request.method}] {request.url.path}: {exc}")
    log.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


app.include_router(auth_router,     prefix="/api/v1/auth",     tags=["Auth"])
app.include_router(courses_router,  prefix="/api/v1/courses",  tags=["Courses"])
app.include_router(tutor_router,    prefix="/api/v1/tutor",    tags=["AI Tutor"])
app.include_router(quiz_router,     prefix="/api/v1/quiz",     tags=["Quiz"])
app.include_router(progress_router, prefix="/api/v1/progress", tags=["Progress"])


@app.get("/")
async def root():
    return {"status": "running", "message": "नमस्ते! Sikai API is live 🇳🇵"}


@app.get("/health")
async def health():
    return {"status": "ok"}
