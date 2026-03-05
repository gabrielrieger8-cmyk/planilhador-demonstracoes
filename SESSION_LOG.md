# SESSION LOG — Planilhador de Demonstracoes

---

## Sessao 1 — 2026-02-27

### Objetivo
Tornar os modelos de IA configuraveis por etapa do pipeline, com selecao via UI.

### O que foi feito

**1. Modelos configuraveis por etapa (classificacao, extracao, formatacao)**
- Cada etapa do pipeline agora aceita um modelo escolhido pelo usuario
- Default de todas as etapas: Gemini 2.5 Flash (antes: 2.0 Flash para classificacao, Sonnet para formatacao)
- Sonnet 4.5 removido, substituido por Haiku 4.5 como opcao Anthropic

**2. Formatacao via Gemini (novo)**
- Criadas `formatar_demonstracao_gemini()` e `refinar_balancete_gemini()` em gemini_client.py
- Pipeline roteia automaticamente: prefixo "gemini-" → Gemini, prefixo "claude-" → Anthropic
- Mesmos prompts usados para ambos os providers

**3. Endpoint GET /models**
- Retorna modelos disponiveis e defaults para cada etapa
- Usado pelo frontend para popular os selects

**4. Frontend com selecao de modelos**
- 3 selects (Classificacao, Extracao, Formatacao) na secao de arquivos
- Populados via GET /models ao carregar a pagina
- Modelos selecionados enviados como JSON body no POST /process/{job_id}

### Arquivos modificados
- `app/config.py` — Haiku 4.5 substitui Sonnet, defaults todos Gemini 2.5 Flash, ALL_MODELS
- `app/jobs.py` — campo `models` no dataclass Job
- `app/services/gemini_client.py` — param `model` em todas as funcoes + funcoes de formatacao Gemini
- `app/services/anthropic_client.py` — param `model` em formatar_demonstracao e refinar_balancete
- `app/services/classifier.py` — param `model` propagado
- `app/services/pipeline.py` — le job.models, roteia formatacao por provider
- `app/routes/progress.py` — ProcessRequest com campos de modelo, validacao
- `app/main.py` — endpoint GET /models
- `static/index.html` — secao de selecao de modelos
- `static/app.js` — loadModels(), envio de modelos no processamento
- `static/style.css` — estilos da secao de modelos
- `CLAUDE.md` — pipeline atualizado

### Decisoes tecnicas
- Roteamento por prefixo do model ID ("gemini-" vs "claude-") em vez de flag separada
- Formatacao via Gemini usa mesmos prompts do Anthropic (system prompt como texto no contents)
- ProcessRequest com Pydantic para validacao do body JSON
- Validacao de modelo contra ALL_MODELS antes de iniciar processamento
- Verificacao de ANTHROPIC_API_KEY somente quando modelo Anthropic selecionado

### Pendencias / Proximos Passos
- ~~Testar processamento completo com Gemini 2.5 Flash em todas as etapas~~ (feito sessao 2)
- ~~Testar processamento com Haiku 4.5 na formatacao~~ (feito sessao 2)
- Considerar adicionar mais modelos (Gemini 2.5 Pro, etc.)

---

## Sessao 2 — 2026-02-27 (continuacao)

### Objetivo
Correcao de bugs + suporte Anthropic completo + estimativa de custo.

### O que foi feito

**1. Fix: loop de truncamento na formatacao Gemini**
- `refinar_balancete_gemini()` ficava preso em loop infinito ao formatar balancetes grandes
- Causa: cada continuacao reenviava o texto acumulado inteiro, gerando contextos crescentes
- Solucao: enviar apenas ultimas 20 linhas como contexto e limitar a 2 continuacoes
- Criada `_gemini_format_with_continuation()` como helper reutilizavel

**2. Suporte Anthropic em TODAS as etapas do pipeline**
- Haiku inicialmente dava erro 404 quando usado em classificacao/extracao (roteava para Gemini API)
- Implementadas funcoes completas no anthropic_client.py:
  - `classificar_documento_anthropic()` — envia PDF como documento base64
  - `extrair_balancete_anthropic()` — extracao pagina-por-pagina via Claude
  - `extrair_demonstracao_anthropic()` — extracao DRE/BP via Claude
  - `_extract_page_range_bytes()` — helper para extrair paginas especificas
