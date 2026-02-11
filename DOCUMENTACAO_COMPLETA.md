# Documentação Completa do Sistema de Análise Financeira

## Visão Geral do Ecossistema

Este ecossistema é composto por **dois projetos Python** que trabalham em conjunto para transformar PDFs financeiros brutos em dashboards interativos com análise por IA:

```
File Extractor/
├── projeto_balancetes/    ← PROJETO 1: Extrai dados de PDFs → CSV
└── projeto_analise/       ← PROJETO 2: Analisa CSV → Dashboard + Relatório IA
```

**Fluxo completo:**
```
PDF Financeiro
    │
    ▼
[projeto_balancetes]
    │  PyMuPDF analisa estrutura
    │  Gemini 3 Flash extrai tabelas
    │  Parser unifica e deduplica
    │
    ▼
CSV Unificado (formato brasileiro, separador ;)
    │
    ▼
[projeto_analise]
    │  Parser lê CSV com Decimal
    │  Classificador agrupa contas
    │  Motor calcula indicadores
    │  IA gera narrativa (Gemini ou Claude)
    │  Exporta MD + PDF
    │
    ▼
Dashboard Streamlit + Relatório PDF + Análise Narrativa IA
```

---

# PARTE 1: projeto_balancetes (Extrator de PDFs)

## 1.1 Objetivo

Recebe um PDF de balancete contábil (documento financeiro brasileiro) e extrai **todas** as linhas de tabela, produzindo um CSV limpo e unificado. O desafio principal: PDFs financeiros são visuais (tabelas com bordas, fontes pequenas, centenas de linhas) e ferramentas tradicionais de extração de texto falham.

## 1.2 Estrutura de Arquivos

```
projeto_balancetes/
├── main.py                          # Ponto de entrada CLI
├── requirements.txt                 # docling, google-genai, pymupdf, python-dotenv, pytest
├── .env                             # GEMINI_API_KEY
├── data/
│   ├── input/                       # PDFs para processar
│   └── output/                      # CSV, MD, JSON gerados
├── src/
│   ├── __init__.py
│   ├── orchestrator.py              # Coordenador principal (4 etapas)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── classifier.py            # Classifica PDF → rota de processamento
│   │   ├── docling_agent.py         # Extração local (sem custo)
│   │   └── gemini_agent.py          # Extração via Gemini (com custo)
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── csv_parser.py            # Markdown → CSV unificado
│   │   ├── json_parser.py           # Markdown → JSON estruturado
│   │   └── markdown_parser.py       # Formatação do output em Markdown
│   └── utils/
│       ├── __init__.py
│       ├── config.py                # Config, API keys, logging
│       └── pdf_analyzer.py          # Análise estrutural do PDF com PyMuPDF
└── tests/
    └── test_orchestrator.py
```

## 1.3 Tecnologias e Por Que Cada Uma

### PyMuPDF (fitz) — Análise estrutural + Extração de páginas
**O que é:** Biblioteca Python que manipula PDFs em nível baixo. Acessa texto, imagens, desenhos vetoriais, metadados — tudo sem depender de APIs externas.

**Por que usamos:**
1. **Análise estrutural** (`pdf_analyzer.py`): Antes de decidir *como* processar o PDF, precisamos saber *o que ele contém*. PyMuPDF nos dá:
   - `page.get_text()` → quantidade de caracteres por página
   - `page.get_images()` → quantidade e área de imagens
   - `page.get_drawings()` → linhas vetoriais (indicam tabelas/gráficos)
   - Isso alimenta o classificador que decide a rota de processamento

2. **Extração de páginas** (`gemini_agent.py`): O Gemini tem limite de tokens. Então dividimos o PDF em "lotes" de 5 páginas. PyMuPDF faz isso com `insert_pdf`:
   ```python
   dst = fitz.open()                    # cria PDF vazio
   dst.insert_pdf(src, from_page=0, to_page=4)  # copia páginas 1-5
   pdf_bytes = dst.tobytes()            # converte para bytes
   ```
   Esses bytes são enviados diretamente ao Gemini como `application/pdf`.

### Google Gemini 3 Flash — Extração inteligente de tabelas
**O que é:** LLM multimodal do Google que aceita PDFs nativamente como input. Modelo: `gemini-3-flash-preview`.

**Por que usamos:** PDFs de balancete são visualmente complexos. Texto puro (`page.get_text()`) não preserva a estrutura tabular. O Gemini "vê" o PDF como um humano veria e transcreve as tabelas em Markdown.

**Como funciona o envio nativo de PDF:**
```python
from google.genai import types

# Cria um "Part" com os bytes do PDF
pdf_part = types.Part.from_bytes(
    data=pdf_bytes,           # bytes do sub-PDF (5 páginas)
    mime_type="application/pdf"
)

# Envia PDF + prompt em uma única chamada
response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=[pdf_part, prompt],     # lista: [dados, instrução]
    config={"temperature": 0.1, "max_output_tokens": 200000},
)
```

**Estratégia de batching:**
- `PAGES_PER_BATCH = 5` → cada chamada processa 5 páginas
- PDF de 10 páginas = 2 chamadas à API
- Primeiro lote inclui `"Inclua o cabeçalho da tabela"` no prompt
- Lotes seguintes: `"NÃO inclua cabeçalho — apenas as linhas de dados"`
- No final, concatena todos os resultados: `"\n".join(all_results)`

