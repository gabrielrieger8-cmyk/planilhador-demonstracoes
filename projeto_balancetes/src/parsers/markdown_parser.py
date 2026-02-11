"""Parser de saída em formato Markdown."""

from __future__ import annotations

import re
from pathlib import Path

from src.utils.config import OUTPUT_DIR, logger


def save_as_markdown(
    text: str,
    filename: str,
    metadata: dict | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Salva o texto processado como arquivo Markdown.

    Args:
        text: Conteúdo em Markdown.
        filename: Nome do arquivo (sem extensão).
        metadata: Metadados opcionais para incluir no cabeçalho.
        output_dir: Diretório de saída (usa padrão se None).

    Returns:
        Path do arquivo salvo.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Sanitiza nome do arquivo
    safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename)
    output_path = out_dir / f"{safe_name}.md"

    lines: list[str] = []

    # Cabeçalho com metadados
    if metadata:
        lines.append("---")
        for key, value in metadata.items():
            lines.append(f"{key}: {value}")
        lines.append("---")
        lines.append("")

    lines.append(text)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Markdown salvo: %s", output_path)
    return output_path


def format_financial_markdown(
    text: str,
    title: str = "Documento Financeiro",
    source_file: str = "",
) -> str:
    """Formata texto financeiro em Markdown estruturado.

    Adiciona cabeçalho, índice e formatação consistente.

    Args:
        text: Texto bruto extraído.
        title: Título do documento.
        source_file: Nome do arquivo fonte.

    Returns:
        Texto Markdown formatado.
    """
    sections: list[str] = []

    sections.append(f"# {title}")
    sections.append("")
    if source_file:
        sections.append(f"> Fonte: `{source_file}`")
        sections.append("")

    # Adiciona o conteúdo processado
    sections.append(text)

    return "\n".join(sections)
