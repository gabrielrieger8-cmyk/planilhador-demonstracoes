"""Aba Demonstrações — DRE e Balanço Patrimonial estruturados."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from src.analysis.indicators import IndicadoresFinanceiros
from src.parsers.csv_parser import Balancete


def _fmt_brl(val: Decimal | None) -> str:
    """Formata valor em R$ no padrão brasileiro."""
    if val is None:
        return "—"
    f = float(val)
    s = f"R$ {f:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_demonstracoes(
    indicadores: IndicadoresFinanceiros,
    balancete: Balancete,
    mapeamento_ia: dict,
) -> None:
    """Renderiza DRE e BP estruturados."""
    contas_idx = {c.classificacao: c for c in balancete.contas}
    dre = mapeamento_ia.get("dre", {})
    bp = mapeamento_ia.get("bp", {})

    col_dre, col_bp = st.columns(2)

    with col_dre:
        _render_dre(indicadores, contas_idx, dre)

    with col_bp:
        _render_bp(contas_idx, bp)


def _get_saldo(contas_idx: dict, classif: str | None, campo: str = "atual") -> Decimal:
    """Busca saldo de uma conta pelo código de classificação."""
    if not classif:
        return Decimal("0")
    conta = contas_idx.get(classif)
    if not conta:
        return Decimal("0")
    if campo == "atual":
        return conta.saldo_atual
    return conta.saldo_anterior


def _get_descricao(contas_idx: dict, classif: str | None) -> str:
    """Busca descrição de uma conta."""
    if not classif:
        return ""
    conta = contas_idx.get(classif)
    return conta.descricao if conta else ""


def _render_dre(
    ind: IndicadoresFinanceiros,
    contas_idx: dict,
    dre: dict,
) -> None:
    """Renderiza a DRE estruturada."""
    st.markdown(
        '<div style="background-color: #2b6cb022; border-left: 4px solid #2b6cb0; '
        'padding: 0.5rem 1rem; margin-bottom: 1rem;">'
        '<h3 style="color: #2b6cb0; margin: 0;">Demonstração do Resultado (DRE)</h3></div>',
        unsafe_allow_html=True,
    )

    rows: list[dict] = []

    # Receita Bruta
    _add_row(rows, "RECEITA BRUTA", ind.receita_bruta, nivel=0, bold=True)
    _add_detail(rows, contas_idx, dre.get("receita_bruta"), nivel=1)

    # Deduções
    deducoes = -abs(ind.receita_liquida - ind.receita_bruta) if ind.receita_liquida and ind.receita_bruta else None
    _add_row(rows, "(-) DEDUÇÕES", deducoes, nivel=0, bold=True)
    _add_detail(rows, contas_idx, dre.get("deducoes_receita"), nivel=1)

    # Receita Líquida
    _add_row(rows, "= RECEITA LÍQUIDA", ind.receita_liquida, nivel=0, bold=True, calculated=True)

    # Custos
    custos_val = _get_saldo(contas_idx, dre.get("custos_servicos"))
    _add_row(rows, "(-) CUSTOS DOS SERVIÇOS", custos_val, nivel=0, bold=True)

    # Lucro Bruto
    _add_row(rows, "= LUCRO BRUTO", ind.lucro_bruto, nivel=0, bold=True, calculated=True)

    # Despesas Operacionais (excl. financeiras)
    desp_fin_classif = dre.get("despesas_financeiras") or ""
    desp_op_classif = dre.get("despesas_operacionais") or ""
    desp_adm_classif = dre.get("despesas_administrativas") or ""

    fin_dentro = (
        desp_fin_classif
        and (desp_op_classif or desp_adm_classif)
        and (
            desp_fin_classif.startswith(desp_op_classif + ".") if desp_op_classif
            else desp_fin_classif.startswith(desp_adm_classif + ".")
        )
    )

    # Valor das despesas operacionais excluindo financeiras
    desp_op_val = _get_saldo(contas_idx, dre.get("despesas_operacionais"))
    desp_adm_val = _get_saldo(contas_idx, dre.get("despesas_administrativas"))
    desp_fin_val = _get_saldo(contas_idx, dre.get("despesas_financeiras"))

    if desp_op_val != 0:
        desp_op_display = desp_op_val
        if fin_dentro:
            desp_op_display = desp_op_val - desp_fin_val
    elif desp_adm_val != 0:
        desp_op_display = desp_adm_val
        if fin_dentro:
            desp_op_display = desp_adm_val - desp_fin_val
    else:
        desp_op_display = Decimal("0")

    _add_row(rows, "(-) DESPESAS OPERACIONAIS", desp_op_display, nivel=0, bold=True)
    if dre.get("despesas_administrativas"):
        desp_adm_display = desp_adm_val
        if fin_dentro and desp_adm_val != 0:
            desp_adm_display = desp_adm_val - desp_fin_val
        _add_row(rows, "Despesas Administrativas", desp_adm_display, nivel=1)
    if dre.get("despesas_comerciais"):
        _add_row(rows, "Despesas Comerciais", _get_saldo(contas_idx, dre.get("despesas_comerciais")), nivel=1)

    # EBIT
    _add_row(rows, "= RESULTADO OPERACIONAL (EBIT)", ind.lucro_operacional, nivel=0, bold=True, calculated=True)

    # Despesas e Receitas Financeiras
    if desp_fin_val != 0:
        _add_row(rows, "(-) Despesas Financeiras", desp_fin_val, nivel=0)
    rec_fin_val = _get_saldo(contas_idx, dre.get("receitas_financeiras"))
    if rec_fin_val != 0:
        _add_row(rows, "(+) Receitas Financeiras", rec_fin_val, nivel=0)

    # Outras Receitas
    if dre.get("outras_receitas"):
        _add_row(rows, "Outras Receitas", _get_saldo(contas_idx, dre.get("outras_receitas")), nivel=0)

    # LAIR
    _add_row(rows, "= LAIR", ind.lucro_liquido, nivel=0, bold=True, calculated=True)

    # IR/CSLL
    if dre.get("ir_csll"):
        _add_row(rows, "(-) IR e CSLL", _get_saldo(contas_idx, dre.get("ir_csll")), nivel=0)

    # Lucro Líquido
    _add_row(rows, "= LUCRO LÍQUIDO", ind.resultado_periodo, nivel=0, bold=True, calculated=True)

    _display_table(rows, "DRE")


def _render_bp(contas_idx: dict, bp: dict) -> None:
    """Renderiza o Balanço Patrimonial estruturado."""
    st.markdown(
        '<div style="background-color: #38a16922; border-left: 4px solid #38a169; '
        'padding: 0.5rem 1rem; margin-bottom: 1rem;">'
        '<h3 style="color: #38a169; margin: 0;">Balanço Patrimonial</h3></div>',
        unsafe_allow_html=True,
    )

    rows: list[dict] = []

    # ATIVO
    _add_bp_row(rows, contas_idx, bp, "ativo_total", "ATIVO", nivel=0, bold=True, header=True)

    _add_bp_row(rows, contas_idx, bp, "ativo_circulante", "ATIVO CIRCULANTE", nivel=1, bold=True)
    _add_bp_row(rows, contas_idx, bp, "disponibilidades", "Disponibilidades", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "clientes", "Clientes", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "estoques", "Estoques", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "outros_creditos_cp", "Outros Créditos CP", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "despesas_antecipadas", "Despesas Antecipadas", nivel=2)

    _add_bp_row(rows, contas_idx, bp, "ativo_nao_circulante", "ATIVO NÃO CIRCULANTE", nivel=1, bold=True)
    _add_bp_row(rows, contas_idx, bp, "investimentos", "Investimentos", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "imobilizado", "Imobilizado", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "depreciacao_amortizacao", "(-) Depreciações", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "intangivel", "Intangível", nivel=2)

    # Separador
    rows.append({"Conta": "", "Saldo Anterior": "", "Saldo Atual": ""})

    # PASSIVO + PL
    _add_bp_row(rows, contas_idx, bp, "passivo_total", "PASSIVO + PL", nivel=0, bold=True, header=True)

    _add_bp_row(rows, contas_idx, bp, "passivo_circulante", "PASSIVO CIRCULANTE", nivel=1, bold=True)
    _add_bp_row(rows, contas_idx, bp, "emprestimos_financiamentos_cp", "Empréstimos CP", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "fornecedores", "Fornecedores", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "obrigacoes_fiscais", "Obrigações Fiscais", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "parcelamentos_cp", "Parcelamentos CP", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "obrigacoes_trabalhistas", "Obrigações Trabalhistas", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "outras_obrigacoes_cp", "Outras Obrigações CP", nivel=2)

    _add_bp_row(rows, contas_idx, bp, "passivo_nao_circulante", "PASSIVO NÃO CIRCULANTE", nivel=1, bold=True)
    _add_bp_row(rows, contas_idx, bp, "emprestimos_lp", "Empréstimos LP", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "parcelamentos_lp", "Parcelamentos LP", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "outros_debitos_lp", "Outros Débitos LP", nivel=2)

    _add_bp_row(rows, contas_idx, bp, "patrimonio_liquido", "PATRIMÔNIO LÍQUIDO", nivel=1, bold=True)
    _add_bp_row(rows, contas_idx, bp, "capital_social", "Capital Social", nivel=2)
    _add_bp_row(rows, contas_idx, bp, "lucros_prejuizos", "Lucros/Prejuízos Acum.", nivel=2)

    _display_table(rows, "BP")


def _add_row(
    rows: list[dict],
    nome: str,
    valor: Decimal | None,
    nivel: int = 0,
    bold: bool = False,
    calculated: bool = False,
) -> None:
    """Adiciona uma linha à tabela da DRE."""
    indent = "    " * nivel
    prefix = "**" if bold else ""
    suffix = "**" if bold else ""
    display_name = f"{indent}{prefix}{nome}{suffix}"

    rows.append({
        "Conta": display_name,
        "Saldo Atual": _fmt_brl(valor) if valor is not None else "—",
    })


def _add_detail(rows: list[dict], contas_idx: dict, classif: str | None, nivel: int = 1) -> None:
    """Adiciona sub-contas de detalhe (filhos diretos) se houver."""
    if not classif:
        return
    conta = contas_idx.get(classif)
    if not conta:
        return
    # Mostrar filhos diretos dessa conta
    for c in contas_idx.values():
        if (
            c.classificacao != classif
            and c.classificacao.startswith(classif + ".")
            and c.classificacao.count(".") == classif.count(".") + 1
        ):
            indent = "    " * nivel
            rows.append({
                "Conta": f"{indent}{c.descricao}",
                "Saldo Atual": _fmt_brl(c.saldo_atual),
            })


def _add_bp_row(
    rows: list[dict],
    contas_idx: dict,
    bp: dict,
    chave: str,
    nome: str,
    nivel: int = 0,
    bold: bool = False,
    header: bool = False,
) -> None:
    """Adiciona uma linha ao BP."""
    classif = bp.get(chave)
    if not classif:
        return

    conta = contas_idx.get(classif)
    if not conta:
        return

    indent = "    " * nivel
    prefix = "**" if bold else ""
    suffix = "**" if bold else ""
    display_name = f"{indent}{prefix}{nome}{suffix}"

    rows.append({
        "Conta": display_name,
        "Saldo Anterior": _fmt_brl(conta.saldo_anterior),
        "Saldo Atual": _fmt_brl(conta.saldo_atual),
    })


def _display_table(rows: list[dict], tipo: str) -> None:
    """Exibe a tabela formatada."""
    if not rows:
        st.info(f"Nenhum dado disponível para o {tipo}.")
        return

    # Usar HTML para melhor formatação
    html = '<table style="width:100%; border-collapse:collapse; font-size:0.9em;">'

    if tipo == "BP":
        html += '<tr style="background:#f0f0f0; border-bottom:2px solid #ccc;">'
        html += '<th style="text-align:left; padding:6px;">Conta</th>'
        html += '<th style="text-align:right; padding:6px;">Saldo Anterior</th>'
        html += '<th style="text-align:right; padding:6px;">Saldo Atual</th>'
        html += '</tr>'
    else:
        html += '<tr style="background:#f0f0f0; border-bottom:2px solid #ccc;">'
        html += '<th style="text-align:left; padding:6px;">Conta</th>'
        html += '<th style="text-align:right; padding:6px;">Saldo Atual</th>'
        html += '</tr>'

    for i, row in enumerate(rows):
        conta = row.get("Conta", "")
        is_bold = "**" in conta
        is_calculated = conta.strip().startswith("=") or conta.strip().startswith("**=")
        is_header = is_bold and not is_calculated

        # Limpar markdown
        clean = conta.replace("**", "")

        bg = ""
        if is_calculated:
            bg = "background:#e8f0fe;"
        elif is_header and "ATIVO" in clean.upper() and clean.strip() == clean.strip().upper():
            bg = "background:#f7fafc;"

        border = "border-bottom:1px solid #eee;"
        if is_calculated or is_header:
            border = "border-bottom:1px solid #ccc;"

        weight = "font-weight:bold;" if is_bold else ""

        # Preservar indentação com nbsp
        indent_count = len(clean) - len(clean.lstrip())
        display = "&nbsp;" * indent_count + clean.strip()

        html += f'<tr style="{bg}{border}">'
        html += f'<td style="padding:4px 6px;{weight}">{display}</td>'

        if tipo == "BP":
            ant = row.get("Saldo Anterior", "")
            html += f'<td style="text-align:right; padding:4px 6px;{weight}">{ant}</td>'

        atual = row.get("Saldo Atual", "")
        html += f'<td style="text-align:right; padding:4px 6px;{weight}">{atual}</td>'
        html += '</tr>'

    html += '</table>'
    st.markdown(html, unsafe_allow_html=True)
