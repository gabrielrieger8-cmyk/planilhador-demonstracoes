# Resumo Completo — Projeto Controladoria Plus (Conversor de Balancetes)

## Objetivo

**Controladoria Plus** é um conversor de PDFs de balancetes contábeis brasileiros para CSV/XLSX, com interface web. É o **primeiro projeto** de uma pipeline de 3:

1. **Conversor** (ESTE PROJETO — pronto) → Extrai dados de PDFs de balancetes via IA
2. **Classificador/Consolidador** (PRÓXIMO) → Classifica e consolida balancetes em uma mesma planilha ou banco de dados
3. **Dashboard** → Analisa demonstrações e cria visualizações

## Arquitetura e Stack

| Camada | Tecnologia |
|--------|-----------|
| Core compartilhado | **controladoria_core** — pacote Python instalável (`pip install -e .`) |
| Backend Web | **FastAPI** (`app.py`) com SSE para progresso em tempo real |
| CLI | **Rich** (`cli.py`) — modo direto + interativo com cores e progress bars |
| IA | **Google Gemini API** (`google-genai`) — modelos: `gemini-2.0-flash`, `gemini-2.5-flash`, `gemini-3-flash-preview` |
| PDF | **PyMuPDF** (fitz) para manipulação, extração de texto e OCR fallback (Tesseract) |
| Excel | **openpyxl** para geração de .xlsx profissional |
| Frontend Web | HTML/CSS/JS vanilla (SPA, sem framework) |

## Estrutura do Projeto (Monorepo)

```
Controladoria_Plus/
├── .venv/                              # Virtual environment compartilhado
├── pyproject.toml                      # Editable install do controladoria_core
├── CLAUDE.md                           # Instruções para o Claude Code
├── knowledge/                          # Referências RAG (compartilhado entre projetos)
│
├── controladoria_core/                 # Pacote compartilhado (ex-src/)
│   ├── __init__.py
│   ├── orchestrator.py                 # Orquestrador principal
│   ├── agents/
│   │   ├── __init__.py
│   │   └── gemini_agent.py             # Agente Gemini principal
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── csv_parser.py               # Parser e pós-processamento
│   ├── exporters/
│   │   ├── __init__.py
│   │   ├── xlsx_builder.py             # Excel profissional com fórmulas SUM
│   │   ├── sign_logic.py               # Lógica de sinais D/C → +/-
│   │   ├── hierarchy.py                # Árvore de classificação contábil
│   │   └── reference_extractor.py      # Sistema RAG
│   └── utils/
│       ├── __init__.py
│       └── config.py                   # Configurações centralizadas (configure())
│
├── projeto_balancetes/                 # Projeto Web (FastAPI)
│   ├── .env                            # GEMINI_API_KEY
│   ├── app.py                          # FastAPI backend
│   ├── main.py                         # Ponto de entrada CLI simples
│   ├── test_xlsx_builder.py            # Testes
│   ├── requirements.txt
│   ├── data/input/, data/output/
│   ├── static/                         # Frontend HTML/JS/CSS
│   ├── SESSION_LOG.md
│   └── RESUMO_PROJETO.md
│
└── projeto_balancetes_cli/             # Projeto CLI (Rich)
    ├── .env                            # GEMINI_API_KEY
    ├── cli.py                          # CLI com Rich (modo direto + interativo)
    ├── requirements.txt                # rich
    └── data/input/, data/output/
```

### Bootstrap dos projetos

Cada projeto consumidor deve chamar `configure()` antes de usar o core:

```python
from controladoria_core.utils.config import configure
configure(project_root=Path(__file__).parent)
```

Isso seta `PROJECT_ROOT`, `DATA_DIR`, `INPUT_DIR`, `OUTPUT_DIR`, `KNOWLEDGE_DIR` e carrega `.env`.

## Repositório Git

- **GitHub**: `https://github.com/gabrielrieger8-cmyk/Controladoria-Plus.git`
- **Branch**: `master`

## Fluxo de Dados Completo

