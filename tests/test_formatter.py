"""Testes do formatter — regressão e multi-período."""

from app.services.formatter import (
    formatar_dre, formatar_balanco,
    formatar_dre_multi, formatar_balanco_multi,
    formatar_balancete,
)


# ---------------------------------------------------------------------------
# DRE: header com "Classificação" mas dados sem códigos (coluna vazia)
# ---------------------------------------------------------------------------

DRE_3COL_EMPTY_CLASSIF = """\
| Classificação | Descrição | Valor |
| --- | --- | --- |
| | **Receita Operacional Bruta** | **1.500.000,00** |
| | Receita de Serviços | 1.200.000,00 |
| | Receita de Vendas | 300.000,00 |
| | **(-) Deduções** | **(150.000,00)** |
| | **Receita Líquida** | **1.350.000,00** |
| | Custos | (800.000,00) |
| | **Resultado Bruto** | **550.000,00** |
| | Despesas Administrativas | (200.000,00) |
| | **Resultado Líquido** | **350.000,00** |
"""

DRE_3COL_WITH_CLASSIF = """\
| Classificação | Descrição | Valor |
| --- | --- | --- |
| 3.1 | **Receita Operacional Bruta** | **1.500.000,00** |
| 3.1.1 | Receita de Serviços | 1.200.000,00 |
| 3.1.2 | Receita de Vendas | 300.000,00 |
| 3.2 | **Resultado Líquido** | **350.000,00** |
"""

DRE_2COL = """\
| Descrição | Valor |
| --- | --- |
| **Receita Bruta** | **1.500.000,00** |
| Custos | (800.000,00) |
| **Resultado Líquido** | **700.000,00** |
"""


class TestDREFormatter:

    def test_3col_empty_classif_nao_zera_valores(self):
        """Bug principal: header 3 colunas + classificação vazia não deve zerar valores."""
        result = formatar_dre(DRE_3COL_EMPTY_CLASSIF)
        linhas = result["linhas"]
        assert len(linhas) >= 5, f"Esperava >=5 linhas, veio {len(linhas)}"

        # Nenhum valor deve ser 0 (todos têm valor no texto)
        for linha in linhas:
            desc = linha["descricao"]
            val = linha["valor"]
            assert val != 0, f"Valor zerado para '{desc}'"

    def test_3col_empty_classif_valores_corretos(self):
        """Verifica valores específicos."""
        result = formatar_dre(DRE_3COL_EMPTY_CLASSIF)
        linhas = result["linhas"]
        desc_val = {l["descricao"]: l["valor"] for l in linhas}

        assert desc_val.get("Receita de Serviços") == 1_200_000.0
        assert desc_val.get("Receita de Vendas") == 300_000.0
        assert desc_val.get("Resultado Líquido") == 350_000.0

    def test_3col_with_classif(self):
        """Tabela com classificações numéricas presentes."""
        result = formatar_dre(DRE_3COL_WITH_CLASSIF)
        linhas = result["linhas"]
        assert len(linhas) >= 3

        classifs = [l.get("classificacao", "") for l in linhas]
        assert "3.1" in classifs
        assert "3.1.1" in classifs

    def test_2col_continua_funcionando(self):
        """Regressão: tabelas 2 colunas (sem classificação) devem continuar ok."""
        result = formatar_dre(DRE_2COL)
        linhas = result["linhas"]
        assert len(linhas) >= 2
        desc_val = {l["descricao"]: l["valor"] for l in linhas}
        assert desc_val.get("Resultado Líquido") == 700_000.0


# ---------------------------------------------------------------------------
# Balanço: header com "Classificação" mas dados sem códigos
# ---------------------------------------------------------------------------

BALANCO_3COL_EMPTY_CLASSIF = """\
| Classificação | Descrição | Valor |
| --- | --- | --- |
| | **ATIVO** | |
| | **Ativo Circulante** | |
| | Caixa e Equivalentes | 500.000,00 |
| | Contas a Receber | 300.000,00 |
| | **Ativo Não Circulante** | |
| | Imobilizado | 700.000,00 |
| | **PASSIVO** | |
| | **Passivo Circulante** | |
| | Fornecedores | 200.000,00 |
| | **Passivo Não Circulante** | |
| | Empréstimos | 400.000,00 |
| | **PATRIMÔNIO LÍQUIDO** | |
| | Capital Social | 900.000,00 |
"""


