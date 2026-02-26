# Planilhador de Demonstrações

Converte PDFs de demonstrações financeiras em planilhas Excel profissionais.

## Stack

- **FastAPI** — backend web com SSE para progresso em tempo real
- **Gemini 2.0 Flash** — classificação de documentos (~$0.003/PDF)
- **Gemini 2.5 Flash** — extração de dados (page-by-page balancetes, bulk DRE/BP)
- **Claude Sonnet** — formatação e estruturação dos dados em JSON
- **openpyxl** — geração de Excel profissional com formatação condicional

## Tipos suportados

- Balancete de Verificação
- Demonstração do Resultado do Exercício (DRE)
- Balanço Patrimonial

## Como rodar

```bash
# Instalar dependências
pip install -r requirements.txt

# Configurar API keys
cp .env.example .env
# Editar .env com suas chaves

# Iniciar servidor
python run.py
# Acesse http://localhost:8000
```

## Testes

```bash
python -m pytest tests/ -v
```
