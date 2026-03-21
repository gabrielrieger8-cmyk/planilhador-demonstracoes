FROM python:3.12-slim

WORKDIR /app

# Dependencias do sistema para PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt fastmcp uvicorn

COPY . .

RUN mkdir -p /app/output

EXPOSE 8000

ENV MCP_TRANSPORT=http
ENV PORT=8000

CMD ["python", "mcp_server.py"]
