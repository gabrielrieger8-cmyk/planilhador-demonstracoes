"""Cliente Anthropic: Sonnet formata e refina dados extraídos pelo Gemini.

Sonnet = "cérebro" do sistema. Recebe texto bruto do Gemini e estrutura em JSON.
Único uso de Anthropic no projeto.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import anthropic

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


def formatar_demonstracao(
    texto_gemini: str,
    tipo: str,
    api_key: str | None = None,
) -> dict:
    """Formata dados extraídos pelo Gemini em JSON estruturado usando Sonnet.

    Args:
        texto_gemini: Texto bruto do Gemini (Markdown tables).
        tipo: "dre" ou "balanco_patrimonial".
        api_key: Chave da API Anthropic.

    Returns:
        Dict com: dados (JSON estruturado), custo_usd, usage.
    """
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
                model=FORMATTER_MODEL,
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
        total_custo += calcular_custo_anthropic(response.usage, FORMATTER_MODEL)
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
) -> dict:
    """Refina dados de balancete extraídos pelo Gemini usando Sonnet.

    Sonnet corrige: Tipo A/D, natureza D/C, sinais, hierarquia.

    Args:
        csv_text: Texto Markdown com tabelas do balancete (do Gemini).
        api_key: Chave da API Anthropic.

    Returns:
        Dict com: dados (JSON estruturado), custo_usd, usage.
    """
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
                model=FORMATTER_MODEL,
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
        total_custo += calcular_custo_anthropic(response.usage, FORMATTER_MODEL)
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
