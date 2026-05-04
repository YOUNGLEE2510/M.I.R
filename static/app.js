const API = '';

// ════════════════════════════════════════
//  UTILS
// ════════════════════════════════════════
const $ = id => document.getElementById(id);

function showOverlay(txt = 'Đang xử lý...') {
    $('overlay').classList.remove('hidden');
    $('overlayText').textContent = txt;
}
function hideOverlay() { $('overlay').classList.add('hidden'); }

function log(msg, type = 'info') {
    const box = $('ingestLog');
    box.classList.remove('hidden');
    const d = document.createElement('div');
    d.className = `l-${type}`;
    d.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
}

function fmt(n, d = 2) {
    return (n === undefined || n === null) ? '–' : Number(n).toFixed(d);
}

function instIcon(instrument = '') {
    const name = instrument.toLowerCase();
    if (['violin', 'viola'].some(x => name.includes(x))) return '🎻';
    if (['cello', 'bass', 'contrabass'].some(x => name.includes(x))) return '🎻';
    if (['guitar'].some(x => name.includes(x))) return '🎸';
    if (['ukulele', 'mandolin', 'banjo'].some(x => name.includes(x))) return '🪕';
    if (['harp'].some(x => name.includes(x))) return '🎵';
    if (['sitar', 'dan_tranh', 'dan_ty_ba', 'dan_bau'].some(x => name.includes(x))) return '🎶';
    return '♪';
}

function scoreColorClass(pct) {
    if (pct >= 70) return 'score-high';
    if (pct >= 40) return 'score-mid';
    return 'score-low';
}

// ════════════════════════════════════════
//  INIT
// ════════════════════════════════════════
async function initApp() {
    await Promise.all([checkDb(), loadStats()]);
}

async function checkDb() {
    const dot = $('dbDot');
    const text = $('dbStatusText');
    dot.className = 'status-dot loading';
    try {
        const { status, message } = await fetch(`${API}/api/ping`).then(r => r.json());
        if (status === 'OK') {
            dot.className = 'status-dot ok';
            text.textContent = 'Đã kết nối';
        } else throw new Error(message);
    } catch {
        dot.className = 'status-dot error';
        text.textContent = 'Lỗi kết nối';
    }
}

async function loadStats() {
    try {
        const d = await fetch(`${API}/api/stats`).then(r => r.json());
        $('totalFiles').textContent = d.total_files ?? 0;
        $('totalInstruments').textContent = (d.by_instrument ?? []).length;
        $('faissVectors').textContent = d.faiss_vectors ?? 0;
    } catch { }
}

// ════════════════════════════════════════
//  SIDEBAR NAVIGATION
// ════════════════════════════════════════
document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        $(`tab-${btn.dataset.tab}`).classList.add('active');
        if (btn.dataset.tab === 'database') loadDatabase();
    });
});

// ════════════════════════════════════════
//  DROPZONE HELPER
// ════════════════════════════════════════
function setupDrop(zoneId, inputId, onFiles) {
    const zone = $(zoneId);
    const input = $(inputId);
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', e => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onFiles(files);
    });
    input.addEventListener('change', () => {
        if (input.files.length) onFiles(Array.from(input.files));
    });
}

// ════════════════════════════════════════
//  TAB 1 – SEARCH
// ════════════════════════════════════════
let searchFile = null;

setupDrop('searchDropzone', 'searchFile', files => {
    const file = files[0];
    searchFile = file;
    $('searchFileName').textContent = file.name;
    $('searchAudio').src = URL.createObjectURL(file);
    $('uzIdle').classList.add('hidden');
    $('uzReady').classList.remove('hidden');
    $('searchEmpty').classList.add('hidden');
});

$('clearSearchBtn').addEventListener('click', () => {
    searchFile = null;
    // Revoke blob URL to prevent memory leak
    const audio = $('searchAudio');
    if (audio.src) URL.revokeObjectURL(audio.src);
    audio.src = '';
    $('uzIdle').classList.remove('hidden');
    $('uzReady').classList.add('hidden');
    $('searchEmpty').classList.remove('hidden');
    $('searchResults').classList.add('hidden');
    $('searchFile').value = '';
});

