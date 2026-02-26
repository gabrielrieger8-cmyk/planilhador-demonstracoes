"""Rota de upload de PDFs.

POST /upload — Recebe PDFs e retorna job_id com info dos arquivos.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import fitz
from fastapi import APIRouter, HTTPException, UploadFile

from app.config import logger
from app.jobs import FileInfo, Job, JobProgress, jobs

router = APIRouter()


@router.post("/upload")
async def upload(files: list[UploadFile]):
    """Recebe PDFs e retorna job_id com info dos arquivos."""
    if not files:
        raise HTTPException(400, "Nenhum arquivo enviado.")

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

        file_infos.append(FileInfo(
            name=safe_filename,
            path=dest,
            pages=pages,
            size=len(content),
        ))

    if not file_infos:
        raise HTTPException(400, "Nenhum PDF válido enviado.")

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
