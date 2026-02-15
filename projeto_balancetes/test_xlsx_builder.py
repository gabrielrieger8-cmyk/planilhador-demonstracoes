"""Test xlsx_builder + sign_logic — cenários reais de sinais contábeis."""
import tempfile
from pathlib import Path

from src.exporters.xlsx_builder import BalanceteXlsxBuilder, detect_periodo, _parse_br_float
from src.exporters.sign_logic import (
    STANDARD_CONVENTION,
    SignConfig,
    apply_sign_convention,
    detect_sign_mode,
)

print("=" * 60)
print("TEST 1: STANDARD_CONVENTION")
print("=" * 60)

# Verifica que a convencao está correta
assert STANDARD_CONVENTION[1] == {"D": 1, "C": -1}, "Ativo: D=+, C=-"
assert STANDARD_CONVENTION[2] == {"D": -1, "C": 1}, "Passivo: D=-, C=+"
assert STANDARD_CONVENTION[3] == {"D": -1, "C": 1}, "Despesas: D=-, C=+"
assert STANDARD_CONVENTION[4] == {"D": -1, "C": 1}, "Receitas: D=-, C=+"
print("  Grupo 1 (Ativo):    D=+, C=-  OK")
print("  Grupo 2 (Passivo):  D=-, C=+  OK")
print("  Grupo 3 (Despesas): D=-, C=+  OK")
print("  Grupo 4 (Receitas): D=-, C=+  OK")

print()
print("=" * 60)
print("TEST 2: SINAIS — Depreciacao no Ativo (C = negativo)")
print("=" * 60)

# Cenário real: depreciacao acumulada e conta do Ativo (1.x) com natureza C
# Deve ficar NEGATIVA porque no Ativo D=+ e C=-
sign_rows = [
    # [Cod, Classif, Desc, SA, Nat_SA, Deb, Cred, SAT, Nat_SAT, Tipo]
    # Índices: 0=Cod, 1=Classif, 2=Desc, 3=SA, 4=Nat_SA, 5=Deb, 6=Cred, 7=SAT, 8=Nat_SAT, 9=Tipo
    ["1", "1",       "ATIVO",                    "500.000,00", "D", "50.000,00", "30.000,00", "520.000,00", "D", "A"],
    ["2", "1.2",     "NAO CIRCULANTE",           "300.000,00", "D", "20.000,00", "10.000,00", "310.000,00", "D", "A"],
    ["3", "1.2.01",  "IMOBILIZADO",              "400.000,00", "D", "10.000,00", "0,00",      "410.000,00", "D", "D"],
    ["4", "1.2.02",  "DEPRECIACAO ACUMULADA",    "100.000,00", "C", "0,00",      "5.000,00",  "105.000,00", "C", "D"],  # <-- C no Ativo!
]

# Aplica convencao
config = SignConfig(mode="auto")
converted = apply_sign_convention(
    rows=sign_rows,
    sa_col=3,
    sat_col=7,
    nat_sa_col=4,
    nat_sat_col=8,
    classif_col=1,
    config=config,
)

# Verifica depreciacao (row index 3 = "1.2.02")
dep_sa = converted[3][3]    # Saldo Anterior
dep_sat = converted[3][7]   # Saldo Atual

print(f"  ATIVO SA:          {converted[0][3]}  (D -> positivo)")
print(f"  IMOBILIZADO SA:    {converted[2][3]}  (D -> positivo)")
print(f"  DEPRECIACAO SA:    {dep_sa}  (C -> NEGATIVO)")
print(f"  DEPRECIACAO SAT:   {dep_sat}  (C -> NEGATIVO)")

assert dep_sa.startswith("-"), f"Depreciacao SA deveria ser negativa, got: {dep_sa}"
assert dep_sat.startswith("-"), f"Depreciacao SAT deveria ser negativa, got: {dep_sat}"
assert dep_sa == "-100.000,00", f"Expected -100.000,00, got {dep_sa}"
assert dep_sat == "-105.000,00", f"Expected -105.000,00, got {dep_sat}"

# Ativo normal deve ser positivo
ativo_sa = converted[0][3]
assert not ativo_sa.startswith("-"), f"Ativo SA deveria ser positivo, got: {ativo_sa}"
print("  DEPRECIAÇÃO C->NEGATIVO: OK OK")

print()
print("=" * 60)
print("TEST 3: SINAIS — Passivo (C = positivo, D = negativo)")
print("=" * 60)

