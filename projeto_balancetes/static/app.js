// State
let jobId = null;
let uploadedFiles = [];
let eventSource = null;
let selectedModel = 'gemini-2.0-flash';
let signDialogResolve = null;
let currentPreviewData = null;
let selectedReferenceName = null;  // referência selecionada para a conversão
let allReferences = [];            // cache da lista de referências

// Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileListSection = document.getElementById('file-list-section');
const fileList = document.getElementById('file-list');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const workersSlider = document.getElementById('workers-slider');
const workersValue = document.getElementById('workers-value');
const convertBtn = document.getElementById('convert-btn');

// ---------------------------------------------------------------------------
// Model toggle
// ---------------------------------------------------------------------------
const MODEL_LABELS = {
    'gemini-2.0-flash': 'Gemini 2 Flash',
    'gemini-2.5-flash': 'Gemini 2.5 Flash',
    'gemini-3-flash-preview': 'Gemini 3 Flash Preview',
};

async function setModel(modelId) {
    if (modelId === selectedModel) return;

    try {
        const resp = await fetch('/set-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId }),
        });

        if (!resp.ok) return;

        selectedModel = modelId;

        document.querySelectorAll('.model-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.model === modelId);
        });

        document.getElementById('subtitle').innerHTML =
            `PDF &rarr; CSV via ${MODEL_LABELS[modelId] || modelId}`;
    } catch (err) {
        console.error('Erro ao trocar modelo:', err);
    }
}

// ---------------------------------------------------------------------------
// Drop zone
// ---------------------------------------------------------------------------
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('active');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('active');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('active');
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (files.length > 0) uploadFiles(files);
});

fileInput.addEventListener('change', () => {
    const files = Array.from(fileInput.files);
    if (files.length > 0) uploadFiles(files);
    fileInput.value = '';
});

workersSlider.addEventListener('input', () => {
    workersValue.textContent = workersSlider.value;
});

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------
async function uploadFiles(files) {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));

    convertBtn.disabled = true;
    convertBtn.textContent = 'Enviando...';

    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });

        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro no upload');
            return;
        }

        const data = await resp.json();
        jobId = data.job_id;
        uploadedFiles = data.files;

        renderFileList(data);
        fileListSection.classList.remove('hidden');
        progressSection.classList.add('hidden');
        resultsSection.classList.add('hidden');

    } catch (err) {
        alert('Erro de conexao: ' + err.message);
    } finally {
        convertBtn.disabled = false;
        convertBtn.textContent = 'Converter';
    }
}

function renderFileList(data) {
    fileList.innerHTML = '';

    data.files.forEach(f => {
        const div = document.createElement('div');
        div.className = 'file-item';
        div.innerHTML = `
            <span class="file-icon">📋</span>
            <span class="file-name" title="${f.name}">${f.name}</span>
            <span class="file-meta">${f.pages}p &middot; ${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeFile('${f.name}')" title="Remover">&times;</button>
        `;
        fileList.appendChild(div);
    });

    updateInfo(data);

    // Carrega seletor de referências
    loadAllReferences();
}

function updateInfo(data) {
    document.getElementById('total-info').textContent =
        `${data.files.length} arquivo(s) · ${data.total_pages} pagina(s)`;
    document.getElementById('cost-estimate').textContent =
        `Custo estimado: ~R$ ${(data.estimated_cost * 5.5).toFixed(2)}`;
}

