"""Agente Gemini Flash para análise de PDFs financeiros.

Envia o PDF diretamente ao Gemini (entrada nativa de PDF),
processando em lotes de páginas para garantir extração completa.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from src.utils.config import GEMINI_API_KEY, config, logger

# Quantas páginas enviar por chamada à API
PAGES_PER_BATCH = 5

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
FINANCIAL_PROMPT = """\
TAREFA: Transcrever TODAS as linhas de tabela financeira presentes neste PDF.

INSTRUÇÕES CRÍTICAS — LEIA COM ATENÇÃO:
- Você DEVE extrair ABSOLUTAMENTE TODAS as linhas visíveis. Sem exceção.
- NÃO resuma. NÃO agrupe. NÃO simplifique. NÃO pule nenhuma conta.
- Cada linha do documento original DEVE aparecer na sua saída.
- Se houver 50 linhas visíveis, sua saída DEVE ter 50 linhas.
- Contas de clientes, fornecedores, bancos — TODAS devem aparecer individualmente.
- Subcontas (1.1.10.200.1, etc.) são TÃO importantes quanto as contas principais.
- Valores numéricos EXATOS: não arredonde, não omita casas decimais.
- Mantenha D (Débito) e C (Crédito) junto aos valores.
- Formato brasileiro: ponto para milhar, vírgula para decimal.
- Se uma linha estiver parcialmente cortada na borda, extraia o que for legível.

COLUNA TIPO (OBRIGATÓRIA):
- Adicione uma coluna "Tipo" APÓS a coluna "Descrição da conta".
- Valor "A" para contas AGRUPADORAS (totalizadoras): são as que aparecem em negrito,
  com indentação menor, com cor diferente, ou que claramente agrupam outras contas abaixo.
- Valor "D" para contas de DETALHE: são as contas individuais, folhas da árvore contábil.
- Na dúvida, marque como "D".

FORMATO: Tabela Markdown com colunas: Código | Classificação | Descrição da conta | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual
Apenas dados — sem texto explicativo.

