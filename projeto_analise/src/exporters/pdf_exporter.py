"""Exportador de relatórios em PDF.

Converte Markdown → HTML → PDF usando markdown2 e xhtml2pdf.
"""

from __future__ import annotations

from pathlib import Path

from src.utils.config import OUTPUT_DIR, logger

CSS_STYLE = """\
<style>
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 11px;
    line-height: 1.5;
    color: #333;
    margin: 40px;
}
h1 {
    color: #1a365d;
    border-bottom: 2px solid #2b6cb0;
    padding-bottom: 8px;
    font-size: 22px;
}
h2 {
    color: #2b6cb0;
    border-bottom: 1px solid #bee3f8;
    padding-bottom: 4px;
    font-size: 16px;
    margin-top: 24px;
}
h3 {
    color: #2c5282;
    font-size: 13px;
    margin-top: 16px;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
}
th, td {
    border: 1px solid #e2e8f0;
    padding: 6px 10px;
    text-align: left;
    font-size: 10px;
}
th {
    background-color: #ebf8ff;
    font-weight: bold;
    color: #2b6cb0;
}
tr:nth-child(even) {
    background-color: #f7fafc;
}
hr {
    border: none;
    border-top: 1px solid #e2e8f0;
    margin: 20px 0;
}
strong {
    color: #2d3748;
}
</style>
"""


def markdown_to_pdf(
    markdown_content: str,
    output_path: str | Path,
) -> Path:
    """Converte Markdown para PDF.

    Args:
        markdown_content: Conteúdo em Markdown.
        output_path: Caminho do arquivo PDF de saída.

    Returns:
        Path do arquivo PDF gerado.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import markdown2
        from xhtml2pdf import pisa

        html = markdown2.markdown(
            markdown_content,
            extras=["tables", "fenced-code-blocks"],
        )

        full_html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            {CSS_STYLE}
        </head>
        <body>
            {html}
        </body>
        </html>
        """

        with open(path, "wb") as f:
            status = pisa.CreatePDF(full_html, dest=f)

        if status.err:
            logger.error("Erro ao gerar PDF: %d erros", status.err)
        else:
            logger.info("Relatório PDF salvo: %s", path)

        return path

    except ImportError as exc:
        logger.error(
            "Dependências de PDF não instaladas: %s. "
            "Execute: pip install markdown2 xhtml2pdf", exc,
        )
        raise


def save_as_pdf(
    markdown_content: str,
    filename: str,
    output_dir: str | Path | None = None,
) -> Path:
    """Salva relatório como PDF.

    Args:
        markdown_content: Conteúdo Markdown.
        filename: Nome base do arquivo.
        output_dir: Diretório de saída.

    Returns:
        Path do arquivo PDF.
    """
    out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    output_path = out_dir / f"{filename}_analise.pdf"
    return markdown_to_pdf(markdown_content, output_path)
