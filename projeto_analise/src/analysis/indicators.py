"""Cálculo de indicadores financeiros.

Calcula liquidez, estrutura de capital, capital de giro, prazos/ciclo,
rentabilidade e EBITDA a partir dos saldos agrupados.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from src.analysis.account_classifier import GrupoContabil, SaldosAgrupados


def _safe_div(numerador: Decimal, denominador: Decimal) -> Decimal | None:
    """Divisão segura — retorna None se denominador é zero."""
    if denominador == 0:
        return None
    return (numerador / denominador).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass
class ParamsCAPM:
    """Parâmetros do CAPM fornecidos pelo usuário no sidebar."""

    rf: Decimal = Decimal("0")    # Taxa livre de risco (%)
    rm: Decimal = Decimal("0")    # Retorno esperado do mercado (%)
    beta: Decimal = Decimal("1")  # Beta da empresa
    rp: Decimal = Decimal("0")    # Prêmio de risco-país (%)


@dataclass
class IndicadoresFinanceiros:
    """Conjunto completo de indicadores financeiros."""

    # --- Liquidez ---
    liquidez_corrente: Decimal | None = None
    liquidez_seca: Decimal | None = None
    liquidez_imediata: Decimal | None = None
    liquidez_geral: Decimal | None = None

    # --- Estrutura de Capital ---
    investimentos_totais: Decimal | None = None
    passivo_oneroso: Decimal | None = None
    passivo_nao_oneroso: Decimal | None = None
    investimentos_liquidos: Decimal | None = None
    capitais_proprios: Decimal | None = None
    capitais_terceiros: Decimal | None = None
    participacao_capital_proprio: Decimal | None = None
    participacao_capital_terceiros: Decimal | None = None
    ke: Decimal | None = None
    ki: Decimal | None = None
    wacc: Decimal | None = None

    # --- Endividamento (legado, mantido para compatibilidade) ---
    endividamento_geral: Decimal | None = None
    composicao_endividamento: Decimal | None = None
    grau_alavancagem: Decimal | None = None

    # --- Rentabilidade ---
    margem_bruta: Decimal | None = None
    margem_contribuicao: Decimal | None = None
    margem_operacional: Decimal | None = None
    margem_liquida: Decimal | None = None
    nopat: Decimal | None = None
    roi: Decimal | None = None
    roa: Decimal | None = None
    roe: Decimal | None = None
    gaf: Decimal | None = None
    ebitda: Decimal | None = None
    margem_ebitda: Decimal | None = None

    # --- Capital de Giro ---
    capital_circulante_liquido: Decimal | None = None
    ativo_ciclico: Decimal | None = None
    passivo_ciclico: Decimal | None = None
    necessidade_capital_giro: Decimal | None = None

    # --- Prazos e Ciclo Financeiro (em dias) ---
    pmp: Decimal | None = None
    pmr: Decimal | None = None
    pmre: Decimal | None = None
    ciclo_financeiro: Decimal | None = None

    # --- Valores DRE derivados (para contexto) ---
    receita_bruta: Decimal | None = None
    receita_liquida: Decimal | None = None
    lucro_bruto: Decimal | None = None
    lucro_operacional: Decimal | None = None  # EBIT
    lucro_liquido: Decimal | None = None
    resultado_periodo: Decimal | None = None

    # --- Avisos contextuais ---
    aviso_estoques: str = ""
    aviso_fornecedores: str = ""


def calcular_indicadores(saldos: SaldosAgrupados) -> IndicadoresFinanceiros:
    """Calcula indicadores financeiros (wrapper de compatibilidade).

    Args:
        saldos: Saldos agrupados por grupo contábil.

    Returns:
        IndicadoresFinanceiros preenchido.
    """
    return calcular_indicadores_completos(saldos)


def calcular_indicadores_completos(
    saldos: SaldosAgrupados,
    params_capm: ParamsCAPM | None = None,
    dias_periodo: int = 30,
    mapeamento_ia: dict | None = None,
) -> IndicadoresFinanceiros:
    """Calcula todos os indicadores financeiros.

    Args:
        saldos: Saldos agrupados por grupo contábil.
        params_capm: Parâmetros CAPM (opcional, para KE/KI/WACC).
        dias_periodo: Dias do período (30=mensal, 90=trimestral, etc.).
        mapeamento_ia: JSON da IA para detecção de hierarquia DRE.

    Returns:
        IndicadoresFinanceiros completo.
    """
    g = saldos.get
    D = Decimal

    # =================================================================
    # Valores base — Balanço Patrimonial
    # =================================================================
    ativo_total = abs(g(GrupoContabil.ATIVO_TOTAL))
    ac = abs(g(GrupoContabil.ATIVO_CIRCULANTE))
    disponivel = abs(g(GrupoContabil.DISPONIBILIDADES))
    clientes = abs(g(GrupoContabil.CLIENTES))
    estoques = abs(g(GrupoContabil.ESTOQUES))
    anc = abs(g(GrupoContabil.ATIVO_NAO_CIRCULANTE))
    imobilizado = abs(g(GrupoContabil.IMOBILIZADO))
    intangivel = abs(g(GrupoContabil.INTANGIVEL))

    pc = abs(g(GrupoContabil.PASSIVO_CIRCULANTE))
    pnc = abs(g(GrupoContabil.PASSIVO_NAO_CIRCULANTE))
    pl = g(GrupoContabil.PATRIMONIO_LIQUIDO)  # pode ser negativo
    fornecedores = abs(g(GrupoContabil.FORNECEDORES))

    emprestimos_cp = abs(g(GrupoContabil.EMPRESTIMOS_FINANCIAMENTOS_CP))
    emprestimos_lp = abs(g(GrupoContabil.EMPRESTIMOS_LP))
    parcelamentos = abs(g(GrupoContabil.PARCELAMENTOS_TRIBUTARIOS))

    # =================================================================
    # Valores base — DRE
    # =================================================================
    receita_bruta = abs(g(GrupoContabil.RECEITA_BRUTA))
    deducoes = abs(g(GrupoContabil.DEDUCOES_RECEITA))
    custos = abs(g(GrupoContabil.CUSTOS_SERVICOS))
    despesas_op = abs(g(GrupoContabil.DESPESAS_OPERACIONAIS))
    despesas_adm = abs(g(GrupoContabil.DESPESAS_ADMINISTRATIVAS))
    despesas_fin = abs(g(GrupoContabil.DESPESAS_FINANCEIRAS))
    despesas_com = abs(g(GrupoContabil.DESPESAS_COMERCIAIS))
    receitas_fin = abs(g(GrupoContabil.RECEITAS_FINANCEIRAS))
    deprec_atual = abs(g(GrupoContabil.DEPRECIACAO_AMORTIZACAO))
    deprec_anterior = abs(saldos.get_anterior(GrupoContabil.DEPRECIACAO_AMORTIZACAO))
    deprec_periodo = abs(deprec_atual - deprec_anterior)

    # Detectar hierarquia: despesas_financeiras é sub-conta de despesas_operacionais?
    dre = (mapeamento_ia or {}).get("dre", {})
    desp_op_classif = dre.get("despesas_operacionais") or ""
    desp_adm_classif = dre.get("despesas_administrativas") or ""
    desp_fin_classif = dre.get("despesas_financeiras") or ""
    desp_com_classif = dre.get("despesas_comerciais") or ""

    fin_dentro_de_op = (
        desp_fin_classif and desp_op_classif
        and desp_fin_classif.startswith(desp_op_classif + ".")
    )
    fin_dentro_de_adm = (
        desp_fin_classif and desp_adm_classif
        and desp_fin_classif.startswith(desp_adm_classif + ".")
    )
    com_dentro_de_op = (
        desp_com_classif and desp_op_classif
        and desp_com_classif.startswith(desp_op_classif + ".")
    )

    # Total de despesas operacionais (excluindo financeiras e comerciais separadas)
    if despesas_op > 0:
        total_despesas_op = despesas_op
    elif despesas_adm > 0:
        total_despesas_op = despesas_adm
        if not fin_dentro_de_adm and despesas_com > 0:
            total_despesas_op += despesas_com
    else:
        total_despesas_op = D("0")

    # DRE derivado
    receita_liquida = receita_bruta - deducoes
    lucro_bruto = receita_liquida - custos

    # EBIT: exclui despesas financeiras do total operacional
    if fin_dentro_de_op or fin_dentro_de_adm:
        # Financeiras estão dentro do total → subtrair para obter EBIT
        ebit = lucro_bruto - total_despesas_op + despesas_fin
    else:
        # Financeiras são separadas → total operacional já exclui financeiras
        ebit = lucro_bruto - total_despesas_op
        if despesas_com > 0 and not com_dentro_de_op:
            ebit -= despesas_com

    # Lucro Líquido = EBIT + Receitas Financeiras - Despesas Financeiras
    lucro_liquido = ebit + receitas_fin - despesas_fin

    # =================================================================
    # Indicadores
    # =================================================================
    ind = IndicadoresFinanceiros()

    # --- Valores DRE ---
    ind.receita_bruta = receita_bruta
    ind.receita_liquida = receita_liquida
    ind.lucro_bruto = lucro_bruto
    ind.lucro_operacional = ebit
    ind.lucro_liquido = lucro_liquido
    ind.resultado_periodo = lucro_liquido

    # =================================================================
    # 1. LIQUIDEZ
    # =================================================================
    ind.liquidez_corrente = _safe_div(ac, pc)
    ind.liquidez_seca = _safe_div(ac - estoques, pc)
    ind.liquidez_imediata = _safe_div(disponivel, pc)
    # Liquidez Geral = (AC + ANC - Imobilizado - Intangível) / (PC + PNC)
    if (pc + pnc) > 0:
        ind.liquidez_geral = _safe_div(
            ac + anc - imobilizado - intangivel, pc + pnc,
        )

    # =================================================================
    # 2. ESTRUTURA DE CAPITAL
    # =================================================================
    passivo_oneroso = emprestimos_cp + emprestimos_lp + parcelamentos
    capital_terceiros_total = pc + pnc
    passivo_nao_oneroso = capital_terceiros_total - passivo_oneroso
    investimentos_liquidos = ativo_total - passivo_nao_oneroso

    ind.investimentos_totais = ativo_total
    ind.passivo_oneroso = passivo_oneroso
    ind.passivo_nao_oneroso = passivo_nao_oneroso
    ind.investimentos_liquidos = investimentos_liquidos
    ind.capitais_proprios = pl
    ind.capitais_terceiros = passivo_oneroso

    if investimentos_liquidos > 0:
        ind.participacao_capital_proprio = _safe_div(abs(pl), investimentos_liquidos)
        ind.participacao_capital_terceiros = _safe_div(
            passivo_oneroso, investimentos_liquidos,
        )

    # Endividamento legado
    ind.endividamento_geral = _safe_div(capital_terceiros_total, ativo_total)
    ind.composicao_endividamento = _safe_div(pc, capital_terceiros_total)
    if pl > 0:
        ind.grau_alavancagem = _safe_div(ativo_total, pl)

    # CAPM: KE, KI, WACC
    if params_capm is not None:
        p = params_capm
        # KE = RF + (RM - RF) × β + RP
        ind.ke = (
            p.rf + (p.rm - p.rf) * p.beta + p.rp
        ).quantize(D("0.0001"), rounding=ROUND_HALF_UP)

        # KI = Desp.Financeiras × (1 - 0,34) / Passivo Oneroso
        if passivo_oneroso > 0:
            ind.ki = _safe_div(despesas_fin * D("0.66"), passivo_oneroso)

        # WACC = (Part.Ke × Ke) + (Part.Ki × Ki)
        if (
            ind.participacao_capital_proprio is not None
            and ind.participacao_capital_terceiros is not None
            and ind.ke is not None
            and ind.ki is not None
        ):
            ind.wacc = (
                ind.participacao_capital_proprio * ind.ke
                + ind.participacao_capital_terceiros * ind.ki
            ).quantize(D("0.0001"), rounding=ROUND_HALF_UP)

    # =================================================================
    # 3. CAPITAL DE GIRO
    # =================================================================
    ind.capital_circulante_liquido = ac - pc
    ind.ativo_ciclico = ac - disponivel
    ind.passivo_ciclico = pc - emprestimos_cp
    ind.necessidade_capital_giro = ind.ativo_ciclico - ind.passivo_ciclico

    # =================================================================
    # 4. PRAZOS E CICLO FINANCEIRO
    # =================================================================
    DIAS = D(str(dias_periodo))
    cmv = custos  # CMV = Custos dos Serviços/Produtos

    # Avisos de estoques e fornecedores
    if estoques == 0:
        ind.aviso_estoques = "Sem estoques registrados"
    elif estoques < D("1000"):
        ind.aviso_estoques = "Estoques com valor baixo"

    if fornecedores == 0:
        ind.aviso_fornecedores = "Sem fornecedores registrados"
    elif fornecedores < D("1000"):
        ind.aviso_fornecedores = "Fornecedores com valor baixo"

    # Só calcular prazos quando a conta existe
    if cmv > 0 and fornecedores > 0:
        ind.pmp = _safe_div(fornecedores * DIAS, cmv)
    if cmv > 0 and estoques > 0:
        ind.pmre = _safe_div(estoques * DIAS, cmv)
    if receita_bruta > 0 and clientes > 0:
        ind.pmr = _safe_div(clientes * DIAS, receita_bruta)

    # Ciclo Financeiro = PMR + PMRE - PMP
    pmr_v = ind.pmr or D("0")
    pmre_v = ind.pmre or D("0")
    pmp_v = ind.pmp or D("0")
    if ind.pmr is not None or ind.pmre is not None:
        ind.ciclo_financeiro = (pmr_v + pmre_v - pmp_v).quantize(
            D("0.0001"), rounding=ROUND_HALF_UP,
        )

    # =================================================================
    # 5. RENTABILIDADE
    # =================================================================
    if receita_bruta > 0:
        ind.margem_bruta = _safe_div(lucro_bruto, receita_bruta)
        # Margem de Contribuição = (Lucro Bruto - Desp.Comerciais) / Receita Bruta
        ind.margem_contribuicao = _safe_div(
            lucro_bruto - despesas_com, receita_bruta,
        )
        # Margem Operacional = EBIT / Receita Bruta
        ind.margem_operacional = _safe_div(ebit, receita_bruta)
        # Margem Líquida = Lucro Líquido / Receita Bruta
        ind.margem_liquida = _safe_div(lucro_liquido, receita_bruta)

    # NOPAT = EBIT × (1 - 0,34), mas se EBIT < 0 não há benefício fiscal
    if ebit < 0:
        ind.nopat = ebit.quantize(D("0.01"), rounding=ROUND_HALF_UP)
    else:
        ind.nopat = (ebit * D("0.66")).quantize(D("0.01"), rounding=ROUND_HALF_UP)

    # ROI = NOPAT / Investimentos Líquidos
    if investimentos_liquidos > 0 and ind.nopat is not None:
        ind.roi = _safe_div(ind.nopat, investimentos_liquidos)

    # ROA = Lucro Líquido / Ativo Total
    if ativo_total > 0:
        ind.roa = _safe_div(lucro_liquido, ativo_total)

    # ROE = Lucro Líquido / PL
    if pl > 0:
        ind.roe = _safe_div(lucro_liquido, pl)

    # GAF = ROE / ROI (Grau de Alavancagem Financeira)
    if ind.roi is not None and ind.roe is not None and ind.roi != 0:
        ind.gaf = _safe_div(ind.roe, ind.roi)

    # EBITDA = EBIT + Depreciação do período (variação: atual - anterior)
    ind.ebitda = ebit + deprec_periodo
    if receita_bruta > 0:
        ind.margem_ebitda = _safe_div(ind.ebitda, receita_bruta)

    return ind
