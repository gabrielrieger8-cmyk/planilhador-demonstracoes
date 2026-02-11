"""Componentes reutilizáveis do dashboard (KPI cards, tabelas, narrativa)."""

from __future__ import annotations

from decimal import Decimal

import streamlit as st

from src.analysis.indicators import IndicadoresFinanceiros


def _fmt(val: Decimal | None, pct: bool = False) -> str:
    if val is None:
        return "N/D"
    if pct:
        return f"{float(val) * 100:.2f}%"
    f = f"{float(val):,.2f}"
    return f.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_moeda(val: Decimal | None) -> str:
    if val is None:
        return "N/D"
    return f"R$ {_fmt(val)}"


def _delta_str(atual: Decimal | None, anterior: Decimal | None) -> str | None:
    """Calcula delta para st.metric."""
    if atual is None or anterior is None:
        return None
    diff = float(atual - anterior)
    if abs(diff) < 0.001:
        return None
    return f"{diff:+.4f}"


def _delta_pct(atual: Decimal | None, anterior: Decimal | None) -> str | None:
    """Calcula delta em pontos percentuais."""
    if atual is None or anterior is None:
        return None
    d = float(atual - anterior) * 100
    if abs(d) < 0.01:
        return None
    return f"{d:+.2f}pp"


def render_kpi_cards(
    indicadores: IndicadoresFinanceiros,
    indicadores_anterior: IndicadoresFinanceiros | None = None,
) -> None:
    """Renderiza 8 cards KPI no topo do dashboard (2 linhas de 4)."""
    ant = indicadores_anterior

    # Linha 1
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Liquidez Corrente",
            value=str(indicadores.liquidez_corrente or "N/D"),
            delta=_delta_str(
                indicadores.liquidez_corrente,
                ant.liquidez_corrente if ant else None,
            ),
        )

    with col2:
        st.metric(
            label="Margem Bruta",
            value=_fmt(indicadores.margem_bruta, pct=True),
            delta=_delta_pct(
                indicadores.margem_bruta,
                ant.margem_bruta if ant else None,
            ),
        )

    with col3:
        val = indicadores.necessidade_capital_giro
        delta = None
        if ant and val is not None and ant.necessidade_capital_giro is not None:
            delta = _fmt(Decimal(str(float(val - ant.necessidade_capital_giro))))
        st.metric(
            label="NCG",
            value=_fmt_moeda(val),
            delta=delta,
            delta_color="inverse",
        )

    with col4:
        st.metric(
            label="EBITDA",
            value=_fmt_moeda(indicadores.ebitda),
            delta=_delta_str(
                indicadores.ebitda,
                ant.ebitda if ant else None,
            ),
        )

    # Linha 2
    col5, col6, col7, col8 = st.columns(4)

    with col5:
        wacc = indicadores.wacc
        st.metric(
            label="WACC",
            value=_fmt(wacc, pct=True) if wacc is not None else "N/D (CAPM)",
        )

    with col6:
        cf = indicadores.ciclo_financeiro
        st.metric(
            label="Ciclo Financeiro",
            value=f"{float(cf):.0f} dias" if cf is not None else "N/D",
            delta=_delta_str(
                cf,
                ant.ciclo_financeiro if ant else None,
            ),
            delta_color="inverse",
        )

    with col7:
        st.metric(
            label="ROE",
            value=_fmt(indicadores.roe, pct=True),
            delta=_delta_pct(
                indicadores.roe,
                ant.roe if ant else None,
            ),
        )

    with col8:
        st.metric(
            label="Endividamento Geral",
            value=_fmt(indicadores.endividamento_geral, pct=True),
            delta=_delta_pct(
                indicadores.endividamento_geral,
                ant.endividamento_geral if ant else None,
            ),
            delta_color="inverse",
        )


def render_narrative(texto: str) -> None:
    """Renderiza relatório narrativo da IA."""
    if not texto:
        st.warning("Narrativa não disponível.")
        return

    sections = texto.split("\n## ")
    if len(sections) > 1:
        if sections[0].strip():
            st.markdown(sections[0])
        for section in sections[1:]:
            title = section.split("\n")[0].strip()
            body = "\n".join(section.split("\n")[1:])
            with st.expander(title, expanded=True):
                st.markdown(body)
    else:
        st.markdown(texto)
