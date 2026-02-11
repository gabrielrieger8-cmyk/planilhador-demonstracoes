"""Agente Gemini para geração de relatórios narrativos financeiros."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from src.analysis.account_classifier import GrupoContabil, SaldosAgrupados
from src.analysis.comparative import AnaliseComparativa
from src.analysis.indicators import IndicadoresFinanceiros
from src.utils.config import GEMINI_API_KEY, config, logger

SYSTEM_PROMPT = """\
Você é um analista financeiro especializado em empresas brasileiras.
Sua tarefa é produzir um relatório de análise econômico-financeira
completo e profissional em Português do Brasil.

O relatório deve conter:
1. RESUMO EXECUTIVO — Visão geral da saúde financeira (2-3 parágrafos)
2. ANÁLISE DE LIQUIDEZ — Interpretação dos 4 índices de liquidez
3. ESTRUTURA DE CAPITAL — Passivo Oneroso vs Não Oneroso, Investimentos Líquidos, WACC
4. CAPITAL DE GIRO — NCG, Ativo/Passivo Cíclico e suas implicações
5. PRAZOS E CICLO FINANCEIRO — PMP, PMR, PMRE e Ciclo Financeiro
6. RENTABILIDADE — Margens, NOPAT, ROI, ROA, ROE, GAF, EBITDA
7. PONTOS DE ATENÇÃO — Riscos identificados e alertas
8. RECOMENDAÇÕES — Ações sugeridas para melhorar a saúde financeira

Diretrizes:
- Use linguagem profissional mas acessível
- Cite os números específicos dos indicadores
- Compare com benchmarks setoriais quando possível
- Seja objetivo e direto nas recomendações
- Formate em Markdown com cabeçalhos claros
- Se KE, KI ou WACC foram calculados, analise o custo de capital
"""


@dataclass
class NarrativeResult:
    """Resultado da geração de narrativa por IA."""

    texto: str
    modelo: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    processing_time: float = 0.0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None


class GeminiNarrativeAgent:
    """Agente que usa Google Gemini para gerar relatórios narrativos."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or GEMINI_API_KEY
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate_narrative(
        self,
        indicadores: IndicadoresFinanceiros,
        saldos: SaldosAgrupados,
        comparativo: AnaliseComparativa | None = None,
        model: str | None = None,
    ) -> NarrativeResult:
        """Gera relatório narrativo a partir dos indicadores.

        Args:
            indicadores: Indicadores calculados.
            saldos: Saldos agrupados.
            comparativo: Comparativo entre períodos (opcional).
            model: ID do modelo Gemini (usa config padrão se None).
        """
        if not self._api_key:
            return NarrativeResult(
                texto="", success=False,
                error="GEMINI_API_KEY não configurada.",
            )

        model_to_use = model or config.gemini_model
        start = time.time()
        try:
            client = self._get_client()
            user_prompt = _build_user_prompt(indicadores, saldos, comparativo)

            response = client.models.generate_content(
                model=model_to_use,
                contents=[f"{SYSTEM_PROMPT}\n\n{user_prompt}"],
                config={
                    "temperature": config.temperature,
                    "max_output_tokens": config.max_tokens,
                },
            )

            texto = response.text or ""
            tokens_in = 0
            tokens_out = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                meta = response.usage_metadata
                tokens_in = getattr(meta, "prompt_token_count", 0) or 0
                tokens_out = getattr(meta, "candidates_token_count", 0) or 0

            cost = (tokens_in / 1_000_000) * 0.15 + (tokens_out / 1_000_000) * 0.60

            return NarrativeResult(
                texto=texto,
                modelo=model_to_use,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                processing_time=time.time() - start,
                estimated_cost=round(cost, 6),
            )

        except Exception as exc:
            return NarrativeResult(
                texto="", success=False,
                error=f"Erro Gemini: {exc}",
                processing_time=time.time() - start,
            )


def _format_decimal(val: Decimal | None, pct: bool = False) -> str:
    """Formata Decimal para exibição."""
    if val is None:
        return "N/D"
    if pct:
        return f"{float(val) * 100:.2f}%"
    return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(val: Decimal | None) -> str:
    """Formata indicador numérico."""
    if val is None:
        return "N/D"
    return str(float(val))


