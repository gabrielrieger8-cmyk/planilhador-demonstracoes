"""Configurações centralizadas e gerenciamento de API keys.

Uso: cada entry point (app.py, cli.py, main.py) deve chamar configure()
uma vez antes de qualquer importação dos módulos core.

    from controladoria_core.utils.config import configure
    configure(project_root=Path(__file__).parent)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Diretórios (iniciam None; configure() seta tudo)
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path | None = None
DATA_DIR: Path | None = None
INPUT_DIR: Path | None = None
OUTPUT_DIR: Path | None = None
KNOWLEDGE_DIR: Path | None = None

# ---------------------------------------------------------------------------
# API Keys (lê do env imediatamente, configure() atualiza depois)
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

_configured: bool = False


def configure(
    project_root: Path | str,
    env_file: Path | str | None = None,
    knowledge_dir: Path | str | None = None,
) -> None:
    """Bootstrap: deve ser chamado UMA VEZ antes de usar o core.

    Args:
        project_root: Raiz do projeto consumidor.
                      data/input/ e data/output/ são criados abaixo.
        env_file: Caminho do .env. Default: project_root/.env.
        knowledge_dir: Diretório para referências RAG.
                       Default: project_root/../knowledge/ (raiz do monorepo).
    """
    global PROJECT_ROOT, DATA_DIR, INPUT_DIR, OUTPUT_DIR
    global KNOWLEDGE_DIR, GEMINI_API_KEY, _configured

    PROJECT_ROOT = Path(project_root)

    # Carrega .env
    env_path = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

    # Diretórios de dados
    DATA_DIR = PROJECT_ROOT / "data"
    INPUT_DIR = DATA_DIR / "input"
    OUTPUT_DIR = DATA_DIR / "output"
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Knowledge (compartilhado na raiz do monorepo por padrão)
    if knowledge_dir:
        KNOWLEDGE_DIR = Path(knowledge_dir)
    else:
        KNOWLEDGE_DIR = PROJECT_ROOT.parent / "knowledge"
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    # API key (relê após dotenv)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    _configured = True
    logger.info(
        "Core configurado: root=%s, knowledge=%s, api_key=%s",
        PROJECT_ROOT, KNOWLEDGE_DIR, "OK" if GEMINI_API_KEY else "AUSENTE",
    )


# ---------------------------------------------------------------------------
# Configuração de processamento (funciona sem configure())
# ---------------------------------------------------------------------------

@dataclass
class ProcessingConfig:
    """Configurações de processamento."""

    gemini_model: str = "gemini-2.0-flash"
    gemini_temperature: float = 0.1
    gemini_max_tokens: int = 200000
    api_timeout: int = 120


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
# Logging (sempre disponível, não precisa de configure())
# ---------------------------------------------------------------------------
def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna o logger principal do sistema."""
    _logger = logging.getLogger("projeto_balancetes")
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
