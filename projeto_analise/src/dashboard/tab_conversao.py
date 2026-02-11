"""Aba Conversão — Gerenciamento de empresas/grupos e conversão PDF → CSV."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

from src.utils.empresa_manager import (
    Company,
    EmpresaManager,
    EmpresasStructure,
    Group,
    PDFInfo,
)

# Referência ao projeto irmão para importar o Orchestrator de balancetes
_BALANCETES_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "projeto_balancetes"


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def render_conversao(empresas_dir: Path) -> None:
    """Renderiza a aba Conversão completa."""
    manager = _get_manager(empresas_dir)
    structure = manager.scan_structure()

    # Layout: coluna esquerda (árvore) + coluna direita (file explorer + preview)
    col_tree, col_main = st.columns([1, 3])

    with col_tree:
        _render_company_tree(manager, structure)

    with col_main:
        selected: Company | None = st.session_state.get("_conv_selected_company")
        if selected:
            # Recarregar dados da empresa (pode ter mudado após upload/conversão)
            fresh_structure = manager.scan_structure()
            fresh_company = _find_company(fresh_structure, selected.path)
            if fresh_company:
                _render_right_panel(fresh_company, manager)
            else:
                st.warning("Empresa não encontrada. Selecione outra.")
        else:
            st.info("Selecione uma empresa na coluna esquerda para gerenciar seus balancetes.")


# ---------------------------------------------------------------------------
# Coluna esquerda: árvore de empresas/grupos
# ---------------------------------------------------------------------------

def _render_company_tree(manager: EmpresaManager, structure: EmpresasStructure) -> None:
    """Renderiza a árvore de navegação com criação/deleção inline."""
    st.subheader("Empresas")
    st.divider()

    if not structure.standalone_companies and not structure.groups:
        st.caption("Nenhuma empresa cadastrada.")

    # Empresas standalone
    for company in structure.standalone_companies:
        _company_row(company, manager)

    # Grupos
    for group in structure.groups:
        with st.expander(f"📂 {group.name}", expanded=True):
            for company in group.companies:
                _company_row(company, manager)
            # Adicionar empresa ao grupo
            _inline_add_company(manager, group)
            # Deletar grupo
            if st.button(
                "🗑 Remover grupo",
                key=f"_del_group_{group.name}",
                use_container_width=True,
            ):
                st.session_state[f"_confirm_del_group_{group.name}"] = True

            if st.session_state.get(f"_confirm_del_group_{group.name}"):
                st.warning(f"Deletar grupo **{group.name}** e todas suas empresas?")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Confirmar", key=f"_yes_del_group_{group.name}", type="primary"):
                        manager.delete_group(group.path)
                        st.session_state.pop(f"_confirm_del_group_{group.name}", None)
                        _clear_selection()
                        st.rerun()
                with c2:
                    if st.button("Cancelar", key=f"_no_del_group_{group.name}"):
                        st.session_state.pop(f"_confirm_del_group_{group.name}", None)
                        st.rerun()

    st.divider()

    # Criação inline
    _inline_create_group(manager)
    _inline_create_standalone_company(manager)


def _company_row(company: Company, manager: EmpresaManager) -> None:
    """Renderiza uma linha com botão de seleção + botão de deleção."""
    c1, c2 = st.columns([5, 1])

    with c1:
        pending = sum(1 for p in company.pdfs if not p.converted)
        total = len(company.pdfs)
        label = f"📁 {company.name}"
        if total > 0:
            label += f"  ({pending}/{total})"

        selected = st.session_state.get("_conv_selected_company")
        is_selected = selected and selected.path == company.path
        btn_type = "primary" if is_selected else "secondary"

        if st.button(label, key=f"_sel_{company.path}", use_container_width=True, type=btn_type):
            st.session_state["_conv_selected_company"] = company
            st.session_state.pop("_conv_selected_pdfs", None)
            st.session_state.pop("_conv_selected_csv", None)
            st.rerun()

    with c2:
        if st.button("🗑", key=f"_del_co_{company.path}", help="Deletar empresa"):
            st.session_state[f"_confirm_del_{company.name}"] = True

    if st.session_state.get(f"_confirm_del_{company.name}"):
        st.warning(f"Deletar **{company.name}** e todos seus arquivos?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Confirmar", key=f"_yes_del_{company.name}", type="primary"):
                manager.delete_company(company.path)
                st.session_state.pop(f"_confirm_del_{company.name}", None)
                _clear_selection()
                st.rerun()
        with c2:
            if st.button("Cancelar", key=f"_no_del_{company.name}"):
                st.session_state.pop(f"_confirm_del_{company.name}", None)
                st.rerun()


# ---------------------------------------------------------------------------
# Criação inline
# ---------------------------------------------------------------------------

def _inline_create_group(manager: EmpresaManager) -> None:
    """Formulário inline para criar novo grupo."""
    with st.expander("+ Novo Grupo", expanded=False):
        name = st.text_input("Nome do grupo", key="_conv_new_group_name", placeholder="Ex: Grupo ABC")
        if st.button(
            "Criar Grupo",
            disabled=not name,
            key="_btn_inline_create_group",
            use_container_width=True,
        ):
            manager.create_group(name)
            st.success(f"Grupo '{name}' criado!")
            st.rerun()


def _inline_create_standalone_company(manager: EmpresaManager) -> None:
    """Formulário inline para criar empresa standalone."""
    with st.expander("+ Nova Empresa", expanded=False):
        name = st.text_input("Nome da empresa", key="_conv_new_company_name", placeholder="Ex: VFR Logística")
        if st.button(
            "Criar Empresa",
            disabled=not name,
            key="_btn_inline_create_company",
            use_container_width=True,
        ):
            company = manager.create_company(name)
            st.success(f"Empresa '{name}' criada!")
            st.session_state["_conv_selected_company"] = company
            st.rerun()


def _inline_add_company(manager: EmpresaManager, group: Group) -> None:
    """Campo inline para adicionar empresa dentro de um grupo."""
    key_input = f"_conv_add_to_{group.name}_name"
    key_btn = f"_conv_add_to_{group.name}_btn"
    name = st.text_input(
        "Nova empresa",
        key=key_input,
        placeholder="Nome...",
        label_visibility="collapsed",
    )
    if name:
        if st.button("Adicionar", key=key_btn, use_container_width=True):
            company = manager.create_company(name, group.path)
            st.session_state["_conv_selected_company"] = company
            st.rerun()


# ---------------------------------------------------------------------------
# Coluna direita: File Explorer + Preview
# ---------------------------------------------------------------------------

def _render_right_panel(company: Company, manager: EmpresaManager) -> None:
    """Painel direito com file explorer, upload/conversão e preview."""
    st.subheader(f"📁 {company.name}")
    st.caption(str(company.path))

    # File Explorer (componente JS)
    _render_file_explorer(company, manager)

    st.divider()

    # Upload & Conversão
    _render_upload_and_conversion(company, manager)

    # Preview CSV
    selected_csv = st.session_state.get("_conv_selected_csv")
    if selected_csv and Path(selected_csv).exists():
        st.divider()
        _render_csv_preview(Path(selected_csv))


def _render_file_explorer(company: Company, manager: EmpresaManager) -> None:
    """Renderiza o file explorer com 3 painéis: balancetes, output, análise."""
    from src.dashboard.file_explorer import file_explorer_component

    balancetes_data = [
        {"name": p.name, "path": str(p.path), "converted": p.converted, "pages": p.page_count}
        for p in company.pdfs
    ]
    output_data = [{"name": p.name, "path": str(p)} for p in company.csv_output]
    analise_data = [{"name": p.name, "path": str(p)} for p in company.csv_analise]

    file_explorer_component(
        balancetes=balancetes_data,
        output_csvs=output_data,
        analise_csvs=analise_data,
        company_path=str(company.path),
        key=f"_explorer_{company.name}",
    )

    # Botões Streamlit-nativos para ações que o JS não pode fazer diretamente
    st.caption("Ações rápidas:")
    c1, c2, c3 = st.columns(3)

    with c1:
        # Copiar todos output → analise
        if company.csv_output:
            if st.button(
                "📊 Copiar tudo → Análise",
                key="_btn_copy_all_analise",
                use_container_width=True,
            ):
                manager.copy_to_analise(company.csv_output, company)
                st.success("CSVs copiados para análise!")
                st.rerun()

    with c2:
        # Copiar sintetico_sinal → analise
        sintetico_sinal = [p for p in company.csv_output if "sintetico_sinal" in p.name]
        if sintetico_sinal:
            if st.button(
                "📊 Copiar sintético → Análise",
                key="_btn_copy_sintetico_analise",
                use_container_width=True,
            ):
                manager.copy_to_analise(sintetico_sinal, company)
                st.success("CSVs sintéticos copiados!")
                st.rerun()

    with c3:
        # Limpar pasta análise
        if company.csv_analise:
            if st.button(
                "🗑 Limpar análise",
                key="_btn_clear_analise",
                use_container_width=True,
            ):
                for csv_path in company.csv_analise:
                    manager.delete_file(csv_path)
                st.success("Pasta análise limpa!")
                st.rerun()


# ---------------------------------------------------------------------------
# Upload & Conversão
# ---------------------------------------------------------------------------

def _render_upload_and_conversion(company: Company, manager: EmpresaManager) -> None:
    """Upload de PDFs e controles de conversão em expander."""
    has_preview = bool(st.session_state.get("_conv_selected_csv"))

    with st.expander("📤 Upload e Conversão", expanded=not has_preview):
        # Upload
        uploaded = st.file_uploader(
            "Adicionar PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"_upload_{company.name}",
        )
        if uploaded:
            for f in uploaded:
                dest = company.balancetes_dir / f.name
                dest.write_bytes(f.getvalue())
            st.success(f"{len(uploaded)} PDF(s) adicionado(s).")
            st.rerun()

        if not company.pdfs:
            st.info(f"Nenhum PDF encontrado em `{company.balancetes_dir}`")
            return

        st.divider()

        # Seleção de PDFs
        _render_pdf_selection(company)

        st.divider()

        # Controles de conversão
        _render_conversion_controls(company, manager)


def _render_pdf_selection(company: Company) -> None:
    """Checkboxes para seleção de PDFs."""
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Selecionar pendentes", key="_sel_all"):
            st.session_state["_conv_selected_pdfs"] = {
                str(p.path) for p in company.pdfs if not p.converted
            }
            st.rerun()
    with c2:
        if st.button("Limpar seleção", key="_sel_clear"):
            st.session_state["_conv_selected_pdfs"] = set()
            st.rerun()

    if "_conv_selected_pdfs" not in st.session_state:
        st.session_state["_conv_selected_pdfs"] = set()

    selected_set: set[str] = st.session_state["_conv_selected_pdfs"]

    for pdf in company.pdfs:
        cols = st.columns([0.5, 3, 1, 1.5])
        with cols[0]:
            checked = st.checkbox(
                "sel",
                value=str(pdf.path) in selected_set,
                key=f"_chk_{pdf.path}",
                label_visibility="collapsed",
            )
            if checked:
                selected_set.add(str(pdf.path))
            else:
                selected_set.discard(str(pdf.path))
        with cols[1]:
            st.write(pdf.name)
        with cols[2]:
            st.caption(f"{pdf.page_count} pág.")
        with cols[3]:
            if pdf.converted:
                st.success("Convertido")
            else:
                st.warning("Pendente")

    st.session_state["_conv_selected_pdfs"] = selected_set


def _render_conversion_controls(company: Company, manager: EmpresaManager) -> None:
    """Seletor de modo, estimativa e botão de converter."""
    selected_set: set[str] = st.session_state.get("_conv_selected_pdfs", set())
    selected_pdfs = [p for p in company.pdfs if str(p.path) in selected_set]

    if not selected_pdfs:
        st.info("Selecione PDFs para converter.")
        return

    st.subheader("Conversão")

    c1, c2 = st.columns(2)
    with c1:
        mode = st.radio(
            "Modo de processamento",
            options=["free", "paid"],
            format_func=lambda x: "Gratuito (2 workers)" if x == "free" else "Rápido (Tier 1)",
            horizontal=True,
            key="_conv_mode",
        )
    with c2:
        if mode == "paid":
            workers = st.slider("Workers", 3, 10, 5, key="_conv_workers")
        else:
            workers = 2
            st.metric("Workers", "2")

    estimate = manager.estimate_processing(selected_pdfs, mode)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("PDFs", len(selected_pdfs))
    with c2:
        st.metric("Páginas", estimate["total_pages"])
    with c3:
        secs = estimate["estimated_time_seconds"]
        if secs >= 60:
            st.metric("Tempo est.", f"{secs / 60:.1f} min")
        else:
            st.metric("Tempo est.", f"{secs:.0f}s")
    with c4:
        if mode == "free":
            st.metric("Custo", "Grátis")
        else:
            st.metric("Custo", f"~R$ {estimate['estimated_cost_brl']:.2f}")

    st.divider()

    if st.button(
        f"Converter {len(selected_pdfs)} PDF(s)",
        type="primary",
        use_container_width=True,
        key="_btn_convert",
    ):
        _run_conversion(selected_pdfs, company, mode, workers)


# ---------------------------------------------------------------------------
# Execução da conversão
# ---------------------------------------------------------------------------

def _run_conversion(
    pdfs: list[PDFInfo],
    company: Company,
    mode: str,
    workers: int,
) -> None:
    """Executa a conversão com barra de progresso."""
    if str(_BALANCETES_ROOT) not in sys.path:
        sys.path.insert(0, str(_BALANCETES_ROOT))

    from src.orchestrator import Orchestrator as BalancetesOrchestrator
    from src.orchestrator import OutputFormat

    progress_bar = st.progress(0, text="Iniciando conversão...")
    status_container = st.empty()

    def progress_callback(completed: int, total: int, filename: str) -> None:
        pct = completed / total
        progress_bar.progress(pct, text=f"Convertido {completed}/{total}")
        status_container.caption(f"Último: {filename}")

    orch = BalancetesOrchestrator()
    pdf_paths = [p.path for p in pdfs]

    try:
        results = orch.process_batch_parallel(
            file_paths=pdf_paths,
            max_workers=workers,
            output_format=OutputFormat.CSV,
            output_dir=str(company.output_dir),
            progress_callback=progress_callback,
        )

        progress_bar.progress(1.0, text="Conversão concluída!")

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_cost = sum(r.estimated_cost for r in results)

        if successful > 0:
            st.success(f"{successful} PDF(s) convertido(s) com sucesso!")
        if failed > 0:
            st.error(f"{failed} PDF(s) falharam.")
            with st.expander("Ver erros"):
                for r in results:
                    if not r.success:
                        st.write(f"**{Path(r.file_path).name}**: {r.error}")

        if total_cost > 0:
            st.caption(f"Custo total: ${total_cost:.4f}")

        st.session_state["_conv_selected_pdfs"] = set()

    except Exception as exc:
        progress_bar.empty()
        status_container.empty()
        st.error(f"Erro durante conversão: {exc}")


# ---------------------------------------------------------------------------
# Preview CSV
# ---------------------------------------------------------------------------

def _render_csv_preview(csv_path: Path) -> None:
    """Renderiza preview formatado de um CSV de balancete."""
    from src.dashboard.balancete_preview import render_balancete_preview

    st.subheader(f"Preview: {csv_path.name}")

    mode = st.radio(
        "Modo de visualização",
        options=["tree", "raw"],
        format_func=lambda x: "Árvore Hierárquica" if x == "tree" else "Tabela Bruta",
        horizontal=True,
        key="_conv_preview_mode",
    )

    render_balancete_preview(csv_path, mode)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_manager(empresas_dir: Path) -> EmpresaManager:
    """Retorna (ou cria) o EmpresaManager no session_state."""
    if "_conv_manager" not in st.session_state:
        st.session_state["_conv_manager"] = EmpresaManager(empresas_dir)
    return st.session_state["_conv_manager"]


def _find_company(structure: EmpresasStructure, path: Path) -> Company | None:
    """Busca uma empresa na estrutura pelo path."""
    for c in structure.standalone_companies:
        if c.path == path:
            return c
    for g in structure.groups:
        for c in g.companies:
            if c.path == path:
                return c
    return None


def _clear_selection() -> None:
    """Limpa a seleção de empresa e arquivos."""
    st.session_state.pop("_conv_selected_company", None)
    st.session_state.pop("_conv_selected_pdfs", None)
    st.session_state.pop("_conv_selected_csv", None)