passivo_rows = [
    ["1", "2",      "PASSIVO",            "200.000,00", "C", "10.000,00", "20.000,00", "210.000,00", "C", "A"],
    ["2", "2.1",    "CIRCULANTE",         "100.000,00", "C", "5.000,00",  "10.000,00", "105.000,00", "C", "A"],
    ["3", "2.1.01", "FORNECEDORES",       "80.000,00",  "C", "3.000,00",  "8.000,00",  "85.000,00",  "C", "D"],
    ["4", "2.1.02", "ADIANT. CLIENTES",   "20.000,00",  "D", "2.000,00",  "2.000,00",  "20.000,00",  "D", "D"],  # D no Passivo!
]

converted_p = apply_sign_convention(
    rows=passivo_rows, sa_col=3, sat_col=7, nat_sa_col=4, nat_sat_col=8,
    classif_col=1, config=config,
)

print(f"  PASSIVO SA:         {converted_p[0][3]}  (C -> positivo)")
print(f"  FORNECEDORES SA:    {converted_p[2][3]}  (C -> positivo)")
print(f"  ADIANT.CLIENTES SA: {converted_p[3][3]}  (D -> NEGATIVO)")

assert converted_p[2][3] == "80.000,00", f"Fornecedores deveria ser +, got: {converted_p[2][3]}"
assert converted_p[3][3] == "-20.000,00", f"Adiant deveria ser -, got: {converted_p[3][3]}"
print("  PASSIVO D->NEGATIVO / C->POSITIVO: OK OK")

print()
print("=" * 60)
print("TEST 4: SINAIS — Despesas (D=-, C=+) e Receitas (D=-, C=+)")
print("=" * 60)

dre_rows = [
    # Despesas (grupo 3): convencao D=-, C=+
    ["1", "3",      "DESPESAS",          "50.000,00", "D", "10.000,00", "2.000,00", "58.000,00", "D", "A"],
    ["2", "3.1",    "DESP OPERACIONAIS", "30.000,00", "D", "8.000,00",  "1.000,00", "37.000,00", "D", "A"],
    ["3", "3.1.01", "SALARIOS",          "20.000,00", "D", "5.000,00",  "0,00",     "25.000,00", "D", "D"],
    ["4", "3.1.02", "REVERSAO PROVISAO", "5.000,00",  "C", "0,00",      "3.000,00", "2.000,00",  "C", "D"],  # C em Despesa
    # Receitas (grupo 4): convencao D=-, C=+
    ["5", "4",      "RECEITAS",          "100.000,00", "C", "5.000,00", "20.000,00", "115.000,00", "C", "A"],
    ["6", "4.1",    "REC OPERACIONAIS",  "80.000,00",  "C", "3.000,00", "15.000,00", "92.000,00",  "C", "A"],
    ["7", "4.1.01", "VENDAS",            "60.000,00",  "C", "2.000,00", "10.000,00", "68.000,00",  "C", "D"],
    ["8", "4.1.02", "DEVOLUCOES",        "10.000,00",  "D", "1.000,00", "0,00",      "11.000,00",  "D", "D"],  # D em Receita = devolucao
]

converted_d = apply_sign_convention(
    rows=dre_rows, sa_col=3, sat_col=7, nat_sa_col=4, nat_sat_col=8,
    classif_col=1, config=config,
)

print(f"  SALARIOS SA:        {converted_d[2][3]}  (Desp D -> NEGATIVO)")
print(f"  REVERSAO SA:        {converted_d[3][3]}  (Desp C -> positivo)")
print(f"  VENDAS SA:          {converted_d[6][3]}  (Rec C -> positivo)")
print(f"  DEVOLUCOES SA:      {converted_d[7][3]}  (Rec D -> NEGATIVO)")

# Despesas: D=-, C=+  (nossa convencao)
assert converted_d[2][3] == "-20.000,00", f"Salarios deveria -, got: {converted_d[2][3]}"
assert converted_d[3][3] == "5.000,00", f"Reversao deveria +, got: {converted_d[3][3]}"
# Receitas: D=-, C=+
assert converted_d[6][3] == "60.000,00", f"Vendas deveria +, got: {converted_d[6][3]}"
assert converted_d[7][3] == "-10.000,00", f"Devolucoes deveria -, got: {converted_d[7][3]}"
print("  DESPESAS D=-/C=+: OK OK")
print("  RECEITAS D=-/C=+: OK OK")

