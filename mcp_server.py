"""MCP Server para o Planilhador de Demonstracoes.

Expoe as funcoes standalone do pipeline como ferramentas MCP:
  - classificar_documento
  - extrair_demonstracao
  - exportar_planilha
  - estimar_custo_processamento
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Garante que o pacote 'app' seja importavel
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

mcp = FastMCP("mirar-planilhador")
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def _excel_response(caminho: Path, extra: dict) -> str:
    """Retorna JSON com o caminho do Excel e metadados."""
    result = {"arquivo": str(caminho.resolve()), **extra}
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 1 — Classificar documento
# ---------------------------------------------------------------------------

@mcp.tool()
def classificar_documento(pdf_path: str, modelo: str = "gemini-2.5-flash") -> str:
    """Classifica um PDF contabil e identifica as demonstracoes presentes.

    Args:
        pdf_path: Caminho absoluto para o arquivo PDF.
        modelo: Modelo de IA a usar (ex: gemini-2.5-flash).

    Returns:
        JSON com empresa, demonstracoes encontradas e custo estimado.
    """
    from app.services.classifier import classificar

    resultado = classificar(pdf_path, model=modelo)
    return json.dumps(resultado, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool 2 — Extrair demonstracao (salva em arquivo, retorna só resumo)
# ---------------------------------------------------------------------------

def _extrair_e_formatar(pdf_path: str, tipo: str, paginas=None, modelo="gemini-2.5-flash"):
    """Executa extracao + formatacao + validacao. Retorna (resultado_dict, validacoes)."""
    from app.services.gemini_client import (
        extrair_balancete,
        extrair_demonstracao as extrair_demo_gemini,
    )
    from app.services.formatter import (
        formatar_balancete,
        formatar_balanco_multi,
        formatar_dre_multi,
    )
    from app.services.validator import validate

    if tipo == "balancete":
        gemini_result = extrair_balancete(pdf_path, paginas=paginas, model=modelo)
    elif tipo in ("dre", "balanco_patrimonial"):
        gemini_result = extrair_demo_gemini(pdf_path, tipo=tipo, paginas=paginas, model=modelo)
    else:
        raise ValueError(f"Tipo invalido: {tipo}. Use balancete, dre ou balanco_patrimonial.")

    if tipo == "balancete":
        dados = formatar_balancete(gemini_result.text)
        dados_list = [dados]
    elif tipo == "dre":
        dados_list = formatar_dre_multi(gemini_result.text)
    else:
        dados_list = formatar_balanco_multi(gemini_result.text)

    validacoes = []
    for d in dados_list:
        vr = validate(d, tipo)
        validacoes.append({
            "passed": vr.passed,
            "errors": vr.errors,
            "warnings": vr.warnings,
            "details": vr.details,
        })

    return dados_list, validacoes, gemini_result.custo_usd, gemini_result.pages_processed


@mcp.tool()
def extrair_demonstracao(
    tipo: str,
    pdf_path: str,
    paginas: list[int] | None = None,
    modelo: str = "gemini-2.5-flash",
) -> str:
    """Extrai, formata e valida uma demonstracao financeira de um PDF.

    Salva os dados completos em arquivo JSON e retorna apenas um resumo
    com caminho do arquivo, validacao e custo (sem carregar os dados no contexto).

    Args:
        tipo: Tipo da demonstracao — "balancete", "dre" ou "balanco_patrimonial".
        pdf_path: Caminho absoluto para o arquivo PDF.
        paginas: Lista de paginas (1-indexed) a processar. None = todas.
        modelo: Modelo de IA a usar na extracao.

    Returns:
        JSON com caminho do arquivo de dados, resumo da validacao e custo.
    """
    resolved = pdf_path
    dados_list, validacoes, custo, pages = _extrair_e_formatar(resolved, tipo, paginas, modelo)

    # Salva dados completos em arquivo JSON
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(pdf_path).stem.replace(" ", "_")
    json_path = OUTPUT_DIR / f"{base_name}_{tipo}_{timestamp}.json"
    resultado_completo = {
        "tipo": tipo,
        "dados": dados_list if len(dados_list) > 1 else dados_list[0],
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
        "paginas_processadas": pages,
        "pdf_origem": pdf_path,
    }
    json_path.write_text(json.dumps(resultado_completo, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Retorna só resumo
    total_contas = sum(len(d.get("contas", [])) if isinstance(d, dict) else 0 for d in dados_list)
    resumo = {
        "arquivo_dados": str(json_path.resolve()),
        "tipo": tipo,
        "total_contas": total_contas,
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
        "paginas_processadas": pages,
        "pdf_origem": pdf_path,
    }
    return json.dumps(resumo, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool 3 — Exportar planilha (aceita arquivos JSON ou dados diretos)
# ---------------------------------------------------------------------------

@mcp.tool()
def exportar_planilha(empresa: str, arquivos_json: list[str] | None = None, demonstracoes: list[dict] | None = None) -> str:
    """Gera um arquivo Excel (.xlsx) a partir de demonstracoes extraidas.

    Pode receber os caminhos dos arquivos JSON gerados por extrair_demonstracao,
    ou dados de demonstracoes diretamente.

    Args:
        empresa: Nome da empresa.
        arquivos_json: Lista de caminhos de arquivos JSON gerados por extrair_demonstracao.
        demonstracoes: Lista de dicts, cada um com {tipo, periodo, dados}. Alternativa a arquivos_json.

    Returns:
        JSON com o caminho do arquivo Excel gerado.
    """
    from app.services.exporter import export_excel_multi

    if arquivos_json:
        demonstracoes = []
        for arq in arquivos_json:
            with open(arq, "r", encoding="utf-8") as f:
                data = json.load(f)
            dados = data["dados"]
            if isinstance(dados, list):
                demonstracoes.extend([{"tipo": data["tipo"], "dados": d} for d in dados])
            else:
                demonstracoes.append({"tipo": data["tipo"], "dados": dados})
    elif not demonstracoes:
        return json.dumps({"erro": "Forneça arquivos_json ou demonstracoes."})

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"{empresa.replace(' ', '_')}_{timestamp}.xlsx"
    output_path = OUTPUT_DIR / nome_arquivo

    caminho = export_excel_multi(
        demonstracoes=demonstracoes,
        empresa=empresa,
        output_path=output_path,
    )

    return _excel_response(caminho, {"empresa": empresa})


# ---------------------------------------------------------------------------
# Tool 5 — Planilhar (pipeline completo: classificar → extrair → exportar)
# ---------------------------------------------------------------------------

def _processar_pdf(pdf_path: str, modelo: str):
    """Classifica e extrai um PDF. Retorna (class_result, demos, resultados, custo)."""
    from app.services.classifier import classificar

    class_result = classificar(pdf_path, model=modelo)
    custo = class_result.get("custo_usd", 0)
    demos = []
    resultados = []

    for demo in class_result.get("demonstracoes", []):
        tipo = demo["tipo"]
        paginas = demo.get("paginas")
        periodo = demo.get("periodo", "")

        dados_list, validacoes, custo_ext, pages = _extrair_e_formatar(
            pdf_path, tipo, paginas, modelo
        )
        custo += custo_ext

        for dados in dados_list:
            demos.append({"tipo": tipo, "periodo": periodo, "dados": dados})

        resultados.append({
            "pdf": Path(pdf_path).name,
            "tipo": tipo,
            "periodo": periodo,
            "total_contas": sum(len(d.get("contas", [])) if isinstance(d, dict) else 0 for d in dados_list),
            "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
            "custo_usd": custo_ext,
        })

    return class_result, demos, resultados, custo


@mcp.tool()
def planilhar(pdf_paths: list[str], modelo: str = "gemini-2.5-flash") -> str:
    """Pipeline completo: classifica, extrai e exporta demonstracoes de um ou mais PDFs para Excel.

    Processa PDFs em paralelo (1 key por PDF via round-robin) sem devolver dados grandes ao Claude.

    Args:
        pdf_paths: Lista de caminhos absolutos dos PDFs.
        modelo: Modelo de IA a usar (default: gemini-2.5-flash).

    Returns:
        JSON com caminho do Excel gerado, resumo por arquivo e custo total.
    """
    from app.services.exporter import export_excel_multi

    for p in pdf_paths:
        if not Path(p).is_file():
            return json.dumps({"erro": f"Arquivo não encontrado: {p}"})

    todas_demonstracoes = []
    todos_resultados = []
    empresa = None
    custo_total = 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pdf_paths)) as executor:
        futures = {
            executor.submit(_processar_pdf, pdf_path, modelo): pdf_path
            for pdf_path in pdf_paths
        }
        for future in concurrent.futures.as_completed(futures):
            class_result, demos, resultados, custo = future.result()
            if not empresa:
                empresa = class_result.get("empresa", "Empresa")
            todas_demonstracoes.extend(demos)
            todos_resultados.extend(resultados)
            custo_total += custo

    todas_demonstracoes.sort(key=lambda d: d.get("periodo", ""))
    todos_resultados.sort(key=lambda r: r.get("periodo", ""))

    pdf_dir = Path(pdf_paths[0]).parent
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"{empresa.replace(' ', '_')}_{timestamp}.xlsx"
    output_path = pdf_dir / nome_arquivo

    caminho = export_excel_multi(
        demonstracoes=todas_demonstracoes,
        empresa=empresa,
        output_path=output_path,
    )

    return _excel_response(caminho, {
        "empresa": empresa,
        "total_pdfs": len(pdf_paths),
        "resumo": todos_resultados,
        "custo_total_usd": round(custo_total, 6),
    })


# ---------------------------------------------------------------------------
# Tool 4 — Estimar custo de processamento
# ---------------------------------------------------------------------------

@mcp.tool()
def estimar_custo_processamento(
    total_paginas: int,
    modelo_classificador: str = "gemini-2.5-flash",
    modelo_extrator: str = "gemini-2.5-flash",
) -> str:
    """Estima o custo de processar um PDF com base no numero de paginas.

    Args:
        total_paginas: Numero total de paginas do documento.
        modelo_classificador: Modelo usado na classificacao.
        modelo_extrator: Modelo usado na extracao e formatacao.

    Returns:
        JSON com custo estimado por etapa (classifier, extractor, formatter) e total.
    """
    from app.config import estimar_custo

    models = {
        "classifier": modelo_classificador,
        "extractor": modelo_extrator,
        "formatter": modelo_extrator,
    }

    resultado = estimar_custo(total_paginas, models)
    return json.dumps(resultado, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
