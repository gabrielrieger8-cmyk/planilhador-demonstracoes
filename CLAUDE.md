# CLAUDE.md - Instruções para o Claude Code

## Estilo de trabalho HIGH IMPORTANCE!!
- Durante planejamento e discussão, pode fazer perguntas e alinhar a abordagem.
- Na hora de executar (rodar código, editar arquivos, usar ferramentas), faça direto sem pedir permissão.
- Se algo falhar, corrija e siga em frente.

## Início de sessão

Ao iniciar uma sessão com contexto zerado, leia estes arquivos antes de qualquer tarefa:

1. `projeto_balancetes/SESSION_LOG.md` — histórico das sessões anteriores (o que foi feito, decisões, pendências)
2. `projeto_balancetes/RESUMO_PROJETO.md` — arquitetura, stack e estrutura do projeto

Isso evita retrabalho e garante continuidade entre sessões.

## Estrutura do monorepo

- `controladoria_core/` — pacote Python compartilhado (instalado com `pip install -e .`)
- `projeto_balancetes/` — projeto web (FastAPI + frontend HTML/JS/CSS)
- `projeto_balancetes_cli/` — projeto CLI (Rich — terminal com cores)
- `knowledge/` — referências RAG compartilhadas entre projetos
- Cada projeto chama `configure(project_root=...)` antes de usar o core

## Session Log

Ao final de cada sessão, salve um resumo do que foi feito no arquivo `SESSION_LOG.md` na raiz do projeto. O log deve conter:

- Data da sessão
- Resumo das alterações realizadas
- Arquivos criados ou modificados
- Decisões técnicas tomadas
- Pendências ou próximos passos
