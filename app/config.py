"""Configurações e pricing dos modelos Anthropic + Gemini."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Carrega .env do diretório do projeto
_project_root = Path(__file__).resolve().parent.parent
_env_path = _project_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)


# ---------------------------------------------------------------------------
# Variáveis de ambiente
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_project_root / 'data.db'}")
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(_project_root / "uploads"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))

# ---------------------------------------------------------------------------
# Modelos e pricing (custo por 1M tokens)
# ---------------------------------------------------------------------------

GEMINI_MODELS: dict[str, dict] = {
    "gemini-2.0-flash": {
        "label": "Gemini 2.0 Flash",
        "input_price": 0.10,
        "output_price": 0.40,
    },
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash",
        "input_price": 0.15,
        "output_price": 3.50,
    },
}

ANTHROPIC_MODELS: dict[str, dict] = {
    "claude-haiku-4-5-20251001": {
        "label": "Haiku 4.5",
        "input_price": 0.80,
        "output_price": 4.0,
    },
}

# Modelos usados em cada etapa do pipeline (defaults)
CLASSIFIER_MODEL = "gemini-2.5-flash"
EXTRACTOR_MODEL = "gemini-2.5-flash"
FORMATTER_MODEL = "gemini-2.5-flash"

# Todos os modelos disponíveis (Gemini + Anthropic)
ALL_MODELS: dict[str, dict] = {**GEMINI_MODELS, **ANTHROPIC_MODELS}


def calcular_custo_gemini(usage: dict, modelo: str) -> float:
    """Calcula custo em USD para chamadas Gemini.

    Args:
        usage: Dict com input_tokens e output_tokens.
        modelo: ID do modelo Gemini.
    """
    pricing = GEMINI_MODELS.get(modelo, {})
    input_price = pricing.get("input_price", 0.15)
    output_price = pricing.get("output_price", 3.50)

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    custo = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return round(custo, 6)


def calcular_custo_anthropic(usage, modelo: str) -> float:
    """Calcula custo em USD para chamadas Anthropic.

    Considera prompt caching:
    - cache_read_input_tokens: 0.1x do preço de input
    - cache_creation_input_tokens: 1.25x do preço de input
    """
    pricing = ANTHROPIC_MODELS.get(modelo, {})
    input_price = pricing.get("input_price", 3.0)
    output_price = pricing.get("output_price", 15.0)

    input_tokens = getattr(usage, "input_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", 0)
    cache_read = getattr(usage, "cache_read_input_tokens", 0)
    cache_write = getattr(usage, "cache_creation_input_tokens", 0)

    regular_input = input_tokens - cache_read - cache_write

    custo_input = regular_input * input_price / 1_000_000
    custo_cache_read = cache_read * input_price * 0.1 / 1_000_000
    custo_cache_write = cache_write * input_price * 1.25 / 1_000_000
    custo_output = output_tokens * output_price / 1_000_000

    return round(custo_input + custo_cache_read + custo_cache_write + custo_output, 6)


# ---------------------------------------------------------------------------
# Estimativa de custo (tokens empíricos por página)
# ---------------------------------------------------------------------------

TOKENS_PER_PAGE = {
    "classifier": {"input_per_page": 1500, "output_fixed": 50},
    "extractor":  {"input_per_page": 1500, "output_per_page": 3000},
    "formatter":  {"input_per_page": 4000, "output_per_page": 4000},
}


def estimar_custo(total_pages: int, models: dict[str, str]) -> dict:
    """Estima custo por etapa baseado em tokens/página e pricing do modelo.

    Returns:
        Dict com custo estimado por etapa e total.
    """
    result = {}
    total = 0.0

    for stage, tpp in TOKENS_PER_PAGE.items():
        model_id = models.get(stage, "gemini-2.5-flash")
        pricing = ALL_MODELS.get(model_id, {})
        input_price = pricing.get("input_price", 0.15)
        output_price = pricing.get("output_price", 3.50)

        input_tokens = tpp.get("input_per_page", 0) * total_pages
        output_tokens = (
            tpp.get("output_per_page", 0) * total_pages
            + tpp.get("output_fixed", 0)
        )

        custo = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
        result[stage] = round(custo, 6)
        total += custo

    result["total"] = round(total, 6)
    return result


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    _logger = logging.getLogger("planilhador")
    if not _logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        _logger.addHandler(handler)
    _logger.setLevel(level)
    return _logger


logger = setup_logging()
