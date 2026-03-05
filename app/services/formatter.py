"""Formatação Python dos dados extraídos — substitui a chamada de IA.

Converte tabelas Markdown (saída da extração) em JSON estruturado,
fazendo em <1s o que a IA levava 10-30s.

Suporta demonstrações comparativas (multi-período): quando a tabela
extraída tem múltiplas colunas de valor (ex: Dez/2024 e Dez/2025),
as funções _multi retornam uma lista de dicts (um por período).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger("planilhador")

# ---------------------------------------------------------------------------
# Parsing de números brasileiros
# ---------------------------------------------------------------------------

_BR_NUM_RE = re.compile(
    r"""
    ^\s*
    (?P<neg>[(\-])?\s*         # sinal negativo: ( ou -
    (?P<num>[\d.,]+)           # dígitos com . e ,
    \s*(?P<paren>\))?          # fecha parêntese
    \s*(?P<dc>[DC])?           # indicador D/C
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _parse_br_number(text: str) -> tuple[float, Optional[str]]:
    """Parse número em formato brasileiro, retorna (valor, indicador_D/C)."""
    text = text.strip()
    if not text or text in ("-", "—", "–", ""):
        return 0.0, None

    m = _BR_NUM_RE.match(text)
    if not m:
        # Tenta extrair só dígitos
        cleaned = re.sub(r"[^\d.,\-]", "", text)
        if not cleaned:
            return 0.0, None
        return _parse_br_number(cleaned)

    neg = m.group("neg") in ("(", "-")
    paren = m.group("paren") == ")"
    num_str = m.group("num")
    dc = m.group("dc")
    if dc:
        dc = dc.upper()

    # Remove pontos de milhar, troca vírgula por ponto decimal
    num_str = num_str.replace(".", "").replace(",", ".")

    try:
        value = float(num_str)
    except ValueError:
        return 0.0, dc

    if neg or paren:
        value = -abs(value)

    return value, dc


def _apply_dc_sign(value: float, dc: Optional[str], natureza_grupo: str) -> float:
    """Aplica sinal baseado em D/C e natureza do grupo contábil."""
    if dc is None:
        return value

    abs_val = abs(value)
    if natureza_grupo == "D":
        return abs_val if dc == "D" else -abs_val
    else:  # natureza_grupo == "C"
        return abs_val if dc == "C" else -abs_val


# ---------------------------------------------------------------------------
# Parser de tabela Markdown
# ---------------------------------------------------------------------------

