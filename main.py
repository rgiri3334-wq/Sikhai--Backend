import sys
import time
import logging
import traceback

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sikai")

# ── Step 1: Test each import individually ────────────────────────
log.info("=== SIKAI STARTUP DIAGNOSTICS ===")

def test_import(name, import_fn):
    try:
        import_fn()
        log.info(f"✅ OK: {name}")
        return True
    except Exception as e:
        log.error(f"❌ CRASH: {name}")
        log.error(f"   Error: {type(e).__name__}: {e}")
        log.error(f"   Traceback:\n{traceback.format_exc()}")
        return False

test_import("fastapi",           lambda: __import__("fastapi"))
test_import("bcrypt",            lambda: __import__("bcrypt"))
test_import("jose",              lambda: __import__("jose"))
test_import("pydantic",          lambda: __import__("pydantic"))
test_import("groq",              lambda: __import__("groq"))
test_import("supabase",          lambda: __import__("supabase"))
test_import("config",            lambda: __import__("config"))
test_import("db.models",         lambda: __import__("db.models"))
test_import("db.client",         lambda: __import__("db.client"))
test_import("services.auth_service", lambda: __import__("services.auth_service"))
test_import("api.auth",          lambda: __import__("api.auth"))
test_import("ai.prompts",        lambda: __import__("ai.prompts"))
test_import("ai.llm",            lambda: __import__("ai.llm"))
test_import("ai.course_engine",  lambda: __import__("ai.course_engine"))
test_import("ai.tutor_engine",   lambda: __import__("ai.tutor_engine"))
test_import("ai.quiz_engine",    lambda: __import__("ai.quiz_engine"))
test_import("api.courses",       lambda: __import__("api.courses"))
test_import("api.tutor",         lambda: __import__("api.tutor"))
test_import("api.quiz",          lambda: __import__("api.quiz"))
test_import("api.progress",      lambda: __import__("api.progress"))

log.info("=== DIAGNOSTICS COMPLETE ===")
log.info("If all OK above, proceeding to start server...")

# ── Step 2: Normal startup ────────────────────────────────────────
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

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
    description="Nepal's AI-powered learning platform",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = round((time.perf_counter() - start) * 1000, 2)
    response.headers["X-Process-Time"] = f"{duration}ms"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."}
    )


app.include_router(auth_router,     prefix="/api/v1/auth",     tags=["Auth"])
app.include_router(courses_router,  prefix="/api/v1/courses",  tags=["Courses"])
app.include_router(tutor_router,    prefix="/api/v1/tutor",    tags=["AI Tutor"])
app.include_router(quiz_router,     prefix="/api/v1/quiz",     tags=["Quiz"])
app.include_router(progress_router, prefix="/api/v1/progress", tags=["Progress"])


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
