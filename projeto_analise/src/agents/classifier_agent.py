"""Agente classificador de contas contábeis via IA.

Usa Claude Sonnet para identificar quais contas do balancete correspondem
a cada item padrão da DRE e do Balanço Patrimonial, retornando um JSON
estruturado que o Python usa para montar as demonstrações e calcular indicadores.
"""

from __future__ import annotations

import json
import re
import time

from src.utils.config import ANTHROPIC_API_KEY, config, logger

CLASSIFICATION_PROMPT = """\
A partir deste CSV de balancete contábil, identifique qual classificação
hierárquica (coluna "Classificação", ex: 1.1, 2.1.3) corresponde a cada
item padrão da DRE e do Balanço Patrimonial.

O CSV tem colunas: Código;Classificação;Descrição da conta;Saldo Anterior;Débito;Crédito;Saldo Atual
Use a coluna CLASSIFICAÇÃO (código hierárquico com pontos), NÃO o Código sequencial.

Retorne APENAS um JSON válido no formato abaixo. Para itens que não existem
nesta empresa, use null.

CHAVES DO BALANÇO PATRIMONIAL (bp):
- ativo_total: Conta raiz do Ativo (ex: "ATIVO")
- ativo_circulante: Ativo Circulante
- disponibilidades: Disponível / Caixa e Equivalentes
- clientes: Clientes / Contas a Receber
- estoques: Estoques / Mercadorias (null se não há)
- outros_creditos_cp: Outros Créditos de Curto Prazo
- despesas_antecipadas: Custos/Despesas Antecipadas
- ativo_nao_circulante: Ativo Não Circulante
- investimentos: Investimentos
- imobilizado: Imobilizado (sem depreciação)
- depreciacao_amortizacao: Depreciação/Amortização ACUMULADA (conta com "(-)" ou "DEPRECIA")
- intangivel: Intangível
- passivo_total: Conta raiz do Passivo (ex: "PASSIVO")
- passivo_circulante: Passivo Circulante
- emprestimos_financiamentos_cp: Empréstimos e Financiamentos de Curto Prazo
- fornecedores: Fornecedores
- obrigacoes_fiscais: Obrigações Tributárias / Fiscais CP
- parcelamentos_cp: Parcelamentos tributários no Passivo Circulante (null se não há)
- obrigacoes_trabalhistas: Obrigações Trabalhistas e Previdenciárias CP
- outras_obrigacoes_cp: Outras Obrigações CP
- passivo_nao_circulante: Passivo Não Circulante
- emprestimos_lp: Empréstimos de Longo Prazo
- parcelamentos_lp: Parcelamentos tributários no Passivo Não Circulante (null se não há)
- outros_debitos_lp: Outros Débitos de Longo Prazo (null se não há)
- patrimonio_liquido: Patrimônio Líquido
- capital_social: Capital Social
- lucros_prejuizos: Lucros ou Prejuízos Acumulados

CHAVES DA DRE (dre):
- receita_bruta: Receita Bruta de Vendas/Serviços
- deducoes_receita: Deduções da Receita (impostos sobre vendas)
- custos_servicos: Custos dos Serviços/Produtos Vendidos
- despesas_operacionais: Despesas Operacionais (conta-pai, se existir)
- despesas_administrativas: Despesas Administrativas
- despesas_financeiras: Despesas Financeiras (mesmo que sub-conta de Adm)
- despesas_comerciais: Despesas Comerciais / com Vendas (null se não há)
- receitas_financeiras: Receitas Financeiras
- outras_receitas: Outras Receitas Operacionais (null se não há)
- ir_csll: IR e CSLL (null se não há)

REGRAS:
- Use a classificação hierárquica E a descrição para decidir
- Cada chave deve mapear para UMA classificação do CSV
- Para depreciação, use a conta ACUMULADA (normalmente com "(-)" na descrição)
- Parcelamentos CP e LP devem ser identificados SEPARADAMENTE
- Despesas Financeiras: mesmo que seja sub-conta de Despesas Administrativas/Operacionais, identifique separadamente
- Se uma conta não existe nesta empresa, use null
- NÃO inclua contas do resumo do balancete (linhas sem Código/Classificação)

EXEMPLO de resposta (empresa VFR):
```json
{{
  "bp": {{
    "ativo_total": "1",
    "ativo_circulante": "1.1",
    "disponibilidades": "1.1.1",
    "clientes": "1.1.2",
    "estoques": null,
    "outros_creditos_cp": "1.1.3",
    "despesas_antecipadas": "1.1.6",
    "ativo_nao_circulante": "1.2",
    "investimentos": "1.2.3",
    "imobilizado": "1.2.4",
    "depreciacao_amortizacao": "1.2.40.7",
    "intangivel": "1.2.5",
    "passivo_total": "2",
    "passivo_circulante": "2.1",
    "emprestimos_financiamentos_cp": "2.1.1",
    "fornecedores": "2.1.30",
    "obrigacoes_fiscais": "2.1.4",
    "parcelamentos_cp": "2.1.40.2",
    "obrigacoes_trabalhistas": "2.1.5",
    "outras_obrigacoes_cp": "2.1.6",
    "passivo_nao_circulante": "2.2",
    "emprestimos_lp": "2.2.10.1",
    "parcelamentos_lp": "2.2.10.4",
    "outros_debitos_lp": "2.2.10.6",
    "patrimonio_liquido": "2.3",
    "capital_social": "2.3.1",
    "lucros_prejuizos": "2.3.5"
  }},
  "dre": {{
    "receita_bruta": "4.1.1",
    "deducoes_receita": "4.1.2",
    "custos_servicos": "3.1.6",
    "despesas_operacionais": "3.2",
    "despesas_administrativas": "3.2.2",
    "despesas_financeiras": "3.2.20.5",
    "despesas_comerciais": null,
    "receitas_financeiras": "4.1.3",
    "outras_receitas": null,
    "ir_csll": null
  }}
}}
```

BALANCETE:
{csv_text}
"""

