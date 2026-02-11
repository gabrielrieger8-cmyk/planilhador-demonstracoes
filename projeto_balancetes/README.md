# Processador Inteligente de PDFs Financeiros

Sistema de processamento de PDFs financeiros (balancetes, DREs, balanços patrimoniais) com orquestração inteligente de agentes.

## Arquitetura

```
PDF → Analisador → Classificador → ┬─ Docling (texto)  ─┬→ Exportador → MD/CSV/JSON
                                    ├─ Gemini  (visual) ─┤
                                    └─ Híbrido (ambos)  ─┘
```

**Fluxo de decisão:**

1. **PyMuPDF** analisa a estrutura do PDF (texto, imagens, tabelas, desenhos)
2. **Classificador** calcula scores de texto vs. visual e decide a rota
3. **Agente Docling** — processamento local, sem custo, ideal para texto corrido
4. **Agente Gemini Flash** — API visual, ideal para tabelas complexas e scans
5. **Modo Híbrido** — combina ambos quando o conteúdo é misto
6. **Exportador** — gera saída em Markdown, CSV e/ou JSON

## Instalação

```bash
# Clone e entre no diretório
cd projeto_balancetes

# Crie e ative o ambiente virtual
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate # Linux/Mac

# Instale as dependências
pip install -r requirements.txt
```

## Configuração

Crie um arquivo `.env` na raiz do projeto:

```env
GEMINI_API_KEY=sua_chave_gemini_aqui
```

> Para obter uma chave: https://aistudio.google.com/apikey

## Uso

### Processamento básico

```python
from src.orchestrator import Orchestrator, OutputFormat

orch = Orchestrator()

# Processa um PDF com saída em todos os formatos
result = orch.process("data/input/balancete_jan2024.pdf", output_format=OutputFormat.ALL)

print(f"Sucesso: {result.success}")
print(f"Rota usada: {result.route_used}")
print(f"Tempo: {result.processing_time:.2f}s")
print(f"Custo: ${result.estimated_cost:.4f}")
print(f"Arquivos gerados:")
for f in result.output_files:
    print(f"  {f}")
```

### Escolher formato de saída

```python
# Apenas Markdown
result = orch.process("balancete.pdf", output_format=OutputFormat.MARKDOWN)

# Apenas CSV (extrai tabelas)
result = orch.process("balancete.pdf", output_format=OutputFormat.CSV)

# Apenas JSON (estruturado)
result = orch.process("balancete.pdf", output_format=OutputFormat.JSON)
```

### Forçar uma rota específica

```python
from src.agents.classifier import ProcessingRoute

# Forçar Gemini mesmo para PDFs com texto
result = orch.process("relatorio.pdf", force_route=ProcessingRoute.GEMINI)

# Forçar Docling (sem custo de API)
result = orch.process("balancete.pdf", force_route=ProcessingRoute.DOCLING)
```

### Processamento em lote

```python
from pathlib import Path

pdfs = list(Path("data/input").glob("*.pdf"))
results = orch.process_batch(pdfs, output_format=OutputFormat.ALL)

for r in results:
    status = "OK" if r.success else "ERRO"
    print(f"[{status}] {r.file_path} → {r.route_used} ({r.processing_time:.1f}s)")
```

### Script rápido via linha de comando

```python
# main.py
import sys
from pathlib import Path
from src.orchestrator import Orchestrator, OutputFormat

if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "data/input"
    orch = Orchestrator()

    path = Path(pdf_path)
    if path.is_dir():
        pdfs = list(path.glob("*.pdf"))
        results = orch.process_batch(pdfs)
    else:
        results = [orch.process(path)]

    for r in results:
        print(f"{'OK' if r.success else 'ERRO'} | {r.file_path} | {r.route_used} | {r.processing_time:.1f}s | ${r.estimated_cost:.4f}")
```

## Testes

```bash
pytest tests/ -v
```

## Estrutura do Projeto

```
projeto_balancetes/
├── src/
│   ├── orchestrator.py           # Orquestrador principal
│   ├── agents/
│   │   ├── docling_agent.py     # Extração local de texto
│   │   ├── gemini_agent.py      # Análise visual via API
│   │   └── classifier.py        # Classificação de conteúdo
│   ├── parsers/
│   │   ├── markdown_parser.py   # Exportação Markdown
│   │   ├── csv_parser.py        # Exportação CSV
│   │   └── json_parser.py       # Exportação JSON
│   └── utils/
│       ├── pdf_analyzer.py      # Análise estrutural (PyMuPDF)
│       └── config.py            # Configurações e API keys
├── data/
│   ├── input/                   # PDFs de entrada
│   └── output/                  # Resultados processados
├── tests/
│   └── test_orchestrator.py
├── .env                         # API keys
├── requirements.txt
└── README.md
```

## Custos

| Agente | Custo | Velocidade | Melhor para |
|--------|-------|------------|-------------|
| Docling | Gratuito | Rápido | Texto corrido, contratos |
| Gemini Flash | ~$0.10/1M input tokens | Moderado | Tabelas, scans, gráficos |
| Híbrido | Custo do Gemini | Mais lento | Documentos mistos |
