"""FastAPI application — Planilhador de Demonstrações."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATABASE_URL, logger
from app.models.database import init_db

app = FastAPI(title="Planilhador de Demonstrações")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def startup():
    logger.info("Inicializando banco de dados...")
    init_db(DATABASE_URL)
    logger.info("Planilhador de Demonstrações pronto.")


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# Registra rotas
from app.routes.upload import router as upload_router  # noqa: E402
from app.routes.progress import router as progress_router  # noqa: E402
from app.routes.results import router as results_router  # noqa: E402

app.include_router(upload_router)
app.include_router(progress_router)
app.include_router(results_router)
