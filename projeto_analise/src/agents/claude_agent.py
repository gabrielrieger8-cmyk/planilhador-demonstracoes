"""Agente Claude para geração de relatórios narrativos financeiros."""

from __future__ import annotations

import time

from src.agents.gemini_agent import (
    SYSTEM_PROMPT,
    NarrativeResult,
    _build_user_prompt,
)
from src.analysis.account_classifier import SaldosAgrupados
from src.analysis.comparative import AnaliseComparativa
from src.analysis.indicators import IndicadoresFinanceiros
from src.utils.config import ANTHROPIC_API_KEY, config, logger


class ClaudeNarrativeAgent:
    """Agente que usa Claude (Anthropic) para gerar relatórios narrativos."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or ANTHROPIC_API_KEY
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
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
            model: ID do modelo Claude (usa config padrão se None).
        """
        if not self._api_key:
            return NarrativeResult(
                texto="", success=False,
                error="ANTHROPIC_API_KEY não configurada.",
            )

        model_to_use = model or config.claude_model
        start = time.time()
        try:
            client = self._get_client()
            user_prompt = _build_user_prompt(indicadores, saldos, comparativo)

            response = client.messages.create(
                model=model_to_use,
                max_tokens=config.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            texto = response.content[0].text if response.content else ""
            tokens_in = getattr(response.usage, "input_tokens", 0)
            tokens_out = getattr(response.usage, "output_tokens", 0)

            # Custo varia por modelo
            if "opus" in model_to_use:
                cost = (tokens_in / 1_000_000) * 15.00 + (tokens_out / 1_000_000) * 75.00
            else:
                cost = (tokens_in / 1_000_000) * 3.00 + (tokens_out / 1_000_000) * 15.00

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
                error=f"Erro Claude: {exc}",
                processing_time=time.time() - start,
            )
