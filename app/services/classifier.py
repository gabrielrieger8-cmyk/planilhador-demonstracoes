"""Serviço de classificação de documentos contábeis.

Usa Gemini 2.0 Flash para classificar o tipo do documento e identificar
quais páginas contêm demonstrações financeiras úteis.
"""

from __future__ import annotations

import logging

from app.services.gemini_client import classificar_documento

logger = logging.getLogger("planilhador")

TIPOS_VALIDOS = {"balancete", "balanco_patrimonial", "dre"}


def classificar(pdf_path: str, api_key: str | None = None, model: str | None = None) -> dict:
    """Classifica um documento PDF e identifica demonstrações presentes.

    Envia o PDF completo para Gemini 2.0 Flash, que identifica todas
    as demonstrações e suas respectivas páginas.

    Args:
        pdf_path: Caminho para o arquivo PDF.
        api_key: Chave da API Gemini.

    Returns:
        Dict com: empresa, demonstracoes (list), custo_usd.
        Cada demonstracao tem: tipo, paginas (list[int]), periodo.
    """
    resultado = classificar_documento(pdf_path, api_key=api_key, model=model)

    confianca = resultado.get("confianca", 0.0)
    demonstracoes = resultado.get("demonstracoes", [])

    if confianca < 0.7:
        logger.warning(
            "Classificação incerta: confiança=%.2f. Nenhuma demonstração aceita.",
            confianca,
        )
        demonstracoes = []

    validas = []
    for demo in demonstracoes:
        tipo = demo.get("tipo", "")
        if tipo in TIPOS_VALIDOS:
            validas.append(demo)
        else:
            logger.warning("Demonstração com tipo inválido ignorada: %s", tipo)

    resultado["demonstracoes"] = validas

    logger.info(
        "Documento classificado: empresa=%s, %d demonstração(ões), confiança=%.2f, custo=$%.6f",
        resultado.get("empresa", "N/A"),
        len(validas),
        confianca,
        resultado.get("custo_usd", 0),
    )
    for demo in validas:
        logger.info(
            "  → %s: páginas %s, período=%s",
            demo.get("tipo"),
            demo.get("paginas", []),
            demo.get("periodo", "N/A"),
        )

    return resultado
