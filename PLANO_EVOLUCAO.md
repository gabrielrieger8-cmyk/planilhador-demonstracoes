# Plano de Evolução: Empresa + Mapeamento + Excel + Validação

## Contexto

O projeto atual tem dois sistemas independentes conectados via filesystem:
- **projeto_balancetes** (`projeto_balancetes/`): PDF → 4 CSVs (analítico, sintético, com/sem sinal)
- **projeto_analise** (`projeto_analise/`): CSV → Dashboard Streamlit com indicadores financeiros

Problemas atuais:
- Não existe conceito de "empresa" — cada análise é stateless
- O mapeamento IA (Claude classifica ~30 contas-chave) é refeito a cada execução ($)
- Não há persistência entre períodos (não acumula mês a mês)
- A conversão de sinais só trata formato D/C puro (Formato A)
- Não há validação contábil dos dados

**Objetivo**: Adicionar empresa persistente, mapeamento salvo/editável, Excel multi-período, validação contábil, detecção de formato de sinais, e dois modos de extração (rápido/completo).

---

## FASE 1: Fundação — Empresa + Mapeamento Persistente

### 1a. Novo: `projeto_analise/src/empresa.py`

```python
@dataclass
class Empresa:
    nome: str
    cnpj: str | None = None
    diretorio: Path  # data/empresas/{nome}/

def criar_empresa(nome, cnpj=None) -> Empresa
def listar_empresas() -> list[Empresa]
def carregar_empresa(nome) -> Empresa | None
```

Estrutura de diretório por empresa:
```
data/empresas/
  VFR/
    mapeamento.json
    historico/
      11-2025.json
      12-2025.json
    excel/
      VFR_Analise.xlsx
```

### 1b. Novo: `projeto_analise/src/mapping/__init__.py` + `mapping_store.py`

```python
def salvar_mapeamento(empresa, mapeamento_ia: dict) -> Path
def carregar_mapeamento(empresa) -> dict | None  # retorna {"bp": {...}, "dre": {...}} ou None
def atualizar_mapeamento(empresa, changes: dict) -> dict
```

JSON salvo (mapeamento.json):
```json
{
  "empresa": "VFR",
  "data_criacao": "2025-11-15T10:30:00",
  "data_atualizacao": "2025-12-01T14:20:00",
  "bp": { "ativo_total": "1", "..." : "..." },
  "dre": { "receita_bruta": "4.1.1", "..." : "..." },
  "linhas_customizadas": [],
  "formato_detectado": null
}
```

`carregar_mapeamento()` retorna apenas `{"bp": {...}, "dre": {...}}` para manter compatibilidade com `agrupar_saldos()`.

### 1c. Modificar: `projeto_analise/src/utils/config.py`

Adicionar:
```python
EMPRESAS_DIR = DATA_DIR / "empresas"
EMPRESAS_DIR.mkdir(parents=True, exist_ok=True)
```

### 1d. Modificar: `projeto_analise/src/orchestrator.py`

Adicionar parâmetro `empresa: Empresa | None = None` em `analyze()`.

Lógica no passo de classificação:
1. Se `empresa` fornecida, tenta `carregar_mapeamento(empresa)`
2. Se mapeamento existe, usa direto (pula chamada IA — economia de custo)
3. Se não existe, chama IA normalmente e depois `salvar_mapeamento(empresa, resultado)`

### 1e. Modificar: `projeto_analise/app.py`

Sidebar: seletor de empresa (dropdown + "Nova Empresa") antes do seletor de CSV.
Mostrar status: "Mapeamento salvo em DD/MM/YYYY" ou "Primeira análise".
Passar `empresa` para o orchestrator.

### Arquivos tocados na Fase 1:
- NOVO: `src/empresa.py`
- NOVO: `src/mapping/__init__.py`
- NOVO: `src/mapping/mapping_store.py`
- MODIFICAR: `src/utils/config.py` (1 linha)
- MODIFICAR: `src/orchestrator.py` (lógica de cache de mapeamento)
- MODIFICAR: `app.py` (sidebar empresa)

---

## FASE 2: Editor de Mapeamento (UI)

### 2a. Novo: `projeto_analise/src/dashboard/tab_mapeamento.py`

Tela com duas colunas:

**Coluna esquerda**: Plano de contas da empresa (somente agrupadoras)
- Conta é agrupadora se tem pelo menos 1 filho no balancete
- Filtra ~72 contas para ~25-30 agrupadoras
- Checkbox opcional "Mostrar níveis mais profundos"
- Exibe: Classificação | Descrição | Saldo Atual

