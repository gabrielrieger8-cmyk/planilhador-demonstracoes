"""Conversor de Balancetes PDF para CSV — FastAPI backend.

Execute: python app.py
Acesse: http://localhost:8000
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF — para contar paginas
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.orchestrator import Orchestrator, OutputFormat
from src.utils.config import MODELOS_DISPONIVEIS, config, logger

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="Conversor de Balancetes")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """Info sobre um PDF enviado."""
    name: str
    path: Path
    pages: int = 0
    size: int = 0


@dataclass
class JobProgress:
    """Progresso de um arquivo individual."""
    filename: str
    pages: int = 0
    status: str = "pending"  # pending | processing | done | error
    stage: str = ""  # analyzing | extracting | exporting | classifying
    stage_detail: str = ""  # ex: "Lote 2/3 (páginas 6-10)"
    error: str | None = None
    output_files: list[str] = field(default_factory=list)
    cost: float = 0.0
    time: float = 0.0


@dataclass
class Job:
    """Representa um job de conversao."""
    id: str
    status: str = "uploaded"  # uploaded | converting | done | error
    files: list[FileInfo] = field(default_factory=list)
    progress: list[JobProgress] = field(default_factory=list)
    output_dir: Path | None = None
    total_pages: int = 0
    completed: int = 0
    total: int = 0
    error: str | None = None
    started_at: float = 0.0  # timestamp do inicio
    preview_data: dict[str, list[list[str]]] = field(default_factory=dict)


jobs: dict[str, Job] = {}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    """Serve a pagina principal."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.post("/upload")
async def upload(files: list[UploadFile]):
    """Recebe PDFs e retorna job_id com info dos arquivos."""
    if not files:
        raise HTTPException(400, "Nenhum arquivo enviado.")

    job_id = str(uuid.uuid4())[:8]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"conv_{job_id}_"))
    output_dir = tmp_dir / "output"
    output_dir.mkdir()

    file_infos: list[FileInfo] = []

    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            continue

        # Sanitiza nome do arquivo (remove caracteres problemáticos no Windows)
        safe_filename = f.filename.replace("/", "_").replace("\\", "_")
        dest = tmp_dir / safe_filename
        content = await f.read()

        if len(content) == 0:
            logger.warning("Arquivo vazio ignorado: %s", safe_filename)
            continue

        dest.write_bytes(content)
        logger.info("Upload: %s (%d bytes) -> %s", safe_filename, len(content), dest)

        # Conta paginas
        try:
            doc = fitz.open(str(dest))
            pages = len(doc)
            doc.close()
        except Exception as exc:
            logger.warning("Erro ao abrir PDF %s: %s", safe_filename, exc)
            pages = 0

        file_infos.append(FileInfo(
            name=safe_filename,
            path=dest,
            pages=pages,
            size=len(content),
        ))

    if not file_infos:
        raise HTTPException(400, "Nenhum PDF valido enviado.")

    total_pages = sum(fi.pages for fi in file_infos)

    job = Job(
        id=job_id,
        files=file_infos,
        output_dir=output_dir,
        total_pages=total_pages,
        total=len(file_infos),
    )
    jobs[job_id] = job

    return {
        "job_id": job_id,
        "files": [
            {"name": fi.name, "pages": fi.pages, "size": fi.size}
            for fi in file_infos
        ],
        "total_pages": total_pages,
        "estimated_cost": _estimate_cost(total_pages),
    }


