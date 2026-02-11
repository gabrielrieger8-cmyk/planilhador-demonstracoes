"""Configurações centralizadas e gerenciamento de API keys."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Diretórios
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"

INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Referência ao projeto irmão (extrator de PDFs)
BALANCETES_OUTPUT_DIR = PROJECT_ROOT.parent / "projeto_balancetes" / "data" / "output"

# Diretório compartilhado de empresas
EMPRESAS_DIR = PROJECT_ROOT.parent / "data" / "empresas"
EMPRESAS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")


# ---------------------------------------------------------------------------
# Configurações de análise
# ---------------------------------------------------------------------------
@dataclass
class AnalysisConfig:
    """Configurações de análise financeira."""

    # Modelo IA para relatório (selecionável no sidebar)
    ai_provider: str = "gemini"  # "gemini" ou "claude"
    gemini_model: str = "gemini-3-flash-preview"
    claude_model: str = "claude-sonnet-4-5-20250929"
    temperature: float = 0.3
    max_tokens: int = 8000
    api_timeout: int = 120
    # Modelo para classificação de contas
    classifier_model: str = "claude-sonnet-4-5-20250929"
    # Idioma do relatório
    language: str = "pt-BR"


config = AnalysisConfig()

# Modelos disponíveis para relatório (sidebar)
MODELOS_RELATORIO: dict[str, dict[str, str]] = {
    "Claude Sonnet 4.5": {"provider": "claude", "model": "claude-sonnet-4-5-20250929"},
    "Claude Opus": {"provider": "claude", "model": "claude-opus-4-6"},
    "Gemini 3 Pro": {"provider": "gemini", "model": "gemini-3-pro-preview"},
    "Gemini Flash": {"provider": "gemini", "model": "gemini-3-flash-preview"},
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna o logger principal."""
    _logger = logging.getLogger("projeto_analise")
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
