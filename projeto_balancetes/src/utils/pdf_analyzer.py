"""Analisador de PDFs usando PyMuPDF (fitz).

Extrai metadados estruturais de um PDF: contagem de texto, imagens,
dimensões de tabelas e métricas de densidade para alimentar o classificador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from src.utils.config import logger


@dataclass
class PageAnalysis:
    """Resultado da análise de uma página individual."""

    page_number: int
    char_count: int = 0
    word_count: int = 0
    image_count: int = 0
    image_area_ratio: float = 0.0
    table_count: int = 0
    has_drawings: bool = False


@dataclass
class PDFAnalysis:
    """Resultado consolidado da análise de um PDF."""

    file_path: str
    total_pages: int = 0
    total_chars: int = 0
    total_words: int = 0
    total_images: int = 0
    total_tables: int = 0
    avg_chars_per_page: float = 0.0
    avg_image_area_ratio: float = 0.0
    pages: list[PageAnalysis] = field(default_factory=list)
    has_scanned_content: bool = False
    metadata: dict = field(default_factory=dict)


def analyze_pdf(file_path: str | Path) -> PDFAnalysis:
    """Analisa um PDF e retorna métricas estruturais.

    Args:
        file_path: Caminho para o arquivo PDF.

    Returns:
        PDFAnalysis com todas as métricas extraídas.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
        RuntimeError: Se o PDF não puder ser aberto.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    logger.info("Analisando PDF: %s", path.name)

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise RuntimeError(f"Erro ao abrir PDF: {exc}") from exc

    analysis = PDFAnalysis(
        file_path=str(path),
        total_pages=len(doc),
        metadata=dict(doc.metadata) if doc.metadata else {},
    )

    pages_with_little_text = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_analysis = _analyze_page(page, page_num)
        analysis.pages.append(page_analysis)

        analysis.total_chars += page_analysis.char_count
        analysis.total_words += page_analysis.word_count
        analysis.total_images += page_analysis.image_count
        analysis.total_tables += page_analysis.table_count

        # Página com imagem mas pouco texto → possível scan
        if page_analysis.image_count > 0 and page_analysis.char_count < 50:
            pages_with_little_text += 1

    doc.close()

    # Médias
    if analysis.total_pages > 0:
        analysis.avg_chars_per_page = analysis.total_chars / analysis.total_pages
        image_ratios = [p.image_area_ratio for p in analysis.pages]
        analysis.avg_image_area_ratio = sum(image_ratios) / len(image_ratios)

    # Detecta conteúdo escaneado
    if analysis.total_pages > 0:
        scan_ratio = pages_with_little_text / analysis.total_pages
        analysis.has_scanned_content = scan_ratio > 0.5

    logger.info(
        "Análise concluída: %d páginas, %d chars, %d imagens, %d tabelas",
        analysis.total_pages,
        analysis.total_chars,
        analysis.total_images,
        analysis.total_tables,
    )

    return analysis


def _analyze_page(page: fitz.Page, page_num: int) -> PageAnalysis:
    """Analisa uma página individual do PDF.

    Args:
        page: Objeto fitz.Page.
        page_num: Número da página (0-indexed).

    Returns:
        PageAnalysis com métricas da página.
    """
    text = page.get_text()
    words = page.get_text("words")  # lista de (x0, y0, x1, y1, word, ...)
    images = page.get_images(full=True)

    # Área da página
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    # Calcula área total ocupada por imagens
    image_area = 0.0
    for img in images:
        xref = img[0]
        try:
            img_rects = page.get_image_rects(xref)
            for rect in img_rects:
                image_area += rect.width * rect.height
        except Exception:
            pass

    image_area_ratio = image_area / page_area if page_area > 0 else 0.0

    # Detecta tabelas usando heurística de linhas/retângulos
    table_count = _detect_tables(page)

    # Detecta desenhos vetoriais
    drawings = page.get_drawings()
    has_drawings = len(drawings) > 10  # threshold para gráficos vetoriais

    return PageAnalysis(
        page_number=page_num,
        char_count=len(text),
        word_count=len(words),
        image_count=len(images),
        image_area_ratio=image_area_ratio,
        table_count=table_count,
        has_drawings=has_drawings,
    )


def _detect_tables(page: fitz.Page) -> int:
    """Detecta tabelas em uma página usando heurística de linhas.

    Conta agrupamentos de linhas horizontais e verticais que formam
    padrões tabulares.

    Args:
        page: Objeto fitz.Page.

    Returns:
        Número estimado de tabelas na página.
    """
    drawings = page.get_drawings()
    horizontal_lines = 0
    vertical_lines = 0

    for drawing in drawings:
        for item in drawing.get("items", []):
            if item[0] == "l":  # line
                p1, p2 = item[1], item[2]
                dx = abs(p2.x - p1.x)
                dy = abs(p2.y - p1.y)
                if dx > 50 and dy < 3:
                    horizontal_lines += 1
                elif dy > 20 and dx < 3:
                    vertical_lines += 1

    # Heurística: muitas linhas H e V → provavelmente uma tabela
    if horizontal_lines >= 3 and vertical_lines >= 2:
        return max(1, min(horizontal_lines // 5, 5))

    # Fallback: tenta detectar via texto tabulado
    text = page.get_text()
    tab_lines = sum(1 for line in text.split("\n") if "\t" in line or "  " in line)
    if tab_lines > 5:
        return 1

    return 0


def extract_text(file_path: str | Path) -> str:
    """Extrai todo o texto de um PDF.

    Args:
        file_path: Caminho para o arquivo PDF.

    Returns:
        Texto completo do PDF.
    """
    path = Path(file_path)
    doc = fitz.open(str(path))
    full_text = []
    for page in doc:
        full_text.append(page.get_text())
    doc.close()
    return "\n".join(full_text)


def extract_pages_as_images(
    file_path: str | Path, dpi: int = 200
) -> list[bytes]:
    """Renderiza cada página do PDF como imagem PNG.

    Args:
        file_path: Caminho para o arquivo PDF.
        dpi: Resolução da imagem (default: 200).

    Returns:
        Lista de bytes PNG, uma por página.
    """
    path = Path(file_path)
    doc = fitz.open(str(path))
    images: list[bytes] = []
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        images.append(pix.tobytes("png"))

    doc.close()
    return images