**Coluna direita**: Estrutura padrão DRE + BP com dropdowns
- Cada slot (ex: "Disponibilidades") tem um `st.selectbox` com as contas agrupadoras
- Pré-preenchido com sugestão da IA
- Usuário pode trocar qualquer atribuição
- Botão "Salvar Mapeamento" persiste no JSON

```python
def _get_aggregator_accounts(balancete) -> list[ContaBalancete]:
    """Retorna contas que tem pelo menos um filho."""

def render_mapeamento(balancete, mapeamento_ia, empresa=None) -> dict | None:
    """Renderiza editor. Retorna mapping atualizado se usuário salvar."""
```

### 2b. Linhas calculadas customizáveis na DRE

No editor de mapeamento, seção "Linhas Customizadas DRE":
- Builder visual: `[variável1] [operador +/-/*/÷] [variável2 ou constante]`
- Posição: "Inserir após [dropdown de linhas DRE]"
- Variáveis disponíveis: receita_bruta, receita_liquida, custos, lucro_bruto, despesas_op, ebit, despesas_fin, receitas_fin, depreciacao_periodo, ir_csll, lucro_liquido
- Salvo em `linhas_customizadas` do mapeamento.json

Avaliação das fórmulas no `tab_demonstracoes.py`:
```python
def _avaliar_linhas_customizadas(indicadores, linhas) -> dict[str, Decimal]
```

### 2c. Modificar: `projeto_analise/app.py`

Adicionar tab "Mapeamento" entre Demonstrações e Relatório:
```python
tab_dash, tab_metricas, tab_demonstracoes, tab_mapeamento, tab_relatorio = st.tabs([...])
```

### Arquivos tocados na Fase 2:
- NOVO: `src/dashboard/tab_mapeamento.py`
- MODIFICAR: `app.py` (nova tab)
- MODIFICAR: `src/dashboard/tab_demonstracoes.py` (renderizar linhas customizadas)

---

## FASE 3: Sistema de Validação

### 3a. Novo: `projeto_analise/src/analysis/validators.py`

```python
class StatusValidacao(Enum): OK, ALERTA, ERRO

@dataclass
class ResultadoValidacao:
    status: StatusValidacao
    categoria: str      # "equacao_patrimonial", "sinal", "hierarquia", etc.
    mensagem: str

@dataclass
class RelatorioValidacao:
    resultados: list[ResultadoValidacao]
    tem_erro: bool      # property
    tem_alerta: bool    # property
```

**Momento 1 — Validação do mapeamento inicial:**
```python
def validar_mapeamento_inicial(saldos, mapeamento_ia, balancete, tolerancia=1.00) -> RelatorioValidacao
```

Checks:
1. Ativo Total ≈ AC + ANC (tolerância < R$1,00)
2. Passivo+PL ≈ PC + PNC + PL
3. Ativo Total ≈ Passivo Total (equação patrimonial)
4. Hierarquia coerente (filho começa com prefixo do pai)
5. Sem classificações duplicadas entre chaves
6. Contas obrigatórias existem (ativo_total, passivo_total, patrimonio_liquido, receita_bruta)
7. Sinais corretos (receita_bruta > 0, custos <= 0, deduções <= 0, depreciação <= 0)

**Momento 2 — Validação de período subsequente:**
```python
def validar_periodo_subsequente(saldos_atual, saldos_anterior, mapeamento, balancete_atual, balancete_anterior, threshold=0.50) -> RelatorioValidacao
```

Checks:
1. Conta mapeada ausente no novo CSV
2. Conta nova no CSV que não está no mapeamento
3. Descrição da conta mudou
4. Saldo anterior do mês atual ≠ saldo atual do mês passado
5. Variação anormal > 50% (threshold configurável)
6. + todas as checks do Momento 1

**Fluxo**: ERRO bloqueia pipeline (mostra alerta, pede revisão). ALERTA permite continuar.

### 3b. Modificar: `projeto_analise/src/orchestrator.py`

Inserir validação entre agrupamento e cálculo de indicadores.
Adicionar campo `validacao: RelatorioValidacao | None` em `AnalysisResult`.

### 3c. Modificar: `projeto_analise/src/dashboard/components.py`

Adicionar função `render_validacao(validacao)` que mostra alertas coloridos expansíveis no topo do Dashboard.

