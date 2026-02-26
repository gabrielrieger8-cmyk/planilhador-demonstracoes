"""Rota SSE para progresso em tempo real.

GET /progress/{job_id} — Server-Sent Events com estado atual.
POST /process/{job_id} — Inicia processamento em background.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import GEMINI_API_KEY, ANTHROPIC_API_KEY, logger
from app.jobs import JobProgress, jobs

router = APIRouter()


@router.post("/process/{job_id}")
async def start_processing(job_id: str):
    """Inicia processamento em background."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    if job.status == "processing":
        raise HTTPException(409, "Processamento já em andamento.")

    if not GEMINI_API_KEY:
        raise HTTPException(400, "GEMINI_API_KEY não configurada.")

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