print()
print("=" * 60)
print("TEST 5: detect_periodo")
print("=" * 60)
assert detect_periodo("Balancete 02.2025.pdf") == "02.2025"
assert detect_periodo("VFR Balancete 112025.csv") == "11.2025"
assert detect_periodo("Balancete 2025.csv") == "2025"
print("  detect_periodo: OK OK")

print()
print("=" * 60)
print("TEST 6: Build XLSX com sinais aplicados")
print("=" * 60)

# Dados com Tipo no index 3 (como o header CSV real do sistema)
# Header: Codigo(0) Classificacao(1) Descricao(2) Tipo(3) SA(4) NatSA(5) Deb(6) Cred(7) SAT(8) NatSAT(9)
xlsx_header = [
    "Codigo", "Classificacao", "Descricao", "Tipo",
    "Saldo Anterior", "Natureza SA", "Debito", "Credito",
    "Saldo Atual", "Natureza SAT",
]
xlsx_rows = [
    xlsx_header,
    ["1", "1",       "ATIVO",                 "A", "500.000,00", "D", "50.000,00", "30.000,00", "520.000,00", "D"],
    ["2", "1.2",     "NAO CIRCULANTE",        "A", "300.000,00", "D", "20.000,00", "10.000,00", "310.000,00", "D"],
    ["3", "1.2.01",  "IMOBILIZADO",           "D", "400.000,00", "D", "10.000,00", "0,00",      "410.000,00", "D"],
    ["4", "1.2.02",  "DEPRECIACAO ACUMULADA",  "D", "100.000,00", "C", "0,00",      "5.000,00",  "105.000,00", "C"],
]

builder = BalanceteXlsxBuilder(xlsx_rows, periodo="02.2025", sign_config=SignConfig(mode="auto"))

# Detect
det = builder.detect_signs()
print(f"  has_dc={det.has_dc}, matches_convention={det.matches_convention}")

# Apply
builder.apply_signs()

# Verifica dados internos pos-apply
dep_internal = builder._rows[3]
print(f"  Internal DEPREC SA={dep_internal[3]} SAT={dep_internal[7]}")
assert isinstance(dep_internal[3], float) and dep_internal[3] < 0, f"Internal SA deveria <0, got {dep_internal[3]}"

# Build
tmp = Path(tempfile.mkdtemp()) / "test_signs.xlsx"
result = builder.build(output_path=tmp)
print(f"  XLSX: {result} ({result.stat().st_size} bytes)")

# Verify
from openpyxl import load_workbook

wb = load_workbook(str(result))
ws = wb["02.2025"]

# Col D = SA (index 3+1=4 in xlsx), Col H = SAT (index 7+1=8 in xlsx)
# Row 5 = depreciacao (row_idx 3 + 1 header + 1-based = 5)
dep_sa_cell = ws.cell(5, 4)
dep_sat_cell = ws.cell(5, 8)

print(f"  DEPRECIACAO SA cell:  {dep_sa_cell.value}")
print(f"  DEPRECIACAO SAT cell: {dep_sat_cell.value}")

# Depreciacao deve ser negativa no Excel
assert isinstance(dep_sa_cell.value, (int, float)), f"SA deveria ser numerico, got {type(dep_sa_cell.value)}"
assert dep_sa_cell.value < 0, f"Depreciacao SA deveria ser < 0, got {dep_sa_cell.value}"
assert dep_sat_cell.value < 0, f"Depreciacao SAT deveria ser < 0, got {dep_sat_cell.value}"
print(f"  DEPRECIACAO NEGATIVA NO XLSX: OK")

# Imobilizado deve ser positivo
imob_sa = ws.cell(4, 4).value
print(f"  IMOBILIZADO SA cell:  {imob_sa}")
assert isinstance(imob_sa, (int, float)), f"Imob SA deveria ser numerico, got {type(imob_sa.value)}"
assert imob_sa > 0, f"Imobilizado SA deveria ser > 0, got {imob_sa}"
print(f"  IMOBILIZADO POSITIVO NO XLSX: OK")

# ATIVO agrupadora deve ter formula SUM
ativo_sa = ws.cell(2, 4).value
print(f"  ATIVO SA (agrupadora): {ativo_sa}")
assert isinstance(ativo_sa, str) and ativo_sa.startswith("=SUM"), f"ATIVO SA deveria ser SUM, got {ativo_sa}"
print(f"  ATIVO COM FORMULA SUM: OK")

wb.close()

print()
print("=" * 60)
print("ALL TESTS PASSED OK")
print("=" * 60)
