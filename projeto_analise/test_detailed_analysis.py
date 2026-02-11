"""Detailed analysis of classification results."""
import sys
from pathlib import Path
from collections import Counter
from dotenv import load_dotenv

# Add src to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.agents.classifier_agent import classify_accounts
from src.parsers.csv_parser import load_balancete

def main():
    print("\n" + "=" * 70)
    print("DETAILED CLASSIFICATION ANALYSIS")
    print("=" * 70)
    
    # Load environment
    load_dotenv(project_root / ".env")
    
    # Load data
    csv_path = project_root / "data" / "input" / "VFR Balancete 112025.csv"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    
    print("\n1. CLASSIFICATION DISTRIBUTION")
    print("-" * 70)
    
    classification = classify_accounts(csv_text)
    
    # Count by grupo
    grupo_counts = Counter(classification.values())
    print(f"\nTotal unique classifications: {len(classification)}")
    print(f"\nTop 15 grupos by frequency:\n")
    for grupo, count in grupo_counts.most_common(15):
        print(f"  {grupo:35} {count:3} accounts")
    
    # Load balancete
    balancete = load_balancete(csv_path)
    
    print("\n\n2. HIERARCHICAL KEY STRUCTURE")
    print("-" * 70)
    
    # Analyze key depths
    depth_counts = {}
    for key in classification.keys():
        depth = key.count('.') + 1
        depth_counts[depth] = depth_counts.get(depth, 0) + 1
    
    print("\nClassification key depths (hierarchy levels):\n")
    for depth in sorted(depth_counts.keys()):
        print(f"  Level {depth}: {depth_counts[depth]:3} keys")
    
    # Show examples at each level
    print("\n\n3. SAMPLE CLASSIFICATIONS BY DEPTH")
    print("-" * 70)
    
    for depth in sorted(depth_counts.keys())[:5]:  # First 5 levels
        print(f"\nLevel {depth} examples:")
        examples = [k for k in classification.keys() if k.count('.') + 1 == depth][:3]
        for key in examples:
            grupo = classification[key]
            # Find matching conta
            conta = next((c for c in balancete.contas if c.classificacao == key), None)
            desc = conta.descricao[:40] if conta else "N/A"
            print(f"  {key:20} -> {grupo:30} | {desc}")
    
    print("\n\n4. KEY MATCHING ANALYSIS")
    print("-" * 70)
    
    # Check if all balancete contas are covered
    unclassified = []
    for conta in balancete.contas:
        if conta.classificacao not in classification:
            unclassified.append(conta)
    
    if unclassified:
        print(f"\n[WARN] Found {len(unclassified)} unclassified accounts:")
        for conta in unclassified[:10]:  # Show first 10
            print(f"  {conta.classificacao:20} | {conta.descricao[:40]}")
    else:
        print("\n[OK] All accounts in balancete are classified!")
    
    # Check for extra classifications not in balancete
    balancete_keys = {c.classificacao for c in balancete.contas}
    extra_classifications = set(classification.keys()) - balancete_keys
    
    if extra_classifications:
        print(f"\n[INFO] {len(extra_classifications)} classifications not matched to balancete accounts")
        print("This is normal - AI classifies parent accounts too")
    
    print("\n\n5. SEQUENTIAL vs HIERARCHICAL VERIFICATION")
    print("-" * 70)
    
    keys_sample = list(classification.keys())[:20]
    print("\nFirst 20 classification keys:\n")
    for i, key in enumerate(keys_sample, 1):
        has_dot = '.' in key
        marker = "[HIER]" if has_dot else "[SEQ]"
        print(f"  {i:2}. {marker} {key}")
    
    # Final verdict
    hierarchical_count = sum(1 for k in classification.keys() if '.' in k)
    sequential_count = len(classification) - hierarchical_count
    
    print(f"\n\nFINAL VERDICT:")
    print(f"  Hierarchical keys (with dots): {hierarchical_count}")
    print(f"  Sequential keys (no dots):     {sequential_count}")
    print(f"  Format: {'HIERARCHICAL [OK]' if hierarchical_count > sequential_count else 'SEQUENTIAL'}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