LEMBRETE: Se você omitir QUALQUER linha, o resultado será considerado incorreto.
A completude é MAIS importante que a formatação.
"""

GENERAL_PROMPT = """\
Extraia ABSOLUTAMENTE TODO o conteúdo visível neste PDF.
Não omita nada. Não resuma. Não simplifique.
Formato: Markdown. Tabelas em formato Markdown.
"""


@dataclass
class GeminiResult:
    """Resultado do processamento pelo agente Gemini."""

    text: str
    pages_processed: int = 0
    metadata: dict = field(default_factory=dict)
    processing_time: float = 0.0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None


def _call_with_retry(client, pdf_part, prompt: str, max_retries: int = 5):
    """Chama Gemini com retry automático e exponential backoff para rate limits.

    Args:
        client: Cliente Gemini.
        pdf_part: Part com o PDF.
        prompt: Prompt a enviar.
        max_retries: Número máximo de tentativas.

    Returns:
        Response do Gemini.

    Raises:
        Exception: Se todas as tentativas falharem.
    """
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=config.gemini_model,
                contents=[pdf_part, prompt],
                config={
                    "temperature": config.gemini_temperature,
                    "max_output_tokens": config.gemini_max_tokens,
                },
            )
            return response
        except Exception as exc:
            error_str = str(exc).lower()
            is_rate_limit = (
                "429" in error_str
                or "rate" in error_str
                or "quota" in error_str
                or "resource_exhausted" in error_str
            )

            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) * 2  # 2s, 4s, 8s, 16s, 32s
                logger.warning(
                    "Rate limit (tentativa %d/%d). Aguardando %ds...",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                raise


class GeminiAgent:
    """Agente que usa Google Gemini para análise de PDFs.

    Envia o PDF nativamente ao Gemini, processando em lotes de
    páginas para balancear velocidade e completude.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or GEMINI_API_KEY
        self._client = None
        if not self._api_key:
            logger.warning(
                "GEMINI_API_KEY não configurada. "
                "Defina no .env ou passe como parâmetro."
            )
        logger.info("GeminiAgent inicializado (modelo: %s).", config.gemini_model)

    def _get_client(self):
        """Inicializa o client Gemini sob demanda."""
        if self._client is None:
            try:
                from google import genai

                self._client = genai.Client(api_key=self._api_key)
                logger.info("Client Gemini criado: %s", config.gemini_model)
            except ImportError as exc:
                raise ImportError(
                    "google-genai não está instalado. "
                    "Execute: pip install google-genai"
                ) from exc
        return self._client

    def process(
        self,
        file_path: str | Path,
        prompt: str | None = None,
        financial: bool = True,
    ) -> GeminiResult:
        """Processa um PDF enviando-o nativamente ao Gemini.

        Para PDFs pequenos (até PAGES_PER_BATCH páginas), envia tudo
        em uma única chamada. Para PDFs maiores, divide em lotes de
        páginas e faz uma chamada por lote.

        Args:
            file_path: Caminho para o arquivo PDF.
            prompt: Prompt customizado.
            financial: Se True, usa prompt financeiro especializado.

        Returns:
            GeminiResult com texto completo extraído.
        """
        path = Path(file_path)
        if not path.exists():
            return GeminiResult(
                text="", success=False,
                error=f"Arquivo não encontrado: {path}",
            )

        if not self._api_key:
            return GeminiResult(
                text="", success=False,
                error="GEMINI_API_KEY não configurada.",
            )

        logger.info("Gemini processando: %s", path.name)
        start_time = time.time()

        try:
            client = self._get_client()
            from google.genai import types

            # Conta páginas do PDF
            doc = fitz.open(str(path))
            total_pages = len(doc)
            doc.close()

            base_prompt = prompt or (
                FINANCIAL_PROMPT if financial else GENERAL_PROMPT
            )

            # Decide se envia tudo de uma vez ou em lotes
            if total_pages <= PAGES_PER_BATCH:
                batches = [(1, total_pages)]
            else:
                batches = []
                for start in range(0, total_pages, PAGES_PER_BATCH):
                    end = min(start + PAGES_PER_BATCH, total_pages)
                    batches.append((start + 1, end))

            total_batches = len(batches)
            logger.info(
                "PDF: %d páginas → %d chamada(s) à API",
                total_pages, total_batches,
            )

            all_results: list[str] = []
            total_input_tokens = 0
            total_output_tokens = 0
            is_first = True

            for batch_idx, (page_start, page_end) in enumerate(batches):
                sys.stdout.write(
                    f"\r  Gemini: páginas {page_start}-{page_end}/{total_pages} "
                    f"(lote {batch_idx + 1}/{total_batches})..."
                )
                sys.stdout.flush()

                # Extrai lote de páginas como sub-PDF
                pdf_bytes = _extract_page_range(str(path), page_start, page_end)

                pdf_part = types.Part.from_bytes(
                    data=pdf_bytes, mime_type="application/pdf"
                )

                batch_prompt = base_prompt
                if is_first:
                    batch_prompt += "\nInclua o cabeçalho da tabela (nomes das colunas) como primeira linha."
                    is_first = False
                else:
                    batch_prompt += "\nNÃO inclua cabeçalho — apenas as linhas de dados."

                response = _call_with_retry(
                    client, pdf_part, batch_prompt,
                    max_retries=5,
                )

                batch_text = response.text if response.text else ""
                all_results.append(batch_text)

                # Tokens
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    total_input_tokens += getattr(meta, "prompt_token_count", 0) or 0
                    total_output_tokens += getattr(meta, "candidates_token_count", 0) or 0

            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()

            combined_text = "\n".join(all_results)
            processing_time = time.time() - start_time
            estimated_cost = _estimate_cost(total_input_tokens, total_output_tokens)

            logger.info(
                "Gemini concluiu em %.2fs — %d páginas, %d lote(s) — custo: $%.4f",
                processing_time, total_pages, total_batches, estimated_cost,
            )

            return GeminiResult(
                text=combined_text,
                pages_processed=total_pages,
                metadata={
                    "source": str(path),
                    "agent": "gemini",
                    "model": config.gemini_model,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                    "total_batches": total_batches,
                    "pages_per_batch": PAGES_PER_BATCH,
                    "financial_mode": financial,
                },
                processing_time=processing_time,
                estimated_cost=estimated_cost,
            )

        except Exception as exc:
            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()
            processing_time = time.time() - start_time
            error_msg = f"Erro no processamento Gemini: {exc}"
            logger.error(error_msg)
            return GeminiResult(
                text="", processing_time=processing_time,
                success=False, error=error_msg,
            )


