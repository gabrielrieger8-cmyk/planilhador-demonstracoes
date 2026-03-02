"""Testes do formatter — foco em regressão do bug de classificação vazia."""

from app.services.formatter import formatar_dre, formatar_balanco


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
