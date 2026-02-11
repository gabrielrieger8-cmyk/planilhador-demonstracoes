"""Ponto de entrada do sistema de análise econômico-financeira.

Uso:
    python main.py                                    # analisa todos CSVs em data/input/
    python main.py balancete.csv                      # analisa um arquivo específico
    python main.py balancete.csv --model claude       # usa Claude ao invés de Gemini
    python main.py balancete.csv --output markdown    # apenas Markdown (sem PDF)
"""

import argparse
import sys
import time
from pathlib import Path

from src.orchestrator import AIProvider, AnalysisResult, Orchestrator, OutputFormat
from src.utils.config import BALANCETES_OUTPUT_DIR, INPUT_DIR


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Análise econômico-financeira de balancetes",
    )
    parser.add_argument(
        "files", nargs="*",
        help="Arquivo(s) CSV para analisar (padrão: todos em data/input/)",
    )
    parser.add_argument(
        "--model", choices=["gemini", "claude"], default="gemini",
        help="Modelo de IA para narrativa (padrão: gemini)",
    )
    parser.add_argument(
        "--output", choices=["markdown", "pdf", "all"], default="all",
        help="Formato de saída (padrão: all)",
    )
    parser.add_argument(
        "--from-extractor", action="store_true",
        help="Busca CSVs na pasta output do projeto extrator",
    )

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  ANÁLISE ECONÔMICO-FINANCEIRA")
    print("=" * 60)

    # Determina arquivos a processar
    if args.files:
        csvs = []
        for f in args.files:
            p = Path(f)
            if not p.exists() and not p.is_absolute():
                p = INPUT_DIR / p
            csvs.append(p)
    elif args.from_extractor and BALANCETES_OUTPUT_DIR.exists():
        csvs = list(BALANCETES_OUTPUT_DIR.glob("*.csv"))
    else:
        csvs = list(INPUT_DIR.glob("*.csv"))

    if not csvs:
        print(f"\n  Nenhum CSV encontrado.")
        print(f"  Coloque os CSVs em: {INPUT_DIR}")
        print(f"  Ou use: python main.py --from-extractor\n")
        return

    print(f"\n  Modelo IA: {args.model.upper()}")
    print(f"  Encontrados: {len(csvs)} arquivo(s)\n")
    for i, c in enumerate(csvs, 1):
        print(f"    {i}. {c.name}")
    print()

    orch = Orchestrator(ai_provider=args.model)
    output_format = OutputFormat(args.output)

    total_start = time.time()
    results: list[AnalysisResult] = []

    for i, csv_path in enumerate(csvs, 1):
        print("-" * 60)
        print(f"  [{i}/{len(csvs)}] {csv_path.name}")
        print("-" * 60)
        result = orch.analyze(csv_path, output_format=output_format)
        results.append(result)

    total_time = time.time() - total_start

    # Resumo
    print()
    print("=" * 60)
    print("  RESULTADOS")
    print("=" * 60)

    ok = sum(1 for r in results if r.success)
    erros = len(results) - ok
    custo_total = sum(r.estimated_cost for r in results)

    for r in results:
        name = Path(r.file_path).name
        if r.success:
            print(f"\n  [OK] {name}")
            print(f"       Tempo: {r.processing_time:.2f}s")
            print(f"       Custo IA: ${r.estimated_cost:.4f}")
            if r.indicadores:
                lc = r.indicadores.liquidez_corrente
                print(f"       Liquidez Corrente: {lc or 'N/D'}")
            print(f"       Saída:")
            for f in r.output_files:
                print(f"         -> {Path(f).name}")
        else:
            print(f"\n  [ERRO] {name}")
            print(f"         {r.error}")

    print()
    print("-" * 60)
    print(f"  Total: {len(results)} arquivo(s) | OK: {ok} | Erros: {erros}")
    print(f"  Tempo total: {total_time:.2f}s | Custo IA: ${custo_total:.4f}")
    print("-" * 60)
    print()


if __name__ == "__main__":
    main()
