"""MCP Server para o Planilhador de Demonstrações.

Wrapper fino sobre cli.py — expõe as mesmas funções como ferramentas MCP
para uso no Claude Desktop App.

Todas as operações longas (extração, pipeline) rodam em background.
O Claude chama iniciar_* e depois consulta_resultado até completar.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP

from cli import (
    extrair_e_formatar,
    processar_pdf,
    OUTPUT_DIR,
)

mcp = FastMCP("mirar-planilhador")

# ---------------------------------------------------------------------------
# Job store — guarda resultados de operações em background
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}


def _run_in_background(job_id: str, fn, *args, **kwargs):
    """Executa fn em thread separada e salva resultado em _jobs."""
    def _worker():
        try:
            result = fn(*args, **kwargs)
            _jobs[job_id]["status"] = "concluido"
            _jobs[job_id]["resultado"] = result
        except Exception as e:
            _jobs[job_id]["status"] = "erro"
            _jobs[job_id]["resultado"] = {
                "erro": str(e),
                "traceback": traceback.format_exc(),
            }

    _jobs[job_id] = {"status": "processando", "resultado": None}
    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Tool: consultar resultado de qualquer operação
# ---------------------------------------------------------------------------

@mcp.tool()
def consultar_resultado(job_id: str) -> str:
    """Consulta o resultado de uma operacao em andamento.

    Chame repetidamente ate o status ser 'concluido' ou 'erro'.

    Args:
        job_id: ID retornado por iniciar_planilhar ou iniciar_extracao.
    """
    job = _jobs.get(job_id)
    if not job:
        return json.dumps({"erro": f"Job {job_id} não encontrado."})

    if job["status"] == "processando":
        return json.dumps({"status": "processando", "job_id": job_id})

    return json.dumps({
        "status": job["status"],
        "job_id": job_id,
        "resultado": job["resultado"],
    }, ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool: classificar (síncrono — é rápido)
# ---------------------------------------------------------------------------

@mcp.tool()
def classificar_documento(pdf_path: str, modelo: str = "gemini-2.5-flash") -> str:
    """Classifica um PDF contabil e identifica as demonstracoes presentes.

    Esta operacao e rapida e retorna o resultado diretamente.

    Args:
        pdf_path: Caminho absoluto para o arquivo PDF.
        modelo: Modelo de IA a usar.
    """
    from app.services.classifier import classificar
    return json.dumps(classificar(pdf_path, model=modelo), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool: iniciar pipeline completo (assíncrono)
# ---------------------------------------------------------------------------

def _pipeline_completo(pdf_paths: list[str], modelo: str) -> dict:
    """Executa o pipeline completo e retorna dict com resultado."""
    import concurrent.futures
    import datetime
    import time
    from pathlib import Path
    from app.services.exporter import export_excel_multi

    t0 = time.time()
    todas_demos, todos_resultados = [], []
    empresa, custo_total = None, 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pdf_paths)) as ex:
        futures = {ex.submit(processar_pdf, p, modelo): p for p in pdf_paths}
        for fut in concurrent.futures.as_completed(futures):
            cr, demos, res, custo = fut.result()
            if not empresa:
                empresa = cr.get("empresa", "Empresa")
            todas_demos.extend(demos)
            todos_resultados.extend(res)
            custo_total += custo

    todas_demos.sort(key=lambda d: d.get("periodo", ""))
    todos_resultados.sort(key=lambda r: r.get("periodo", ""))

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(pdf_paths[0]).parent / f"{empresa.replace(' ', '_')}_{ts}.xlsx"
    caminho = export_excel_multi(demonstracoes=todas_demos, empresa=empresa, output_path=output_path)

    return {
        "arquivo": str(caminho.resolve()) if hasattr(caminho, "resolve") else str(caminho),
        "empresa": empresa,
        "total_pdfs": len(pdf_paths),
        "resumo": todos_resultados,
        "custo_total_usd": round(custo_total, 6),
        "tempo_segundos": round(time.time() - t0, 1),
    }


@mcp.tool()
def iniciar_planilhar(pdf_paths: list[str], modelo: str = "gemini-2.5-flash") -> str:
    """Inicia o pipeline completo em background: classifica, extrai e exporta PDFs para Excel.

    Retorna imediatamente um job_id. Use consultar_resultado(job_id) para
    verificar quando terminou (chame a cada 10-15 segundos).

    Args:
        pdf_paths: Lista de caminhos absolutos dos PDFs.
        modelo: Modelo de IA (default: gemini-2.5-flash).
    """
    from pathlib import Path

    for p in pdf_paths:
        if not Path(p).is_file():
            return json.dumps({"erro": f"Arquivo não encontrado: {p}"})

    job_id = str(uuid.uuid4())[:8]
    _run_in_background(job_id, _pipeline_completo, pdf_paths, modelo)

    return json.dumps({
        "job_id": job_id,
        "status": "processando",
        "mensagem": f"Pipeline iniciado para {len(pdf_paths)} PDF(s). Use consultar_resultado('{job_id}') para acompanhar.",
    })


# ---------------------------------------------------------------------------
# Tool: iniciar extração (assíncrono)
# ---------------------------------------------------------------------------

def _extrair_e_salvar(pdf_path: str, tipo: str, paginas, modelo: str) -> dict:
    """Extrai, formata, valida e salva em JSON."""
    import datetime
    from pathlib import Path

    dados_list, validacoes, custo, pages = extrair_e_formatar(pdf_path, tipo, paginas, modelo)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(pdf_path).stem.replace(" ", "_")
    json_path = OUTPUT_DIR / f"{base}_{tipo}_{ts}.json"
    json_path.write_text(json.dumps({
        "tipo": tipo,
        "dados": dados_list if len(dados_list) > 1 else dados_list[0],
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
        "paginas_processadas": pages,
        "pdf_origem": pdf_path,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    return {
        "arquivo_dados": str(json_path.resolve()),
        "tipo": tipo,
        "total_contas": sum(len(d.get("contas", [])) if isinstance(d, dict) else 0 for d in dados_list),
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
    }


@mcp.tool()
def iniciar_extracao(
    tipo: str, pdf_path: str, paginas: list[int] | None = None, modelo: str = "gemini-2.5-flash",
) -> str:
    """Inicia a extracao de uma demonstracao em background.

    Retorna imediatamente um job_id. Use consultar_resultado(job_id) para
    verificar quando terminou.

    Args:
        tipo: "balancete", "dre" ou "balanco_patrimonial".
        pdf_path: Caminho absoluto para o PDF.
        paginas: Paginas a processar (1-indexed). None = todas.
        modelo: Modelo de IA.
    """
    job_id = str(uuid.uuid4())[:8]
    _run_in_background(job_id, _extrair_e_salvar, pdf_path, tipo, paginas, modelo)

    return json.dumps({
        "job_id": job_id,
        "status": "processando",
        "mensagem": f"Extração de {tipo} iniciada. Use consultar_resultado('{job_id}') para acompanhar.",
    })


# ---------------------------------------------------------------------------
# Tool: exportar (síncrono — é rápido)
# ---------------------------------------------------------------------------

@mcp.tool()
def exportar_planilha(empresa: str, arquivos_json: list[str]) -> str:
    """Gera Excel a partir de JSONs gerados por extrair_demonstracao.

    Esta operacao e rapida e retorna o resultado diretamente.

    Args:
        empresa: Nome da empresa.
        arquivos_json: Lista de caminhos de arquivos JSON.
    """
    import datetime
    from app.services.exporter import export_excel_multi

    demonstracoes = []
    for arq in arquivos_json:
        with open(arq, "r", encoding="utf-8") as f:
            data = json.load(f)
        dados = data["dados"]
        if isinstance(dados, list):
            demonstracoes.extend([{"tipo": data["tipo"], "dados": d} for d in dados])
        else:
            demonstracoes.append({"tipo": data["tipo"], "dados": dados})

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{empresa.replace(' ', '_')}_{ts}.xlsx"
    caminho = export_excel_multi(demonstracoes=demonstracoes, empresa=empresa, output_path=output_path)

    return json.dumps({
        "arquivo": str(caminho.resolve()) if hasattr(caminho, "resolve") else str(caminho),
        "empresa": empresa,
    }, ensure_ascii=False, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
