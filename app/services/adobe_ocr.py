"""OCR via Adobe PDF Services API (PT-BR) para PDFs escaneados."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import fitz

from adobe.pdfservices.operation.auth.service_principal_credentials import (
    ServicePrincipalCredentials,
)
from adobe.pdfservices.operation.io.stream_asset import StreamAsset
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.ocr_pdf_job import OCRPDFJob
from adobe.pdfservices.operation.pdfjobs.params.ocr_pdf.ocr_params import OCRParams
from adobe.pdfservices.operation.pdfjobs.params.ocr_pdf.ocr_supported_locale import (
    OCRSupportedLocale,
)
from adobe.pdfservices.operation.pdfjobs.params.ocr_pdf.ocr_supported_type import (
    OCRSupportedType,
)
from adobe.pdfservices.operation.pdfjobs.result.ocr_pdf_result import OCRPDFResult

logger = logging.getLogger("planilhador")


def has_native_text(pdf_path: str, threshold: int = 100) -> bool:
    """Verifica se o PDF tem texto nativo suficiente."""
    doc = fitz.open(pdf_path)
    total = sum(len(page.get_text().strip()) for page in doc)
    doc.close()
    return total >= threshold


def ocr_with_adobe(pdf_path: str, client_id: str, client_secret: str) -> str:
    """Aplica OCR Adobe (PT-BR) no PDF e sobrescreve o arquivo original.

    Args:
        pdf_path: Caminho do PDF no disco.
        client_id: Adobe Client ID.
        client_secret: Adobe Client Secret.

    Returns:
        O mesmo pdf_path (agora com camada de texto).
    """
    pdf_bytes = Path(pdf_path).read_bytes()

    credentials = ServicePrincipalCredentials(
        client_id=client_id,
        client_secret=client_secret,
    )
    pdf_services = PDFServices(credentials=credentials)

    input_asset = pdf_services.upload(
        input_stream=io.BytesIO(pdf_bytes),
        mime_type=PDFServicesMediaType.PDF,
    )

    ocr_params = OCRParams(
        ocr_locale=OCRSupportedLocale.PT_BR,
        ocr_type=OCRSupportedType.SEARCHABLE_IMAGE_EXACT,
    )

    ocr_job = OCRPDFJob(input_asset=input_asset, ocr_pdf_params=ocr_params)
    location = pdf_services.submit(ocr_job)
    response = pdf_services.get_job_result(location, OCRPDFResult)

    result_asset = response.get_result().get_asset()
    stream_asset: StreamAsset = pdf_services.get_content(result_asset)
    raw = stream_asset.get_input_stream()
    output_bytes = raw if isinstance(raw, bytes) else raw.read()

    # Sobrescreve o PDF original com a versão OCR
    Path(pdf_path).write_bytes(output_bytes)

    logger.info(
        "Adobe OCR concluído: %s (%d bytes → %d bytes)",
        pdf_path, len(pdf_bytes), len(output_bytes),
    )
    return pdf_path