### Arquivos tocados na Fase 3:
- NOVO: `src/analysis/validators.py`
- MODIFICAR: `src/orchestrator.py` (passo de validação)
- MODIFICAR: `src/dashboard/components.py` (render_validacao)
- MODIFICAR: `app.py` (exibir validação no dashboard)

---

## FASE 4: Detecção de Formato de Sinais (projeto_balancetes)

### 4a. Modificar: `projeto_balancetes/src/parsers/csv_parser.py`

**Novo enum:**
```python
class FormatoBalancete(Enum):
    FORMAT_A = "dc_puro"           # D/C sufixos, sem negativos (mais comum)
    FORMAT_C = "sinal_e_dc"        # Sinal + D/C (segundo mais comum)
    FORMAT_B = "sinal_somente"     # Só sinais, sem D/C
    FORMAT_D = "passivo_negativo"  # Passivo com sinal negativo (raro)
```

**Nova função de detecção:**
```python
def detectar_formato(rows: list[list[str]]) -> FormatoBalancete:
    # Escaneia colunas 3 e 6 (Saldo Anterior, Saldo Atual):
    # - flag_dc: tem sufixo D ou C?
    # - flag_negativo: tem valores com "-"?
    # - passivo_total_sign: classificação "2" é positivo ou negativo?
    #
    # Decisão:
    #   dc=True,  neg=False → FORMAT_A
    #   dc=True,  neg=True  → FORMAT_C
    #   dc=False, neg=True, passivo>=0 → FORMAT_B
    #   dc=False, neg=True, passivo<0  → FORMAT_D
    #   fallback → FORMAT_A
```

**Nova função de conversão com formato:**
```python
def _valor_com_sinal_formatado(valor, natureza, grupo, formato) -> float:
    # FORMAT_A: lógica atual (D/C → sinal por grupo)
    # FORMAT_C: ignorar D/C, confiar no sinal já presente
    # FORMAT_B: valor já está correto, pass through
    # FORMAT_D: multiplicar grupo 2 por -1
```

**Modificar `save_signed_csv()`**: chamar `detectar_formato()` antes e passar formato para `_convert_rows_to_signed()`.

### Arquivos tocados na Fase 4:
- MODIFICAR: `projeto_balancetes/src/parsers/csv_parser.py`

---

## FASE 5: Dois Modos de Extração (projeto_balancetes)

### 5a. Modificar: `projeto_balancetes/src/agents/gemini_agent.py`

**Novo enum e prompt:**
```python
class ExtractionMode(Enum):
    RAPIDO = "rapido"
    COMPLETO = "completo"

FINANCIAL_PROMPT_RAPIDO = """
... (mesmo que FINANCIAL_PROMPT mas com instrução adicional):
"Para contas de CLIENTES e FORNECEDORES, extraia APENAS a linha totalizadora.
 NÃO extraia sub-contas individuais."
"""
```

Modificar `GeminiAgent.process()`: aceitar `extraction_mode` e selecionar prompt correto.

### 5b. Modificar: `projeto_balancetes/src/orchestrator.py` + `main.py`

Passar `extraction_mode` pela pipeline. Adicionar argumento CLI `--modo rapido|completo`.

### Arquivos tocados na Fase 5:
- MODIFICAR: `projeto_balancetes/src/agents/gemini_agent.py`
- MODIFICAR: `projeto_balancetes/src/orchestrator.py`
- MODIFICAR: `projeto_balancetes/main.py`

---

## FASE 6: Excel Multi-período (projeto_analise)

### 6a. Novo: `projeto_analise/src/exporters/excel_exporter.py`

Dependência: `openpyxl` (adicionar ao `requirements.txt`).

```python
def criar_workbook(empresa) -> Path
    # Cria Excel com 3 sheets: DRE, BP, Indicadores
    # Cada sheet tem labels nas linhas (coluna A) e períodos nas colunas (B, C, D...)

def atualizar_workbook(empresa, periodo, indicadores, saldos, mapeamento) -> Path
    # Abre Excel existente (ou cria se não existe)
    # Encontra ou cria coluna para o período
    # Preenche valores da DRE, BP e Indicadores
    # Se período já existe, sobrescreve
```

Sheets:
- **DRE**: Receita Bruta, Deduções, =Rec.Líquida, Custos, =Lucro Bruto, Desp.Op., =EBIT, Desp/Rec.Fin, =LAIR, IR, =LL, + linhas customizadas
- **BP**: Ativo (AC + ANC com sub-itens), Passivo (PC + PNC com sub-itens), PL — com Anterior e Atual por período
- **Indicadores**: Todos os 40+ indicadores por período