**Por que 5 páginas e não o PDF inteiro?**
O Gemini 3 Flash tem limite de 65.536 tokens de **output**. Um balancete com 10+ páginas gera mais texto do que esse limite. Dividindo em lotes menores, cada lote tem orçamento completo de output.

**Cálculo de custo:**
```python
# Gemini 3 Flash: $0.15/1M input, $0.60/1M output
input_cost = (input_tokens / 1_000_000) * 0.15
output_cost = (output_tokens / 1_000_000) * 0.60
```

### Docling — Extração local gratuita
**O que é:** Biblioteca da IBM que converte PDFs para texto estruturado localmente, sem API. Usa modelos de layout para detectar tabelas.

**Por que temos (mas não usamos ativamente):** Foi a primeira abordagem testada, mas era lenta e não extraía tabelas financeiras com a mesma precisão do Gemini. Mantemos como fallback gratuito. No `main.py`, forçamos a rota Gemini:
```python
result = orch.process(pdf, force_route=ProcessingRoute.GEMINI)
```

### python-dotenv — Gerenciamento de API keys
**O que é:** Carrega variáveis de ambiente de um arquivo `.env` para `os.environ`.

**Como funciona:**
```python
# .env
GEMINI_API_KEY=AIzaSyBO8Crxc...

# config.py
from dotenv import load_dotenv
load_dotenv()  # carrega .env para os.environ
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
```

Isso evita colocar chaves de API diretamente no código.

## 1.4 Pipeline de Processamento (4 etapas)

### Etapa 1: Análise Estrutural (`pdf_analyzer.py`)

O `analyze_pdf()` abre o PDF com PyMuPDF e analisa **cada página** individualmente:

```python
@dataclass
class PageAnalysis:
    page_number: int
    char_count: int = 0        # quantos caracteres de texto
    word_count: int = 0        # quantas palavras
    image_count: int = 0       # quantas imagens
    image_area_ratio: float = 0.0  # % da página coberta por imagens
    table_count: int = 0       # tabelas detectadas por heurística
    has_drawings: bool = False  # desenhos vetoriais (gráficos)
```

**Detecção de tabelas por heurística de linhas:**
```python
def _detect_tables(page):
    drawings = page.get_drawings()
    horizontal_lines = 0
    vertical_lines = 0
    for drawing in drawings:
        for item in drawing["items"]:
            if item[0] == "l":  # é uma linha
                p1, p2 = item[1], item[2]
                dx = abs(p2.x - p1.x)
                dy = abs(p2.y - p1.y)
                if dx > 50 and dy < 3:     # linha horizontal longa e fina
                    horizontal_lines += 1
                elif dy > 20 and dx < 3:    # linha vertical alta e fina
                    vertical_lines += 1
    # Muitas linhas H e V = tabela
    if horizontal_lines >= 3 and vertical_lines >= 2:
        return max(1, min(horizontal_lines // 5, 5))
```

**Detecção de conteúdo escaneado:**
Se uma página tem imagens mas menos de 50 caracteres de texto, provavelmente é uma imagem escaneada (o texto está "dentro" da imagem). Se >50% das páginas são assim, marca `has_scanned_content = True`.

### Etapa 2: Classificação (`classifier.py`)

Decide a melhor rota de processamento baseado nos scores:

```python
# Score de texto: quão denso em texto é o PDF
text_density = avg_chars_per_page / (min_chars_per_page * 5)

# Score visual: quão visual é o PDF
visual_score = (image_score * 0.4) + (table_score * 0.4) + (drawing_ratio * 0.2)

# Score de texto é penalizado pela presença visual
text_score = text_density * (1.0 - visual_score * 0.3)
```

**Decisão:**
| Condição | Rota | Razão |
|----------|------|-------|
| Conteúdo escaneado | GEMINI | Precisa de "visão" para ler |
| Diferença < 0.15 | HYBRID | Docling + Gemini combinados |
| text > visual | DOCLING | Texto predominante, gratuito |
| visual > text | GEMINI | Tabelas/imagens, precisa IA |

**Na prática:** Balancetes são tabulares → sempre vão para GEMINI. Mas o sistema está preparado para outros tipos de documento.

### Etapa 3: Processamento pelo Agente

O agente Gemini recebe o PDF e retorna tabelas em Markdown. O prompt é crítico:

```
TAREFA: Transcrever TODAS as linhas de tabela financeira presentes neste PDF.

INSTRUÇÕES CRÍTICAS:
- Você DEVE extrair ABSOLUTAMENTE TODAS as linhas visíveis. Sem exceção.
- NÃO resuma. NÃO agrupe. NÃO simplifique. NÃO pule nenhuma conta.
- Cada linha do documento original DEVE aparecer na sua saída.
- Subcontas (1.1.10.200.1, etc.) são TÃO importantes quanto as contas principais.
- Valores numéricos EXATOS: não arredonde, não omita casas decimais.
- Mantenha D (Débito) e C (Crédito) junto aos valores.
```

Sem essas instruções enfáticas, o Gemini tende a "resumir" ou "agrupar" linhas, perdendo subcontas importantes.

### Etapa 4: Exportação

O texto Markdown retornado pelo Gemini é exportado em 3 formatos:

**CSV (`csv_parser.py`):** O parser mais complexo. Faz:
1. `extract_markdown_tables()` — detecta padrões `| col | col |` no Markdown
2. `_unify_and_deduplicate()` — como os lotes se sobrepõem, linhas podem aparecer duplicadas entre o final de um lote e início do próximo. Remove duplicatas por normalização:
   ```python
   def _row_key(row):
       return "|".join(cell.strip().lower() for cell in row)
   ```
