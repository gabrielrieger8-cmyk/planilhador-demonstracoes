"""Classificador de conteúdo PDF.

Analisa a estrutura de um PDF e determina a melhor estratégia de
processamento: texto (Docling), visual (Gemini) ou híbrido.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.utils.config import ClassifierThresholds, config, logger
from src.utils.pdf_analyzer import PDFAnalysis


class ContentType(str, Enum):
    """Tipo de conteúdo predominante no PDF."""

    TEXT = "text"
    VISUAL = "visual"
    HYBRID = "hybrid"


class ProcessingRoute(str, Enum):
    """Rota de processamento recomendada."""

    DOCLING = "docling"
    GEMINI = "gemini"
    HYBRID = "hybrid"


@dataclass
class ClassificationResult:
    """Resultado da classificação de um PDF."""

    content_type: ContentType
    route: ProcessingRoute
    confidence: float
    reasoning: str
    details: dict


def classify(analysis: PDFAnalysis) -> ClassificationResult:
    """Classifica um PDF e recomenda a rota de processamento.

    Usa as métricas extraídas pelo PDFAnalyzer para decidir se o PDF
    deve ser processado por texto (Docling), visualmente (Gemini),
    ou por ambos (híbrido).

    Args:
        analysis: Resultado da análise estrutural do PDF.

    Returns:
        ClassificationResult com a rota recomendada.
    """
    thresholds = config.thresholds
    scores = _compute_scores(analysis, thresholds)

    text_score = scores["text_score"]
    visual_score = scores["visual_score"]

    logger.info(
        "Scores de classificação — texto: %.2f, visual: %.2f",
        text_score,
        visual_score,
    )

    # Conteúdo escaneado → sempre Gemini
    if analysis.has_scanned_content:
        return ClassificationResult(
            content_type=ContentType.VISUAL,
            route=ProcessingRoute.GEMINI,
            confidence=0.95,
            reasoning="PDF contém conteúdo escaneado (imagens sem texto extraível).",
            details=scores,
        )

    # Decisão baseada em scores
    diff = abs(text_score - visual_score)

    if diff < 0.15:
        # Scores próximos → modo híbrido
        return ClassificationResult(
            content_type=ContentType.HYBRID,
            route=ProcessingRoute.HYBRID,
            confidence=0.6 + diff,
            reasoning=(
                f"Conteúdo misto: texto ({text_score:.2f}) e "
                f"visual ({visual_score:.2f}) equilibrados."
            ),
            details=scores,
        )

    if text_score > visual_score:
        return ClassificationResult(
            content_type=ContentType.TEXT,
            route=ProcessingRoute.DOCLING,
            confidence=min(0.95, 0.5 + diff),
            reasoning=(
                f"Texto predominante ({text_score:.2f} vs {visual_score:.2f}). "
                "Docling é suficiente."
            ),
            details=scores,
        )

    return ClassificationResult(
        content_type=ContentType.VISUAL,
        route=ProcessingRoute.GEMINI,
        confidence=min(0.95, 0.5 + diff),
        reasoning=(
            f"Conteúdo visual predominante ({visual_score:.2f} vs {text_score:.2f}). "
            "Gemini necessário para tabelas/imagens."
        ),
        details=scores,
    )


def _compute_scores(
    analysis: PDFAnalysis, thresholds: ClassifierThresholds
) -> dict:
    """Calcula scores de texto e visual para o PDF.

    Args:
        analysis: Análise estrutural do PDF.
        thresholds: Limiares de classificação.

    Returns:
        Dicionário com text_score, visual_score e métricas intermediárias.
    """
    # Score de texto: baseado em densidade de caracteres
    text_density = min(
        1.0,
        analysis.avg_chars_per_page / max(thresholds.min_chars_per_page * 5, 1),
    )

    # Score visual: baseado em imagens + tabelas + desenhos
    image_score = min(1.0, analysis.avg_image_area_ratio / thresholds.image_area_ratio)

    table_score = min(
        1.0, analysis.total_tables / max(thresholds.min_tables_for_complex * 3, 1)
    )

    # Páginas com desenhos vetoriais (gráficos)
    drawing_pages = sum(1 for p in analysis.pages if p.has_drawings)
    drawing_ratio = drawing_pages / max(analysis.total_pages, 1)

    visual_score = (image_score * 0.4) + (table_score * 0.4) + (drawing_ratio * 0.2)
    text_score = text_density * (1.0 - visual_score * 0.3)

    return {
        "text_score": round(text_score, 4),
        "visual_score": round(visual_score, 4),
        "text_density": round(text_density, 4),
        "image_score": round(image_score, 4),
        "table_score": round(table_score, 4),
        "drawing_ratio": round(drawing_ratio, 4),
        "total_pages": analysis.total_pages,
        "total_chars": analysis.total_chars,
        "total_images": analysis.total_images,
        "total_tables": analysis.total_tables,
        "has_scanned": analysis.has_scanned_content,
    }