$('kSlider').addEventListener('input', () => {
    $('kVal').textContent = $('kSlider').value;
});

$('searchBtn').addEventListener('click', async () => {
    if (!searchFile) return;
    showOverlay('🔍 Đang phân tích âm thanh...');

    const form = new FormData();
    form.append('file', searchFile);
    form.append('k', $('kSlider').value);

    try {
        const data = await fetch(`${API}/api/search`, { method: 'POST', body: form }).then(r => r.json());
        hideOverlay();
        if (data.error) { alert(`❌ ${data.error}\n${data.hint || ''}`); return; }
        renderResults(data);
    } catch (e) {
        hideOverlay();
        alert(`❌ Lỗi: ${e.message}`);
    }
});

function renderResults(data) {
    // Show intermediate results FIRST
    renderIntermediate(data.query);

    $('searchResults').classList.remove('hidden');
    $('resultCount').textContent = `${data.results.length} kết quả`;

    // Query bar
    const q = data.query;
    $('queryBar').innerHTML = `
    <div class="qb-item"><div class="qb-val">${data.prediction || 'unknown'}</div><div class="qb-label">Nhạc cụ dự đoán</div></div>
    <div class="qb-item"><div class="qb-val">${data.predicted_pitch_note || q.dominant_note || 'unknown'}</div><div class="qb-label">Nốt ước lượng</div></div>
    <div class="qb-item"><div class="qb-val">${q.pitch_range || data.predicted_pitch_range || 'unknown'}</div><div class="qb-label">Âm vực</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.dominant_f0_hz, 2)} Hz</div><div class="qb-label">F0 (dominant)</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.duration)}s</div><div class="qb-label">Duration</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.spectral_centroid, 0)} Hz</div><div class="qb-label">Spectral Centroid</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.zcr, 4)}</div><div class="qb-label">ZCR</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.rms, 4)}</div><div class="qb-label">RMS</div></div>
    <div class="qb-item"><div class="qb-val">${fmt(q.onset_strength, 3)}</div><div class="qb-label">Onset Strength</div></div>
    <div class="qb-item" style="margin-left:auto;align-self:center;color:var(--muted);font-size:.78rem;">
      📂 <strong style="color:var(--white)">${q.filename}</strong>
    </div>
  `;

    // Cards
    const grid = $('resultGrid');
    grid.innerHTML = '';

    if (!data.results.length) {
        grid.innerHTML = '<p style="color:var(--muted);padding:1rem">Không tìm thấy kết quả. Hãy rebuild FAISS index.</p>';
        return;
    }

    data.results.forEach((r, i) => {
        const fam = r.instrument_family || 'unknown';
        const artCls = fam === 'bowed_string' ? 'bowed' : fam === 'plucked_string' ? 'plucked' : 'unknown';
        const famLabel = fam.replaceAll('_', ' ');
        const icon = instIcon(r.instrument);
        const delay = i * 0.06;

        const card = document.createElement('div');
        card.className = 'result-card';
        card.style.animationDelay = `${delay}s`;
        card.innerHTML = `
      <div class="rc-art ${artCls}">
        ${icon}
        <div class="rc-rank">#${r.rank}</div>
        <div class="rc-play" title="Phát / tạm dừng">▶</div>
      </div>
      <div class="rc-sim">${r.similarity}%</div>
      <div class="sim-bar"><div class="sim-fill" style="width:${r.similarity}%"></div></div>
      <div class="rc-name" title="${r.filename}">${r.filename || '–'}</div>
      <div class="rc-inst">${r.instrument} · ${famLabel}</div>
      <div class="rc-meta">🎼 ${r.labeled_note || 'unknown'}</div>
      <div class="rc-meta">⏱ ${fmt(r.duration)}s &nbsp;|&nbsp; 🔆 ${fmt(r.spectral_centroid, 0)} Hz</div>
      ${r._id ? `<audio class="rc-audio" src="${API}/api/audio/${r._id}"></audio>` : ''}
    `;
        // Wire up the play button to the hidden audio element
        if (r._id) {
            const playBtn = card.querySelector('.rc-play');
            const audioEl = card.querySelector('.rc-audio');
            playBtn.addEventListener('click', () => {
                if (audioEl.paused) {
                    // Pause any other playing cards first
                    document.querySelectorAll('.rc-audio').forEach(a => { if (a !== audioEl) { a.pause(); a.closest('.result-card').querySelector('.rc-play').textContent = '▶'; } });
                    audioEl.play();
                    playBtn.textContent = '⏸';
                } else {
                    audioEl.pause();
                    playBtn.textContent = '▶';
                }
            });
            audioEl.addEventListener('ended', () => { playBtn.textContent = '▶'; });
        }
        grid.appendChild(card);
    });
}

