// State
let jobId = null;
let uploadedFiles = [];
let eventSource = null;
let selectedModel = 'gemini-2.0-flash';

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

        // Atualiza botões do toggle
        document.querySelectorAll('.model-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.model === modelId);
        });

        // Atualiza subtítulo
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

// Workers slider
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
        const resp = await fetch(`/convert/${jobId}?workers=${workers}`, {
            method: 'POST'
        });

        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro ao iniciar conversao');
            convertBtn.disabled = false;
            convertBtn.textContent = 'Converter';
            return;
        }

        // Show progress, hide results
        progressSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');

        // Reset progress bar
        const bar = document.getElementById('progress-bar');
        bar.style.width = '0%';
        bar.classList.add('active');
        bar.classList.remove('done');

        // Start SSE
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

    // Progress bar
    const bar = document.getElementById('progress-bar');
    bar.style.width = pct + '%';

    if (data.status === 'done') {
        bar.classList.remove('active');
        bar.classList.add('done');
    }

    // Percentage
    document.getElementById('progress-pct').textContent = pct + '%';

    // Text
    document.getElementById('progress-text').textContent =
        `${data.completed} de ${data.total} concluido(s)`;

    // Elapsed timer
    if (data.elapsed !== undefined) {
        document.getElementById('elapsed-timer').textContent = formatTime(data.elapsed);
    }

    // File details
    const details = document.getElementById('progress-details');
    details.innerHTML = '';

    data.progress.forEach(p => {
        const div = document.createElement('div');
        div.className = `progress-item ${p.status}`;

        // Icon
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

        // Right-side content based on status
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

    // Mark progress bar as done
    const bar = document.getElementById('progress-bar');
    bar.classList.remove('active');
    bar.classList.add('done');

    // Fetch results
    try {
        const resp = await fetch(`/results/${jobId}`);
        if (!resp.ok) return;

        const data = await resp.json();
        renderResults(data);
        resultsSection.classList.remove('hidden');

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

    // Preview
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

    // Tabs se houver múltiplos arquivos
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

    // Renderiza a primeira tabela
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

    // Detecta índice da coluna Tipo
    let tipoIdx = -1;
    header.forEach((h, i) => {
        if (h.trim().toLowerCase() === 'tipo') tipoIdx = i;
    });

    // Detecta colunas numéricas (Saldo, Débito, Crédito)
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
