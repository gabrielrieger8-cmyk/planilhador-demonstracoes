"""FastAPI application — Planilhador de Demonstrações."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

import requests as http_requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import (
    DATABASE_URL, logger,
    GEMINI_MODELS, ALL_MODELS,
    CLASSIFIER_MODEL, EXTRACTOR_MODEL, FORMATTER_MODEL,
)
from app.models.database import init_db

load_dotenv()

AUTH_USERNAME = os.getenv("AUTH_USERNAME", "")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
AUTH_COOKIE_SECRET = os.getenv("AUTH_COOKIE_SECRET", "")
COOKIE_NAME = "mirar_session"
LOGIN_URL = "https://mirarprojetos.dev/login"

PORTAL_API_URL = os.getenv("PORTAL_API_URL", "http://127.0.0.1:5001")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
APP_NAME = "demo-contabil"


def _post_to_portal(endpoint, data):
    """Fire-and-forget POST to Portal internal API."""
    def _send():
        try:
            http_requests.post(
                f"{PORTAL_API_URL}/api/{endpoint}",
                json=data,
                headers={"X-Internal-Key": INTERNAL_API_KEY},
                timeout=5,
            )
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


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
        username = None
        # 1) Check SSO cookie
        cookie = request.cookies.get(COOKIE_NAME)
        username = verify_sso_cookie(cookie, AUTH_COOKIE_SECRET)
        if username:
            _post_to_portal("log", {
                "username": username, "app": APP_NAME,
                "action": "page_view", "detail": {"path": str(request.url.path)},
                "ip_address": request.client.host if request.client else None,
            })
            return await call_next(request)
        # 2) Check Basic Auth
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="ignore")
            if ":" in decoded:
                user, pwd = decoded.split(":", 1)
                if (secrets.compare_digest(user, AUTH_USERNAME)
                        and secrets.compare_digest(pwd, AUTH_PASSWORD)):
                    _post_to_portal("log", {
                        "username": user, "app": APP_NAME,
                        "action": "page_view", "detail": {"path": str(request.url.path)},
                        "ip_address": request.client.host if request.client else None,
                    })
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

# Cache-busting: hash dos arquivos estáticos calculado no startup
_static_version = ""


def _compute_static_version() -> str:
    """Gera hash curto baseado no conteúdo dos arquivos estáticos."""
    h = hashlib.md5()
    for f in sorted(STATIC_DIR.glob("*.*")):
        h.update(f.read_bytes())
    return h.hexdigest()[:8]


@app.on_event("startup")
def startup():
    global _static_version
    logger.info("Inicializando banco de dados...")
    init_db(DATABASE_URL)
    _static_version = _compute_static_version()
    logger.info("Planilhador de Demonstrações pronto. (static v=%s)", _static_version)


@app.get("/")
async def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("?v=HASH", f"?v={_static_version}")
    return Response(
        html,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/models")
async def get_models():
    """Retorna modelos disponíveis para cada etapa do pipeline."""
    all_options = [
        {"id": mid, "label": info["label"]}
        for mid, info in GEMINI_MODELS.items()
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


@app.post("/feedback")
async def feedback(body: dict):
    """Proxy feedback to Portal internal API."""
    _post_to_portal("feedback", {
        "app": APP_NAME,
        "rating": body.get("rating"),
        "missing_info": body.get("missing_info"),
        "context": body.get("context"),
    })
    return {"ok": True}


# Registra rotas
from app.routes.upload import router as upload_router  # noqa: E402
from app.routes.progress import router as progress_router  # noqa: E402
from app.routes.results import router as results_router  # noqa: E402

app.include_router(upload_router)
app.include_router(progress_router)
app.include_router(results_router)
