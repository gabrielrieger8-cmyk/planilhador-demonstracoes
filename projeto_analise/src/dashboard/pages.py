"""Páginas do dashboard Streamlit (mantido para compatibilidade)."""

from __future__ import annotations

import streamlit as st

from src.analysis.account_classifier import SaldosAgrupados
from src.analysis.comparative import AnaliseComparativa
from src.analysis.indicators import IndicadoresFinanceiros
from src.dashboard.charts import (
    chart_composicao_patrimonial,
    chart_dre,
    chart_estrutura_capital,
    chart_liquidez,
    chart_rentabilidade,
)
from src.dashboard.components import (
    render_kpi_cards,
    render_narrative,
)


def page_overview(
    indicadores: IndicadoresFinanceiros,
    saldos: SaldosAgrupados,
    narrativa: str,
    indicadores_anterior: IndicadoresFinanceiros | None = None,
    comparativo: AnaliseComparativa | None = None,
) -> None:
    """Renderiza a página principal do dashboard (compatibilidade)."""

    render_kpi_cards(indicadores, indicadores_anterior)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(chart_liquidez(indicadores), use_container_width=True)
    with col2:
        st.plotly_chart(chart_composicao_patrimonial(saldos), use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(chart_rentabilidade(indicadores), use_container_width=True)
    with col4:
        st.plotly_chart(chart_estrutura_capital(indicadores), use_container_width=True)

    st.plotly_chart(chart_dre(indicadores), use_container_width=True)

    st.divider()

    st.header("Relatório da IA")
    render_narrative(narrativa)
