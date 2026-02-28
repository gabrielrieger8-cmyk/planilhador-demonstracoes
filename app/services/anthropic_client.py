"""Cliente Anthropic: classificação, extração e formatação via Claude.

Suporta todas as etapas do pipeline usando modelos Anthropic (Haiku, etc).
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
import fitz

from app.config import ANTHROPIC_API_KEY, FORMATTER_MODEL, calcular_custo_anthropic

logger = logging.getLogger("planilhador")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    return path.read_text(encoding="utf-8")


def _call_with_retry(fn, max_retries: int = 5):
    """Executa callable com retry e exponential backoff."""
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError:
            if attempt < max_retries - 1:
                wait = (2 ** attempt) * 2
                logger.warning(
                    "Rate limit (tentativa %d/%d). Aguardando %ds...",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                raise
        except anthropic.APIStatusError as exc:
            if exc.status_code == 529 and attempt < max_retries - 1:
                wait = (2 ** attempt) * 2
                logger.warning(
                    "API overloaded (tentativa %d/%d). Aguardando %ds...",
                    attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
            else:
                raise


# ---------------------------------------------------------------------------
# Classificação via Anthropic
# ---------------------------------------------------------------------------

def classificar_documento_anthropic(
    pdf_path: str,
    model: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Classifica um PDF usando modelo Anthropic.

    Envia o PDF como documento base64 e identifica demonstrações presentes.

    Returns:
        Dict com: empresa, demonstracoes, confianca, custo_usd, usage.
    """
    modelo = model or FORMATTER_MODEL
    client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)

    system_prompt = _load_prompt("system_classifier.txt")
    pdf_bytes = Path(pdf_path).read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    def _call():
        return client.messages.stream(
            model=modelo,
            max_tokens=2000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": "Classifique este documento conforme as instruções."},
                ],
            }],
        )

    stream_ctx = _call_with_retry(_call)
    with stream_ctx as stream:
        response = stream.get_final_message()
    texto = response.content[0].text
    custo = calcular_custo_anthropic(response.usage, modelo)

    dados = _robust_json_parse(texto)
    return {
        **dados,
        "custo_usd": custo,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Extração via Anthropic
# ---------------------------------------------------------------------------

def extrair_balancete_anthropic(
    pdf_path: str,
    paginas: list[int] | None = None,
    model: str | None = None,
    api_key: str | None = None,
    on_progress: callable | None = None,
) -> dict:
    """Extrai dados de balancete usando modelo Anthropic (page-by-page).

    Returns:
        Dict com: text, custo_usd, success, pages_processed.
    """
    modelo = model or FORMATTER_MODEL
    client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)

    base_prompt = _load_prompt("system_balancete_gemini.txt")
    path = Path(pdf_path)
    doc = fitz.open(str(path))
    total_pages = len(doc)

    if paginas:
        pages_to_process = sorted(p for p in paginas if 1 <= p <= total_pages)
    else:
        pages_to_process = list(range(1, total_pages + 1))
    doc.close()

    start_time = time.time()
    all_results: list[str] = []
    total_input = 0
    total_output = 0
    total_custo = 0.0
    is_first = True

    for batch_idx, page_num in enumerate(pages_to_process):
        if on_progress:
            on_progress(
                f"Extraindo página {page_num}/{pages_to_process[-1]} "
                f"(lote {batch_idx + 1}/{len(pages_to_process)})"
            )

        pdf_bytes = _extract_page_range_bytes(str(path), page_num, page_num)
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

        batch_prompt = base_prompt
        if is_first:
            batch_prompt += "\nInclua o cabeçalho da tabela (nomes das colunas) como primeira linha."
            is_first = False
        else:
            batch_prompt += "\nNÃO inclua cabeçalho — apenas as linhas de dados."

        def _call(b64=pdf_b64, prompt=batch_prompt):
            return client.messages.stream(
                model=modelo,
                max_tokens=64000,
                system=prompt,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": "Extraia os dados desta página conforme as instruções."},
                    ],
                }],
            )

        stream_ctx = _call_with_retry(_call)
        with stream_ctx as stream:
            response = stream.get_final_message()
        batch_text = response.content[0].text
        total_custo += calcular_custo_anthropic(response.usage, modelo)
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        all_results.append(batch_text)

        logger.info(
            "Lote %d/%d: %d linhas (página %d)",
            batch_idx + 1, len(pages_to_process),
            len([l for l in batch_text.split("\n") if "|" in l]),
            page_num,
        )

    combined = "\n".join(all_results)
    elapsed = time.time() - start_time

    logger.info(
        "Balancete extraído (Anthropic): %d páginas em %.1fs, custo=$%.4f",
        len(pages_to_process), elapsed, total_custo,
    )

    # Retorna no mesmo formato que GeminiResult para compatibilidade
    from app.services.gemini_client import GeminiResult
    return GeminiResult(
        text=combined,
        pages_processed=len(pages_to_process),
        input_tokens=total_input,
        output_tokens=total_output,
        processing_time=elapsed,
        custo_usd=total_custo,
    )


