"""Parser de saída em formato CSV.

Extrai tabelas do texto Markdown, unifica em um único CSV e remove
linhas duplicadas causadas pela sobreposição entre faixas de página.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from src.utils.config import OUTPUT_DIR, logger


def save_as_csv(
    text: str,
    filename: str,
    output_dir: str | Path | None = None,
) -> tuple[list[Path], list[list[str]]]:
    """Extrai tabelas do texto, unifica e salva como CSV único.

    Detecta tabelas em formato Markdown, combina todas em uma única
    tabela, remove linhas duplicadas (da sobreposição entre faixas),
    separa D/C dos valores em colunas próprias de natureza,
    e gera um único arquivo CSV.

    Args:
        text: Texto contendo tabelas em Markdown.
        filename: Nome base do arquivo (sem extensão).
        output_dir: Diretório de saída.

    Returns:
        Tupla (lista de Paths gerados, linhas unificadas).
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename)
    tables = extract_markdown_tables(text)

    if not tables:
        logger.warning("Nenhuma tabela encontrada no texto para exportar como CSV.")
        return [], []

    # Unifica todas as tabelas em uma só, removendo duplicatas
    unified = _unify_and_deduplicate(tables)

    if not unified:
        logger.warning("Tabela unificada ficou vazia após deduplicação.")
        return [], []

    # Pós-processamento: valida agrupadoras se coluna Tipo existir
    if len(unified) > 1:
        header = unified[0]
        layout = _detect_column_layout(header)
        if layout["has_tipo"]:
            data_rows = unified[1:]
            data_rows = _postprocess_agrupadoras(data_rows, layout)
            unified = [header] + data_rows

    # Separa D/C dos valores em colunas próprias de natureza
    unified = _split_natureza_columns(unified)

    output_path = out_dir / f"{safe_name}.csv"

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        for row in unified:
            writer.writerow(row)

    logger.info("CSV unificado salvo: %s (%d linhas)", output_path, len(unified))
    return [output_path], unified


def _unify_and_deduplicate(
    tables: list[list[list[str]]],
) -> list[list[str]]:
    """Unifica múltiplas tabelas em uma só e remove duplicatas.

    Estratégia:
    1. Usa o cabeçalho da primeira tabela como cabeçalho único.
    2. Concatena todas as linhas de dados de todas as tabelas.
    3. Remove linhas que são cabeçalhos repetidos.
    4. Remove linhas exatamente duplicadas (mantém a primeira ocorrência).

    Args:
        tables: Lista de tabelas extraídas do Markdown.

    Returns:
        Lista de linhas (cada linha é lista de células) sem duplicatas.
    """
    if not tables:
        return []

    # Detecta o cabeçalho: primeira linha da primeira tabela
    header = tables[0][0] if tables[0] else []
    header_key = _row_key(header)

    # Coleta todas as linhas de dados (exceto cabeçalhos repetidos)
    seen: set[str] = set()
    unified: list[list[str]] = []

    # Adiciona o cabeçalho
    unified.append(header)
    seen.add(header_key)

    for table in tables:
        for row in table:
            key = _row_key(row)

            # Pula se é um cabeçalho repetido
            if key == header_key:
                continue

            # Pula se é uma linha duplicada já vista
            if key in seen:
                continue

            seen.add(key)
            unified.append(row)

    return unified


def _row_key(row: list[str]) -> str:
    """Gera uma chave única para uma linha, normalizando espaços.

    Args:
        row: Lista de células.

    Returns:
        String normalizada para comparação.
    """
    return "|".join(cell.strip().lower() for cell in row)


