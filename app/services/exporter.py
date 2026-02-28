"""Geração de arquivos Excel/CSV a partir dos dados parseados."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("planilhador")

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------

HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

AGRUPADORA_FONT = Font(name="Calibri", bold=True, size=11)
AGRUPADORA_FILL = PatternFill(start_color="DCE6F1", end_color="DCE6F1", fill_type="solid")

NORMAL_FONT = Font(name="Calibri", size=11)
RIGHT_ALIGN = Alignment(horizontal="right", vertical="center")
LEFT_ALIGN = Alignment(horizontal="left", vertical="center")
CENTER_ALIGN = Alignment(horizontal="center", vertical="center")

THIN_BORDER = Border(
    left=Side(style="thin", color="D0D0D0"),
    right=Side(style="thin", color="D0D0D0"),
    top=Side(style="thin", color="D0D0D0"),
    bottom=Side(style="thin", color="D0D0D0"),
)

BR_NUMBER_FORMAT = '#,##0.00'

TIPO_LABELS = {
    "balancete": "Balancete",
    "dre": "DRE",
    "balanco_patrimonial": "Balanço Patrimonial",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_tab_name(name: str) -> str:
    """Sanitiza nome de aba Excel (max 31 chars, sem caracteres proibidos)."""
    sanitized = re.sub(r'[/\\*?\[\]:]', '.', name)
    return sanitized[:31]


def _build_title(empresa: str, tipo: str, periodo: str) -> str:
    """Constrói título padronizado: Empresa - Tipo - Período."""
    label = TIPO_LABELS.get(tipo, tipo)
    parts = [p for p in [empresa, label, periodo] if p]
    return " - ".join(parts)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def export_excel_multi(
    demonstracoes: list[dict],
    empresa: str,
    output_path: Path,
) -> Path:
    """Gera Excel com 1 aba por demonstração.

    Args:
        demonstracoes: Lista de dicts com {tipo, periodo, dados}.
        empresa: Nome da empresa.
        output_path: Caminho para salvar o arquivo.

    Returns:
        Path do arquivo gerado.
    """
    wb = Workbook()
    default_ws = wb.active

    for i, demo in enumerate(demonstracoes):
        tipo = demo["tipo"]
        periodo = demo.get("periodo", "")
        dados = demo.get("dados", {})

        tab_name = _sanitize_tab_name(_build_title(empresa, tipo, periodo))

        if i == 0:
            default_ws.title = tab_name
            ws = default_ws
        else:
            ws = wb.create_sheet(title=tab_name)

        titulo = _build_title(empresa, tipo, periodo)

        if tipo == "balancete":
            _write_balancete(ws, dados, titulo)
        elif tipo == "dre":
            _write_dre(ws, dados, titulo)
        elif tipo == "balanco_patrimonial":
            _write_balanco(ws, dados, titulo)

    wb.save(str(output_path))
    logger.info("Excel gerado: %s (%d aba(s))", output_path, len(demonstracoes))
    return output_path


def export_excel(dados: dict, tipo: str, output_path: Path) -> Path:
    """Exporta dados de uma única demonstração para Excel."""
    empresa = dados.get("empresa", "")
    periodo = dados.get("periodo", dados.get("data_referencia", ""))
    demonstracoes = [{"tipo": tipo, "periodo": periodo, "dados": dados}]
    return export_excel_multi(demonstracoes, empresa, output_path)


def export_csv(dados: dict, tipo: str, output_path: Path) -> Path:
    """Exporta dados como CSV (delimitador ;, UTF-8 BOM)."""
    if tipo == "balancete":
        return _export_balancete_csv(dados, output_path)
    elif tipo == "dre":
        return _export_dre_csv(dados, output_path)
    elif tipo == "balanco_patrimonial":
        return _export_balanco_csv(dados, output_path)
    else:
        raise ValueError(f"Tipo não suportado para exportação: {tipo}")


# ---------------------------------------------------------------------------
# Balancete
# ---------------------------------------------------------------------------

BALANCETE_COLUMNS = [
    "Código", "Descrição", "Nível", "Natureza",
    "Saldo Anterior", "Débitos", "Créditos", "Saldo Atual",
]
BALANCETE_NUMERIC_COLS = {4, 5, 6, 7}
BALANCETE_COL_WIDTHS = {0: 14, 1: 42, 2: 8, 3: 10, 4: 18, 5: 18, 6: 18, 7: 18}


def _write_balancete(ws, dados: dict, titulo: str) -> None:
    """Escreve conteúdo de balancete em um worksheet com fórmulas SUM."""
    contas = dados.get("contas", [])

    ws.append([titulo])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(BALANCETE_COLUMNS))
    ws["A1"].font = Font(name="Calibri", bold=True, size=14)

    cnpj = dados.get("cnpj", "")
    periodo = dados.get("periodo", "")
    if cnpj:
        ws.append([f"CNPJ: {cnpj}  |  Período: {periodo}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(BALANCETE_COLUMNS))
        ws["A2"].font = Font(name="Calibri", size=11, color="666666")
    ws.append([])

    ws.append(BALANCETE_COLUMNS)
    header_row = ws.max_row
    for col_idx in range(len(BALANCETE_COLUMNS)):
        cell = ws.cell(row=header_row, column=col_idx + 1)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    # Mapeia classificação → row number para fórmulas de totalizadoras
    classif_to_row = {}

    for conta in contas:
        row = [
            conta.get("codigo_conta", ""),
            conta.get("descricao", ""),
            conta.get("nivel", ""),
            conta.get("natureza", ""),
            conta.get("saldo_anterior", 0) or 0,
            conta.get("debitos", 0) or 0,
            conta.get("creditos", 0) or 0,
            conta.get("saldo_atual", 0) or 0,
        ]
        ws.append(row)

        current_row = ws.max_row
        classif = conta.get("classificacao", "")
        classif_to_row[classif] = current_row
        is_totalizador = conta.get("is_totalizador", False)

        for col_idx in range(len(BALANCETE_COLUMNS)):
            cell = ws.cell(row=current_row, column=col_idx + 1)
            cell.border = THIN_BORDER
            cell.font = AGRUPADORA_FONT if is_totalizador else NORMAL_FONT

            if is_totalizador:
                cell.fill = AGRUPADORA_FILL

            if col_idx in BALANCETE_NUMERIC_COLS:
                cell.number_format = BR_NUMBER_FORMAT
                cell.alignment = RIGHT_ALIGN
            elif col_idx in (2, 3):
                cell.alignment = CENTER_ALIGN
            else:
                cell.alignment = LEFT_ALIGN

    # Segunda passada: adiciona fórmulas SUM nas totalizadoras
    for conta in contas:
        if not conta.get("is_totalizador"):
            continue
        classif = conta.get("classificacao", "")
        parent_row = classif_to_row.get(classif)
        if not parent_row:
            continue

        # Encontra filhas diretas (classificação = parent + ".XX")
        child_rows = []
        for other in contas:
            other_classif = other.get("classificacao", "")
            if (other_classif != classif
                    and other_classif.startswith(classif + ".")
                    and other_classif[len(classif) + 1:].count(".") == 0):
                child_row = classif_to_row.get(other_classif)
                if child_row:
                    child_rows.append(child_row)

        if child_rows:
            # Colunas numéricas: E (Saldo Ant), F (Déb), G (Créd), H (Saldo Atual)
            for col_letter in ("E", "F", "G", "H"):
                refs = "+".join(f"{col_letter}{r}" for r in sorted(child_rows))
                ws.cell(row=parent_row, column=_col_idx(col_letter)).value = f"={refs}"

    for col_idx, width in BALANCETE_COL_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col_idx + 1)].width = width

    ws.freeze_panes = f"A{header_row + 1}"

    if contas:
        last_row = ws.max_row
        last_col = get_column_letter(len(BALANCETE_COLUMNS))
        ws.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"


def _col_idx(letter: str) -> int:
    """Converte letra de coluna em índice (A=1, B=2, etc.)."""
    return ord(letter.upper()) - ord("A") + 1


def _export_balancete_csv(dados: dict, output_path: Path) -> Path:
    contas = dados.get("contas", [])

    with open(str(output_path), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(BALANCETE_COLUMNS)
        for conta in contas:
            writer.writerow([
                conta.get("codigo_conta", ""),
                conta.get("descricao", ""),
                conta.get("nivel", ""),
                conta.get("natureza", ""),
                conta.get("saldo_anterior", 0),
                conta.get("debitos", 0),
                conta.get("creditos", 0),
                conta.get("saldo_atual", 0),
            ])

    logger.info("CSV balancete gerado: %s (%d contas)", output_path, len(contas))
    return output_path


# ---------------------------------------------------------------------------
# DRE
# ---------------------------------------------------------------------------

DRE_COLUMNS = ["Descrição", "Valor", "% da Receita"]
DRE_COL_WIDTHS = {0: 50, 1: 20, 2: 14}


def _write_dre(ws, dados: dict, titulo: str) -> None:
    linhas = dados.get("linhas", [])

    ws.append([titulo])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(DRE_COLUMNS))
    ws["A1"].font = Font(name="Calibri", bold=True, size=14)

    periodo = dados.get("periodo", "")
    if periodo:
        ws.append([f"Período: {periodo}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(DRE_COLUMNS))
        ws["A2"].font = Font(name="Calibri", size=11, color="666666")
    ws.append([])

    # Identifica linha da receita bruta para fórmula AV%
    receita_bruta_row = None

    ws.append(DRE_COLUMNS)
    header_row = ws.max_row  # Row onde os headers foram escritos
    for col_idx in range(len(DRE_COLUMNS)):
        cell = ws.cell(row=header_row, column=col_idx + 1)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    # Primeira passada: encontra a receita bruta
    for idx, linha in enumerate(linhas):
        desc = (linha.get("descricao") or "").upper()
        if "RECEITA" in desc and ("BRUTA" in desc or "OPERACIONAL BRUTA" in desc):
            receita_bruta_row = header_row + 1 + idx
            break
    if receita_bruta_row is None and linhas:
        receita_bruta_row = header_row + 1  # primeira linha de dados

    # Rastreia linhas para fórmulas de subtotal
    last_subtotal_data_row = None  # última linha de subtotal escrita
    non_subtotal_rows = []  # linhas de detalhe desde último subtotal

    for linha in linhas:
        valor = linha.get("valor", 0) or 0
        nivel = linha.get("nivel", 1)
        is_subtotal = linha.get("is_subtotal", False)

        indent = "  " * (nivel - 1)
        descricao = f"{indent}{linha.get('descricao', '')}"

        ws.append([descricao, valor, 0])  # placeholder para AV%
        current_row = ws.max_row

        # Fórmula AV% (Análise Vertical): =B{row}/B${receita_bruta_row}
        pct_cell = ws.cell(row=current_row, column=3)
        if receita_bruta_row:
            pct_cell.value = f"=IF(B${receita_bruta_row}=0,0,B{current_row}/B${receita_bruta_row})"

        # Fórmula de subtotal: =SUM das linhas de detalhe acima
        if is_subtotal and non_subtotal_rows:
            sum_refs = ",".join(f"B{r}" for r in non_subtotal_rows)
            if last_subtotal_data_row:
                # Soma detalhe + subtotal anterior
                sum_refs = f"B{last_subtotal_data_row}," + ",".join(f"B{r}" for r in non_subtotal_rows)
            ws.cell(row=current_row, column=2).value = f"=SUM({sum_refs})"
            last_subtotal_data_row = current_row
            non_subtotal_rows = []
        elif is_subtotal:
            last_subtotal_data_row = current_row
            non_subtotal_rows = []
        else:
            non_subtotal_rows.append(current_row)

        # Estilo
        for col_idx in range(len(DRE_COLUMNS)):
            cell = ws.cell(row=current_row, column=col_idx + 1)
            cell.border = THIN_BORDER

            if is_subtotal or nivel <= 1:
                cell.font = AGRUPADORA_FONT
                cell.fill = AGRUPADORA_FILL
            else:
                cell.font = NORMAL_FONT

            if col_idx == 0:
                cell.alignment = LEFT_ALIGN
            elif col_idx == 1:
                cell.number_format = BR_NUMBER_FORMAT
                cell.alignment = RIGHT_ALIGN
            elif col_idx == 2:
                cell.number_format = '0.0%'
                cell.alignment = RIGHT_ALIGN

    for col_idx, width in DRE_COL_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col_idx + 1)].width = width

    ws.freeze_panes = f"A{header_row + 1}"


def _export_dre_csv(dados: dict, output_path: Path) -> Path:
    linhas = dados.get("linhas", [])

    with open(str(output_path), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Descrição", "Valor", "Nível", "Subtotal"])
        for linha in linhas:
            writer.writerow([
                linha.get("descricao", ""),
                linha.get("valor", 0),
                linha.get("nivel", 1),
                "Sim" if linha.get("is_subtotal") else "Não",
            ])

    logger.info("CSV DRE gerado: %s (%d linhas)", output_path, len(linhas))
    return output_path


# ---------------------------------------------------------------------------
# Balanço Patrimonial
# ---------------------------------------------------------------------------

BALANCO_COLUMNS = ["Descrição", "Valor"]
BALANCO_COL_WIDTHS = {0: 50, 1: 20}


def _write_balanco(ws, dados: dict, titulo: str) -> None:
    ws.append([titulo])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=2)
    ws["A1"].font = Font(name="Calibri", bold=True, size=14)

    data_ref = dados.get("data_referencia", "")
    if data_ref:
        ws.append([f"Data de Referência: {data_ref}"])
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
        ws["A2"].font = Font(name="Calibri", size=11, color="666666")
    ws.append([])

    # Rastreia rows para fórmulas SUM
    section_total_rows = {}  # "ativo", "passivo", "pl" → row number
    sub_total_rows = {}  # ("ativo","circulante") → row number

    def _write_section(title: str, section: dict, section_key: str):
        # Header da seção com placeholder para fórmula SUM
        ws.append([title, 0])
        section_row = ws.max_row
        section_total_rows[section_key] = section_row
        ws.cell(row=section_row, column=1).font = Font(
            name="Calibri", bold=True, size=13, color="2F5496",
        )
        ws.cell(row=section_row, column=2).font = Font(
            name="Calibri", bold=True, size=13, color="2F5496",
        )
        ws.cell(row=section_row, column=2).number_format = BR_NUMBER_FORMAT
        ws.cell(row=section_row, column=2).alignment = RIGHT_ALIGN
        ws.cell(row=section_row, column=1).border = THIN_BORDER
        ws.cell(row=section_row, column=2).border = THIN_BORDER

        sub_rows_for_section = []

        for sub_key in ("circulante", "nao_circulante"):
            sub = section.get(sub_key, {})
            if not sub:
                continue

            sub_title = "Circulante" if sub_key == "circulante" else "Não Circulante"
            ws.append([f"  {sub_title}", 0])  # placeholder
            sub_header_row = ws.max_row
            sub_total_rows[(section_key, sub_key)] = sub_header_row
            sub_rows_for_section.append(sub_header_row)
            ws.cell(row=sub_header_row, column=1).font = AGRUPADORA_FONT
            ws.cell(row=sub_header_row, column=1).fill = AGRUPADORA_FILL
            ws.cell(row=sub_header_row, column=1).border = THIN_BORDER
            ws.cell(row=sub_header_row, column=2).font = AGRUPADORA_FONT
            ws.cell(row=sub_header_row, column=2).fill = AGRUPADORA_FILL
            ws.cell(row=sub_header_row, column=2).number_format = BR_NUMBER_FORMAT
            ws.cell(row=sub_header_row, column=2).alignment = RIGHT_ALIGN
            ws.cell(row=sub_header_row, column=2).border = THIN_BORDER

            conta_rows = []
            for conta in sub.get("contas", []):
                nivel = conta.get("nivel", 3)
                is_sub = conta.get("is_subtotal", False)
                indent = "    " * max(1, nivel - 2)
                ws.append([f"{indent}{conta.get('descricao', '')}", conta.get("valor", 0)])
                current_row = ws.max_row
                conta_rows.append(current_row)
                for c in range(1, 3):
                    cell = ws.cell(row=current_row, column=c)
                    cell.border = THIN_BORDER
                    if is_sub:
                        cell.font = AGRUPADORA_FONT
                        cell.fill = AGRUPADORA_FILL
                    if c == 2:
                        cell.number_format = BR_NUMBER_FORMAT
                        cell.alignment = RIGHT_ALIGN

            # Fórmula SUM no header da subsecção
            if conta_rows:
                first_r, last_r = conta_rows[0], conta_rows[-1]
                ws.cell(row=sub_header_row, column=2).value = f"=SUM(B{first_r}:B{last_r})"

        # Fórmula SUM no header da seção (soma das subsecções)
        if sub_rows_for_section:
            refs = "+".join(f"B{r}" for r in sub_rows_for_section)
            ws.cell(row=section_row, column=2).value = f"={refs}"

        ws.append([])

    _write_section("ATIVO", dados.get("ativo", {}), "ativo")
    _write_section("PASSIVO", dados.get("passivo", {}), "passivo")

    # Patrimônio Líquido
    pl = dados.get("patrimonio_liquido", {})
    ws.append(["PATRIMÔNIO LÍQUIDO", 0])  # placeholder
    pl_row = ws.max_row
    section_total_rows["pl"] = pl_row
    ws.cell(row=pl_row, column=1).font = Font(
        name="Calibri", bold=True, size=13, color="2F5496",
    )
    ws.cell(row=pl_row, column=2).font = Font(
        name="Calibri", bold=True, size=13, color="2F5496",
    )
    ws.cell(row=pl_row, column=2).number_format = BR_NUMBER_FORMAT
    ws.cell(row=pl_row, column=2).alignment = RIGHT_ALIGN
    ws.cell(row=pl_row, column=1).border = THIN_BORDER
    ws.cell(row=pl_row, column=2).border = THIN_BORDER

    pl_conta_rows = []
    for conta in pl.get("contas", []):
        is_sub = conta.get("is_subtotal", False)
        ws.append([f"  {conta.get('descricao', '')}", conta.get("valor", 0)])
        current_row = ws.max_row
        pl_conta_rows.append(current_row)
        for c in range(1, 3):
            cell = ws.cell(row=current_row, column=c)
            cell.border = THIN_BORDER
            if is_sub:
                cell.font = AGRUPADORA_FONT
                cell.fill = AGRUPADORA_FILL
            if c == 2:
                cell.number_format = BR_NUMBER_FORMAT
                cell.alignment = RIGHT_ALIGN

    # Fórmula SUM para PL
    if pl_conta_rows:
        first_r, last_r = pl_conta_rows[0], pl_conta_rows[-1]
        ws.cell(row=pl_row, column=2).value = f"=SUM(B{first_r}:B{last_r})"

    ws.append([])

    # Validação com fórmulas
    ativo_row = section_total_rows.get("ativo")
    passivo_row = section_total_rows.get("passivo")

    ws.append(["VALIDAÇÃO: Ativo = Passivo + PL"])
    ws.cell(row=ws.max_row, column=1).font = Font(name="Calibri", bold=True, size=11)

    if ativo_row and passivo_row:
        ws.append([
            "Diferença (Ativo - Passivo - PL):",
            None,
        ])
        diff_row = ws.max_row
        ws.cell(row=diff_row, column=2).value = f"=B{ativo_row}-B{passivo_row}-B{pl_row}"
        ws.cell(row=diff_row, column=2).number_format = BR_NUMBER_FORMAT
        ws.cell(row=diff_row, column=2).alignment = RIGHT_ALIGN

        ws.append(["Status:"])
        status_row = ws.max_row
        ws.cell(row=status_row, column=2).value = (
            f'=IF(ABS(B{diff_row})<0.01,"OK","DIVERGENTE")'
        )
        status_cell = ws.cell(row=status_row, column=2)
        status_cell.font = Font(name="Calibri", bold=True, size=11)
    else:
        total_ativo = dados.get("ativo", {}).get("total", 0) or 0
        total_passivo = dados.get("passivo", {}).get("total", 0) or 0
        total_pl = pl.get("total", 0) or 0
        passivo_pl = total_passivo + total_pl
        valido = abs(total_ativo - passivo_pl) < max(abs(total_ativo), 0.01) * 0.01
        ws.append([
            f"Ativo Total: {total_ativo:,.2f}  |  Passivo + PL: {passivo_pl:,.2f}  |  "
            f"{'OK' if valido else 'DIVERGENTE'}"
        ])
        status_cell = ws.cell(row=ws.max_row, column=1)
        status_cell.font = Font(
            name="Calibri", bold=True, size=11,
            color="006100" if valido else "9C0006",
        )

    for col_idx, width in BALANCO_COL_WIDTHS.items():
        ws.column_dimensions[get_column_letter(col_idx + 1)].width = width


def _export_balanco_csv(dados: dict, output_path: Path) -> Path:
    with open(str(output_path), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Seção", "Descrição", "Valor"])

        for secao, dados_secao in [
            ("Ativo", dados.get("ativo", {})),
            ("Passivo", dados.get("passivo", {})),
        ]:
            for sub_key in ("circulante", "nao_circulante"):
                sub = dados_secao.get(sub_key, {})
                for conta in sub.get("contas", []):
                    writer.writerow([secao, conta.get("descricao", ""), conta.get("valor", 0)])

        pl = dados.get("patrimonio_liquido", {})
        for conta in pl.get("contas", []):
            writer.writerow(["PL", conta.get("descricao", ""), conta.get("valor", 0)])

    logger.info("CSV balanço gerado: %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Exportação bruta (sem formatação IA)
# ---------------------------------------------------------------------------

def _parse_pipe_table(raw_text: str) -> list[list[str]]:
    """Parseia texto pipe-separated da extração em lista de linhas/colunas."""
    rows = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Pula linhas separadoras (---|---|---)
        if re.match(r'^[\s|:-]+$', line):
            continue
        if '|' in line:
            cells = [c.strip() for c in line.split('|')]
            # Remove células vazias das bordas (|col1|col2| → ['', 'col1', 'col2', ''])
            if cells and cells[0] == '':
                cells = cells[1:]
            if cells and cells[-1] == '':
                cells = cells[:-1]
            rows.append(cells)
        else:
            rows.append([line])
    return rows


def export_raw_csv(raw_text: str, output_path: Path) -> Path:
    """Exporta texto bruto pipe-separated como CSV."""
    rows = _parse_pipe_table(raw_text)

    with open(str(output_path), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        for row in rows:
            writer.writerow(row)

    logger.info("CSV bruto gerado: %s (%d linhas)", output_path, len(rows))
    return output_path


def export_raw_excel(
    demonstracoes: list[dict],
    empresa: str,
    output_path: Path,
) -> Path:
    """Exporta textos brutos pipe-separated como Excel multi-aba."""
    wb = Workbook()
    default_ws = wb.active

    for i, demo in enumerate(demonstracoes):
        tipo = demo["tipo"]
        periodo = demo.get("periodo", "")
        raw_text = demo.get("raw_text", "")

        tab_name = _sanitize_tab_name(_build_title(empresa, tipo, periodo))

        if i == 0:
            default_ws.title = tab_name
            ws = default_ws
        else:
            ws = wb.create_sheet(title=tab_name)

        rows = _parse_pipe_table(raw_text)
        if not rows:
            continue

        # Header
        titulo = _build_title(empresa, tipo, periodo)
        ws.append([titulo])
        num_cols = max(len(r) for r in rows)
        if num_cols > 1:
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
        ws["A1"].font = Font(name="Calibri", bold=True, size=14)
        ws.append([])

        # Primeira linha da tabela como cabeçalho
        header_row_num = ws.max_row + 1
        ws.append(rows[0])
        for col_idx in range(len(rows[0])):
            cell = ws.cell(row=header_row_num, column=col_idx + 1)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER

        # Dados
        for row in rows[1:]:
            ws.append(row)
            current_row = ws.max_row
            for col_idx in range(len(row)):
                cell = ws.cell(row=current_row, column=col_idx + 1)
                cell.border = THIN_BORDER
                cell.font = NORMAL_FONT

        # Auto-width
        for col_idx in range(num_cols):
            max_len = 0
            col_letter = get_column_letter(col_idx + 1)
            for row in rows:
                if col_idx < len(row):
                    max_len = max(max_len, len(str(row[col_idx])))
            ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

        ws.freeze_panes = f"A{header_row_num + 1}"

    wb.save(str(output_path))
    logger.info("Excel bruto gerado: %s (%d aba(s))", output_path, len(demonstracoes))
    return output_path
