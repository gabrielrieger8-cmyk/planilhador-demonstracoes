"""Parser de saída em formato JSON.

Estrutura o conteúdo extraído em JSON hierárquico adequado
para integração com sistemas contábeis.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.parsers.csv_parser import extract_markdown_tables
from src.utils.config import OUTPUT_DIR, logger


def save_as_json(
    text: str,
    filename: str,
    metadata: dict | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Converte o texto processado em JSON estruturado e salva.

    Args:
        text: Texto extraído do PDF.
        filename: Nome do arquivo (sem extensão).
        metadata: Metadados do processamento.
        output_dir: Diretório de saída.

    Returns:
        Path do arquivo JSON salvo.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename)
    output_path = out_dir / f"{safe_name}.json"

    structured = structure_content(text, metadata)

    output_path.write_text(
        json.dumps(structured, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("JSON salvo: %s", output_path)
    return output_path


def structure_content(
    text: str,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Estrutura o conteúdo extraído em formato JSON hierárquico.

    Args:
        text: Texto em Markdown extraído.
        metadata: Metadados de processamento.

    Returns:
        Dicionário estruturado com o conteúdo do documento.
    """
    tables = extract_markdown_tables(text)

    # Extrai seções do Markdown
    sections = _extract_sections(text)

    result: dict[str, Any] = {
        "documento": {
            "data_processamento": datetime.now().isoformat(),
            "metadata": metadata or {},
        },
        "conteudo": {
            "texto_completo": text,
            "secoes": sections,
            "tabelas": [_table_to_dict(table, i) for i, table in enumerate(tables)],
        },
        "resumo": {
            "total_secoes": len(sections),
            "total_tabelas": len(tables),
            "total_caracteres": len(text),
        },
    }

    return result


def _extract_sections(text: str) -> list[dict[str, Any]]:
    """Extrai seções do texto baseado em cabeçalhos Markdown.

    Args:
        text: Texto em Markdown.

    Returns:
        Lista de dicionários com título, nível e conteúdo de cada seção.
    """
    sections: list[dict[str, Any]] = []
    current_section: dict[str, Any] | None = None
    content_lines: list[str] = []

    for line in text.split("\n"):
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)

        if header_match:
            # Salva seção anterior
            if current_section is not None:
                current_section["conteudo"] = "\n".join(content_lines).strip()
                sections.append(current_section)
                content_lines = []

            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            current_section = {
                "nivel": level,
                "titulo": title,
                "conteudo": "",
            }
        else:
            content_lines.append(line)

    # Última seção
    if current_section is not None:
        current_section["conteudo"] = "\n".join(content_lines).strip()
        sections.append(current_section)

    return sections


def _table_to_dict(table: list[list[str]], index: int) -> dict[str, Any]:
    """Converte uma tabela extraída para formato dicionário.

    Se a tabela tem cabeçalho, usa as colunas do cabeçalho como chaves.

    Args:
        table: Lista de linhas da tabela.
        index: Índice da tabela no documento.

    Returns:
        Dicionário com os dados da tabela.
    """
    if not table:
        return {"indice": index, "cabecalhos": [], "linhas": []}

    headers = table[0]
    rows = table[1:] if len(table) > 1 else []

    # Converte linhas para dicionários usando cabeçalhos
    dict_rows: list[dict[str, str]] = []
    for row in rows:
        row_dict = {}
        for j, cell in enumerate(row):
            key = headers[j] if j < len(headers) else f"coluna_{j + 1}"
            row_dict[key] = cell
        dict_rows.append(row_dict)

    return {
        "indice": index,
        "cabecalhos": headers,
        "linhas": dict_rows,
        "total_linhas": len(dict_rows),
    }