@app.post("/convert/{job_id}")
async def convert(job_id: str, workers: int = 3):
    """Inicia conversao em background."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")

    if job.status == "converting":
        raise HTTPException(409, "Conversao ja em andamento.")

    workers = max(1, min(36, workers))

    job.status = "converting"
    job.completed = 0
    job.started_at = time.time()
    job.progress = [
        JobProgress(filename=fi.name, pages=fi.pages) for fi in job.files
    ]

    # Roda em background
    asyncio.get_event_loop().run_in_executor(
        None, _run_conversion, job, workers
    )

    return {"status": "started", "workers": workers}


@app.get("/progress/{job_id}")
async def progress_sse(job_id: str):
    """Server-Sent Events com progresso em tempo real."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")

    async def event_stream():
        import json

        last_snapshot = ""
        while True:
            elapsed = time.time() - job.started_at if job.started_at > 0 else 0

            data = {
                "status": job.status,
                "completed": job.completed,
                "total": job.total,
                "elapsed": round(elapsed, 1),
                "progress": [
                    {
                        "filename": p.filename,
                        "pages": p.pages,
                        "status": p.status,
                        "stage": p.stage,
                        "stage_detail": p.stage_detail,
                        "error": p.error,
                        "output_files": p.output_files,
                        "cost": p.cost,
                        "time": p.time,
                    }
                    for p in job.progress
                ],
            }

            snapshot = json.dumps(data, ensure_ascii=False)
            # Envia sempre (para atualizar elapsed timer) ou quando dados mudam
            if snapshot != last_snapshot or True:
                last_snapshot = snapshot
                yield f"data: {snapshot}\n\n"

                if job.status in ("done", "error"):
                    break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/results/{job_id}")
async def results(job_id: str):
    """Lista CSVs e XLSXs gerados."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")

    output_files = []
    if job.output_dir and job.output_dir.exists():
        for f in sorted(job.output_dir.iterdir()):
            if f.suffix.lower() in (".csv", ".xlsx"):
                ext = f.suffix.lower().lstrip(".")
                output_files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "type": ext,
                })

    total_cost = sum(p.cost for p in job.progress)
    total_time = sum(p.time for p in job.progress)

    return {
        "status": job.status,
        "files": output_files,
        "total_cost": round(total_cost, 6),
        "total_time": round(total_time, 2),
        "preview_data": job.preview_data,
    }


@app.get("/download/{job_id}/{filename}")
async def download(job_id: str, filename: str):
    """Baixa um CSV ou XLSX individual."""
    job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job nao encontrado.")

    file_path = job.output_dir / filename
    if not file_path.exists():
        raise HTTPException(404, "Arquivo nao encontrado.")

    media_types = {
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    media_type = media_types.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        str(file_path),
        media_type=media_type,
        filename=filename,
    )


@app.get("/download-all/{job_id}")
async def download_all(job_id: str):
    """Baixa todos os CSVs e XLSXs como ZIP."""
    job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job nao encontrado.")

    output_files = [
        f for f in job.output_dir.iterdir()
        if f.suffix.lower() in (".csv", ".xlsx")
    ]
    if not output_files:
        raise HTTPException(404, "Nenhum arquivo gerado.")

    zip_path = job.output_dir.parent / f"balancetes_{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for out_file in output_files:
            zf.write(out_file, out_file.name)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"balancetes_{job_id}.zip",
    )


@app.delete("/job/{job_id}/{filename}")
async def remove_file(job_id: str, filename: str):
    """Remove um PDF do job antes da conversao."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado.")

    if job.status == "converting":
        raise HTTPException(409, "Nao pode remover durante conversao.")

    for i, fi in enumerate(job.files):
        if fi.name == filename:
            fi.path.unlink(missing_ok=True)
            job.files.pop(i)
            job.total = len(job.files)
            job.total_pages = sum(f.pages for f in job.files)
            return {
                "removed": filename,
                "total_pages": job.total_pages,
                "estimated_cost": _estimate_cost(job.total_pages),
            }

    raise HTTPException(404, "Arquivo nao encontrado no job.")


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------

@app.get("/models")
async def get_models():
    """Retorna modelos disponíveis e qual está ativo."""
    return {
        "active": config.gemini_model,
        "models": {
            model_id: info["label"]
            for model_id, info in MODELOS_DISPONIVEIS.items()
        },
    }


@app.post("/set-model")
async def set_model(body: dict):
    """Altera o modelo Gemini ativo."""
    model_id = body.get("model", "")
    if model_id not in MODELOS_DISPONIVEIS:
        raise HTTPException(400, f"Modelo inválido: {model_id}")
    config.gemini_model = model_id
    logger.info("Modelo alterado para: %s", model_id)
    return {"active": model_id}