3. Salva com delimitador `;` e encoding `utf-8-sig` (BOM para compatibilidade com Excel brasileiro)

**JSON (`json_parser.py`):** Estrutura hierárquica com metadados, seções e tabelas como dicionários.

**Markdown (`markdown_parser.py`):** Adiciona cabeçalho YAML front-matter com metadados.

## 1.5 Padrões de Código Importantes

### Lazy Loading
Todos os clientes de API são inicializados sob demanda:
```python
class GeminiAgent:
    def __init__(self):
        self._client = None  # NÃO inicializa aqui

    def _get_client(self):
        if self._client is None:  # só cria quando precisa
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        return self._client
```
Isso evita importações desnecessárias e erros se a dependência não estiver instalada.

### Dataclasses como Contratos
Cada módulo define dataclasses que servem como "contratos" entre os componentes:
```python
@dataclass
class GeminiResult:
    text: str
    pages_processed: int = 0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None
```
Isso garante que o orquestrador sempre sabe exatamente o que esperar de cada agente.

### Progress Feedback
O Docling usa um spinner animado em thread separada para feedback visual:
```python
class _ProgressSpinner:
    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        while self._running:
            sys.stdout.write(f"\r  {frames[i]} Processando... ({elapsed:.0f}s)")
```
O Gemini usa `\r` (carriage return) para atualizar a mesma linha no terminal.

---

# PARTE 2: projeto_analise (Análise Financeira + Dashboard)

## 2.1 Objetivo

Recebe o CSV gerado pelo `projeto_balancetes`, calcula indicadores financeiros completos, gera um relatório narrativo por IA, e exibe tudo em um dashboard interativo com Streamlit.

## 2.2 Estrutura de Arquivos

```
projeto_analise/
├── app.py                           # Dashboard Streamlit
├── main.py                          # Entrada CLI
├── requirements.txt                 # python-dotenv, google-genai, anthropic, streamlit, plotly, etc.
├── .env                             # GEMINI_API_KEY + ANTHROPIC_API_KEY
├── data/
│   ├── input/                       # CSVs para análise
│   └── output/                      # Relatórios MD + PDF gerados
├── src/
│   ├── __init__.py
│   ├── orchestrator.py              # Pipeline de 7 etapas
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── gemini_agent.py          # Narrativa via Gemini + prompt compartilhado
│   │   └── claude_agent.py          # Narrativa via Claude (mesma interface)
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── csv_parser.py            # Lê CSV brasileiro → dataclasses
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── account_classifier.py    # Mapeia contas → grupos contábeis
│   │   ├── indicators.py            # Calcula todos os indicadores
│   │   └── comparative.py           # Compara Saldo Anterior vs Atual
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── markdown_exporter.py     # Gera relatório MD completo
│   │   └── pdf_exporter.py          # Converte MD → HTML → PDF
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── pages.py                 # Layout das páginas
│   │   ├── charts.py                # Gráficos Plotly
│   │   └── components.py            # Cards KPI, tabelas, narrativa
│   └── utils/
│       ├── __init__.py
│       └── config.py                # Config centralizada
└── tests/
    └── __init__.py
```

## 2.3 Tecnologias e Por Que Cada Uma

### Decimal (stdlib) — Precisão financeira
**O problema:** `float` do Python tem imprecisão de ponto flutuante:
```python
>>> 0.1 + 0.2
0.30000000000000004  # ERRADO para finanças!
```

**A solução:** `decimal.Decimal` usa aritmética de base 10:
```python
>>> Decimal("0.1") + Decimal("0.2")
Decimal('0.3')  # EXATO
```

Todo o sistema usa `Decimal` para valores monetários. Indicadores como liquidez são arredondados com `ROUND_HALF_UP` (arredondamento bancário):
```python
result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

### Streamlit — Dashboard interativo
**O que é:** Framework Python que transforma scripts em apps web. Cada interação do usuário re-executa o script inteiro.

**Por que:** Zero frontend. Tudo em Python. Perfeito para dashboards de dados.

**Conceito fundamental — re-execução:**
```python
# CADA VEZ que o usuário clica em algo, este script roda do início
st.title("Dashboard")
btn = st.button("Analisar")  # retorna True no momento do clique
if btn:
    # isso roda SOMENTE no momento do clique
    result = analisar()
    st.session_state["result"] = result  # persiste entre re-execuções

# isso roda em TODAS as re-execuções
if "result" in st.session_state:
    mostrar_resultado(st.session_state["result"])
```

`st.session_state` é um dicionário que persiste entre re-execuções. Sem ele, o resultado desapareceria assim que o usuário interagisse com qualquer outro widget.

### Plotly — Gráficos interativos
**O que é:** Biblioteca de gráficos que gera visualizações interativas (zoom, hover, pan).

**Como se integra com Streamlit:**
```python
fig = go.Figure(data=[go.Bar(x=nomes, y=valores)])
st.plotly_chart(fig, use_container_width=True)
```

### Anthropic SDK — Claude como alternativa ao Gemini
**O que é:** SDK oficial da Anthropic para acessar modelos Claude.

**Como funciona:**
```python
import anthropic
client = anthropic.Anthropic(api_key=api_key)
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8000,
    system=SYSTEM_PROMPT,       # instrução do sistema (personalidade)
    messages=[{"role": "user", "content": prompt}],
)
texto = response.content[0].text
```

**Diferença vs Gemini:**
- Gemini: system prompt vai junto do conteúdo (`contents=[f"{system}\n\n{user}"]`)
- Claude: system prompt é parâmetro separado (`system=...`, `messages=[...]`)

### markdown2 + xhtml2pdf — Pipeline MD → PDF
**Cadeia de conversão:**
```
Markdown → HTML (markdown2) → PDF (xhtml2pdf)
```

```python
import markdown2
from xhtml2pdf import pisa

