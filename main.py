import sys
import time
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

# Setup basic logging directly here — no utils needed
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
    log.info("All systems ready!")
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
