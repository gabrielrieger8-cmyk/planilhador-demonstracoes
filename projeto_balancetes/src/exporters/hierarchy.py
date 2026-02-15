"""Utilitários de hierarquia de classificação contábil.

Determina relações pai-filho entre contas pela classificação
para gerar fórmulas SUM de validação nas agrupadoras.
"""

from __future__ import annotations


def build_hierarchy(
    rows: list[list[str]],
    classif_col: int,
    tipo_col: int | None = None,
) -> dict[int, list[int]]:
    """Constrói mapeamento pai → filhos diretos a partir da classificação.

    Filhos diretos de "1.1" são linhas com classificação "1.1.XX"
    onde XX é um único segmento (sem mais pontos).

    Args:
        rows: Linhas de dados (sem header).
        classif_col: Índice da coluna de classificação.
        tipo_col: Índice da coluna Tipo (se disponível, usa para
                  confirmar que o pai é agrupadora).

    Returns:
        Dict {row_index: [child_row_indices]}.
        Apenas pais com pelo menos 1 filho são incluídos.
    """
    # Coleta (index, classificacao) para cada linha válida
    entries: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        if classif_col < len(row):
            c = row[classif_col].strip()
            if c:
                entries.append((i, c))

    hierarchy: dict[int, list[int]] = {}

    for idx, classif in entries:
        children = get_direct_children(classif, entries)
        if children:
            # Se tipo_col disponível, só inclui se for agrupadora
            if tipo_col is not None and tipo_col < len(rows[idx]):
                tipo = rows[idx][tipo_col].strip().upper()
                if tipo != "A":
                    continue
            hierarchy[idx] = children

    return hierarchy


def get_direct_children(
    parent_classif: str,
    all_entries: list[tuple[int, str]],
) -> list[int]:
    """Retorna índices de filhos diretos de uma classificação.

    Filho direto: começa com parent + "." e NÃO tem mais pontos depois.
    Ex: pai="1.1", filho="1.1.01" (sim), neto="1.1.01.001" (não).

    Args:
        parent_classif: Classificação do pai.
        all_entries: Lista de (row_index, classificacao).

    Returns:
        Lista de row_indices dos filhos diretos.
    """
    prefix = parent_classif + "."
    children = []

    for idx, classif in all_entries:
        if classif == parent_classif:
            continue
        if not classif.startswith(prefix):
            continue

        # Verifica se é filho direto (só um nível abaixo)
        remainder = classif[len(prefix):]
        if "." not in remainder:
            children.append(idx)

    return children


def get_account_group(classificacao: str) -> int:
    """Retorna o grupo contábil a partir da classificação.

    Suporta dois formatos de classificação:
    - Direto: "1", "1.1", "2.1.01" → primeiro segmento = grupo
    - Com zero: "01", "01.1", "02.1.01" → primeiro segmento sem zero = grupo

    1 = Ativo, 2 = Passivo, 3 = Custos/Despesas, 4 = Receitas,
    5 = Custos (plano 6 grupos), 6 = Receitas (plano 6 grupos).

    Args:
        classificacao: String de classificação (ex: "1.1.01" ou "01.1.01").

    Returns:
        Grupo (1-9) ou 0 se não identificado.
    """
    c = classificacao.strip()
    if not c:
        return 0
    # Pega primeiro segmento (antes do primeiro ponto)
    first_segment = c.split(".")[0].strip()
    if not first_segment:
        return 0
    try:
        grupo = int(first_segment)
        return grupo if grupo >= 1 else 0
    except (ValueError, IndexError):
        return 0
