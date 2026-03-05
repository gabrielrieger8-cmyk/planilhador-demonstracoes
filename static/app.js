/* Planilhador de Demonstrações — Frontend */

let jobId = null;
let uploadedFiles = [];
let eventSource = null;
let modelDefaults = {};
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileListSection = document.getElementById('file-list-section');
const fileList = document.getElementById('file-list');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const convertBtn = document.getElementById('convert-btn');
const skipFormatCheckbox = document.getElementById('skip-format');

// ---------------------------------------------------------------------------
// Load available models
// ---------------------------------------------------------------------------

async function loadModels() {
    try {
        const resp = await fetch('/models');
        if (!resp.ok) return;
        const data = await resp.json();
        modelDefaults = data.defaults || {};

        const stages = ['classifier', 'extractor'];
        stages.forEach(stage => {
            const select = document.getElementById(`model-${stage}`);
            if (!select) return;
            select.innerHTML = '';
            const options = data[stage] || [];
            options.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = m.label;
                if (m.id === data.defaults[stage]) opt.selected = true;
                select.appendChild(opt);
            });
        });
    } catch (err) {
        console.error('Erro ao carregar modelos:', err);
    }
}

loadModels();

// ---------------------------------------------------------------------------
// Drop Zone
// ---------------------------------------------------------------------------

// Previne o browser de abrir o arquivo ao soltar fora da drop zone
document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => e.preventDefault());

dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dropZone.classList.add('active');
});

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    dropZone.classList.add('active');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('active');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
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
        const url = jobId ? `/upload?existing_job_id=${jobId}` : '/upload';
        const resp = await fetch(url, { method: 'POST', body: formData });
        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Erro no upload');
            return;
        }

        const data = await resp.json();
        if (!jobId) {
            jobId = data.job_id;
            uploadedFiles = data.files;
        } else {
            uploadedFiles = uploadedFiles.concat(data.files);
        }
        const totalPages = uploadedFiles.reduce((s, f) => s + f.pages, 0);

        renderFileList({ files: uploadedFiles, total_pages: totalPages });
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

    // Coleta modelos selecionados
    const models = {};
    ['classifier', 'extractor'].forEach(stage => {
        const select = document.getElementById(`model-${stage}`);
        if (select) models[stage] = select.value;
    });

    const skipFormat = skipFormatCheckbox && skipFormatCheckbox.checked;

    const formulasDre = document.getElementById('formulas-dre')?.checked ?? true;
    const formulasBalanco = document.getElementById('formulas-balanco')?.checked ?? true;
    const formulasBalancete = document.getElementById('formulas-balancete')?.checked ?? false;

    try {
        const resp = await fetch(`/process/${jobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...models,
                skip_format: skipFormat,
                formulas_dre: formulasDre,
                formulas_balanco: formulasBalanco,
                formulas_balancete: formulasBalancete,
            }),
        });
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

    // Agrupa arquivos por status
    const processing = data.progress.filter(p => p.status === 'processing');
    const queued = data.progress.filter(p => p.status === 'pending' && p.queue_position != null);
    const done = data.progress.filter(p => p.status === 'done');
    const errors = data.progress.filter(p => p.status === 'error');
    const cancelled = data.progress.filter(p => p.status === 'cancelled');

    const details = document.getElementById('progress-details');
    details.innerHTML = '';

    // Grupo: Em processamento
    if (processing.length > 0) {
        _appendGroupHeader(details, `Em processamento (${processing.length})`);
        processing.forEach(p => details.appendChild(_buildProgressItem(p, data)));
    }

    // Grupo: Na fila
    if (queued.length > 0) {
        _appendGroupHeader(details, `Na fila (${queued.length})`);
        queued.sort((a, b) => a.queue_position - b.queue_position);
        queued.forEach(p => details.appendChild(_buildProgressItem(p, data)));
    }

    // Grupo: Concluídos
    if (done.length > 0) {
        _appendGroupHeader(details, `Concluídos (${done.length})`);
        done.forEach(p => details.appendChild(_buildProgressItem(p, data)));
    }

    // Grupo: Erros
    if (errors.length > 0) {
        _appendGroupHeader(details, `Erros (${errors.length})`);
        errors.forEach(p => details.appendChild(_buildProgressItem(p, data)));
    }

    // Grupo: Cancelados
    if (cancelled.length > 0) {
        _appendGroupHeader(details, `Cancelados (${cancelled.length})`);
        cancelled.forEach(p => details.appendChild(_buildProgressItem(p, data)));
    }
}

function _appendGroupHeader(container, text) {
    const header = document.createElement('div');
    header.className = 'progress-group-header';
    header.textContent = text;
    container.appendChild(header);
}

function _buildProgressItem(p, data) {
    const div = document.createElement('div');
    div.className = `progress-item ${p.status}`;

    let iconHtml = '';
    if (p.status === 'pending') iconHtml = '<span class="pulse-dot"></span>';
    else if (p.status === 'processing') iconHtml = '<span class="spinner"></span>';
    else if (p.status === 'done') iconHtml = '<span class="check-icon">✓</span>';
    else if (p.status === 'error') iconHtml = '<span style="color:#e53935;">✗</span>';
    else if (p.status === 'cancelled') iconHtml = '<span style="color:#9ca3af;">⊘</span>';

    let rightHtml = '';
    if (p.status === 'pending') {
        const queuedItems = data.progress.filter(x => x.status === 'pending' && x.queue_position != null);
        const isFirst = queuedItems.length > 0 && p.queue_position === 1;
        const isLast = queuedItems.length > 0 && p.queue_position === queuedItems.length;

        rightHtml = `
            <span class="queue-position">Posição ${p.queue_position}</span>
            <span class="queue-actions">
                <button class="queue-btn" ${isFirst ? 'disabled' : ''} onclick="moveInQueue(${p.idx}, -1)" title="Mover para cima">↑</button>
                <button class="queue-btn" ${isLast ? 'disabled' : ''} onclick="moveInQueue(${p.idx}, 1)" title="Mover para baixo">↓</button>
                <button class="queue-btn queue-btn-cancel" onclick="cancelFromQueue(${p.idx})" title="Cancelar">✕</button>
            </span>
        `;
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
            </span>
        `;
    } else if (p.status === 'error') {
        rightHtml = `<span class="error-info" title="${p.error || ''}">${p.error || 'Erro'}</span>`;
    } else if (p.status === 'cancelled') {
        rightHtml = '<span class="stage-info cancelled-text">Cancelado</span>';
    }

    div.innerHTML = `
        <span class="status-icon">${iconHtml}</span>
        <span class="filename">${p.filename}</span>
        <span class="pages-badge">${p.pages || 0}p</span>
        ${rightHtml}
    `;
    return div;
}