### 6b. Novo: `projeto_analise/src/dashboard/tab_excel.py`

Preview das 3 sheets em tabs Streamlit + botão de download `.xlsx`.

### 6c. Modificar: `projeto_analise/app.py`

Adicionar tab "Excel":
```python
tab_dash, tab_metricas, tab_demonstracoes, tab_mapeamento, tab_excel, tab_relatorio = st.tabs([...])
```

### Arquivos tocados na Fase 6:
- NOVO: `src/exporters/excel_exporter.py`
- NOVO: `src/dashboard/tab_excel.py`
- MODIFICAR: `app.py` (nova tab)
- MODIFICAR: `requirements.txt` (openpyxl)

---

## FASE 7: Auto-fill Pipeline

### 7a. Modificar: `projeto_analise/src/orchestrator.py`

Após calcular indicadores, automaticamente:
1. `atualizar_workbook(empresa, periodo, indicadores, saldos, mapeamento)`
2. Salvar histórico: `empresa/historico/{periodo}.json` com indicadores-chave e saldos
3. Se histórico anterior existe, rodar `validar_periodo_subsequente()`

### 7b. Histórico em JSON

Salvar após cada análise bem-sucedida:
```json
{
  "periodo": "11/2025",
  "arquivo": "VFR Balancete 112025_sintetico_sinal.csv",
  "saldos_grupos": { "ATIVO_TOTAL": "5050430.34", "..." : "..." },
  "indicadores_resumo": { "ebitda": "-24234.10", "..." : "..." }
}
```

Usado para comparação no Momento 2 da validação.

### Arquivos tocados na Fase 7:
- MODIFICAR: `src/orchestrator.py` (auto-fill + histórico)
- MODIFICAR: `src/mapping/mapping_store.py` (funções de histórico)

---

## Grafo de Dependências

```
FASE 1 (Empresa + Mapeamento)  ← pré-requisito de tudo
   |
   v
FASE 2 (Editor UI) ──→ FASE 3 (Validação)
                              |
FASE 4 (Sinais) ←── independente, pode rodar em paralelo
FASE 5 (Modos)  ←── independente, pode rodar em paralelo
                              |
                              v
                        FASE 6 (Excel)
                              |
                              v
                        FASE 7 (Auto-fill)
```

---

## Resumo de Arquivos

### projeto_analise — NOVOS (7):
| Arquivo | Fase |
|---|---|
| `src/empresa.py` | 1 |
| `src/mapping/__init__.py` | 1 |
| `src/mapping/mapping_store.py` | 1 |
| `src/dashboard/tab_mapeamento.py` | 2 |
| `src/analysis/validators.py` | 3 |
| `src/exporters/excel_exporter.py` | 6 |
| `src/dashboard/tab_excel.py` | 6 |

### projeto_analise — MODIFICADOS (6):
| Arquivo | Fases |
|---|---|
| `src/utils/config.py` | 1 |
| `src/orchestrator.py` | 1, 3, 7 |
| `app.py` | 1, 2, 3, 6 |
| `src/dashboard/components.py` | 3 |
| `src/dashboard/tab_demonstracoes.py` | 2 |
| `requirements.txt` | 6 |

### projeto_balancetes — MODIFICADOS (4):
| Arquivo | Fase |
|---|---|
| `src/parsers/csv_parser.py` | 4 |
| `src/agents/gemini_agent.py` | 5 |
| `src/orchestrator.py` | 5 |
| `main.py` | 5 |

---

## Verificação (por fase)

**Fase 1**: Criar empresa "VFR" → analisar CSV → mapeamento salvo em JSON → re-analisar → pula IA, usa cache.

**Fase 2**: Abrir tab Mapeamento → ver agrupadoras na esquerda → editar dropdown → salvar → recalcular indicadores.

**Fase 3**: Analisar VFR → ver validação no topo (OK para equação patrimonial) → forçar erro (trocar ativo_total) → ver ERRO.

**Fase 4**: Testar com CSV formato A (VFR) → detectar FORMAT_A → valores corretos. Testar com CSV formato C → ignorar D/C → valores corretos.

**Fase 5**: `python main.py --modo rapido arquivo.pdf` → CSV sem sub-contas de clientes/fornecedores.

**Fase 6**: Analisar dois períodos → Excel com 2 colunas → download funciona.

**Fase 7**: Analisar período novo → Excel atualiza automaticamente → histórico salvo → validação cruzada com período anterior.
