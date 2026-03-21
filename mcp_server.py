"""MCP Server para o Planilhador de Demonstracoes.

Expoe as funcoes standalone do pipeline como ferramentas MCP:
  - classificar_documento
  - extrair_demonstracao
  - exportar_planilha
  - estimar_custo_processamento
"""

from __future__ import annotations

import base64
import concurrent.futures
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Garante que o pacote 'app' seja importavel
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

mcp = FastMCP("mirar-planilhador")
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


IS_REMOTE = os.environ.get("MCP_TRANSPORT", "stdio") != "stdio"


def _excel_response(caminho: Path, extra: dict) -> str:
    """Retorna JSON com o resultado. No modo remoto inclui o Excel em base64."""
    result = {"arquivo": str(caminho.resolve()), **extra}
    if IS_REMOTE:
        with open(caminho, "rb") as f:
            result["excel_base64"] = base64.b64encode(f.read()).decode()
        result["filename"] = caminho.name
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def _resolve_pdf(pdf_path: str | None = None, pdf_base64: str | None = None, filename: str = "documento.pdf") -> str:
    """Resolve um PDF de path local ou base64 para um path no disco."""
    if pdf_path and os.path.isfile(pdf_path):
        return pdf_path
    if pdf_base64:
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", prefix=filename.replace(".pdf", "_"), delete=False, dir=OUTPUT_DIR)
        tmp.write(base64.b64decode(pdf_base64))
        tmp.close()
        return tmp.name
    if pdf_path:
        return pdf_path  # Tenta usar o path mesmo assim
    raise ValueError("Forneça pdf_path ou pdf_base64.")


# ---------------------------------------------------------------------------
# Tool 1 — Classificar documento
# ---------------------------------------------------------------------------

@mcp.tool()
def classificar_documento(pdf_path: str = "", pdf_base64: str = "", modelo: str = "gemini-2.5-flash") -> str:
    """Classifica um PDF contabil e identifica as demonstracoes presentes.

    Args:
        pdf_path: Caminho absoluto para o arquivo PDF (uso local).
        pdf_base64: Conteudo do PDF em base64 (uso remoto).
        modelo: Modelo de IA a usar (ex: gemini-2.5-flash, gemini-2.0-flash).

    Returns:
        JSON com empresa, demonstracoes encontradas e custo estimado.
    """
    from app.services.classifier import classificar

    resolved = _resolve_pdf(pdf_path or None, pdf_base64 or None)
    resultado = classificar(resolved, model=modelo)
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
    pdf_path: str = "",
    pdf_base64: str = "",
    paginas: list[int] | None = None,
    modelo: str = "gemini-2.5-flash",
) -> str:
    """Extrai, formata e valida uma demonstracao financeira de um PDF.

    Salva os dados completos em arquivo JSON e retorna apenas um resumo
    com caminho do arquivo, validacao e custo (sem carregar os dados no contexto).

    Args:
        tipo: Tipo da demonstracao — "balancete", "dre" ou "balanco_patrimonial".
        pdf_path: Caminho absoluto para o arquivo PDF (uso local).
        pdf_base64: Conteudo do PDF em base64 (uso remoto).
        paginas: Lista de paginas (1-indexed) a processar. None = todas.
        modelo: Modelo de IA a usar na extracao.

    Returns:
        JSON com caminho do arquivo de dados, resumo da validacao e custo.
    """
    resolved = _resolve_pdf(pdf_path or None, pdf_base64 or None)
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
def planilhar(pdf_paths: list[str] | None = None, pdfs_base64: list[dict] | None = None, modelo: str = "gemini-2.5-flash") -> str:
    """Pipeline completo: classifica, extrai e exporta demonstracoes de um ou mais PDFs para Excel.

    Processa PDFs em paralelo (1 key por PDF via round-robin) sem devolver dados grandes ao Claude.

    Args:
        pdf_paths: Lista de caminhos absolutos dos PDFs (uso local).
        pdfs_base64: Lista de dicts {filename, base64} com os PDFs (uso remoto).
        modelo: Modelo de IA a usar (default: gemini-2.5-flash).

    Returns:
        JSON com caminho do Excel gerado, resumo por arquivo e custo total.
    """
    from app.services.exporter import export_excel_multi

    # Resolve PDFs (paths locais ou base64)
    if pdfs_base64:
        pdf_paths = [_resolve_pdf(pdf_base64=p["base64"], filename=p.get("filename", f"doc_{i}.pdf")) for i, p in enumerate(pdfs_base64)]
    if not pdf_paths:
        return json.dumps({"erro": "Forneça pdf_paths ou pdfs_base64."})

    todas_demonstracoes = []
    todos_resultados = []
    empresa = None
    custo_total = 0.0

    # Processa PDFs em paralelo — cada thread pega keys do pool round-robin
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

    # Ordena por periodo para manter ordem cronologica no Excel
    todas_demonstracoes.sort(key=lambda d: d.get("periodo", ""))
    todos_resultados.sort(key=lambda r: r.get("periodo", ""))

    # Exportar Excel: mesma pasta dos PDFs (local) ou OUTPUT_DIR (remoto)
    pdf_dir = Path(pdf_paths[0]).parent
    if pdfs_base64 or str(pdf_dir).startswith(str(OUTPUT_DIR)):
        output_dir = OUTPUT_DIR
    else:
        output_dir = pdf_dir
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_arquivo = f"{empresa.replace(' ', '_')}_{timestamp}.xlsx"
    output_path = output_dir / nome_arquivo

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
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "http":
        import uvicorn
        port = int(os.environ.get("PORT", 8000))
        app = mcp.streamable_http_app()
        uvicorn.run(app, host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    else:
        mcp.run()
