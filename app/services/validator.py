"""Validação contábil dos dados extraídos.

Regras por tipo de documento:
- Balancete: soma dos débitos == soma dos créditos (tolerância de 1%)
- Balanço: Ativo Total == Passivo Total + PL (tolerância de 1%)
- DRE: resultado líquido coerente com a hierarquia
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("planilhador")


@dataclass
class ValidationResult:
    """Resultado da validação contábil."""
    passed: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def validate(dados: dict, tipo: str) -> ValidationResult:
    """Valida dados extraídos conforme o tipo do documento."""
    if tipo == "balancete":
        return _validate_balancete(dados)
    elif tipo == "balanco_patrimonial":
        return _validate_balanco(dados)
    elif tipo == "dre":
        return _validate_dre(dados)
    else:
        result = ValidationResult()
        result.warnings.append(f"Tipo '{tipo}' não possui validação implementada.")
        result.passed = True
        return result


def _validate_balancete(dados: dict) -> ValidationResult:
    """Valida balancete: soma dos débitos == soma dos créditos."""
    result = ValidationResult()
    contas = dados.get("contas", [])

    if not contas:
        result.errors.append("Nenhuma conta encontrada no balancete.")
        return result

    totais = dados.get("totais", {})
    if totais:
        total_deb = totais.get("total_debitos", 0) or 0
        total_cred = totais.get("total_creditos", 0) or 0
    else:
        total_deb = 0.0
        total_cred = 0.0
        for conta in contas:
            if conta.get("is_totalizador"):
                continue
            total_deb += conta.get("debitos", 0) or 0
            total_cred += conta.get("creditos", 0) or 0

    diff = abs(total_deb - total_cred)
    max_val = max(abs(total_deb), abs(total_cred), 0.01)
    tolerance = max_val * 0.01

    result.details = {
        "total_debitos": total_deb,
        "total_creditos": total_cred,
        "diferenca": diff,
        "tolerancia": tolerance,
        "total_contas": len(contas),
    }

    if diff <= tolerance:
        result.passed = True
        logger.info(
            "Balancete válido: débitos=%.2f, créditos=%.2f, diff=%.2f",
            total_deb, total_cred, diff,
        )
    else:
        result.errors.append(
            f"Débitos ({total_deb:,.2f}) != Créditos ({total_cred:,.2f}). "
            f"Diferença: {diff:,.2f} (tolerância: {tolerance:,.2f})."
        )

    return result


def _validate_balanco(dados: dict) -> ValidationResult:
    """Valida balanço: Ativo Total == Passivo Total + PL."""
    result = ValidationResult()

    ativo = dados.get("ativo", {})
    passivo = dados.get("passivo", {})
    pl = dados.get("patrimonio_liquido", {})

    total_ativo = ativo.get("total", 0) or 0
    total_passivo = passivo.get("total", 0) or 0
    total_pl = pl.get("total", 0) or 0

    passivo_mais_pl = total_passivo + total_pl
    diff = abs(total_ativo - passivo_mais_pl)
    max_val = max(abs(total_ativo), abs(passivo_mais_pl), 0.01)
    tolerance = max_val * 0.01

    result.details = {
        "total_ativo": total_ativo,
        "total_passivo": total_passivo,
        "total_pl": total_pl,
        "passivo_mais_pl": passivo_mais_pl,
        "diferenca": diff,
        "tolerancia": tolerance,
    }

    if diff <= tolerance:
        result.passed = True
        logger.info(
            "Balanço válido: ativo=%.2f, passivo+PL=%.2f",
            total_ativo, passivo_mais_pl,
        )
    else:
        result.errors.append(
            f"Ativo ({total_ativo:,.2f}) != Passivo + PL ({passivo_mais_pl:,.2f}). "
            f"Diferença: {diff:,.2f}."
        )

    return result


def _validate_dre(dados: dict) -> ValidationResult:
    """Valida DRE: resultado líquido coerente com a estrutura."""
    result = ValidationResult()

    linhas = dados.get("linhas", [])
    resultado_liquido = dados.get("resultado_liquido")

    if not linhas:
        result.errors.append("Nenhuma linha encontrada na DRE.")
        return result

    result.details = {
        "total_linhas": len(linhas),
        "resultado_liquido": resultado_liquido,
    }

    if resultado_liquido is None:
        result.warnings.append("Resultado líquido não informado na DRE.")
        result.passed = True
        return result

    subtotais = [l for l in linhas if l.get("is_subtotal")]
    if subtotais:
        ultimo_subtotal = subtotais[-1].get("valor", 0) or 0
        diff = abs(ultimo_subtotal - resultado_liquido)
        max_val = max(abs(resultado_liquido), 0.01)
        tolerance = max_val * 0.01

        if diff > tolerance:
            result.warnings.append(
                f"Último subtotal ({ultimo_subtotal:,.2f}) difere do resultado "
                f"líquido informado ({resultado_liquido:,.2f})."
            )

    result.passed = len(result.errors) == 0
    logger.info("DRE validada: %d linhas, resultado=%.2f", len(linhas), resultado_liquido or 0)
    return result
