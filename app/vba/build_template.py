"""Reconstrói template.xlsm a partir dos .bas do Controladoria Plus.

Usa COM automation (win32com) para importar módulos VBA no Excel.
Só reconstrói se os .bas forem mais recentes que o template existente.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("planilhador")

# Caminho dos fontes VBA no projeto Controladoria Plus
VBA_SOURCES_DIR = Path.home() / "Dev" / "Controladoria Plus app"
BAS_FILES = ["ConsolidadorBalancetes.bas", "Loader.bas"]

TEMPLATE_PATH = Path(__file__).parent / "template.xlsm"


def _sources_newer_than_template() -> bool:
    """Retorna True se algum .bas é mais recente que o template."""
    if not TEMPLATE_PATH.exists():
        return True
    template_mtime = TEMPLATE_PATH.stat().st_mtime
    for name in BAS_FILES:
        bas = VBA_SOURCES_DIR / name
        if bas.exists() and bas.stat().st_mtime > template_mtime:
            return True
    return False


def _bas_files_exist() -> bool:
    """Verifica se os .bas existem no diretório fonte."""
    return all((VBA_SOURCES_DIR / name).exists() for name in BAS_FILES)


def ensure_vba_template() -> Path | None:
    """Reconstrói template.xlsm se necessário. Retorna o path ou None se falhar."""
    if not _bas_files_exist():
        logger.warning("Arquivos .bas não encontrados em %s", VBA_SOURCES_DIR)
        return TEMPLATE_PATH if TEMPLATE_PATH.exists() else None

    if not _sources_newer_than_template():
        return TEMPLATE_PATH

    logger.info("Reconstruindo template VBA a partir dos .bas...")

    try:
        import win32com.client

        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        try:
            wb = excel.Workbooks.Add()

            # Importar cada .bas
            for name in BAS_FILES:
                bas_path = str(VBA_SOURCES_DIR / name)
                wb.VBProject.VBComponents.Import(bas_path)

            # Salvar como .xlsm (xlOpenXMLWorkbookMacroEnabled = 52)
            wb.SaveAs(str(TEMPLATE_PATH.resolve()), FileFormat=52)
            wb.Close(SaveChanges=False)
            logger.info("Template VBA reconstruído: %s", TEMPLATE_PATH)
            return TEMPLATE_PATH

        finally:
            excel.DisplayAlerts = True
            excel.Quit()

    except ImportError:
        logger.warning("pywin32 não instalado — não é possível reconstruir template VBA")
        return TEMPLATE_PATH if TEMPLATE_PATH.exists() else None
    except Exception as e:
        logger.warning("Falha ao reconstruir template VBA: %s", e)
        return TEMPLATE_PATH if TEMPLATE_PATH.exists() else None
