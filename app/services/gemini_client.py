"""Cliente Gemini unificado: classificação (2.0 Flash) e extração (2.5 Flash).

Gemini = "olhos" do sistema. Lê o PDF e extrai dados brutos.
- 2.0 Flash: classifica documento e identifica páginas (~$0.003/PDF)
- 2.5 Flash: extrai dados de cada demonstração (page-by-page para balancetes)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from app.config import (
    CLASSIFIER_MODEL,
    EXTRACTOR_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODELS,
    calcular_custo_gemini,
)

logger = logging.getLogger("planilhador")

# Quantas páginas enviar por chamada (1 = máxima precisão para balancetes)
PAGES_PER_BATCH = 1

# OCR como guia
OCR_TEXT_THRESHOLD = 50
MAX_OCR_CHARS_PER_BATCH = 15000

# Diretório dos prompts
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


@dataclass
class GeminiResult:
    """Resultado do processamento pelo Gemini."""

    text: str
    pages_processed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    processing_time: float = 0.0
    custo_usd: float = 0.0
    success: bool = True
    error: str | None = None


# ---------------------------------------------------------------------------
# Client e retry
# ---------------------------------------------------------------------------

def _get_client(api_key: str | None = None):
    """Cria client Gemini."""
    from google import genai

    key = api_key or GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY não configurada.")
    return genai.Client(api_key=key)


def _call_gemini(
    client,
    model: str,
    contents: list,
    max_tokens: int = 200000,
    temperature: float = 0.1,
    max_retries: int = 5,
):
    """Chama Gemini com retry e exponential backoff."""
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            return response
        except Exception as exc:
            error_str = str(exc).lower()
            is_rate_limit = any(
                k in error_str
                for k in ("429", "rate", "quota", "resource_exhausted")
            )
            if is_rate_limit and attempt < max_retries - 1:
                wait = (2 ** attempt) * 2
                logger.warning(
                    "Rate limit (tentativa %d/%d). Aguardando %ds...",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                raise


def _get_usage(response) -> tuple[int, int]:
    """Extrai tokens de input e output do response."""
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta = response.usage_metadata
        return (
            getattr(meta, "prompt_token_count", 0) or 0,
            getattr(meta, "candidates_token_count", 0) or 0,
        )
    return 0, 0


# ---------------------------------------------------------------------------
# Classificação (Gemini 2.0 Flash)
# ---------------------------------------------------------------------------

def classificar_documento(
    pdf_path: str,
    api_key: str | None = None,
) -> dict:
    """Classifica um PDF usando Gemini 2.0 Flash.

    Envia o PDF completo e identifica todas as demonstrações presentes.

    Returns:
        Dict com: empresa, demonstracoes, confianca, custo_usd, usage.
    """
    from google.genai import types

    client = _get_client(api_key)
    system_prompt = _load_prompt("system_classifier.txt")

    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    response = _call_gemini(
        client,
        model=CLASSIFIER_MODEL,
        contents=[pdf_part, system_prompt],
        max_tokens=2000,
        temperature=0.1,
    )

    inp, out = _get_usage(response)
    custo = calcular_custo_gemini(
        {"input_tokens": inp, "output_tokens": out}, CLASSIFIER_MODEL
    )

    texto = response.text or ""
    dados = _robust_json_parse(texto)

    return {
        **dados,
        "custo_usd": custo,
        "usage": {"input_tokens": inp, "output_tokens": out},
    }


# ---------------------------------------------------------------------------
# Extração — Balancete (page-by-page com FINANCIAL_PROMPT)
# ---------------------------------------------------------------------------

def extrair_balancete(
    pdf_path: str,
    paginas: list[int] | None = None,
    api_key: str | None = None,
    on_progress: callable | None = None,
) -> GeminiResult:
    """Extrai dados de um balancete usando Gemini 2.5 Flash page-by-page.

    Args:
        pdf_path: Caminho para o PDF.
        paginas: Páginas específicas (1-indexed). None = todas.
        api_key: Chave da API Gemini.
        on_progress: Callback(stage_detail: str) para atualizar progresso.

    Returns:
        GeminiResult com texto Markdown das tabelas extraídas.
    """
    from google.genai import types

    client = _get_client(api_key)
    base_prompt = _load_prompt("system_balancete_gemini.txt")

    path = Path(pdf_path)
    doc = fitz.open(str(path))
    total_pages = len(doc)

    # Determina páginas a processar
    if paginas:
        pages_to_process = sorted(p for p in paginas if 1 <= p <= total_pages)
    else:
        pages_to_process = list(range(1, total_pages + 1))

    doc.close()

    start_time = time.time()
    all_results: list[str] = []
    total_input = 0
    total_output = 0
    is_first = True

    for batch_idx, page_num in enumerate(pages_to_process):
        if on_progress:
            on_progress(
                f"Extraindo página {page_num}/{pages_to_process[-1]} "
                f"(lote {batch_idx + 1}/{len(pages_to_process)})"
            )

        # Extrai página como sub-PDF
        pdf_bytes = _extract_page_range(str(path), page_num, page_num)
        pdf_part = types.Part.from_bytes(
            data=pdf_bytes, mime_type="application/pdf"
        )

        # OCR guide
        ocr_text = _extract_ocr_text(str(path), page_num, page_num)
        batch_prompt = base_prompt

        # Contagem esperada de contas
        account_count = _count_accounts_from_text(ocr_text)
        if account_count > 0:
            batch_prompt += (
                f"\n\nCONTAGEM PRÉVIA: Esta página contém EXATAMENTE {account_count} contas/linhas. "
                f"Sua saída DEVE ter exatamente {account_count} linhas de dados."
            )

        # Injetar OCR como guia
        if ocr_text.strip():
            ocr_inject = ocr_text[:MAX_OCR_CHARS_PER_BATCH]
            batch_prompt += (
                "\n\nTEXTO OCR DE REFERÊNCIA (pode conter erros — use como guia):\n"
                f"```\n{ocr_inject}\n```"
            )

        if is_first:
            batch_prompt += "\nInclua o cabeçalho da tabela (nomes das colunas) como primeira linha."
            is_first = False
        else:
            batch_prompt += "\nNÃO inclua cabeçalho — apenas as linhas de dados."

        response = _call_gemini(
            client, model=EXTRACTOR_MODEL,
            contents=[pdf_part, batch_prompt],
            max_tokens=200000,
        )

        batch_text = response.text or ""
        inp, out = _get_usage(response)
        total_input += inp
        total_output += out

        # Anti-truncamento
        batch_text = _handle_continuation(
            client, pdf_part, batch_text, response, total_input, total_output
        )

        all_results.append(batch_text)
        logger.info(
            "Lote %d/%d: %d linhas (página %d)",
            batch_idx + 1, len(pages_to_process),
            len([l for l in batch_text.split("\n") if "|" in l]),
            page_num,
        )

    combined = "\n".join(all_results)
    elapsed = time.time() - start_time
    custo = calcular_custo_gemini(
        {"input_tokens": total_input, "output_tokens": total_output},
        EXTRACTOR_MODEL,
    )

    logger.info(
        "Balancete extraído: %d páginas em %.1fs, custo=$%.4f",
        len(pages_to_process), elapsed, custo,
    )

    return GeminiResult(
        text=combined,
        pages_processed=len(pages_to_process),
        input_tokens=total_input,
        output_tokens=total_output,
        processing_time=elapsed,
        custo_usd=custo,
    )


# ---------------------------------------------------------------------------
# Extração — DRE / Balanço Patrimonial (prompt genérico)
# ---------------------------------------------------------------------------

def extrair_demonstracao(
    pdf_path: str,
    tipo: str,
    paginas: list[int] | None = None,
    api_key: str | None = None,
    on_progress: callable | None = None,
) -> GeminiResult:
    """Extrai dados de DRE ou Balanço Patrimonial usando Gemini 2.5 Flash.

    Envia as páginas filtradas com um prompt genérico.

    Args:
        pdf_path: Caminho para o PDF.
        tipo: "dre" ou "balanco_patrimonial".
        paginas: Páginas específicas (1-indexed). None = todas.
        api_key: Chave da API Gemini.
        on_progress: Callback(stage_detail: str).

    Returns:
        GeminiResult com texto extraído.
    """
    from google.genai import types

    client = _get_client(api_key)
    prompt = _load_prompt("system_demonstracao_gemini.txt")

    path = Path(pdf_path)

    # Extrai páginas específicas ou o PDF todo
    if paginas:
        pdf_bytes = _extract_page_range(str(path), min(paginas), max(paginas))
    else:
        pdf_bytes = path.read_bytes()

    pdf_part = types.Part.from_bytes(
        data=pdf_bytes, mime_type="application/pdf"
    )

    if on_progress:
        on_progress(f"Extraindo {tipo} ({len(paginas or [])} páginas)")

    start_time = time.time()

    response = _call_gemini(
        client, model=EXTRACTOR_MODEL,
        contents=[pdf_part, prompt],
        max_tokens=200000,
    )

    text = response.text or ""
    inp, out = _get_usage(response)

    # Anti-truncamento
    text = _handle_continuation(client, pdf_part, text, response, inp, out)

    elapsed = time.time() - start_time
    custo = calcular_custo_gemini(
        {"input_tokens": inp, "output_tokens": out}, EXTRACTOR_MODEL
    )

    logger.info(
        "%s extraído em %.1fs, custo=$%.4f",
        tipo, elapsed, custo,
    )

    return GeminiResult(
        text=text,
        pages_processed=len(paginas) if paginas else 0,
        input_tokens=inp,
        output_tokens=out,
        processing_time=elapsed,
        custo_usd=custo,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _handle_continuation(
    client, pdf_part, text: str, response, total_input: int, total_output: int
) -> str:
    """Detecta truncamento por MAX_TOKENS e pede continuação."""
    finish_reason = None
    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = str(response.candidates[0].finish_reason)

    max_continuations = 3
    for i in range(max_continuations):
        if not finish_reason or "MAX_TOKENS" not in finish_reason:
            break

        logger.warning("Resposta truncada (continuação %d/%d)...", i + 1, max_continuations)
        cont_response = _call_gemini(
            client, model=EXTRACTOR_MODEL,
            contents=[
                pdf_part,
                "Continue EXATAMENTE de onde parou, sem repetir dados já enviados. "
                "Mantenha o mesmo formato.",
            ],
            max_tokens=200000,
        )
        cont_text = cont_response.text or ""
        text += "\n" + cont_text

        finish_reason = None
        if cont_response.candidates and cont_response.candidates[0].finish_reason:
            finish_reason = str(cont_response.candidates[0].finish_reason)

    return text


def _extract_page_range(file_path: str, page_start: int, page_end: int) -> bytes:
    """Extrai intervalo de páginas como bytes de sub-PDF."""
    src = fitz.open(file_path)
    total = len(src)

    if page_start == 1 and page_end >= total:
        pdf_bytes = src.tobytes()
        src.close()
        return pdf_bytes

    dst = fitz.open()
    dst.insert_pdf(src, from_page=page_start - 1, to_page=page_end - 1)
    pdf_bytes = dst.tobytes()
    dst.close()
    src.close()
    return pdf_bytes


def _extract_ocr_text(file_path: str, page_start: int, page_end: int) -> str:
    """Extrai texto de páginas via PyMuPDF get_text."""
    doc = fitz.open(file_path)
    parts = []
    for page_num in range(page_start - 1, min(page_end, len(doc))):
        text = doc[page_num].get_text().strip()
        if text:
            parts.append(text)
    doc.close()
    return "\n".join(parts)


def _count_accounts_from_text(text: str) -> int:
    """Conta linhas de contas no texto extraído via OCR."""
    if not text.strip():
        return 0

    p1 = re.compile(r"^\d+\s+\d[\d.]*$")
    p2 = re.compile(r"^\d+$")
    skip_set = {"0001", "0002", "0003", "0004", "0005"}

    count_p1, count_p2 = 0, 0
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if p1.match(s):
            count_p1 += 1
        elif p2.match(s) and s not in skip_set and len(s) <= 5:
            count_p2 += 1

    return max(count_p1, count_p2)


def _deduplicate_batch_lines(batch_text: str) -> str:
    """Remove linhas duplicadas usando Código+Classificação como chave."""
    lines = batch_text.split("\n")
    result = []
    seen_keys: set[str] = set()

    for line in lines:
        stripped = line.strip()

        if "|" not in stripped:
            result.append(line)
            continue

        clean_sep = stripped.strip("|").strip()
        if clean_sep and re.match(r"^[\s\-:|]+$", clean_sep):
            result.append(line)
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
        elif stripped.startswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:]]
        else:
            cells = [c.strip() for c in stripped.split("|")]

        if len(cells) < 3:
            result.append(line)
            continue

        codigo = cells[0].strip().lower()
        classificacao = cells[1].strip().lower()

        is_header = not codigo or (
            codigo and not codigo[0].isdigit() and not codigo.startswith("*")
        )
        if is_header:
            header_key = f"HDR|{codigo}|{classificacao}"
            if header_key in seen_keys:
                continue
            seen_keys.add(header_key)
            result.append(line)
            continue

        key = f"{codigo}|{classificacao}"
        if key in seen_keys:
            continue

        seen_keys.add(key)
        result.append(line)

    return "\n".join(result)


def _robust_json_parse(text: str) -> dict:
    """Tenta parsear JSON da resposta do Gemini."""
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Não foi possível extrair JSON da resposta: {text[:200]}...")