SYNTHETIC_PROMPT = """\
Dado este plano de contas (Classificação | Descrição), identifique quais
contas devem aparecer em uma versão SINTÉTICA (resumida) do balancete.

REGRAS:
- Mantenha contas AGRUPADORAS (que representam categorias/grupos)
- Remova contas de DETALHE INDIVIDUAL (nomes de bancos específicos,
  clientes específicos, fornecedores específicos, despesas individuais)
- Use seu julgamento: o nível certo é aquele que mostra a estrutura
  sem entrar em detalhes operacionais. Ex: manter "BANCOS CONTA
  MOVIMENTO" mas remover cada banco individual

INDICADORES VISUAIS:
- Contas marcadas com ** (negrito) no plano são forte indicador de conta
  agrupadora. Geralmente devem ser mantidas no sintético.
- Nem sempre o negrito é o único sinal — o documento original pode usar
  cores ou outros destaques. Use a hierarquia (nível da classificação)
  e o nome da conta como critérios complementares.

DESPESAS OPERACIONAIS (grupo 3.2):
- As despesas operacionais/administrativas devem ter mais detalhamento
  do que outros grupos. Mantenha subcategorias como "Despesas c/ Pessoal",
  "Aluguéis", "Impostos e Taxas", "Despesas Gerais", "Despesas Financeiras",
  etc. Mas NÃO desça ao nível de cada despesa individual (cada salário,
  cada aluguel específico, etc.).

CONSISTÊNCIA:
- REGRA CRÍTICA: Se você decidir remover contas de detalhe em um
  determinado nível dentro de um grupo pai, REMOVA TODAS as contas
  nesse mesmo nível do mesmo grupo. Exemplo: se dentro de "EMPRÉSTIMOS
  E FINANCIAMENTOS" você decide que empréstimos individuais são detalhe
  demais, remova TODOS (Bradesco 134903, Itaú 1234234, etc). Nunca
  mantenha uns e remova outros no mesmo nível hierárquico do mesmo pai.
- Na dúvida, MANTENHA a conta (melhor ter um pouco mais de detalhe
  do que perder informação relevante)

OBRIGATÓRIO: Você DEVE analisar e retornar contas de TODOS os grupos:
- Grupo 1: ATIVO (e seus subgrupos)
- Grupo 2: PASSIVO (incluindo Patrimônio Líquido 2.3.x)
- Grupo 3: CUSTOS E DESPESAS (e seus subgrupos, com detalhe em despesas)
- Grupo 4: RECEITAS (e seus subgrupos)
Se um grupo existe no plano de contas, ele DEVE ter contas no resultado.

FORMATO DE RESPOSTA:
Retorne APENAS as classificações das contas a manter, uma por linha.
Nada mais.

PLANO DE CONTAS:
{chart_text}
"""


def _extract_chart_of_accounts(csv_text: str) -> str:
    """Extrai apenas Classificação e Descrição do CSV para enviar ao Gemini.

    Reduz o tamanho do input drasticamente, enviando só o que é
    necessário para a decisão de agrupamento.
    """
    lines = []
    for row in csv_text.strip().split("\n"):
        parts = row.split(";")
        if len(parts) >= 3:
            classificacao = parts[1].strip()
            descricao = parts[2].strip()
            if classificacao:
                lines.append(f"{classificacao} | {descricao}")
    return "\n".join(lines)