def _build_user_prompt(
    ind: IndicadoresFinanceiros,
    saldos: SaldosAgrupados,
    comp: AnaliseComparativa | None,
) -> str:
    """Constrói o prompt com os dados financeiros completos."""
    g = saldos.get
    G = GrupoContabil

    lines = [
        "DADOS FINANCEIROS PARA ANÁLISE",
        "=" * 50,
        "",
        "BALANÇO PATRIMONIAL (Saldos Atuais)",
        f"  Ativo Total: {_format_decimal(abs(g(G.ATIVO_TOTAL)))}",
        f"    Ativo Circulante: {_format_decimal(abs(g(G.ATIVO_CIRCULANTE)))}",
        f"      Disponibilidades: {_format_decimal(abs(g(G.DISPONIBILIDADES)))}",
        f"      Clientes: {_format_decimal(abs(g(G.CLIENTES)))}",
        f"      Estoques: {_format_decimal(abs(g(G.ESTOQUES)))}",
        f"      Outros Créditos CP: {_format_decimal(abs(g(G.OUTROS_CREDITOS_CP)))}",
        f"      Despesas Antecipadas: {_format_decimal(abs(g(G.DESPESAS_ANTECIPADAS)))}",
        f"    Ativo Não Circulante: {_format_decimal(abs(g(G.ATIVO_NAO_CIRCULANTE)))}",
        f"      Investimentos: {_format_decimal(abs(g(G.INVESTIMENTOS)))}",
        f"      Imobilizado: {_format_decimal(abs(g(G.IMOBILIZADO)))}",
        f"      Intangível: {_format_decimal(abs(g(G.INTANGIVEL)))}",
        f"      Depreciação/Amortização: {_format_decimal(abs(g(G.DEPRECIACAO_AMORTIZACAO)))}",
        "",
        f"  Passivo Total: {_format_decimal(abs(g(G.PASSIVO_TOTAL)))}",
        f"    Passivo Circulante: {_format_decimal(abs(g(G.PASSIVO_CIRCULANTE)))}",
        f"      Empréstimos CP: {_format_decimal(abs(g(G.EMPRESTIMOS_FINANCIAMENTOS_CP)))}",
        f"      Fornecedores: {_format_decimal(abs(g(G.FORNECEDORES)))}",
        f"      Obrigações Fiscais: {_format_decimal(abs(g(G.OBRIGACOES_FISCAIS)))}",
        f"      Obrigações Trabalhistas: {_format_decimal(abs(g(G.OBRIGACOES_TRABALHISTAS)))}",
        f"      Outras Obrigações CP: {_format_decimal(abs(g(G.OUTRAS_OBRIGACOES_CP)))}",
        f"    Passivo Não Circulante: {_format_decimal(abs(g(G.PASSIVO_NAO_CIRCULANTE)))}",
        f"      Empréstimos LP: {_format_decimal(abs(g(G.EMPRESTIMOS_LP)))}",
        f"      Parcelamentos Tributários: {_format_decimal(abs(g(G.PARCELAMENTOS_TRIBUTARIOS)))}",
        f"      Outros Débitos LP: {_format_decimal(abs(g(G.OUTROS_DEBITOS_LP)))}",
        f"  Patrimônio Líquido: {_format_decimal(g(G.PATRIMONIO_LIQUIDO))}",
        f"    Capital Social: {_format_decimal(abs(g(G.CAPITAL_SOCIAL)))}",
        f"    Lucros/Prejuízos Acumulados: {_format_decimal(g(G.LUCROS_PREJUIZOS))}",
        "",
        "DEMONSTRAÇÃO DO RESULTADO (Período)",
        f"  Receita Bruta: {_format_decimal(ind.receita_bruta)}",
        f"  (-) Deduções: {_format_decimal(abs(g(G.DEDUCOES_RECEITA)))}",
        f"  = Receita Líquida: {_format_decimal(ind.receita_liquida)}",
        f"  (-) Custos: {_format_decimal(abs(g(G.CUSTOS_SERVICOS)))}",
        f"  = Lucro Bruto: {_format_decimal(ind.lucro_bruto)}",
        f"  (-) Despesas Operacionais: {_format_decimal(abs(g(G.DESPESAS_OPERACIONAIS)))}",
        f"  (+) Receitas Financeiras: {_format_decimal(abs(g(G.RECEITAS_FINANCEIRAS)))}",
        f"  = EBIT (Lucro Operacional): {_format_decimal(ind.lucro_operacional)}",
        f"  (-) Despesas Financeiras: {_format_decimal(abs(g(G.DESPESAS_FINANCEIRAS)))}",
        f"  = Lucro Líquido: {_format_decimal(ind.lucro_liquido)}",
        "",
        "INDICADORES CALCULADOS",
        "-" * 40,
        "",
        "1. LIQUIDEZ",
        f"  Corrente: {_fmt(ind.liquidez_corrente)}",
        f"  Seca: {_fmt(ind.liquidez_seca)}",
        f"  Imediata: {_fmt(ind.liquidez_imediata)}",
        f"  Geral: {_fmt(ind.liquidez_geral)}",
        "",
        "2. ESTRUTURA DE CAPITAL",
        f"  Investimentos Totais: {_format_decimal(ind.investimentos_totais)}",
        f"  Passivo Oneroso: {_format_decimal(ind.passivo_oneroso)}",
        f"  Passivo Não Oneroso: {_format_decimal(ind.passivo_nao_oneroso)}",
        f"  Investimentos Líquidos: {_format_decimal(ind.investimentos_liquidos)}",
        f"  Capitais Próprios (PL): {_format_decimal(ind.capitais_proprios)}",
        f"  Capitais de Terceiros: {_format_decimal(ind.capitais_terceiros)}",
        f"  Participação Cap. Próprio: {_fmt(ind.participacao_capital_proprio)}",
        f"  Participação Cap. Terceiros: {_fmt(ind.participacao_capital_terceiros)}",
        f"  KE (Custo Cap. Próprio): {_fmt(ind.ke)}",
        f"  KI (Custo Cap. Terceiros): {_fmt(ind.ki)}",
        f"  WACC: {_fmt(ind.wacc)}",
        "",
        "3. CAPITAL DE GIRO",
        f"  Capital Circulante Líquido: {_format_decimal(ind.capital_circulante_liquido)}",
        f"  Ativo Cíclico: {_format_decimal(ind.ativo_ciclico)}",
        f"  Passivo Cíclico: {_format_decimal(ind.passivo_ciclico)}",
        f"  Necessidade Capital de Giro: {_format_decimal(ind.necessidade_capital_giro)}",
        "",
        "4. PRAZOS E CICLO FINANCEIRO",
        f"  PMP (dias): {_fmt(ind.pmp)}",
        f"  PMR (dias): {_fmt(ind.pmr)}",
        f"  PMRE (dias): {_fmt(ind.pmre)}",
        f"  Ciclo Financeiro (dias): {_fmt(ind.ciclo_financeiro)}",
        "",
        "5. RENTABILIDADE",
        f"  Margem Bruta: {_fmt(ind.margem_bruta)}",
        f"  Margem de Contribuição: {_fmt(ind.margem_contribuicao)}",
        f"  Margem Operacional: {_fmt(ind.margem_operacional)}",
        f"  Margem Líquida: {_fmt(ind.margem_liquida)}",
        f"  NOPAT: {_format_decimal(ind.nopat)}",
        f"  ROI: {_fmt(ind.roi)}",
        f"  ROA: {_fmt(ind.roa)}",
        f"  ROE: {_fmt(ind.roe)}",
        f"  GAF: {_fmt(ind.gaf)}",
        f"  EBITDA: {_format_decimal(ind.ebitda)}",
        f"  Margem EBITDA: {_fmt(ind.margem_ebitda)}",
    ]

    if comp:
        lines.extend([
            "",
            f"COMPARATIVO: {comp.periodo_anterior} → {comp.periodo_atual}",
        ])
        for grupo in [
            comp.variacoes_liquidez,
            comp.variacoes_endividamento,
            comp.variacoes_rentabilidade,
            comp.variacoes_capital_giro,
        ]:
            for v in grupo:
                delta = f"({v.variacao_percentual:+}%)" if v.variacao_percentual else ""
                lines.append(
                    f"  {v.nome}: {v.valor_anterior} → {v.valor_atual} {delta} [{v.tendencia}]"
                )

    return "\n".join(lines)
