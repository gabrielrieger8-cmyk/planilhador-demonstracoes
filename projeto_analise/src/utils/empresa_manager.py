"""Gerenciador de empresas e grupos econômicos baseado em filesystem.

Estrutura de pastas:
    data/empresas/
      Grupo ABC/                    ← grupo (contém subpastas de empresas)
        ABC Holding/
          balancetes/               ← PDFs
          output/                   ← CSVs gerados
          analise/                  ← CSVs selecionados para análise
      VFR Logística/                ← empresa solo (tem balancetes/ direto)
        balancetes/
        output/
        analise/

Detecção:
    - Pasta com ``balancetes/`` dentro → empresa
    - Pasta cujas subpastas são empresas → grupo
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PDFInfo:
    """Metadados de um arquivo PDF."""

    path: Path
    name: str
    page_count: int
    converted: bool
    csv_files: list[Path] = field(default_factory=list)


@dataclass
class Company:
    """Representa uma empresa com seus balancetes."""

    name: str
    path: Path
    balancetes_dir: Path
    output_dir: Path
    analise_dir: Path
    pdfs: list[PDFInfo] = field(default_factory=list)
    csv_output: list[Path] = field(default_factory=list)
    csv_analise: list[Path] = field(default_factory=list)


@dataclass
class Group:
    """Representa um grupo econômico com múltiplas empresas."""

    name: str
    path: Path
    companies: list[Company] = field(default_factory=list)


@dataclass
class EmpresasStructure:
    """Estrutura completa de grupos e empresas standalone."""

    standalone_companies: list[Company] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Constantes de estimativa
# ---------------------------------------------------------------------------

PAGES_PER_BATCH = 5
SECONDS_PER_API_CALL = 12.0
TOKENS_INPUT_PER_PAGE = 5_000
TOKENS_OUTPUT_PER_PAGE = 1_000

# Gemini 3 Flash Preview pricing (USD per 1M tokens)
PRICE_INPUT_PER_M = 0.50
PRICE_OUTPUT_PER_M = 3.00


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class EmpresaManager:
    """Gerencia estrutura de empresas/grupos no filesystem."""

    def __init__(self, empresas_dir: Path) -> None:
        self.empresas_dir = empresas_dir
        self.empresas_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------

    def scan_structure(self) -> EmpresasStructure:
        """Escaneia o diretório e retorna a estrutura de empresas/grupos."""
        structure = EmpresasStructure()

        if not self.empresas_dir.exists():
            return structure

        for folder in sorted(self.empresas_dir.iterdir()):
            if not folder.is_dir():
                continue

            kind = self._classify_folder(folder)

            if kind == "company":
                structure.standalone_companies.append(self._build_company(folder))
            elif kind == "group":
                group = Group(name=folder.name, path=folder)
                for sub in sorted(folder.iterdir()):
                    if sub.is_dir() and self._classify_folder(sub) == "company":
                        group.companies.append(self._build_company(sub))
                structure.groups.append(group)

        return structure

    # ------------------------------------------------------------------
    # Criação
    # ------------------------------------------------------------------

    def create_group(self, name: str) -> Path:
        """Cria um novo grupo econômico (pasta)."""
        group_dir = self.empresas_dir / name
        group_dir.mkdir(parents=True, exist_ok=True)
        return group_dir

    def create_company(self, name: str, parent_dir: Path | None = None) -> Company:
        """Cria uma nova empresa com subpastas balancetes/, output/ e analise/.

        Args:
            name: Nome da empresa.
            parent_dir: Pasta do grupo (None = standalone).
        """
        base = parent_dir if parent_dir else self.empresas_dir
        company_dir = base / name
        balancetes_dir = company_dir / "balancetes"
        output_dir = company_dir / "output"
        analise_dir = company_dir / "analise"
        balancetes_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        analise_dir.mkdir(parents=True, exist_ok=True)
        return Company(
            name=name,
            path=company_dir,
            balancetes_dir=balancetes_dir,
            output_dir=output_dir,
            analise_dir=analise_dir,
        )

    # ------------------------------------------------------------------
    # Deleção
    # ------------------------------------------------------------------

    def delete_company(self, company_path: Path) -> None:
        """Deleta uma empresa e todo seu conteúdo."""
        if company_path.exists() and company_path.is_dir():
            shutil.rmtree(company_path)

    def delete_group(self, group_path: Path) -> None:
        """Deleta um grupo e todas suas empresas."""
        if group_path.exists() and group_path.is_dir():
            shutil.rmtree(group_path)

    def delete_file(self, file_path: Path) -> None:
        """Deleta um arquivo individual (PDF ou CSV)."""
        if file_path.exists() and file_path.is_file():
            file_path.unlink()

    def delete_folder(self, folder_path: Path) -> None:
        """Deleta uma pasta e todo seu conteúdo."""
        if folder_path.exists() and folder_path.is_dir():
            shutil.rmtree(folder_path)

    # ------------------------------------------------------------------
    # Operações de arquivo
    # ------------------------------------------------------------------

    def create_folder(self, parent_path: Path, name: str) -> Path:
        """Cria uma subpasta dentro de um diretório."""
        new_dir = parent_path / name
        new_dir.mkdir(parents=True, exist_ok=True)
        return new_dir

    def move_file(self, src: Path, dest_dir: Path) -> Path:
        """Move um arquivo para outro diretório."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.move(str(src), str(dest))
        return dest

    def copy_to_analise(self, csv_paths: list[Path], company: Company) -> list[Path]:
        """Copia CSVs selecionados de output/ para analise/."""
        company.analise_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for src in csv_paths:
            if src.exists():
                dest = company.analise_dir / src.name
                shutil.copy2(str(src), str(dest))
                copied.append(dest)
        return copied

    # ------------------------------------------------------------------
    # Estimativa
    # ------------------------------------------------------------------

    def estimate_processing(
        self,
        pdf_infos: list[PDFInfo],
        mode: Literal["free", "paid"],
    ) -> dict:
        """Estima tempo e custo para processar os PDFs selecionados.

        Returns:
            Dict com total_pages, total_api_calls, estimated_time_seconds,
            estimated_cost_usd, estimated_cost_brl, mode.
        """
        total_pages = sum(p.page_count for p in pdf_infos)
        calls_per_pdf = [math.ceil(p.page_count / PAGES_PER_BATCH) + 1 for p in pdf_infos]
        total_calls = sum(calls_per_pdf)
        max_calls_single = max(calls_per_pdf) if calls_per_pdf else 0

        if mode == "free":
            # 2 workers — metade do tempo sequencial
            estimated_time = (total_calls / 2) * SECONDS_PER_API_CALL
            estimated_cost = 0.0
        else:
            # N workers — limitado pelo PDF mais pesado
            estimated_time = max_calls_single * SECONDS_PER_API_CALL
            # Custo baseado em tokens
            input_cost = (total_pages * TOKENS_INPUT_PER_PAGE / 1_000_000) * PRICE_INPUT_PER_M
            output_cost = (total_pages * TOKENS_OUTPUT_PER_PAGE / 1_000_000) * PRICE_OUTPUT_PER_M
            estimated_cost = input_cost + output_cost

        return {
            "total_pages": total_pages,
            "total_api_calls": total_calls,
            "estimated_time_seconds": estimated_time,
            "estimated_cost_usd": estimated_cost,
            "estimated_cost_brl": estimated_cost * 5.80,  # câmbio aproximado
            "mode": mode,
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _classify_folder(self, folder: Path) -> Literal["company", "group", "unknown"]:
        """Classifica uma pasta como empresa, grupo ou desconhecido."""
        if (folder / "balancetes").exists():
            return "company"

        # Se alguma subpasta é empresa → é grupo
        for sub in folder.iterdir():
            if sub.is_dir() and (sub / "balancetes").exists():
                return "group"

        return "unknown"

    def _build_company(self, folder: Path) -> Company:
        """Constrói um objeto Company a partir de uma pasta."""
        balancetes_dir = folder / "balancetes"
        output_dir = folder / "output"
        analise_dir = folder / "analise"
        output_dir.mkdir(exist_ok=True)
        analise_dir.mkdir(exist_ok=True)

        pdfs: list[PDFInfo] = []
        if balancetes_dir.exists():
            for pdf_path in sorted(balancetes_dir.glob("*.pdf")):
                pdfs.append(self._get_pdf_info(pdf_path, output_dir))

        csv_output = sorted(output_dir.glob("*.csv")) if output_dir.exists() else []
        csv_analise = sorted(analise_dir.glob("*.csv")) if analise_dir.exists() else []

        return Company(
            name=folder.name,
            path=folder,
            balancetes_dir=balancetes_dir,
            output_dir=output_dir,
            analise_dir=analise_dir,
            pdfs=pdfs,
            csv_output=csv_output,
            csv_analise=csv_analise,
        )

    def _get_pdf_info(self, pdf_path: Path, output_dir: Path) -> PDFInfo:
        """Obtém metadados de um PDF incluindo page count e status de conversão."""
        try:
            doc = fitz.open(str(pdf_path))
            page_count = doc.page_count
            doc.close()
        except Exception:
            page_count = 0

        converted, csv_files = self._check_converted(pdf_path, output_dir)

        return PDFInfo(
            path=pdf_path,
            name=pdf_path.name,
            page_count=page_count,
            converted=converted,
            csv_files=csv_files,
        )

    @staticmethod
    def _check_converted(pdf_path: Path, output_dir: Path) -> tuple[bool, list[Path]]:
        """Verifica se o PDF já foi convertido (CSVs existem no output)."""
        stem = pdf_path.stem
        variants = [
            output_dir / f"{stem}.csv",
            output_dir / f"{stem}_sintetico.csv",
            output_dir / f"{stem}_sinal.csv",
            output_dir / f"{stem}_sintetico_sinal.csv",
        ]
        existing = [p for p in variants if p.exists()]
        # Consideramos "convertido" se o _sintetico_sinal existe
        main_csv = output_dir / f"{stem}_sintetico_sinal.csv"
        return main_csv.exists(), existing