// ════════════════════════════════════════
//  TAB 2 – INGEST
// ════════════════════════════════════════
let ingestFiles = [];

setupDrop('ingestDropzone', 'ingestFile', files => {
    ingestFiles = files;
    $('izIdle').classList.add('hidden');
    $('ingestSelected').textContent = files.length === 1
        ? `✓ ${files[0].name}`
        : `✓ ${files.length} files đã chọn`;
    $('ingestSelected').classList.remove('hidden');
    $('ingestBtn').disabled = false;
});

$('ingestBtn').addEventListener('click', async () => {
    const instrument = $('instrumentName').value.trim();
    const family = $('instrumentFamily').value;
    if (!instrument) { alert('Vui lòng nhập tên nhạc cụ!'); return; }
    if (!ingestFiles.length) return;

    showOverlay(`Đang xử lý ${ingestFiles.length} file...`);
    for (const f of ingestFiles) {
        const form = new FormData();
        form.append('file', f);
        form.append('instrument', instrument);
        form.append('instrument_family', family);
        try {
            const d = await fetch(`${API}/api/ingest`, { method: 'POST', body: form }).then(r => r.json());
            if (d.status === 'OK') log(`✓ ${f.name} → ${d.instrument} (${d.duration}s)`, 'ok');
            else log(`✗ ${f.name}: ${d.error}`, 'err');
        } catch (e) { log(`✗ ${f.name}: ${e.message}`, 'err'); }
    }
    hideOverlay();
    log('💡 Nhớ nhấn "Rebuild Index" để cập nhật FAISS!', 'info');
    loadStats();
});

$('rebuildBtn').addEventListener('click', async () => {
    showOverlay('⚡ Đang rebuild FAISS index...');
    log('Đang rebuild FAISS index...', 'info');
    try {
        const d = await fetch(`${API}/api/index/build`, { method: 'POST' }).then(r => r.json());
        hideOverlay();
        if (d.status === 'OK') { log(`✓ Built: ${d.indexed_vectors} vectors`, 'ok'); loadStats(); }
        else log(`✗ ${d.error}`, 'err');
    } catch (e) { hideOverlay(); log(`✗ ${e.message}`, 'err'); }
});

// ════════════════════════════════════════
//  TAB 3 – DATABASE (with pagination – Fix #16)
// ════════════════════════════════════════
let allRecords = [];
let dbCurrentPage = 1;
let dbTotalPages = 1;
let dbPerPage = 50;
let dbFilterInst = '';

async function loadDatabase(page = 1) {
    $('dbTableBody').innerHTML = '<tr><td colspan="9" class="td-center">⏳ Đang tải...</td></tr>';
    try {
        let url = `${API}/api/records?page=${page}&per_page=${dbPerPage}`;
        if (dbFilterInst) url += `&instrument=${encodeURIComponent(dbFilterInst)}`;
        const data = await fetch(url).then(r => r.json());
        allRecords = data.records || [];
        dbCurrentPage = data.page || 1;
        dbTotalPages = data.total_pages || 1;
        renderTable(allRecords, (dbCurrentPage - 1) * dbPerPage);
        renderBadges(data.total || allRecords.length);
        renderPagination();
    } catch {
        $('dbTableBody').innerHTML = '<tr><td colspan="9" class="td-center" style="color:#e22134">Lỗi tải dữ liệu</td></tr>';
    }
}