class TestBalancoFormatter:

    def test_3col_empty_classif_nao_zera_valores(self):
        """Bug principal: header 3 colunas + classificação vazia."""
        result = formatar_balanco(BALANCO_3COL_EMPTY_CLASSIF)
        ativo_circ = result["ativo"]["circulante"]["contas"]

        assert len(ativo_circ) >= 2, f"Esperava >=2 contas ativo circ, veio {len(ativo_circ)}"
        desc_val = {c["descricao"]: c["valor"] for c in ativo_circ}
        assert desc_val.get("Caixa e Equivalentes") == 500_000.0
        assert desc_val.get("Contas a Receber") == 300_000.0

    def test_3col_empty_classif_passivo(self):
        result = formatar_balanco(BALANCO_3COL_EMPTY_CLASSIF)
        passivo_circ = result["passivo"]["circulante"]["contas"]
        desc_val = {c["descricao"]: c["valor"] for c in passivo_circ}
        assert desc_val.get("Fornecedores") == 200_000.0

    def test_3col_empty_classif_pl(self):
        result = formatar_balanco(BALANCO_3COL_EMPTY_CLASSIF)
        pl_contas = result["patrimonio_liquido"]["contas"]
        desc_val = {c["descricao"]: c["valor"] for c in pl_contas}
        assert desc_val.get("Capital Social") == 900_000.0


# ---------------------------------------------------------------------------
# Multi-período: DRE comparativa
# ---------------------------------------------------------------------------

DRE_MULTI_PERIOD = """\
| Classificação | Descrição | Dez/2024 | Dez/2025 |
| --- | --- | --- | --- |
| 3.1 | **Receita Operacional Bruta** | **1.200.000,00** | **1.500.000,00** |
| 3.1.1 | Receita de Serviços | 900.000,00 | 1.200.000,00 |
| 3.1.2 | Receita de Vendas | 300.000,00 | 300.000,00 |
| 3.2 | **(-) Deduções** | **(100.000,00)** | **(150.000,00)** |
| 3.3 | **Receita Líquida** | **1.100.000,00** | **1.350.000,00** |
| 3.4 | Custos | (600.000,00) | (700.000,00) |
| 3.5 | **Resultado Líquido** | **500.000,00** | **650.000,00** |
"""

DRE_MULTI_NO_CLASSIF = """\
| Descrição | Jan-Dez/2024 | Jan-Dez/2025 |
| --- | --- | --- |
| **Receita Bruta** | **1.000.000,00** | **1.200.000,00** |
| Custos | (400.000,00) | (500.000,00) |
| **Resultado Líquido** | **600.000,00** | **700.000,00** |
"""


class TestDREMultiPeriod:

    def test_detects_two_periods_with_classif(self):
        results = formatar_dre_multi(DRE_MULTI_PERIOD)
        assert len(results) == 2

    def test_period_names(self):
        results = formatar_dre_multi(DRE_MULTI_PERIOD)
        periodos = [r["periodo"] for r in results]
        assert "Dez/2024" in periodos
        assert "Dez/2025" in periodos

    def test_values_correctly_split(self):
        results = formatar_dre_multi(DRE_MULTI_PERIOD)
        dec24 = next(r for r in results if r["periodo"] == "Dez/2024")
        dec25 = next(r for r in results if r["periodo"] == "Dez/2025")

        dec24_vals = {l["descricao"]: l["valor"] for l in dec24["linhas"]}
        dec25_vals = {l["descricao"]: l["valor"] for l in dec25["linhas"]}

        assert dec24_vals["Receita de Serviços"] == 900_000.0
        assert dec25_vals["Receita de Serviços"] == 1_200_000.0
        assert dec24_vals["Receita de Vendas"] == 300_000.0
        assert dec25_vals["Receita de Vendas"] == 300_000.0

    def test_resultado_liquido_per_period(self):
        results = formatar_dre_multi(DRE_MULTI_PERIOD)
        dec24 = next(r for r in results if r["periodo"] == "Dez/2024")
        dec25 = next(r for r in results if r["periodo"] == "Dez/2025")
        assert dec24["resultado_liquido"] == 500_000.0
        assert dec25["resultado_liquido"] == 650_000.0

    def test_classif_preserved(self):
        results = formatar_dre_multi(DRE_MULTI_PERIOD)
        for r in results:
            classifs = [l.get("classificacao", "") for l in r["linhas"]]
            assert "3.1" in classifs
            assert "3.1.1" in classifs

    def test_no_classif_two_periods(self):
        results = formatar_dre_multi(DRE_MULTI_NO_CLASSIF)
        assert len(results) == 2
        periodos = [r["periodo"] for r in results]
        assert "Jan-Dez/2024" in periodos
        assert "Jan-Dez/2025" in periodos

    def test_single_period_returns_list_of_one(self):
        results = formatar_dre_multi(DRE_3COL_WITH_CLASSIF)
        assert len(results) == 1
        assert len(results[0]["linhas"]) >= 3

    def test_single_period_2col_returns_list_of_one(self):
        results = formatar_dre_multi(DRE_2COL)
        assert len(results) == 1
        assert results[0]["linhas"]