- classifier.py atualizado para rotear por prefixo do modelo
- pipeline.py atualizado para rotear extracao por prefixo do modelo

**3. Estimativa de custo (orcado vs realizado)**
- Backend: funcao `estimar_custo()` em config.py com tokens empiricos por pagina
- Backend: endpoint `POST /estimate` em main.py
- Frontend: barra verde com custo estimado aparece apos upload, recalcula ao mudar modelo
- Frontend: resultados mostram "Orcado" e "Realizado" lado a lado apos processamento
- Tokens por pagina: classificacao (1500 in, 50 out fixo), extracao (1500 in, 3000 out), formatacao (4000 in, 4000 out)

### Arquivos modificados
- `app/config.py` — `TOKENS_PER_PAGE`, `estimar_custo()`
- `app/main.py` — `POST /estimate`, import `estimar_custo`
- `app/services/gemini_client.py` — `_gemini_format_with_continuation()`, fix truncamento
- `app/services/anthropic_client.py` — classificacao, extracao balancete e demonstracao via Anthropic
- `app/services/classifier.py` — roteamento Gemini/Anthropic
- `app/services/pipeline.py` — roteamento completo por modelo em extracao
- `static/index.html` — div `#cost-estimate`
- `static/app.js` — `updateEstimate()`, listeners de modelo, orcado vs realizado nos resultados
- `static/style.css` — estilos `.cost-estimate`

### Decisoes tecnicas
- Estimativa usa tokens empiricos por pagina (nao conta tokens reais antes de processar)
- Continuacao de formatacao Gemini limitada a ultimas 20 linhas + max 2 continuacoes
- Anthropic recebe PDF como base64 document (nao imagem), mesma abordagem da classificacao
- Extracao Anthropic e pagina-por-pagina para balancetes, bloco unico para DRE/BP

### Commits
- `8eb1574` — fix: corrige loop de truncamento na formatacao Gemini
- `1366f78` — fix: restringe Haiku apenas a etapa de formatacao (revertido depois)
- `79c840f` — feat: suporte a modelos Anthropic em todas as etapas do pipeline
- `3ba08f2` — feat: estimativa de custo antes do processamento (orcado vs realizado)

### Pendencias / Proximos passos
- Calibrar tokens empiricos com dados reais de uso
- Considerar adicionar mais modelos (Gemini 2.5 Pro, etc.)

---

## Sessao 3 — 2026-03-02

### Objetivo
Teste end-to-end com 9 balancetes reais, correcao de bugs encontrados, processamento paralelo e consolidacao multi-periodo.

### O que foi feito

**1. Fix: coluna Classificacao ausente no Excel de balancetes**
- formatter.py extraia a classificacao corretamente, mas exporter.py nao incluia na saida
- Adicionada "Classificacao" como segunda coluna em BALANCETE_COLUMNS
- Atualizados todos os indices dependentes (colunas numericas, alinhamento, formulas SUM, letras de coluna)
- CSV tambem atualizado para incluir classificacao

**2. Processamento paralelo com ThreadPoolExecutor**
- Pipeline reescrito: de sequencial para paralelo com ate 10 workers simultaneos
- Fila gerenciada manualmente no Job (queue + queue_lock + active_count)
- threading.Event para sinalizar conclusao de todos os arquivos
- Tempo de 9 PDFs (66 paginas) caiu de ~23min para ~4min

**3. Waitlist visual com reordenacao e cancelamento**
- Backend: campos queue/queue_lock/active_count/file_results no Job
- Backend: endpoints POST /queue/reorder e POST /queue/cancel
- Backend: queue_position no payload SSE para cada arquivo
- Frontend: arquivos agrupados por status (processando, na fila, concluidos, erros, cancelados)
- Frontend: botoes seta cima/baixo para reordenar + botao X para cancelar
- CSS: estilos para grupos, badges de posicao, status cancelado