function renderPagination() {
    let container = $('dbPagination');
    if (!container) {
        container = document.createElement('div');
        container.id = 'dbPagination';
        container.className = 'db-pagination';
        const tableWrap = document.querySelector('.sp-table-wrap');
        tableWrap.parentNode.insertBefore(container, tableWrap.nextSibling);
    }
    container.innerHTML = `
        <button class="sp-btn sp-btn--ghost sp-btn--sm" ${dbCurrentPage <= 1 ? 'disabled' : ''} id="dbPrevPage">← Trước</button>
        <span class="db-page-info">Trang ${dbCurrentPage} / ${dbTotalPages}</span>
        <button class="sp-btn sp-btn--ghost sp-btn--sm" ${dbCurrentPage >= dbTotalPages ? 'disabled' : ''} id="dbNextPage">Tiếp →</button>
    `;
    const prev = $('dbPrevPage');
    const next = $('dbNextPage');
    if (prev) prev.addEventListener('click', () => loadDatabase(dbCurrentPage - 1));
    if (next) next.addEventListener('click', () => loadDatabase(dbCurrentPage + 1));
}

function renderBadges(total) {
    // Use a separate API call to get instrument counts for badges
    fetch(`${API}/api/instruments`).then(r => r.json()).then(data => {
        const container = $('instrumentBadges');
        container.innerHTML =
            `<span class="inst-badge ${!dbFilterInst ? 'active' : ''}" data-inst="">Tất cả</span>` +
            (data.instruments || []).map(inst =>
                `<span class="inst-badge ${dbFilterInst === inst ? 'active' : ''}" data-inst="${inst}">${inst}</span>`
            ).join('');

        container.querySelectorAll('.inst-badge').forEach(badge => {
            badge.addEventListener('click', () => {
                dbFilterInst = badge.dataset.inst;
                loadDatabase(1);
            });
        });
    }).catch(() => {});
}

function renderTable(records, startIdx = 0) {
    if (!records.length) {
        $('dbTableBody').innerHTML = '<tr><td colspan="9" class="td-center">Chưa có dữ liệu trong CSDL</td></tr>';
        return;
    }
    $('dbTableBody').innerHTML = records.map((r, i) => `
    <tr>
      <td style="color:var(--muted)">${startIdx + i + 1}</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.filename}">${r.filename || '–'}</td>
      <td><strong style="color:var(--green)">${r.instrument || '–'}</strong></td>
      <td style="color:var(--muted);font-size:.75rem">${(r.instrument_family || '–').replaceAll('_', ' ')}</td>
      <td>${fmt(r.duration)}s</td>
      <td>${fmt(r.spectral_centroid, 0)} Hz</td>
      <td>${fmt(r.zcr, 5)}</td>
      <td>${fmt(r.rms, 5)}</td>
      <td style="color:var(--muted);font-size:.75rem">${r.created_at ? new Date(r.created_at).toLocaleDateString('vi-VN') : '–'}</td>
    </tr>
  `).join('');
}

$('dbFilter').addEventListener('input', function () {
    dbFilterInst = this.value.toLowerCase();
    loadDatabase(1);
});

$('refreshDbBtn').addEventListener('click', () => loadDatabase(1));

// ════════════════════════════════════════
//  TAB 4 – EVALUATE
// ════════════════════════════════════════
$('evalBtn').addEventListener('click', async () => {
    showOverlay('📊 Đang tính Precision...');
    try {
        const d = await fetch(`${API}/api/evaluate`, { method: 'POST' }).then(r => r.json());
        hideOverlay();
        if (d.error) { alert(`❌ ${d.error}`); return; }

        $('evalResults').classList.remove('hidden');
        $('evalScore').textContent = `${d.overall_precision_at_5}%`;

        $('evalBreakdown').innerHTML = Object.entries(d.per_instrument || {})
            .sort((a, b) => b[1] - a[1])
            .map(([inst, score]) => `
        <div class="eval-card">
          <div class="eval-card-inst">${inst}</div>
          <div class="eval-card-score ${scoreColorClass(score)}">${score}%</div>
        </div>`)
            .join('');

        // Render confusion matrix
        renderConfusionMatrix(d.confusion_matrix || {});
    } catch (e) {
        hideOverlay();
        alert(`❌ Lỗi: ${e.message}`);
    }
});

