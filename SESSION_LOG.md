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
