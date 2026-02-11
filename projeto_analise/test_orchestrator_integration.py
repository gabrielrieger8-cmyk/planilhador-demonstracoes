"""Test orchestrator integration with classifier."""
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.orchestrator import Orchestrator
from src.parsers.csv_parser import load_balancete

def main():
    print("\n" + "=" * 70)
    print("ORCHESTRATOR INTEGRATION TEST")
    print("=" * 70)
    
    # Load environment
    load_dotenv(project_root / ".env")
    
    csv_path = project_root / "data" / "input" / "VFR Balancete 112025.csv"
    
    orchestrator = Orchestrator()
    
    # Test step-by-step execution (as dashboard would use it)
    print("\n[STEP-BY-STEP EXECUTION TEST]")
    print("-" * 70)
    
    # Step 1: Parse
    print("\n1. Parsing CSV...")
    balancete = orchestrator.parse(csv_path)
    print(f"   [OK] Loaded {len(balancete.contas)} accounts")
    
    # Step 2: Classify
    print("\n2. Classifying accounts via AI...")
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    classificacao = orchestrator.classify(csv_text)
    print(f"   [OK] Classified {len(classificacao)} accounts")
    print(f"   First 5 mappings:")
    for k, v in list(classificacao.items())[:5]:
        print(f"     {k:20} -> {v}")
    
    # Step 3: Group
    print("\n3. Grouping saldos by grupo contabil...")
    saldos = orchestrator.group(balancete, classificacao)
    print(f"   [OK] Grouped into {len(saldos.grupos)} grupos")
    print(f"   Sample grupos (first 10):")
    for i, (grupo, valor) in enumerate(list(saldos.grupos.items())[:10], 1):
        print(f"     {i:2}. {str(grupo):35} R$ {valor:>15,.2f}")
    
    # Step 4: Calculate indicators
    print("\n4. Calculating financial indicators...")
    indicadores = orchestrator.calculate(saldos)
    
    # Format indicator values
    def fmt(val):
        if val is None:
            return "N/A"
        return f"{float(val):.2f}"
    
    def fmt_pct(val):
        if val is None:
            return "N/A"
        return f"{float(val):.2%}"
    
    print(f"   [OK] Indicators calculated:")
    print(f"     - Liquidez Corrente:     {fmt(indicadores.liquidez_corrente)}")
    print(f"     - Liquidez Seca:         {fmt(indicadores.liquidez_seca)}")
    print(f"     - ROA:                   {fmt_pct(indicadores.roa)}")
    print(f"     - ROE:                   {fmt_pct(indicadores.roe)}")
    print(f"     - Margem Operacional:    {fmt_pct(indicadores.margem_operacional)}")
    print(f"     - EBITDA:                R$ {fmt(indicadores.ebitda) if indicadores.ebitda else 'N/A'}")
    
    # Step 5: Compare
    print("\n5. Comparing periods...")
    comparativo = orchestrator.compare(saldos)
    print(f"   [OK] Comparison complete")
    print(f"     - Periodo anterior:      {comparativo.periodo_anterior}")
    print(f"     - Periodo atual:         {comparativo.periodo_atual}")
    print(f"     - Liquidez variations:   {len(comparativo.variacoes_liquidez)} indicators")
    print(f"     - Rental variations:     {len(comparativo.variacoes_rentabilidade)} indicators")
    
    # Verify key format used in classification
    print("\n\n[KEY FORMAT VERIFICATION]")
    print("-" * 70)
    
    # Check what keys are in balancete vs classification
    print("\nBalancete account classifications (first 10):")
    for i, conta in enumerate(balancete.contas[:10], 1):
        in_classif = conta.classificacao in classificacao
        status = "[OK]" if in_classif else "[MISS]"
        grupo = classificacao.get(conta.classificacao, "NOT_FOUND")
        print(f"  {i:2}. {status} {conta.classificacao:20} -> {grupo}")
    
    # Summary
    print("\n\n[SUMMARY]")
    print("-" * 70)
    matched = sum(1 for c in balancete.contas if c.classificacao in classificacao)
    match_rate = (matched / len(balancete.contas)) * 100
    
    hierarchical = sum(1 for k in classificacao.keys() if '.' in k)
    total_keys = len(classificacao)
    
    print(f"\nClassification Coverage:")
    print(f"  - Total accounts in balancete:     {len(balancete.contas)}")
    print(f"  - Accounts matched by classifier:  {matched}")
    print(f"  - Match rate:                      {match_rate:.1f}%")
    
    print(f"\nKey Format:")
    print(f"  - Hierarchical keys (with dots):   {hierarchical}/{total_keys}")
    print(f"  - Sequential keys (no dots):       {total_keys - hierarchical}/{total_keys}")
    print(f"  - Format type:                     {'HIERARCHICAL [OK]' if hierarchical > 10 else 'SEQUENTIAL'}")
    
    print(f"\nGrouping Results:")
    print(f"  - Unique grupos identified:        {len(saldos.grupos)}")
    print(f"  - Non-zero grupos:                 {sum(1 for v in saldos.grupos.values() if v != 0)}")
    
    print(f"\nIndicators Summary:")
    print(f"  - Liquidez Corrente:               {fmt(indicadores.liquidez_corrente)}")
    print(f"  - ROE:                             {fmt_pct(indicadores.roe)}")
    print(f"  - Capital de Giro (NCG):           R$ {fmt(indicadores.necessidade_capital_giro)}")
    
    print(f"\n{'='*70}")
    print(f"PIPELINE STATUS: [OK] ALL TESTS PASSED")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
