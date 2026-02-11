"""Test script to verify classifier_agent and orchestrator pipeline."""
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.agents.classifier_agent import classify_accounts
from src.parsers.csv_parser import load_balancete

def main():
    print("=" * 70)
    print("CLASSIFIER & ORCHESTRATOR PIPELINE TEST")
    print("=" * 70)
    
    # 1. Load .env file
    print("\n[1/6] Loading .env file...")
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"  [OK] Loaded from: {env_path}")
    else:
        print(f"  [WARN] .env not found at: {env_path}")
    
    # 2. Find CSV file
    print("\n[2/6] Finding CSV file...")
    csv_path = project_root / "data" / "input" / "VFR Balancete 112025.csv"
    if not csv_path.exists():
        print(f"  [ERROR] File not found: {csv_path}")
        return
    print(f"  [OK] Found: {csv_path}")
    
    # 3. Read CSV text
    print("\n[3/6] Reading CSV text...")
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    lines = csv_text.strip().split('\n')
    print(f"  [OK] Read {len(lines)} lines")
    print(f"  First line: {lines[0][:80]}...")
    
    # 4. Call classify_accounts(csv_text)
    print("\n[4/6] Calling classify_accounts()...")
    print("  This will use Claude Sonnet via API - may take 10-30 seconds...")
    classification = classify_accounts(csv_text)
    
    if not classification:
        print("  [ERROR] Classification failed (empty result)")
        print("  Check ANTHROPIC_API_KEY in .env file")
        return
    
    print(f"  [OK] Classified {len(classification)} accounts")
    
    # 5. Check keys format
    print("\n[5/6] Analyzing classification keys...")
    keys = list(classification.keys())[:10]
    print(f"  First 10 keys: {keys}")
    
    # Check if keys contain dots (hierarchical) vs sequential numbers
    has_dots = any('.' in k for k in keys)
    is_numeric_only = all(k.replace('.', '').isdigit() for k in keys)
    
    print(f"\n  Key Analysis:")
    print(f"    - Contains dots (hierarchical like '1.1', '1.1.1'): {has_dots}")
    print(f"    - Numeric only (not sequential 1,2,3...): {is_numeric_only}")
    print(f"    - Key type: {'HIERARCHICAL [OK]' if has_dots else 'SEQUENTIAL'}")
    
    print(f"\n  Sample mappings:")
    for k, v in list(classification.items())[:10]:
        print(f"    {k:15} -> {v}")
    
    # 6. Load balancete and compare
    print("\n[6/6] Loading balancete and comparing...")
    balancete = load_balancete(csv_path)
    print(f"  [OK] Loaded balancete with {len(balancete.contas)} accounts")
    
    print(f"\n  First 10 conta.classificacao values from balancete:")
    for i, conta in enumerate(balancete.contas[:10], 1):
        match_status = "[OK]" if conta.classificacao in classification else "[X]"
        grupo = classification.get(conta.classificacao, "NOT_CLASSIFIED")
        print(f"    {i:2}. {conta.classificacao:15} {match_status}  -> {grupo}")
    
    # Summary
    matched_count = sum(1 for c in balancete.contas if c.classificacao in classification)
    match_rate = (matched_count / len(balancete.contas)) * 100 if balancete.contas else 0
    
    print(f"\n" + "=" * 70)
    print(f"SUMMARY")
    print(f"=" * 70)
    print(f"  Total accounts in balancete: {len(balancete.contas)}")
    print(f"  Classified by AI:            {len(classification)}")
    print(f"  Matched accounts:            {matched_count}")
    print(f"  Match rate:                  {match_rate:.1f}%")
    print(f"  Key format:                  {'Hierarchical (with dots)' if has_dots else 'Sequential'}")
    print(f"\n  Status: {'[OK] PASS' if match_rate > 80 else '[WARN] REVIEW'}")
    print("=" * 70)

if __name__ == "__main__":
    main()