# Chaves válidas para validação do JSON
CHAVES_BP = {
    "ativo_total", "ativo_circulante", "disponibilidades", "clientes",
    "estoques", "outros_creditos_cp", "despesas_antecipadas",
    "ativo_nao_circulante", "investimentos", "imobilizado",
    "depreciacao_amortizacao", "intangivel",
    "passivo_total", "passivo_circulante",
    "emprestimos_financiamentos_cp", "fornecedores",
    "obrigacoes_fiscais", "parcelamentos_cp",
    "obrigacoes_trabalhistas", "outras_obrigacoes_cp",
    "passivo_nao_circulante", "emprestimos_lp",
    "parcelamentos_lp", "outros_debitos_lp",
    "patrimonio_liquido", "capital_social", "lucros_prejuizos",
}

CHAVES_DRE = {
    "receita_bruta", "deducoes_receita", "custos_servicos",
    "despesas_operacionais", "despesas_administrativas",
    "despesas_financeiras", "despesas_comerciais",
    "receitas_financeiras", "outras_receitas", "ir_csll",
}


def classify_accounts(
    csv_text: str,
    api_key: str | None = None,
) -> dict:
    """Identifica contas-chave do balancete usando Claude Sonnet.

    Args:
        csv_text: Conteúdo completo do CSV sintético com sinal.
        api_key: Chave da API Anthropic (usa config se None).

    Returns:
        Mapeamento {"bp": {...}, "dre": {...}} com classificações hierárquicas.
        Retorna {} em caso de erro.
    """
    key = api_key or ANTHROPIC_API_KEY
    if not key:
        logger.warning("ANTHROPIC_API_KEY não configurada para classificação.")
        return {}

    start = time.time()
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        prompt = CLASSIFICATION_PROMPT.format(csv_text=csv_text)

        response = client.messages.create(
            model=config.classifier_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text if response.content else ""
        result = _parse_json_response(text)

        elapsed = time.time() - start
        tokens_in = getattr(response.usage, "input_tokens", 0)
        tokens_out = getattr(response.usage, "output_tokens", 0)
        cost = (tokens_in / 1_000_000) * 3.00 + (tokens_out / 1_000_000) * 15.00

        bp_count = sum(1 for v in result.get("bp", {}).values() if v)
        dre_count = sum(1 for v in result.get("dre", {}).values() if v)
        logger.info(
            "Mapeamento IA: %d contas BP + %d contas DRE em %.1fs ($%.4f)",
            bp_count, dre_count, elapsed, cost,
        )
        return result

    except Exception as exc:
        logger.error("Erro na classificação IA: %s", exc)
        return {}


def _parse_json_response(text: str) -> dict:
    """Parseia o JSON retornado pela IA."""
    # Tenta extrair JSON de dentro de blocos ```json ... ```
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Tenta encontrar o JSON diretamente
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            logger.error("Nenhum JSON encontrado na resposta da IA.")
            return {}

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("JSON inválido na resposta da IA: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.error("Resposta da IA não é um dict.")
        return {}

    # Valida estrutura
    result = {"bp": {}, "dre": {}}

    for key, val in data.get("bp", {}).items():
        if key in CHAVES_BP:
            result["bp"][key] = val if val else None
        else:
            logger.warning("Chave BP desconhecida ignorada: %s", key)

    for key, val in data.get("dre", {}).items():
        if key in CHAVES_DRE:
            result["dre"][key] = val if val else None
        else:
            logger.warning("Chave DRE desconhecida ignorada: %s", key)

    return result
