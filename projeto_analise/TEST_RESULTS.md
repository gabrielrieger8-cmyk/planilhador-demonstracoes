# Classifier Agent and Orchestrator Pipeline Test Results

**Date:** 2026-02-08  
**Test File:** VFR Balancete 112025.csv  
**Total Accounts:** 375

---

## Test Summary

### ✓ ALL TESTS PASSED

The classifier_agent and orchestrator pipeline are working correctly.

---

## Detailed Results

### 1. Classification via AI (Claude Sonnet)

**Status:** ✓ SUCCESS

- **API Response Time:** ~27 seconds
- **Estimated Cost:** $0.095 per request
- **Total Classifications:** 153 unique account classifications
- **Match Rate:** 100.0% (all 375 balancete accounts matched)

### 2. Key Format Analysis

**Format Type:** HIERARCHICAL ✓

- **Hierarchical keys (with dots):** 149/153 (97.4%)
- **Sequential keys (no dots):** 4/153 (2.6%)

**Example Keys:**
```
1               -> ATIVO_TOTAL
1.1             -> ATIVO_CIRCULANTE
1.1.1           -> DISPONIBILIDADES
1.1.10.1        -> DISPONIBILIDADES
1.1.10.100.1    -> DISPONIBILIDADES
1.1.2           -> CLIENTES
```

**Key Depth Distribution:**
- Level 1: 4 keys
- Level 2: 8 keys
- Level 3: 20 keys
- Level 4: 40 keys
- Level 5: 81 keys

### 3. Classification Distribution

**Top 15 Grupos by Frequency:**

| Grupo                          | Count |
|--------------------------------|-------|
| DESPESAS_ADMINISTRATIVAS       | 21    |
| OUTROS_CREDITOS_CP             | 17    |
| OBRIGACOES_TRABALHISTAS        | 15    |
| OBRIGACOES_FISCAIS             | 10    |
| OUTRAS_OBRIGACOES_CP           | 8     |
| DISPONIBILIDADES               | 7     |
| IMOBILIZADO                    | 7     |
| CUSTOS_SERVICOS                | 7     |
| RECEITA_BRUTA                  | 5     |
| RECEITAS_FINANCEIRAS           | 5     |
| PARCELAMENTOS_TRIBUTARIOS      | 4     |
| LUCROS_PREJUIZOS               | 4     |
| CLIENTES                       | 3     |
| DESPESAS_ANTECIPADAS           | 3     |
| INVESTIMENTOS                  | 3     |

### 4. Grouping Results

**Status:** ✓ SUCCESS

- **Unique grupos identified:** 32
- **Non-zero grupos:** 32 (100%)

**Sample Grouped Saldos:**

```
1. ATIVO_TOTAL                     R$    5,050,430.34
2. ATIVO_CIRCULANTE                R$    2,318,795.66
3. DISPONIBILIDADES                R$      142,769.75
4. CLIENTES                        R$      793,130.66
5. OUTROS_CREDITOS_CP              R$    1,362,951.33
6. DESPESAS_ANTECIPADAS            R$       19,943.92
7. ATIVO_NAO_CIRCULANTE            R$    2,731,634.68
8. INVESTIMENTOS                   R$        9,193.90
9. IMOBILIZADO                     R$       41,831.53
10. DEPRECIACAO_AMORTIZACAO        R$      -24,622.24
```

### 5. Indicators Calculation

**Status:** ✓ SUCCESS

**Sample Indicators:**
- Liquidez Corrente: 0.67
- Liquidez Seca: 0.67
- ROA: -7.28%
- ROE: N/A (negative PL)
- Margem Operacional: -60.33%
- EBITDA: R$ -363,664.95
- Capital de Giro (NCG): R$ 441,507.30

### 6. Comparative Analysis

**Status:** ✓ SUCCESS

- Periodo anterior: Saldo Anterior
- Periodo atual: Saldo Atual
- Liquidez variations: 4 indicators tracked
- Rentabilidade variations: 5 indicators tracked

---

## Key Findings

### 1. Hierarchical vs Sequential Keys

✓ **The classifier correctly uses HIERARCHICAL keys (with dots)**, not sequential numbers.

- The AI properly identifies the "Classificação" column (hierarchical codes like 1.1, 1.1.1)
- It does NOT use the "Código" column (sequential numbers like 1, 2, 3)
- Example: Classification key "1.1.10.200.1" maps to DISPONIBILIDADES

### 2. Classification Coverage

✓ **Perfect coverage** - all 375 accounts in the balancete are classified.

### 3. Pipeline Integration

✓ **All orchestrator steps work correctly:**
1. Parse CSV ✓
2. Classify accounts via AI ✓
3. Group saldos by grupo contábil ✓
4. Calculate financial indicators ✓
5. Compare periods ✓

---

## Test Files Created

1. **test_classifier_pipeline.py** - Basic classification test
2. **test_detailed_analysis.py** - Detailed classification analysis
3. **test_orchestrator_integration.py** - Full pipeline integration test

---

## Conclusion

The classifier_agent and orchestrator pipeline are working as expected:

- ✓ AI classification uses hierarchical keys (not sequential)
- ✓ 100% account coverage
- ✓ Correct grouping by grupo contábil
- ✓ Financial indicators calculated successfully
- ✓ Comparative analysis functional

**No modifications needed to any files.**
