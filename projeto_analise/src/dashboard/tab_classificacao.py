"""Aba de Classificação do dashboard — tabela editável de mapeamento IA."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analysis.account_classifier import GrupoContabil
from src.parsers.csv_parser import Balancete

_GRUPOS_OPCOES = [g.value for g in GrupoContabil]


def render_classificacao(
    balancete: Balancete,
    classificacao_ia: dict[str, str],
) -> None:
    """Renderiza tabela editável de classificação de contas.

    Args:
        balancete: Balancete parseado.
        classificacao_ia: Mapa {classificação → grupo} retornado pela IA.
    """
    st.subheader("Classificação de Contas")
    st.caption(
        "A IA classificou cada conta do balancete em um grupo contábil padronizado. "
        "Edite a coluna **Grupo Manual** e clique em **Recalcular** para atualizar."
    )

    rows = []
    for conta in balancete.contas:
        grupo_ia = classificacao_ia.get(conta.classificacao, "")
        rows.append({
            "Classificação": conta.classificacao,
            "Descrição": conta.descricao,
            "Grupo IA": grupo_ia,
            "Grupo Manual": grupo_ia,
        })

    if not rows:
        st.warning("Nenhuma conta encontrada no balancete.")
        return

    df = pd.DataFrame(rows)

    # Apply stored manual edits
    editada = st.session_state.get("classificacao_editada")
    if editada:
        for i, row in df.iterrows():
            classif = row["Classificação"]
            if classif in editada:
                df.at[i, "Grupo Manual"] = editada[classif]

    edited_df = st.data_editor(
        df,
        column_config={
            "Classificação": st.column_config.TextColumn(disabled=True, width="small"),
            "Descrição": st.column_config.TextColumn(disabled=True, width="large"),
            "Grupo IA": st.column_config.TextColumn(disabled=True, width="medium"),
            "Grupo Manual": st.column_config.SelectboxColumn(
                options=_GRUPOS_OPCOES,
                required=True,
                width="medium",
            ),
        },
        hide_index=True,
        use_container_width=True,
        key="classif_editor",
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Recalcular", type="primary"):
            new_classificacao = {}
            for _, row in edited_df.iterrows():
                classif = row["Classificação"]
                grupo = row["Grupo Manual"]
                if grupo:
                    new_classificacao[classif] = grupo

            st.session_state["classificacao_editada"] = new_classificacao

            from src.orchestrator import Orchestrator

            orch = Orchestrator()
            params_capm = st.session_state.get("params_capm")
            dias_periodo = st.session_state.get("dias_periodo", 30)

            results = st.session_state.get("results", {})
            for _periodo, result in results.items():
                if result.balancete:
                    saldos = orch.group(result.balancete, new_classificacao)
                    indicadores = orch.calculate(saldos, params_capm, dias_periodo)
                    comparativo = orch.compare(saldos)
                    result.classificacao_ia = new_classificacao
                    result.saldos = saldos
                    result.indicadores = indicadores
                    result.comparativo = comparativo
                    result.narrativa = ""

            st.session_state["results"] = results
            st.session_state["classificacao_ia"] = new_classificacao
            st.success("Indicadores recalculados!")
            st.rerun()

    with col2:
        n_changed = sum(
            1
            for _, row in edited_df.iterrows()
            if row["Grupo IA"] != row["Grupo Manual"]
        )
        if n_changed > 0:
            st.warning(f"{n_changed} classificação(ões) alterada(s) manualmente.")
