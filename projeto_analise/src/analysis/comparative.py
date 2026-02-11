"""Análise comparativa entre períodos.

Compara indicadores financeiros e saldos entre dois períodos,
calculando variações absolutas, percentuais e tendências.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from src.analysis.account_classifier import GrupoContabil, SaldosAgrupados
from src.analysis.indicators import IndicadoresFinanceiros


@dataclass
class VariacaoIndicador:
    """Variação de um indicador entre dois períodos."""

    nome: str
    valor_anterior: Decimal | None
    valor_atual: Decimal | None
    variacao_absoluta: Decimal | None = None
    variacao_percentual: Decimal | None = None
    tendencia: str = "estavel"  # "melhora", "piora", "estavel"


@dataclass
class AnaliseComparativa:
    """Resultado completo da análise comparativa."""

    periodo_anterior: str
    periodo_atual: str
    variacoes_liquidez: list[VariacaoIndicador] = field(default_factory=list)
    variacoes_endividamento: list[VariacaoIndicador] = field(default_factory=list)
    variacoes_rentabilidade: list[VariacaoIndicador] = field(default_factory=list)
    variacoes_capital_giro: list[VariacaoIndicador] = field(default_factory=list)


# Mapa de indicadores: nome → (atributo, direção positiva)
# True = maior é melhor, False = menor é melhor
_INDICADORES_LIQUIDEZ = [
    ("Liquidez Corrente", "liquidez_corrente", True),
    ("Liquidez Seca", "liquidez_seca", True),
    ("Liquidez Imediata", "liquidez_imediata", True),
    ("Liquidez Geral", "liquidez_geral", True),
]

_INDICADORES_ENDIVIDAMENTO = [
    ("Endividamento Geral", "endividamento_geral", False),
    ("Composição Endividamento", "composicao_endividamento", False),
    ("Grau de Alavancagem", "grau_alavancagem", False),
    ("Participação Cap. Terceiros", "participacao_capital_terceiros", False),
]

_INDICADORES_RENTABILIDADE = [
    ("Margem Bruta", "margem_bruta", True),
    ("Margem Operacional", "margem_operacional", True),
    ("Margem Líquida", "margem_liquida", True),
    ("ROE", "roe", True),
    ("ROA", "roa", True),
]

_INDICADORES_CAPITAL_GIRO = [
    ("Capital Circulante Líquido", "capital_circulante_liquido", True),
    ("Necessidade Capital Giro", "necessidade_capital_giro", False),
    ("EBITDA", "ebitda", True),
]


def _calcular_variacao(
    nome: str,
    anterior: Decimal | None,
    atual: Decimal | None,
    maior_melhor: bool,
) -> VariacaoIndicador:
    """Calcula a variação entre dois valores de um indicador."""
    var = VariacaoIndicador(nome=nome, valor_anterior=anterior, valor_atual=atual)

    if anterior is not None and atual is not None:
        var.variacao_absoluta = atual - anterior
        if anterior != 0:
            var.variacao_percentual = (
                ((atual - anterior) / abs(anterior)) * 100
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Determina tendência
        diff = atual - anterior
        if abs(diff) < Decimal("0.001"):
            var.tendencia = "estavel"
        elif (diff > 0 and maior_melhor) or (diff < 0 and not maior_melhor):
            var.tendencia = "melhora"
        else:
            var.tendencia = "piora"

    return var


def comparar_periodos(
    anterior: IndicadoresFinanceiros,
    atual: IndicadoresFinanceiros,
    periodo_anterior: str = "Anterior",
    periodo_atual: str = "Atual",
) -> AnaliseComparativa:
    """Compara indicadores entre dois períodos.

    Args:
        anterior: Indicadores do período anterior.
        atual: Indicadores do período atual.
        periodo_anterior: Label do período anterior.
        periodo_atual: Label do período atual.

    Returns:
        AnaliseComparativa com todas as variações.
    """
    comp = AnaliseComparativa(
        periodo_anterior=periodo_anterior,
        periodo_atual=periodo_atual,
    )

    for nome, attr, maior_melhor in _INDICADORES_LIQUIDEZ:
        comp.variacoes_liquidez.append(_calcular_variacao(
            nome, getattr(anterior, attr), getattr(atual, attr), maior_melhor,
        ))

    for nome, attr, maior_melhor in _INDICADORES_ENDIVIDAMENTO:
        comp.variacoes_endividamento.append(_calcular_variacao(
            nome, getattr(anterior, attr), getattr(atual, attr), maior_melhor,
        ))

    for nome, attr, maior_melhor in _INDICADORES_RENTABILIDADE:
        comp.variacoes_rentabilidade.append(_calcular_variacao(
            nome, getattr(anterior, attr), getattr(atual, attr), maior_melhor,
        ))

    for nome, attr, maior_melhor in _INDICADORES_CAPITAL_GIRO:
        comp.variacoes_capital_giro.append(_calcular_variacao(
            nome, getattr(anterior, attr), getattr(atual, attr), maior_melhor,
        ))

    return comp


def comparar_colunas(
    saldos: SaldosAgrupados,
) -> AnaliseComparativa:
    """Compara saldos anteriores vs atuais dentro de um mesmo balancete.

    Útil para análise de um único arquivo usando Saldo Anterior vs Saldo Atual.

    Args:
        saldos: SaldosAgrupados contendo tanto grupos (atual) quanto grupos_anterior.

    Returns:
        AnaliseComparativa.
    """
    from src.analysis.indicators import calcular_indicadores

    ind_anterior = calcular_indicadores(
        SaldosAgrupados(grupos=saldos.grupos_anterior)
    )
    ind_atual = calcular_indicadores(saldos)

    return comparar_periodos(ind_anterior, ind_atual, "Saldo Anterior", "Saldo Atual")
