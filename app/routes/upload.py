"""Rota de upload de PDFs.

POST /upload — Recebe PDFs e retorna job_id com info dos arquivos.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import date
from pathlib import Path

import fitz
from fastapi import APIRouter, HTTPException, UploadFile

from app.config import logger
from app.jobs import FileInfo, Job, JobProgress, jobs
from app.main import _post_to_portal, APP_NAME

STORAGE_BASE = Path("/home/gabriel/mirar-data/files")

router = APIRouter()


@router.post("/upload")
async def upload(files: list[UploadFile], existing_job_id: str | None = None):
    """Recebe PDFs e retorna job_id com info dos arquivos.

    Se existing_job_id for fornecido e o job existir, acumula os novos
    arquivos no job existente (em vez de criar um novo).
    """
    if not files:
        raise HTTPException(400, "Nenhum arquivo enviado.")

    # Accumulate files into existing job
    if existing_job_id and existing_job_id in jobs:
        job = jobs[existing_job_id]
        if job.status == "processing":
            raise HTTPException(409, "Nao pode adicionar durante processamento.")
        job_id = existing_job_id
        # Reuse existing tmp_dir from first file
        tmp_dir = job.files[0].path.parent if job.files else Path(tempfile.mkdtemp(prefix=f"plan_{job_id}_"))
        output_dir = job.output_dir
    else:
        job_id = str(uuid.uuid4())[:8]
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"plan_{job_id}_"))
        output_dir = tmp_dir / "output"
        output_dir.mkdir()

    file_infos: list[FileInfo] = []

    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            continue

        safe_filename = f.filename.replace("/", "_").replace("\\", "_")
        dest = tmp_dir / safe_filename
        content = await f.read()

        if len(content) == 0:
            logger.warning("Arquivo vazio ignorado: %s", safe_filename)
            continue

        dest.write_bytes(content)
        logger.info("Upload: %s (%d bytes)", safe_filename, len(content))

        try:
            doc = fitz.open(str(dest))
            pages = len(doc)
            doc.close()
        except Exception as exc:
            logger.warning("Erro ao abrir PDF %s: %s", safe_filename, exc)
            pages = 0

        # Save to permanent storage
        perm_dir = STORAGE_BASE / APP_NAME / date.today().isoformat()
        perm_dir.mkdir(parents=True, exist_ok=True)
        perm_path = perm_dir / f"{job_id}_{safe_filename}"
        shutil.copy2(str(dest), str(perm_path))

        # Register file in Portal DB (synchronous to get file_id back)
        import requests as http_requests
        import os
        db_file_id = None
        try:
            resp = http_requests.post(
                f"{os.getenv('PORTAL_API_URL', 'http://127.0.0.1:5001')}/api/files",
                json={
                    "app": APP_NAME,
                    "original_filename": safe_filename,
                    "stored_path": str(perm_path),
                    "file_size_bytes": len(content),
                    "mime_type": "application/pdf",
                },
                headers={"X-Internal-Key": os.getenv("INTERNAL_API_KEY", "")},
                timeout=5,
            )
            if resp.ok:
                db_file_id = resp.json().get("file_id")
        except Exception:
            pass

        file_infos.append(FileInfo(
            name=safe_filename,
            path=dest,
            pages=pages,
            size=len(content),
            db_file_id=db_file_id,
        ))

    if not file_infos:
        raise HTTPException(400, "Nenhum PDF válido enviado.")

    if existing_job_id and existing_job_id in jobs:
        # Append to existing job
        job = jobs[existing_job_id]
        job.files.extend(file_infos)
        job.total = len(job.files)
        job.total_pages = sum(f.pages for f in job.files)
    else:
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
        "total_pages": sum(fi.pages for fi in file_infos),
    }


@router.delete("/job/{job_id}/{filename}")
async def remove_file(job_id: str, filename: str):
    """Remove um PDF do job antes do processamento."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

    if job.status == "processing":
        raise HTTPException(409, "Não pode remover durante processamento.")

    for i, fi in enumerate(job.files):
        if fi.name == filename:
            fi.path.unlink(missing_ok=True)
            job.files.pop(i)
            job.total = len(job.files)
            job.total_pages = sum(f.pages for f in job.files)
            return {
                "removed": filename,
                "total_pages": job.total_pages,
            }

    raise HTTPException(404, "Arquivo não encontrado no job.")
