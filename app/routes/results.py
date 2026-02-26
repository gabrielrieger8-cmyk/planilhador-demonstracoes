"""Rotas de resultados e downloads.

GET /results/{job_id} — Lista arquivos gerados.
GET /download/{job_id}/{filename} — Baixa arquivo individual.
GET /download-all/{job_id} — Baixa todos como ZIP.
"""

from __future__ import annotations

import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.jobs import jobs

router = APIRouter()


@router.get("/results/{job_id}")
async def results(job_id: str):
    """Lista CSVs e XLSXs gerados."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado.")

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


@router.get("/download/{job_id}/{filename}")
async def download(job_id: str, filename: str):
    """Baixa um CSV ou XLSX individual."""
    job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job não encontrado.")

    file_path = job.output_dir / filename
    if not file_path.exists():
        raise HTTPException(404, "Arquivo não encontrado.")

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


@router.get("/download-all/{job_id}")
async def download_all(job_id: str):
    """Baixa todos os CSVs e XLSXs como ZIP."""
    job = jobs.get(job_id)
    if not job or not job.output_dir:
        raise HTTPException(404, "Job não encontrado.")

    output_files = [
        f for f in job.output_dir.iterdir()
        if f.suffix.lower() in (".csv", ".xlsx")
    ]
    if not output_files:
        raise HTTPException(404, "Nenhum arquivo gerado.")

    zip_path = job.output_dir.parent / f"demonstracoes_{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for out_file in output_files:
            zf.write(out_file, out_file.name)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"demonstracoes_{job_id}.zip",
    )
