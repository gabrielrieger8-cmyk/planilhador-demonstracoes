# CLAUDE.md - Planilhador de Demonstrações

## Estilo de trabalho HIGH IMPORTANCE!!
- Durante planejamento e discussão, pode fazer perguntas e alinhar a abordagem.
- Na hora de executar (rodar código, editar arquivos, usar ferramentas), faça direto sem pedir permissão.
- Se algo falhar, corrija e siga em frente.

## O que é o projeto

Planilhador de Demonstrações converte PDFs de demonstrações financeiras (balancetes, DRE, balanço patrimonial) em planilhas Excel profissionais.

**Pipeline**: PDF → Classificação → Extração → Formatação → Validação → Excel multi-aba + CSV

**Modelos configuráveis por etapa** (default: Gemini 2.5 Flash para tudo). Opções: Gemini 2.0 Flash, Gemini 2.5 Flash, Haiku 4.5. O usuário escolhe via UI antes de processar.

## Estrutura do projeto

```
app/
  main.py              # FastAPI app, mount static, startup
  config.py            # Anthropic + Gemini pricing, DB URL
  jobs.py              # Job/FileInfo/JobProgress dataclasses
  models/              # SQLAlchemy (database.py, documento.py, conta_contabil.py)
  routes/              # upload.py, progress.py (SSE), results.py
  services/            # pipeline.py, gemini_client.py, anthropic_client.py, classifier.py, validator.py, exporter.py
  prompts/             # Prompts .txt para cada modelo/etapa
  utils/               # pdf_utils.py
static/                # Frontend SPA (index.html, app.js, style.css)
tests/                 # test_validator.py, test_exporter.py
run.py                 # Entry point (uvicorn, porta 8000)
requirements.txt       # Dependências
```

## Comandos úteis

- `python run.py` — inicia o servidor na porta 8000
- `python -m pytest tests/ -v` — roda os testes (25 testes)
- `pip install -r requirements.txt` — instala dependências

## Session Log

Ao final de cada sessão, salve um resumo do que foi feito no arquivo `SESSION_LOG.md` na raiz do projeto. O log deve conter:

- Data da sessão
- Resumo das alterações realizadas
- Arquivos criados ou modificados
- Decisões técnicas tomadas
- Pendências ou próximos passos
