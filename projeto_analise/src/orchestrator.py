"""Orquestrador principal da análise econômico-financeira.

Coordena: parsing → classificação IA → agrupamento → indicadores → comparativo → narrativa.
Suporta execução passo-a-passo (para uso interativo no dashboard) ou completa.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.agents.claude_agent import ClaudeNarrativeAgent
from src.agents.gemini_agent import GeminiNarrativeAgent, NarrativeResult
from src.analysis.account_classifier import (
    SaldosAgrupados,
    agrupar_saldos,
)
from src.analysis.comparative import AnaliseComparativa, comparar_colunas
from src.analysis.indicators import (
    IndicadoresFinanceiros,
    ParamsCAPM,
    calcular_indicadores_completos,
)
from src.parsers.csv_parser import Balancete, load_balancete
from src.utils.config import OUTPUT_DIR, logger


class OutputFormat(str, Enum):
    MARKDOWN = "markdown"
    PDF = "pdf"
    ALL = "all"


@dataclass
class AnalysisResult:
    """Resultado completo da análise financeira."""

    file_path: str = ""
    balancete: Balancete | None = None
    classificacao_ia: dict = field(default_factory=dict)
    saldos: SaldosAgrupados | None = None
    indicadores: IndicadoresFinanceiros | None = None
    comparativo: AnaliseComparativa | None = None
    narrativa: str = ""
    output_files: list[str] = field(default_factory=list)
    processing_time: float = 0.0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None


class Orchestrator:
    """Orquestrador da análise financeira.

    Métodos públicos para cada etapa permitem uso interativo pelo dashboard.
    O método ``analyze()`` executa o pipeline completo de uma vez.
    """

    def __init__(self) -> None:
        self._gemini_agent: GeminiNarrativeAgent | None = None
        self._claude_agent: ClaudeNarrativeAgent | None = None
        logger.info("Orquestrador inicializado.")

    # -----------------------------------------------------------------
    # Etapas individuais (para uso pelo dashboard)
    # -----------------------------------------------------------------

    @staticmethod
    def parse(file_path: str | Path) -> Balancete:
        """Carrega e parseia o CSV de balancete."""
        return load_balancete(Path(file_path))

    @staticmethod
    def classify(csv_text: str) -> dict:
        """Identifica contas-chave via IA (Claude Sonnet).

        Args:
            csv_text: Texto completo do CSV.

        Returns:
            Mapeamento {"bp": {...}, "dre": {...}}.
        """
        from src.agents.classifier_agent import classify_accounts

        return classify_accounts(csv_text)

    @staticmethod
    def group(
        balancete: Balancete,
        mapeamento_ia: dict | None = None,
    ) -> SaldosAgrupados:
        """Agrupa saldos por grupo contábil usando mapeamento da IA."""
        return agrupar_saldos(balancete, mapeamento_ia)

    @staticmethod
    def calculate(
        saldos: SaldosAgrupados,
        params_capm: ParamsCAPM | None = None,
        dias_periodo: int = 30,
        mapeamento_ia: dict | None = None,
    ) -> IndicadoresFinanceiros:
        """Calcula todos os indicadores financeiros."""
        return calcular_indicadores_completos(
            saldos, params_capm, dias_periodo, mapeamento_ia,
        )

    @staticmethod
    def compare(saldos: SaldosAgrupados) -> AnaliseComparativa:
        """Compara Saldo Anterior vs Saldo Atual dentro do mesmo balancete."""
        return comparar_colunas(saldos)

    def generate_narrative(
        self,
        indicadores: IndicadoresFinanceiros,
        saldos: SaldosAgrupados,
        comparativo: AnaliseComparativa | None = None,
        provider: str = "gemini",
        model: str | None = None,
    ) -> NarrativeResult:
        """Gera narrativa usando o modelo especificado.

        Args:
            indicadores: Indicadores calculados.
            saldos: Saldos agrupados.
            comparativo: Comparativo entre períodos (opcional).
            provider: ``"gemini"`` ou ``"claude"``.
            model: ID do modelo (ex: ``"claude-opus-4-6"``). Usa config padrão se None.
        """
        if provider == "claude":
            agent = self._get_claude_agent()
        else:
            agent = self._get_gemini_agent()
        return agent.generate_narrative(
            indicadores, saldos, comparativo, model=model,
        )

    # -----------------------------------------------------------------
    # Execução completa
    # -----------------------------------------------------------------

    def analyze(
        self,
        file_path: str | Path,
        classificacao_ia: dict | None = None,
        params_capm: ParamsCAPM | None = None,
        dias_periodo: int = 30,
        narrative_provider: str = "gemini",
        narrative_model: str | None = None,
        skip_narrative: bool = False,
        output_format: OutputFormat = OutputFormat.ALL,
        output_dir: str | Path | None = None,
    ) -> AnalysisResult:
        """Executa a análise financeira completa.

        Args:
            file_path: Caminho do CSV de balancete.
            classificacao_ia: Classificação pré-computada (ou None para classificar via IA).
            params_capm: Parâmetros CAPM para KE/KI/WACC.
            narrative_provider: ``"gemini"`` ou ``"claude"``.
            narrative_model: ID do modelo de narrativa.
            skip_narrative: Se True, pula geração de narrativa.
            output_format: Formato(s) de saída.
            output_dir: Diretório de saída.

        Returns:
            AnalysisResult com todos os detalhes.
        """
        path = Path(file_path)
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        start = time.time()

        logger.info("=" * 60)
        logger.info("Iniciando análise: %s", path.name)
        logger.info("=" * 60)

        try:
            # [1/7] Validação
            sys.stdout.write("  [1/7] Validando arquivo...\n")
            if not path.exists():
                return AnalysisResult(
                    file_path=str(path), success=False,
                    error=f"Arquivo não encontrado: {path}",
                )

            # [2/7] Parsing
            sys.stdout.write("  [2/7] Carregando dados do balancete...\n")
            balancete = self.parse(path)

            # [3/7] Classificação IA
            if classificacao_ia is None:
                sys.stdout.write("  [3/7] Classificando contas via IA...\n")
                csv_text = path.read_text(encoding="utf-8-sig")
                classificacao_ia = self.classify(csv_text)
                if not classificacao_ia:
                    return AnalysisResult(
                        file_path=str(path), success=False,
                        error="Falha na classificação IA. Verifique a ANTHROPIC_API_KEY no .env.",
                        processing_time=time.time() - start,
                    )
            else:
                sys.stdout.write("  [3/7] Usando classificação fornecida...\n")

            # [4/7] Agrupamento
            sys.stdout.write("  [4/7] Agrupando saldos por grupo contábil...\n")
            saldos = self.group(balancete, classificacao_ia)

            # [5/7] Indicadores
            sys.stdout.write("  [5/7] Calculando indicadores financeiros...\n")
            indicadores = self.calculate(saldos, params_capm, dias_periodo, classificacao_ia)

            # [6/7] Comparativo (Saldo Anterior vs Saldo Atual)
            sys.stdout.write("  [6/7] Realizando análise comparativa...\n")
            comparativo = self.compare(saldos)

            # [7/7] Narrativa IA
            narrativa = ""
            narrative_cost = 0.0

            if not skip_narrative:
                sys.stdout.write(
                    f"  [7/7] Gerando narrativa com {narrative_provider}...\n"
                )
                narrative_result = self.generate_narrative(
                    indicadores, saldos, comparativo,
                    provider=narrative_provider, model=narrative_model,
                )
                if not narrative_result.success:
                    logger.warning("Narrativa IA falhou: %s", narrative_result.error)
                    narrativa = (
                        f"*Erro na geração de narrativa: {narrative_result.error}*"
                    )
                else:
                    narrativa = narrative_result.texto
                narrative_cost = narrative_result.estimated_cost
            else:
                sys.stdout.write("  [7/7] Narrativa não solicitada.\n")

            # Exportação delegada ao dashboard (app.py)
            processing_time = time.time() - start

            logger.info("-" * 60)
            logger.info("Análise concluída em %.2fs", processing_time)
            logger.info("-" * 60)

            return AnalysisResult(
                file_path=str(path),
                balancete=balancete,
                classificacao_ia=classificacao_ia,
                saldos=saldos,
                indicadores=indicadores,
                comparativo=comparativo,
                narrativa=narrativa,
                processing_time=processing_time,
                estimated_cost=narrative_cost,
            )

        except Exception as exc:
            processing_time = time.time() - start
            error_msg = f"Erro na análise: {exc}"
            logger.error(error_msg, exc_info=True)
            return AnalysisResult(
                file_path=str(path), success=False,
                error=error_msg, processing_time=processing_time,
            )

    # -----------------------------------------------------------------
    # Privados
    # -----------------------------------------------------------------

    def _get_gemini_agent(self) -> GeminiNarrativeAgent:
        if self._gemini_agent is None:
            self._gemini_agent = GeminiNarrativeAgent()
        return self._gemini_agent

    def _get_claude_agent(self) -> ClaudeNarrativeAgent:
        if self._claude_agent is None:
            self._claude_agent = ClaudeNarrativeAgent()
        return self._claude_agent
