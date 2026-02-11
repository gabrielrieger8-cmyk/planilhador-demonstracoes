"""Gráficos do dashboard usando Plotly."""

from __future__ import annotations

from decimal import Decimal

import plotly.graph_objects as go

from src.analysis.account_classifier import GrupoContabil, SaldosAgrupados
from src.analysis.indicators import IndicadoresFinanceiros

# Paleta de cores
AZUL = "#2b6cb0"
AZUL_CLARO = "#63b3ed"
VERDE = "#38a169"
VERMELHO = "#e53e3e"
LARANJA = "#dd6b20"
ROXO = "#805ad5"
CINZA = "#a0aec0"
AMARELO = "#d69e2e"
TEAL = "#2c7a7b"


def _to_float(val: Decimal | None) -> float:
    return float(val) if val is not None else 0.0


def chart_liquidez(indicadores: IndicadoresFinanceiros) -> go.Figure:
    """Gráfico de barras dos índices de liquidez."""
    nomes = ["Corrente", "Seca", "Imediata", "Geral"]
    valores = [
        _to_float(indicadores.liquidez_corrente),
        _to_float(indicadores.liquidez_seca),
        _to_float(indicadores.liquidez_imediata),
        _to_float(indicadores.liquidez_geral),
    ]

    cores = [VERDE if v >= 1.0 else VERMELHO for v in valores]

    fig = go.Figure(data=[
        go.Bar(
            x=nomes, y=valores, marker_color=cores,
            text=[f"{v:.2f}" for v in valores], textposition="auto",
        )
    ])
    fig.add_hline(y=1.0, line_dash="dash", line_color=CINZA, annotation_text="Ref. (1,0)")
    fig.update_layout(
        title="Indicadores de Liquidez",
        yaxis_title="Índice",
        height=350,
        margin=dict(t=40, b=30, l=40, r=20),
    )
    return fig


def chart_composicao_patrimonial(saldos: SaldosAgrupados) -> go.Figure:
    """Gráfico de pizza da composição patrimonial."""
    g = saldos.get
    labels = [
        "Ativo Circulante", "Ativo Não Circulante",
        "Passivo Circulante", "Passivo Não Circulante",
        "Patrimônio Líquido",
    ]
    values = [
        abs(_to_float(g(GrupoContabil.ATIVO_CIRCULANTE))),
        abs(_to_float(g(GrupoContabil.ATIVO_NAO_CIRCULANTE))),
        abs(_to_float(g(GrupoContabil.PASSIVO_CIRCULANTE))),
        abs(_to_float(g(GrupoContabil.PASSIVO_NAO_CIRCULANTE))),
        abs(_to_float(g(GrupoContabil.PATRIMONIO_LIQUIDO))),
    ]
    cores = [AZUL, AZUL_CLARO, VERMELHO, LARANJA, VERDE]

    fig = go.Figure(data=[
        go.Pie(
            labels=labels, values=values,
            marker=dict(colors=cores),
            textinfo="label+percent", hole=0.35,
        )
    ])
    fig.update_layout(
        title="Composição Patrimonial",
        height=350,
        margin=dict(t=40, b=30, l=20, r=20),
        showlegend=False,
    )
    return fig


def chart_rentabilidade(indicadores: IndicadoresFinanceiros) -> go.Figure:
    """Gráfico de barras horizontais de rentabilidade."""
    nomes = [
        "Margem Bruta", "Margem Contribuição", "Margem Operacional",
        "Margem Líquida", "ROA", "ROE",
    ]
    valores = [
        _to_float(indicadores.margem_bruta) * 100,
        _to_float(indicadores.margem_contribuicao) * 100,
        _to_float(indicadores.margem_operacional) * 100,
        _to_float(indicadores.margem_liquida) * 100,
        _to_float(indicadores.roa) * 100,
        _to_float(indicadores.roe) * 100,
    ]

    cores = [VERDE if v >= 0 else VERMELHO for v in valores]

    fig = go.Figure(data=[
        go.Bar(
            y=nomes, x=valores, orientation="h",
            marker_color=cores,
            text=[f"{v:.1f}%" for v in valores],
            textposition="auto",
        )
    ])
    fig.add_vline(x=0, line_color=CINZA)
    fig.update_layout(
        title="Indicadores de Rentabilidade (%)",
        xaxis_title="Percentual (%)",
        height=380,
        margin=dict(t=40, b=30, l=140, r=20),
    )
    return fig