**4. Fix: erro de parse JSON na classificacao paralela**
- Gemini API retornava JSON envolto em blocos ```json quando multiplas requests simultaneas
- Corrigido adicionando response_mime_type="application/json" na chamada de classificacao
- Parametro propagado na funcao _call_gemini

**5. Excel consolidado multi-periodo**
- Ao processar multiplos PDFs, gera "Consolidado.xlsx" com todos os periodos como abas
- Funcao _consolidate_excel() roda apos todos os arquivos completarem
- Resultados armazenados em job.file_results para consolidacao

**6. Fix: corrupcao de Excel por nomes de aba duplicados**
- Nomes como "EMPRESA LTDA - Balancete - 01/2025" truncados a 31 chars ficavam identicos
- Criada _short_tab_name() que usa apenas tipo + periodo (sem empresa)
- Criada _unique_tab_name() que garante unicidade com sufixo numerico

### Arquivos modificados
- `app/jobs.py` — campos queue, queue_lock, active_count, file_results; status "cancelled"
- `app/services/pipeline.py` — reescrita completa: fila gerenciada, paralelo, _consolidate_excel
- `app/services/exporter.py` — coluna Classificacao, _short_tab_name, _unique_tab_name, formulas SUM atualizadas
- `app/services/formatter.py` — deteccao de coluna classificacao em DRE e Balanco
- `app/services/gemini_client.py` — response_mime_type em _call_gemini e classificacao
- `app/routes/progress.py` — endpoints reorder/cancel, queue_position no SSE, ReorderRequest
- `static/app.js` — grupos visuais, controles de fila, PARALLEL_WORKERS, estimativa atualizada
- `static/style.css` — estilos para fila, grupos, cancelado, botoes de acao
- `tests/test_formatter.py` — novo arquivo com testes do formatter

### Decisoes tecnicas
- Fila gerenciada manualmente (em vez de submeter tudo ao ThreadPoolExecutor) para permitir reordenacao e cancelamento em tempo real
- response_mime_type="application/json" forca Gemini a retornar JSON puro sem markdown
- Nomes de aba curtos (tipo + periodo) para multi-tab, nomes longos (com empresa) para single-tab
- threading.Event em vez de polling para aguardar conclusao de todos os workers

### Commits
- `e7a5f4f` — feat: processamento paralelo, waitlist com controle de fila, coluna Classificacao e Excel consolidado

### Pendencias / Proximos passos
- Testar waitlist com >10 arquivos para verificar reordenacao e cancelamento
- Calibrar tokens empiricos com dados reais de uso
- Considerar adicionar mais modelos (Gemini 2.5 Pro, etc.)

---

## Sessao 4 — 2026-03-02 (continuacao)

### Objetivo
Corrigir processamento de demonstracoes comparativas (multi-periodo). O PDF da TONIOLO, BUSNELLO com Balanco e DRE comparativos (Dez/24 e Dez/25) saiu todo errado: datas nao reconhecidas, Passivo/PL errados, DRE vazia.

### Diagnostico
- **Balanco**: validacao falhou com `Ativo (563M) != Passivo+PL (674M)` — valores misturados entre colunas Dez/24 e Dez/25
- **DRE**: CSV com apenas 1 linha — parser nao conseguiu interpretar tabela de 4 colunas
- **Classificador**: retornou `periodo=31/12/2025` — ignorou periodo comparativo Dez/24
- **Causa raiz**: prompt de extracao pedia "EXATAMENTE 3 colunas" mas tambem "inclua multiplos periodos", e o formatter so lia `row[2]` como valor

### O que foi feito

**1. Fix: prompt de extracao (system_demonstracao_gemini.txt)**
- Removida contradicao "EXATAMENTE 3 colunas" vs "inclua multiplos periodos"
- Instrucoes claras: 1 periodo → `Classificacao | Descricao | Valor`; comparativo → `Classificacao | Descricao | Dez/2024 | Dez/2025`
- Exemplos explicitos para cada cenario

**2. Classificador com consciencia de comparativos (system_classifier.txt)**
- Novo campo `comparativo: true/false` no JSON de cada demonstracao
- Campo `periodo` agora aceita multiplos periodos: "31/12/2024 e 31/12/2025"
- Nota sobre demonstracoes comparativas brasileiras

**3. Formatter multi-periodo (formatter.py) — mudanca principal**
- Nova funcao `_detect_value_columns()`: detecta automaticamente quantas colunas de valor a tabela tem, extrai nomes dos periodos dos headers, filtra colunas nao-numericas (ex: AV%)
- Nova funcao `_analyze_header()`: analise compartilhada de header (start, has_classif)
- Refatoracao: logica core extraida para `_formatar_dre_internal()` e `_formatar_balanco_internal()` com parametro `val_col_idx`
- Novas funcoes publicas `formatar_dre_multi()` e `formatar_balanco_multi()` que retornam `list[dict]` (1 por periodo)
- Funcoes originais `formatar_dre()` e `formatar_balanco()` inalteradas (backward compatible)

**4. Pipeline multi-periodo (pipeline.py)**
- Usa `formatar_dre_multi` e `formatar_balanco_multi` em vez das funcoes originais
- Loop de validacao por periodo (cada periodo validado independentemente)
- Fix CSV naming: quando ha duplicata de tipo, adiciona periodo ao nome do arquivo

**5. Testes (test_formatter.py)**
- 21 novos testes: DRE multi-periodo, Balanco multi-periodo, edge cases
- Edge cases: 3 periodos, headers de secao sem valor, coluna AV% ignorada, texto vazio
- Total: 53 testes passando (28 formatter + 13 exporter + 12 validator)

### Arquivos modificados
- `app/prompts/system_demonstracao_gemini.txt` — instrucoes claras para multi-coluna
- `app/prompts/system_classifier.txt` — campo comparativo, periodos multiplos
- `app/services/formatter.py` — _detect_value_columns, _analyze_header, funcoes _internal e _multi
- `app/services/pipeline.py` — imports _multi, loop validacao por periodo, fix CSV naming
- `tests/test_formatter.py` — 21 novos testes multi-periodo

### Decisoes tecnicas
- Abordagem "split at formatter level": o Gemini retorna tabela multi-coluna, e o formatter Python detecta e separa cada periodo automaticamente
- Funcoes _multi retornam sempre list[dict] (1 elemento para single-period) — pipeline trata uniformemente
- Deteccao de colunas de valor valida que >=50% das linhas tem conteudo numerico (evita falso positivo com colunas de texto)
- Funcoes originais formatar_dre/formatar_balanco mantidas intactas para nao quebrar outros callers

### Pendencias / Proximos passos
- Reprocessar PDF da TONIOLO para validar fix end-to-end
- Testar com outros PDFs comparativos (3+ periodos)
- Considerar tratar sinal de "Prejuizos Acumulados" no Balanco (abs() pode ser incorreto)

---

## Sessao 5 — 2026-03-02 (continuacao)

### Objetivo
Fix: linhas de header repetidas em balancetes (quebra de pagina no PDF).

### O que foi feito

**1. Fix: headers repetidos em balancetes**
- Na extracao pagina-por-pagina, o Gemini repete o header (Codigo, Classificacao, Descricao...) no inicio de cada pagina
- Adicionada deteccao de linhas de header no loop principal de `formatar_balancete()`
- Set `_HEADER_KW` com keywords de header (CODIGO, CLASSIFICACAO, DESCRICAO, SALDO, DEBITO, CREDITO, etc.)
- Logica: se a linha contem keywords de header E as primeiras 2 colunas nao comecam com digito → pula a linha
- Isso preserva contas reais que contenham palavras como "SALDO" na descricao

**2. Testes**
- 3 novos testes em `TestBalanceteRepeatedHeaders`: header nao aparece nas contas, contagem correta, valores corretos
- Total: 56 testes passando (31 formatter + 13 exporter + 12 validator)

### Arquivos modificados
- `app/services/formatter.py` — `_HEADER_KW` set + logica de skip no loop de `formatar_balancete()`
- `tests/test_formatter.py` — import `formatar_balancete`, fixture `BALANCETE_WITH_REPEATED_HEADERS`, classe `TestBalanceteRepeatedHeaders`

### Decisoes tecnicas
- Deteccao por keywords em vez de comparacao exata (cobre variacoes de acentuacao e maiusculas/minusculas)
- Condicao adicional "primeiras 2 colunas nao comecam com digito" evita falso positivo com contas que contenham palavras do header

### Pendencias / Proximos passos
- Reiniciar servico `balancetes.service` (requer sudo)
- Reprocessar PDF da TONIOLO para validar fixes end-to-end
- Testar com outros PDFs comparativos

---

## Sessao 6 — 2026-03-02

### Objetivo
Corrigir formato de saida de DRE e Balanco comparativos para reproduzir o layout do exemplo (TONIOLO ULTIMATE.xlsx). CSV gerado somente on-demand.

### Diagnostico
Comparando o exemplo `Exemplos/TONIOLO ULTIMATE.xlsx` com o output do sistema, foram identificados 5 problemas:
1. Multi-periodo em abas separadas (deveria ser lado a lado em 1 aba)
2. Coluna VARIACAO e AV auto-geradas desnecessariamente
3. `abs(valor)` no Balanco removia negativos (ex: Prejuizos Acumulados)
4. Filtro `_NON_PERIOD_KEYWORDS` nao cobria "AV (2024)", "AV (2025)", "VARIACAO"
5. Validacao do Balanco falhava: PASSIVO total do PDF ja incluia PL → dupla contagem

### O que foi feito

**1. Formato comparativo lado a lado (exporter.py)**
- Nova funcao `_write_dre_comparativo()`: escreve DRE com colunas `Descricao | Periodo1 | Periodo2 | ...`
- Nova funcao `_write_balanco_comparativo()`: escreve Balanco com ATIVO + PASSIVO + PL em 1 aba, periodos lado a lado
- `export_excel_multi()` refatorado: agrupa resultados por tipo, DRE/Balanco multi-periodo usam funcoes comparativas

**2. Valores negativos preservados (formatter.py)**
- Removido `abs(valor)` em `_formatar_balanco_internal()` — valores como Prejuizos Acumulados mantem sinal negativo

**3. Filtro AV/VARIACAO corrigido (formatter.py)**
- Adicionados keywords: "AV(", "AV (", "A.V.", "VARIACAO", "VARIAÇÃO", "VAR."
- Adicionada regex `_AV_ONLY_RE` para filtrar colunas cujo nome comeca com "AV" (ex: "AV (2024)")

**4. Validacao Balanco corrigida (formatter.py)**
- `_fill_missing_totals()` agora SEMPRE recalcula total de ativo/passivo a partir das sub-secoes (circulante + nao_circulante)
- Evita dupla contagem quando o PDF mostra PASSIVO total = Passivo + PL

**5. CSV on-demand (pipeline.py + results.py + frontend)**
- Pipeline nao gera mais CSVs automaticamente — apenas Excel
- Novo endpoint `POST /generate-csv/{job_id}` gera CSVs a partir dos dados ja processados (job.file_results)
- Frontend: botao "Gerar CSV" aparece nos resultados, gera CSVs e atualiza lista de arquivos

**6. Testes (test_exporter.py)**
- 7 novos testes em `TestComparativoExporter`: DRE/Balanco comparativo 1 aba, valores lado a lado, negativos preservados, mix tipos
- Total: 63 testes passando (31 formatter + 20 exporter + 12 validator)

### Arquivos modificados
- `app/services/formatter.py` — abs() removido, _NON_PERIOD_KEYWORDS ampliado, _AV_ONLY_RE, _fill_missing_totals recalcula sempre
- `app/services/exporter.py` — _write_dre_comparativo, _write_balanco_comparativo, export_excel_multi refatorado
- `app/services/pipeline.py` — removida geracao automatica de CSV
- `app/routes/results.py` — novo endpoint POST /generate-csv/{job_id}
- `static/index.html` — botao "Gerar CSV"
- `static/app.js` — generateCSV(), logica de visibilidade do botao CSV
- `tests/test_exporter.py` — 7 novos testes comparativos

### Decisoes tecnicas
- Periodos lado a lado no Excel (nao em abas separadas) — reproduz formato do exemplo
- AV e VARIACAO filtradas como nao-periodos no formatter (se presentes no PDF, sao ignoradas)
- CSV gerado on-demand para output mais limpo — endpoint reutiliza dados ja processados em job.file_results
- Total de ativo/passivo sempre recalculado das sub-secoes para evitar inconsistencia com PDFs que incluem PL no total de PASSIVO
