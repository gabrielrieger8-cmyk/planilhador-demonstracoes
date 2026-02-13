# Resumo Completo — Projeto Controladoria Plus (Conversor de Balancetes)

## Objetivo

**Controladoria Plus** é um conversor de PDFs de balancetes contábeis brasileiros para CSV/XLSX, com interface web. É o **primeiro projeto** de uma pipeline de 3:

1. **Conversor** (ESTE PROJETO — pronto) → Extrai dados de PDFs de balancetes via IA
2. **Classificador/Consolidador** (PRÓXIMO) → Classifica e consolida balancetes em uma mesma planilha ou banco de dados
3. **Dashboard** → Analisa demonstrações e cria visualizações

## Arquitetura

- **Backend**: FastAPI (`app.py`) com SSE para progresso em tempo real
- **IA**: Google Gemini API (`google-genai`) para extração nativa PDF→Markdown
- **PDF**: PyMuPDF (fitz) para manipulação, extração de texto e OCR fallback (Tesseract)
- **Excel**: openpyxl para geração de .xlsx formatado
- **Frontend**: HTML/CSS/JS vanilla (SPA)

## Estrutura do Projeto

```
C:\Controladoria_Plus\
├── .venv\                          # Virtual environment Python
└── projeto_balancetes\
    ├── .env                        # GEMINI_API_KEY
    ├── .gitignore
    ├── app.py                      # FastAPI backend (516 linhas)
    ├── requirements.txt            # docling, google-genai, pymupdf, python-dotenv, pytest, openpyxl
    ├── data/
    │   ├── input/                  # PDFs enviados pelo usuário
    │   └── output/                 # CSVs e XLSXs gerados
    ├── src/
    │   ├── agents/
    │   │   └── gemini_agent.py     # Agente Gemini principal (987 linhas)
    │   ├── parsers/
    │   │   └── csv_parser.py       # Parser e pós-processamento (1217 linhas)
    │   ├── orchestrator.py         # Orquestrador (227 linhas)
    │   └── utils/
    │       └── config.py           # Configurações centralizadas (109 linhas)
    └── static/
        ├── index.html              # Interface HTML (96 linhas)
        ├── app.js                  # JavaScript frontend (589 linhas)
        └── style.css               # Estilos CSS (700+ linhas)
```

## Repositório Git

- **GitHub**: `https://github.com/gabrielrieger8-cmyk/Controladoria-Plus.git`
- **Branch**: `master` (única branch, limpa)
- **Último commit**: `dece286` — "Evolucao completa: OCR guide, per-page API, agrupadora detection, preview web + xlsx export"

## Componentes Principais

### 1. `gemini_agent.py` — Agente de Extração (987 linhas)

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

**Sistema OCR Guide**: Extrai texto de cada página via `get_text()` (ou Tesseract OCR como fallback), injeta no prompt do Gemini como referência para evitar omissões de contas.

**Contagem local de contas**: Regex-based (Pattern 1: "CODIGO CLASSIFICACAO", Pattern 2: código numérico standalone). Substitui chamadas caras de pré-contagem via Gemini.

**Prompt principal** (`FINANCIAL_PROMPT`): Instrui o Gemini a extrair tabela Markdown com 8 colunas, identificar agrupadoras (Tipo=A), e nunca omitir contas.

**Modelos suportados**: `gemini-2.0-flash` e `gemini-3-flash-preview`, selecionáveis em runtime.

### 2. `csv_parser.py` — Parser e Pós-Processamento (1217 linhas)

Toda a transformação de dados acontece aqui.

**Pipeline de pós-processamento** (ordem):
1. `extract_markdown_tables()` → Parseia tabelas Markdown
2. `_unify_and_deduplicate()` → Merge de todas as tabelas, remove duplicatas exatas e por Código+Classificação
3. `_postprocess_agrupadoras()` → Detecção de agrupadoras em 2 camadas:
   - **Camada 1 (Hierarquia)**: Matching de prefixo de classificação (ex: "3.2" é pai de "3.2.1")
   - **Camada 2 (Soma numérica)**: Verifica se SA, Deb, Cred, SAT da linha ≈ soma das linhas filhas consecutivas (tolerância 1%, mínimo 2 filhos, 2+ de 4 colunas devem bater)
4. `_fix_tipo_in_numeric_columns()` → Corrige A/D encontrados em colunas numéricas
5. `_fix_dc_in_numeric_columns()` → Remove sufixo D/C de colunas Débito/Crédito
6. `_split_natureza_columns()` → Separa "47.649.092,98D" em valor + "D" em colunas separadas

**Layout de colunas**:
- 8 colunas base: Código, Classificação, Descrição, Tipo, Saldo Anterior, Débito, Crédito, Saldo Atual
- 10 colunas após split natureza: adiciona Natureza SA, Natureza SAT

**`save_as_csv()`**: Gera CSV com delimitador `;` e encoding `utf-8-sig`