# ---------------------------------------------------------------------------
# Multi-período: Balanço comparativo
# ---------------------------------------------------------------------------

BALANCO_MULTI_PERIOD = """\
| Classificação | Descrição | 31/12/2024 | 31/12/2025 |
| --- | --- | --- | --- |
| | **ATIVO** | | |
| | **Ativo Circulante** | | |
| | Caixa e Equivalentes | 400.000,00 | 500.000,00 |
| | Contas a Receber | 200.000,00 | 300.000,00 |
| | **Ativo Não Circulante** | | |
| | Imobilizado | 600.000,00 | 700.000,00 |
| | **PASSIVO** | | |
| | **Passivo Circulante** | | |
| | Fornecedores | 150.000,00 | 200.000,00 |
| | **Passivo Não Circulante** | | |
| | Empréstimos | 350.000,00 | 400.000,00 |
| | **PATRIMÔNIO LÍQUIDO** | | |
| | Capital Social | 700.000,00 | 900.000,00 |
"""

BALANCO_MULTI_NO_CLASSIF = """\
| Descrição | Dez/2024 | Dez/2025 |
| --- | --- | --- |
| **ATIVO** | | |
| **Circulante** | | |
| Caixa | 100.000,00 | 200.000,00 |
| **Não Circulante** | | |
| Imobilizado | 300.000,00 | 400.000,00 |
| **PASSIVO** | | |
| **Circulante** | | |
| Fornecedores | 50.000,00 | 100.000,00 |
| **PATRIMÔNIO LÍQUIDO** | | |
| Capital Social | 350.000,00 | 500.000,00 |
"""


class TestBalancoMultiPeriod:

    def test_detects_two_periods(self):
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        assert len(results) == 2

    def test_period_names(self):
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        periodos = [r["data_referencia"] for r in results]
        assert "31/12/2024" in periodos
        assert "31/12/2025" in periodos

    def test_values_independent_per_period(self):
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        dec24 = next(r for r in results if r["data_referencia"] == "31/12/2024")
        dec25 = next(r for r in results if r["data_referencia"] == "31/12/2025")

        dec24_ativo = {c["descricao"]: c["valor"] for c in dec24["ativo"]["circulante"]["contas"]}
        dec25_ativo = {c["descricao"]: c["valor"] for c in dec25["ativo"]["circulante"]["contas"]}

        assert dec24_ativo["Caixa e Equivalentes"] == 400_000.0
        assert dec25_ativo["Caixa e Equivalentes"] == 500_000.0

    def test_passivo_per_period(self):
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        dec24 = next(r for r in results if r["data_referencia"] == "31/12/2024")
        dec25 = next(r for r in results if r["data_referencia"] == "31/12/2025")

        dec24_p = {c["descricao"]: c["valor"] for c in dec24["passivo"]["circulante"]["contas"]}
        dec25_p = {c["descricao"]: c["valor"] for c in dec25["passivo"]["circulante"]["contas"]}

        assert dec24_p["Fornecedores"] == 150_000.0
        assert dec25_p["Fornecedores"] == 200_000.0

    def test_pl_per_period(self):
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        dec24 = next(r for r in results if r["data_referencia"] == "31/12/2024")
        dec25 = next(r for r in results if r["data_referencia"] == "31/12/2025")

        dec24_pl = {c["descricao"]: c["valor"] for c in dec24["patrimonio_liquido"]["contas"]}
        dec25_pl = {c["descricao"]: c["valor"] for c in dec25["patrimonio_liquido"]["contas"]}

        assert dec24_pl["Capital Social"] == 700_000.0
        assert dec25_pl["Capital Social"] == 900_000.0

    def test_balanco_equation_per_period(self):
        """Ativo = Passivo + PL para cada período."""
        results = formatar_balanco_multi(BALANCO_MULTI_PERIOD)
        for r in results:
            ativo_total = r["ativo"]["total"]
            passivo_total = r["passivo"]["total"]
            pl_total = r["patrimonio_liquido"]["total"]
            assert abs(ativo_total - passivo_total - pl_total) < 0.01, (
                f"Período {r['data_referencia']}: Ativo={ativo_total}, "
                f"Passivo={passivo_total}, PL={pl_total}"
            )

    def test_no_classif_two_periods(self):
        results = formatar_balanco_multi(BALANCO_MULTI_NO_CLASSIF)
        assert len(results) == 2

    def test_single_period_returns_list_of_one(self):
        results = formatar_balanco_multi(BALANCO_3COL_EMPTY_CLASSIF)
        assert len(results) == 1
        assert results[0]["ativo"]["circulante"]["contas"]


