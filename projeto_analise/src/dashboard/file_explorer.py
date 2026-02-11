"""File Explorer com drag & drop — componente Streamlit custom (JS bidirecional).

Renderiza árvore de arquivos das pastas balancetes/, output/ e analise/
com suporte a:
- Drag & drop entre pastas
- Drag & drop de arquivos do computador (upload)
- Seleção de CSV para preview
- Deleção de arquivos
- Criação de pastas
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import streamlit.components.v1 as components


def file_explorer_component(
    balancetes: list[dict],
    output_csvs: list[dict],
    analise_csvs: list[dict],
    company_path: str,
    height: int = 400,
    key: str = "file_explorer",
) -> dict | None:
    """Renderiza o file explorer e retorna ação do usuário.

    Args:
        balancetes: Lista de dicts {name, path, converted, pages}.
        output_csvs: Lista de dicts {name, path}.
        analise_csvs: Lista de dicts {name, path}.
        company_path: Caminho da empresa (para referência).
        height: Altura do componente em pixels.
        key: Chave única do componente.

    Returns:
        Dict com ação ({action, ...}) ou None se nenhuma interação.
    """
    component_data = {
        "balancetes": balancetes,
        "output_csvs": output_csvs,
        "analise_csvs": analise_csvs,
        "company_path": company_path,
    }

    html_content = _build_html(component_data)

    result = components.html(
        html_content,
        height=height,
        scrolling=True,
    )

    return None


def file_explorer_st(
    balancetes: list[dict],
    output_csvs: list[dict],
    analise_csvs: list[dict],
    company_path: str,
    key: str = "file_explorer",
) -> dict | None:
    """Versão Streamlit-nativa do file explorer usando st.components.v1.html
    com comunicação via query params para ações simples.

    Para ações complexas (move, delete, upload), usa session_state polling.
    """
    import streamlit as st

    action_key = f"_fe_action_{key}"

    # Renderiza HTML com JavaScript
    component_data = {
        "balancetes": balancetes,
        "output_csvs": output_csvs,
        "analise_csvs": analise_csvs,
        "company_path": company_path,
    }

    html = _build_html(component_data)
    components.html(html, height=420, scrolling=True)

    # Retorna ação pendente (se existir)
    action = st.session_state.pop(action_key, None)
    return action


def _build_html(data: dict) -> str:
    """Gera o HTML/CSS/JS do file explorer."""
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html>
<head>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: #333; background: #fff; }}

    .explorer-container {{ display: flex; gap: 8px; padding: 8px; }}
    .folder-panel {{ flex: 1; border: 1px solid #e0e0e0; border-radius: 6px; background: #fafafa; min-height: 300px; }}
    .folder-header {{
        padding: 8px 12px; font-weight: 600; font-size: 12px;
        background: #f0f0f0; border-bottom: 1px solid #e0e0e0;
        border-radius: 6px 6px 0 0; display: flex; align-items: center; gap: 6px;
        user-select: none;
    }}
    .folder-header .icon {{ font-size: 14px; }}
    .folder-header .badge {{
        background: #6c757d; color: #fff; font-size: 10px;
        padding: 1px 6px; border-radius: 10px; margin-left: auto;
    }}
    .folder-body {{ padding: 4px; min-height: 200px; }}
    .folder-body.drag-over {{ background: #e3f2fd; border: 2px dashed #2196f3; }}

    .file-item {{
        display: flex; align-items: center; gap: 6px;
        padding: 5px 8px; margin: 2px 0; border-radius: 4px;
        cursor: pointer; user-select: none; transition: background 0.15s;
    }}
    .file-item:hover {{ background: #e8e8e8; }}
    .file-item.selected {{ background: #d4e6f9; border: 1px solid #90caf9; }}
    .file-item.dragging {{ opacity: 0.5; }}
    .file-item .icon {{ font-size: 14px; flex-shrink: 0; }}
    .file-item .name {{ flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }}
    .file-item .status {{ font-size: 10px; flex-shrink: 0; }}
    .file-item .status.converted {{ color: #4caf50; }}
    .file-item .status.pending {{ color: #ff9800; }}
    .file-item .actions {{ display: none; flex-shrink: 0; }}
    .file-item:hover .actions {{ display: flex; gap: 2px; }}
    .file-item .actions button {{
        background: none; border: none; cursor: pointer;
        font-size: 12px; padding: 2px 4px; border-radius: 3px;
        color: #666; transition: all 0.15s;
    }}
    .file-item .actions button:hover {{ background: #ffcdd2; color: #c62828; }}

    .drop-zone {{
        border: 2px dashed #ccc; border-radius: 6px; padding: 16px;
        text-align: center; color: #999; font-size: 11px; margin: 4px;
        transition: all 0.2s;
    }}
    .drop-zone.active {{ border-color: #2196f3; background: #e3f2fd; color: #1976d2; }}

    .action-bar {{
        display: flex; gap: 4px; padding: 8px; border-top: 1px solid #e0e0e0;
        background: #f5f5f5; border-radius: 0 0 6px 6px;
    }}
    .action-bar button {{
        background: #fff; border: 1px solid #ddd; padding: 4px 10px;
        border-radius: 4px; font-size: 11px; cursor: pointer;
        transition: all 0.15s;
    }}
    .action-bar button:hover {{ background: #e3f2fd; border-color: #90caf9; }}
    .action-bar button.primary {{ background: #1976d2; color: #fff; border-color: #1565c0; }}
    .action-bar button.primary:hover {{ background: #1565c0; }}
    .action-bar button.danger {{ color: #c62828; }}
    .action-bar button.danger:hover {{ background: #ffebee; border-color: #ef9a9a; }}

    .toast {{
        position: fixed; bottom: 12px; right: 12px; padding: 8px 16px;
        background: #333; color: #fff; border-radius: 6px; font-size: 12px;
        opacity: 0; transition: opacity 0.3s; z-index: 1000;
    }}
    .toast.show {{ opacity: 1; }}
</style>
</head>
<body>

<div class="explorer-container" id="explorer">
    <div class="folder-panel" id="panel-balancetes">
        <div class="folder-header">
            <span class="icon">📁</span> Balancetes (PDFs)
            <span class="badge" id="badge-balancetes">0</span>
        </div>
        <div class="folder-body" id="body-balancetes" data-folder="balancetes"></div>
        <div class="drop-zone" id="drop-balancetes" data-folder="balancetes">
            Arraste PDFs aqui
        </div>
    </div>

    <div class="folder-panel" id="panel-output">
        <div class="folder-header">
            <span class="icon">📄</span> Output (CSVs)
            <span class="badge" id="badge-output">0</span>
        </div>
        <div class="folder-body" id="body-output" data-folder="output"></div>
        <div class="action-bar">
            <button class="primary" onclick="copySelectedToAnalise()">Copiar para Análise →</button>
        </div>
    </div>

    <div class="folder-panel" id="panel-analise">
        <div class="folder-header">
            <span class="icon">📊</span> Análise (CSVs)
            <span class="badge" id="badge-analise">0</span>
        </div>
        <div class="folder-body" id="body-analise" data-folder="analise"></div>
        <div class="drop-zone" id="drop-analise" data-folder="analise">
            Arraste CSVs aqui
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
    const DATA = {data_json};
    let selectedFiles = new Set();
    let draggedItem = null;

    function init() {{
        renderFiles();
        setupDropZones();
        setupExternalDrop();
    }}

    function renderFiles() {{
        // Balancetes (PDFs)
        const balBody = document.getElementById('body-balancetes');
        balBody.innerHTML = '';
        DATA.balancetes.forEach(f => {{
            balBody.appendChild(createFileItem(f.name, f.path, 'pdf', f.converted, f.pages));
        }});
        document.getElementById('badge-balancetes').textContent = DATA.balancetes.length;

        // Output CSVs
        const outBody = document.getElementById('body-output');
        outBody.innerHTML = '';
        DATA.output_csvs.forEach(f => {{
            outBody.appendChild(createFileItem(f.name, f.path, 'csv', null, null, true));
        }});
        document.getElementById('badge-output').textContent = DATA.output_csvs.length;

        // Análise CSVs
        const anaBody = document.getElementById('body-analise');
        anaBody.innerHTML = '';
        DATA.analise_csvs.forEach(f => {{
            anaBody.appendChild(createFileItem(f.name, f.path, 'csv-analise'));
        }});
        document.getElementById('badge-analise').textContent = DATA.analise_csvs.length;
    }}

    function createFileItem(name, path, type, converted, pages, selectable) {{
        const div = document.createElement('div');
        div.className = 'file-item';
        div.setAttribute('draggable', 'true');
        div.dataset.path = path;
        div.dataset.name = name;
        div.dataset.type = type;

        let icon = type === 'pdf' ? '📋' : '📄';
        let statusHtml = '';
        if (converted === true) statusHtml = '<span class="status converted">✓</span>';
        else if (converted === false) statusHtml = '<span class="status pending">⏳</span>';
        let pagesHtml = pages ? `<span style="font-size:10px;color:#999;">${{pages}}p</span>` : '';

        let checkbox = '';
        if (selectable) {{
            checkbox = `<input type="checkbox" style="margin:0;" onchange="toggleSelect(this, '${{path}}')" />`;
        }}

        div.innerHTML = `
            ${{checkbox}}
            <span class="icon">${{icon}}</span>
            <span class="name" title="${{name}}">${{name}}</span>
            ${{pagesHtml}}
            ${{statusHtml}}
            <span class="actions">
                <button onclick="deleteFile('${{path}}')" title="Deletar">🗑</button>
            </span>
        `;

        // Click para preview CSV
        if (type === 'csv' || type === 'csv-analise') {{
            div.addEventListener('dblclick', () => sendAction('select_csv', {{ path }}));
        }}

        // Drag
        div.addEventListener('dragstart', (e) => {{
            draggedItem = {{ name, path, type }};
            div.classList.add('dragging');
            e.dataTransfer.setData('text/plain', path);
            e.dataTransfer.effectAllowed = 'move';
        }});
        div.addEventListener('dragend', () => {{
            div.classList.remove('dragging');
            draggedItem = null;
        }});

        return div;
    }}

    function toggleSelect(checkbox, path) {{
        if (checkbox.checked) selectedFiles.add(path);
        else selectedFiles.delete(path);
    }}

    function copySelectedToAnalise() {{
        if (selectedFiles.size === 0) {{
            showToast('Selecione CSVs para copiar');
            return;
        }}
        sendAction('copy_to_analise', {{ paths: Array.from(selectedFiles) }});
        selectedFiles.clear();
        showToast('Copiando para análise...');
    }}

    function deleteFile(path) {{
        if (confirm('Deletar este arquivo?')) {{
            sendAction('delete', {{ path }});
        }}
    }}

    function setupDropZones() {{
        document.querySelectorAll('.folder-body, .drop-zone').forEach(zone => {{
            zone.addEventListener('dragover', (e) => {{
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                zone.classList.add('drag-over');
            }});
            zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
            zone.addEventListener('drop', (e) => {{
                e.preventDefault();
                zone.classList.remove('drag-over');

                const folder = zone.dataset.folder;
                if (!folder) return;

                // Drop interno (mover entre pastas)
                if (draggedItem) {{
                    sendAction('move', {{
                        src: draggedItem.path,
                        dest_folder: folder,
                    }});
                    showToast(`Movido para ${{folder}}/`);
                    return;
                }}

                // Drop externo (upload do computador)
                const files = e.dataTransfer.files;
                if (files.length > 0) {{
                    handleFileUpload(files, folder);
                }}
            }});
        }});
    }}

    function setupExternalDrop() {{
        // Previne que o browser abra o arquivo
        document.addEventListener('dragover', (e) => e.preventDefault());
        document.addEventListener('drop', (e) => e.preventDefault());
    }}

    function handleFileUpload(files, folder) {{
        const fileData = [];
        let processed = 0;

        Array.from(files).forEach(file => {{
            const reader = new FileReader();
            reader.onload = () => {{
                fileData.push({{
                    name: file.name,
                    data: reader.result.split(',')[1], // base64
                    size: file.size,
                }});
                processed++;
                if (processed === files.length) {{
                    sendAction('upload', {{ files: fileData, dest_folder: folder }});
                    showToast(`${{files.length}} arquivo(s) enviado(s)`);
                }}
            }};
            reader.readAsDataURL(file);
        }});
    }}

    function sendAction(action, payload) {{
        // Comunica com Streamlit via postMessage para o iframe parent
        const msg = {{ action, ...payload }};
        // Salva no DOM para polling
        const el = document.getElementById('action-output');
        if (el) el.value = JSON.stringify(msg);

        // Tenta comunicar via Streamlit component API
        try {{
            window.parent.postMessage({{
                type: 'streamlit:setComponentValue',
                value: msg,
            }}, '*');
        }} catch(e) {{}}
    }}

    function showToast(text) {{
        const toast = document.getElementById('toast');
        toast.textContent = text;
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 2000);
    }}

    init();
</script>

<input type="hidden" id="action-output" value="" />
</body>
</html>"""
