"""Agente Gemini Flash para análise de PDFs financeiros.

Envia o PDF diretamente ao Gemini (entrada nativa de PDF),
processando em lotes de páginas para garantir extração completa.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from controladoria_core.exporters.reference_extractor import load_reference_for_prompt
from controladoria_core.utils.config import GEMINI_API_KEY, MODELOS_DISPONIVEIS, config, logger

# Quantas páginas enviar por chamada à API
# Valor 1 = uma chamada por página, maximiza precisão e evita omissões
PAGES_PER_BATCH = 1

# OCR como guia: extrai texto do PDF para orientar o Gemini
OCR_TEXT_THRESHOLD = 50          # chars/página mínimo para considerar get_text() suficiente
MAX_OCR_CHARS_PER_BATCH = 15000  # cap de segurança para texto OCR no prompt

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
FINANCIAL_PROMPT = """\
TAREFA: Transcrever TODAS as linhas de tabela financeira (balancete) presentes neste PDF.

REGRA #1 — ZERO OMISSÕES:
- Extraia ABSOLUTAMENTE TODAS as linhas visíveis. Sem exceção.
- NÃO resuma. NÃO agrupe. NÃO simplifique. NÃO pule nenhuma conta.
- Cada linha do documento original DEVE aparecer na sua saída.
- Se houver 80 linhas visíveis, sua saída DEVE ter 80 linhas.
- Contas de clientes, fornecedores, bancos — TODAS individualmente.
- Subcontas (1.1.10.200.1, etc.) são TÃO importantes quanto as contas principais.
- NÃO pare antes de terminar todas as linhas da página.

COLUNAS DO PDF ORIGINAL E COMO MAPEAR:
O PDF pode ter colunas como: CONTA, CLASSIFICAÇÃO, TIPO, NOME DA CONTA, SALDO ANTERIOR, DÉBITO, CRÉDITO, SALDO ATUAL.
- A coluna "TIPO" do PDF original (que contém letras T, C, S etc.) deve ser DESCARTADA.
  NÃO copie essa coluna. Ela é irrelevante.
- Copie todas as OUTRAS colunas normalmente.

COLUNA TIPO (GERADA POR VOCÊ — NÃO É A DO PDF):
- CRIE uma nova coluna "Tipo" com SUA classificação:
  - "A" = contas AGRUPADORAS (totalizadoras, que somam outras contas abaixo).
  - "D" = contas de DETALHE (individuais, folhas da árvore contábil).

COMO IDENTIFICAR AGRUPADORAS (Tipo=A) — PRESTE MUITA ATENÇÃO:
- Contas em NEGRITO ou destaque visual quase sempre são agrupadoras.
- Contas cujo Saldo Atual é a SOMA dos saldos das contas logo abaixo são agrupadoras.
- Contas com Débito=0 e Crédito=0 (sem movimento próprio) geralmente são agrupadoras.
- Nomes genéricos/categóricos são agrupadoras: "IMPOSTOS, TAXAS E CONTRIBUIÇÕES",
  "DESPESAS GERAIS ADMINISTRATIVAS", "DESPESAS COM PESSOAL", "ATIVO CIRCULANTE",
  "PASSIVO CIRCULANTE", "RECEITAS OPERACIONAIS", etc.
- Nomes específicos são detalhe (D): "IOF", "IPTU", "IPVA", "Banco do Brasil",
  "ASSESSORIA ADVOCATÍCIA", "COMBUSTÍVEL P/ VEÍCULOS", etc.
- Na dúvida entre A e D, olhe se a conta tem filhas abaixo (contas mais específicas
  que detalham essa conta). Se tiver filhas, é A. Se não, é D.
- ERRAR para A é MENOS grave que errar para D. Na dúvida, marque como "A".

VALORES NUMÉRICOS:
- Valores EXATOS: não arredonde, não omita casas decimais.
- Mantenha D (Débito) e C (Crédito) junto aos valores numéricos.
- Formato brasileiro: ponto para milhar, vírgula para decimal.

