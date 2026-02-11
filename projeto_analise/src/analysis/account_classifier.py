"""Classificador de contas contábeis.

Recebe o mapeamento da IA (JSON com "bp" e "dre") e agrega saldos
por grupo contábil, buscando cada conta diretamente pelo código
de classificação hierárquica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from src.parsers.csv_parser import Balancete, valor_com_sinal
from src.utils.config import logger


class GrupoContabil(str, Enum):
    """Grupos contábeis padrão do plano de contas."""

    # ATIVO
    ATIVO_TOTAL = "ATIVO_TOTAL"
    ATIVO_CIRCULANTE = "ATIVO_CIRCULANTE"
    DISPONIBILIDADES = "DISPONIBILIDADES"
    CLIENTES = "CLIENTES"
    ESTOQUES = "ESTOQUES"
    OUTROS_CREDITOS_CP = "OUTROS_CREDITOS_CP"
    DESPESAS_ANTECIPADAS = "DESPESAS_ANTECIPADAS"
    ATIVO_NAO_CIRCULANTE = "ATIVO_NAO_CIRCULANTE"
    INVESTIMENTOS = "INVESTIMENTOS"
    IMOBILIZADO = "IMOBILIZADO"
    INTANGIVEL = "INTANGIVEL"
    DEPRECIACAO_AMORTIZACAO = "DEPRECIACAO_AMORTIZACAO"

    # PASSIVO
    PASSIVO_TOTAL = "PASSIVO_TOTAL"
    PASSIVO_CIRCULANTE = "PASSIVO_CIRCULANTE"
    EMPRESTIMOS_FINANCIAMENTOS_CP = "EMPRESTIMOS_FINANCIAMENTOS_CP"
    FORNECEDORES = "FORNECEDORES"
    OBRIGACOES_FISCAIS = "OBRIGACOES_FISCAIS"
    OBRIGACOES_TRABALHISTAS = "OBRIGACOES_TRABALHISTAS"
    OUTRAS_OBRIGACOES_CP = "OUTRAS_OBRIGACOES_CP"
    PASSIVO_NAO_CIRCULANTE = "PASSIVO_NAO_CIRCULANTE"
    EMPRESTIMOS_LP = "EMPRESTIMOS_LP"
    PARCELAMENTOS_TRIBUTARIOS = "PARCELAMENTOS_TRIBUTARIOS"
    OUTROS_DEBITOS_LP = "OUTROS_DEBITOS_LP"
    PATRIMONIO_LIQUIDO = "PATRIMONIO_LIQUIDO"
    CAPITAL_SOCIAL = "CAPITAL_SOCIAL"
    LUCROS_PREJUIZOS = "LUCROS_PREJUIZOS"

    # RESULTADO
    RECEITA_BRUTA = "RECEITA_BRUTA"
    DEDUCOES_RECEITA = "DEDUCOES_RECEITA"
    CUSTOS_SERVICOS = "CUSTOS_SERVICOS"
    DESPESAS_OPERACIONAIS = "DESPESAS_OPERACIONAIS"
    DESPESAS_ADMINISTRATIVAS = "DESPESAS_ADMINISTRATIVAS"
    DESPESAS_FINANCEIRAS = "DESPESAS_FINANCEIRAS"
    DESPESAS_COMERCIAIS = "DESPESAS_COMERCIAIS"
    RECEITAS_FINANCEIRAS = "RECEITAS_FINANCEIRAS"


# Mapa: chave do JSON da IA → GrupoContabil
MAPA_CHAVES: dict[str, GrupoContabil] = {
    # BP
    "ativo_total": GrupoContabil.ATIVO_TOTAL,
    "ativo_circulante": GrupoContabil.ATIVO_CIRCULANTE,
    "disponibilidades": GrupoContabil.DISPONIBILIDADES,
    "clientes": GrupoContabil.CLIENTES,
    "estoques": GrupoContabil.ESTOQUES,
    "outros_creditos_cp": GrupoContabil.OUTROS_CREDITOS_CP,
    "despesas_antecipadas": GrupoContabil.DESPESAS_ANTECIPADAS,
    "ativo_nao_circulante": GrupoContabil.ATIVO_NAO_CIRCULANTE,
    "investimentos": GrupoContabil.INVESTIMENTOS,
    "imobilizado": GrupoContabil.IMOBILIZADO,
    "depreciacao_amortizacao": GrupoContabil.DEPRECIACAO_AMORTIZACAO,
    "intangivel": GrupoContabil.INTANGIVEL,
    "passivo_total": GrupoContabil.PASSIVO_TOTAL,
    "passivo_circulante": GrupoContabil.PASSIVO_CIRCULANTE,
    "emprestimos_financiamentos_cp": GrupoContabil.EMPRESTIMOS_FINANCIAMENTOS_CP,
    "fornecedores": GrupoContabil.FORNECEDORES,
    "obrigacoes_fiscais": GrupoContabil.OBRIGACOES_FISCAIS,
    "obrigacoes_trabalhistas": GrupoContabil.OBRIGACOES_TRABALHISTAS,
    "outras_obrigacoes_cp": GrupoContabil.OUTRAS_OBRIGACOES_CP,
    "passivo_nao_circulante": GrupoContabil.PASSIVO_NAO_CIRCULANTE,
    "emprestimos_lp": GrupoContabil.EMPRESTIMOS_LP,
    "outros_debitos_lp": GrupoContabil.OUTROS_DEBITOS_LP,
    "patrimonio_liquido": GrupoContabil.PATRIMONIO_LIQUIDO,
    "capital_social": GrupoContabil.CAPITAL_SOCIAL,
    "lucros_prejuizos": GrupoContabil.LUCROS_PREJUIZOS,
    # DRE
    "receita_bruta": GrupoContabil.RECEITA_BRUTA,
    "deducoes_receita": GrupoContabil.DEDUCOES_RECEITA,
    "custos_servicos": GrupoContabil.CUSTOS_SERVICOS,
    "despesas_operacionais": GrupoContabil.DESPESAS_OPERACIONAIS,
    "despesas_administrativas": GrupoContabil.DESPESAS_ADMINISTRATIVAS,
    "despesas_financeiras": GrupoContabil.DESPESAS_FINANCEIRAS,
    "despesas_comerciais": GrupoContabil.DESPESAS_COMERCIAIS,
    "receitas_financeiras": GrupoContabil.RECEITAS_FINANCEIRAS,
}


@dataclass
class SaldosAgrupados:
    """Saldos agregados por grupo contábil."""

    grupos: dict[GrupoContabil, Decimal] = field(default_factory=dict)
    grupos_anterior: dict[GrupoContabil, Decimal] = field(default_factory=dict)

    def get(self, grupo: GrupoContabil, default: Decimal = Decimal("0")) -> Decimal:
        return self.grupos.get(grupo, default)

    def get_anterior(self, grupo: GrupoContabil, default: Decimal = Decimal("0")) -> Decimal:
        return self.grupos_anterior.get(grupo, default)


def agrupar_saldos(
    balancete: Balancete,
    mapeamento_ia: dict | None = None,
) -> SaldosAgrupados:
    """Agrega saldos usando o mapeamento estruturado da IA.

    O mapeamento tem formato {"bp": {chave: classificação}, "dre": {chave: classificação}}.
    Para cada chave, busca a conta no balancete pela classificação e extrai os saldos.

    Args:
        balancete: Balancete parseado.
        mapeamento_ia: JSON da IA com seções "bp" e "dre".

    Returns:
        SaldosAgrupados com valores por grupo.

    Raises:
        ValueError: Se mapeamento_ia não for fornecido.
    """
    if not mapeamento_ia or not mapeamento_ia.get("bp"):
        raise ValueError(
            "Mapeamento IA é obrigatório. Configure ANTHROPIC_API_KEY no .env."
        )

    saldos = SaldosAgrupados()

    # Índice: classificação → conta (para busca rápida)
    contas_por_classif = {c.classificacao: c for c in balancete.contas}

    # Processa BP e DRE
    for secao in ("bp", "dre"):
        for chave, classif in mapeamento_ia.get(secao, {}).items():
            if not classif:
                continue

            grupo = MAPA_CHAVES.get(chave)
            if not grupo:
                # Chaves especiais (parcelamentos_cp, parcelamentos_lp)
                # são tratadas abaixo
                continue

            conta = contas_por_classif.get(classif)
            if not conta:
                logger.warning(
                    "Conta não encontrada no balancete: %s → %s", chave, classif,
                )
                continue

            valor_atual, valor_anterior = _extrair_valores(conta)
            saldos.grupos[grupo] = valor_atual
            saldos.grupos_anterior[grupo] = valor_anterior

    # Parcelamentos: soma CP + LP → PARCELAMENTOS_TRIBUTARIOS
    _somar_parcelamentos(mapeamento_ia, contas_por_classif, saldos)

    # Fallback: depreciação por keyword se IA não identificou
    if GrupoContabil.DEPRECIACAO_AMORTIZACAO not in saldos.grupos:
        _adicionar_depreciacao_keyword(balancete, saldos)

    logger.info("Saldos agrupados: %d grupos encontrados", len(saldos.grupos))
    return saldos


def _extrair_valores(conta) -> tuple[Decimal, Decimal]:
    """Extrai saldo_atual e saldo_anterior de uma conta."""
    if conta.natureza_atual:
        valor_atual = valor_com_sinal(
            conta.saldo_atual, conta.natureza_atual, conta.grupo_principal,
        )
        valor_anterior = valor_com_sinal(
            conta.saldo_anterior, conta.natureza_anterior, conta.grupo_principal,
        )
    else:
        valor_atual = conta.saldo_atual
        valor_anterior = conta.saldo_anterior
    return valor_atual, valor_anterior


def _somar_parcelamentos(
    mapeamento_ia: dict,
    contas_por_classif: dict,
    saldos: SaldosAgrupados,
) -> None:
    """Soma parcelamentos CP e LP em PARCELAMENTOS_TRIBUTARIOS."""
    total_atual = Decimal("0")
    total_anterior = Decimal("0")
    encontrou = False

    for chave in ("parcelamentos_cp", "parcelamentos_lp"):
        classif = mapeamento_ia.get("bp", {}).get(chave)
        if not classif:
            continue
        conta = contas_por_classif.get(classif)
        if not conta:
            continue
        val_atual, val_anterior = _extrair_valores(conta)
        total_atual += val_atual
        total_anterior += val_anterior
        encontrou = True

    if encontrou:
        saldos.grupos[GrupoContabil.PARCELAMENTOS_TRIBUTARIOS] = total_atual
        saldos.grupos_anterior[GrupoContabil.PARCELAMENTOS_TRIBUTARIOS] = total_anterior


def _adicionar_depreciacao_keyword(
    balancete: Balancete, saldos: SaldosAgrupados,
) -> None:
    """Fallback: busca depreciação/amortização por keyword nas descrições."""
    deprec_atual = Decimal("0")
    deprec_anterior = Decimal("0")
    for conta in balancete.contas:
        desc_upper = conta.descricao.upper()
        if "DEPRECIA" in desc_upper or "AMORTIZA" in desc_upper:
            val_atual, val_anterior = _extrair_valores(conta)
            deprec_atual += abs(val_atual)
            deprec_anterior += abs(val_anterior)

    if deprec_atual > 0 or deprec_anterior > 0:
        saldos.grupos[GrupoContabil.DEPRECIACAO_AMORTIZACAO] = deprec_atual
        saldos.grupos_anterior[GrupoContabil.DEPRECIACAO_AMORTIZACAO] = deprec_anterior
