"""Testes unitários para o serviço de validação contábil."""

import pytest

from app.services.validator import validate, ValidationResult


class TestBalanceteValidator:
    def test_balancete_valido(self):
        dados = {
            "contas": [
                {"codigo_conta": "1", "is_totalizador": True, "debitos": 0, "creditos": 0},
                {"codigo_conta": "1.1", "is_totalizador": False, "debitos": 1000, "creditos": 500},
                {"codigo_conta": "2.1", "is_totalizador": False, "debitos": 500, "creditos": 1000},
            ],
            "totais": {"total_debitos": 1500, "total_creditos": 1500},
        }
        result = validate(dados, "balancete")
        assert result.passed

    def test_balancete_invalido(self):
        dados = {
            "contas": [
                {"codigo_conta": "1.1", "is_totalizador": False, "debitos": 1000, "creditos": 500},
            ],
            "totais": {"total_debitos": 1000, "total_creditos": 500},
        }
        result = validate(dados, "balancete")
        assert not result.passed
        assert len(result.errors) > 0

    def test_balancete_sem_contas(self):
        dados = {"contas": []}
        result = validate(dados, "balancete")
        assert not result.passed
        assert "Nenhuma conta" in result.errors[0]

    def test_balancete_tolerancia(self):
        """1% de tolerância em arredondamentos."""
        dados = {
            "contas": [
                {"codigo_conta": "1.1", "is_totalizador": False, "debitos": 10000, "creditos": 10050},
            ],
            "totais": {"total_debitos": 10000, "total_creditos": 10050},
        }
        result = validate(dados, "balancete")
        assert result.passed

    def test_balancete_calcula_sem_totais(self):
        """Calcula totais a partir das contas de detalhe."""
        dados = {
            "contas": [
                {"codigo_conta": "1", "is_totalizador": True, "debitos": 0, "creditos": 0},
                {"codigo_conta": "1.1", "is_totalizador": False, "debitos": 500, "creditos": 300},
                {"codigo_conta": "2.1", "is_totalizador": False, "debitos": 300, "creditos": 500},
            ],
        }
        result = validate(dados, "balancete")
        assert result.passed
        assert result.details["total_debitos"] == 800
        assert result.details["total_creditos"] == 800


class TestBalancoValidator:
    def test_balanco_valido(self):
        dados = {
            "ativo": {"total": 500000},
            "passivo": {"total": 250000},
            "patrimonio_liquido": {"total": 250000},
        }
        result = validate(dados, "balanco_patrimonial")
        assert result.passed

    def test_balanco_invalido(self):
        dados = {
            "ativo": {"total": 500000},
            "passivo": {"total": 300000},
            "patrimonio_liquido": {"total": 100000},
        }
        result = validate(dados, "balanco_patrimonial")
        assert not result.passed
        assert "Ativo" in result.errors[0]

    def test_balanco_tolerancia(self):
        dados = {
            "ativo": {"total": 100000},
            "passivo": {"total": 50000},
            "patrimonio_liquido": {"total": 50500},
        }
        result = validate(dados, "balanco_patrimonial")
        assert result.passed


class TestDREValidator:
    def test_dre_valida(self):
        dados = {
            "linhas": [
                {"descricao": "Receita", "valor": 500000, "is_subtotal": False},
                {"descricao": "Resultado", "valor": 200000, "is_subtotal": True},
            ],
            "resultado_liquido": 200000,
        }
        result = validate(dados, "dre")
        assert result.passed

    def test_dre_sem_linhas(self):
        dados = {"linhas": []}
        result = validate(dados, "dre")
        assert not result.passed

    def test_dre_sem_resultado(self):
        dados = {
            "linhas": [{"descricao": "Receita", "valor": 500000}],
            "resultado_liquido": None,
        }
        result = validate(dados, "dre")
        assert result.passed
        assert len(result.warnings) > 0


class TestTipoDesconhecido:
    def test_tipo_desconhecido_passa_com_warning(self):
        result = validate({}, "outro")
        assert result.passed
        assert len(result.warnings) > 0
