"""In-memory job store para rastrear progresso de processamento."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileInfo:
    """Info sobre um PDF enviado."""
    name: str
    path: Path
    pages: int = 0
    size: int = 0
    db_file_id: int | None = None  # ID in Portal's uploaded_files table


@dataclass
class JobProgress:
    """Progresso de um arquivo individual."""
    filename: str
    pages: int = 0
    status: str = "pending"  # pending | processing | done | error | cancelled
    stage: str = ""  # classifying | extracting | formatting | validating | exporting
    stage_detail: str = ""
    error: str | None = None
    output_files: list[str] = field(default_factory=list)
    cost: float = 0.0
    time: float = 0.0


@dataclass
class Job:
    """Representa um job de processamento."""
    id: str
    status: str = "uploaded"  # uploaded | processing | done | error
    files: list[FileInfo] = field(default_factory=list)
    progress: list[JobProgress] = field(default_factory=list)
    output_dir: Path | None = None
    total_pages: int = 0
    completed: int = 0
    total: int = 0
    error: str | None = None
    started_at: float = 0.0
    skip_format: bool = False
    preview_data: dict[str, list[list[str]]] = field(default_factory=dict)
    models: dict[str, str] = field(default_factory=lambda: {
        "classifier": "gemini-2.5-flash",
        "extractor": "gemini-2.5-flash",
        "formatter": "gemini-2.5-flash",
    })
    # Fila gerenciada para controle de waitlist
    queue: list[int] = field(default_factory=list)
    queue_lock: threading.Lock = field(default_factory=threading.Lock)
    active_count: int = 0
    # Preferências de fórmulas por tipo de demonstração
    formula_opts: dict[str, bool] = field(default_factory=lambda: {
        "dre": True,
        "balanco": True,
        "balancete": False,
    })
    # Resultados por arquivo para consolidação multi-aba
    file_results: list[list[dict]] = field(default_factory=list)


# Store global
jobs: dict[str, Job] = {}
