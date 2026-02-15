"""Configurações centralizadas e gerenciamento de API keys."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env
load_dotenv()

# ---------------------------------------------------------------------------
# Diretórios
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

# Garante que os diretórios existam
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")


@dataclass
class ProcessingConfig:
    """Configurações de processamento."""

    # Modelo Gemini a ser utilizado
    gemini_model: str = "gemini-2.0-flash"
    # Temperatura para geração do Gemini
    gemini_temperature: float = 0.1
    # Máximo de tokens na resposta do Gemini
    gemini_max_tokens: int = 200000
    # Timeout em segundos para chamadas de API
    api_timeout: int = 120


# Instância global de configuração
config = ProcessingConfig()

# Modelos disponíveis e pricing (custo por 1M tokens)
MODELOS_DISPONIVEIS: dict[str, dict] = {
    "gemini-2.0-flash": {
        "label": "Gemini 2 Flash",
        "input_price": 0.10,
        "output_price": 0.40,
    },
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash",
        "input_price": 0.15,
        "output_price": 3.50,
    },
    "gemini-3-flash-preview": {
        "label": "Gemini 3 Flash Preview",
        "input_price": 0.15,
        "output_price": 0.60,
    },
}

# Modelos para análise de referência (mais caprichados)
MODELOS_REFERENCIA: dict[str, dict] = {
    "gemini-2.5-flash": {
        "label": "Gemini 2.5 Flash",
        "input_price": 0.15,
        "output_price": 3.50,
    },
    "gemini-2.5-pro": {
        "label": "Gemini 2.5 Pro",
        "input_price": 1.25,
        "output_price": 10.00,
    },
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna o logger principal do sistema.

    Args:
        level: Nível de logging (default: INFO).

    Returns:
        Logger configurado.
    """
    logger = logging.getLogger("projeto_balancetes")
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


logger = setup_logging()