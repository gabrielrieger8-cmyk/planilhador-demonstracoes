"""Rota SSE para progresso em tempo real + controle de fila.

GET /progress/{job_id} — Server-Sent Events com estado atual.
POST /process/{job_id} — Inicia processamento em background.
POST /queue/reorder/{job_id} — Reordena fila de espera.
POST /queue/cancel/{job_id}/{file_idx} — Cancela arquivo da fila.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import (
    GEMINI_API_KEY, ANTHROPIC_API_KEY, ALL_MODELS,
    CLASSIFIER_MODEL, EXTRACTOR_MODEL, FORMATTER_MODEL, logger,
)
from app.jobs import JobProgress, jobs


class ProcessRequest(BaseModel):
    classifier: Optional[str] = None
    extractor: Optional[str] = None
    formatter: Optional[str] = None
    skip_format: bool = False
    formulas_dre: bool = False
    formulas_balanco: bool = True
    formulas_balancete: bool = False
    include_vba: bool = False


class ReorderRequest(BaseModel):
    order: list[int]

router = APIRouter()


@router.post("/process/{job_id}")
async def start_processing(job_id: str, body: ProcessRequest = ProcessRequest()):
    """Inicia processamento em background."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    if job.status == "processing":
        raise HTTPException(409, "Processamento já em andamento.")

    if not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY não configurada.")

    # Configura modelos (valida se existem no catálogo)
    models = {
        "classifier": body.classifier or CLASSIFIER_MODEL,
        "extractor": body.extractor or EXTRACTOR_MODEL,
        "formatter": body.formatter or FORMATTER_MODEL,
    }
    for stage, model_id in models.items():
        if model_id not in ALL_MODELS:
            raise HTTPException(400, f"Modelo inválido para {stage}: {model_id}")

    # Verifica se Anthropic API key está configurada quando necessário
    needs_anthropic = any(
        m.startswith("claude-") for m in models.values()
    )
    if needs_anthropic and not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY não configurada (modelo Anthropic selecionado).")

    job.models = models
    job.skip_format = body.skip_format
    job.include_vba = body.include_vba
    job.formula_opts = {
        "dre": body.formulas_dre,
        "balanco": body.formulas_balanco,
        "balancete": body.formulas_balancete,
    }
    job.status = "processing"
    job.completed = 0
    job.started_at = time.time()
    job.progress = [
        JobProgress(filename=fi.name, pages=fi.pages) for fi in job.files
    ]

    # Importa e roda pipeline em background
    from app.services.pipeline import process_job

    asyncio.get_event_loop().run_in_executor(None, process_job, job)

    return {"status": "started", "total_files": job.total}


@router.get("/progress/{job_id}")
async def progress_sse(job_id: str):
    """Server-Sent Events com progresso em tempo real."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    async def event_stream():
        last_snapshot = ""
        while True:
            elapsed = time.time() - job.started_at if job.started_at > 0 else 0

            # Snapshot da fila para incluir posição
            with job.queue_lock:
                queue_snapshot = list(job.queue)

            progress_list = []
            for idx, p in enumerate(job.progress):
                try:
                    qpos = queue_snapshot.index(idx) + 1
                except ValueError:
                    qpos = None
                progress_list.append({
                    "idx": idx,
                    "filename": p.filename,
                    "pages": p.pages,
                    "status": p.status,
                    "stage": p.stage,
                    "stage_detail": p.stage_detail,
                    "error": p.error,
                    "output_files": p.output_files,
                    "cost": p.cost,
                    "time": p.time,
                    "queue_position": qpos,
                })

            data = {
                "status": job.status,
                "completed": job.completed,
                "total": job.total,
                "elapsed": round(elapsed, 1),
                "progress": progress_list,
            }

            snapshot = json.dumps(data, ensure_ascii=False)
            if snapshot != last_snapshot:
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


@router.post("/queue/reorder/{job_id}")
async def reorder_queue(job_id: str, body: ReorderRequest):
    """Reordena a fila de espera."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    with job.queue_lock:
        current_set = set(job.queue)
        new_set = set(body.order)
        if new_set != current_set:
            raise HTTPException(
                400,
                f"Índices inválidos. Esperado: {sorted(current_set)}, recebido: {sorted(new_set)}",
            )
        job.queue = body.order

    return {"status": "ok", "queue": body.order}


@router.post("/queue/cancel/{job_id}/{file_idx}")
async def cancel_queued_file(job_id: str, file_idx: int):
    """Cancela um arquivo que está na fila (não em processamento)."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    with job.queue_lock:
        if file_idx not in job.queue:
            raise HTTPException(400, "Arquivo não está na fila.")
        job.queue.remove(file_idx)
        job.progress[file_idx].status = "cancelled"
        job.completed += 1

    return {"status": "cancelled", "file_idx": file_idx}
