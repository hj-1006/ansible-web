import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.bootstrap import ensure_api_key
from app.config import settings, BASE_DIR
from app.database import SessionLocal, check_db_connection, init_db
from app.routers import devices, jobs, api_keys, monitoring
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        key = ensure_api_key(db)
        if key:
            print(f"\n[ansible-web] API 키: {key}\n")
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    description="Ansible 기반 네트워크 장비 제어 및 통신 테스트 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(devices.router)
app.include_router(monitoring.router)
app.include_router(jobs.router)
app.include_router(api_keys.router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/v1/health")
def health():
    db_ok = check_db_connection()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.app_name,
        "database": "ok" if db_ok else "error",
        "db_type": "mysql" if settings.is_mysql else "sqlite",
    }


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "ansible-web API", "docs": "/docs"}


@app.get("/docs-api")
def api_docs_redirect():
    return FileResponse(STATIC_DIR / "api-docs.html") if (STATIC_DIR / "api-docs.html").exists() else {"docs": "/docs"}