# Markdown → HTML
html = markdown2.markdown(md_content, extras=["tables", "fenced-code-blocks"])

# HTML com CSS → PDF
full_html = f"<html><head>{CSS_STYLE}</head><body>{html}</body></html>"
with open("output.pdf", "wb") as f:
    pisa.CreatePDF(full_html, dest=f)
```

O CSS inline garante formatação profissional (cores, tabelas, fontes).

## 2.4 O CSV de Entrada — Formato Brasileiro

O CSV produzido pelo `projeto_balancetes` tem este formato:

```csv
Código;Classificação;Descrição;Saldo Anterior;Débito;Crédito;Saldo Atual
1000;1;ATIVO;4.960.556,92D;1.265.449,23;1.175.575,81;5.050.430,34D
1100;1.1;ATIVO CIRCULANTE;2.272.549,49D;1.259.999,93;1.213.753,76;2.318.795,66D
```

**Particularidades brasileiras:**
- Separador de colunas: `;` (ponto e vírgula)
- Ponto = separador de milhar: `4.960.556`
- Vírgula = separador decimal: `,92`
- Sufixo D/C = natureza contábil: `D` (Débito) ou `C` (Crédito)
- Encoding: `utf-8-sig` (BOM — Byte Order Mark, compatível com Excel)

## 2.5 Parser de CSV (`csv_parser.py`)

### `parse_valor_brasileiro()`
Converte string brasileira para `Decimal`:

```python
def parse_valor_brasileiro("4.960.556,92D"):
    s = "4.960.556,92D"
    natureza = "D"           # extrai sufixo
    s = "4.960.556,92"       # remove sufixo
    s = "4960556.92"         # remove pontos, troca vírgula por ponto
    return (Decimal("4960556.92"), "D")
```

### `valor_com_sinal()`
Converte o par (valor, D/C) para um número com sinal correto:

```python
def valor_com_sinal(valor, natureza, grupo):
    # Ativo (grupo 1): D = positivo, C = negativo
    # Passivo (grupo 2): C = positivo, D = negativo
    # Custos (grupo 3): D = positivo, C = negativo
    # Receitas (grupo 4): C = positivo, D = negativo
```

**Por que isso é necessário?**
Na contabilidade brasileira, D e C não significam "positivo" e "negativo". O significado depende do *tipo* da conta:
- Um Ativo com saldo D (Débito) é positivo (a empresa TEM esse valor)
- Um Passivo com saldo C (Crédito) é positivo (a empresa DEVE esse valor)
- Um Ativo com saldo C significa redução (ex: depreciação)

### `load_balancete()`
Lê o CSV completo e retorna um `Balancete`:

```python
@dataclass
class ContaBalancete:
    codigo: str           # "1100"
    classificacao: str    # "1.1"
    descricao: str        # "ATIVO CIRCULANTE"
    saldo_anterior: Decimal
    natureza_anterior: str
    debito: Decimal
    credito: Decimal
    saldo_atual: Decimal
    natureza_atual: str
    nivel: int            # profundidade: "1.1" = 2, "1.1.3" = 3
    grupo_principal: int  # primeiro dígito: 1=Ativo, 2=Passivo...
```

Também detecta a seção **RESUMO DO BALANCETE** no final do CSV (linhas onde Código e Classificação estão vazios).

## 2.6 Classificador de Contas (`account_classifier.py`)

### O Problema
O CSV tem 375 contas individuais (ex: "Banco do Brasil", "Fornecedor X"). Para calcular indicadores, precisamos agrupar por categoria contábil:
- Todas as contas bancárias → "Disponível"
- Todos os clientes → "Clientes"
- Todos os empréstimos → "Empréstimos CP" ou "LP"

### A Solução: Prefix Matching (Casamento por Prefixo)

Contas contábeis seguem uma hierarquia padronizada pelo plano de contas:
```
1.x     = Ativo
1.1     = Ativo Circulante
1.1.1   = Disponível (caixa, bancos)
1.1.2   = Clientes (contas a receber)
1.1.3   = Estoques
1.2     = Ativo Não Circulante
2.1     = Passivo Circulante
2.3     = Patrimônio Líquido
...
```

O mapa de classificação:
```python
MAPA_CLASSIFICACAO = {
    "1": GrupoContabil.ATIVO_TOTAL,
    "1.1": GrupoContabil.ATIVO_CIRCULANTE,
    "1.1.1": GrupoContabil.DISPONIVEL,
    "1.1.2": GrupoContabil.CLIENTES,
    "1.1.3": GrupoContabil.ESTOQUES,
    "1.2": GrupoContabil.ATIVO_NAO_CIRCULANTE,
    # ... etc
}
```

**Algoritmo de match:** Prefixo mais longo vence.

```python
# Prefixos ordenados do mais longo ao mais curto
_PREFIXOS_ORDENADOS = sorted(MAPA_CLASSIFICACAO.keys(), key=len, reverse=True)
# ["3.2.20.5", "1.1.1", "1.1.2", "1.1.3", "2.1.1", ..., "1.1", "1.2", ..., "1"]