def extract_markdown_tables(text: str) -> list[list[list[str]]]:
    """Extrai tabelas de texto em formato Markdown.

    Detecta padrões de tabela Markdown (|col1|col2|...) e retorna
    como listas de linhas/células. Também lida com tabelas dentro
    de blocos de código (```markdown, ```csv, etc.).

    Args:
        text: Texto com tabelas Markdown.

    Returns:
        Lista de tabelas, cada uma sendo lista de linhas (lista de células).
    """
    # Remove blocos de código (```markdown, ```csv, ```, etc.)
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", text)

    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []
    in_table = False

    for line in cleaned.split("\n"):
        stripped = line.strip()

        # Detecta linha de tabela Markdown (com | no conteúdo)
        if "|" in stripped:
            # Ignora linhas separadoras (|---|---|) ou (---|---|)
            clean_sep = stripped.strip("|").strip()
            if clean_sep and re.match(r"^[\s\-:|]+$", clean_sep):
                continue

            # Extrai células baseado no formato
            if stripped.startswith("|") and stripped.endswith("|"):
                # Formato padrão: |col1|col2|col3|
                cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
            elif stripped.startswith("|"):
                # Formato: |col1|col2|col3
                cells = [cell.strip() for cell in stripped.split("|")[1:]]
            elif stripped.endswith("|"):
                # Formato: col1|col2|col3|
                cells = [cell.strip() for cell in stripped.split("|")[:-1]]
            else:
                # Formato sem bordas: col1|col2|col3
                cells = [cell.strip() for cell in stripped.split("|")]

            # Filtra: deve ter pelo menos 3 colunas não-vazias para ser tabela
            non_empty = [c for c in cells if c]
            if len(non_empty) >= 3:
                current_table.append(cells)
                in_table = True
            elif in_table:
                # Linha com poucos campos — fim da tabela
                if current_table:
                    tables.append(current_table)
                current_table = []
                in_table = False

        elif in_table:
            # Fim da tabela
            if current_table:
                tables.append(current_table)
            current_table = []
            in_table = False

    # Captura última tabela se o texto terminar com ela
    if current_table:
        tables.append(current_table)

    if not tables:
        logger.debug(
            "Nenhuma tabela Markdown encontrada. Primeiros 500 chars do texto:\n%s",
            text[:500],
        )

    return tables


def _detect_column_layout(header: list[str]) -> dict[str, int]:
    """Detecta layout de colunas do CSV baseado no cabeçalho.

    Suporta dois layouts:
    - 7 colunas (legado): Código, Classificação, Descrição, Saldo Anterior, Débito, Crédito, Saldo Atual
    - 8 colunas (novo):   Código, Classificação, Descrição, Tipo, Saldo Anterior, Débito, Crédito, Saldo Atual

    Returns:
        Dict com índices: {tipo, saldo_anterior, debito, credito, saldo_atual, has_tipo, min_cols}
    """
    n = len(header)
    # Checa se a coluna 3 parece ser "Tipo" (A/D)
    has_tipo = False
    if n >= 8:
        col3 = header[3].strip().lower() if len(header) > 3 else ""
        if "tipo" in col3:
            has_tipo = True

    if has_tipo:
        return {
            "tipo": 3,
            "saldo_anterior": 4,
            "debito": 5,
            "credito": 6,
            "saldo_atual": 7,
            "has_tipo": True,
            "min_cols": 8,
        }
    else:
        return {
            "tipo": -1,
            "saldo_anterior": 3,
            "debito": 4,
            "credito": 5,
            "saldo_atual": 6,
            "has_tipo": False,
            "min_cols": 7,
        }


def _extract_natureza(value: str) -> tuple[str, str]:
    """Extrai natureza (D/C) de um valor brasileiro.

    Valores como "47.649.092,98D" → ("47.649.092,98", "D")
    Valores sem D/C como "60.917.957,40" → ("60.917.957,40", "")
    Valores zerados como "0,00" → ("0,00", "")

    Args:
        value: Valor com possível sufixo D/C.

    Returns:
        Tupla (valor_sem_natureza, natureza).
    """
    s = value.strip().replace("**", "")
    if not s:
        return "", ""
    if s.endswith("D"):
        return s[:-1], "D"
    if s.endswith("C"):
        return s[:-1], "C"
    return s, ""


