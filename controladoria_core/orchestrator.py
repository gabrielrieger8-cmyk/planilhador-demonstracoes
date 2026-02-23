"""Orquestrador principal do sistema de processamento de PDFs financeiros.

Fluxo simplificado: validação → Gemini → exportação CSV.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF — apenas para contar páginas

from controladoria_core.agents.gemini_agent import GeminiAgent, GeminiResult
from controladoria_core.parsers.csv_parser import save_as_csv, save_as_xlsx
from controladoria_core.utils.config import OUTPUT_DIR, logger


class OutputFormat(str, Enum):
    """Formatos de saída suportados."""

    CSV = "csv"


@dataclass
class ProcessingResult:
    """Resultado completo do processamento de um PDF."""

    file_path: str
    extracted_text: str = ""
    output_files: list[str] = field(default_factory=list)
    processing_time: float = 0.0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    """Orquestrador principal — envia PDFs direto ao Gemini.

    Exemplo de uso::

        orch = Orchestrator()
        result = orch.process("balancete_jan2024.pdf", output_format=OutputFormat.CSV)
        print(result.output_files)
    """

    def __init__(self) -> None:
        self._gemini_agent = GeminiAgent()
        logger.info("Orquestrador inicializado (Gemini only).")

    def process(
        self,
        file_path: str | Path,
        output_format: OutputFormat = OutputFormat.CSV,
        output_dir: str | Path | None = None,
        **kwargs,
    ) -> ProcessingResult:
        """Processa um PDF financeiro: envia ao Gemini e exporta.

        Args:
            file_path: Caminho para o PDF.
            output_format: Formato(s) de saída desejado(s).
            output_dir: Diretório de saída (usa padrão se None).

        Returns:
            ProcessingResult com todos os detalhes.
        """
        path = Path(file_path)
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        start_time = time.time()

        logger.info("=" * 60)
        logger.info("Processando: %s", path.name)
        logger.info("=" * 60)

        # Validação
        if not path.exists():
            return ProcessingResult(
                file_path=str(path),
                success=False,
                error=f"Arquivo não encontrado: {path}",
            )

        if not path.suffix.lower() == ".pdf":
            return ProcessingResult(
                file_path=str(path),
                success=False,
                error=f"Formato não suportado: {path.suffix}",
            )

        try:
            # Conta páginas
            doc = fitz.open(str(path))
            total_pages = len(doc)
            doc.close()

            # Envia direto ao Gemini
            reference_name = kwargs.get("reference_name")
            logger.info("[1/2] Enviando ao Gemini (%d páginas)... ref=%s", total_pages, reference_name)
            result: GeminiResult = self._gemini_agent.process(
                path, financial=True, reference_name=reference_name,
            )

            if not result.success:
                return ProcessingResult(
                    file_path=str(path),
                    success=False,
                    error=result.error or "Gemini não retornou texto.",
                    processing_time=time.time() - start_time,
                )

            if not result.text:
                return ProcessingResult(
                    file_path=str(path),
                    success=False,
                    error="Nenhum texto extraído do PDF.",
                    processing_time=time.time() - start_time,
                )

            # Exportação
            logger.info("[2/2] Exportando resultados...")
            output_files, unified_rows = self._export(
                text=result.text,
                filename=path.stem,
                output_format=output_format,
                metadata={
                    "fonte": path.name,
                    "modelo": result.metadata.get("model", ""),
                    "paginas": total_pages,
                },
                output_dir=out_dir,
            )

            processing_time = time.time() - start_time

            logger.info("-" * 60)
            logger.info("Concluído em %.2fs — %d arquivo(s)", processing_time, len(output_files))
            logger.info("Custo: $%.4f", result.estimated_cost)
            logger.info("-" * 60)

            # Inclui preview_rows nos details para o frontend
            details = dict(result.metadata)
            if unified_rows:
                details["preview_rows"] = unified_rows

            return ProcessingResult(
                file_path=str(path),
                extracted_text=result.text,
                output_files=[str(f) for f in output_files],
                processing_time=processing_time,
                estimated_cost=result.estimated_cost,
                details=details,
            )

        except Exception as exc:
            processing_time = time.time() - start_time
            error_msg = f"Erro no processamento: {exc}"
            logger.error(error_msg, exc_info=True)
            return ProcessingResult(
                file_path=str(path),
                success=False,
                error=error_msg,
                processing_time=processing_time,
            )

    def _export(
        self,
        text: str,
        filename: str,
        output_format: OutputFormat,
        metadata: dict,
        output_dir: Path,
    ) -> tuple[list[Path], list[list[str]]]:
        """Exporta o texto nos formatos solicitados.

        Returns:
            Tupla (lista de Paths gerados, linhas unificadas para preview).
        """
        files: list[Path] = []
        unified_rows: list[list[str]] = []

        # Debug: salva texto raw do Gemini para diagnóstico
        raw_path = output_dir / f"{filename}_raw.txt"
        raw_path.write_text(text, encoding="utf-8")
        logger.info("Texto raw salvo em: %s (%d chars)", raw_path, len(text))

        csv_paths, unified_rows = save_as_csv(text, filename, output_dir=output_dir)
        files.extend(csv_paths)

        # Gera .xlsx formatado a partir das mesmas linhas
        if unified_rows:
            try:
                xlsx_path = save_as_xlsx(unified_rows, filename, output_dir=output_dir)
                files.append(xlsx_path)
            except Exception as exc:
                logger.warning("Erro ao gerar XLSX: %s", exc)

        return files, unified_rows