# ---------------------------------------------------------------------------
# Conversao em background
# ---------------------------------------------------------------------------

def _run_conversion(job: Job, max_workers: int) -> None:
    """Executa a conversao de PDFs em threads paralelas."""
    logger.info("Iniciando conversao: %d PDFs, %d workers", job.total, max_workers)

    def _process_one(idx: int, fi: FileInfo) -> tuple[int, dict[str, Any]]:
        """Worker: processa um PDF usando Orchestrator."""
        p = job.progress[idx]

        # Stagger: cada worker espera idx * 2s para evitar burst na API
        if idx > 0:
            delay = idx * 2
            p.stage = "queued"
            p.stage_detail = f"Aguardando {delay}s..."
            logger.info("Worker %d: aguardando %ds (stagger)", idx, delay)
            time.sleep(delay)

        p.stage = "processing"
        p.stage_detail = "Processando..."
        start = time.time()

        try:
            file_path = str(fi.path)
            logger.info("Worker %d: processando %s (path=%s, exists=%s)",
                        idx, fi.name, file_path, Path(file_path).exists())

            orch = Orchestrator()
            result = orch.process(
                file_path,
                output_format=OutputFormat.CSV,
                output_dir=job.output_dir,
            )
            elapsed = time.time() - start

            if result.success:
                return idx, {
                    "status": "done",
                    "output_files": [
                        Path(f).name for f in result.output_files
                        if f.endswith((".csv", ".xlsx"))
                    ],
                    "cost": result.estimated_cost,
                    "time": elapsed,
                    "preview_rows": result.details.get("preview_rows", []),
                }
            else:
                return idx, {
                    "status": "error",
                    "error": result.error or "Erro desconhecido",
                    "cost": 0.0,
                    "time": elapsed,
                }
        except Exception as exc:
            elapsed = time.time() - start
            return idx, {
                "status": "error",
                "error": str(exc),
                "cost": 0.0,
                "time": elapsed,
            }

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for p in job.progress:
                p.status = "processing"
                p.stage = "processing"
                p.stage_detail = "Processando..."

            future_to_idx = {
                executor.submit(_process_one, i, fi): i
                for i, fi in enumerate(job.files)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    _, info = future.result()
                except Exception as exc:
                    info = {"status": "error", "error": str(exc), "cost": 0.0, "time": 0.0}

                p = job.progress[idx]
                p.status = info["status"]
                p.error = info.get("error")
                p.output_files = info.get("output_files", [])
                p.cost = info.get("cost", 0.0)
                p.time = info.get("time", 0.0)
                p.stage = "done" if info["status"] == "done" else "error"
                p.stage_detail = ""
                job.completed += 1

                # Guarda preview data indexado pelo nome base do PDF
                preview_rows = info.get("preview_rows", [])
                if preview_rows:
                    base_name = job.files[idx].name.rsplit(".", 1)[0]
                    job.preview_data[base_name] = preview_rows

        job.status = "done"
        logger.info("Conversao concluida: %d/%d", job.completed, job.total)

    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        logger.error("Erro na conversao: %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _estimate_cost(total_pages: int) -> float:
    """Estima custo baseado no numero de paginas e modelo ativo.

    ~2000 tokens/pagina input, ~1500 tokens/pagina output (estimativa).
    Pricing varia conforme o modelo selecionado.
    """
    pricing = MODELOS_DISPONIVEIS.get(config.gemini_model, {})
    input_price = pricing.get("input_price", 0.15)
    output_price = pricing.get("output_price", 0.60)
    input_tokens = total_pages * 2000
    output_tokens = total_pages * 1500
    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    return round(cost, 4)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print()
    print("=" * 50)
    print("  Conversor de Balancetes")
    print("  http://localhost:8000")
    print("=" * 50)
    print()
    uvicorn.run(app, host="0.0.0.0", port=8000)