async function removeFile(filename) {
    if (!jobId) return;

    try {
        const resp = await fetch(`/job/${jobId}/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });

        if (resp.ok) {
            const data = await resp.json();
            uploadedFiles = uploadedFiles.filter(f => f.name !== filename);

            if (uploadedFiles.length === 0) {
                fileListSection.classList.add('hidden');
                jobId = null;
                return;
            }

            renderFileList({
                files: uploadedFiles,
                total_pages: data.total_pages,
                estimated_cost: data.estimated_cost,
            });
        }
    } catch (err) {
        console.error('Erro ao remover:', err);
    }
}

// ---------------------------------------------------------------------------
// Conversion
// ---------------------------------------------------------------------------
async function startConversion() {
    if (!jobId) return;

    const workers = parseInt(workersSlider.value);
    convertBtn.disabled = true;
    convertBtn.textContent = 'Convertendo...';

    try {
        let url = `/convert/${jobId}?workers=${workers}`;
        if (selectedReferenceName) {
            url += `&reference=${encodeURIComponent(selectedReferenceName)}`;
        }
        const resp = await fetch(url, {
            method: 'POST'
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro ao iniciar conversao');
            convertBtn.disabled = false;
            convertBtn.textContent = 'Converter';
            return;
        }

        progressSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        const bar = document.getElementById('progress-bar');
        bar.style.width = '0%';
        bar.classList.add('active');
        bar.classList.remove('done');

        listenProgress();

    } catch (err) {
        alert('Erro de conexao: ' + err.message);
        convertBtn.disabled = false;
        convertBtn.textContent = 'Converter';
    }
}

function listenProgress() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/progress/${jobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        renderProgress(data);

        if (data.status === 'done' || data.status === 'error') {
            eventSource.close();
            eventSource = null;
            onConversionDone(data);
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        setTimeout(() => onConversionDone(null), 1000);
    };
}

// ---------------------------------------------------------------------------
// Progress rendering
// ---------------------------------------------------------------------------

const STAGE_LABELS = {
    waiting:     'Na fila',
    analyzing:   'Analisando PDF',
    classifying: 'Classificando',
    extracting:  'Extraindo via Gemini',
    exporting:   'Gerando CSVs',
    done:        'Concluido',
    error:       'Erro',
};

const STAGE_ICONS = {
    analyzing:   '🔍',
    classifying: '🏷️',
    extracting:  '🤖',
    exporting:   '📦',
};

function renderProgress(data) {
    const pct = data.total > 0 ? Math.round((data.completed / data.total) * 100) : 0;

    const bar = document.getElementById('progress-bar');
    bar.style.width = pct + '%';

    if (data.status === 'done') {
        bar.classList.remove('active');
        bar.classList.add('done');
    }

    document.getElementById('progress-pct').textContent = pct + '%';
    document.getElementById('progress-text').textContent =
        `${data.completed} de ${data.total} concluido(s)`;

    if (data.elapsed !== undefined) {
        document.getElementById('elapsed-timer').textContent = formatTime(data.elapsed);
    }

    const details = document.getElementById('progress-details');
    details.innerHTML = '';

    data.progress.forEach(p => {
        const div = document.createElement('div');
        div.className = `progress-item ${p.status}`;

        let iconHtml = '';
        if (p.status === 'queued') {
            iconHtml = '<span class="pulse-dot"></span>';
        } else if (p.status === 'processing') {
            iconHtml = '<span class="spinner"></span>';
        } else if (p.status === 'done') {
            iconHtml = '<span class="check-icon">✓</span>';
        } else if (p.status === 'error') {
            iconHtml = '<span style="color:#e53935;">✗</span>';
        }

        let rightHtml = '';

        if (p.status === 'queued') {
            rightHtml = '<span class="stage-info">Na fila...</span>';
        } else if (p.status === 'processing') {
            const stageIcon = STAGE_ICONS[p.stage] || '';
            const stageLabel = STAGE_LABELS[p.stage] || p.stage;
            const detail = p.stage_detail || '';

            rightHtml = `
                <span class="stage-badge ${p.stage}">
                    ${stageIcon} ${stageLabel}
                </span>
                <span class="stage-info">${detail}</span>
            `;
        } else if (p.status === 'done') {
            const csvCount = p.output_files ? p.output_files.length : 0;
            rightHtml = `
                <span class="done-info">
                    <span>${p.time.toFixed(1)}s</span>
                    <span>·</span>
                    <span>$${p.cost.toFixed(4)}</span>
                    <span>·</span>
                    <span>${csvCount} CSV${csvCount !== 1 ? 's' : ''}</span>
                </span>
            `;
        } else if (p.status === 'error') {
            rightHtml = `<span class="error-info" title="${p.error || ''}">${p.error || 'Erro desconhecido'}</span>`;
        }

        div.innerHTML = `
            <span class="status-icon">${iconHtml}</span>
            <span class="filename">${p.filename}</span>
            <span class="pages-badge">${p.pages || 0}p</span>
            ${rightHtml}
        `;
        details.appendChild(div);
    });
}

// ---------------------------------------------------------------------------
// Conversion done
// ---------------------------------------------------------------------------
async function onConversionDone(lastData) {
    convertBtn.disabled = false;
    convertBtn.textContent = 'Converter';

    const bar = document.getElementById('progress-bar');
    bar.classList.remove('active');
    bar.classList.add('done');

    try {
        const resp = await fetch(`/results/${jobId}`);
        if (!resp.ok) return;

        const data = await resp.json();
        renderResults(data);
        resultsSection.classList.remove('hidden');

        if (data.preview_data && Object.keys(data.preview_data).length > 0) {
            currentPreviewData = data.preview_data;
            showXlsxSection(data.preview_data);
            showCorrectionSection(data.preview_data);
        }

    } catch (err) {
        console.error('Erro ao buscar resultados:', err);
    }
}

function renderResults(data) {
    const summary = document.getElementById('results-summary');
    const csvCount = data.files.filter(f => f.type === 'csv').length;
    const xlsxCount = data.files.filter(f => f.type === 'xlsx').length;
    const fileLabel = [];
    if (csvCount) fileLabel.push(`${csvCount} CSV${csvCount > 1 ? 's' : ''}`);
    if (xlsxCount) fileLabel.push(`${xlsxCount} XLSX`);

    summary.innerHTML = `
        <span class="result-stat">
            <span class="label">Tempo:</span>
            <span class="value">${data.total_time.toFixed(1)}s</span>
        </span>
        <span class="result-stat">
            <span class="label">Custo:</span>
            <span class="value">$${data.total_cost.toFixed(4)}</span>
        </span>
        <span class="result-stat">
            <span class="label">~</span>
            <span class="value">R$ ${(data.total_cost * 5.5).toFixed(2)}</span>
        </span>
        <span class="result-stat">
            <span class="label">Arquivos:</span>
            <span class="value">${fileLabel.join(' + ') || '0'}</span>
        </span>
    `;

    if (data.preview_data && Object.keys(data.preview_data).length > 0) {
        renderPreview(data.preview_data);
    }

    const list = document.getElementById('results-list');
    list.innerHTML = '';

    if (data.files.length === 0) {
        list.innerHTML = '<p style="color:#999; text-align:center; padding:12px;">Nenhum arquivo gerado.</p>';
        document.getElementById('download-all-btn').classList.add('hidden');
        return;
    }

    document.getElementById('download-all-btn').classList.remove('hidden');

    data.files.forEach(f => {
        const div = document.createElement('div');
        div.className = 'result-item';

        const isXlsx = f.type === 'xlsx';
        const icon = isXlsx ? '📊' : '📄';
        const badgeClass = isXlsx ? 'xlsx' : 'csv';
        const badgeLabel = isXlsx ? 'XLSX' : 'CSV';

        div.innerHTML = `
            <span class="file-icon">${icon}</span>
            <span class="file-name" title="${f.name}">${f.name}</span>
            <span class="file-type-badge ${badgeClass}">${badgeLabel}</span>
            <span class="file-meta">${formatSize(f.size)}</span>
            <button class="btn-download" onclick="downloadFile('${f.name}')">Baixar</button>
        `;
        list.appendChild(div);
    });
}

// ---------------------------------------------------------------------------
// Preview
// ---------------------------------------------------------------------------
function renderPreview(previewData) {
    const section = document.getElementById('preview-section');
    const tabsContainer = document.getElementById('preview-tabs');
    const container = document.getElementById('preview-container');
    const rowCountEl = document.getElementById('preview-row-count');

    section.classList.remove('hidden');

    const keys = Object.keys(previewData);

    tabsContainer.innerHTML = '';
    if (keys.length > 1) {
        keys.forEach((key, idx) => {
            const btn = document.createElement('button');
            btn.className = 'preview-tab' + (idx === 0 ? ' active' : '');
            btn.textContent = key;
            btn.onclick = () => {
                document.querySelectorAll('.preview-tab').forEach(t => t.classList.remove('active'));
                btn.classList.add('active');
                renderTable(previewData[key], container, rowCountEl);
            };
            tabsContainer.appendChild(btn);
        });
    }

    if (keys.length > 0) {
        renderTable(previewData[keys[0]], container, rowCountEl);
    }
}

function renderTable(rows, container, rowCountEl) {
    if (!rows || rows.length === 0) {
        container.innerHTML = '<p style="color:#999; text-align:center;">Sem dados.</p>';
        rowCountEl.textContent = '';
        return;
    }

    const header = rows[0];
    const dataRows = rows.slice(1);
    rowCountEl.textContent = `${dataRows.length} linhas`;

    let tipoIdx = -1;
    header.forEach((h, i) => {
        if (h.trim().toLowerCase() === 'tipo') tipoIdx = i;
    });

    const numericCols = new Set();
    header.forEach((h, i) => {
        const lower = h.trim().toLowerCase();
        if (lower.includes('saldo') || lower.includes('débito') || lower.includes('debito') ||
            lower.includes('crédito') || lower.includes('credito')) {
            numericCols.add(i);
        }
    });

    let html = '<table class="preview-table"><thead><tr>';
    header.forEach(h => {
        html += `<th>${escapeHtml(h)}</th>`;
    });
    html += '</tr></thead><tbody>';

    dataRows.forEach((row, rowIdx) => {
        const isAgrupadora = tipoIdx >= 0 && tipoIdx < row.length &&
                             row[tipoIdx].trim().toUpperCase() === 'A';
        const classes = [];
        if (isAgrupadora) classes.push('agrupadora');
        if (rowIdx % 2 === 1) classes.push('zebra');

        html += `<tr class="${classes.join(' ')}">`;
        row.forEach((cell, colIdx) => {
            const align = numericCols.has(colIdx) ? ' class="num-cell"' : '';
            html += `<td${align}>${escapeHtml(cell)}</td>`;
        });
        html += '</tr>';
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

// ---------------------------------------------------------------------------
// XLSX Profissional
// ---------------------------------------------------------------------------
function showXlsxSection(previewData) {
    document.getElementById('xlsx-section').classList.remove('hidden');

    const keys = Object.keys(previewData);
    if (keys.length > 0) {
        detectSigns(keys[0]);
    }
}

async function detectSigns(baseName) {
    const infoEl = document.getElementById('sign-detection-info');
    infoEl.textContent = 'Analisando...';

    try {
        const resp = await fetch(`/detect-signs/${jobId}/${encodeURIComponent(baseName)}`, {
            method: 'POST',
        });

        if (!resp.ok) {
            infoEl.textContent = '';
            return;
        }

        const data = await resp.json();

        if (data.has_dc && data.matches_convention) {
            infoEl.textContent = 'D/C detectado — convencao padrao confirmada';
            infoEl.className = 'sign-info sign-ok';
        } else if (data.has_dc && !data.matches_convention) {
            infoEl.textContent = 'D/C detectado — convencao NAO padrao';
            infoEl.className = 'sign-info sign-warn';
        } else if (data.has_signs) {
            infoEl.textContent = 'Valores ja tem sinais +/-';
            infoEl.className = 'sign-info sign-ok';
        } else if (data.needs_user_input) {
            infoEl.textContent = 'Sem D/C e sem sinais — escolha abaixo';
            infoEl.className = 'sign-info sign-ask';
        } else {
            infoEl.textContent = data.details || '';
            infoEl.className = 'sign-info';
        }
    } catch (err) {
        infoEl.textContent = '';
    }
}

async function generateXlsx() {
    if (!jobId) return;

    const btn = document.getElementById('xlsx-btn');
    const resultDiv = document.getElementById('xlsx-result');
    const signMode = document.getElementById('xlsx-sign-mode').value;

    btn.disabled = true;
    btn.textContent = 'Gerando...';
    resultDiv.classList.add('hidden');

    try {
        const resp = await fetch(`/convert-xlsx/${jobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sign_mode: signMode }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro ao gerar XLSX');
            return;
        }

        const data = await resp.json();

        resultDiv.classList.remove('hidden');
        resultDiv.innerHTML = '';

        const f = data.files[0];
        if (!f) return;

        if (f.error) {
            resultDiv.innerHTML = `<div class="xlsx-error">Erro: ${f.error}</div>`;
            return;
        }

        const signInfo = f.sign_detection || {};
        let signText = '';
        if (signInfo.has_dc && signInfo.matches_convention) {
            signText = ' — D/C convertido';
        } else if (signInfo.has_signs) {
            signText = ' — sinais mantidos';
        } else if (signInfo.needs_user_input) {
            signText = ' — sem conversao de sinais';
        }

        const tabsCount = f.tabs_count || 0;
        const periodos = (f.periodos || []).join(', ');

        resultDiv.innerHTML = `
            <div class="xlsx-result-item">
                <span>📊 ${f.filename}</span>
                <span class="xlsx-periodo">${tabsCount} aba${tabsCount > 1 ? 's' : ''}: ${periodos}${signText}</span>
                <button class="btn-download" onclick="downloadFile('${f.filename}')">Baixar</button>
            </div>
        `;

        // Mostra seção de referência após gerar XLSX
        showReferenceSection();

        refreshResults();

    } catch (err) {
        alert('Erro: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Gerar XLSX Profissional';
    }
}

// ---------------------------------------------------------------------------
// Sign Dialog
// ---------------------------------------------------------------------------
function showSignDialog(message) {
    return new Promise((resolve) => {
        signDialogResolve = resolve;
        document.getElementById('sign-dialog-message').textContent = message;
        document.getElementById('sign-dialog').classList.remove('hidden');
    });
}

function signDialogConfirm(mode) {
    document.getElementById('sign-dialog').classList.add('hidden');
    if (signDialogResolve) {
        signDialogResolve(mode);
        signDialogResolve = null;
    }
}

// ---------------------------------------------------------------------------
// Correction / Resubmission
// ---------------------------------------------------------------------------
function showCorrectionSection(previewData) {
    const section = document.getElementById('correction-section');
    const select = document.getElementById('correction-file');

    section.classList.remove('hidden');

    select.innerHTML = '<option value="">Selecione o arquivo...</option>';
    Object.keys(previewData).forEach(key => {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = key;
        select.appendChild(opt);
    });
}

async function submitCorrection() {
    const baseName = document.getElementById('correction-file').value;
    const correction = document.getElementById('correction-text').value.trim();
    const statusDiv = document.getElementById('correction-status');

    if (!baseName) {
        alert('Selecione um arquivo.');
        return;
    }
    if (!correction) {
        alert('Descreva a correcao necessaria.');
        return;
    }

    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = '<span class="spinner"></span> Reenviando ao Gemini...';

    try {
        const resp = await fetch(`/resubmit/${jobId}/${encodeURIComponent(baseName)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ correction, version: 2 }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            statusDiv.innerHTML = `<span class="error-info">Erro: ${err.detail || 'falha'}</span>`;
            return;
        }

        statusDiv.innerHTML = 'Resubmissao iniciada. Aguarde...';
        pollCorrectionResult(baseName, 2);

    } catch (err) {
        statusDiv.innerHTML = `<span class="error-info">Erro: ${err.message}</span>`;
    }
}

async function pollCorrectionResult(baseName, version) {
    const statusDiv = document.getElementById('correction-status');
    const key = `${baseName}_v${version}`;
    let attempts = 0;

    const interval = setInterval(async () => {
        attempts++;
        if (attempts > 120) {
            clearInterval(interval);
            statusDiv.innerHTML = 'Tempo esgotado. Verifique os resultados manualmente.';
            return;
        }

        try {
            const resp = await fetch(`/results/${jobId}`);
            if (!resp.ok) return;

            const data = await resp.json();
            if (data.preview_data && data.preview_data[key]) {
                clearInterval(interval);
                statusDiv.innerHTML = `Nova versao <strong>${key}</strong> gerada!`;
                renderResults(data);
                currentPreviewData = data.preview_data;
                showCorrectionSection(data.preview_data);
            }
        } catch (err) {
            // continue polling
        }
    }, 1000);
}

// ---------------------------------------------------------------------------
// Reference / RAG — painel unificado (pré e pós-conversão)
// ---------------------------------------------------------------------------
let refSource = 'system';  // 'system' ou 'upload' (post-conversion only)
let refUploadedFilePre = null;
let refUploadedFilePost = null;

// Toggle painel colapsável
function toggleRefPanel(which) {
    const body = document.getElementById(`ref-panel-${which}-body`);
    const toggle = document.getElementById(`ref-panel-${which}-toggle`);
    const isOpen = !body.classList.contains('collapsed');
    if (isOpen) {
        body.classList.add('collapsed');
        toggle.innerHTML = '&#9654;';  // ▶
    } else {
        body.classList.remove('collapsed');
        toggle.innerHTML = '&#9660;';  // ▼
    }
}

// Carrega referências e popula ambos os painéis
async function loadAllReferences() {
    try {
        const resp = await fetch('/references');
        if (!resp.ok) return;
        const data = await resp.json();
        allReferences = data.references || [];

        // Atualiza seletor no painel pré
        renderRefList(allReferences);

        // Atualiza badge no header
        const badgePre = document.getElementById('ref-panel-pre-badge');
        const badgePost = document.getElementById('ref-panel-post-badge');
        if (allReferences.length > 0) {
            badgePre.textContent = allReferences.length;
            badgePre.classList.remove('hidden');
            if (badgePost) {
                badgePost.textContent = allReferences.length;
                badgePost.classList.remove('hidden');
            }
        } else {
            badgePre.classList.add('hidden');
            if (badgePost) badgePost.classList.add('hidden');
        }

        // Mostra/esconde empty state
        const emptyEl = document.getElementById('ref-list-empty');
        if (allReferences.length === 0) {
            emptyEl.classList.remove('hidden');
            document.getElementById('ref-selector-list').classList.add('hidden');
            document.getElementById('ref-search').classList.add('hidden');
        } else {
            emptyEl.classList.add('hidden');
            document.getElementById('ref-selector-list').classList.remove('hidden');
            document.getElementById('ref-search').classList.remove('hidden');
        }

        // Atualiza listas de referências ativas em ambos os painéis
        renderRefActiveLists();

        // Atualiza seleção no pós se visível
        updatePostSelectionDisplay();
    } catch (err) {
        console.error('Erro ao carregar referências:', err);
    }
}

function renderRefList(refs) {
    const list = document.getElementById('ref-selector-list');
    list.innerHTML = '';

    if (refs.length === 0) return;

    refs.forEach(ref => {
        const div = document.createElement('div');
        div.className = 'ref-list-item' + (selectedReferenceName === ref.filename ? ' selected' : '');
        div.onclick = () => selectReference(ref);
        div.innerHTML = `
            <span class="ref-list-name">${escapeHtml(ref.display_name || ref.empresa || ref.filename)}</span>
            <span class="ref-list-meta">${ref.total_contas} contas · ${ref.grupos} grupos</span>
        `;
        list.appendChild(div);
    });
}

function filterReferences() {
    const query = document.getElementById('ref-search').value.toLowerCase().trim();
    if (!query) {
        renderRefList(allReferences);
        return;
    }
    const filtered = allReferences.filter(ref => {
        const name = (ref.display_name || ref.empresa || ref.filename || '').toLowerCase();
        const periodo = (ref.periodo || '').toLowerCase();
        return name.includes(query) || periodo.includes(query);
    });
    renderRefList(filtered);
}

function selectReference(ref) {
    selectedReferenceName = ref.filename;
    const displayName = ref.display_name || ref.empresa || ref.filename;

    // Atualiza seleção no pré-conversão
    const selectedEl = document.getElementById('ref-selected');
    const nameEl = document.getElementById('ref-selected-name');
    selectedEl.classList.remove('hidden');
    nameEl.textContent = `📚 ${displayName}`;

    // Fecha a lista
    document.getElementById('ref-selector-list').classList.add('collapsed');
    document.getElementById('ref-search').value = '';

    // Atualiza visual da lista
    renderRefList(allReferences);

    // Atualiza seleção no pós-conversão
    updatePostSelectionDisplay();
}

function clearSelectedRef() {
    selectedReferenceName = null;

    // Limpa pré
    document.getElementById('ref-selected').classList.add('hidden');
    document.getElementById('ref-selected-name').textContent = '';
    document.getElementById('ref-selector-list').classList.remove('collapsed');
    renderRefList(allReferences);

    // Limpa pós
    updatePostSelectionDisplay();
}

function updatePostSelectionDisplay() {
    const selectedPost = document.getElementById('ref-selected-post');
    const namePost = document.getElementById('ref-selected-name-post');
    const noSelection = document.getElementById('ref-no-selection-post');

    if (!selectedPost) return;

    if (selectedReferenceName) {
        const ref = allReferences.find(r => r.filename === selectedReferenceName);
        const displayName = ref ? (ref.display_name || ref.empresa || ref.filename) : selectedReferenceName;
        selectedPost.classList.remove('hidden');
        namePost.textContent = `📚 ${displayName}`;
        if (noSelection) noSelection.classList.add('hidden');
    } else {
        selectedPost.classList.add('hidden');
        namePost.textContent = '';
        if (noSelection) noSelection.classList.remove('hidden');
    }
}

function renderRefActiveLists() {
    // Renderiza lista em pré
    renderRefActiveList('refs-list-pre', 'ref-active-list-pre');
    // Renderiza lista em pós
    renderRefActiveList('refs-list-post', 'ref-active-list-post');
}

function renderRefActiveList(listId, containerId) {
    const container = document.getElementById(containerId);
    const list = document.getElementById(listId);
    if (!container || !list) return;

    if (allReferences.length === 0) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');
    list.innerHTML = '';

    allReferences.forEach(ref => {
        const div = document.createElement('div');
        div.className = 'ref-item';
        div.innerHTML = `
            <span class="ref-name">${escapeHtml(ref.display_name || ref.empresa || ref.filename)} — ${ref.periodo || 'sem período'}</span>
            <span class="ref-meta">${ref.total_contas} contas · ${ref.grupos} grupos</span>
            <button class="btn-ref-remove" onclick="deleteReference('${ref.filename}')" title="Remover">&times;</button>
        `;
        list.appendChild(div);
    });
}

// Mostra painel pós-conversão
function showReferenceSection() {
    document.getElementById('reference-section').classList.remove('hidden');
    loadAllReferences();
}

// Alterna entre source system/upload (pós-conversão)
function setRefSource(source) {
    refSource = source;
    document.querySelectorAll('.ref-source-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.source === source);
    });

    const uploadArea = document.getElementById('ref-upload-area-post');
    if (source === 'upload') {
        uploadArea.classList.remove('hidden');
    } else {
        uploadArea.classList.add('hidden');
    }
}

// Inicializa drag & drop para ambos os painéis
(function initRefUpload() {
    document.addEventListener('DOMContentLoaded', () => {
        // Painel pré-conversão
        initDropZone('ref-drop-zone-pre', 'ref-file-input-pre', 'pre');
        // Painel pós-conversão
        initDropZone('ref-drop-zone-post', 'ref-file-input-post', 'post');
    });
})();

function initDropZone(dropZoneId, fileInputId, which) {
    const dz = document.getElementById(dropZoneId);
    const fi = document.getElementById(fileInputId);
    if (!dz || !fi) return;

    dz.addEventListener('dragover', (e) => {
        e.preventDefault();
        dz.classList.add('drag-over');
    });
    dz.addEventListener('dragleave', () => {
        dz.classList.remove('drag-over');
    });
    dz.addEventListener('drop', (e) => {
        e.preventDefault();
        dz.classList.remove('drag-over');
        const file = Array.from(e.dataTransfer.files).find(f =>
            f.name.toLowerCase().endsWith('.xlsx') || f.name.toLowerCase().endsWith('.xls')
        );
        if (file) setRefFile(file, which);
    });

    fi.addEventListener('change', () => {
        if (fi.files.length > 0) setRefFile(fi.files[0], which);
        fi.value = '';
    });
}

function setRefFile(file, which) {
    if (which === 'pre') {
        refUploadedFilePre = file;
    } else {
        refUploadedFilePost = file;
    }
    const nameEl = document.getElementById(`ref-file-name-${which}`);
    nameEl.classList.remove('hidden');
    nameEl.innerHTML = `
        <span class="ref-file-icon">📊</span>
        <span>${file.name}</span>
        <span class="ref-file-size">(${formatSize(file.size)})</span>
        <button class="btn-ref-remove" onclick="clearRefFile('${which}')" title="Remover">&times;</button>
    `;
}

function clearRefFile(which) {
    if (which === 'pre') {
        refUploadedFilePre = null;
    } else {
        refUploadedFilePost = null;
    }
    const nameEl = document.getElementById(`ref-file-name-${which}`);
    nameEl.classList.add('hidden');
    nameEl.innerHTML = '';
}

// Salvar referência do painel pré-conversão (upload only)
async function saveReferencePre() {
    const btn = document.getElementById('save-ref-btn-pre');
    const status = document.getElementById('ref-status-pre');
    const refName = document.getElementById('ref-name-pre').value.trim();
    const instructions = document.getElementById('ref-instructions-pre').value.trim();

    if (!refName) {
        status.textContent = 'Informe o nome da referência.';
        status.className = 'reference-status error';
        document.getElementById('ref-name-pre').focus();
        return;
    }

    if (!refUploadedFilePre) {
        status.textContent = 'Anexe o arquivo XLSX.';
        status.className = 'reference-status error';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Extraindo padrão...';
    status.textContent = '';

    try {
        const refModel = document.getElementById('ref-model-pre').value;
        const formData = new FormData();
        formData.append('file', refUploadedFilePre);
        formData.append('instructions', instructions);
        formData.append('name', refName);
        formData.append('model', refModel);

        const resp = await fetch('/upload-reference', {
            method: 'POST',
            body: formData,
        });

        if (!resp.ok) {
            const err = await resp.json();
            status.textContent = 'Erro: ' + (err.detail || 'falha');
            status.className = 'reference-status error';
            return;
        }

        const data = await resp.json();

        status.textContent = 'Referência salva com sucesso!';
        status.className = 'reference-status success';

        // Limpa formulário
        document.getElementById('ref-name-pre').value = '';
        document.getElementById('ref-instructions-pre').value = '';
        clearRefFile('pre');

        // Recarrega listas e seleciona automaticamente a nova
        await loadAllReferences();

        // Auto-seleciona a referência recém-criada
        const newRef = allReferences.find(r => (r.display_name || '') === refName || r.filename === data.filename);
        if (newRef) selectReference(newRef);

    } catch (err) {
        status.textContent = 'Erro: ' + err.message;
        status.className = 'reference-status error';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Salvar Referência';
    }
}

// Salvar referência do painel pós-conversão (system ou upload)
async function saveReferencePost() {
    const btn = document.getElementById('save-ref-btn-post');
    const status = document.getElementById('ref-status-post');
    const infoDiv = document.getElementById('ref-info-post');
    const detailsDiv = document.getElementById('ref-details-post');
    const refName = document.getElementById('ref-name-post').value.trim();
    const instructions = document.getElementById('ref-instructions-post').value.trim();

    if (!refName) {
        status.textContent = 'Informe o nome da referência.';
        status.className = 'reference-status error';
        document.getElementById('ref-name-post').focus();
        return;
    }

    if (refSource === 'upload' && !refUploadedFilePost) {
        status.textContent = 'Anexe o XLSX corrigido ou use o XLSX gerado.';
        status.className = 'reference-status error';
        return;
    }

    if (refSource === 'system' && !jobId) {
        status.textContent = 'Gere o XLSX Profissional primeiro.';
        status.className = 'reference-status error';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Extraindo padrão...';
    status.textContent = '';
    infoDiv.classList.add('hidden');

    try {
        let resp;
        const refModel = document.getElementById('ref-model-post').value;

        if (refSource === 'upload') {
            const formData = new FormData();
            formData.append('file', refUploadedFilePost);
            formData.append('instructions', instructions);
            formData.append('name', refName);
            formData.append('model', refModel);
            resp = await fetch('/upload-reference', { method: 'POST', body: formData });
        } else {
            resp = await fetch(`/save-reference/${jobId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instructions, name: refName, model: refModel }),
            });
        }

        if (!resp.ok) {
            const err = await resp.json();
            status.textContent = 'Erro: ' + (err.detail || 'falha');
            status.className = 'reference-status error';
            return;
        }

        const data = await resp.json();

        status.textContent = 'Referência salva com sucesso!';
        status.className = 'reference-status success';

        infoDiv.classList.remove('hidden');
        detailsDiv.innerHTML = `
            <div class="ref-stat">
                <span class="label">Nome:</span>
                <span class="value">${escapeHtml(data.display_name || refName)}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Empresa:</span>
                <span class="value">${data.empresa || 'N/A'}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Período:</span>
                <span class="value">${data.periodo || 'N/A'}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Contas:</span>
                <span class="value">${data.total_contas}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Grupos:</span>
                <span class="value">${data.grupos}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Nós hierárquicos:</span>
                <span class="value">${data.hierarchy_nodes}</span>
            </div>
            <div class="ref-stat">
                <span class="label">Exemplos de sinais:</span>
                <span class="value">${data.sign_examples}</span>
            </div>
            <div class="ref-preview">
                <details>
                    <summary>Preview da referência</summary>
                    <pre>${escapeHtml(data.preview || '')}</pre>
                </details>
            </div>
        `;

        // Limpa formulário
        document.getElementById('ref-name-post').value = '';
        document.getElementById('ref-instructions-post').value = '';
        if (refSource === 'upload') clearRefFile('post');

        // Recarrega listas
        await loadAllReferences();

        // Auto-seleciona
        const newRef = allReferences.find(r => (r.display_name || '') === refName || r.filename === data.filename);
        if (newRef) selectReference(newRef);

    } catch (err) {
        status.textContent = 'Erro: ' + err.message;
        status.className = 'reference-status error';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Salvar como Referência';
    }
}

