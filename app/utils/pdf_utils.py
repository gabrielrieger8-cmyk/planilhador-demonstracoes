"""Utilitários para manipulação de PDFs."""

from __future__ import annotations

import base64
from pathlib import Path

import fitz  # PyMuPDF


def get_pdf_pages(path: Path | str) -> int:
    """Retorna o número de páginas de um PDF."""
    doc = fitz.open(str(path))
    count = len(doc)
    doc.close()
    return count


def pdf_to_base64(path: Path | str) -> str:
    """Converte um arquivo PDF para string base64."""
    with open(str(path), "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def extract_pages(path: Path | str, pages: list[int]) -> bytes:
    """Extrai páginas específicas de um PDF como bytes.

    Args:
        path: Caminho para o PDF.
        pages: Lista de números de página (1-indexed).

    Returns:
        Bytes do novo PDF contendo apenas as páginas solicitadas.
    """
    doc = fitz.open(str(path))
    out = fitz.open()

    for page_num in sorted(pages):
        idx = page_num - 1
        if 0 <= idx < len(doc):
            out.insert_pdf(doc, from_page=idx, to_page=idx)

    pdf_bytes = out.tobytes()
    out.close()
    doc.close()
    return pdf_bytes


def pdf_bytes_to_base64(pdf_bytes: bytes) -> str:
    """Converte bytes de PDF para string base64."""
    return base64.standard_b64encode(pdf_bytes).decode("utf-8")


def extract_text_per_page(path: Path | str) -> list[str]:
    """Extrai texto OCR de cada página do PDF.

    Retorna lista indexada por página (0-indexed).
    Útil como guia OCR para o Gemini.
    """
    doc = fitz.open(str(path))
    texts = []
    for page in doc:
        texts.append(page.get_text("text") or "")
    doc.close()
    return texts