FORMATO DE SAÍDA — Tabela Markdown com EXATAMENTE estas 8 colunas:
Código | Classificação | Descrição da conta | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual

Onde:
- Código = número da conta (ex: 1, 5, 685, 615)
- Classificação = código hierárquico (ex: 01, 01.1, 01.1.1.02.01)
- Descrição da conta = nome da conta (ex: ATIVO, Caixa, Banco do Brasil S/A)
- Tipo = A ou D (gerado por você, NÃO copiado do PDF)
- Saldo Anterior, Débito, Crédito, Saldo Atual = valores numéricos com D ou C no final

Apenas dados — sem texto explicativo, sem comentários.

LEMBRETE FINAL: Se você omitir QUALQUER linha, o resultado é INCORRETO.
Completude é MAIS importante que formatação. NÃO TRUNCAR.
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
        reference_name: str | None = None,
    ) -> GeminiResult:
        """Processa um PDF enviando-o nativamente ao Gemini.

        Para PDFs pequenos (até PAGES_PER_BATCH páginas), envia tudo
        em uma única chamada. Para PDFs maiores, divide em lotes de
        páginas e faz uma chamada por lote.

        Args:
            file_path: Caminho para o arquivo PDF.
            prompt: Prompt customizado.
            financial: Se True, usa prompt financeiro especializado.
            reference_name: Nome da referência a carregar (None = mais recente).

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

            # RAG: injeta referência de padrão contábil validado (se disponível)
            if financial and prompt is None:
                ref_text = load_reference_for_prompt(reference_name=reference_name)
                if ref_text:
                    base_prompt += (
                        "\n\nREFERÊNCIA DE XLSX VALIDADO PELO USUÁRIO:\n"
                        "O texto abaixo mostra o padrão de um balancete JÁ VALIDADO pelo controller.\n"
                        "Use como guia para:\n"
                        "1. Classificar corretamente Tipo=A (agrupadora) vs Tipo=D (detalhe)\n"
                        "2. Entender a hierarquia de contas (quais são filhas de quais)\n"
                        "3. Manter a mesma estrutura de classificação\n\n"
                        f"{ref_text}\n\n"
                        "FIM DA REFERÊNCIA. Agora processe o PDF conforme as instruções acima.\n"
                    )
                    logger.info(
                        "RAG: referência injetada no prompt (%d chars)",
                        len(ref_text),
                    )

            # Decide se envia tudo de uma vez ou em lotes
            if total_pages <= PAGES_PER_BATCH:
                batches = [(1, total_pages)]
            else:
                batches = []
                for start in range(0, total_pages, PAGES_PER_BATCH):
                    end = min(start + PAGES_PER_BATCH, total_pages)
                    batches.append((start + 1, end))

            # OCR guia: extrai texto e conta contas localmente (sem API)
            total_batches = len(batches)
            ocr_texts: dict[str, str] = {}
            expected_accounts: dict[str, int] = {}

            for bi, (ps, pe) in enumerate(batches):
                bk = f"{ps}-{pe}"
                sys.stdout.write(
                    f"\r  OCR: páginas {ps}-{pe}/{total_pages} "
                    f"(lote {bi + 1}/{total_batches})..."
                )
                sys.stdout.flush()
                ocr_text, method = _extract_ocr_text_for_batch(str(path), ps, pe)
                ocr_texts[bk] = ocr_text
                count = _count_accounts_from_text(ocr_text)
                expected_accounts[bk] = count
                logger.info(
                    "OCR lote %d/%d (págs %d-%d): %d contas, método=%s, %d chars",
                    bi + 1, total_batches, ps, pe, count, method, len(ocr_text),
                )

            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()

            # Fallback: se OCR não produziu texto nenhum, usa contagem via Gemini
            total_ocr_chars = sum(len(t) for t in ocr_texts.values())
            if total_ocr_chars == 0:
                logger.warning(
                    "OCR não produziu texto. Fallback para contagem via Gemini."
                )
                expected_accounts = _gemini_count_accounts(
                    client, types, str(path), total_pages, batches,
                )

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

                # Injeta contagem esperada de contas no prompt
                batch_key = f"{page_start}-{page_end}"
                batch_accounts = expected_accounts.get(batch_key, 0)
                if batch_accounts > 0:
                    batch_prompt += (
                        f"\n\nCONTAGEM PRÉVIA: Estas páginas contêm EXATAMENTE {batch_accounts} contas/linhas. "
                        f"Sua saída DEVE ter exatamente {batch_accounts} linhas de dados. "
                        f"Se você retornar menos, está omitindo contas. "
                        f"Se retornar mais, está duplicando. Confira antes de enviar."
                    )

                # Injeta texto OCR como guia/mapa para o Gemini
                batch_ocr = ocr_texts.get(batch_key, "")
                if batch_ocr.strip():
                    ocr_inject = batch_ocr
                    if len(ocr_inject) > MAX_OCR_CHARS_PER_BATCH:
                        ocr_inject = ocr_inject[:MAX_OCR_CHARS_PER_BATCH] + "\n[... texto OCR truncado ...]"
                    batch_prompt += (
                        "\n\nTEXTO OCR DE REFERÊNCIA (pode conter erros — use como guia):\n"
                        "O texto abaixo foi extraído via OCR destas páginas. Serve como MAPA de "
                        "todas as informações presentes. Use para garantir que NENHUMA conta seja "
                        "omitida. Corrija erros de OCR usando o que você vê na imagem do PDF.\n\n"
                        f"```\n{ocr_inject}\n```"
                    )

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

                # Tokens
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    meta = response.usage_metadata
                    total_input_tokens += getattr(meta, "prompt_token_count", 0) or 0
                    total_output_tokens += getattr(meta, "candidates_token_count", 0) or 0

                # Anti-truncamento: detecta se a resposta foi cortada e continua
                finish_reason = None
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = str(response.candidates[0].finish_reason)

                max_continuations = 3
                continuation = 0
                while finish_reason and "MAX_TOKENS" in finish_reason and continuation < max_continuations:
                    continuation += 1
                    logger.warning(
                        "Resposta truncada (lote %d, continuação %d/%d). Pedindo continuação...",
                        batch_idx + 1, continuation, max_continuations,
                    )
                    cont_prompt = (
                        "A resposta anterior foi cortada. Continue EXATAMENTE de onde parou, "
                        "sem repetir linhas já enviadas. Mantenha o mesmo formato de tabela Markdown."
                    )
                    cont_response = _call_with_retry(
                        client, pdf_part, cont_prompt,
                        max_retries=5,
                    )
                    cont_text = cont_response.text if cont_response.text else ""
                    batch_text += "\n" + cont_text

                    if hasattr(cont_response, "usage_metadata") and cont_response.usage_metadata:
                        cmeta = cont_response.usage_metadata
                        total_input_tokens += getattr(cmeta, "prompt_token_count", 0) or 0
                        total_output_tokens += getattr(cmeta, "candidates_token_count", 0) or 0

                    finish_reason = None
                    if cont_response.candidates and cont_response.candidates[0].finish_reason:
                        finish_reason = str(cont_response.candidates[0].finish_reason)

                # Deduplicação intra-batch: continuações podem repetir linhas
                if continuation > 0:
                    before = len([l for l in batch_text.split("\n") if "|" in l])
                    batch_text = _deduplicate_batch_lines(batch_text)
                    after = len([l for l in batch_text.split("\n") if "|" in l])
                    if before != after:
                        logger.info(
                            "Dedup lote %d: %d → %d linhas (%d duplicatas removidas)",
                            batch_idx + 1, before, after, before - after,
                        )

                # Log de linhas extraídas no batch
                batch_lines = len([l for l in batch_text.split("\n") if "|" in l])
                logger.info(
                    "Lote %d/%d: %d linhas extraídas (páginas %d-%d)%s",
                    batch_idx + 1, total_batches, batch_lines,
                    page_start, page_end,
                    f" [+{continuation} continuações]" if continuation else "",
                )
                all_results.append(batch_text)

            sys.stdout.write("\r" + " " * 70 + "\r")
            sys.stdout.flush()

            combined_text = "\n".join(all_results)
            total_lines = len([l for l in combined_text.split("\n") if "|" in l])
            logger.info("Total de linhas com dados: %d", total_lines)
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


def _count_accounts_in_pdf(file_path: str) -> tuple[int, dict[int, int]]:
    """Conta linhas de contas no PDF usando extração de texto do PyMuPDF.

    Detecta dois formatos de balancete:
    - Formato 1: "CODIGO CLASSIFICAÇÃO" na mesma linha (ex: "615 01.1.1.02.01")
    - Formato 2: Código sozinho em uma linha (ex: "615")

    Para PDFs de imagem (sem texto extraível), retorna 0.

    Args:
        file_path: Caminho do PDF.

    Returns:
        Tupla (total_contas, dict pagina→contas_na_pagina).
        Páginas são 1-indexed.
    """
    # Padrão 1: "CODIGO CLASSIFICACAO" (ex: "615 01.1.1.02.01")
    p1 = re.compile(r"^\d+\s+\d[\d.]*$")
    # Padrão 2: número inteiro sozinho (ex: "615")
    p2 = re.compile(r"^\d+$")
    # Números de metadata a ignorar (páginas, folhas)
    skip_set = {"0001", "0002", "0003", "0004", "0005"}

    doc = fitz.open(file_path)
    per_page_p1: dict[int, int] = {}
    per_page_p2: dict[int, int] = {}

    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        c1, c2 = 0, 0
        for line in text.split("\n"):
            s = line.strip()
            if p1.match(s):
                c1 += 1
            elif p2.match(s) and s not in skip_set and len(s) <= 5:
                c2 += 1
        per_page_p1[page_num + 1] = c1
        per_page_p2[page_num + 1] = c2

    doc.close()

    total_p1 = sum(per_page_p1.values())
    total_p2 = sum(per_page_p2.values())

    # Usa o padrão que encontrou mais contas
    if total_p1 >= total_p2:
        return total_p1, per_page_p1
    return total_p2, per_page_p2


def _count_accounts_in_range(
    per_page: dict[int, int], page_start: int, page_end: int,
) -> int:
    """Conta contas em um intervalo de páginas.

    Args:
        per_page: Dict pagina→contas (de _count_accounts_in_pdf).
        page_start: Primeira página (1-indexed).
        page_end: Última página (1-indexed, inclusive).

    Returns:
        Total de contas no intervalo.
    """
    return sum(per_page.get(p, 0) for p in range(page_start, page_end + 1))


def _count_accounts_from_text(text: str) -> int:
    """Conta linhas de contas no texto extraído via OCR/get_text.

    Usa os mesmos heurísticos de _count_accounts_in_pdf():
    - Padrão 1: "CODIGO CLASSIFICACAO" (ex: "615 01.1.1.02.01")
    - Padrão 2: Código sozinho (ex: "615")

    Retorna a contagem do padrão que encontrou mais matches.

    Args:
        text: Texto extraído (de get_text ou OCR).

    Returns:
        Número estimado de contas.
    """
    if not text.strip():
        return 0

    p1 = re.compile(r"^\d+\s+\d[\d.]*$")
    p2 = re.compile(r"^\d+$")
    skip_set = {"0001", "0002", "0003", "0004", "0005"}

    count_p1 = 0
    count_p2 = 0

    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if p1.match(s):
            count_p1 += 1
        elif p2.match(s) and s not in skip_set and len(s) <= 5:
            count_p2 += 1

    return max(count_p1, count_p2)


COUNT_PROMPT = """\
Conte APENAS o número de linhas/contas na tabela financeira (balancete) destas páginas.