def _split_natureza_columns(rows: list[list[str]]) -> list[list[str]]:
    """Separa D/C dos valores de Saldo Anterior e Saldo Atual em colunas próprias.

    Transforma:
        Código | Classificação | Descrição | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual
    Em:
        Código | Classificação | Descrição | Tipo | Saldo Anterior | Natureza SA | Débito | Crédito | Saldo Atual | Natureza SAT

    Args:
        rows: Linhas unificadas (header + dados).

    Returns:
        Linhas com colunas de natureza adicionadas.
    """
    if not rows:
        return rows

    header = rows[0]
    layout = _detect_column_layout(header)
    col_sa = layout["saldo_anterior"]
    col_sat = layout["saldo_atual"]

    # Verifica se realmente tem D/C nos dados (checa primeiras 10 linhas de dados)
    has_natureza = False
    for row in rows[1:11]:
        if len(row) > col_sat:
            _, nat_sa = _extract_natureza(row[col_sa])
            _, nat_sat = _extract_natureza(row[col_sat])
            if nat_sa or nat_sat:
                has_natureza = True
                break

    if not has_natureza:
        return rows  # Sem D/C, retorna sem modificar

    # Monta novo header com colunas de natureza
    # Inserimos "Natureza SA" DEPOIS de Saldo Anterior,
    # e "Natureza SAT" DEPOIS de Saldo Atual
    # Mas como Saldo Atual vem por último, fazemos na ordem certa
    result = []

    for i, row in enumerate(rows):
        if i == 0:
            # Header: insere colunas de natureza
            new_header = list(row[:col_sa])
            new_header.append(row[col_sa])          # Saldo Anterior
            new_header.append("Natureza SA")         # Nova coluna
            # Débito e Crédito ficam no meio
            for mid_col in range(col_sa + 1, col_sat):
                new_header.append(row[mid_col])
            new_header.append(row[col_sat])          # Saldo Atual
            new_header.append("Natureza SAT")        # Nova coluna
            # Colunas extras depois de Saldo Atual (se houver)
            for extra_col in range(col_sat + 1, len(row)):
                new_header.append(row[extra_col])
            result.append(new_header)
        else:
            # Dados
            if len(row) <= col_sat:
                result.append(row)
                continue

            val_sa, nat_sa = _extract_natureza(row[col_sa] if col_sa < len(row) else "")
            val_sat, nat_sat = _extract_natureza(row[col_sat] if col_sat < len(row) else "")

            new_row = list(row[:col_sa])
            new_row.append(val_sa)       # Saldo Anterior (sem D/C)
            new_row.append(nat_sa)       # Natureza SA
            for mid_col in range(col_sa + 1, col_sat):
                new_row.append(row[mid_col] if mid_col < len(row) else "")
            new_row.append(val_sat)      # Saldo Atual (sem D/C)
            new_row.append(nat_sat)      # Natureza SAT
            for extra_col in range(col_sat + 1, len(row)):
                new_row.append(row[extra_col])
            result.append(new_row)

    return result


def _postprocess_agrupadoras(rows: list[list[str]], layout: dict[str, int]) -> list[list[str]]:
    """Pós-processamento: valida e corrige coluna Tipo baseado na hierarquia.

    Se uma conta tem classificação que é prefixo de outra conta no balancete,
    ela DEVE ser agrupadora (Tipo='A'). Corrige caso o Gemini tenha errado.

    Args:
        rows: Linhas de dados (sem header e sem resumo).
        layout: Layout de colunas detectado.

    Returns:
        Linhas com Tipo corrigido.
    """
    if not layout["has_tipo"] or layout["tipo"] < 0:
        return rows

    tipo_idx = layout["tipo"]

    # Coleta todas as classificações
    classificacoes = set()
    for row in rows:
        if len(row) > 1:
            c = row[1].strip()
            if c:
                classificacoes.add(c)

    # Identifica agrupadoras: conta cujo classificacao é prefixo de outra
    agrupadoras = set()
    for c in classificacoes:
        for other in classificacoes:
            if other != c and other.startswith(c + "."):
                agrupadoras.add(c)
                break

    # Corrige Tipo
    corrected = 0
    for row in rows:
        if len(row) <= tipo_idx:
            continue
        classificacao = row[1].strip()
        if classificacao in agrupadoras and row[tipo_idx].strip().upper() != "A":
            row[tipo_idx] = "A"
            corrected += 1
        # Se não é agrupadora mas foi marcada como A, corrige para D
        elif classificacao not in agrupadoras and row[tipo_idx].strip().upper() == "A":
            # Mantém — Gemini pode ter razão (conta pode ter filhas fora do balancete)
            pass

    if corrected:
        logger.info("Pós-processamento: %d conta(s) corrigida(s) para agrupadora (Tipo=A).", corrected)

    return rows


def _parse_brazilian_value(value_str: str) -> tuple[float, str]:
    """Parseia valor em formato brasileiro com sufixo D/C.

    Args:
        value_str: Valor como string (ex: "4.960.556,92D").

    Returns:
        Tupla (valor_float, natureza) — ex: (4960556.92, "D").
    """
    s = value_str.strip().replace("**", "")
    if not s:
        return 0.0, ""

    natureza = ""
    if s.endswith("D"):
        natureza = "D"
        s = s[:-1]
    elif s.endswith("C"):
        natureza = "C"
        s = s[:-1]

    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s), natureza
    except ValueError:
        return 0.0, ""


def _format_brazilian_value(value: float, natureza: str) -> str:
    """Formata valor float de volta para formato brasileiro com D/C.

    Args:
        value: Valor absoluto.
        natureza: "D", "C" ou "".

    Returns:
        String formatada (ex: "334.509,61D").
    """
    formatted = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted}{natureza}" if natureza else formatted


