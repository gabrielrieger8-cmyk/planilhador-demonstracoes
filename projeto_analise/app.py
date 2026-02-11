"""Dashboard interativo Streamlit para análise financeira.

Execute: streamlit run app.py
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Análise Financeira",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.utils.config import EMPRESAS_DIR, MODELOS_RELATORIO
from src.utils.empresa_manager import Company, EmpresaManager


def _extract_periodo(filename: str) -> str:
    """Extrai período do nome do arquivo (ex: 112025 → 11/2025)."""
    match = re.search(r"(\d{6})", filename)
    if match:
        mmyyyy = match.group(1)
        return f"{mmyyyy[:2]}/{mmyyyy[2:]}"
    return filename.split("_")[0]


def _get_manager() -> EmpresaManager:
    """Retorna (ou cria) o EmpresaManager no session_state."""
    if "_app_manager" not in st.session_state:
        st.session_state["_app_manager"] = EmpresaManager(EMPRESAS_DIR)
    return st.session_state["_app_manager"]


def _build_empresa_options(manager: EmpresaManager) -> dict[str, Company]:
    """Constrói mapa label → Company para o selectbox global."""
    structure = manager.scan_structure()
    options: dict[str, Company] = {}
    for company in structure.standalone_companies:
        options[company.name] = company
    for group in structure.groups:
        for company in group.companies:
            options[f"{group.name} > {company.name}"] = company
    return options


def _list_csv_files_from_empresa(empresa: Company | None) -> dict[str, Path]:
    """Lista CSVs da pasta analise/ da empresa ativa, priorizando _sintetico_sinal."""
    if empresa is None:
        return {}

    csv_sources: list[Path] = []
    if empresa.analise_dir.exists():
        csv_sources.extend(empresa.analise_dir.glob("*.csv"))

    def sort_key(p: Path) -> tuple[int, str]:
        if "sintetico_sinal" in p.name:
            return (0, p.name)
        if "sintetico" in p.name:
            return (1, p.name)
        if "sinal" in p.name:
            return (2, p.name)
        return (3, p.name)

    csv_sources.sort(key=sort_key)
    return {p.name: p for p in csv_sources}


def main() -> None:
    st.title("📊 Análise Econômico-Financeira")

    manager = _get_manager()

    # --- Seletor global de empresa (acima das abas) ---
    empresa_options = _build_empresa_options(manager)

    if empresa_options:
        option_labels = ["(Nenhuma)"] + list(empresa_options.keys())
        current_label = st.session_state.get("_empresa_ativa_label", "(Nenhuma)")
        if current_label not in option_labels:
            current_label = "(Nenhuma)"

        selected_label = st.selectbox(
            "Empresa ativa",
            options=option_labels,
            index=option_labels.index(current_label),
            key="_empresa_selectbox",
        )

        # Detecta mudança de empresa
        if selected_label != st.session_state.get("_empresa_ativa_label"):
            st.session_state["_empresa_ativa_label"] = selected_label
            # Limpa resultados de análise anterior
            st.session_state.pop("results", None)
            st.session_state.pop("classificacao_ia", None)

        empresa_ativa = empresa_options.get(selected_label)
        st.session_state["empresa_ativa"] = empresa_ativa
    else:
        empresa_ativa = None
        st.session_state["empresa_ativa"] = None
        st.info("Nenhuma empresa cadastrada. Crie uma na aba **Conversão**.")

    # --- Sidebar ---
    with st.sidebar:
        st.header("Configurações")

        # Seleção de arquivo(s) da empresa ativa
        csv_files = _list_csv_files_from_empresa(empresa_ativa)

        uploaded = st.file_uploader("Upload CSV", type=["csv"])

        if csv_files:
            default_sel = [k for k in csv_files if "sintetico_sinal" in k][:1]
            selected_names = st.multiselect(
                "Selecionar arquivo(s):",
                options=list(csv_files.keys()),
                default=default_sel,
            )
        else:
            selected_names = []
            if empresa_ativa:
                st.caption("Nenhum CSV em `analise/`. Copie CSVs na aba Conversão.")
            else:
                st.caption("Selecione uma empresa acima.")

        st.divider()

        # Modelo para relatório
        modelo_relatorio = st.selectbox(
            "Modelo para Relatório",
            options=list(MODELOS_RELATORIO.keys()),
            index=0,
        )

        st.divider()

        # Período da demonstração
        st.subheader("Período da Demonstração")
        periodo_tipo = st.selectbox(
            "Tipo de período",
            options=["Mensal", "Trimestral", "Semestral", "Anual"],
            index=0,
        )
        _DIAS_PERIODO = {"Mensal": 30, "Trimestral": 90, "Semestral": 180, "Anual": 360}
        dias_periodo = _DIAS_PERIODO[periodo_tipo]

        st.divider()

        # CAPM Parameters
        st.subheader("Parâmetros CAPM")
        c1, c2 = st.columns(2)
        with c1:
            rf = st.number_input(
                "RF (%)", min_value=0.0, max_value=100.0,
                value=0.0, step=0.1, format="%.2f",
            )
            beta = st.number_input(
                "Beta", min_value=0.0, max_value=5.0,
                value=1.0, step=0.1, format="%.2f",
            )
        with c2:
            rm = st.number_input(
                "RM (%)", min_value=0.0, max_value=100.0,
                value=0.0, step=0.1, format="%.2f",
            )
            rp = st.number_input(
                "RP (%)", min_value=0.0, max_value=100.0,
                value=0.0, step=0.1, format="%.2f",
            )

        use_capm = any([rf > 0, rm > 0, rp > 0])

        st.divider()

        analyze_btn = st.button(
            "🔍 Analisar", type="primary", use_container_width=True,
        )

    # --- Determina arquivos ---
    csv_paths: list[Path] = []

    if uploaded is not None and empresa_ativa:
        tmp_path = empresa_ativa.analise_dir / uploaded.name
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(uploaded.getvalue())
        csv_paths.append(tmp_path)

    for name in selected_names:
        if name in csv_files:
            csv_paths.append(csv_files[name])

    # --- Análise ---
    if analyze_btn:
        if not csv_paths:
            st.error("Selecione ou faça upload de um arquivo CSV.")
            return

        from src.analysis.indicators import ParamsCAPM
        from src.orchestrator import Orchestrator

        orch = Orchestrator()
        params_capm = None
        if use_capm:
            params_capm = ParamsCAPM(
                rf=Decimal(str(rf / 100)),
                rm=Decimal(str(rm / 100)),
                beta=Decimal(str(beta)),
                rp=Decimal(str(rp / 100)),
            )

        # Reutilizar classificação IA entre períodos da mesma empresa
        classificacao_ia = st.session_state.get("classificacao_editada")

        results: dict = {}
        for csv_path in csv_paths:
            periodo = _extract_periodo(csv_path.name)
            with st.spinner(f"Analisando {csv_path.name}..."):
                result = orch.analyze(
                    csv_path,
                    classificacao_ia=classificacao_ia,
                    params_capm=params_capm,
                    dias_periodo=dias_periodo,
                    skip_narrative=True,
                )

                if result.success:
                    results[periodo] = result
                    if classificacao_ia is None and result.classificacao_ia:
                        classificacao_ia = result.classificacao_ia
                else:
                    st.error(f"Erro em {csv_path.name}: {result.error}")

        if results:
            st.session_state["results"] = results
            st.session_state["classificacao_ia"] = classificacao_ia
            st.session_state["params_capm"] = params_capm
            st.session_state["dias_periodo"] = dias_periodo
            st.session_state["modelo_relatorio"] = modelo_relatorio

    # --- Tabs (sempre visíveis) ---
    tab_conversao, tab_dash, tab_metricas, tab_demonstracoes, tab_relatorio = st.tabs([
        "🔄 Conversão", "📊 Dashboard", "📈 Métricas", "📋 Demonstrações", "📝 Relatório",
    ])

    with tab_conversao:
        _render_tab_conversao()

    # Tabs de análise requerem resultados
    if "results" not in st.session_state:
        with tab_dash:
            if empresa_ativa:
                st.info("Selecione um arquivo CSV e clique em **Analisar** para começar.")
            else:
                st.info("Selecione uma empresa acima para começar.")
        return

    results = st.session_state["results"]
    periodos = sorted(results.keys())
    ultimo = periodos[-1]
    result = results[ultimo]

    with tab_dash:
        st.caption(
            f"Período(s): **{', '.join(periodos)}** | "
            f"Tempo: **{sum(r.processing_time for r in results.values()):.1f}s**"
        )
        _render_tab_dashboard(results, periodos)

    with tab_metricas:
        _render_tab_metricas(results, periodos)

    with tab_demonstracoes:
        _render_tab_demonstracoes(result)

    with tab_relatorio:
        _render_tab_relatorio(results, periodos)


# -----------------------------------------------------------------
# Tab renderers
# -----------------------------------------------------------------


def _render_tab_conversao() -> None:
    from src.dashboard.tab_conversao import render_conversao

    render_conversao(EMPRESAS_DIR)


def _render_tab_dashboard(results: dict, periodos: list[str]) -> None:
    from src.analysis.account_classifier import SaldosAgrupados
    from src.analysis.indicators import calcular_indicadores_completos
    from src.dashboard.charts import (
        chart_ciclo_financeiro,
        chart_composicao_patrimonial,
        chart_dre,
        chart_estrutura_capital,
        chart_liquidez,
        chart_rentabilidade,
    )
    from src.dashboard.components import render_kpi_cards

    ultimo = periodos[-1]
    result = results[ultimo]

    # Indicadores anteriores para deltas
    indicadores_anterior = None
    if len(periodos) > 1:
        penultimo = periodos[-2]
        indicadores_anterior = results[penultimo].indicadores
    elif result.saldos:
        saldos_ant = SaldosAgrupados(grupos=result.saldos.grupos_anterior)
        params = st.session_state.get("params_capm")
        dias = st.session_state.get("dias_periodo", 30)
        indicadores_anterior = calcular_indicadores_completos(saldos_ant, params, dias)

    render_kpi_cards(result.indicadores, indicadores_anterior)

    st.divider()

    # Charts - row 1
    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(chart_liquidez(result.indicadores), use_container_width=True)
    with col2:
        st.plotly_chart(
            chart_composicao_patrimonial(result.saldos), use_container_width=True,
        )

    # Charts - row 2
    col3, col4 = st.columns(2)
    with col3:
        st.plotly_chart(
            chart_rentabilidade(result.indicadores), use_container_width=True,
        )
    with col4:
        st.plotly_chart(
            chart_estrutura_capital(result.indicadores), use_container_width=True,
        )

    # Charts - row 3
    col5, col6 = st.columns(2)
    with col5:
        st.plotly_chart(chart_dre(result.indicadores), use_container_width=True)
    with col6:
        fig_ciclo = chart_ciclo_financeiro(result.indicadores)
        if fig_ciclo:
            st.plotly_chart(fig_ciclo, use_container_width=True)


def _render_tab_metricas(results: dict, periodos: list[str]) -> None:
    from src.dashboard.tab_metricas import render_metricas

    dias = st.session_state.get("dias_periodo", 30)
    indicadores_por_periodo = {p: results[p].indicadores for p in periodos}
    render_metricas(indicadores_por_periodo, dias)


def _render_tab_demonstracoes(result) -> None:
    from src.dashboard.tab_demonstracoes import render_demonstracoes

    if result.balancete and result.classificacao_ia and result.indicadores:
        render_demonstracoes(result.indicadores, result.balancete, result.classificacao_ia)
    else:
        st.info("Demonstrações não disponíveis. Execute a análise primeiro.")


def _render_tab_relatorio(results: dict, periodos: list[str]) -> None:
    from src.dashboard.components import render_narrative
    from src.utils.config import MODELOS_RELATORIO

    ultimo = periodos[-1]
    result = results[ultimo]

    if result.narrativa:
        render_narrative(result.narrativa)
    else:
        st.info("Clique em **Gerar Relatório** para criar a análise narrativa com IA.")

        modelo = st.session_state.get("modelo_relatorio", "Claude Sonnet 4.5")
        model_info = MODELOS_RELATORIO.get(modelo, {})

        st.caption(f"Modelo selecionado: **{modelo}**")

        if st.button("📝 Gerar Relatório", type="primary"):
            provider = model_info.get("provider", "gemini")
            model_id = model_info.get("model", "")

            with st.spinner(f"Gerando relatório com {modelo}..."):
                from src.orchestrator import Orchestrator

                orch = Orchestrator()
                narrative_result = orch.generate_narrative(
                    result.indicadores,
                    result.saldos,
                    result.comparativo,
                    provider=provider,
                    model=model_id,
                )

                if narrative_result.success:
                    result.narrativa = narrative_result.texto
                    results[ultimo] = result
                    st.session_state["results"] = results
                    st.rerun()
                else:
                    st.error(f"Erro: {narrative_result.error}")


if __name__ == "__main__":
    main()
