"""CLI standalone para o Planilhador de Demonstrações.

Uso:
    python cli.py planilhar PDF1 [PDF2 ...] [--modelo gemini-2.5-flash]
    python cli.py classificar PDF [--modelo gemini-2.5-flash]
    python cli.py extrair TIPO PDF [--paginas 1,2,3] [--modelo gemini-2.5-flash]
    python cli.py exportar EMPRESA JSON1 [JSON2 ...]
    python cli.py custo TOTAL_PAGINAS [--modelo-classificador X] [--modelo-extrator Y]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

# Garante imports do pacote app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Funções core do pipeline
# ---------------------------------------------------------------------------

def extrair_e_formatar(pdf_path: str, tipo: str, paginas=None, modelo="gemini-2.5-flash"):
    """Executa extração + formatação + validação. Retorna (dados_list, validacoes, custo, pages)."""
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

    nome = Path(pdf_path).name
    logging.info("Extraindo %s de: %s", tipo, nome)
    t0 = time.time()

    if tipo == "balancete":
        gemini_result = extrair_balancete(pdf_path, paginas=paginas, model=modelo)
    elif tipo in ("dre", "balanco_patrimonial"):
        gemini_result = extrair_demo_gemini(pdf_path, tipo=tipo, paginas=paginas, model=modelo)
    else:
        raise ValueError(f"Tipo invalido: {tipo}. Use balancete, dre ou balanco_patrimonial.")

    logging.info("Formatando %s de: %s (extracao: %.1fs)", tipo, nome, time.time() - t0)

    if tipo == "balancete":
        dados = formatar_balancete(gemini_result.text)
        dados_list = [dados]
    elif tipo == "dre":
        dados_list = formatar_dre_multi(gemini_result.text)
    else:
        dados_list = formatar_balanco_multi(gemini_result.text)

    logging.info("Validando %s de: %s", tipo, nome)
    validacoes = []
    for d in dados_list:
        vr = validate(d, tipo)
        validacoes.append({
            "passed": vr.passed,
            "errors": vr.errors,
            "warnings": vr.warnings,
            "details": vr.details,
        })
    status = "OK" if all(v["passed"] for v in validacoes) else "WARN"
    logging.info("[%s] Validacao %s de %s concluida", status, tipo, nome)

    return dados_list, validacoes, gemini_result.custo_usd, gemini_result.pages_processed


def processar_pdf(pdf_path: str, modelo: str):
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

        dados_list, validacoes, custo_ext, pages = extrair_e_formatar(
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


# ---------------------------------------------------------------------------
# Comandos CLI
# ---------------------------------------------------------------------------

def cmd_planilhar(args):
    from app.services.exporter import export_excel_multi

    pdf_paths = args.pdfs
    modelo = args.modelo

    for p in pdf_paths:
        if not Path(p).is_file():
            print(json.dumps({"erro": f"Arquivo nao encontrado: {p}"}))
            sys.exit(1)

    t0 = time.time()
    todas_demos = []
    todos_resultados = []
    empresa = None
    custo_total = 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pdf_paths)) as ex:
        futures = {ex.submit(processar_pdf, p, modelo): p for p in pdf_paths}
        for fut in concurrent.futures.as_completed(futures):
            class_result, demos, resultados, custo = fut.result()
            if not empresa:
                empresa = class_result.get("empresa", "Empresa")
            todas_demos.extend(demos)
            todos_resultados.extend(resultados)
            custo_total += custo

    todas_demos.sort(key=lambda d: d.get("periodo", ""))
    todos_resultados.sort(key=lambda r: r.get("periodo", ""))

    pdf_dir = Path(pdf_paths[0]).parent
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"{empresa.replace(' ', '_')}_{timestamp}.xlsx"
    output_path = pdf_dir / nome

    logging.info("Exportando Excel: %s (%d demonstracoes)", nome, len(todas_demos))
    caminho = export_excel_multi(
        demonstracoes=todas_demos, empresa=empresa, output_path=output_path,
    )
    logging.info("Pipeline concluido em %.1fs — Excel: %s", time.time() - t0, caminho)

    result = {
        "arquivo": str(caminho.resolve()) if hasattr(caminho, 'resolve') else str(caminho),
        "empresa": empresa,
        "total_pdfs": len(pdf_paths),
        "resumo": todos_resultados,
        "custo_total_usd": round(custo_total, 6),
        "tempo_segundos": round(time.time() - t0, 1),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def cmd_classificar(args):
    from app.services.classifier import classificar
    resultado = classificar(args.pdf, model=args.modelo)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


def cmd_extrair(args):
    paginas = [int(p) for p in args.paginas.split(",")] if args.paginas else None
    dados_list, validacoes, custo, pages = extrair_e_formatar(
        args.pdf, args.tipo, paginas, args.modelo
    )

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(args.pdf).stem.replace(" ", "_")
    json_path = OUTPUT_DIR / f"{base}_{args.tipo}_{timestamp}.json"

    resultado = {
        "tipo": args.tipo,
        "dados": dados_list if len(dados_list) > 1 else dados_list[0],
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
        "paginas_processadas": pages,
        "pdf_origem": args.pdf,
    }
    json_path.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    resumo = {
        "arquivo_dados": str(json_path.resolve()),
        "tipo": args.tipo,
        "total_contas": sum(
            len(d.get("contas", [])) if isinstance(d, dict) else 0 for d in dados_list
        ),
        "validacao": validacoes if len(validacoes) > 1 else validacoes[0],
        "custo_extracao_usd": custo,
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2, default=str))


def cmd_exportar(args):
    from app.services.exporter import export_excel_multi

    demonstracoes = []
    for arq in args.jsons:
        with open(arq, "r", encoding="utf-8") as f:
            data = json.load(f)
        dados = data["dados"]
        if isinstance(dados, list):
            demonstracoes.extend([{"tipo": data["tipo"], "dados": d} for d in dados])
        else:
            demonstracoes.append({"tipo": data["tipo"], "dados": dados})

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{args.empresa.replace(' ', '_')}_{timestamp}.xlsx"

    caminho = export_excel_multi(
        demonstracoes=demonstracoes, empresa=args.empresa, output_path=output_path,
    )
    result = {
        "arquivo": str(caminho.resolve()) if hasattr(caminho, 'resolve') else str(caminho),
        "empresa": args.empresa,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def cmd_custo(args):
    from app.config import estimar_custo

    models = {
        "classifier": args.modelo_classificador,
        "extractor": args.modelo_extrator,
        "formatter": args.modelo_extrator,
    }
    resultado = estimar_custo(args.total_paginas, models)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Planilhador de Demonstracoes CLI")
    sub = parser.add_subparsers(dest="comando", required=True)

    # planilhar
    p = sub.add_parser("planilhar", help="Pipeline completo: classificar -> extrair -> Excel")
    p.add_argument("pdfs", nargs="+", help="Caminhos dos PDFs")
    p.add_argument("--modelo", default="gemini-2.5-flash")
    p.set_defaults(func=cmd_planilhar)

    # classificar
    p = sub.add_parser("classificar", help="Classificar documento PDF")
    p.add_argument("pdf", help="Caminho do PDF")
    p.add_argument("--modelo", default="gemini-2.5-flash")
    p.set_defaults(func=cmd_classificar)

    # extrair
    p = sub.add_parser("extrair", help="Extrair demonstracao de PDF")
    p.add_argument("tipo", choices=["balancete", "dre", "balanco_patrimonial"])
    p.add_argument("pdf", help="Caminho do PDF")
    p.add_argument("--paginas", default=None, help="Paginas (ex: 1,2,3)")
    p.add_argument("--modelo", default="gemini-2.5-flash")
    p.set_defaults(func=cmd_extrair)

    # exportar
    p = sub.add_parser("exportar", help="Exportar JSONs para Excel")
    p.add_argument("empresa", help="Nome da empresa")
    p.add_argument("jsons", nargs="+", help="Caminhos dos JSONs")
    p.set_defaults(func=cmd_exportar)

    # custo
    p = sub.add_parser("custo", help="Estimar custo de processamento")
    p.add_argument("total_paginas", type=int, help="Total de paginas")
    p.add_argument("--modelo-classificador", default="gemini-2.5-flash")
    p.add_argument("--modelo-extrator", default="gemini-2.5-flash")
    p.set_defaults(func=cmd_custo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