**`save_as_xlsx()`**: Gera Excel formatado com:
- Header: negrito, fundo azul (#2F5496), texto branco
- Agrupadoras (Tipo=A): negrito + fundo cinza (#E8E8E8)
- Colunas numéricas alinhadas à direita
- Bordas finas, freeze panes, auto-filtro
- Larguras de coluna otimizadas

**Valores**: Formato brasileiro (ponto=milhar, vírgula=decimal), sufixos D/C para natureza.

### 3. `orchestrator.py` — Orquestrador (227 linhas)

Orquestrador simplificado (apenas Gemini, sem Docling).

- `Orchestrator.process()`: Valida PDF → envia para Gemini → exporta CSV+XLSX → retorna `ProcessingResult` com `preview_rows` nos detalhes
- `_export()`: Retorna `tuple[list[Path], list[list[str]]]` — gera CSV, depois XLSX com as mesmas `unified_rows`, passa `unified_rows` de volta para preview
- Também salva `{filename}_raw.txt` com output bruto do Gemini para debug

### 4. `app.py` — Backend FastAPI (516 linhas)

**Endpoints**:
- `POST /upload` — Recebe PDFs, cria job
- `POST /convert/{job_id}` — Inicia conversão em background com ThreadPoolExecutor
- `GET /progress/{job_id}` — SSE stream com progresso real-time
- `GET /results/{job_id}` — Lista de arquivos (csv/xlsx), custos, tempos, e `preview_data`
- `GET /download/{job_id}/{filename}` — Download individual (media type dinâmico)
- `GET /download-all/{job_id}` — ZIP com todos os CSV e XLSX
- `GET /models` / `POST /set-model` — Toggle de modelo
- `DELETE /job/{job_id}/{filename}` — Remove PDF antes da conversão

**`Job` dataclass**: Inclui `preview_data: dict[str, list[list[str]]]` para preview rows por PDF.

**Processamento paralelo**: `ThreadPoolExecutor` com workers configuráveis (1-36), stagger delay de 2s entre workers para evitar burst de API.

### 5. Frontend — HTML/JS/CSS

**Fluxo da interface**: Upload (drag & drop) → Lista de Arquivos (com slider de workers) → Progresso (SSE em tempo real) → Resultados (preview + downloads)

**Preview Web**: Tabela HTML renderizada com agrupadoras em negrito, tabs para múltiplos PDFs, badges coloridos (CSV verde, XLSX azul).

**`renderPreview(previewData)`**: Cria tabs se múltiplos arquivos, chama `renderTable()`.

**`renderTable(rows, container, rowCountEl)`**: Monta tabela HTML, detecta coluna Tipo, aplica classe `.agrupadora` em linhas com Tipo=A, zebra striping.

### 6. `config.py` — Configurações (109 linhas)

- `GEMINI_API_KEY` do `.env`
- `ProcessingConfig` dataclass: modelo, temperatura (0.1), max_tokens (200000), timeout (120s)
- `MODELOS_DISPONIVEIS`: pricing para gemini-2.0-flash (in: $0.10/1M, out: $0.40/1M) e gemini-3-flash-preview (in: $0.15/1M, out: $0.60/1M)
- Diretórios: `PROJECT_ROOT / "data" / "input"` e `"output"`

## Fluxo de Dados Completo

```
PDF upload → app.py /upload → Job criado
  → /convert → ThreadPoolExecutor
    → orchestrator.process()
      → gemini_agent.process() [1 página por vez com OCR guide]
        → Gemini API retorna Markdown
      → csv_parser.save_as_csv() [pipeline de pós-processamento]
        → unified_rows gerados
        → csv_parser.save_as_xlsx(unified_rows) → .xlsx formatado
      → ProcessingResult.details["preview_rows"] = unified_rows
    → app.py Job.preview_data[nome] = preview_rows
  → SSE /progress → frontend atualiza em tempo real
  → /results → { files: [...], preview_data: {...} }
    → frontend renderPreview() → tabela HTML na tela
    → downloads .csv / .xlsx / ZIP disponíveis
```

## Como Rodar

```bash
cd C:\Controladoria_Plus
.venv\Scripts\activate
cd projeto_balancetes
pip install -r requirements.txt
# Criar .env com GEMINI_API_KEY=sua_chave
python app.py
# Abrir http://localhost:8000
```

## Detalhes Técnicos Importantes

- **Deduplicação 3 níveis**: exact row match → Código+Classificação match → intra-batch continuation dedup
- **Anti-truncation**: Detecta MAX_TOKENS finish_reason e pede continuações (até 3)
- **Retry exponencial**: 2s, 4s, 8s, 16s, 32s para erros 429
- **Stagger delay**: 2s entre workers para evitar burst de API
- **Contagem local**: Regex substitui chamadas caras de pré-contagem via Gemini
- **OCR fallback**: get_text() → Tesseract → text_fallback (3 níveis)
- **Tolerância agrupadoras**: 1% na soma numérica, mínimo 2 filhos, 2+ de 4 colunas devem bater

## Próximos Passos

Este projeto está **pronto e funcionando**. O próximo projeto da pipeline será o **Classificador/Consolidador** — para classificar e consolidar os balancetes gerados por este conversor em uma mesma planilha ou banco de dados, alimentando o projeto final de Dashboard.