def classificar_conta("1.1.3.200.1"):
    for prefixo in _PREFIXOS_ORDENADOS:
        if "1.1.3.200.1".startswith("1.1.3" + "."):  # match!
            return ESTOQUES
    # "1.1.3" é o prefixo mais longo que casa com "1.1.3.200.1"
```

### Evitando Dupla Contagem

Se somarmos todas as 375 contas, vamos contar várias vezes (a conta "1.1" já inclui "1.1.1" + "1.1.2" + "1.1.3"). A solução: usar **apenas linhas-resumo** — contas cuja classificação é exatamente um dos prefixos do mapa.

```python
for conta in balancete.contas:
    if conta.classificacao in MAPA_CLASSIFICACAO:  # ex: "1.1" está no mapa
        grupo = MAPA_CLASSIFICACAO[conta.classificacao]
        saldos.grupos[grupo] = valor_com_sinal(conta.saldo_atual, ...)
```

### Depreciação para EBITDA

EBITDA precisa da depreciação/amortização, que não tem classificação padronizada. Buscamos por keyword:
```python
for conta in balancete.contas:
    if "DEPRECIA" in conta.descricao.upper() or "AMORTIZA" in conta.descricao.upper():
        deprec_total += abs(val)
```

## 2.7 Cálculo de Indicadores (`indicators.py`)

### Valores Base

Primeiro, extraímos os valores agrupados:
```python
g = saldos.get  # atalho

ac = abs(g(GrupoContabil.ATIVO_CIRCULANTE))        # Ativo Circulante
pc = abs(g(GrupoContabil.PASSIVO_CIRCULANTE))       # Passivo Circulante
pl = g(GrupoContabil.PATRIMONIO_LIQUIDO)             # PL (pode ser negativo!)
disponivel = abs(g(GrupoContabil.DISPONIVEL))        # Caixa + Bancos
estoques = abs(g(GrupoContabil.ESTOQUES))            # Estoques
receita_bruta = abs(g(GrupoContabil.RECEITA_BRUTA))  # Receita
```

### Indicadores de Liquidez

Medem a capacidade da empresa de pagar suas dívidas de curto prazo.

```python
# Liquidez Corrente = AC / PC
# "Para cada R$1 de dívida curto prazo, tenho R$X de ativos"
# > 1.0 = bom (mais ativos que dívidas)
liquidez_corrente = ac / pc  # → 0.6712 (< 1.0 = ATENÇÃO)

# Liquidez Seca = (AC - Estoques) / PC
# Remove estoques (menos líquidos) da conta
liquidez_seca = (ac - estoques) / pc  # → 0.2767

# Liquidez Imediata = Disponível / PC
# Só conta dinheiro em caixa/banco
liquidez_imediata = disponivel / pc  # → 0.0413

# Liquidez Geral = (AC + ANC) / (PC + PNC)
# Considera TODOS os ativos e dívidas
liquidez_geral = (ac + anc) / (pc + pnc)  # → 0.8571
```

### Indicadores de Endividamento

Medem quanto a empresa depende de capital de terceiros.

```python
capital_terceiros = pc + pnc  # total de dívidas

# Endividamento Geral = Capital Terceiros / Ativo Total
# "% do ativo financiado por dívida"
endividamento_geral = capital_terceiros / ativo_total  # → 116.7% (> 100% = PL negativo!)

# Composição do Endividamento = PC / Capital Terceiros
# "% da dívida que é de curto prazo"
composicao_endividamento = pc / capital_terceiros  # → 58.6%

# Grau de Alavancagem = Ativo Total / PL
# "Quantas vezes o ativo supera o capital próprio"
# Se PL negativo → None (não faz sentido calcular)
grau_alavancagem = ativo_total / pl if pl > 0 else None
```

### Indicadores de Rentabilidade

Medem quanto a empresa ganha em relação ao que vende.

```python
# DRE derivado dos saldos
receita_liquida = receita_bruta - deducoes          # Receita - impostos sobre venda
lucro_bruto = receita_liquida - custos              # Receita - custo dos produtos
lucro_operacional = lucro_bruto - despesas_op + receitas_fin  # Operacional
resultado = lucro_operacional - despesas_fin        # Final

# Margem Bruta = Lucro Bruto / Receita Líquida
# "De cada R$1 vendido, quanto sobra após custos diretos"
margem_bruta = lucro_bruto / receita_liquida  # → 30.8%

# ROE = Resultado / PL
# "Retorno sobre o capital do sócio"
roe = resultado / pl if pl > 0 else None

# ROA = Resultado / Ativo Total
# "Retorno sobre todos os ativos"
roa = resultado / ativo_total
```

### Capital de Giro e EBITDA

```python
# CCL = AC - PC
# "Folga financeira de curto prazo"
# Negativo = empresa precisa de mais dinheiro no curto prazo
ccl = ac - pc  # → -R$ 1.136.011,31

# NCG = (Clientes + Estoques) - (Fornecedores + Obrig.Trab. + Obrig.Fisc.)
# "Quanto capital fica preso no ciclo operacional"
ncg = (clientes + estoques) - (fornecedores + obrig_trab + obrig_fisc)