```
1. Usuário arrasta PDFs na interface web (drag & drop)
2. POST /upload → salva PDFs em temp, conta páginas via PyMuPDF → cria Job
3. POST /convert → ThreadPoolExecutor processa PDFs em paralelo
   Para CADA PDF:
   a) Orchestrator.process() chama GeminiAgent.process()
   b) GeminiAgent divide o PDF em 1 página por chamada API
   c) Para cada página:
      - Extrai texto OCR local (PyMuPDF get_text → fallback Tesseract)
      - Conta contas via regex (2 padrões)
      - Envia PDF + prompt + OCR guide + contagem ao Gemini
      - Recebe tabela Markdown com 8 colunas
      - Anti-truncamento: detecta MAX_TOKENS e pede continuações (até 3)
      - Deduplicação intra-batch entre continuações
   d) csv_parser processa o Markdown:
      - extract_markdown_tables() → parseia tabelas
      - _unify_and_deduplicate() → 3 níveis de dedup
      - _postprocess_agrupadoras() → 2 camadas (hierarquia + soma)
      - _fix_tipo_in_numeric_columns() → realinha A/D
      - _fix_dc_in_numeric_columns() → limpa D/C de Débito/Crédito
      - _split_natureza_columns() → separa D/C em colunas próprias
   e) Gera CSV (;) + XLSX básico
4. GET /progress → SSE stream em tempo real
5. GET /results → retorna arquivos + preview_data
6. Frontend renderiza preview com tabs e tabela HTML
7. POST /convert-xlsx → gera XLSX Profissional consolidado
   - BalanceteXlsxBuilder reordena colunas, converte D/C → +/-
   - Gera fórmulas SUM para agrupadoras (com validação)
   - Formata com conditional formatting, Tables, freeze panes
   - Consolida múltiplos PDFs como abas no mesmo arquivo
```

## Componentes Principais

### 1. `gemini_agent.py` — Agente de Extração (1009 linhas)

O coração do sistema. Envia PDFs para a API Gemini e recebe dados estruturados.

**Fluxo principal** (`GeminiAgent.process()`):
1. Divide o PDF em batches de **1 página por chamada** (`PAGES_PER_BATCH = 1`)
2. Para cada página: extrai texto OCR local → conta contas via regex → envia para Gemini com texto OCR como "mapa" + contagem de contas
3. Anti-truncation: detecta `MAX_TOKENS` no finish_reason e pede continuações (até 3)
4. Deduplicação intra-batch entre continuações
5. Retry com backoff exponencial para rate limits (429)

**Constantes importantes**:
- `PAGES_PER_BATCH = 1` — uma chamada API por página (máxima precisão)
- `OCR_TEXT_THRESHOLD = 50` — mínimo de caracteres para considerar texto válido
- `MAX_OCR_CHARS_PER_BATCH = 15000` — limite de texto OCR no prompt

**Sistema OCR Guide**: Extrai texto de cada página via `get_text()` (ou Tesseract OCR como fallback), injeta no prompt do Gemini como referência para evitar omissões de contas. Três camadas: get_text() → Tesseract get_textpage_ocr() → text_fallback.

**Contagem local de contas**: Regex-based (Pattern 1: "CODIGO CLASSIFICACAO", Pattern 2: código numérico standalone). Se OCR não produz texto, fallback para contagem via Gemini (`_gemini_count_accounts()`).

**Prompt principal** (`FINANCIAL_PROMPT`): Instrui o Gemini a:
- Extrair ABSOLUTAMENTE TODAS as linhas sem omissão
- Gerar tabela Markdown com 8 colunas: Código, Classificação, Descrição, Tipo(A/D), SA, Débito, Crédito, SAT
- Classificar Tipo: A=agrupadora (totalizadora), D=detalhe (folha)
- Manter valores exatos em formato brasileiro (ponto=milhar, vírgula=decimal)
- Descartar coluna "Tipo" original do PDF e gerar nova classificação A/D

**Sistema RAG**: Injeta referência de XLSX validado no prompt do Gemini (se houver em `knowledge/`) para guiar a extração com base em padrões já aprovados pelo controller.

**Balancete Sintético**: `classify_synthetic()` envia o plano de contas ao Gemini para identificar quais classificações devem aparecer na versão resumida, com cobertura obrigatória de todos os grupos (1-4).

**Modelos suportados**: `gemini-2.0-flash`, `gemini-2.5-flash` e `gemini-3-flash-preview`, selecionáveis em runtime.