def _parse_pipe_table(raw_text: str) -> list[list[str]]:
    """Parseia texto pipe-separated em lista de linhas/colunas."""
    rows = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"^[\s|:\-]+$", line):
            continue
        if "|" in line:
            cells = [c.strip() for c in line.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            rows.append(cells)
        else:
            rows.append([line])
    return rows


# ---------------------------------------------------------------------------
# Detecção de colunas e headers (compartilhado)
# ---------------------------------------------------------------------------

def _detect_classif_column(rows: list[list[str]]) -> bool:
    """Detecta se a primeira coluna contém classificações numéricas (1.1, 2.3.1, etc.)."""
    if not rows:
        return False
    # Checa se header menciona "classificação"
    if rows[0]:
        first_upper = " ".join(rows[0]).upper()
        if "CLASSIFICAÇÃO" in first_upper or "CLASSIFICACAO" in first_upper:
            return True
    # Checa se pelo menos 30% das linhas têm classificação numérica na coluna 0
    classif_count = 0
    total = 0
    classif_re = re.compile(r"^\d+(\.\d+)*$")
    for row in rows:
        if len(row) >= 3:
            total += 1
            col0 = row[0].strip().replace("**", "")
            if classif_re.match(col0):
                classif_count += 1
    return total > 0 and classif_count / total >= 0.3


_HEADER_KEYWORDS_DESC = ("DESCRIÇÃO", "DESCRICAO", "CONTA", "DESCRIPTION")
_HEADER_KEYWORDS_CLASSIF = ("CLASSIFICAÇÃO", "CLASSIFICACAO")
_HEADER_KEYWORDS_VALUE = ("VALOR", "VALUE")

# Keywords que indicam colunas NÃO-numéricas (não são períodos)
_NON_PERIOD_KEYWORDS = (
    "AV%", "AV %", "AV(", "AV (", "A.V.", "A.V",
    "ANÁLISE VERTICAL", "ANALISE VERTICAL",
    "%", "PERCENTUAL",
    "VARIAÇÃO", "VARIACAO", "VAR.",
)

# Regex para detectar colunas que são apenas "AV" (análise vertical)
_AV_ONLY_RE = re.compile(r"^AV\b", re.IGNORECASE)


def _analyze_header(
    rows: list[list[str]],
    extra_keywords: tuple[str, ...] = (),
) -> tuple[int, bool]:
    """Analisa header da tabela e retorna (start_index, has_classif).

    Args:
        rows: Linhas da tabela parseada.
        extra_keywords: Keywords adicionais para detecção de header.
    """
    all_keywords = _HEADER_KEYWORDS_DESC + _HEADER_KEYWORDS_CLASSIF + extra_keywords
    start = 0
    header_has_classif = False

    if rows and any(h.upper() in all_keywords for h in rows[0]):
        header_has_classif = any(
            h.upper() in _HEADER_KEYWORDS_CLASSIF for h in rows[0]
        )
        start = 1

    has_classif = header_has_classif or _detect_classif_column(rows[start:])
    return start, has_classif


def _is_numeric_cell(text: str) -> bool:
    """Verifica se uma célula contém um valor numérico brasileiro."""
    text = text.strip()
    if not text or text in ("-", "—", "–", ""):
        return True  # vazio ou traço = zero válido
    val, _ = _parse_br_number(text)
    # Se parseia como zero, verifica se era realmente um zero ou texto
    if val == 0.0:
        cleaned = re.sub(r"[^\d]", "", text)
        return len(cleaned) > 0  # tem dígitos = é numérico
    return True


def _detect_value_columns(
    rows: list[list[str]],
    start: int,
    has_classif: bool,
) -> list[tuple[int, str]]:
    """Detecta colunas de valor na tabela (uma por período).

    Returns:
        Lista de (índice_coluna, nome_período) para cada coluna de valor.
        Single-period: [(2, "")] com classif, [(1, "")] sem classif.
        Multi-period: [(2, "Dez/2024"), (3, "Dez/2025")] etc.
    """
    base_val_idx = 2 if has_classif else 1

    data_rows = rows[start:]
    if not data_rows:
        return [(base_val_idx, "")]

    # Encontra a contagem máxima de colunas entre linhas com dados suficientes
    col_counts = [len(r) for r in data_rows if len(r) >= base_val_idx + 1]
    if not col_counts:
        return [(base_val_idx, "")]

    max_cols = max(col_counts)

    if max_cols <= base_val_idx + 1:
        # Apenas uma coluna de valor
        return [(base_val_idx, "")]

    # Múltiplas colunas possíveis: valida cada candidata
    header = rows[0] if start > 0 and rows else []

    candidates = []
    for col_idx in range(base_val_idx, max_cols):
        # Extrai nome do período do header
        period_name = ""
        if col_idx < len(header):
            name = header[col_idx].strip().replace("**", "")
            name_upper = name.upper()
            # Ignora colunas explicitamente não-periódicas (AV, VARIAÇÃO, etc.)
            if any(kw in name_upper for kw in _NON_PERIOD_KEYWORDS):
                continue
            if _AV_ONLY_RE.match(name_upper):
                continue
            if name_upper not in ("VALOR", "VALUE", ""):
                period_name = name

        # Valida: conta linhas com conteúdo numérico nesta coluna
        numeric_count = 0
        total_with_col = 0
        for row in data_rows:
            if col_idx < len(row):
                total_with_col += 1
                if _is_numeric_cell(row[col_idx]):
                    numeric_count += 1

        # Aceita se ≥50% das linhas que têm esta coluna são numéricas
        if total_with_col > 0 and numeric_count / total_with_col >= 0.5:
            candidates.append((col_idx, period_name))

    if not candidates:
        return [(base_val_idx, "")]

    return candidates


# ---------------------------------------------------------------------------
# Formatar DRE
# ---------------------------------------------------------------------------

_DRE_SUBTOTAL_KEYWORDS = [
    "RECEITA OPERACIONAL LÍQUIDA", "RECEITA LÍQUIDA",
    "RESULTADO BRUTO", "LUCRO BRUTO",
    "RESULTADO OPERACIONAL", "LUCRO OPERACIONAL",
    "RESULTADO ANTES", "LUCRO ANTES",
    "RESULTADO LÍQUIDO", "LUCRO LÍQUIDO", "PREJUÍZO",
    "RESULTADO DO EXERCÍCIO", "LUCRO DO EXERCÍCIO",
    "EBITDA", "LAJIDA",
    "TOTAL",
]


def _formatar_dre_internal(
    rows: list[list[str]],
    start: int,
    has_classif: bool,
    val_col_idx: int,
    empresa: str,
    periodo: str,
) -> dict:
    """Lógica core de formatação DRE para uma coluna de valor específica."""
    linhas = []
    resultado_liquido = None

    for row in rows[start:]:
        if has_classif:
            if len(row) < 3:
                continue
            classificacao = row[0].strip().replace("**", "")
            descricao_raw = row[1].strip()
        else:
            if len(row) < 2:
                continue
            classificacao = ""
            descricao_raw = row[0].strip()

        valor_raw = row[val_col_idx] if val_col_idx < len(row) else ""

        # Remove markdown bold e entidades HTML (&nbsp;) que o modelo às vezes retorna
        descricao = descricao_raw.replace("**", "").replace("&nbsp;", " ").strip()
        if not descricao:
            continue

        valor, _ = _parse_br_number(valor_raw)

        # Determina nível
        is_bold = "**" in descricao_raw
        desc_upper = descricao.upper()

        # Identifica subtotais
        is_subtotal = False
        for kw in _DRE_SUBTOTAL_KEYWORDS:
            if kw in desc_upper:
                is_subtotal = True
                break
        if desc_upper.startswith("=") or desc_upper.startswith("(=)"):
            is_subtotal = True
            descricao = descricao.lstrip("= ").strip()

        # Nível: 1 para categorias principais e subtotais, 2 para detalhe
        is_all_upper = descricao == descricao.upper() and len(descricao) > 3
        nivel = 1 if (is_bold or is_subtotal or is_all_upper) else 2
        # Heurística: linhas que começam com (-) ou (+) são detalhe
        if descricao.startswith("(-)") or descricao.startswith("(+)"):
            nivel = 2

        # Última linha de resultado
        for kw in ("RESULTADO LÍQUIDO", "LUCRO LÍQUIDO", "PREJUÍZO LÍQUIDO",
                    "RESULTADO DO EXERCÍCIO", "LUCRO DO EXERCÍCIO"):
            if kw in desc_upper:
                resultado_liquido = valor
                break

        linha_dict = {
            "descricao": descricao,
            "valor": valor,
            "nivel": nivel,
            "is_subtotal": is_subtotal,
        }
        if classificacao:
            linha_dict["classificacao"] = classificacao
        linhas.append(linha_dict)

    # Segunda passada: marca agrupadoras (nivel 1, não-subtotal, após primeiro subtotal, com filhos nivel 2)
    seen_subtotal = False
    for i, linha in enumerate(linhas):
        if linha["is_subtotal"]:
            seen_subtotal = True
            continue
        if linha["nivel"] == 1 and seen_subtotal and not linha["is_subtotal"]:
            # Verifica se há filhos nivel 2 logo abaixo
            has_children = False
            for j in range(i + 1, len(linhas)):
                if linhas[j]["nivel"] == 2:
                    has_children = True
                    break
                if linhas[j]["nivel"] == 1 or linhas[j]["is_subtotal"]:
                    break
            if has_children:
                linha["is_agrupadora"] = True

    return {
        "empresa": empresa,
        "periodo": periodo,
        "linhas": linhas,
        "resultado_liquido": resultado_liquido,
    }


def formatar_dre(texto: str, empresa: str = "", periodo: str = "") -> dict:
    """Converte tabela Markdown de DRE em JSON estruturado (single-period)."""
    rows = _parse_pipe_table(texto)
    if not rows:
        return {"empresa": empresa, "periodo": periodo, "linhas": []}

    start, has_classif = _analyze_header(rows)
    val_col_idx = 2 if has_classif else 1

    return _formatar_dre_internal(rows, start, has_classif, val_col_idx, empresa, periodo)


def formatar_dre_multi(texto: str, empresa: str = "", periodo: str = "") -> list[dict]:
    """Formata DRE detectando multi-período automaticamente.

    Para single-period, retorna lista com 1 elemento.
    Para comparativo, retorna um dict por período.
    """
    rows = _parse_pipe_table(texto)
    if not rows:
        return [{"empresa": empresa, "periodo": periodo, "linhas": []}]

    start, has_classif = _analyze_header(rows)
    value_columns = _detect_value_columns(rows, start, has_classif)

    if len(value_columns) == 1:
        col_idx, period_name = value_columns[0]
        return [_formatar_dre_internal(
            rows, start, has_classif, col_idx,
            empresa, period_name or periodo,
        )]

    results = []
    for col_idx, period_name in value_columns:
        result = _formatar_dre_internal(
            rows, start, has_classif, col_idx,
            empresa, period_name or periodo,
        )
        results.append(result)

    logger.info(
        "DRE multi-período detectada: %d períodos (%s)",
        len(results),
        ", ".join(p for _, p in value_columns if p),
    )
    return results


# ---------------------------------------------------------------------------
# Formatar Balanço Patrimonial
# ---------------------------------------------------------------------------

_SECAO_ATIVO = ("ATIVO",)
_SECAO_PASSIVO = ("PASSIVO",)
_SECAO_PL = ("PATRIMÔNIO LÍQUIDO", "PATRIMONIO LIQUIDO", "PL")
_SUB_CIRCULANTE = ("CIRCULANTE", "ATIVO CIRCULANTE", "PASSIVO CIRCULANTE")
_SUB_NAO_CIRC = (
    "NÃO CIRCULANTE", "NAO CIRCULANTE",
    "ATIVO NÃO CIRCULANTE", "ATIVO NAO CIRCULANTE",
    "PASSIVO NÃO CIRCULANTE", "PASSIVO NAO CIRCULANTE",
    "REALIZÁVEL A LONGO PRAZO", "EXIGÍVEL A LONGO PRAZO",
)


def _formatar_balanco_internal(
    rows: list[list[str]],
    start: int,
    has_classif: bool,
    val_col_idx: int,
    empresa: str,
    data_ref: str,
) -> dict:
    """Lógica core de formatação Balanço para uma coluna de valor específica."""
    secao = None  # "ativo", "passivo", "pl"
    subsecao = None  # "circulante", "nao_circulante"

    result = {
        "empresa": empresa,
        "data_referencia": data_ref,
        "ativo": {
            "circulante": {"total": 0, "contas": []},
            "nao_circulante": {"total": 0, "contas": []},
            "total": 0,
        },
        "passivo": {
            "circulante": {"total": 0, "contas": []},
            "nao_circulante": {"total": 0, "contas": []},
            "total": 0,
        },
        "patrimonio_liquido": {"total": 0, "contas": []},
    }

    for row in rows[start:]:
        if len(row) < 1:
            continue

        if has_classif:
            if len(row) < 2:
                continue
            classificacao_raw = row[0].strip().replace("**", "")
            descricao_raw = row[1].strip()
        else:
            classificacao_raw = ""
            descricao_raw = row[0].strip()

        valor_col = row[val_col_idx] if val_col_idx < len(row) else ""

        descricao = descricao_raw.replace("**", "").replace("&nbsp;", " ").strip()
        if not descricao:
            continue

        desc_upper = _normalize_accents(descricao.upper())
        valor = 0.0
        if valor_col:
            valor, _ = _parse_br_number(valor_col)

        # Detecta subsecções ANTES de seções (para evitar que "Ativo Não Circulante"
        # seja capturado pelo check de "ATIVO")
        if secao in ("ativo", "passivo"):
            if _matches_any(desc_upper, _SUB_NAO_CIRC):
                subsecao = "nao_circulante"
                if _is_total_line(desc_upper) and valor > 0:
                    result[secao]["nao_circulante"]["total"] = valor
                continue
            elif _matches_any(desc_upper, _SUB_CIRCULANTE) and "NAO" not in desc_upper and "NÃO" not in descricao.upper():
                subsecao = "circulante"
                if _is_total_line(desc_upper) and valor > 0:
                    result[secao]["circulante"]["total"] = valor
                continue

        # Detecta seção principal
        if _matches_any(desc_upper, _SECAO_PL):
            secao = "pl"
            subsecao = None
            if _is_total_line(desc_upper) and valor > 0:
                result["patrimonio_liquido"]["total"] = valor
            continue
        elif _matches_any(desc_upper, _SECAO_PASSIVO) and "PATRIMONIO" not in desc_upper:
            secao = "passivo"
            subsecao = None
            if _is_total_line(desc_upper) and valor > 0:
                result["passivo"]["total"] = valor
            elif desc_upper.strip() in ("PASSIVO",) and valor > 0:
                result["passivo"]["total"] = valor
            continue
        elif _matches_any(desc_upper, _SECAO_ATIVO):
            secao = "ativo"
            subsecao = None
            if _is_total_line(desc_upper) and valor > 0:
                result["ativo"]["total"] = valor
            elif desc_upper.strip() in ("ATIVO",) and valor > 0:
                result["ativo"]["total"] = valor
            continue

        if secao is None:
            # Tenta inferir seção pelo conteúdo
            if any(kw in desc_upper for kw in ("CAIXA", "ESTOQUE", "CLIENTE", "BANCO")):
                secao = "ativo"
                subsecao = "circulante"
            elif any(kw in desc_upper for kw in ("FORNECEDOR", "EMPRESTIMO", "OBRIGAC")):
                secao = "passivo"
                subsecao = "circulante"
            elif any(kw in desc_upper for kw in ("CAPITAL", "RESERVA", "LUCRO")):
                secao = "pl"
            else:
                continue

        # Detecta totais de seção
        if "TOTAL" in desc_upper:
            if secao == "pl":
                result["patrimonio_liquido"]["total"] = valor
            elif secao in ("ativo", "passivo"):
                if subsecao and "TOTAL" in desc_upper:
                    result[secao][subsecao]["total"] = valor
                else:
                    result[secao]["total"] = valor
            continue

        # Conta normal
        conta = {"descricao": descricao, "valor": valor, "nivel": 3}
        if classificacao_raw:
            conta["classificacao"] = classificacao_raw

        if secao == "pl":
            result["patrimonio_liquido"]["contas"].append(conta)
        elif secao in ("ativo", "passivo"):
            if subsecao is None:
                subsecao = "circulante"  # default
            result[secao][subsecao]["contas"].append(conta)

    # Calcula totais que estão faltando
    _fill_missing_totals(result)

    return result


def formatar_balanco(texto: str, empresa: str = "", data_ref: str = "") -> dict:
    """Converte tabela Markdown de Balanço Patrimonial em JSON estruturado (single-period)."""
    rows = _parse_pipe_table(texto)
    if not rows:
        return {
            "empresa": empresa, "data_referencia": data_ref,
            "ativo": {"circulante": {"total": 0, "contas": []},
                      "nao_circulante": {"total": 0, "contas": []}, "total": 0},
            "passivo": {"circulante": {"total": 0, "contas": []},
                        "nao_circulante": {"total": 0, "contas": []}, "total": 0},
            "patrimonio_liquido": {"total": 0, "contas": []},
        }

    start, has_classif = _analyze_header(rows, extra_keywords=("VALOR",))
    val_col_idx = 2 if has_classif else 1

    return _formatar_balanco_internal(rows, start, has_classif, val_col_idx, empresa, data_ref)


def formatar_balanco_multi(texto: str, empresa: str = "", data_ref: str = "") -> list[dict]:
    """Formata Balanço detectando multi-período automaticamente.

    Para single-period, retorna lista com 1 elemento.
    Para comparativo, retorna um dict por período.
    """
    rows = _parse_pipe_table(texto)
    empty = {
        "empresa": empresa, "data_referencia": data_ref,
        "ativo": {"circulante": {"total": 0, "contas": []},
                  "nao_circulante": {"total": 0, "contas": []}, "total": 0},
        "passivo": {"circulante": {"total": 0, "contas": []},
                    "nao_circulante": {"total": 0, "contas": []}, "total": 0},
        "patrimonio_liquido": {"total": 0, "contas": []},
    }
    if not rows:
        return [empty]

    start, has_classif = _analyze_header(rows, extra_keywords=("VALOR",))
    value_columns = _detect_value_columns(rows, start, has_classif)

    if len(value_columns) == 1:
        col_idx, period_name = value_columns[0]
        return [_formatar_balanco_internal(
            rows, start, has_classif, col_idx,
            empresa, period_name or data_ref,
        )]

    results = []
    for col_idx, period_name in value_columns:
        result = _formatar_balanco_internal(
            rows, start, has_classif, col_idx,
            empresa, period_name or data_ref,
        )
        results.append(result)

    logger.info(
        "Balanço multi-período detectado: %d períodos (%s)",
        len(results),
        ", ".join(p for _, p in value_columns if p),
    )
    return results


# ---------------------------------------------------------------------------
# Helpers Balanço
# ---------------------------------------------------------------------------

def _normalize_accents(text: str) -> str:
    """Remove acentos comuns para comparação."""
    return (text
            .replace("Ã", "A").replace("Õ", "O")
            .replace("Ç", "C").replace("É", "E")
            .replace("Á", "A").replace("Í", "I")
            .replace("Ú", "U").replace("Ó", "O")
            .replace("Â", "A").replace("Ê", "E")
            .replace("Ô", "O"))


def _matches_any(text: str, keywords: tuple) -> bool:
    """Verifica se text contém alguma das keywords."""
    text_clean = _normalize_accents(text.strip())
    for kw in keywords:
        kw_clean = _normalize_accents(kw)
        if kw_clean in text_clean:
            return True
    return False


def _is_total_line(desc_upper: str) -> bool:
    """Verifica se é uma linha de total."""
    return "TOTAL" in desc_upper


def _fill_missing_totals(result: dict) -> None:
    """Preenche/recalcula totais somando as sub-seções.

    Sempre recalcula o total de ativo/passivo a partir das sub-seções,
    porque muitos PDFs mostram PASSIVO total = Passivo + PL, o que
    causaria dupla-contagem na validação (Ativo = Passivo + PL).
    """
    for secao in ("ativo", "passivo"):
        data = result[secao]
        for sub in ("circulante", "nao_circulante"):
            sub_data = data.get(sub, {})
            if not sub_data.get("total") and sub_data.get("contas"):
                sub_data["total"] = sum(c.get("valor", 0) for c in sub_data["contas"])
        # Sempre recalcula total da seção a partir das sub-seções
        sub_total = (
            data.get("circulante", {}).get("total", 0) +
            data.get("nao_circulante", {}).get("total", 0)
        )
        if sub_total > 0:
            data["total"] = sub_total

    pl = result["patrimonio_liquido"]
    if not pl.get("total") and pl.get("contas"):
        pl["total"] = sum(c.get("valor", 0) for c in pl["contas"])


# ---------------------------------------------------------------------------
# Formatar Balancete
# ---------------------------------------------------------------------------

def formatar_balancete(texto: str, empresa: str = "", periodo: str = "") -> dict:
    """Converte tabela Markdown de Balancete em JSON estruturado."""
    rows = _parse_pipe_table(texto)
    if not rows:
        return {"empresa": empresa, "periodo": periodo, "moeda": "BRL",
                "contas": [], "totais": {}}

    # Pula header (primeira linha com nomes de coluna)
    start = 0
    if rows and len(rows[0]) >= 4:
        first_upper = " ".join(rows[0]).upper()
        if any(kw in first_upper for kw in ("CÓDIGO", "CODIGO", "CLASSIFICAÇÃO",
                                              "CLASSIFICACAO", "DESCRIÇÃO", "DESCRICAO",
                                              "SALDO", "DÉBITO", "DEBITO")):
            start = 1

    # Keywords que identificam linhas de header repetidas (quebra de página)
    _HEADER_KW = {
        "CÓDIGO", "CODIGO", "CLASSIFICAÇÃO", "CLASSIFICACAO",
        "DESCRIÇÃO", "DESCRICAO", "SALDO", "DÉBITO", "DEBITO",
        "CRÉDITO", "CREDITO", "TIPO", "CONTA", "NOME",
    }

    contas = []
    total_debitos = 0.0
    total_creditos = 0.0

    for row in rows[start:]:
        if len(row) < 7:
            continue

        # Mapeia colunas: Código | Classificação | Descrição | Tipo | Saldo Ant | Déb | Créd | Saldo Atual
        codigo = row[0].strip()
        classificacao = row[1].strip()
        descricao = row[2].strip().replace("**", "").replace("&nbsp;", " ").strip()
        tipo_raw = row[3].strip().upper()

        # Pula linhas de header repetidas (quebra de página no PDF)
        row_upper_set = {c.strip().upper() for c in row if c.strip()}
        if row_upper_set & _HEADER_KW and not any(c.strip()[:1].isdigit() for c in row[:2] if c.strip()):
            continue

        if not codigo and not descricao:
            continue

        # Nível pela classificação (conta pontos)
        nivel = classificacao.count(".") + 1

        # Tipo: A (agrupadora) ou D (detalhe)
        is_totalizador = tipo_raw == "A"

        # Natureza pelo grupo contábil (primeiro segmento da classificação)
        primeiro_segmento = classificacao.split(".")[0].strip()
        # Remove zeros à esquerda: "01" → "1", "02" → "2"
        grupo = primeiro_segmento.lstrip("0") or "0"

        natureza = "D"  # default
        if grupo in ("2", "4"):
            natureza = "C"
        elif grupo in ("1", "3"):
            natureza = "D"

        # Parse valores
        saldo_ant_raw, dc_sa = _parse_br_number(row[4]) if len(row) > 4 else (0.0, None)
        debitos_raw, dc_deb = _parse_br_number(row[5]) if len(row) > 5 else (0.0, None)
        creditos_raw, dc_cred = _parse_br_number(row[6]) if len(row) > 6 else (0.0, None)
        saldo_at_raw, dc_sat = _parse_br_number(row[7]) if len(row) > 7 else (0.0, None)

        # Aplica sinais D/C
        saldo_anterior = _apply_dc_sign(saldo_ant_raw, dc_sa, natureza) if dc_sa else saldo_ant_raw
        debitos = abs(debitos_raw)  # Débitos são sempre positivos
        creditos = abs(creditos_raw)  # Créditos são sempre positivos
        saldo_atual = _apply_dc_sign(saldo_at_raw, dc_sat, natureza) if dc_sat else saldo_at_raw

        contas.append({
            "codigo_conta": codigo,
            "classificacao": classificacao,
            "descricao": descricao,
            "nivel": nivel,
            "natureza": natureza,
            "is_totalizador": is_totalizador,
            "saldo_anterior": round(saldo_anterior, 2),
            "debitos": round(debitos, 2),
            "creditos": round(creditos, 2),
            "saldo_atual": round(saldo_atual, 2),
        })

        # Soma totais (apenas contas de detalhe)
        if not is_totalizador:
            total_debitos += debitos
            total_creditos += creditos

    return {
        "empresa": empresa,
        "periodo": periodo,
        "moeda": "BRL",
        "contas": contas,
        "totais": {
            "total_debitos": round(total_debitos, 2),
            "total_creditos": round(total_creditos, 2),
        },
    }