# EBITDA = Lucro Operacional + Depreciação/Amortização
# "Geração de caixa operacional" (antes de juros, impostos, deprec.)
ebitda = lucro_operacional + deprec
```

### Divisão Segura

Todos os indicadores usam `_safe_div` para evitar divisão por zero:
```python
def _safe_div(numerador, denominador):
    if denominador == 0:
        return None  # retorna None, não erro
    return (numerador / denominador).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

## 2.8 Análise Comparativa (`comparative.py`)

Compara indicadores entre **Saldo Anterior** e **Saldo Atual** dentro do mesmo balancete.

```python
def comparar_colunas(saldos):
    # Cria indicadores do período anterior usando grupos_anterior
    ind_anterior = calcular_indicadores(
        SaldosAgrupados(grupos=saldos.grupos_anterior)
    )
    # Indicadores atuais usando grupos normais
    ind_atual = calcular_indicadores(saldos)

    return comparar_periodos(ind_anterior, ind_atual)
```

Cada variação tem uma **tendência direcional** — o sistema sabe que:
- Liquidez maior = melhor (`maior_melhor=True`)
- Endividamento maior = pior (`maior_melhor=False`)

```python
# Se a diferença é positiva E maior é melhor → "melhora"
# Se a diferença é positiva E maior é pior → "piora"
if (diff > 0 and maior_melhor) or (diff < 0 and not maior_melhor):
    tendencia = "melhora"
else:
    tendencia = "piora"
```

## 2.9 Agentes de IA para Narrativa

### System Prompt Compartilhado

Ambos os agentes (Gemini e Claude) usam o mesmo prompt de sistema:

```python
SYSTEM_PROMPT = """
Você é um analista financeiro especializado em empresas brasileiras.
Sua tarefa é produzir um relatório de análise econômico-financeira.

O relatório deve conter:
1. RESUMO EXECUTIVO
2. ANÁLISE DE LIQUIDEZ
3. ANÁLISE DE ENDIVIDAMENTO
4. ANÁLISE DE RENTABILIDADE
5. CAPITAL DE GIRO E EBITDA
6. PONTOS DE ATENÇÃO
7. RECOMENDAÇÕES
"""
```

### User Prompt Dinâmico

O `_build_user_prompt()` formata todos os dados financeiros como texto estruturado:

```
DADOS FINANCEIROS PARA ANÁLISE
========================================

BALANÇO PATRIMONIAL (Saldos Atuais)
  Ativo Total: R$ 5.050.430,34
    Ativo Circulante: R$ 2.318.795,66
      Disponível: R$ 142.769,75
      ...

INDICADORES CALCULADOS
  Liquidez Corrente: 0.6712
  Endividamento Geral: 116.67%
  ...

COMPARATIVO: Saldo Anterior → Saldo Atual
  Liquidez Corrente: 0.6561 → 0.6712 (+2.30%) [melhora]
  ...
```

### Claude vs Gemini — Diferenças de Implementação

**Gemini:**
```python
response = client.models.generate_content(
    model="gemini-3-flash-preview",
    contents=[f"{SYSTEM_PROMPT}\n\n{user_prompt}"],  # tudo junto
    config={"temperature": 0.3, "max_output_tokens": 8000},
)
texto = response.text
# Custo: $0.15/1M input + $0.60/1M output
```

**Claude:**
```python
response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=8000,
    system=SYSTEM_PROMPT,                              # separado!
    messages=[{"role": "user", "content": user_prompt}],
)
texto = response.content[0].text
# Custo: $3.00/1M input + $15.00/1M output (25x mais caro!)
```

O Claude compartilha `SYSTEM_PROMPT` e `_build_user_prompt` importando do `gemini_agent.py` — não duplica código.

## 2.10 Dashboard Streamlit (`app.py`)

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  SIDEBAR                        CONTEÚDO PRINCIPAL      │
│  ┌──────────────┐  ┌──────────────────────────────────┐ │
│  │ File upload  │  │  [Liq. 0,67] [End. 116%]        │ │
│  │ File select  │  │  [Marg. 30,8%] [CCL -1,1M]     │ │
│  │ Modelo IA    │  │                                  │ │
│  │ [Analisar]   │  │  [Gráfico Liquidez] [Composição]│ │
│  │              │  │  [Rentabilidade]  [Endividamento]│ │
│  │ Downloads:   │  │  [DRE Waterfall]                │ │
│  │  📥 MD       │  │                                  │ │
│  │  📥 PDF      │  │  Relatório IA (Markdown)        │ │
│  └──────────────┘  │  Tabela Completa (expandível)   │ │
│                    └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Fluxo de Dados no App

```python
# 1. Sidebar - configuração
with st.sidebar:
    uploaded = st.file_uploader("Upload CSV", type=["csv"])
    model = st.selectbox("Modelo de IA", ["gemini", "claude"])
    analyze_btn = st.button("Analisar")

# 2. Se clicou "Analisar"
if analyze_btn:
    orch = Orchestrator(ai_provider=model)
    result = orch.analyze(csv_path)    # executa pipeline completo
    st.session_state["result"] = result  # salva para persistir

# 3. Se tem resultado salvo, renderiza
if "result" in st.session_state:
    page_overview(
        indicadores=result.indicadores,
        saldos=result.saldos,
        narrativa=result.narrativa,
        indicadores_anterior=indicadores_anterior,
        comparativo=result.comparativo,
    )
```

### Componentes (`components.py`)