// ---------------------------------------------------------------------------
// Queue control
// ---------------------------------------------------------------------------

async function moveInQueue(fileIdx, direction) {
    if (!jobId) return;
    try {
        // Busca fila atual do último render
        const resp = await fetch(`/progress/${jobId}`);
        // Não podemos usar SSE aqui, vamos manipular a fila diretamente
        // Pega a fila atual do backend
        const queueResp = await fetch(`/queue/reorder/${jobId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ order: _reorderQueue(fileIdx, direction) }),
        });
        if (!queueResp.ok) {
            console.error('Erro ao reordenar fila:', await queueResp.text());
        }
    } catch (err) {
        console.error('Erro ao reordenar:', err);
    }
}

function _reorderQueue(fileIdx, direction) {
    // Reconstrói a fila a partir dos dados do último render
    const details = document.getElementById('progress-details');
    const queueBtns = details.querySelectorAll('.queue-btn[onclick*="moveInQueue"]');
    // Extrai índices dos itens na fila na ordem atual
    const queueItems = [];
    details.querySelectorAll('.progress-item.pending').forEach(item => {
        const btn = item.querySelector('.queue-btn-cancel');
        if (btn) {
            const match = btn.getAttribute('onclick').match(/cancelFromQueue\((\d+)\)/);
            if (match) queueItems.push(parseInt(match[1]));
        }
    });

    const pos = queueItems.indexOf(fileIdx);
    if (pos === -1) return queueItems;

    const newPos = pos + direction;
    if (newPos < 0 || newPos >= queueItems.length) return queueItems;

    // Swap
    [queueItems[pos], queueItems[newPos]] = [queueItems[newPos], queueItems[pos]];
    return queueItems;
}

async function cancelFromQueue(fileIdx) {
    if (!jobId) return;
    try {
        const resp = await fetch(`/queue/cancel/${jobId}/${fileIdx}`, { method: 'POST' });
        if (!resp.ok) {
            console.error('Erro ao cancelar:', await resp.text());
        }
    } catch (err) {
        console.error('Erro ao cancelar:', err);
    }
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
        document.getElementById('feedback-section').classList.remove('hidden');
    } catch (err) {
        console.error('Erro ao buscar resultados:', err);
    }
}

function renderResults(data) {
    const summary = document.getElementById('results-summary');

    let html = '<div class="result-stats">';

    html += `
        <span class="result-stat">
            <span class="label">Tempo:</span>
            <span class="value">${data.total_time.toFixed(1)}s</span>
        </span>
    `;

    html += `
        <span class="result-stat">
            <span class="label">Arquivos:</span>
            <span class="value">${data.files.length}</span>
        </span>
    </div>`;

    summary.innerHTML = html;

    const list = document.getElementById('results-list');
    list.innerHTML = '';

    if (data.files.length === 0) {
        list.innerHTML = '<p class="no-results">Nenhum arquivo gerado.</p>';
        document.getElementById('download-all-btn').classList.add('hidden');
        return;
    }

    document.getElementById('download-all-btn').classList.remove('hidden');

    // Mostra botão "Gerar CSV" se ainda não há CSVs gerados
    const hasCSV = data.files.some(f => f.type === 'csv');
    const csvBtn = document.getElementById('generate-csv-btn');
    if (csvBtn) {
        if (hasCSV) {
            csvBtn.classList.add('hidden');
        } else {
            csvBtn.classList.remove('hidden');
        }
    }

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

async function generateCSV() {
    if (!jobId) return;
    const btn = document.getElementById('generate-csv-btn');
    btn.disabled = true;
    btn.textContent = 'Gerando...';
    try {
        const resp = await fetch(`/generate-csv/${jobId}`, { method: 'POST' });
        if (!resp.ok) throw new Error('Erro ao gerar CSV');
        const result = await resp.json();
        btn.classList.add('hidden');
        // Recarrega lista de arquivos para mostrar os CSVs
        const dataResp = await fetch(`/results/${jobId}`);
        const data = await dataResp.json();
        renderResults(data);
    } catch (e) {
        btn.textContent = 'Gerar CSV';
        btn.disabled = false;
        console.error('Erro ao gerar CSV:', e);
    }
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

    // Restaura selects de modelo ao default
    ['classifier', 'extractor'].forEach(stage => {
        const select = document.getElementById(`model-${stage}`);
        if (select && modelDefaults[stage]) select.value = modelDefaults[stage];
    });

    // Restaura checkboxes
    if (skipFormatCheckbox) {
        skipFormatCheckbox.checked = false;
    }
    const fDre = document.getElementById('formulas-dre');
    const fBal = document.getElementById('formulas-balanco');
    const fBct = document.getElementById('formulas-balancete');
    if (fDre) fDre.checked = true;
    if (fBal) fBal.checked = true;
    if (fBct) fBct.checked = false;

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

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

const RATING_DESCS = {
    1: 'Inutilizavel: Output completamente errado, dados incorretos, formato ilegivel. Precisa refazer do zero.',
    2: 'Ruim: Muitos erros significativos (valores trocados, contas faltando). Retrabalho extenso.',
    3: 'Regular: Estrutura correta mas com erros pontuais. Correcao manual necessaria.',
    4: 'Bom: Poucos erros menores (arredondamento, acentuacao). Utilizavel com pequenos ajustes.',
    5: 'Excelente: Resultado perfeito ou quase perfeito. Pronto para uso direto.',
};

let selectedRating = 0;

function setRating(n) {
    selectedRating = n;
    document.querySelectorAll('.star-btn').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.rating) <= n);
    });
    document.getElementById('rating-desc').textContent = RATING_DESCS[n] || '';
    document.getElementById('feedback-submit').disabled = false;
}

async function submitFeedback() {
    if (!selectedRating) return;
    const text = document.getElementById('feedback-text').value.trim();
    try {
        await fetch('/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                rating: selectedRating,
                missing_info: text || null,
                context: { job_id: jobId, files: uploadedFiles.map(f => f.name) },
            }),
        });
        document.getElementById('feedback-submit').disabled = true;
        document.getElementById('feedback-thanks').classList.remove('hidden');
    } catch (err) {
        alert('Erro ao enviar avaliacao: ' + err.message);
    }
}
