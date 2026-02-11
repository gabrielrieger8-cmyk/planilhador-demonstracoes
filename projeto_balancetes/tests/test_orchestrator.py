"""Testes do sistema de processamento de PDFs financeiros.

Testes unitários para classificador, parsers e orquestrador.
Usa mocks para evitar dependência de APIs externas e PDFs reais.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.classifier import (
    ClassificationResult,
    ContentType,
    ProcessingRoute,
    classify,
)
from src.parsers.csv_parser import extract_markdown_tables, tables_to_csv_string
from src.parsers.json_parser import structure_content
from src.utils.pdf_analyzer import PDFAnalysis, PageAnalysis


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def text_heavy_analysis() -> PDFAnalysis:
    """PDF com predominância de texto."""
    return PDFAnalysis(
        file_path="relatorio.pdf",
        total_pages=10,
        total_chars=50000,
        total_words=8000,
        total_images=0,
        total_tables=0,
        avg_chars_per_page=5000,
        avg_image_area_ratio=0.0,
        pages=[
            PageAnalysis(
                page_number=i,
                char_count=5000,
                word_count=800,
                image_count=0,
                image_area_ratio=0.0,
                table_count=0,
                has_drawings=False,
            )
            for i in range(10)
        ],
        has_scanned_content=False,
    )


@pytest.fixture
def visual_heavy_analysis() -> PDFAnalysis:
    """PDF com predominância visual (tabelas/imagens)."""
    return PDFAnalysis(
        file_path="balancete.pdf",
        total_pages=5,
        total_chars=2000,
        total_words=300,
        total_images=10,
        total_tables=8,
        avg_chars_per_page=400,
        avg_image_area_ratio=0.30,
        pages=[
            PageAnalysis(
                page_number=i,
                char_count=400,
                word_count=60,
                image_count=2,
                image_area_ratio=0.30,
                table_count=2,
                has_drawings=True,
            )
            for i in range(5)
        ],
        has_scanned_content=False,
    )


@pytest.fixture
def scanned_analysis() -> PDFAnalysis:
    """PDF escaneado (imagens sem texto)."""
    return PDFAnalysis(
        file_path="scan.pdf",
        total_pages=3,
        total_chars=50,
        total_words=5,
        total_images=3,
        total_tables=0,
        avg_chars_per_page=17,
        avg_image_area_ratio=0.90,
        pages=[
            PageAnalysis(
                page_number=i,
                char_count=17,
                word_count=2,
                image_count=1,
                image_area_ratio=0.90,
                table_count=0,
                has_drawings=False,
            )
            for i in range(3)
        ],
        has_scanned_content=True,
    )


@pytest.fixture
def sample_markdown_with_tables() -> str:
    """Texto Markdown com tabelas financeiras."""
    return """\
# Balancete Mensal - Janeiro 2024

## Ativo

| Conta | Descrição | Saldo Anterior | Débito | Crédito | Saldo Atual |
|-------|-----------|----------------|--------|---------|-------------|
| 1.1.1 | Caixa | 10.000,00 | 5.000,00 | 3.000,00 | 12.000,00 |
| 1.1.2 | Bancos | 50.000,00 | 20.000,00 | 15.000,00 | 55.000,00 |
| 1.2.1 | Clientes | 30.000,00 | 10.000,00 | 8.000,00 | 32.000,00 |

## Passivo

