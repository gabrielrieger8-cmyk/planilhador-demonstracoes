"""Orquestrador principal do sistema de processamento de PDFs financeiros.

Coordena o fluxo completo: análise → classificação → roteamento → processamento → exportação.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from src.agents.classifier import (
    ClassificationResult,
    ProcessingRoute,
    classify,
)
from src.agents.docling_agent import DoclingAgent, DoclingResult
from src.agents.gemini_agent import GeminiAgent, GeminiResult
from src.parsers.csv_parser import save_as_csv, save_signed_csv, save_synthetic_csv
from src.parsers.json_parser import save_as_json
from src.parsers.markdown_parser import (
    format_financial_markdown,
    save_as_markdown,
)
from src.utils.config import OUTPUT_DIR, logger
from src.utils.pdf_analyzer import PDFAnalysis, analyze_pdf


class OutputFormat(str, Enum):
    """Formatos de saída suportados."""

    MARKDOWN = "markdown"
    CSV = "csv"
    JSON = "json"
    ALL = "all"


@dataclass
class ProcessingResult:
    """Resultado completo do processamento de um PDF."""

    file_path: str
    classification: ClassificationResult | None = None
    route_used: ProcessingRoute | None = None
    extracted_text: str = ""
    output_files: list[str] = field(default_factory=list)
    processing_time: float = 0.0
    estimated_cost: float = 0.0
    success: bool = True
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    """Orquestrador principal do sistema.

    Coordena a análise, classificação e roteamento de PDFs para o
    agente apropriado, e exporta os resultados nos formatos desejados.

    Exemplo de uso::

        orch = Orchestrator()
        result = orch.process("balancete_jan2024.pdf", output_format=OutputFormat.ALL)
        print(result.output_files)
    """

    def __init__(self) -> None:
        self._docling_agent = DoclingAgent()
        self._gemini_agent = GeminiAgent()
        logger.info("Orquestrador inicializado.")

    def process(
        self,
        file_path: str | Path,
        output_format: OutputFormat = OutputFormat.ALL,
        force_route: ProcessingRoute | None = None,
        output_dir: str | Path | None = None,
    ) -> ProcessingResult:
        """Processa um PDF financeiro de ponta a ponta.

        Args:
            file_path: Caminho para o PDF.
            output_format: Formato(s) de saída desejado(s).
            force_route: Forçar uma rota específica (ignora classificação).
            output_dir: Diretório de saída (usa padrão se None).

        Returns:
            ProcessingResult com todos os detalhes.
        """
        path = Path(file_path)
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        start_time = time.time()

        logger.info("=" * 60)
        logger.info("Iniciando processamento: %s", path.name)
        logger.info("=" * 60)

        # 1. Validação
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
            # 2. Análise estrutural
            logger.info("[1/4] Analisando estrutura do PDF...")
            analysis = analyze_pdf(path)

            # 3. Classificação
            logger.info("[2/4] Classificando conteúdo...")
            classification = classify(analysis)
            route = force_route or classification.route

            logger.info(
                "Classificação: %s (confiança: %.0f%%) → Rota: %s",
                classification.content_type.value,
                classification.confidence * 100,
                route.value,
            )
            logger.info("Razão: %s", classification.reasoning)

            # 4. Processamento pelo agente apropriado
            logger.info("[3/4] Processando com agente: %s", route.value)
            extracted_text, cost = self._route_to_agent(path, route, analysis)

            if not extracted_text:
                return ProcessingResult(
                    file_path=str(path),
                    classification=classification,
                    route_used=route,
                    success=False,
                    error="Nenhum texto extraído do PDF.",
                    processing_time=time.time() - start_time,
                )

            # 5. Exportação
            logger.info("[4/4] Exportando resultados...")
            output_files = self._export(
                text=extracted_text,
                filename=path.stem,
                output_format=output_format,
                metadata={
                    "fonte": path.name,
                    "rota": route.value,
                    "classificacao": classification.content_type.value,
                    "confianca": f"{classification.confidence:.0%}",
                    "paginas": analysis.total_pages,
                },
                output_dir=out_dir,
            )

            processing_time = time.time() - start_time

            logger.info("-" * 60)
            logger.info("Processamento concluído em %.2fs", processing_time)
            logger.info("Arquivos gerados: %d", len(output_files))
            for f in output_files:
                logger.info("  → %s", f)
            logger.info("Custo estimado: $%.4f", cost)
            logger.info("-" * 60)

            return ProcessingResult(
                file_path=str(path),
                classification=classification,
                route_used=route,
                extracted_text=extracted_text,
                output_files=[str(f) for f in output_files],
                processing_time=processing_time,
                estimated_cost=cost,
                details={
                    "analysis": {
                        "total_pages": analysis.total_pages,
                        "total_chars": analysis.total_chars,
                        "total_images": analysis.total_images,
                        "total_tables": analysis.total_tables,
                        "has_scanned": analysis.has_scanned_content,
                    },
                    "classification": {
                        "type": classification.content_type.value,
                        "route": classification.route.value,
                        "confidence": classification.confidence,
                        "scores": classification.details,
                    },
                },
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

    def process_batch(
        self,
        file_paths: list[str | Path],
        output_format: OutputFormat = OutputFormat.ALL,
        output_dir: str | Path | None = None,
    ) -> list[ProcessingResult]:
        """Processa múltiplos PDFs em sequência.

        Args:
            file_paths: Lista de caminhos para PDFs.
            output_format: Formato de saída.
            output_dir: Diretório de saída.

        Returns:
            Lista de ProcessingResult, um por arquivo.
        """
        results: list[ProcessingResult] = []
        total = len(file_paths)

        logger.info("Processamento em lote: %d arquivos", total)

        for i, fp in enumerate(file_paths, 1):
            logger.info("Arquivo %d/%d: %s", i, total, Path(fp).name)
            result = self.process(fp, output_format=output_format, output_dir=output_dir)
            results.append(result)

        # Resumo do lote
        successful = sum(1 for r in results if r.success)
        total_cost = sum(r.estimated_cost for r in results)
        total_time = sum(r.processing_time for r in results)

        logger.info("=" * 60)
        logger.info("RESUMO DO LOTE")
        logger.info("Total: %d | Sucesso: %d | Falhas: %d", total, successful, total - successful)
        logger.info("Tempo total: %.2fs | Custo total: $%.4f", total_time, total_cost)
        logger.info("=" * 60)

        return results

    def process_batch_parallel(
        self,
        file_paths: list[str | Path],
        max_workers: int = 2,
        output_format: OutputFormat = OutputFormat.CSV,
        output_dir: str | Path | None = None,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> list[ProcessingResult]:
        """Processa múltiplos PDFs em paralelo usando ThreadPoolExecutor.

        Cada worker cria sua própria instância de Orchestrator para
        garantir thread-safety (evita race condition no lazy init do GeminiAgent).

        Args:
            file_paths: Lista de caminhos para PDFs.
            max_workers: Número de workers paralelos (2=free, 5-10=paid).
            output_format: Formato de saída.
            output_dir: Diretório de saída.
            progress_callback: Chamado com (completed, total, filename) após cada PDF.

        Returns:
            Lista de ProcessingResult na ordem original.
        """
        total = len(file_paths)
        results: dict[int, ProcessingResult] = {}

        logger.info("=" * 60)
        logger.info(
            "Processamento paralelo: %d arquivo(s) com %d worker(s)",
            total,
            max_workers,
        )
        logger.info("=" * 60)

        def _process_one(idx: int, fp: str | Path) -> tuple[int, ProcessingResult]:
            """Worker: cria Orchestrator isolado e processa um PDF."""
            worker_orch = Orchestrator()
            result = worker_orch.process(
                fp,
                output_format=output_format,
                force_route=ProcessingRoute.GEMINI,
                output_dir=output_dir,
            )
            return idx, result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_process_one, i, fp): i
                for i, fp in enumerate(file_paths)
            }

            completed = 0
            for future in as_completed(future_to_idx):
                try:
                    idx, result = future.result()
                    results[idx] = result
                except Exception as exc:
                    idx = future_to_idx[future]
                    results[idx] = ProcessingResult(
                        file_path=str(file_paths[idx]),
                        success=False,
                        error=f"Erro no worker: {exc}",
                    )

                completed += 1
                filename = Path(file_paths[future_to_idx[future]]).name

                if progress_callback:
                    progress_callback(completed, total, filename)

                logger.info("Progresso: %d/%d concluído (%s)", completed, total, filename)

        # Retorna na ordem original
        sorted_results = [results[i] for i in range(total)]

        successful = sum(1 for r in sorted_results if r.success)
        total_cost = sum(r.estimated_cost for r in sorted_results)
        total_time = sum(r.processing_time for r in sorted_results)

        logger.info("=" * 60)
        logger.info("RESUMO PARALELO")
        logger.info(
            "Total: %d | Sucesso: %d | Falhas: %d",
            total, successful, total - successful,
        )
        logger.info("Tempo total: %.2fs | Custo total: $%.4f", total_time, total_cost)
        logger.info("=" * 60)

        return sorted_results

    def _route_to_agent(
        self, path: Path, route: ProcessingRoute, analysis: PDFAnalysis
    ) -> tuple[str, float]:
        """Roteia o PDF para o agente apropriado.

        Args:
            path: Caminho do PDF.
            route: Rota de processamento.
            analysis: Análise estrutural.

        Returns:
            Tupla (texto extraído, custo estimado).
        """
        if route == ProcessingRoute.DOCLING:
            return self._process_with_docling(path)

        if route == ProcessingRoute.GEMINI:
            return self._process_with_gemini(path)

        # HYBRID: usa ambos e combina
        return self._process_hybrid(path, analysis)

    def _process_with_docling(self, path: Path) -> tuple[str, float]:
        """Processa com Docling (custo zero).

        Returns:
            Tupla (texto, custo=0.0).
        """
        result: DoclingResult = self._docling_agent.process(path)
        if not result.success:
            logger.warning("Docling falhou: %s", result.error)
            return "", 0.0
        return result.text, 0.0

    def _process_with_gemini(self, path: Path) -> tuple[str, float]:
        """Processa com Gemini.

        Returns:
            Tupla (texto, custo estimado).
        """
        result: GeminiResult = self._gemini_agent.process(path, financial=True)
        if not result.success:
            logger.warning("Gemini falhou: %s", result.error)
            return "", 0.0
        return result.text, result.estimated_cost

    def _process_hybrid(
        self, path: Path, analysis: PDFAnalysis
    ) -> tuple[str, float]:
        """Processamento híbrido: Docling para texto + Gemini para visual.

        Combina o melhor de ambos agentes.

        Returns:
            Tupla (texto combinado, custo do Gemini).
        """
        logger.info("Modo híbrido: combinando Docling + Gemini")

        # Docling extrai a base textual
        docling_result = self._docling_agent.process(path)
        docling_text = docling_result.text if docling_result.success else ""

        # Gemini extrai tabelas e conteúdo visual
        gemini_result = self._gemini_agent.process(path, financial=True)
        gemini_text = gemini_result.text if gemini_result.success else ""
        gemini_cost = gemini_result.estimated_cost if gemini_result.success else 0.0

        # Combina resultados
        combined_parts: list[str] = []

        if docling_text:
            combined_parts.append("# Conteúdo Textual (Docling)\n")
            combined_parts.append(docling_text)

        if gemini_text:
            combined_parts.append("\n\n# Conteúdo Visual (Gemini)\n")
            combined_parts.append(gemini_text)

        combined = "\n".join(combined_parts) if combined_parts else ""
        return combined, gemini_cost

    def _export(
        self,
        text: str,
        filename: str,
        output_format: OutputFormat,
        metadata: dict,
        output_dir: Path,
    ) -> list[Path]:
        """Exporta o texto nos formatos solicitados.

        Args:
            text: Texto extraído.
            filename: Nome base do arquivo.
            output_format: Formato(s) de saída.
            metadata: Metadados do processamento.
            output_dir: Diretório de saída.

        Returns:
            Lista de Paths dos arquivos gerados.
        """
        files: list[Path] = []

        formatted_text = format_financial_markdown(
            text=text,
            title=f"Documento: {filename}",
            source_file=metadata.get("fonte", ""),
        )

        if output_format in (OutputFormat.MARKDOWN, OutputFormat.ALL):
            md_path = save_as_markdown(
                formatted_text, filename, metadata=metadata, output_dir=output_dir
            )
            files.append(md_path)

        if output_format in (OutputFormat.CSV, OutputFormat.ALL):
            # Debug: salva texto raw do Gemini para diagnóstico
            raw_path = output_dir / f"{filename}_raw.txt"
            raw_path.write_text(text, encoding="utf-8")
            logger.info("Texto raw salvo em: %s (%d chars)", raw_path, len(text))
            csv_paths, unified_rows = save_as_csv(text, filename, output_dir=output_dir)
            files.extend(csv_paths)

        if output_format in (OutputFormat.JSON, OutputFormat.ALL):
            json_path = save_as_json(
                text, filename, metadata=metadata, output_dir=output_dir
            )
            files.append(json_path)

        return files