**Cards KPI** com `st.metric`:
```python
st.metric(
    label="Liquidez Corrente",
    value="0.6712",          # valor atual
    delta="+0.0151",         # variação vs anterior
)
# Renderiza: "Liquidez Corrente: 0.6712 ▲ +0.0151"
```

**Formatação de valores:**
```python
def _fmt(val, pct=False):
    if pct:
        return f"{float(val) * 100:.2f}%"
    # Converte formato US → BR: 1,234.56 → 1.234,56
    f = f"{float(val):,.2f}"
    return f.replace(",", "X").replace(".", ",").replace("X", ".")
```

**Narrativa em seções expandíveis:**
```python
def render_narrative(texto):
    sections = texto.split("\n## ")
    for section in sections[1:]:
        title = section.split("\n")[0]
        body = "\n".join(section.split("\n")[1:])
        with st.expander(title, expanded=True):
            st.markdown(body)
```

### Gráficos (`charts.py`)

**5 gráficos Plotly:**

1. **Liquidez (barras):** 4 barras coloridas (verde se ≥1.0, vermelho se <1.0) com linha de referência em 1.0
2. **Composição Patrimonial (donut):** AC, ANC, PC, PNC, PL em pizza com furo central
3. **Rentabilidade (barras horizontais):** Margens e ROE/ROA em percentual
4. **Endividamento (barras):** 3 indicadores em percentual
5. **DRE Waterfall:** Gráfico cascata mostrando de Receita Bruta até Resultado Final

**Exemplo — Gráfico Waterfall DRE:**
```python
fig = go.Figure(go.Waterfall(
    x=["Receita Bruta", "Deduções", "Receita Líquida", "Custos", "Lucro Bruto", "Despesas", "Resultado"],
    y=[rec_bruta, -deducoes, 0, -custos, 0, -despesas, 0],
    measure=["absolute", "relative", "total", "relative", "total", "relative", "total"],
    # absolute = valor de partida
    # relative = diferença (pode ser negativa)
    # total = soma acumulada (barra inteira)
))
```

### Paleta de Cores
```python
AZUL = "#2b6cb0"        # Elementos principais
AZUL_CLARO = "#63b3ed"  # Ativo Não Circulante
VERDE = "#38a169"       # Positivo/bom
VERMELHO = "#e53e3e"    # Negativo/ruim
LARANJA = "#dd6b20"     # Passivo Não Circulante
ROXO = "#805ad5"        # Composição Endividamento
CINZA = "#a0aec0"       # Linhas de referência
```

## 2.11 Pipeline do Orchestrator (7 etapas)

```python
class Orchestrator:
    def analyze(self, file_path, output_format=OutputFormat.ALL):
        # [1/7] Validar arquivo
        if not path.exists(): return erro

        # [2/7] Parsear CSV → Balancete (375 contas)
        balancete = load_balancete(path)

        # [3/7] Classificar contas → SaldosAgrupados (24 grupos)
        saldos = agrupar_saldos(balancete)

        # [4/7] Calcular indicadores → IndicadoresFinanceiros
        indicadores = calcular_indicadores(saldos)

        # [5/7] Comparar Saldo Anterior vs Atual → AnaliseComparativa
        comparativo = comparar_colunas(saldos)

        # [6/7] Gerar narrativa com IA (Gemini ou Claude)
        narrative_result = agent.generate_narrative(indicadores, saldos, comparativo)

        # [7/7] Exportar → Markdown + PDF
        report_md = generate_report(indicadores, saldos, narrativa, comparativo)
        save_report(report_md, filename)
        save_as_pdf(report_md, filename)
```

## 2.12 Exportadores

### Markdown (`markdown_exporter.py`)
Gera um relatório completo com:
- Cabeçalho (arquivo, período, data, modelo IA)
- Tabelas de indicadores por categoria
- Tabela comparativa com tendências
- Narrativa da IA

### PDF (`pdf_exporter.py`)
Pipeline de 3 etapas:
```
Markdown → HTML (markdown2) → PDF (xhtml2pdf)
```

O CSS define estilo profissional:
- Cores azuis para cabeçalhos (`#1a365d`, `#2b6cb0`)
- Tabelas com listras zebra (`tr:nth-child(even)`)
- Bordas suaves (`#e2e8f0`)

---

# PARTE 3: Como os Projetos se Conectam

## 3.1 Referência Cruzada

O `projeto_analise` sabe onde o `projeto_balancetes` salva seus CSVs:

```python
# projeto_analise/src/utils/config.py
BALANCETES_OUTPUT_DIR = PROJECT_ROOT.parent / "projeto_balancetes" / "data" / "output"
```

Isso permite:
- **CLI:** `python main.py --from-extractor` busca CSVs automaticamente
- **Dashboard:** sidebar lista CSVs de ambas as pastas (input local + output do extrator)

## 3.2 Formato do CSV como Contrato

O CSV é o "contrato" entre os dois projetos:
- **Separador:** `;` (ponto e vírgula)
- **Encoding:** `utf-8-sig` (BOM)
- **Colunas:** Código, Classificação, Descrição, Saldo Anterior, Débito, Crédito, Saldo Atual
- **Formato numérico:** Brasileiro (ponto=milhar, vírgula=decimal, D/C no final)

## 3.3 Fluxo Completo End-to-End

