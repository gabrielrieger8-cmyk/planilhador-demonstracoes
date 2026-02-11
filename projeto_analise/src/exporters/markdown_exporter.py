"""Exportador de relatórios em Markdown."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from src.analysis.account_classifier import GrupoContabil, SaldosAgrupados
from src.analysis.comparative import AnaliseComparativa
from src.analysis.indicators import IndicadoresFinanceiros
from src.utils.config import OUTPUT_DIR, logger


def _fmt(val: Decimal | None, pct: bool = False) -> str:
    """Formata valor para exibição no relatório."""
    if val is None:
        return "N/D"
    if pct:
        return f"{float(val) * 100:.2f}%"
    f = f"{float(val):,.2f}"
    return f.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_moeda(val: Decimal | None) -> str:
    """Formata valor como moeda brasileira."""
    if val is None:
        return "N/D"
    return f"R$ {_fmt(val)}"


def generate_report(
    indicadores: IndicadoresFinanceiros,
    saldos: SaldosAgrupados,
    narrativa: str,
    comparativo: AnaliseComparativa | None = None,
    metadata: dict | None = None,
) -> str:
    """Gera relatório completo em Markdown.

    Args:
        indicadores: Indicadores calculados.
        saldos: Saldos agrupados.
        narrativa: Texto narrativo gerado pela IA.
        comparativo: Análise comparativa (opcional).
        metadata: Metadados (arquivo, período, etc).

    Returns:
        Conteúdo Markdown completo.
    """
    meta = metadata or {}
    lines: list[str] = []

    # Cabeçalho
    lines.append("# Relatório de Análise Econômico-Financeira")
    lines.append("")
    lines.append(f"**Arquivo:** {meta.get('arquivo', 'N/D')}")
    lines.append(f"**Período:** {meta.get('periodo', 'N/D')}")
    lines.append(f"**Data da análise:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    lines.append(f"**Modelo IA:** {meta.get('modelo', 'N/D')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Tabela de indicadores
    lines.append("## Indicadores Financeiros")
    lines.append("")
    lines.append("### Liquidez")
    lines.append("")
    lines.append("| Indicador | Valor |")
    lines.append("|-----------|-------|")
    lines.append(f"| Liquidez Corrente | {indicadores.liquidez_corrente or 'N/D'} |")
    lines.append(f"| Liquidez Seca | {indicadores.liquidez_seca or 'N/D'} |")
    lines.append(f"| Liquidez Imediata | {indicadores.liquidez_imediata or 'N/D'} |")
    lines.append(f"| Liquidez Geral | {indicadores.liquidez_geral or 'N/D'} |")
    lines.append("")

    lines.append("### Endividamento")
    lines.append("")
    lines.append("| Indicador | Valor |")
    lines.append("|-----------|-------|")
    lines.append(f"| Endividamento Geral | {_fmt(indicadores.endividamento_geral, pct=True)} |")
    lines.append(f"| Composição do Endividamento | {_fmt(indicadores.composicao_endividamento, pct=True)} |")
    lines.append(f"| Grau de Alavancagem | {indicadores.grau_alavancagem or 'N/D'} |")
    lines.append(f"| Participação Cap. Terceiros | {indicadores.participacao_capital_terceiros or 'N/D'} |")
    lines.append("")

    lines.append("### Rentabilidade")
    lines.append("")
    lines.append("| Indicador | Valor |")
    lines.append("|-----------|-------|")
    lines.append(f"| Margem Bruta | {_fmt(indicadores.margem_bruta, pct=True)} |")
    lines.append(f"| Margem Operacional | {_fmt(indicadores.margem_operacional, pct=True)} |")
    lines.append(f"| Margem Líquida | {_fmt(indicadores.margem_liquida, pct=True)} |")
    lines.append(f"| ROE | {_fmt(indicadores.roe, pct=True)} |")
    lines.append(f"| ROA | {_fmt(indicadores.roa, pct=True)} |")
    lines.append("")

    lines.append("### Capital de Giro e EBITDA")
    lines.append("")
    lines.append("| Indicador | Valor |")
    lines.append("|-----------|-------|")
    lines.append(f"| Capital Circulante Líquido | {_fmt_moeda(indicadores.capital_circulante_liquido)} |")
    lines.append(f"| Necessidade Capital de Giro | {_fmt_moeda(indicadores.necessidade_capital_giro)} |")
    lines.append(f"| EBITDA | {_fmt_moeda(indicadores.ebitda)} |")
    lines.append(f"| Margem EBITDA | {_fmt(indicadores.margem_ebitda, pct=True)} |")
    lines.append("")

    # Comparativo
    if comparativo:
        lines.append("---")
        lines.append("")
        lines.append(f"## Análise Comparativa ({comparativo.periodo_anterior} → {comparativo.periodo_atual})")
        lines.append("")

        for titulo, variacoes in [
            ("Liquidez", comparativo.variacoes_liquidez),
            ("Endividamento", comparativo.variacoes_endividamento),
            ("Rentabilidade", comparativo.variacoes_rentabilidade),
            ("Capital de Giro", comparativo.variacoes_capital_giro),
        ]:
            lines.append(f"### {titulo}")
            lines.append("")
            lines.append("| Indicador | Anterior | Atual | Variação | Tendência |")
            lines.append("|-----------|----------|-------|----------|-----------|")
            for v in variacoes:
                ant = str(v.valor_anterior) if v.valor_anterior is not None else "N/D"
                at = str(v.valor_atual) if v.valor_atual is not None else "N/D"
                delta = f"{v.variacao_percentual:+}%" if v.variacao_percentual else "—"
                tend = v.tendencia.capitalize()
                lines.append(f"| {v.nome} | {ant} | {at} | {delta} | {tend} |")
            lines.append("")

    # Narrativa IA
    lines.append("---")
    lines.append("")
    lines.append("## Análise Narrativa (IA)")
    lines.append("")
    lines.append(narrativa)
    lines.append("")

    return "\n".join(lines)


def save_report(
    content: str,
    filename: str,
    output_dir: str | Path | None = None,
) -> Path:
    """Salva relatório Markdown em arquivo.

    Args:
        content: Conteúdo Markdown.
        filename: Nome base do arquivo.
        output_dir: Diretório de saída.

    Returns:
        Path do arquivo salvo.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / f"{filename}_analise.md"
    output_path.write_text(content, encoding="utf-8")
    logger.info("Relatório MD salvo: %s", output_path)
    return output_path