async function deleteReference(filename) {
    try {
        const resp = await fetch(`/references/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
        });
        if (resp.ok) {
            // Se deletou a referência selecionada, limpa seleção
            if (selectedReferenceName === filename) {
                clearSelectedRef();
            }
            await loadAllReferences();
        }
    } catch (err) {
        console.error('Erro ao remover referência:', err);
    }
}

// ---------------------------------------------------------------------------
// Chat — Atualizar referências via IA
// ---------------------------------------------------------------------------
let chatHistory = [];  // histórico de mensagens {role: 'user'|'assistant', content: ''}

function toggleChatPanel() {
    const body = document.getElementById('chat-body');
    const toggle = document.getElementById('chat-toggle');
    const isOpen = !body.classList.contains('collapsed');
    if (isOpen) {
        body.classList.add('collapsed');
        toggle.innerHTML = '&#9654;';
    } else {
        body.classList.remove('collapsed');
        toggle.innerHTML = '&#9660;';
        populateChatRefSelector();
    }
}

function populateChatRefSelector() {
    const select = document.getElementById('chat-ref-select');
    const current = select.value;
    select.innerHTML = '<option value="">Selecione uma referência...</option>';
    allReferences.forEach(ref => {
        const opt = document.createElement('option');
        opt.value = ref.filename;
        opt.textContent = ref.display_name || ref.empresa || ref.filename;
        select.appendChild(opt);
    });
    if (current) select.value = current;
}

function chatKeyHandler(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const refSelect = document.getElementById('chat-ref-select');
    const modelSelect = document.getElementById('chat-model-select');
    const btn = document.getElementById('chat-send-btn');
    const messagesDiv = document.getElementById('chat-messages');

    const message = input.value.trim();
    if (!message) return;

    const refName = refSelect.value;
    if (!refName) {
        alert('Selecione uma referência para editar.');
        return;
    }

    // Adiciona mensagem do usuário
    chatHistory.push({ role: 'user', content: message });
    appendChatBubble('user', message);
    input.value = '';
    btn.disabled = true;
    btn.textContent = 'Enviando...';

    // Mostra indicador de carregamento
    const loadingId = appendChatBubble('assistant', '<span class="spinner"></span> Analisando...');

    try {
        const resp = await fetch('/chat-reference', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                reference_name: refName,
                message: message,
                model: modelSelect.value,
                history: chatHistory.slice(-10),  // últimas 10 mensagens
            }),
        });

        // Remove loading
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();

        if (!resp.ok) {
            const err = await resp.json();
            appendChatBubble('assistant', 'Erro: ' + (err.detail || 'falha'));
            return;
        }

        const data = await resp.json();
        chatHistory.push({ role: 'assistant', content: data.response });
        appendChatBubble('assistant', data.response);

        if (data.updated) {
            appendChatBubble('system', 'Referência atualizada com sucesso!');
            await loadAllReferences();
        }

    } catch (err) {
        const loadingEl = document.getElementById(loadingId);
        if (loadingEl) loadingEl.remove();
        appendChatBubble('assistant', 'Erro de conexão: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Enviar';
    }
}

function appendChatBubble(role, content) {
    const messagesDiv = document.getElementById('chat-messages');
    const id = 'chat-msg-' + Date.now() + '-' + Math.random().toString(36).substr(2, 5);

    const div = document.createElement('div');
    div.id = id;
    div.className = `chat-bubble chat-${role}`;

    if (role === 'user') {
        div.innerHTML = `<strong>Você:</strong> ${escapeHtml(content)}`;
    } else if (role === 'system') {
        div.innerHTML = `<em>${content}</em>`;
    } else {
        div.innerHTML = `<strong>IA:</strong> ${content}`;
    }

    messagesDiv.appendChild(div);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    return id;
}

// ---------------------------------------------------------------------------
// Refresh results
// ---------------------------------------------------------------------------
async function refreshResults() {
    try {
        const resp = await fetch(`/results/${jobId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        renderResults(data);
    } catch (err) {
        // ignore
    }
}

// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------
function downloadFile(filename) {
    window.open(`/download/${jobId}/${encodeURIComponent(filename)}`);
}

function downloadAll() {
    if (!jobId) return;
    window.open(`/download-all/${jobId}`);
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------
function resetApp() {
    jobId = null;
    uploadedFiles = [];
    currentPreviewData = null;

    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }

    fileListSection.classList.add('hidden');
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');

    fileList.innerHTML = '';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-bar').className = 'progress-bar active';
    document.getElementById('progress-pct').textContent = '0%';
    document.getElementById('progress-text').textContent = '';
    document.getElementById('elapsed-timer').textContent = '0:00';
    document.getElementById('progress-details').innerHTML = '';
    document.getElementById('results-list').innerHTML = '';
    document.getElementById('preview-section').classList.add('hidden');
    document.getElementById('preview-tabs').innerHTML = '';
    document.getElementById('preview-container').innerHTML = '';
    document.getElementById('xlsx-section').classList.add('hidden');
    document.getElementById('xlsx-result').classList.add('hidden');
    document.getElementById('correction-section').classList.add('hidden');
    document.getElementById('correction-status').classList.add('hidden');
    document.getElementById('correction-text').value = '';
    // Reset painel pós-conversão
    document.getElementById('reference-section').classList.add('hidden');
    document.getElementById('ref-info-post').classList.add('hidden');
    document.getElementById('ref-status-post').textContent = '';
    document.getElementById('ref-instructions-post').value = '';
    document.getElementById('ref-name-post').value = '';
    document.getElementById('ref-upload-area-post').classList.add('hidden');
    document.getElementById('ref-active-list-post').classList.add('hidden');
    clearRefFile('post');
    refSource = 'system';
    document.querySelectorAll('.ref-source-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.source === 'system');
    });
    document.getElementById('sign-dialog').classList.add('hidden');

    // Reset chat
    chatHistory = [];
    const chatMsgs = document.getElementById('chat-messages');
    if (chatMsgs) chatMsgs.innerHTML = '';

    // Reset painel pré-conversão
    selectedReferenceName = null;
    allReferences = [];
    document.getElementById('ref-selector-list').innerHTML = '';
    document.getElementById('ref-selected').classList.add('hidden');
    document.getElementById('ref-selected-name').textContent = '';
    document.getElementById('ref-search').value = '';
    document.getElementById('ref-name-pre').value = '';
    document.getElementById('ref-instructions-pre').value = '';
    document.getElementById('ref-status-pre').textContent = '';
    document.getElementById('ref-active-list-pre').classList.add('hidden');
    clearRefFile('pre');

    convertBtn.disabled = false;
    convertBtn.textContent = 'Converter';
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}
