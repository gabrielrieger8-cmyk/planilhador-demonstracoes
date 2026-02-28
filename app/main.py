"""FastAPI application — Planilhador de Demonstrações."""

from __future__ import annotations

import base64
import os
import secrets
import hmac
import hashlib
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    DATABASE_URL, logger,
    GEMINI_MODELS, ANTHROPIC_MODELS, ALL_MODELS,
    CLASSIFIER_MODEL, EXTRACTOR_MODEL, FORMATTER_MODEL,
)
from app.models.database import init_db

load_dotenv()

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
AUTH_COOKIE_SECRET = os.getenv("AUTH_COOKIE_SECRET", "")
COOKIE_NAME = "mirar_session"
LOGIN_URL = "https://mirarprojetos.dev/login"


def verify_sso_cookie(cookie_value, secret):
    if not cookie_value or not secret:
        return None
    parts = cookie_value.split(":")
    if len(parts) != 3:
        return None
    username, expiry_str, signature = parts
    try:
        expiry = int(expiry_str)
    except ValueError:
        return None
    if time.time() > expiry:
        return None
    payload = f"{username}:{expiry_str}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return username


class SSOAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not AUTH_USERNAME:
            return await call_next(request)
        # 1) Check SSO cookie
        cookie = request.cookies.get(COOKIE_NAME)
        if verify_sso_cookie(cookie, AUTH_COOKIE_SECRET):
            return await call_next(request)
        # 2) Check Basic Auth
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="ignore")
            if ":" in decoded:
                user, pwd = decoded.split(":", 1)
                if (secrets.compare_digest(user, AUTH_USERNAME)
                        and secrets.compare_digest(pwd, AUTH_PASSWORD)):
                    return await call_next(request)
        # 3) Redirect browser or 401 for API
        accept = request.headers.get("Accept", "")
        if "text/html" in accept:
            return RedirectResponse(f"{LOGIN_URL}?next={request.url}")
        return Response(
            "Autenticacao necessaria",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Mirar Projetos"'},
        )


app = FastAPI(title="Planilhador de Demonstrações")
app.add_middleware(SSOAuthMiddleware)

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


@app.get("/models")
async def get_models():
    """Retorna modelos disponíveis para cada etapa do pipeline."""
    all_options = [
        {"id": mid, "label": info["label"]}
        for mid, info in ALL_MODELS.items()
    ]
    return {
        "classifier": all_options,
        "extractor": all_options,
        "formatter": all_options,
        "defaults": {
            "classifier": CLASSIFIER_MODEL,
            "extractor": EXTRACTOR_MODEL,
            "formatter": FORMATTER_MODEL,
        },
    }


# Registra rotas
from app.routes.upload import router as upload_router  # noqa: E402
from app.routes.progress import router as progress_router  # noqa: E402
from app.routes.results import router as results_router  # noqa: E402

app.include_router(upload_router)
app.include_router(progress_router)
app.include_router(results_router)