def extrair_demonstracao_anthropic(
    pdf_path: str,
    tipo: str,
    paginas: list[int] | None = None,
    model: str | None = None,
    api_key: str | None = None,
    on_progress: callable | None = None,
) -> dict:
    """Extrai dados de DRE ou Balanço Patrimonial usando modelo Anthropic.

    Returns:
        GeminiResult com texto extraído.
    """
    modelo = model or FORMATTER_MODEL
    client = anthropic.Anthropic(api_key=api_key or ANTHROPIC_API_KEY)

    prompt = _load_prompt("system_demonstracao_gemini.txt")
    path = Path(pdf_path)

    if paginas:
        pdf_bytes = _extract_page_range_bytes(str(path), min(paginas), max(paginas))
    else:
        pdf_bytes = path.read_bytes()

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    if on_progress:
        on_progress(f"Extraindo {tipo} ({len(paginas or [])} páginas)")

    start_time = time.time()

    def _call():
        return client.messages.stream(
            model=modelo,
            max_tokens=64000,
            system=prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": "Extraia os dados desta demonstração conforme as instruções."},
                ],
            }],
        )

    stream_ctx = _call_with_retry(_call)
    with stream_ctx as stream:
        response = stream.get_final_message()
    text = response.content[0].text
    custo = calcular_custo_anthropic(response.usage, modelo)
    elapsed = time.time() - start_time

    logger.info("%s extraído (Anthropic) em %.1fs, custo=$%.4f", tipo, elapsed, custo)

    from app.services.gemini_client import GeminiResult
    return GeminiResult(
        text=text,
        pages_processed=len(paginas) if paginas else 0,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        processing_time=elapsed,
        custo_usd=custo,
    )


def _extract_page_range_bytes(file_path: str, page_start: int, page_end: int) -> bytes:
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


# ---------------------------------------------------------------------------
# Formatação via Anthropic
# ---------------------------------------------------------------------------

def formatar_demonstracao(
    texto_gemini: str,
    tipo: str,
    api_key: str | None = None,
    model: str | None = None,
) -> dict:
    """Formata dados extraídos pelo Gemini em JSON estruturado.

    Args:
        texto_gemini: Texto bruto do Gemini (Markdown tables).
        tipo: "dre" ou "balanco_patrimonial".
        api_key: Chave da API Anthropic.
        model: Modelo Anthropic a usar.

    Returns:
        Dict com: dados (JSON estruturado), custo_usd, usage.
    """
    modelo = model or FORMATTER_MODEL
    client = anthropic.Anthropic(
        api_key=api_key or ANTHROPIC_API_KEY
    )

    prompt_files = {
        "dre": "system_dre_format.txt",
        "balanco_patrimonial": "system_balanco_format.txt",
    }
    prompt_file = prompt_files.get(tipo)
    if not prompt_file:
        raise ValueError(f"Tipo não suportado para formatação Sonnet: {tipo}")

    system_prompt = _load_prompt(prompt_file)

    total_custo = 0
    full_text = ""
    total_input = 0
    total_output = 0

    messages = [
        {
            "role": "user",
            "content": (
                "Dados extraídos de um PDF (podem conter erros de extração):\n\n"
                f"{texto_gemini}\n\n"
                "Estruture esses dados conforme as instruções do sistema."
            ),
        }
    ]

    for attempt in range(4):
        def _call():
            return client.messages.stream(
                model=modelo,
                max_tokens=64000,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )

        stream_ctx = _call_with_retry(_call)
        with stream_ctx as stream:
            response = stream.get_final_message()

        texto_parte = response.content[0].text
        total_custo += calcular_custo_anthropic(response.usage, modelo)
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        full_text += texto_parte

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "max_tokens":
            logger.warning(
                "Resposta truncada (tentativa %d/3). Pedindo continuação...",
                attempt + 1,
            )
            messages.append({"role": "assistant", "content": texto_parte})
            messages.append({
                "role": "user",
                "content": "Continue EXATAMENTE de onde parou. Não repita dados já extraídos.",
            })
        else:
            break

    dados = _robust_json_parse(full_text)

    return {
        "dados": dados,
        "custo_usd": total_custo,
        "usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def refinar_balancete(
    csv_text: str,
    api_key: str | None = None,
    model: str | None = None,
) -> dict:
    """Refina dados de balancete extraídos pelo Gemini.

    Corrige: Tipo A/D, natureza D/C, sinais, hierarquia.

    Args:
        csv_text: Texto Markdown com tabelas do balancete (do Gemini).
        api_key: Chave da API Anthropic.
        model: Modelo Anthropic a usar.

    Returns:
        Dict com: dados (JSON estruturado), custo_usd, usage.
    """
    modelo = model or FORMATTER_MODEL
    client = anthropic.Anthropic(
        api_key=api_key or ANTHROPIC_API_KEY
    )

    system_prompt = _load_prompt("system_balancete_refine.txt")

    total_custo = 0
    full_text = ""
    total_input = 0
    total_output = 0

    messages = [
        {
            "role": "user",
            "content": (
                "Dados de balancete extraídos de um PDF (tabela Markdown):\n\n"
                f"{csv_text}\n\n"
                "Refine e estruture esses dados conforme as instruções do sistema."
            ),
        }
    ]

    for attempt in range(4):
        def _call():
            return client.messages.stream(
                model=modelo,
                max_tokens=64000,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
            )

        stream_ctx = _call_with_retry(_call)
        with stream_ctx as stream:
            response = stream.get_final_message()

        texto_parte = response.content[0].text
        total_custo += calcular_custo_anthropic(response.usage, modelo)
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        full_text += texto_parte

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "max_tokens":
            logger.warning(
                "Resposta truncada (tentativa %d/3). Pedindo continuação...",
                attempt + 1,
            )
            messages.append({"role": "assistant", "content": texto_parte})
            messages.append({
                "role": "user",
                "content": "Continue EXATAMENTE de onde parou. Não repita dados já extraídos.",
            })
        else:
            break

    dados = _robust_json_parse(full_text)

    return {
        "dados": dados,
        "custo_usd": total_custo,
        "usage": {
            "input_tokens": total_input,
            "output_tokens": total_output,
        },
    }


def _robust_json_parse(text: str) -> dict:
    """Tenta parsear JSON da resposta do Claude."""
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
