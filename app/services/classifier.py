"""Serviço de classificação de documentos contábeis.

Roteia entre Gemini e Anthropic conforme o modelo selecionado.
"""

from __future__ import annotations

import logging

from app.services.gemini_client import classificar_documento
from app.services.anthropic_client import classificar_documento_anthropic

logger = logging.getLogger("planilhador")

TIPOS_VALIDOS = {"balancete", "balanco_patrimonial", "dre"}


def classificar(pdf_path: str, api_key: str | None = None, model: str | None = None) -> dict:
    """Classifica um documento PDF e identifica demonstrações presentes.

    Roteia para Gemini ou Anthropic conforme o prefixo do modelo.

    Args:
        pdf_path: Caminho para o arquivo PDF.
        api_key: Chave da API.
        model: Modelo a usar (gemini-* ou claude-*).

    Returns:
        Dict com: empresa, demonstracoes (list), custo_usd.
    """
    if model and model.startswith("claude-"):
        resultado = classificar_documento_anthropic(pdf_path, model=model, api_key=api_key)
    else:
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