| Conta | Descrição | Saldo Anterior | Débito | Crédito | Saldo Atual |
|-------|-----------|----------------|--------|---------|-------------|
| 2.1.1 | Fornecedores | 25.000,00 | 12.000,00 | 10.000,00 | 23.000,00 |
| 2.1.2 | Impostos | 8.000,00 | 3.000,00 | 5.000,00 | 10.000,00 |
"""


# ---------------------------------------------------------------------------
# Testes do Classificador
# ---------------------------------------------------------------------------
class TestClassifier:
    """Testes para o classificador de conteúdo."""

    def test_text_heavy_routes_to_docling(self, text_heavy_analysis: PDFAnalysis):
        result = classify(text_heavy_analysis)
        assert result.route == ProcessingRoute.DOCLING
        assert result.content_type == ContentType.TEXT
        assert result.confidence > 0.5

    def test_visual_heavy_routes_to_gemini(self, visual_heavy_analysis: PDFAnalysis):
        result = classify(visual_heavy_analysis)
        assert result.route in (ProcessingRoute.GEMINI, ProcessingRoute.HYBRID)
        assert result.confidence > 0.5

    def test_scanned_always_routes_to_gemini(self, scanned_analysis: PDFAnalysis):
        result = classify(scanned_analysis)
        assert result.route == ProcessingRoute.GEMINI
        assert result.content_type == ContentType.VISUAL
        assert result.confidence >= 0.95

    def test_classification_has_reasoning(self, text_heavy_analysis: PDFAnalysis):
        result = classify(text_heavy_analysis)
        assert result.reasoning
        assert len(result.reasoning) > 10

    def test_classification_has_details(self, visual_heavy_analysis: PDFAnalysis):
        result = classify(visual_heavy_analysis)
        assert "text_score" in result.details
        assert "visual_score" in result.details


# ---------------------------------------------------------------------------
# Testes dos Parsers
# ---------------------------------------------------------------------------
class TestMarkdownTableExtraction:
    """Testes para extração de tabelas Markdown."""

    def test_extracts_two_tables(self, sample_markdown_with_tables: str):
        tables = extract_markdown_tables(sample_markdown_with_tables)
        assert len(tables) == 2

    def test_first_table_has_correct_rows(self, sample_markdown_with_tables: str):
        tables = extract_markdown_tables(sample_markdown_with_tables)
        # Cabeçalho + 3 linhas de dados
        assert len(tables[0]) == 4

    def test_second_table_has_correct_rows(self, sample_markdown_with_tables: str):
        tables = extract_markdown_tables(sample_markdown_with_tables)
        # Cabeçalho + 2 linhas de dados
        assert len(tables[1]) == 3

    def test_csv_string_output(self, sample_markdown_with_tables: str):
        tables = extract_markdown_tables(sample_markdown_with_tables)
        csv_str = tables_to_csv_string(tables)
        assert "Caixa" in csv_str
        assert "Fornecedores" in csv_str

    def test_empty_text_returns_no_tables(self):
        tables = extract_markdown_tables("Texto sem tabelas.")
        assert tables == []


class TestJsonStructure:
    """Testes para estruturação em JSON."""

    def test_structure_has_documento(self, sample_markdown_with_tables: str):
        result = structure_content(sample_markdown_with_tables)
        assert "documento" in result
        assert "data_processamento" in result["documento"]

    def test_structure_has_tabelas(self, sample_markdown_with_tables: str):
        result = structure_content(sample_markdown_with_tables)
        assert len(result["conteudo"]["tabelas"]) == 2

    def test_structure_has_secoes(self, sample_markdown_with_tables: str):
        result = structure_content(sample_markdown_with_tables)
        sections = result["conteudo"]["secoes"]
        titles = [s["titulo"] for s in sections]
        assert "Ativo" in titles
        assert "Passivo" in titles

    def test_table_dict_has_headers(self, sample_markdown_with_tables: str):
        result = structure_content(sample_markdown_with_tables)
        table = result["conteudo"]["tabelas"][0]
        assert "Conta" in table["cabecalhos"]
        assert "Saldo Atual" in table["cabecalhos"]

    def test_metadata_included(self, sample_markdown_with_tables: str):
        meta = {"fonte": "test.pdf", "rota": "docling"}
        result = structure_content(sample_markdown_with_tables, metadata=meta)
        assert result["documento"]["metadata"]["fonte"] == "test.pdf"


# ---------------------------------------------------------------------------
# Testes do Orquestrador (com mocks)
# ---------------------------------------------------------------------------
class TestOrchestrator:
    """Testes do orquestrador com dependências mockadas."""

    @patch("src.orchestrator.analyze_pdf")
    @patch("src.orchestrator.classify")
    def test_process_routes_correctly(
        self,
        mock_classify: MagicMock,
        mock_analyze: MagicMock,
        text_heavy_analysis: PDFAnalysis,
        tmp_path: Path,
    ):
        from src.orchestrator import Orchestrator, OutputFormat

        # Setup
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")

        mock_analyze.return_value = text_heavy_analysis
        mock_classify.return_value = ClassificationResult(
            content_type=ContentType.TEXT,
            route=ProcessingRoute.DOCLING,
            confidence=0.9,
            reasoning="Texto predominante.",
            details={"text_score": 0.9, "visual_score": 0.1},
        )

        orch = Orchestrator()
        # Mock do agente Docling
        orch._docling_agent.process = MagicMock(
            return_value=MagicMock(
                text="# Relatório\n\nConteúdo do teste.",
                tables=[],
                success=True,
            )
        )

        result = orch.process(
            pdf_path,
            output_format=OutputFormat.MARKDOWN,
            output_dir=tmp_path,
        )

        assert result.success
        assert result.route_used == ProcessingRoute.DOCLING
        assert len(result.output_files) > 0

    def test_process_nonexistent_file(self, tmp_path: Path):
        from src.orchestrator import Orchestrator

        orch = Orchestrator()
        result = orch.process(tmp_path / "nao_existe.pdf")
        assert not result.success
        assert "não encontrado" in result.error

    def test_process_non_pdf_file(self, tmp_path: Path):
        from src.orchestrator import Orchestrator

        txt_file = tmp_path / "teste.txt"
        txt_file.write_text("not a pdf")

        orch = Orchestrator()
        result = orch.process(txt_file)
        assert not result.success
        assert "não suportado" in result.error


# ---------------------------------------------------------------------------
# Testes de integração de exportação
# ---------------------------------------------------------------------------
class TestExportIntegration:
    """Testes de exportação para verificar que os arquivos são gerados."""

    def test_save_markdown(self, tmp_path: Path):
        from src.parsers.markdown_parser import save_as_markdown

        path = save_as_markdown(
            "# Teste\n\nConteúdo.", "teste_doc", output_dir=tmp_path
        )
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "Conteúdo" in content

    def test_save_csv(self, tmp_path: Path, sample_markdown_with_tables: str):
        from src.parsers.csv_parser import save_as_csv

        paths = save_as_csv(
            sample_markdown_with_tables, "teste_csv", output_dir=tmp_path
        )
        assert len(paths) >= 1
        for p in paths:
            assert p.exists()
            assert p.suffix == ".csv"

    def test_save_json(self, tmp_path: Path, sample_markdown_with_tables: str):
        from src.parsers.json_parser import save_as_json

        path = save_as_json(
            sample_markdown_with_tables, "teste_json", output_dir=tmp_path
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "documento" in data
        assert "conteudo" in data