### 2. `csv_parser.py` — Parser e Pós-Processamento (1217 linhas)

Toda a transformação de dados acontece aqui.

**Pipeline de pós-processamento** (ordem):
1. `extract_markdown_tables()` → Parseia tabelas Markdown (suporta 4 formatos de delimitador |)
2. `_unify_and_deduplicate()` → Merge de todas as tabelas, remove duplicatas em 3 níveis:
   - Headers repetidos
   - Linhas exatamente iguais
   - Linhas com mesmo Código+Classificação
3. `_postprocess_agrupadoras()` → Detecção de agrupadoras em 2 camadas:
   - **Camada 1 (Hierarquia)**: Matching de prefixo de classificação (ex: "3.2" é pai de "3.2.1")
   - **Camada 2 (Soma numérica)**: Verifica se SA, Deb, Cred, SAT da linha ≈ soma das linhas filhas consecutivas (tolerância 1%, mínimo 2 filhos, 2+ de 4 colunas devem bater)
4. `_fix_tipo_in_numeric_columns()` → Corrige A/D encontrados em colunas numéricas (realinhamento)
5. `_fix_dc_in_numeric_columns()` → Remove sufixo D/C de colunas Débito/Crédito
6. `_split_natureza_columns()` → Separa "47.649.092,98D" em valor + coluna "Natureza" separada

**Layout de colunas**:
- 8 colunas base: Código, Classificação, Descrição, Tipo, Saldo Anterior, Débito, Crédito, Saldo Atual
- 10 colunas após split natureza: adiciona Natureza SA, Natureza SAT

**`save_as_csv()`**: Gera CSV com delimitador `;` e encoding `utf-8-sig`

