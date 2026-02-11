"""Preview hierárquico de balancetes CSV.

Renderiza dados de balancete em dois modos:
- Árvore hierárquica com contas agrupadoras em bold
- Tabela bruta com todos os dados
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import streamlit as st

from src.parsers.csv_parser import Balancete, ContaBalancete, load_balancete


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def render_balancete_preview(csv_path: Path, mode: str) -> None:
    """Renderiza preview de um balancete CSV."""
    try:
        balancete = _load_cached(str(csv_path), csv_path.stat().st_mtime)
    except (FileNotFoundError, ValueError) as e:
        st.error(f"Erro ao carregar: {e}")
        return

    if not balancete.contas:
        st.warning("Balancete vazio — nenhuma conta encontrada.")
        return

    if mode == "raw":
        _render_raw_table(balancete)
    else:
        _render_tree_view(balancete)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Carregando balancete...")
def _load_cached(csv_path_str: str, _mtime: float) -> Balancete:
    """Carrega balancete com cache (invalidado por mtime)."""
    return load_balancete(csv_path_str)


# ---------------------------------------------------------------------------
# Modo Raw
# ---------------------------------------------------------------------------

def _render_raw_table(balancete: Balancete) -> None:
    """Tabela HTML plana com todas as linhas do balancete."""
    html = (
        '<div style="overflow-x:auto;">'
        '<table style="width:100%; border-collapse:collapse; font-size:0.82em; font-family:monospace;">'
        '<thead>'
        '<tr style="background:#1a1a2e; color:#e0e0e0; border-bottom:2px solid #444;">'
    )
    headers = ["Cód", "Classif.", "Descrição", "Saldo Anterior", "Débito", "Crédito", "Saldo Atual"]
    aligns = ["left", "left", "left", "right", "right", "right", "right"]
    for h, a in zip(headers, aligns):
        html += f'<th style="text-align:{a}; padding:6px 8px; white-space:nowrap;">{h}</th>'
    html += '</tr></thead><tbody>'

    for i, conta in enumerate(balancete.contas):
        bg = "#f8f9fa" if i % 2 == 0 else "#ffffff"
        html += f'<tr style="background:{bg}; border-bottom:1px solid #eee;">'
        html += f'<td style="padding:3px 8px;">{conta.codigo}</td>'
        html += f'<td style="padding:3px 8px;">{conta.classificacao}</td>'
        html += f'<td style="padding:3px 8px;">{conta.descricao}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_val(conta.saldo_anterior, conta.natureza_anterior)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_abs(conta.debito)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_abs(conta.credito)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_val(conta.saldo_atual, conta.natureza_atual)}</td>'
        html += '</tr>'

    html += '</tbody></table></div>'
    st.markdown(html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Modo Árvore
# ---------------------------------------------------------------------------

def _render_tree_view(balancete: Balancete) -> None:
    """Árvore hierárquica com slider de profundidade e expanders por raiz."""
    children_map, agrupadoras, contas_idx, roots = _build_tree(balancete.contas)
    max_level = max(c.nivel for c in balancete.contas)

    c1, c2, c3 = st.columns([2, 2, 4])
    with c1:
        display_level = st.slider(
            "Profundidade",
            min_value=1,
            max_value=max_level,
            value=min(3, max_level),
            key="_conv_preview_depth",
        )
    with c2:
        st.caption(f"Mostrando até nível {display_level} de {max_level}")
    with c3:
        st.caption(f"{len(balancete.contas)} contas | {len(agrupadoras)} agrupadoras")

    for root_classif in roots:
        root_conta = contas_idx[root_classif]
        saldo_str = _fmt_val(root_conta.saldo_atual, root_conta.natureza_atual)
        with st.expander(
            f"{root_conta.classificacao} — {root_conta.descricao}  |  {saldo_str}",
            expanded=True,
        ):
            subtree = [
                c for c in balancete.contas
                if (c.classificacao == root_classif or c.classificacao.startswith(root_classif + "."))
                and c.nivel <= display_level
            ]
            if subtree:
                html = _build_tree_html(subtree, agrupadoras)
                st.markdown(html, unsafe_allow_html=True)
            else:
                st.caption("Nenhuma conta neste nível.")


# ---------------------------------------------------------------------------
# Construção da árvore
# ---------------------------------------------------------------------------

def _build_tree(
    contas: list[ContaBalancete],
) -> tuple[dict[str, list[str]], set[str], dict[str, ContaBalancete], list[str]]:
    """Constrói mapa pai→filhos e identifica agrupadoras.

    Returns:
        (children_map, agrupadoras_set, contas_by_classif, roots)
    """
    contas_idx = {c.classificacao: c for c in contas}
    children_map: dict[str, list[str]] = {}
    agrupadoras: set[str] = set()
    roots: list[str] = []

    for c in contas:
        classif = c.classificacao
        parts = classif.split(".")

        # Encontra pai existente subindo pela hierarquia
        parent_found = None
        for i in range(len(parts) - 1, 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in contas_idx:
                parent_found = candidate
                break

        if parent_found:
            children_map.setdefault(parent_found, []).append(classif)
            agrupadoras.add(parent_found)
        else:
            roots.append(classif)

    return children_map, agrupadoras, contas_idx, roots


def _build_tree_html(contas: list[ContaBalancete], agrupadoras: set[str]) -> str:
    """Gera tabela HTML hierárquica com indentação e bold para agrupadoras."""
    html = (
        '<table style="width:100%; border-collapse:collapse; font-size:0.82em;">'
        '<thead>'
        '<tr style="background:#f0f0f0; border-bottom:2px solid #ccc;">'
        '<th style="text-align:left; padding:4px 8px;">Classificação</th>'
        '<th style="text-align:left; padding:4px 8px;">Descrição</th>'
        '<th style="text-align:right; padding:4px 8px;">Saldo Anterior</th>'
        '<th style="text-align:right; padding:4px 8px;">Débito</th>'
        '<th style="text-align:right; padding:4px 8px;">Crédito</th>'
        '<th style="text-align:right; padding:4px 8px;">Saldo Atual</th>'
        '</tr></thead><tbody>'
    )

    for conta in contas:
        is_agrup = conta.classificacao in agrupadoras
        indent = (conta.nivel - 1) * 20
        weight = "font-weight:600;" if is_agrup else ""
        bg = "background:#f0f4f8;" if is_agrup else ""
        border = "border-bottom:1px solid #d0d5dd;" if is_agrup else "border-bottom:1px solid #eee;"

        html += f'<tr style="{bg}{border}">'
        html += f'<td style="padding:3px 8px; padding-left:{indent + 8}px;{weight}">{conta.classificacao}</td>'
        html += f'<td style="padding:3px 8px;{weight}">{conta.descricao}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;{weight}">{_fmt_val(conta.saldo_anterior, conta.natureza_anterior)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_abs(conta.debito)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;">{_fmt_abs(conta.credito)}</td>'
        html += f'<td style="text-align:right; padding:3px 8px;{weight}">{_fmt_val(conta.saldo_atual, conta.natureza_atual)}</td>'
        html += '</tr>'

    html += '</tbody></table>'
    return html


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def _fmt_val(val: Decimal, natureza: str) -> str:
    """Formata valor em formato brasileiro com sufixo D/C."""
    if val == 0:
        return "0,00"
    f = float(val)
    s = f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if natureza:
        s += natureza
    return s


def _fmt_abs(val: Decimal) -> str:
    """Formata valor absoluto em formato brasileiro."""
    f = float(val)
    if f == 0:
        return "0,00"
    return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
