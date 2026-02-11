"""Aba de Métricas do dashboard — todos os indicadores organizados por categoria."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from src.analysis.indicators import IndicadoresFinanceiros

# Categorias com cor, indicadores (nome, fórmula, atributo, is_moeda)
CATEGORIAS = {
    "Liquidez": {
        "cor": "#2b6cb0",
        "indicadores": [
            ("Liquidez Corrente", "AC / PC", "liquidez_corrente", False),
            ("Liquidez Seca", "(AC - Estoques) / PC", "liquidez_seca", False),
            ("Liquidez Imediata", "Disponibilidades / PC", "liquidez_imediata", False),
            ("Liquidez Geral", "(AC + ANC - Imob - Intang) / (PC + PNC)", "liquidez_geral", False),
        ],
    },
    "Estrutura de Capital": {
        "cor": "#d69e2e",
        "indicadores": [
            ("Investimentos Totais", "Ativo Total", "investimentos_totais", True),
            ("Passivo Oneroso", "Emp.CP + Emp.LP + Parcelam.", "passivo_oneroso", True),
            ("Passivo Não Oneroso", "(PC + PNC) - Passivo Oneroso", "passivo_nao_oneroso", True),
            ("Investimentos Líquidos", "Ativo Total - Passivo Não Oneroso", "investimentos_liquidos", True),
            ("Capitais Próprios", "Patrimônio Líquido", "capitais_proprios", True),
            ("Capitais de Terceiros", "Passivo Oneroso", "capitais_terceiros", True),
            ("Part. Capital Próprio", "PL / Invest. Líquidos", "participacao_capital_proprio", False),
            ("Part. Capital Terceiros", "Pass. Oneroso / Invest. Líquidos", "participacao_capital_terceiros", False),
            ("KE (Custo Cap. Próprio)", "RF + (RM-RF)xBeta + RP", "ke", False),
            ("KI (Custo Cap. Terceiros)", "Desp.Fin x 0,66 / Pass. Oneroso", "ki", False),
            ("WACC", "(Part.Ke x Ke) + (Part.Ki x Ki)", "wacc", False),
        ],
    },
    "Capital de Giro": {
        "cor": "#38a169",
        "indicadores": [
            ("Capital Circulante Líquido", "AC - PC", "capital_circulante_liquido", True),
            ("Ativo Cíclico", "AC - Disponibilidades", "ativo_ciclico", True),
            ("Passivo Cíclico", "PC - Empréstimos CP", "passivo_ciclico", True),
            ("Necessidade Capital de Giro", "Ativo Cíclico - Passivo Cíclico", "necessidade_capital_giro", True),
        ],
    },
    "Prazos e Ciclo Financeiro": {
        "cor": "#b7791f",
        "indicadores": [
            ("PMP (Prazo Médio Pagamento)", "Fornecedores x {dias} / CMV", "pmp", False),
            ("PMR (Prazo Médio Recebimento)", "Clientes x {dias} / Receita Bruta", "pmr", False),
            ("PMRE (Prazo Médio Renov. Estoques)", "Estoques x {dias} / CMV", "pmre", False),
            ("Ciclo Financeiro", "PMR + PMRE - PMP", "ciclo_financeiro", False),
        ],
    },
    "Rentabilidade": {
        "cor": "#2c7a7b",
        "indicadores": [
            ("Margem Bruta", "Lucro Bruto / Receita Bruta", "margem_bruta", False),
            ("Margem de Contribuição", "(LB - Desp.Com.) / Receita Bruta", "margem_contribuicao", False),
            ("Margem Operacional", "EBIT / Receita Bruta", "margem_operacional", False),
            ("Margem Líquida", "Lucro Líquido / Receita Bruta", "margem_liquida", False),
            ("NOPAT", "EBIT (se negativo) ou EBIT x 0,66", "nopat", True),
            ("ROI", "NOPAT / Invest. Líquidos", "roi", False),
            ("ROA", "Lucro Líquido / Ativo Total", "roa", False),
            ("ROE", "Lucro Líquido / PL", "roe", False),
            ("GAF", "ROE / ROI", "gaf", False),
            ("EBITDA", "EBIT + Deprec. do Período", "ebitda", True),
            ("Margem EBITDA", "EBITDA / Receita Bruta", "margem_ebitda", False),
        ],
    },
}


def _fmt_valor(val: Decimal | None, is_moeda: bool) -> str:
    """Formata valor para exibição na tabela."""
    if val is None:
        return "N/D"
    f = float(val)
    if is_moeda:
        s = f"R$ {f:,.2f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{f:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_metricas(
    indicadores_por_periodo: dict[str, IndicadoresFinanceiros],
    dias_periodo: int = 30,
) -> None:
    """Renderiza a aba Métricas com todas as categorias.

    Se há 1 período: Nome | Fórmula | Valor
    Se há N períodos: Nome | Fórmula | Per1 | ... | PerN | Variação
    """
    periodos = sorted(indicadores_por_periodo.keys())
    n_periodos = len(periodos)

    for cat_nome, cat_config in CATEGORIAS.items():
        cor = cat_config["cor"]
        indicadores_list = cat_config["indicadores"]

        st.markdown(
            f'<div style="background-color: {cor}22; border-left: 4px solid {cor}; '
            f'padding: 0.5rem 1rem; margin: 1rem 0 0.5rem 0;">'
            f'<h3 style="color: {cor}; margin: 0;">{cat_nome}</h3></div>',
            unsafe_allow_html=True,
        )

        if n_periodos == 1:
            data = {"Indicador": [], "Fórmula": [], "Valor": []}
            ind = indicadores_por_periodo[periodos[0]]
            for nome, formula, attr, is_moeda in indicadores_list:
                val = getattr(ind, attr, None)
                data["Indicador"].append(nome)
                data["Fórmula"].append(formula.format(dias=dias_periodo))
                data["Valor"].append(_fmt_valor(val, is_moeda))
        else:
            data = {"Indicador": [], "Fórmula": []}
            for p in periodos:
                data[p] = []
            data["Var."] = []

            for nome, formula, attr, is_moeda in indicadores_list:
                data["Indicador"].append(nome)
                data["Fórmula"].append(formula.format(dias=dias_periodo))

                vals: list[Decimal | None] = []
                for p in periodos:
                    ind = indicadores_por_periodo[p]
                    val = getattr(ind, attr, None)
                    data[p].append(_fmt_valor(val, is_moeda))
                    vals.append(val)

                if (
                    len(vals) >= 2
                    and vals[-1] is not None
                    and vals[-2] is not None
                ):
                    diff = float(vals[-1] - vals[-2])
                    data["Var."].append(f"{diff:+.4f}" if abs(diff) > 0.0001 else "—")
                else:
                    data["Var."].append("—")

        st.dataframe(data, use_container_width=True, hide_index=True)

        # Avisos contextuais na seção de Prazos
        if cat_nome == "Prazos e Ciclo Financeiro":
            ind_ultimo = indicadores_por_periodo[periodos[-1]]
            if ind_ultimo.aviso_estoques:
                st.info(f"ℹ️ {ind_ultimo.aviso_estoques} — PMRE pode não ser representativo.")
            if ind_ultimo.aviso_fornecedores:
                st.info(f"ℹ️ {ind_ultimo.aviso_fornecedores} — PMP pode não ser representativo.")
