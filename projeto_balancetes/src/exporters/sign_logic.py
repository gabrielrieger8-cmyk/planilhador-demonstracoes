"""Lógica de sinais contábeis (D/C → +/-).

Detecta a convenção de sinais nos dados e converte Saldo Anterior / Saldo Atual
de D/C para +/- conforme regras contábeis brasileiras.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.exporters.hierarchy import get_account_group


@dataclass
class SignDetectionResult:
    """Resultado da análise de sinais nos dados."""
    has_dc: bool = False            # D/C encontrado nos valores/natureza
    has_signs: bool = False         # +/- encontrado nos valores
    matches_convention: bool = False  # Sinais batem com convenção padrão
    needs_user_input: bool = False  # Precisa perguntar ao usuário
    details: str = ""               # Explicação legível


@dataclass
class SignConfig:
    """Configuração para conversão de sinais."""
    mode: str = "auto"  # "auto", "ask", "skip"
    custom_rules: dict[int, dict[str, int]] | None = None
    # custom_rules ex: {1: {"D": 1, "C": -1}, 2: {"D": -1, "C": 1}}


# Convenção padrão brasileira (Controladoria Plus)
# Regra: o D/C de CADA CONTA individual determina o sinal.
# Ex: Depreciação acumulada (Ativo, grupo 1) tem natureza C → fica negativa.
# Ex: Receita financeira (Receita, grupo 4) tem natureza C → fica positiva.
# A natureza D ou C da linha individual é quem manda.
STANDARD_CONVENTION: dict[int, dict[str, int]] = {
    1: {"D": 1, "C": -1},   # Ativo: D=+, C=-  (depreciação C → negativa)
    2: {"D": -1, "C": 1},   # Passivo: D=-, C=+
    3: {"D": -1, "C": 1},   # Custos/Despesas: D=-, C=+  (convenção do grupo)
    4: {"D": -1, "C": 1},   # Receitas: D=-, C=+
    5: {"D": -1, "C": 1},   # Custos (plano 6 grupos): D=-, C=+
    6: {"D": -1, "C": 1},   # Receitas (plano 6 grupos): D=-, C=+
}


def detect_sign_mode(
    rows: list[list[str]],
    sa_col: int,
    sat_col: int,
    nat_sa_col: int | None,
    nat_sat_col: int | None,
    classif_col: int = 1,
) -> SignDetectionResult:
    """Analisa dados para determinar a convenção de sinais presente.

    Args:
        rows: Linhas de dados (sem header).
        sa_col: Índice da coluna Saldo Anterior.
        sat_col: Índice da coluna Saldo Atual.
        nat_sa_col: Índice da coluna Natureza SA (ou None).
        nat_sat_col: Índice da coluna Natureza SAT (ou None).
        classif_col: Índice da coluna Classificação.

    Returns:
        SignDetectionResult com análise completa.
    """
    result = SignDetectionResult()

    dc_count = 0
    sign_count = 0
    total_checked = 0

    sample = rows[:50] if len(rows) > 50 else rows

    for row in sample:
        total_checked += 1

        # Checa D/C nas colunas de natureza
        if nat_sa_col is not None and nat_sa_col < len(row):
            nat = row[nat_sa_col].strip().upper()
            if nat in ("D", "C"):
                dc_count += 1

        if nat_sat_col is not None and nat_sat_col < len(row):
            nat = row[nat_sat_col].strip().upper()
            if nat in ("D", "C"):
                dc_count += 1

        # Checa D/C embutido nos valores
        for col in (sa_col, sat_col):
            if col < len(row):
                val = row[col].strip()
                if val and val[-1] in ("D", "C", "d", "c"):
                    dc_count += 1

        # Checa sinais +/-
        for col in (sa_col, sat_col):
            if col < len(row):
                val = row[col].strip()
                if val and (val[0] == "-" or val[0] == "+"):
                    sign_count += 1

    if total_checked == 0:
        result.needs_user_input = True
        result.details = "Nenhuma linha de dados para analisar."
        return result

    # CASE A: D/C encontrado
    if dc_count > total_checked * 0.3:
        result.has_dc = True
        # Verifica se bate com a convenção padrão
        convention_matches = _verify_convention(rows, sa_col, sat_col, nat_sa_col, nat_sat_col, classif_col)
        if convention_matches is True:
            result.matches_convention = True
            result.details = "D/C detectado. Convenção padrão confirmada (Ativo: D=+, Passivo: C=+)."
        elif convention_matches is False:
            result.needs_user_input = True
            result.details = "D/C detectado mas a lógica NÃO corresponde à convenção padrão. Verifique."
        else:
            # Inconclusivo
            result.matches_convention = True
            result.details = "D/C detectado. Assumindo convenção padrão."
        return result

    # CASE B: +/- encontrado, sem D/C
    if sign_count > total_checked * 0.3:
        result.has_signs = True
        result.matches_convention = True
        result.details = "Valores já possuem sinais +/-. Prosseguindo sem conversão."
        return result

    # CASE C: Sem D/C e sem sinais
    result.needs_user_input = True
    result.details = "Nenhum indicador D/C ou +/- encontrado nos dados. Necessário input do usuário."
    return result


def apply_sign_convention(
    rows: list[list[str]],
    sa_col: int,
    sat_col: int,
    nat_sa_col: int | None,
    nat_sat_col: int | None,
    classif_col: int = 1,
    config: SignConfig | None = None,
) -> list[list[str]]:
    """Aplica convenção de sinais: converte D/C em +/-.

    Args:
        rows: Linhas de dados (sem header).
        sa_col, sat_col: Índices das colunas de saldo.
        nat_sa_col, nat_sat_col: Índices das colunas de natureza.
        classif_col: Índice da coluna de classificação.
        config: Configuração de sinais.

    Returns:
        Novas linhas com valores convertidos para +/-.
    """
    if config and config.mode == "skip":
        return rows

    convention = STANDARD_CONVENTION
    if config and config.custom_rules:
        convention = {**STANDARD_CONVENTION, **config.custom_rules}

    result = []

    for row in rows:
        new_row = list(row)

        classif = row[classif_col].strip() if classif_col < len(row) else ""
        grupo = get_account_group(classif)

        if grupo == 0:
            result.append(new_row)
            continue

        rules = convention.get(grupo, {"D": 1, "C": -1})

        for val_col, nat_col in [(sa_col, nat_sa_col), (sat_col, nat_sat_col)]:
            if val_col >= len(new_row):
                continue

            val_str = new_row[val_col].strip()
            if not val_str:
                continue

            valor, natureza = _parse_value_with_dc(val_str)

            # Se natureza não veio do valor, tenta da coluna de natureza
            if not natureza and nat_col is not None and nat_col < len(new_row):
                natureza = new_row[nat_col].strip().upper()

            if not natureza or natureza not in ("D", "C"):
                continue

            multiplier = rules.get(natureza, 1)
            signed_val = valor * multiplier
            new_row[val_col] = _format_signed(signed_val)

            # Mantém D/C na coluna de natureza (não limpa mais)

        result.append(new_row)

    return result


def _verify_convention(
    rows: list[list[str]],
    sa_col: int,
    sat_col: int,
    nat_sa_col: int | None,
    nat_sat_col: int | None,
    classif_col: int,
) -> bool | None:
    """Verifica se os D/C dos dados batem com a convenção padrão.

    Convenção:
      - Ativo (1) e Despesas (3): natureza devedora → maioria D
      - Passivo (2) e Receitas (4): natureza credora → maioria C
      (Exceções como depreciação no Ativo com C são normais e esperadas)

    Returns:
        True = bate, False = não bate, None = inconclusivo.
    """
    # Conta D/C por grupo (suporta planos de 4 ou 6 grupos)
    counts: dict[int, dict[str, int]] = {}
    for g in range(1, 10):
        counts[g] = {"D": 0, "C": 0}

    for row in rows[:200]:
        classif = row[classif_col].strip() if classif_col < len(row) else ""
        grupo = get_account_group(classif)

        if grupo < 1:
            continue

        # Pega natureza do SAT
        nat = ""
        if nat_sat_col is not None and nat_sat_col < len(row):
            nat = row[nat_sat_col].strip().upper()
        if not nat and sat_col < len(row):
            val = row[sat_col].strip()
            if val and val[-1] in ("D", "C"):
                nat = val[-1].upper()

        if nat not in ("D", "C"):
            continue

        counts[grupo][nat] += 1

    total = sum(c["D"] + c["C"] for c in counts.values())
    if total < 5:
        return None  # Inconclusivo

    # Grupos devedores (Ativo=1): maioria D
    # Grupos credores (Passivo=2, Desp=3, Rec=4, Custos=5, Rec=6): maioria C
    # Não exigimos 100% — depreciação (1,C) e devoluções são exceções normais
    devedores_ok = True
    for g in (1,):
        if counts[g]["D"] + counts[g]["C"] > 0:
            if counts[g]["D"] < counts[g]["C"]:
                devedores_ok = False

    credores_ok = True
    for g in (2, 3, 4, 5, 6):
        if counts[g]["D"] + counts[g]["C"] > 0:
            if counts[g]["C"] < counts[g]["D"]:
                credores_ok = False

    if devedores_ok and credores_ok:
        return True
    return False


def _parse_value_with_dc(val_str: str) -> tuple[float, str]:
    """Parseia valor brasileiro com possível D/C.

    Returns:
        (valor_absoluto, natureza: "D"|"C"|"")
    """
    s = val_str.strip().replace("**", "")
    if not s:
        return 0.0, ""

    natureza = ""
    if s[-1] in ("D", "C", "d", "c"):
        natureza = s[-1].upper()
        s = s[:-1].strip()

    s = s.replace(".", "").replace(",", ".")
    try:
        return abs(float(s)), natureza
    except ValueError:
        return 0.0, ""


def _format_signed(value: float) -> str:
    """Formata valor com sinal no formato brasileiro.

    Ex: -12345.67 → "-12.345,67"
        12345.67 → "12.345,67"
    """
    formatted = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if value < 0:
        return f"-{formatted}"
    return formatted