**`save_as_xlsx()`**: Gera Excel básico formatado com:
- Header: negrito, fundo azul (#2F5496), texto branco
- Agrupadoras (Tipo=A): negrito + fundo cinza (#E8E8E8)
- Colunas numéricas alinhadas à direita
- Bordas finas, freeze panes, auto-filtro
- Larguras de coluna otimizadas

**`save_synthetic_csv()`**: Filtra contas para balancete sintético + calcula resultado do período (saldo_atual - saldo_anterior com sinal).

**`save_signed_csv()`**: Converte D/C para +/- com convenção contábil (Ativo: D=+/C=-, Passivo/Desp/Rec: C=+/D=-).

**Valores**: Formato brasileiro (ponto=milhar, vírgula=decimal), sufixos D/C para natureza.

### 3. `orchestrator.py` — Orquestrador (203 linhas)

Orquestrador simplificado (apenas Gemini).

- `Orchestrator.process()`: Valida PDF → envia para Gemini (com referência RAG se disponível) → exporta CSV+XLSX → retorna `ProcessingResult` com `preview_rows` nos detalhes
- `_export()`: Retorna `tuple[list[Path], list[list[str]]]` — gera CSV, depois XLSX com as mesmas `unified_rows`, passa `unified_rows` de volta para preview
- Também salva `{filename}_raw.txt` com output bruto do Gemini para debug

### 4. `app.py` — Backend FastAPI (1026 linhas)

**17 endpoints**:

| Endpoint | Função |
|----------|--------|
| `GET /` | Serve página principal |
| `POST /upload` | Recebe PDFs, cria job |
| `POST /convert/{job_id}` | Inicia conversão em background com ThreadPoolExecutor |
| `GET /progress/{job_id}` | SSE stream com progresso real-time |
| `GET /results/{job_id}` | Lista de arquivos (csv/xlsx), custos, tempos, e `preview_data` |
| `GET /download/{job_id}/{filename}` | Download individual (media type dinâmico) |
| `GET /download-all/{job_id}` | ZIP com todos os CSV e XLSX |
| `DELETE /job/{job_id}/{filename}` | Remove PDF antes da conversão |
| `GET /models` / `POST /set-model` | Toggle de modelo Gemini |
| `POST /convert-xlsx/{job_id}` | Gera XLSX Profissional consolidado (todas as abas em um único arquivo) |
| `POST /detect-signs/{job_id}/{base_name}` | Detecta modo de sinais D/C nos dados |
| `POST /upload-xlsx` | Upload de XLSX existente para adicionar abas |
| `POST /resubmit/{job_id}/{base_name}` | Reenvia PDF com prompt de correção ao Gemini |
| `POST /save-reference/{job_id}` | Extrai padrão do XLSX validado e salva como referência |
| `POST /upload-reference` | Upload de XLSX corrigido como referência |
| `GET /references` / `DELETE /references/{filename}` | Lista e remove referências |
| `POST /chat-reference` | Chat com IA para ajustar referências existentes |

**`Job` dataclass**: Inclui `preview_data: dict[str, list[list[str]]]` para preview rows por PDF.

**Processamento paralelo**: `ThreadPoolExecutor` com workers configuráveis (1-36), stagger delay de 2s entre workers para evitar burst de API.

**Resubmissão**: Permite reenviar um PDF com prompt de correção, gerando versão v2, v3, etc.

### 5. `xlsx_builder.py` — Excel Profissional (846 linhas)

Classe `BalanceteXlsxBuilder` para gerar Excel de qualidade profissional:

- **Reordena colunas**: remove Tipo visível, coloca como coluna oculta (J)
- **Números como float**: parseia valores brasileiros para float nativo do Excel com `BR_NUMBER_FORMAT = '#,##0.00'`
- **Fórmulas SUM**: para agrupadoras, gera `=SUM(D5,D8,D12)` referenciando filhos diretos
- **Validação de SUM**: compara |SUM(filhos)| com |valor original| — se diverge (>1%), mantém valor do PDF com Comment explicativo
- **Comments**: valor original do Gemini como nota no celular, aviso de divergência quando soma não confere
- **Conditional Formatting**: `$J2="A"` → negrito + fundo azul claro (DCE6F1) em toda a linha
- **Excel Tables**: nomeadas `Tab_MM_AAAA` com TableStyleLight9
- **Consolidação**: múltiplos PDFs como abas no mesmo workbook, ordenadas cronologicamente
- **Freeze panes, auto-filtro, bordas, larguras otimizadas**
- **Integração com sign_logic**: converte D/C → +/- antes de gravar valores

Layout de colunas no Excel:
```
A=Código | B=Classificação | C=Descrição | D=Saldo Anterior | E=Natureza SA
F=Débito | G=Crédito | H=Saldo Atual | I=Natureza SAT | J=Tipo (oculta)
```

### 6. `sign_logic.py` — Lógica de Sinais Contábeis (309 linhas)

Detecta e converte D/C para +/- conforme regras contábeis brasileiras.

**Convenção padrão brasileira** (`STANDARD_CONVENTION`):
- Grupo 1 (Ativo): D=+, C=- (depreciação acumulada com C → fica negativa)
- Grupo 2 (Passivo): D=-, C=+
- Grupo 3 (Custos/Despesas): D=-, C=+ (reversão de provisão com C → fica positiva)
- Grupo 4 (Receitas): D=-, C=+ (devoluções com D → ficam negativas)
- Grupos 5-6 (planos de 6 grupos): D=-, C=+

**`detect_sign_mode()`**: Analisa amostra de 50 linhas → detecta se dados têm D/C, +/-, ou nenhum indicador.

**`_verify_convention()`**: Verifica se a distribuição D/C por grupo bate com a convenção padrão (Ativo=maioria D, Passivo/Desp/Rec=maioria C). Aceita exceções normais (depreciação, devoluções).

**`apply_sign_convention()`**: Aplica a conversão D/C → +/- por grupo contábil. Lê natureza da coluna dedicada ou embutida no valor.

**Modos**: `auto` (detecta e aplica), `skip` (mantém original), `ask` (pede input ao usuário).

### 7. `hierarchy.py` — Árvore de Classificação Contábil (114 linhas)

- **`build_hierarchy()`**: Constrói mapeamento pai → filhos diretos a partir da classificação. Só inclui pais marcados como Tipo=A.
- **`get_direct_children()`**: Filho direto = `parent + ".XX"` onde XX é um único segmento (sem mais pontos). Ex: "1.1" é pai de "1.1.01" mas não de "1.1.01.001".
- **`get_account_group()`**: Extrai grupo (1-9) do primeiro segmento da classificação. Suporta formato direto ("1.1") e com zero-fill ("01.1").

### 8. `reference_extractor.py` — Sistema RAG (744 linhas)

Sistema de aprendizado: extrai padrão de XLSX já validado pelo controller e salva em `knowledge/` para uso futuro.

**O que extrai de um XLSX validado**:
1. **Hierarquia completa** de agrupadoras (qual conta soma quais filhos diretos)
2. **Convenção de sinais** por grupo com exemplos concretos (Nat=D→+, Nat=C→-)
3. **Plano de contas** com tipos A/D por classificação
4. **Estrutura de grupos** (total de contas, agrupadoras, detalhe por grupo)
5. **Instruções do controller** (prioridade máxima sobre heurísticas)

**Persistência**: Gera dois arquivos por referência:
- `.txt` — texto formatado para injeção direta no prompt do Gemini
- `.json` — dados estruturados para persistência, debug e listagem

**Carregamento**: `load_reference_for_prompt()` carrega referência específica (por nome) ou a mais recente. Busca por filename stem ou por display_name no JSON.

**Fluxo RAG completo**:
```
XLSX validado → extract_reference_from_xlsx() → ReferenceData
  → save_reference() → knowledge/nome.txt + knowledge/nome.json
  → load_reference_for_prompt() → texto injetado no prompt do Gemini
  → Gemini usa como guia para classificar Tipo, hierarquia e sinais
```

### 9. Frontend — HTML/JS/CSS

**SPA com 4 telas principais**:
1. **Upload**: Drag & drop de PDFs com validação
2. **Lista/Configuração**: Lista de arquivos + slider de workers (1-36) + painel de referências
3. **Progresso**: Barra de progresso com SSE em tempo real + timer decorrido
4. **Resultados**: Preview em tabela + downloads + XLSX Profissional + correção/resubmissão

**Funcionalidades da interface**:
- **Preview Web**: Tabela HTML com agrupadoras em negrito, tabs para múltiplos PDFs, badges coloridos (CSV verde, XLSX azul)
- **Seletor de Modelo**: Toggle entre gemini-2.0-flash, gemini-2.5-flash, gemini-3-flash-preview
- **XLSX Profissional**: Botão para gerar + seletor de sinais (auto-detectar / manter original)
- **Painel de Referências (pré-conversão)**: Selecionar referência existente, criar nova (upload XLSX + nome + instruções), listar/deletar
- **Painel de Referências (pós-conversão)**: Salvar XLSX gerado ou corrigido como referência
- **Chat de Referências**: Conversar com IA (Gemini 2.5 Flash/Pro) para ajustar referências existentes
- **Correção/Resubmissão**: Descrever erro e reenviar ao Gemini para gerar nova versão
- **Downloads**: Individual (CSV/XLSX) ou ZIP com todos os arquivos
- **Dialog de Sinais**: Modal para escolha de convenção quando auto-detect é inconclusivo

### 10. `config.py` — Configurações Centralizadas (`controladoria_core/utils/config.py`)

- **`configure(project_root, env_file, knowledge_dir)`**: Bootstrap obrigatório — seta paths, carrega `.env`, cria diretórios
- `PROJECT_ROOT`, `DATA_DIR`, `INPUT_DIR`, `OUTPUT_DIR`, `KNOWLEDGE_DIR` começam como `None`
- `KNOWLEDGE_DIR` default: `PROJECT_ROOT.parent / "knowledge"` (raiz do monorepo, compartilhado)
- `GEMINI_API_KEY` carregada do `.env` via python-dotenv
- `ProcessingConfig` dataclass: modelo (`gemini-2.0-flash`), temperatura (0.1), max_tokens (200000), timeout (120s)
- **Modelos de conversão** (`MODELOS_DISPONIVEIS`):
  - `gemini-2.0-flash` — in: $0.10/1M, out: $0.40/1M
  - `gemini-2.5-flash` — in: $0.15/1M, out: $3.50/1M
  - `gemini-3-flash-preview` — in: $0.15/1M, out: $0.60/1M
- **Modelos de referência** (`MODELOS_REFERENCIA`):
  - `gemini-2.5-flash` — in: $0.15/1M, out: $3.50/1M
  - `gemini-2.5-pro` — in: $1.25/1M, out: $10.00/1M
- Logger configurado com formato `[timestamp] LEVEL name - message`

### 11. `main.py` — Ponto de Entrada CLI simples (92 linhas)

Script de linha de comando básico (projeto web):
- `python main.py` — processa todos os PDFs em `data/input/`
- `python main.py balancete.pdf` — processa um arquivo específico
- Exibe resumo final com status, tempo e custo por arquivo

### 12. `cli.py` — CLI Rich (`projeto_balancetes_cli/cli.py`)

CLI avançada com interface Rich para terminal:

**Modo direto**: `python cli.py balancete.pdf --model gemini-2.5-flash --xlsx --workers 4`
- argparse com flags: `--model`, `--xlsx`, `--workers`, `--sign-mode`, `--reference`, `--output-dir`, `--detail-level`
- Processa, mostra Rich progress, exibe resultados, sai

**Modo interativo**: `python cli.py` (sem args)
- Menu Rich com 6 opções: Processar PDFs, Gerar XLSX Prof., Selecionar modelo, Gerenciar referências, Listar input, Sair
- Prompts interativos para workers, referência, sinais
- Preview em tabela Rich (agrupadoras em bold azul)

**Componentes Rich**: Panel, Table, Progress (SpinnerColumn + BarColumn + TimeElapsedColumn), Prompt, Confirm, IntPrompt

### 13. `test_xlsx_builder.py` — Testes (358 linhas)

9 testes dos cenários reais de sinais contábeis:
1. Convenção padrão (STANDARD_CONVENTION)
2. Depreciação no Ativo (C → negativo)
3. Passivo (C → positivo, D → negativo)
4. Despesas (D → negativo, C → positivo) e Receitas (D → negativo, C → positivo)
5. `detect_periodo()` — parsing de período do nome do arquivo
6. Build XLSX completo com sinais aplicados e verificação das células
7. Agrupadora com soma divergente (mantém valor original do PDF)
8. Filtro somente agrupadoras (detail_level="agrupadoras")
9. Filtro personalizado — colapsar grupo específico

## Detalhes Técnicos Importantes

- **Deduplicação 3 níveis**: exact row match → Código+Classificação match → intra-batch continuation dedup
- **Anti-truncation**: Detecta MAX_TOKENS finish_reason e pede continuações (até 3)
- **Retry exponencial**: 2s, 4s, 8s, 16s, 32s para erros 429
- **Stagger delay**: 2s entre workers para evitar burst de API
- **Contagem local**: Regex substitui chamadas caras de pré-contagem via Gemini
- **OCR fallback**: get_text() → Tesseract → text_fallback (3 níveis)
- **Tolerância agrupadoras**: 1% na soma numérica, mínimo 2 filhos, 2+ de 4 colunas devem bater
- **Validação de fórmulas SUM**: só coloca fórmula se |SUM(filhos)| ≈ |valor original|, senão mantém valor do PDF
- **RAG com instruções**: controller humano pode ensinar a IA com feedback de prioridade máxima
- **Resubmissão com correção**: reenvia PDF com prompt de correção, gerando versões v2, v3, etc.
- **Chat de referências**: conversa com Gemini 2.5 para refinar padrões contábeis
- **Job system in-memory**: dict[str, Job] com FileInfo, JobProgress, preview_data

## Como Rodar

```bash
cd "C:\Users\gabri\Dev\Controladoria_Plus"
.venv\Scripts\activate

# Instalar pacote core (uma vez)
pip install -e .

# Projeto Web
cd projeto_balancetes
pip install -r requirements.txt
python app.py              # Abrir http://localhost:8000

# Projeto CLI
cd projeto_balancetes_cli
python cli.py              # Modo interativo
python cli.py *.pdf        # Modo direto

# Testes
cd projeto_balancetes
python test_xlsx_builder.py
```

## Próximos Passos

Este projeto está **pronto e funcionando** com duas interfaces (web + CLI). O próximo projeto da pipeline será o **Classificador/Consolidador** — para classificar e consolidar os balancetes gerados por este conversor em uma mesma planilha ou banco de dados, alimentando o projeto final de Dashboard.
