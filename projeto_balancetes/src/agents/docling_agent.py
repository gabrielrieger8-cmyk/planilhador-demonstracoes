"""Agente Docling para extração de texto de PDFs.

Processa PDFs com texto predominante de forma local, sem custo de API.
Ideal para relatórios narrativos, contratos e documentos com texto corrido.
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import logger


class _ProgressSpinner:
    """Spinner animado para indicar processamento em andamento."""

    def __init__(self, message: str = "Processando") -> None:
        self._message = message
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

    def _spin(self) -> None:
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        start = time.time()
        while self._running:
            elapsed = time.time() - start
            sys.stdout.write(
                f"\r  {frames[i % len(frames)]} {self._message}... ({elapsed:.0f}s)"
            )
            sys.stdout.flush()
            time.sleep(0.15)
            i += 1


@dataclass
class DoclingResult:
    """Resultado do processamento pelo agente Docling."""

    text: str
    tables: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    processing_time: float = 0.0
    success: bool = True
    error: str | None = None


class DoclingAgent:
    """Agente que usa a biblioteca Docling para extrair texto de PDFs.

    Docling é uma ferramenta local e gratuita que converte PDFs em
    texto estruturado, incluindo detecção básica de tabelas.
    """

    def __init__(self) -> None:
        self._converter = None
        logger.info("DoclingAgent inicializado.")

    def _get_converter(self):
        """Inicializa o converter Docling sob demanda (lazy loading)."""
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter

                self._converter = DocumentConverter()
                logger.info("Docling DocumentConverter carregado com sucesso.")
            except ImportError as exc:
                raise ImportError(
                    "Docling não está instalado. Execute: pip install docling"
                ) from exc
        return self._converter

    def process(self, file_path: str | Path) -> DoclingResult:
        """Processa um PDF usando Docling.

        Args:
            file_path: Caminho para o arquivo PDF.

        Returns:
            DoclingResult com texto extraído e metadados.
        """
        path = Path(file_path)
        if not path.exists():
            return DoclingResult(
                text="",
                success=False,
                error=f"Arquivo não encontrado: {path}",
            )

        logger.info("Docling processando: %s", path.name)
        start_time = time.time()
        spinner = _ProgressSpinner(f"Docling extraindo texto de {path.name}")

        try:
            converter = self._get_converter()
            spinner.start()
            result = converter.convert(str(path))
            spinner.stop()

            # Extrai texto em Markdown
            markdown_text = result.document.export_to_markdown()

            # Extrai tabelas se disponíveis
            tables = self._extract_tables(result)

            processing_time = time.time() - start_time
            logger.info(
                "Docling concluiu em %.2fs: %d chars, %d tabelas",
                processing_time,
                len(markdown_text),
                len(tables),
            )

            return DoclingResult(
                text=markdown_text,
                tables=tables,
                metadata={
                    "source": str(path),
                    "agent": "docling",
                    "chars_extracted": len(markdown_text),
                    "tables_found": len(tables),
                },
                processing_time=processing_time,
            )

        except Exception as exc:
            spinner.stop()
            processing_time = time.time() - start_time
            error_msg = f"Erro no processamento Docling: {exc}"
            logger.error(error_msg)
            return DoclingResult(
                text="",
                processing_time=processing_time,
                success=False,
                error=error_msg,
            )

    def _extract_tables(self, result) -> list[dict]:
        """Extrai tabelas do resultado Docling.

        Args:
            result: Resultado da conversão Docling.

        Returns:
            Lista de dicionários com dados tabulares.
        """
        tables: list[dict] = []
        try:
            doc = result.document
            for i, table in enumerate(doc.tables):
                table_data = {
                    "index": i,
                    "markdown": table.export_to_markdown()
                    if hasattr(table, "export_to_markdown")
                    else str(table),
                }
                # Tenta extrair como DataFrame se disponível
                if hasattr(table, "export_to_dataframe"):
                    try:
                        df = table.export_to_dataframe()
                        table_data["headers"] = list(df.columns)
                        table_data["rows"] = df.values.tolist()
                        table_data["row_count"] = len(df)
                    except Exception:
                        pass
                tables.append(table_data)
        except (AttributeError, TypeError):
            # Documento pode não ter tabelas ou API diferente
            pass
        return tables