REGRAS:
- Conte cada linha da tabela que representa uma conta contábil.
- NÃO conte cabeçalhos, separadores, totais de página, rodapés ou linhas em branco.
- Conte contas agrupadoras E contas de detalhe.
- Responda APENAS com um número inteiro. Nada mais.

Exemplo de resposta: 127
"""


def _gemini_count_accounts(
    client, types, file_path: str, total_pages: int,
    batches: list[tuple[int, int]],
) -> dict[str, int]:
    """Pede ao Gemini para contar contas em cada batch de páginas.

    Faz uma chamada rápida por batch, pedindo apenas a contagem.
    Isso orienta o Gemini na extração subsequente sobre quantas
    linhas esperar.

    Args:
        client: Cliente Gemini.
        types: Módulo google.genai.types.
        file_path: Caminho do PDF.
        total_pages: Total de páginas.
        batches: Lista de (page_start, page_end).

    Returns:
        Dict com chave "page_start-page_end" → contagem esperada.
        Retorna 0 para batches onde a contagem falhou.
    """
    results: dict[str, int] = {}
    total_counted = 0

    for batch_idx, (page_start, page_end) in enumerate(batches):
        batch_key = f"{page_start}-{page_end}"
        try:
            pdf_bytes = _extract_page_range(file_path, page_start, page_end)
            pdf_part = types.Part.from_bytes(
                data=pdf_bytes, mime_type="application/pdf",
            )

            response = _call_with_retry(
                client, pdf_part, COUNT_PROMPT, max_retries=3,
            )

            text = (response.text or "").strip()
            # Extrai o primeiro número da resposta
            match = re.search(r"\d+", text)
            if match:
                count = int(match.group())
                results[batch_key] = count
                total_counted += count
                logger.info(
                    "Pré-contagem lote %d/%d (págs %d-%d): %d contas",
                    batch_idx + 1, len(batches), page_start, page_end, count,
                )
            else:
                logger.warning(
                    "Pré-contagem lote %d: resposta não numérica: %s",
                    batch_idx + 1, text[:50],
                )
                results[batch_key] = 0

        except Exception as exc:
            logger.warning(
                "Pré-contagem lote %d falhou: %s", batch_idx + 1, exc,
            )
            results[batch_key] = 0

    if total_counted > 0:
        logger.info("Pré-contagem total: %d contas no PDF", total_counted)
    else:
        logger.warning("Pré-contagem: não foi possível contar contas")

    return results


def _deduplicate_batch_lines(batch_text: str) -> str:
    """Remove linhas duplicadas de um batch que teve continuações.

    Quando o Gemini é forçado a continuar após MAX_TOKENS, ele não tem
    contexto do que já enviou (é uma chamada nova com o mesmo PDF).
    Isso causa duplicação de linhas. Esta função remove duplicatas
    usando Código+Classificação como chave única.

    Estratégia:
    1. Separa linhas de tabela (com |) das demais.
    2. Para cada linha de tabela, extrai Código e Classificação (colunas 1 e 2).
    3. Se Código+Classificação já foi visto, descarta (mantém a primeira).
    4. Linhas sem dados suficientes ou sem | são preservadas.

    Args:
        batch_text: Texto bruto do batch (pode conter múltiplas respostas concatenadas).

    Returns:
        Texto com duplicatas removidas.
    """
    lines = batch_text.split("\n")
    result = []
    seen_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()

        # Não é linha de tabela — preserva
        if "|" not in stripped:
            result.append(line)
            continue

        # Ignora separadores (|---|---|)
        clean_sep = stripped.strip("|").strip()
        if clean_sep and re.match(r"^[\s\-:|]+$", clean_sep):
            result.append(line)
            continue

        # Extrai células
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:]]
        else:
            cells = [c.strip() for c in stripped.split("|")]

        # Precisa de pelo menos Código + Classificação + Descrição
        if len(cells) < 3:
            result.append(line)
            continue

        codigo = cells[0].strip().lower()
        classificacao = cells[1].strip().lower()

        # Cabeçalhos (contêm texto não-numérico no código) — pular duplicatas
        is_header = not codigo or (codigo and not codigo[0].isdigit() and not codigo.startswith("*"))
        if is_header:
            # Preserva o primeiro cabeçalho, pula os repetidos
            header_key = f"HDR|{codigo}|{classificacao}"
            if header_key in seen_keys:
                continue
            seen_keys.add(header_key)
            result.append(line)
            continue

        # Chave: Código + Classificação identifica uma conta única
        key = f"{codigo}|{classificacao}"
        if key in seen_keys:
            continue

        seen_keys.add(key)
        result.append(line)

    return "\n".join(result)


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


def _extract_ocr_text_for_batch(
    file_path: str, page_start: int, page_end: int,
) -> tuple[str, str]:
    """Extrai texto de um batch de páginas, usando OCR se necessário.

    Estratégia em camadas:
    1. PyMuPDF get_text() — rápido, funciona em PDFs com texto embutido.
    2. Se texto escasso (< OCR_TEXT_THRESHOLD por página), tenta OCR via
       PyMuPDF get_textpage_ocr() (requer Tesseract instalado).
    3. Se Tesseract indisponível, usa o texto escasso mesmo.

    O texto extraído serve como "mapa/guia" para o Gemini — mesmo com
    erros de OCR, ajuda a garantir que nenhuma conta seja omitida.

    Args:
        file_path: Caminho do PDF.
        page_start: Primeira página (1-indexed).
        page_end: Última página (1-indexed, inclusive).

    Returns:
        Tupla (texto_extraído, método: 'text'|'ocr'|'text_fallback'|'error').
    """
    try:
        doc = fitz.open(file_path)
        pages_text: list[str] = []
        method = "text"
        needs_ocr = False

        # Fase 1: tenta get_text() para todas as páginas do batch
        for page_num in range(page_start - 1, min(page_end, len(doc))):
            page = doc[page_num]
            text = page.get_text()
            pages_text.append((page_num, text))
            if len(text.strip()) < OCR_TEXT_THRESHOLD:
                needs_ocr = True

        # Fase 2: se alguma página tem texto escasso, tenta OCR
        if needs_ocr:
            try:
                ocr_pages: list[str] = []
                for page_num in range(page_start - 1, min(page_end, len(doc))):
                    page = doc[page_num]
                    tp = page.get_textpage_ocr(flags=0, language="por", dpi=150)
                    ocr_text = tp.extractText()
                    ocr_pages.append((page_num, ocr_text))
                # OCR teve sucesso — usar resultado OCR
                pages_text = ocr_pages
                method = "ocr"
                logger.info(
                    "OCR Tesseract usado para páginas %d-%d (texto escasso detectado).",
                    page_start, page_end,
                )
            except Exception as ocr_exc:
                # Tesseract não instalado ou OCR falhou — usar texto escasso
                method = "text_fallback"
                logger.debug(
                    "OCR indisponível para páginas %d-%d: %s. Usando get_text().",
                    page_start, page_end, ocr_exc,
                )

        doc.close()

        # Monta texto final com marcadores de página
        result_parts: list[str] = []
        for page_num, text in pages_text:
            text_clean = text.strip()
            if text_clean:
                result_parts.append(f"--- Página {page_num + 1} ---")
                result_parts.append(text_clean)

        return "\n".join(result_parts), method

    except Exception as exc:
        logger.warning(
            "OCR falhou para páginas %d-%d: %s. Continuando sem OCR.",
            page_start, page_end, exc,
        )
        return "", "error"


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estima o custo das chamadas ao Gemini Flash (pricing do modelo ativo)."""
    pricing = MODELOS_DISPONIVEIS.get(config.gemini_model, {})
    input_price = pricing.get("input_price", 0.15)
    output_price = pricing.get("output_price", 0.60)
    input_cost = (input_tokens / 1_000_000) * input_price
    output_cost = (output_tokens / 1_000_000) * output_price
    return round(input_cost + output_cost, 6)