// ════════════════════════════════════════
//  INTERMEDIATE RESULTS
// ════════════════════════════════════════
function renderIntermediate(q) {
    $('intermediatePanel').classList.remove('hidden');

    // ── MFCC Bar Chart (Canvas) ──
    const canvas = $('mfccChart');
    const ctx = canvas.getContext('2d');
    const mfcc = q.mfcc_mean || [];
    const W = canvas.width, H = canvas.height;
    const barW = Math.max(1, Math.floor(W / mfcc.length));
    const maxVal = Math.max(...mfcc.map(Math.abs), 1);

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d1b2e';
    ctx.fillRect(0, 0, W, H);

    const midY = H / 2;
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, midY); ctx.lineTo(W, midY); ctx.stroke();

    mfcc.forEach((v, i) => {
        const barH = (Math.abs(v) / maxVal) * (midY - 6);
        const x = i * barW + 1;
        const isPos = v >= 0;
        const grad = ctx.createLinearGradient(0, isPos ? midY - barH : midY, 0, isPos ? midY : midY + barH);
        grad.addColorStop(0, isPos ? '#7e57c2' : '#ef5350');
        grad.addColorStop(1, isPos ? '#4a2080' : '#8b2020');
        ctx.fillStyle = grad;
        ctx.fillRect(x, isPos ? midY - barH : midY, barW - 2, barH);
        if (i % 5 === 0) {
            ctx.fillStyle = '#556677';
            ctx.font = '8px Inter,sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(`c${i + 1}`, x + barW / 2, H - 2);
        }
    });

    // ── Feature Table ──
    const rows = [
        ['Duration', `${fmt(q.duration)} s`],
        ['Sample Rate', `${q.sample_rate || 22050} Hz`],
        ['Dominant Note', `${q.dominant_note || 'unknown'}`],
        ['Dominant F0', `${fmt(q.dominant_f0_hz, 2)} Hz`],
        ['Pitch Range', `${q.pitch_range || 'unknown'}`],
        ['Spectral Centroid', `${fmt(q.spectral_centroid, 0)} Hz`],
        ['ZCR', fmt(q.zcr, 5)],
        ['RMS Energy', fmt(q.rms, 5)],
        ['Onset Strength', fmt(q.onset_strength, 4)],
        ['Feature Dim', `${(q.feature_vector || []).length}d`],
    ];
    $('featTable').innerHTML =
        `<thead><tr><th>Tham số</th><th>Giá trị</th></tr></thead>` +
        `<tbody>${rows.map(([k, v]) => `<tr><td>${k}</td><td style="color:var(--green);font-family:monospace">${v}</td></tr>`).join('')}</tbody>`;
}

// ════════════════════════════════════════
//  CONFUSION MATRIX RENDERER
// ════════════════════════════════════════
function renderConfusionMatrix(cm) {
    const container = $('confusionMatrix');
    if (!cm || !Object.keys(cm).length) {
        container.innerHTML = '<p style="color:var(--muted)">Chưa có dữ liệu confusion matrix.</p>';
        return;
    }
    const instruments = [...new Set([
        ...Object.keys(cm),
        ...Object.values(cm).flatMap(row => Object.keys(row))
    ])].sort();

    let html = '<table class="cf-table"><thead><tr><th>Actual \\ Pred</th>';
    instruments.forEach(c => { html += `<th>${c}</th>`; });
    html += '</tr></thead><tbody>';

    instruments.forEach(actual => {
        html += `<tr><th>${actual}</th>`;
        const rowMax = Math.max(...instruments.map(p => (cm[actual] || {})[p] || 0), 1);
        instruments.forEach(pred => {
            const count = (cm[actual] || {})[pred] || 0;
            const heat = Math.round((count / rowMax) * 100);
            const isDiag = actual === pred;
            html += `<td style="background:rgba(${isDiag ? '100,200,100' : '200,80,80'},${heat / 100 * 0.7});color:${count ? '#fff' : 'var(--muted)'};">${count || '–'}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

// ════════════════════════════════════════
//  BOOT
// ════════════════════════════════════════
document.addEventListener('DOMContentLoaded', initApp);