```
1. Usuário coloca PDF em projeto_balancetes/data/input/
2. python main.py (projeto_balancetes)
   → PyMuPDF analisa → Gemini extrai → CSV em data/output/
3. python main.py --from-extractor (projeto_analise)
   → Lê CSV → Calcula indicadores → IA narra → MD + PDF em data/output/
4. python -m streamlit run app.py (projeto_analise)
   → Dashboard interativo com gráficos, KPIs e relatório IA
```

---

# PARTE 4: Padrões de Arquitetura

## 4.1 Padrão Strategy (Agentes de IA)

Ambos os agentes (Gemini e Claude) implementam a mesma interface:
```python
agent.generate_narrative(indicadores, saldos, comparativo) → NarrativeResult
```

O orchestrator seleciona o agente em runtime:
```python
if self._ai_provider == AIProvider.GEMINI:
    return self._gemini_agent
return self._claude_agent
```

## 4.2 Padrão Pipeline (Orchestrator)

Cada etapa recebe o output da anterior:
```
CSV → Balancete → SaldosAgrupados → IndicadoresFinanceiros → NarrativeResult → Arquivo
```

Se qualquer etapa falha, retorna `AnalysisResult(success=False, error=...)`.

## 4.3 Dataclasses como DTOs

Todas as transferências de dados usam dataclasses tipadas:
```python
@dataclass
class AnalysisResult:
    indicadores: IndicadoresFinanceiros | None = None
    saldos: SaldosAgrupados | None = None
    comparativo: AnaliseComparativa | None = None
    narrativa: str = ""
    success: bool = True
    error: str | None = None
```

Isso dá autocompletar no IDE, type checking estático, e documentação implícita.

## 4.4 Lazy Loading

Todos os clientes de API e converters são carregados sob demanda:
```python
self._client = None  # __init__: não carrega

def _get_client(self):
    if self._client is None:  # primeira chamada: carrega
        self._client = genai.Client(...)
    return self._client  # chamadas seguintes: reutiliza
```

Benefícios:
- Import rápido (não espera conexão com API)
- Não quebra se dependência não está instalada (só quebra quando usa)
- Reutiliza conexão entre chamadas

## 4.5 `from __future__ import annotations`

Presente em TODOS os arquivos. Permite usar sintaxe moderna de tipos:
```python
# Sem o import:
def foo(x: Optional[int]) -> Union[str, None]:  # verbose

# Com o import (PEP 604):
def foo(x: int | None) -> str | None:  # limpo
```

O import faz o Python tratar todas as anotações como strings (avaliadas tardiamente), permitindo usar `X | Y` mesmo em versões mais antigas do Python.

---

# PARTE 5: Dependências Completas

## projeto_balancetes
| Pacote | Versão | Função |
|--------|--------|--------|
| `pymupdf` (fitz) | — | Análise estrutural de PDF, extração de páginas |
| `google-genai` | — | SDK do Google Gemini para extração de tabelas |
| `docling` | — | Extração local de texto (fallback gratuito) |
| `python-dotenv` | — | Carrega API keys do `.env` |
| `pytest` | — | Framework de testes |

## projeto_analise
| Pacote | Versão | Função |
|--------|--------|--------|
| `python-dotenv` | — | Carrega API keys do `.env` |
| `google-genai` | — | SDK do Gemini para narrativa |
| `anthropic` | — | SDK do Claude para narrativa alternativa |
| `streamlit` | — | Dashboard web interativo |
| `plotly` | — | Gráficos interativos (barras, pizza, waterfall) |
| `markdown2` | — | Converte Markdown para HTML (para PDF) |
| `xhtml2pdf` | — | Converte HTML para PDF |
| `pytest` | — | Framework de testes |

---

# PARTE 6: Referência Rápida de Comandos

```bash
# === PROJETO 1: Extrator de PDFs ===
cd projeto_balancetes
python main.py                        # processa todos os PDFs em data/input/
python main.py balancete.pdf          # processa arquivo específico

# === PROJETO 2: Análise Financeira ===
cd projeto_analise
python main.py --from-extractor                  # analisa CSVs do extrator
python main.py "arquivo.csv" --model gemini      # Gemini
python main.py "arquivo.csv" --model claude      # Claude
python main.py "arquivo.csv" --output markdown   # só Markdown (sem PDF)
python -m streamlit run app.py                   # Dashboard web
```

---

# PARTE 7: Indicadores Calculados — Referência

| Indicador | Fórmula | Benchmark | Resultado VFR |
|-----------|---------|-----------|---------------|
| Liquidez Corrente | AC / PC | > 1.0 | 0.6712 |
| Liquidez Seca | (AC - Estoques) / PC | > 1.0 | 0.2767 |
| Liquidez Imediata | Disponível / PC | > 0.2 | 0.0413 |
| Liquidez Geral | (AC + ANC) / (PC + PNC) | > 1.0 | 0.8571 |
| Endividamento Geral | (PC + PNC) / Ativo Total | < 60% | 116.67% |
| Composição Endivid. | PC / (PC + PNC) | < 50% | 58.63% |
| Margem Bruta | Lucro Bruto / Receita Líq. | Setor | 30.80% |
| Margem Operacional | Lucro Operac. / Receita Líq. | > 0 | Calculado |
| Margem Líquida | Resultado / Receita Líq. | > 0 | Calculado |
| ROE | Resultado / PL | > Selic | N/D (PL negativo) |
| ROA | Resultado / Ativo Total | > 0 | Calculado |
| CCL | AC - PC | > 0 | -R$ 1.136.011,31 |
| EBITDA | Lucro Operac. + Deprec. | > 0 | Calculado |