# ---------------------------------------------------------------------------
# Edge cases multi-período
# ---------------------------------------------------------------------------

class TestMultiPeriodEdgeCases:

    def test_three_periods(self):
        """Tabela com 3 colunas de valor."""
        text = """\
| Descrição | 2023 | 2024 | 2025 |
| --- | --- | --- | --- |
| **Receita Bruta** | **800.000,00** | **1.000.000,00** | **1.200.000,00** |
| Custos | (300.000,00) | (400.000,00) | (500.000,00) |
| **Resultado Líquido** | **500.000,00** | **600.000,00** | **700.000,00** |
"""
        results = formatar_dre_multi(text)
        assert len(results) == 3
        periodos = [r["periodo"] for r in results]
        assert "2023" in periodos
        assert "2024" in periodos
        assert "2025" in periodos

    def test_section_headers_with_empty_values(self):
        """Headers de seção (ATIVO, PASSIVO) sem valor não quebram multi-período."""
        text = """\
| Descrição | Dez/2024 | Dez/2025 |
| --- | --- | --- |
| **ATIVO** | | |
| Caixa | 100.000,00 | 200.000,00 |
| **PASSIVO** | | |
| Fornecedores | 50.000,00 | 100.000,00 |
| **PATRIMÔNIO LÍQUIDO** | | |
| Capital Social | 50.000,00 | 100.000,00 |
"""
        results = formatar_balanco_multi(text)
        assert len(results) == 2
        for r in results:
            assert r["ativo"]["circulante"]["contas"]

    def test_av_percent_column_not_treated_as_period(self):
        """Coluna AV% não deve ser tratada como um período."""
        text = """\
| Descrição | Valor | AV% |
| --- | --- | --- |
| **Receita Bruta** | **1.000.000,00** | **100%** |
| Custos | (500.000,00) | 50% |
| **Resultado Líquido** | **500.000,00** | **50%** |
"""
        results = formatar_dre_multi(text)
        assert len(results) == 1

    def test_empty_text_returns_single_empty(self):
        results = formatar_dre_multi("")
        assert len(results) == 1
        assert results[0]["linhas"] == []

    def test_empty_balanco_returns_single_empty(self):
        results = formatar_balanco_multi("")
        assert len(results) == 1
        assert results[0]["ativo"]["total"] == 0


# ---------------------------------------------------------------------------
# Balancete: linhas de header repetidas (quebra de página)
# ---------------------------------------------------------------------------

BALANCETE_WITH_REPEATED_HEADERS = """\
| Código | Classificação | Descrição | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | ATIVO | A | 100.000,00 | 10.000,00 | 5.000,00 | 105.000,00 |
| 11 | 1.1 | Caixa | D | 50.000,00 | 10.000,00 | 5.000,00 | 55.000,00 |
| 12 | 1.2 | Bancos | D | 50.000,00 | 0,00 | 0,00 | 50.000,00 |
| Código | Classificação | Descrição | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual |
| 2 | 2 | PASSIVO | A | 60.000,00 | 3.000,00 | 8.000,00 | 65.000,00 |
| 21 | 2.1 | Fornecedores | D | 60.000,00 | 3.000,00 | 8.000,00 | 65.000,00 |
| Código | Classificação | Descrição | Tipo | Saldo Anterior | Débito | Crédito | Saldo Atual |
| 3 | 3 | RECEITAS | A | 0,00 | 0,00 | 20.000,00 | 20.000,00 |
| 31 | 3.1 | Receita Serviços | D | 0,00 | 0,00 | 20.000,00 | 20.000,00 |
"""


class TestBalanceteRepeatedHeaders:
    """Headers repetidos por quebra de página devem ser ignorados."""

    def test_repeated_headers_not_in_contas(self):
        result = formatar_balancete(BALANCETE_WITH_REPEATED_HEADERS)
        descs = [c["descricao"] for c in result["contas"]]
        assert "Descrição" not in descs
        assert "Descrição " not in descs

    def test_correct_conta_count(self):
        result = formatar_balancete(BALANCETE_WITH_REPEATED_HEADERS)
        # 6 contas reais: ATIVO, Caixa, Bancos, PASSIVO, Fornecedores, RECEITAS, Receita Serviços
        assert len(result["contas"]) == 7

    def test_values_correct(self):
        result = formatar_balancete(BALANCETE_WITH_REPEATED_HEADERS)
        caixa = [c for c in result["contas"] if c["descricao"] == "Caixa"][0]
        assert caixa["saldo_atual"] == 55000.0
        assert caixa["debitos"] == 10000.0