def chart_estrutura_capital(indicadores: IndicadoresFinanceiros) -> go.Figure:
    """Gráfico de barras agrupadas: Capital Próprio vs Terceiros.

    PL negativo aparece como barra abaixo do eixo zero.
    """
    cap_proprio = _to_float(indicadores.capitais_proprios)  # mantém sinal
    cap_terceiros = _to_float(indicadores.capitais_terceiros)

    cor_pl = VERDE if cap_proprio >= 0 else VERMELHO

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Capitais Próprios (PL)", "Capitais de Terceiros"],
        y=[cap_proprio, cap_terceiros],
        marker_color=[cor_pl, LARANJA],
        text=[f"R$ {cap_proprio:,.0f}", f"R$ {cap_terceiros:,.0f}"],
        textposition="outside",
    ))
    fig.add_hline(y=0, line_color=CINZA)
    fig.update_layout(
        title="Estrutura de Capital",
        yaxis_title="R$",
        height=350,
        margin=dict(t=40, b=30, l=40, r=20),
        showlegend=False,
    )
    return fig


def chart_ciclo_financeiro(indicadores: IndicadoresFinanceiros) -> go.Figure | None:
    """Gráfico de barras do ciclo financeiro (PMP, PMR, PMRE, Ciclo)."""
    pmp = _to_float(indicadores.pmp)
    pmr = _to_float(indicadores.pmr)
    pmre = _to_float(indicadores.pmre)
    ciclo = _to_float(indicadores.ciclo_financeiro)

    if pmp == 0 and pmr == 0 and pmre == 0:
        return None

    nomes = ["PMP", "PMR", "PMRE", "Ciclo Financeiro"]
    valores = [pmp, pmr, pmre, ciclo]
    cores = [AZUL, AMARELO, LARANJA, TEAL if ciclo >= 0 else VERMELHO]

    fig = go.Figure(data=[
        go.Bar(
            x=nomes, y=valores, marker_color=cores,
            text=[f"{v:.0f} dias" for v in valores],
            textposition="auto",
        )
    ])
    fig.add_hline(y=0, line_color=CINZA)
    fig.update_layout(
        title="Prazos e Ciclo Financeiro (dias)",
        yaxis_title="Dias",
        height=350,
        margin=dict(t=40, b=30, l=40, r=20),
    )
    return fig


def chart_dre(indicadores: IndicadoresFinanceiros) -> go.Figure:
    """Gráfico waterfall simplificado do DRE."""
    nomes = [
        "Receita Bruta", "Deduções", "Receita Líquida",
        "Custos", "Lucro Bruto", "Despesas", "Resultado",
    ]

    rec_bruta = _to_float(indicadores.receita_bruta)
    rec_liq = _to_float(indicadores.receita_liquida)
    deducoes = rec_bruta - rec_liq
    lucro_bruto = _to_float(indicadores.lucro_bruto)
    custos = rec_liq - lucro_bruto
    resultado = _to_float(indicadores.lucro_liquido)
    despesas = lucro_bruto - resultado

    fig = go.Figure(go.Waterfall(
        name="DRE",
        orientation="v",
        x=nomes,
        y=[rec_bruta, -deducoes, 0, -custos, 0, -despesas, 0],
        measure=["absolute", "relative", "total", "relative", "total", "relative", "total"],
        text=[
            f"R$ {v:,.0f}" for v in [
                rec_bruta, deducoes, rec_liq, custos,
                lucro_bruto, despesas, resultado,
            ]
        ],
        textposition="outside",
        connector={"line": {"color": CINZA}},
        increasing={"marker": {"color": VERDE}},
        decreasing={"marker": {"color": VERMELHO}},
        totals={"marker": {"color": AZUL}},
    ))
    fig.update_layout(
        title="Demonstração do Resultado (Cascata)",
        height=400,
        margin=dict(t=40, b=30, l=40, r=20),
        showlegend=False,
    )
    return fig
