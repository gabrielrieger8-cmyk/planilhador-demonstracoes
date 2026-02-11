"""Configurações centralizadas e gerenciamento de API keys."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Thresholds para classificação de conteúdo
# ---------------------------------------------------------------------------
@dataclass
class ClassifierThresholds:
    """Limiares usados pelo classificador de conteúdo PDF."""

    # Proporção mínima de área ocupada por imagens para considerar "visual"
    image_area_ratio: float = 0.15
    # Número mínimo de tabelas detectadas para considerar "tabular"
    min_tables_for_complex: int = 1
    # Proporção mínima de texto para considerar "texto predominante"
    text_density_ratio: float = 0.60
    # Número mínimo de caracteres por página para considerar texto denso
    min_chars_per_page: int = 200


@dataclass
class ProcessingConfig:
    """Configurações de processamento."""

    # Modelo Gemini a ser utilizado
    gemini_model: str = "gemini-3-flash-preview"
    # Temperatura para geração do Gemini
    gemini_temperature: float = 0.1
    # Máximo de tokens na resposta do Gemini
    gemini_max_tokens: int = 200000
    # Timeout em segundos para chamadas de API
    api_timeout: int = 120
    # Thresholds do classificador
    thresholds: ClassifierThresholds = field(default_factory=ClassifierThresholds)


# Instância global de configuração
config = ProcessingConfig()


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