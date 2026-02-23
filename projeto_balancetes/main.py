"""Ponto de entrada do sistema de processamento de PDFs financeiros.

Uso:
    python main.py                          # processa todos os PDFs em data/input/
    python main.py balancete.pdf            # processa um arquivo específico
    python main.py data/input/balancete.pdf # caminho completo tambem funciona
"""

import sys
import time
from pathlib import Path

from controladoria_core.utils.config import configure as _configure
_configure(project_root=Path(__file__).parent)

from controladoria_core.orchestrator import Orchestrator, OutputFormat
from controladoria_core.utils.config import INPUT_DIR


def main() -> None:
    print()
    print("=" * 60)
    print("  PROCESSADOR DE PDFs FINANCEIROS")
    print("=" * 60)

    orch = Orchestrator()

    # Se passou um argumento, processa esse arquivo
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not pdf_path.exists() and not pdf_path.is_absolute():
            pdf_path = INPUT_DIR / pdf_path
        pdfs = [pdf_path]
    else:
        pdfs = list(INPUT_DIR.glob("*.pdf"))

    if not pdfs:
        print(f"\n  Nenhum PDF encontrado em: {INPUT_DIR}")
        print("  Coloque seus PDFs nessa pasta e execute novamente.\n")
        return

    print(f"\n  Encontrados: {len(pdfs)} PDF(s)\n")
    for i, p in enumerate(pdfs, 1):
        print(f"    {i}. {p.name}")
    print()

    total_start = time.time()
    results = []

    for i, pdf in enumerate(pdfs, 1):
        print("-" * 60)
        print(f"  [{i}/{len(pdfs)}] {pdf.name}")
        print("-" * 60)
        result = orch.process(
            pdf,
            output_format=OutputFormat.CSV,
        )
        results.append(result)

    total_time = time.time() - total_start

    # Resumo final
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
            print(f"       Tempo:  {r.processing_time:.2f}s")
            print(f"       Custo:  ${r.estimated_cost:.4f}")
            print(f"       Saida:")
            for f in r.output_files:
                print(f"         -> {Path(f).name}")
        else:
            print(f"\n  [ERRO] {name}")
            print(f"         {r.error}")

    print()
    print("-" * 60)
    print(f"  Total: {len(results)} arquivo(s) | OK: {ok} | Erros: {erros}")
    print(f"  Tempo total: {total_time:.2f}s | Custo total: ${custo_total:.4f}")
    print("-" * 60)
    print()


if __name__ == "__main__":
    main()
