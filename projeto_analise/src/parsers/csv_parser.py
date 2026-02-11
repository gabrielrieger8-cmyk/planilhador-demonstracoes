"""Parser de CSV de balancetes financeiros.

Lê CSVs produzidos pelo projeto extrator, parseando formato brasileiro
(ponto para milhar, vírgula para decimal) e sufixos D/C.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.utils.config import logger


@dataclass
class ContaBalancete:
    """Uma linha do balancete (uma conta contábil)."""

    codigo: str
    classificacao: str
    descricao: str
    saldo_anterior: Decimal
    natureza_anterior: str  # "D", "C" ou ""
    debito: Decimal
    credito: Decimal
    saldo_atual: Decimal
    natureza_atual: str  # "D", "C" ou ""
    nivel: int  # profundidade hierárquica (qtd de pontos + 1)
    grupo_principal: int  # primeiro dígito: 1=Ativo, 2=Passivo, 3=Custos, 4=Receitas


@dataclass
class ResumoBalancete:
    """Seção de resumo no final do balancete."""

    itens: dict[str, tuple[Decimal, str]]  # descricao -> (valor, natureza)


@dataclass
class Balancete:
    """Balancete completo parseado."""

    contas: list[ContaBalancete]
    resumo: ResumoBalancete
    arquivo_origem: str
    periodo: str  # extraído do nome do arquivo


def parse_valor_brasileiro(valor_str: str) -> tuple[Decimal, str]:
    """Parseia valor em formato brasileiro com sufixo D/C.

    Exemplos:
        '4.960.556,92D' -> (Decimal('4960556.92'), 'D')
        '0,00'          -> (Decimal('0.00'), '')
        '748.896,68D'   -> (Decimal('748896.68'), 'D')

    Args:
        valor_str: Valor como string no formato brasileiro.

    Returns:
        Tupla (valor_decimal, natureza).
    """
    s = valor_str.strip()
    if not s:
        return Decimal("0"), ""

    # Remove ** de formatação bold do markdown
    s = s.replace("**", "")

    # Extrai sufixo D ou C
    natureza = ""
    if s.endswith("D"):
        natureza = "D"
        s = s[:-1]
    elif s.endswith("C"):
        natureza = "C"
        s = s[:-1]

    # Remove pontos (separador de milhar) e troca vírgula por ponto
    s = s.replace(".", "").replace(",", ".")

    try:
        valor = Decimal(s)
    except InvalidOperation:
        logger.warning("Valor não parseável: '%s'", valor_str)
        return Decimal("0"), ""

    return valor, natureza


def valor_com_sinal(valor: Decimal, natureza: str, grupo: int) -> Decimal:
    """Converte valor para formato com sinal baseado na natureza da conta.

    Convenção contábil:
    - Ativo (1.x): D = positivo, C = negativo
    - Passivo (2.x): C = positivo, D = negativo
    - Custos/Despesas (3.x): D = positivo, C = negativo
    - Receitas (4.x): C = positivo, D = negativo

    Args:
        valor: Valor absoluto.
        natureza: 'D', 'C' ou ''.
        grupo: Primeiro dígito da classificação.

    Returns:
        Valor com sinal correto.
    """
    if valor == 0 or not natureza:
        return valor

    # Grupos com natureza devedora (D = positivo)
    if grupo in (1, 3):
        return valor if natureza == "D" else -valor
    # Grupos com natureza credora (C = positivo)
    return valor if natureza == "C" else -valor


def extrair_periodo(filename: str) -> str:
    """Extrai período do nome do arquivo.

    Exemplos:
        'VFR Balancete 112025.csv' -> '11/2025'
        'balancete_jan2024.csv'    -> 'jan2024'

    Args:
        filename: Nome do arquivo.

    Returns:
        String representando o período.
    """
    nome = Path(filename).stem

    # Padrão MMYYYY (ex: 112025)
    match = re.search(r"(\d{2})(\d{4})", nome)
    if match:
        mes, ano = match.groups()
        return f"{mes}/{ano}"

    return nome


def load_balancete(file_path: str | Path) -> Balancete:
    """Carrega e parseia um CSV de balancete.

    Args:
        file_path: Caminho para o arquivo CSV.

    Returns:
        Balancete parseado com todas as contas e resumo.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
        ValueError: Se o formato do CSV for inválido.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    logger.info("Carregando balancete: %s", path.name)

    contas: list[ContaBalancete] = []
    resumo_itens: dict[str, tuple[Decimal, str]] = {}
    in_resumo = False

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")

        # Pula cabeçalho
        header = next(reader, None)
        if header is None:
            raise ValueError(f"Arquivo vazio: {path}")

        for row in reader:
            if len(row) < 7:
                continue

            codigo, classificacao, descricao = row[0], row[1], row[2]
            str_anterior, str_debito, str_credito, str_atual = (
                row[3], row[4], row[5], row[6]
            )

            # Detecta seção de resumo (Código e Classificação vazios)
            if not codigo.strip() and not classificacao.strip():
                desc = descricao.strip().replace("**", "")
                if desc:
                    in_resumo = True
                    val, nat = parse_valor_brasileiro(str_atual)
                    resumo_itens[desc] = (val, nat)
                continue

            if in_resumo:
                continue

            # Parseia valores
            saldo_ant, nat_ant = parse_valor_brasileiro(str_anterior)
            debito, _ = parse_valor_brasileiro(str_debito)
            credito, _ = parse_valor_brasileiro(str_credito)
            saldo_at, nat_at = parse_valor_brasileiro(str_atual)

            # Calcula nível hierárquico
            nivel = classificacao.count(".") + 1 if classificacao else 0

            # Grupo principal (primeiro caractere da classificação)
            grupo = 0
            if classificacao:
                try:
                    grupo = int(classificacao[0])
                except ValueError:
                    pass

            contas.append(ContaBalancete(
                codigo=codigo.strip(),
                classificacao=classificacao.strip(),
                descricao=descricao.strip(),
                saldo_anterior=saldo_ant,
                natureza_anterior=nat_ant,
                debito=debito,
                credito=credito,
                saldo_atual=saldo_at,
                natureza_atual=nat_at,
                nivel=nivel,
                grupo_principal=grupo,
            ))

    periodo = extrair_periodo(path.name)
    logger.info(
        "Balancete carregado: %d contas, período %s",
        len(contas), periodo,
    )

    return Balancete(
        contas=contas,
        resumo=ResumoBalancete(itens=resumo_itens),
        arquivo_origem=str(path),
        periodo=periodo,
    )


def load_multiple(file_paths: list[str | Path]) -> list[Balancete]:
    """Carrega múltiplos balancetes.

    Args:
        file_paths: Lista de caminhos para CSVs.

    Returns:
        Lista de Balancetes parseados.
    """
    return [load_balancete(fp) for fp in file_paths]
