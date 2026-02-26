/* Planilhador de Demonstrações — Frontend */

let jobId = null;
let uploadedFiles = [];
let eventSource = null;

const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileListSection = document.getElementById('file-list-section');
const fileList = document.getElementById('file-list');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const convertBtn = document.getElementById('convert-btn');

// ---------------------------------------------------------------------------
// Drop Zone
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
        alert('Erro de conexão: ' + err.message);
    } finally {
        convertBtn.disabled = false;
        convertBtn.textContent = 'Gerar Demonstrações';
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
            <span class="file-meta">${f.pages}p · ${formatSize(f.size)}</span>
            <button class="file-remove" onclick="removeFile('${f.name}')" title="Remover">&times;</button>
        `;
        fileList.appendChild(div);
    });
    document.getElementById('total-info').textContent =
        `${data.files.length} arquivo(s) · ${data.total_pages} página(s)`;
}

async function removeFile(filename) {
    if (!jobId) return;
    try {
        const resp = await fetch(`/job/${jobId}/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        if (resp.ok) {
            const data = await resp.json();
            uploadedFiles = uploadedFiles.filter(f => f.name !== filename);
            renderFileList({ files: uploadedFiles, total_pages: data.total_pages });
            if (uploadedFiles.length === 0) {
                fileListSection.classList.add('hidden');
            }
        }
    } catch (err) {
        console.error('Erro ao remover:', err);
    }
}

// ---------------------------------------------------------------------------
// Processing & SSE
// ---------------------------------------------------------------------------

const STAGE_LABELS = {
    classifying: 'Classificando',
    extracting: 'Extraindo',
    formatting: 'Formatando',
    validating: 'Validando',
    exporting: 'Exportando',
};

const STAGE_ICONS = {
    classifying: '🏷️',
    extracting: '🔍',
    formatting: '🧠',
    validating: '✓',
    exporting: '📦',
};

async function startProcessing() {
    if (!jobId) return;

    convertBtn.disabled = true;
    convertBtn.textContent = 'Processando...';

    try {
        const resp = await fetch(`/process/${jobId}`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro ao iniciar');
            convertBtn.disabled = false;
            convertBtn.textContent = 'Gerar Demonstrações';
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
        alert('Erro de conexão: ' + err.message);
        convertBtn.disabled = false;
        convertBtn.textContent = 'Gerar Demonstrações';
    }
}

function listenProgress() {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`/progress/${jobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        renderProgress(data);

        if (data.status === 'done' || data.status === 'error') {
            eventSource.close();
            eventSource = null;
            onProcessingDone();
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        setTimeout(onProcessingDone, 1000);
    };
}

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
        `${data.completed} de ${data.total} concluído(s)`;

    if (data.elapsed !== undefined) {
        document.getElementById('elapsed-timer').textContent = formatTime(data.elapsed);
    }

    const details = document.getElementById('progress-details');
    details.innerHTML = '';

    data.progress.forEach(p => {
        const div = document.createElement('div');
        div.className = `progress-item ${p.status}`;

        let iconHtml = '';
        if (p.status === 'pending') iconHtml = '<span class="pulse-dot"></span>';
        else if (p.status === 'processing') iconHtml = '<span class="spinner"></span>';
        else if (p.status === 'done') iconHtml = '<span class="check-icon">✓</span>';
        else if (p.status === 'error') iconHtml = '<span style="color:#e53935;">✗</span>';

        let rightHtml = '';
        if (p.status === 'pending') {
            rightHtml = '<span class="stage-info">Na fila...</span>';
        } else if (p.status === 'processing') {
            const icon = STAGE_ICONS[p.stage] || '';
            const label = STAGE_LABELS[p.stage] || p.stage;
            rightHtml = `
                <span class="stage-badge ${p.stage}">${icon} ${label}</span>
                <span class="stage-info">${p.stage_detail || ''}</span>
            `;
        } else if (p.status === 'done') {
            rightHtml = `
                <span class="done-info">
                    <span>${p.time.toFixed(1)}s</span>
                    <span>·</span>
                    <span>$${p.cost.toFixed(4)}</span>
                </span>
            `;
        } else if (p.status === 'error') {
            rightHtml = `<span class="error-info" title="${p.error || ''}">${p.error || 'Erro'}</span>`;
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
// Results
// ---------------------------------------------------------------------------

async function onProcessingDone() {
    convertBtn.disabled = false;
    convertBtn.textContent = 'Gerar Demonstrações';

    const bar = document.getElementById('progress-bar');
    bar.classList.remove('active');
    bar.classList.add('done');

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
    summary.innerHTML = `
        <div class="result-stats">
            <span class="result-stat">
                <span class="label">Tempo:</span>
                <span class="value">${data.total_time.toFixed(1)}s</span>
            </span>
            <span class="result-stat">
                <span class="label">Custo:</span>
                <span class="value">$${data.total_cost.toFixed(4)}</span>
            </span>
            <span class="result-stat">
                <span class="label">Arquivos:</span>
                <span class="value">${data.files.length}</span>
            </span>
        </div>
    `;

    const list = document.getElementById('results-list');
    list.innerHTML = '';

    if (data.files.length === 0) {
        list.innerHTML = '<p class="no-results">Nenhum arquivo gerado.</p>';
        document.getElementById('download-all-btn').classList.add('hidden');
        return;
    }

    document.getElementById('download-all-btn').classList.remove('hidden');

    data.files.forEach(f => {
        const div = document.createElement('div');
        div.className = 'result-item';

        let badgeClass = f.type;
        let badgeLabel = f.type.toUpperCase();

        if (f.name.includes('dre')) { badgeClass = 'dre'; badgeLabel = 'DRE'; }
        else if (f.name.includes('balanco')) { badgeClass = 'bp'; badgeLabel = 'BP'; }
        else if (f.name.includes('balancete')) { badgeClass = 'balancete'; badgeLabel = 'Balancete'; }
        else if (f.type === 'xlsx') { badgeClass = 'xlsx'; badgeLabel = 'XLSX'; }

        div.innerHTML = `
            <span class="file-icon">📊</span>
            <span class="file-name" title="${f.name}">${f.name}</span>
            <span class="file-type-badge ${badgeClass}">${badgeLabel}</span>
            <span class="file-meta">${formatSize(f.size)}</span>
            <button class="btn-download" onclick="downloadFile('${f.name}')">Baixar</button>
        `;
        list.appendChild(div);
    });
}

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
    if (eventSource) { eventSource.close(); eventSource = null; }

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

    convertBtn.disabled = false;
    convertBtn.textContent = 'Gerar Demonstrações';
}

// ---------------------------------------------------------------------------
// Utilities
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
