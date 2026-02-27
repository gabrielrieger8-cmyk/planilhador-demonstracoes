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
- Testar processamento completo com Gemini 2.5 Flash em todas as etapas
- Testar processamento com Haiku 4.5 na formatacao
- Considerar adicionar mais modelos (Gemini 2.5 Pro, etc.)