def _valor_com_sinal(valor: float, natureza: str, grupo: int) -> float:
    """Converte valor para formato com sinal baseado na convenção contábil.

    Balanço Patrimonial:
        Ativo (1): D = +valor, C = -valor
        Passivo (2): C = +valor, D = -valor

    DRE (Resultado):
        Custos/Despesas (3): C = +valor, D = -valor
        Receitas (4): C = +valor, D = -valor

    Args:
        valor: Valor absoluto.
        natureza: "D", "C" ou "".
        grupo: Primeiro dígito da classificação.

    Returns:
        Valor com sinal correto.
    """
    if valor == 0.0 or not natureza:
        return valor

    # Ativo: D = positivo, C = negativo
    if grupo == 1:
        return valor if natureza == "D" else -valor

    # Passivo, Custos/Despesas, Receitas: C = positivo, D = negativo
    return valor if natureza == "C" else -valor


def save_synthetic_csv(
    unified_rows: list[list[str]],
    keep_classificacoes: set[str],
    filename: str,
    output_dir: str | Path | None = None,
) -> tuple[Path, list[list[str]]]:
    """Gera CSV sintético filtrando contas e calculando resultado do período.

    Para contas de resultado (grupos 3 e 4), calcula:
        resultado = saldo_atual_com_sinal - saldo_anterior_com_sinal

    Args:
        unified_rows: Linhas do CSV completo (header + dados + resumo).
        keep_classificacoes: Set de classificações a manter.
        filename: Nome base do arquivo.
        output_dir: Diretório de saída.

    Returns:
        Tupla (Path do arquivo CSV sintético, linhas processadas).
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename)

    if not unified_rows:
        raise ValueError("unified_rows está vazio.")

    header = unified_rows[0]
    layout = _detect_column_layout(header)
    col_sa = layout["saldo_anterior"]
    col_sat = layout["saldo_atual"]
    min_cols = layout["min_cols"]

    data_rows = []
    resumo_rows = []

    for row in unified_rows[1:]:
        if len(row) < min_cols:
            continue
        codigo, classificacao = row[0].strip(), row[1].strip()
        # Resumo: Código e Classificação vazios
        if not codigo and not classificacao:
            resumo_rows.append(row)
        else:
            data_rows.append(row)

    # Pós-processamento: valida agrupadoras
    data_rows = _postprocess_agrupadoras(data_rows, layout)

    # Filtra: manter apenas contas cujo classificacao está no set
    filtered = []
    for row in data_rows:
        classificacao = row[1].strip()
        if classificacao in keep_classificacoes:
            filtered.append(row)

    # Transforma contas de resultado (grupos 3 e 4)
    result_rows = []
    for row in filtered:
        classificacao = row[1].strip()
        if not classificacao:
            result_rows.append(row)
            continue

        grupo = 0
        try:
            grupo = int(classificacao[0])
        except (ValueError, IndexError):
            pass

        if grupo in (3, 4):
            # Parseia saldo anterior e saldo atual
            val_ant, nat_ant = _parse_brazilian_value(row[col_sa])
            val_at, nat_at = _parse_brazilian_value(row[col_sat])

            # Converte para valores com sinal
            saldo_ant_signed = _valor_com_sinal(val_ant, nat_ant, grupo)
            saldo_at_signed = _valor_com_sinal(val_at, nat_at, grupo)

            # Resultado do período
            resultado = saldo_at_signed - saldo_ant_signed

            # Converte de volta para D/C (DRE: positivo=C, negativo=D)
            if resultado >= 0:
                nat_resultado = "C"
            else:
                nat_resultado = "D"

            # Monta nova linha: Saldo Anterior=0, Saldo Atual=resultado
            new_row = list(row)
            new_row[col_sa] = "0,00"  # Saldo Anterior zerado
            new_row[col_sat] = _format_brazilian_value(resultado, nat_resultado)
            result_rows.append(new_row)
        else:
            result_rows.append(row)

    # Monta CSV final: header + dados filtrados + resumo
    output_rows = [header] + result_rows + resumo_rows

    output_path = out_dir / f"{safe_name}_sintetico.csv"
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        for row in output_rows:
            writer.writerow(row)

    logger.info(
        "CSV sintético salvo: %s (%d linhas, de %d originais)",
        output_path, len(result_rows), len(data_rows),
    )
    return output_path, output_rows


def _format_signed_brazilian(value: float) -> str:
    """Formata valor float com sinal em formato brasileiro.

    Args:
        value: Valor com sinal (positivo ou negativo).

    Returns:
        String formatada (ex: "4.960.556,92" ou "-24.317,76").
    """
    formatted = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if value < 0:
        return f"-{formatted}"
    return formatted


def _grupo_from_resumo(descricao: str) -> int:
    """Infere o grupo contábil a partir da descrição da linha de resumo.

    Args:
        descricao: Descrição da conta no resumo.

    Returns:
        Grupo (1-4) ou 0 se não identificado.
    """
    desc = descricao.strip().upper().replace("**", "")
    if desc.startswith("ATIVO") or desc == "CONTAS DEVEDORAS":
        return 1
    if desc.startswith("PASSIVO") or desc.startswith("PATRIMÔNIO") or desc == "CONTAS CREDORAS":
        return 2
    if "CUSTOS" in desc and "DESPESAS" in desc:
        return 3
    if "RECEITAS" in desc:
        return 4
    if "RESULTADO" in desc:
        return 4  # resultados seguem lógica DRE (C=+, D=-)
    return 0


def _convert_row_to_signed(row: list[str], grupo: int, col_sa: int, col_sat: int) -> list[str]:
    """Converte uma linha do CSV de D/C para +/-.

    Converte apenas Saldo Anterior e Saldo Atual.
    Débito e Crédito permanecem como estão.

    Args:
        row: Linha original do CSV.
        grupo: Grupo contábil (1-4).
        col_sa: Índice da coluna Saldo Anterior.
        col_sat: Índice da coluna Saldo Atual.

    Returns:
        Nova linha com valores em formato +/-.
    """
    new_row = list(row)
    if len(new_row) <= col_sat:
        return new_row

    for col_idx in (col_sa, col_sat):
        val, nat = _parse_brazilian_value(new_row[col_idx])
        if val == 0.0 and not nat:
            new_row[col_idx] = "0,00"
        elif grupo > 0:
            signed = _valor_com_sinal(val, nat, grupo)
            new_row[col_idx] = _format_signed_brazilian(signed)
        # Se grupo == 0, mantém original

    return new_row


def _convert_rows_to_signed(rows: list[list[str]]) -> list[list[str]]:
    """Converte linhas de D/C para +/- usando convenção contábil.

    Args:
        rows: Linhas do CSV (header + dados + resumo).

    Returns:
        Novas linhas com valores em formato +/-.
    """
    if not rows:
        return rows

    header = rows[0]
    layout = _detect_column_layout(header)
    col_sa = layout["saldo_anterior"]
    col_sat = layout["saldo_atual"]
    min_cols = layout["min_cols"]

    output_rows = [header]

    for row in rows[1:]:
        if len(row) < min_cols:
            output_rows.append(row)
            continue

        codigo, classificacao = row[0].strip(), row[1].strip()

        if not codigo and not classificacao:
            descricao = row[2].strip()
            grupo = _grupo_from_resumo(descricao)
            output_rows.append(_convert_row_to_signed(row, grupo, col_sa, col_sat))
        elif classificacao:
            try:
                grupo = int(classificacao[0])
            except (ValueError, IndexError):
                grupo = 0
            output_rows.append(_convert_row_to_signed(row, grupo, col_sa, col_sat))
        else:
            output_rows.append(row)

    return output_rows


def save_signed_csv(
    unified_rows: list[list[str]],
    filename: str,
    output_dir: str | Path | None = None,
    suffix: str = "_sinal",
) -> Path:
    """Gera CSV com +/- no lugar de D/C usando convenção contábil.

    Args:
        unified_rows: Linhas do CSV (header + dados + resumo).
        filename: Nome base do arquivo.
        output_dir: Diretório de saída.
        suffix: Sufixo do arquivo (padrão: "_sinal").

    Returns:
        Path do arquivo CSV gerado.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r'[<>:"/\\|?*]', "_", filename)

    if not unified_rows:
        raise ValueError("unified_rows está vazio.")

    output_rows = _convert_rows_to_signed(unified_rows)

    output_path = out_dir / f"{safe_name}{suffix}.csv"
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        for row in output_rows:
            writer.writerow(row)

    logger.info("CSV com sinal salvo: %s (%d linhas)", output_path, len(output_rows) - 1)
    return output_path


def tables_to_csv_string(tables: list[list[list[str]]], delimiter: str = ";") -> str:
    """Converte tabelas extraídas para uma string CSV.

    Args:
        tables: Lista de tabelas (saída de extract_markdown_tables).
        delimiter: Delimitador CSV.

    Returns:
        String formatada como CSV.
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter)

    unified = _unify_and_deduplicate(tables)
    for row in unified:
        writer.writerow(row)

    return output.getvalue()