def classify_synthetic(csv_text: str, api_key: str | None = None) -> set[str]:
    """Envia o plano de contas ao Gemini e pede que identifique as
    classificações que devem aparecer no balancete sintético.

    Args:
        csv_text: Conteúdo completo do CSV.
        api_key: Chave da API Gemini (usa config se None).

    Returns:
        Set de classificações a manter (ex: {"1", "1.1", "1.1.1"}).
    """
    key = api_key or GEMINI_API_KEY
    if not key:
        logger.warning("GEMINI_API_KEY não configurada para classificação sintética.")
        return set()

    try:
        from google import genai

        client = genai.Client(api_key=key)
        chart_text = _extract_chart_of_accounts(csv_text)
        prompt = SYNTHETIC_PROMPT.format(chart_text=chart_text)

        response = client.models.generate_content(
            model=config.gemini_model,
            contents=[prompt],
            config={
                "temperature": 0.1,
                "max_output_tokens": 8192,
            },
        )

        text = response.text or ""
        keep = set()
        for line in text.strip().split("\n"):
            classif = line.strip()
            if classif:
                keep.add(classif)

        # Garante cobertura de todos os subgrupos presentes no CSV
        all_classificacoes = set()
        for csv_line in csv_text.strip().split("\n"):
            parts = csv_line.split(";")
            if len(parts) >= 3:
                c = parts[1].strip()
                # Ignora header e valores não-numéricos
                if c and c[0].isdigit():
                    all_classificacoes.add(c)

        # Identifica subgrupos de 2° nível presentes (ex: 1.1, 1.2, 2.1, 2.3, 3.1, 4.1)
        subgrupos_presentes = set()
        for c in all_classificacoes:
            parts = c.split(".")
            if len(parts) >= 2:
                subgrupos_presentes.add(f"{parts[0]}.{parts[1]}")
            else:
                subgrupos_presentes.add(c)

        # Verifica quais subgrupos estão cobertos no resultado
        subgrupos_cobertos = set()
        for c in keep:
            parts = c.split(".")
            if len(parts) >= 2:
                subgrupos_cobertos.add(f"{parts[0]}.{parts[1]}")
            else:
                subgrupos_cobertos.add(c)

        # Para subgrupos faltantes, adiciona contas automaticamente
        # Grupos 3 e 4 (DRE): nivel <= 4 para detalhar despesas/receitas
        # Grupos 1 e 2 (BP): nivel <= 3
        faltantes = subgrupos_presentes - subgrupos_cobertos
        if faltantes:
            logger.warning(
                "Subgrupos faltantes na classificação: %s. Adicionando automaticamente.",
                faltantes,
            )
            for c in all_classificacoes:
                c_parts = c.split(".")
                if len(c_parts) >= 2:
                    subgrupo = f"{c_parts[0]}.{c_parts[1]}"
                else:
                    subgrupo = c
                if subgrupo in faltantes:
                    nivel = c.count(".") + 1
                    grupo = int(c[0]) if c[0].isdigit() else 0
                    max_nivel = 4 if grupo in (3, 4) else 3
                    if nivel <= max_nivel:
                        keep.add(c)

        logger.info("Classificação sintética: %d contas selecionadas.", len(keep))
        return keep

    except Exception as exc:
        logger.error("Erro na classificação sintética: %s", exc)
        return set()


def _extract_page_range(file_path: str, page_start: int, page_end: int) -> bytes:
    """Extrai um intervalo de páginas do PDF como bytes.

    Args:
        file_path: Caminho do PDF original.
        page_start: Primeira página (1-indexed).
        page_end: Última página (1-indexed, inclusive).

    Returns:
        Bytes do sub-PDF contendo apenas as páginas do intervalo.
    """
    src = fitz.open(file_path)
    total = len(src)

    # Se é o PDF inteiro, retorna os bytes originais
    if page_start == 1 and page_end >= total:
        pdf_bytes = src.tobytes()
        src.close()
        return pdf_bytes

    # Cria sub-PDF com as páginas do intervalo
    dst = fitz.open()
    dst.insert_pdf(src, from_page=page_start - 1, to_page=page_end - 1)
    pdf_bytes = dst.tobytes()
    dst.close()
    src.close()
    return pdf_bytes


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estima o custo das chamadas ao Gemini Flash."""
    input_cost = (input_tokens / 1_000_000) * 0.15
    output_cost = (output_tokens / 1_000_000) * 0.60
    return round(input_cost + output_cost, 6)
