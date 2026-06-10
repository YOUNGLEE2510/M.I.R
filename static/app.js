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
    if (['sitar', 'dan_tranh', 'dan_ty_ba', 'dan_bau'].some(x => name.includes(x))) return '🎶';
    return '♪';
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
        if (btn.dataset.tab === 'evaluate') renderEvaluation();
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

$('searchBtn').addEventListener('click', async () => {
    if (!searchFile) return;
    showOverlay('🔍 Đang phân tích âm thanh...');

    const form = new FormData();
    form.append('file', searchFile);
    form.append('k', 5);

    try {
        const data = await fetch(`${API}/api/search`, { method: 'POST', body: form }).then(r => r.json());
        hideOverlay();
        if (data.error) { alert(`❌ ${data.error}\n${data.hint || ''}`); return; }
        lastSearchResult = data;
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
      <button class="rc-detail-btn" title="Xem chi tiết" style="width: 100%; margin-top: 10px; padding: 6px 0; background: transparent; border: 1px solid rgba(255,255,255,0.1); border-radius: var(--radius-sm); color: var(--muted); font-family: var(--font); font-size: 0.75rem; font-weight: 600; cursor: pointer; transition: var(--trans); letter-spacing: 0.3px;">📄 Chi tiết</button>
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
        // Detail button → open drawer
        card.querySelector('.rc-detail-btn').addEventListener('click', () => {
            openDetailDrawer(r._id, { similarity: r.similarity, family: fam });
        });
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
    let successCount = 0;
    for (const f of ingestFiles) {
        const form = new FormData();
        form.append('file', f);
        form.append('instrument', instrument);
        form.append('instrument_family', family);
        try {
            const d = await fetch(`${API}/api/ingest`, { method: 'POST', body: form }).then(r => r.json());
            if (d.status === 'OK') {
                log(`✓ ${f.name} → ${d.instrument} (${d.duration}s)`, 'ok');
                successCount++;
            }
            else log(`✗ ${f.name}: ${d.error}`, 'err');
        } catch (e) { log(`✗ ${f.name}: ${e.message}`, 'err'); }
    }
    
    if (successCount > 0) {
        log('⚡ Đang tự động xây dựng lại chỉ mục FAISS...', 'info');
        try {
            const d = await fetch(`${API}/api/index/build`, { method: 'POST' }).then(r => r.json());
            if (d.status === 'OK') {
                log(`✓ Đã cập nhật chỉ mục: ${d.indexed_vectors} vectors`, 'ok');
            } else {
                log(`✗ Lỗi rebuild: ${d.error}`, 'err');
            }
        } catch (e) {
            log(`✗ Lỗi rebuild: ${e.message}`, 'err');
        }
    }
    
    hideOverlay();
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
    $('dbTableBody').innerHTML = '<tr><td colspan="10" class="td-center">⏳ Đang tải...</td></tr>';
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
        $('dbTableBody').innerHTML = '<tr><td colspan="10" class="td-center" style="color:#e22134">Lỗi tải dữ liệu</td></tr>';
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
        $('dbTableBody').innerHTML = '<tr><td colspan="10" class="td-center">Chưa có dữ liệu trong CSDL</td></tr>';
        return;
    }
    $('dbTableBody').innerHTML = records.map((r, i) => `
    <tr class="db-row" data-id="${r._id || ''}">
      <td style="color:var(--muted)">${startIdx + i + 1}</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.filename}">${r.filename || '–'}</td>
      <td><strong style="color:var(--green)">${r.instrument || '–'}</strong></td>
      <td style="color:var(--muted);font-size:.75rem">${(r.instrument_family || '–').replaceAll('_', ' ')}</td>
      <td>${fmt(r.duration)}s</td>
      <td>${fmt(r.spectral_centroid, 0)} Hz</td>
      <td>${fmt(r.zcr, 5)}</td>
      <td>${fmt(r.rms, 5)}</td>
      <td style="color:var(--muted);font-size:.75rem">${r.created_at ? new Date(r.created_at).toLocaleDateString('vi-VN') : '–'}</td>
      <td>
        <button class="sp-btn sp-btn--ghost sp-btn--sm db-view-btn" style="padding: 3px 8px; font-size: 0.75rem;">📄 Chi tiết</button>
      </td>
    </tr>
  `).join('');

    // Bind event listeners to details buttons
    document.querySelectorAll('.db-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const row = btn.closest('.db-row');
            const recordId = row.dataset.id;
            if (recordId) openDetailDrawer(recordId);
        });
    });
}

$('dbFilter').addEventListener('input', function () {
    dbFilterInst = this.value.toLowerCase();
    loadDatabase(1);
});

$('refreshDbBtn').addEventListener('click', () => loadDatabase(1));

// ════════════════════════════════════════
//  TAB 4 – EVALUATE & EXPLAINABLE SEARCH
// ════════════════════════════════════════
let lastSearchResult = null;

function renderEvaluation() {
    const emptyState = $('eval-empty-state');
    const contentState = $('eval-content-state');

    if (!lastSearchResult) {
        emptyState.classList.remove('hidden');
        contentState.classList.add('hidden');
        return;
    }

    emptyState.classList.add('hidden');
    contentState.classList.remove('hidden');

    const q = lastSearchResult.query;
    const results = lastSearchResult.results;

    // ── 1. Vẽ bảng so sánh đặc trưng ──
    const compareTable = $('evalCompareTable');
    let tableHtml = `
        <thead>
            <tr>
                <th>Thuộc tính vật lý</th>
                <th style="background: rgba(29, 185, 84, 0.05)">Query (${q.filename})</th>
    `;
    results.forEach(r => {
        tableHtml += `<th>Top ${r.rank} (${r.instrument})</th>`;
    });
    tableHtml += `
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><strong>Nhạc cụ (Gán nhãn)</strong></td>
                <td style="color:var(--green)">${lastSearchResult.prediction || 'unknown'} (Dự đoán)</td>
    `;
    results.forEach(r => {
        tableHtml += `<td><strong style="color:var(--green)">${r.instrument}</strong></td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Họ nhạc cụ</strong></td>
                <td>${(q.pitch_range === 'low' ? 'Bowed String' : 'String')}</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${(r.instrument_family || '–').replaceAll('_', ' ')}</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Nốt nhạc</strong></td>
                <td>${q.dominant_note || 'unknown'}</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${r.labeled_note || 'unknown'}</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Thời lượng</strong></td>
                <td>${fmt(q.duration)} s</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${fmt(r.duration)} s</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Spectral Centroid (Đo độ sáng)</strong></td>
                <td>${fmt(q.spectral_centroid, 0)} Hz</td>
    `;
    results.forEach(r => {
        const pctDiff = q.spectral_centroid ? Math.abs(r.spectral_centroid - q.spectral_centroid) / q.spectral_centroid * 100 : 0;
        tableHtml += `<td>${fmt(r.spectral_centroid, 0)} Hz <br><small style="color:var(--muted)">(${fmt(pctDiff, 1)}% lệch)</small></td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>ZCR (Tỉ lệ qua điểm 0)</strong></td>
                <td>${fmt(q.zcr, 5)}</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${fmt(r.zcr, 5)}</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>RMS Energy (Cường độ)</strong></td>
                <td>${fmt(q.rms, 5)}</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${fmt(r.rms, 5)}</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Onset Strength (Attack)</strong></td>
                <td>${fmt(q.onset_strength, 4)}</td>
    `;
    results.forEach(r => {
        tableHtml += `<td>${fmt(r.onset_strength, 4)}</td>`;
    });
    tableHtml += `</tr><tr>
                <td><strong>Độ tương đồng toàn cục</strong></td>
                <td style="background: rgba(29, 185, 84, 0.05)">-</td>
    `;
    results.forEach(r => {
        tableHtml += `<td style="color:var(--green);font-size:1.1rem;font-weight:800">${r.similarity}%</td>`;
    });
    tableHtml += `
        </tbody>
    `;
    compareTable.innerHTML = tableHtml;

    // ── 2. Cập nhật Dropdown chọn kết quả phân tích vector ──
    const selector = $('evalSelectResult');
    selector.innerHTML = results.map((r, i) => `
        <option value="${i}">Top ${r.rank}: ${r.filename.slice(0, 30)}... (${r.similarity}%)</option>
    `).join('');

    // Bật listener change
    selector.onchange = () => {
        renderDetailAnalysis(Number(selector.value));
    };

    // Vẽ phân tích chi tiết của kết quả đầu tiên (Top 1) mặc định
    renderDetailAnalysis(0);
}

function renderDetailAnalysis(idx) {
    const data = lastSearchResult;
    const q = data.query;
    const r = data.results[idx];

    const q_vec = q.feature_vector || [];
    const r_vec = r.feature_vector || [];

    if (!q_vec.length || !r_vec.length) {
        $('evalContributionBars').innerHTML = '<p style="color:var(--muted)">Không có dữ liệu vector để phân tích.</p>';
        return;
    }

    // Tích vô hướng từng chiều: P_i = Q_i * R_i
    const prods = q_vec.map((qv, i) => qv * (r_vec[i] || 0));

    // Tính toán theo các nhóm chiều đặc trưng đã định nghĩa ở extractor.py
    // - MFCC Mean: 0 -> 39
    // - MFCC Std: 40 -> 79
    // - Chroma: 80 -> 91
    // - Spectral: 92 -> 95 (Centroid 2d + Rolloff 1d + Flux 1d)
    // - Dynamics: 96 -> 99 (ZCR 1d + RMS 1d + HNR 1d + Onset 1d)
    
    let mfccContrib = 0;
    for (let i = 0; i < 80; i++) mfccContrib += prods[i] || 0;

    let chromaContrib = 0;
    for (let i = 80; i < 92; i++) chromaContrib += prods[i] || 0;

    let spectralContrib = 0;
    for (let i = 92; i < 96; i++) spectralContrib += prods[i] || 0;

    let dynamicsContrib = 0;
    for (let i = 96; i < 100; i++) dynamicsContrib += prods[i] || 0;

    // Chuẩn hóa điểm đóng góp (tránh điểm âm làm hỏng phần trăm trực quan)
    const mfccScore = Math.max(0, mfccContrib);
    const chromaScore = Math.max(0, chromaContrib);
    const spectralScore = Math.max(0, spectralContrib);
    const dynamicsScore = Math.max(0, dynamicsContrib);
    const sumScore = mfccScore + chromaScore + spectralScore + dynamicsScore || 1;

    const mfccPct = (mfccScore / sumScore) * 100;
    const chromaPct = (chromaScore / sumScore) * 100;
    const spectralPct = (spectralScore / sumScore) * 100;
    const dynamicsPct = (dynamicsScore / sumScore) * 100;

    // Render thanh tiến trình đóng góp
    $('evalContributionBars').innerHTML = `
        <div class="contribution-bar">
            <div class="c-bar-info">
                <span class="c-bar-label">🎸 Âm sắc & Nhận diện (MFCC Mean/Std - 80d)</span>
                <span class="c-bar-val">${fmt(mfccPct, 1)}% (${fmt(mfccContrib, 3)})</span>
            </div>
            <div class="c-bar-track"><div class="c-bar-fill mfcc" style="width: ${mfccPct}%"></div></div>
        </div>
        <div class="contribution-bar">
            <div class="c-bar-info">
                <span class="c-bar-label">🎹 Hài âm & Tần số cơ bản (Chroma - 12d)</span>
                <span class="c-bar-val">${fmt(chromaPct, 1)}% (${fmt(chromaContrib, 3)})</span>
            </div>
            <div class="c-bar-track"><div class="c-bar-fill chroma" style="width: ${chromaPct}%"></div></div>
        </div>
        <div class="contribution-bar">
            <div class="c-bar-info">
                <span class="c-bar-label">🔆 Tần số phổ & Độ sáng (Centroid, Rolloff, Flux - 4d)</span>
                <span class="c-bar-val">${fmt(spectralPct, 1)}% (${fmt(spectralContrib, 3)})</span>
            </div>
            <div class="c-bar-track"><div class="c-bar-fill spectral" style="width: ${spectralPct}%"></div></div>
        </div>
        <div class="contribution-bar">
            <div class="c-bar-info">
                <span class="c-bar-label">⏱ Động lực học & Thời gian (ZCR, RMS, HNR, Onset - 4d)</span>
                <span class="c-bar-val">${fmt(dynamicsPct, 1)}% (${fmt(dynamicsContrib, 3)})</span>
            </div>
            <div class="c-bar-track"><div class="c-bar-fill dynamics" style="width: ${dynamicsPct}%"></div></div>
        </div>
    `;
}

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
//  BOOT
// ════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

// ════════════════════════════════════════
//  DETAIL DRAWER
// ════════════════════════════════════════
const drawer   = $('detailDrawer');
const backdrop = $('detailBackdrop');
let currentDrawerRecordId = null;

function openDetailDrawer(recordId, ctx = {}) {
    currentDrawerRecordId = recordId;

    // Pause any playing card audio to avoid overlapping sound
    document.querySelectorAll('.rc-audio').forEach(a => {
        a.pause();
        const card = a.closest('.result-card');
        if (card) {
            const playBtn = card.querySelector('.rc-play');
            if (playBtn) playBtn.textContent = '▶';
        }
    });

    // Show drawer immediately with loading state
    $('ddFname').textContent = 'Đang tải...';
    $('ddInst').textContent  = '';
    $('ddIcon').className    = 'dd-icon';
    $('ddIcon').textContent  = '♪';
    $('ddTable').innerHTML   = '<tr><td colspan="2" style="color:var(--muted);padding:24px 0;text-align:center">⏳ Đang tải dữ liệu...</td></tr>';
    $('ddVecWrap').innerHTML = '';
    $('ddAudio').src = '';

    // Similarity row
    const simRow = $('ddSimRow');
    if (ctx.similarity != null) {
        simRow.classList.remove('hidden');
        $('ddSimVal').textContent = `${ctx.similarity}%`;
        setTimeout(() => { $('ddSimFill').style.width = `${ctx.similarity}%`; }, 50);
    } else {
        simRow.classList.add('hidden');
        $('ddSimFill').style.width = '0%';
    }

    backdrop.classList.remove('hidden');
    drawer.classList.add('open');
    document.body.style.overflow = 'hidden';

    if (!recordId) { return; }

    // Fetch full record
    fetch(`${API}/api/records/${recordId}`)
        .then(r => r.json())
        .then(doc => renderDrawer(doc, ctx))
        .catch(() => {
            $('ddTable').innerHTML = '<tr><td colspan="2" style="color:#e22134;padding:16px 0">Không tải được dữ liệu</td></tr>';
        });
}

function closeDetailDrawer() {
    drawer.classList.remove('open');
    backdrop.classList.add('hidden');
    document.body.style.overflow = '';
    // Stop audio
    const audio = $('ddAudio');
    audio.pause();
    audio.src = '';
    currentDrawerRecordId = null;
}

$('ddClose').addEventListener('click', closeDetailDrawer);
backdrop.addEventListener('click', closeDetailDrawer);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetailDrawer(); });

function renderDrawer(doc, ctx) {
    // ── Header ──────────────────────────────────────────────
    const fam   = doc.instrument_family || 'unknown';
    const icon  = instIcon(doc.instrument || '');
    $('ddFname').textContent = doc.filename || '–';
    $('ddInst').textContent  = `${doc.instrument || '–'} · ${(fam).replaceAll('_', ' ')}`;
    $('ddIcon').textContent  = icon;
    $('ddIcon').className    = `dd-icon ${fam === 'plucked_string' ? 'plucked' : ''}`;

    // ── Audio ────────────────────────────────────────────────
    if (doc._id) {
        $('ddAudio').src = `${API}/api/audio/${doc._id}`;
    }

    // ── MFCC Chart ───────────────────────────────────────────
    const mfcc = doc.mfcc_mean || [];
    if (mfcc.length) {
        const canvas = $('ddMfccChart');
        const ctx2   = canvas.getContext('2d');
        const W = canvas.offsetWidth || 360;
        const H = 90;
        canvas.width  = W;
        canvas.height = H;
        const barW  = Math.max(1, Math.floor(W / mfcc.length));
        const maxV  = Math.max(...mfcc.map(Math.abs), 1);
        const midY  = H / 2;

        ctx2.clearRect(0, 0, W, H);
        ctx2.fillStyle = '#0d1b2e';
        ctx2.fillRect(0, 0, W, H);

        ctx2.strokeStyle = '#2a3a4a';
        ctx2.lineWidth = 1;
        ctx2.beginPath(); ctx2.moveTo(0, midY); ctx2.lineTo(W, midY); ctx2.stroke();

        mfcc.forEach((v, i) => {
            const barH = (Math.abs(v) / maxV) * (midY - 4);
            const x    = i * barW + 1;
            const isPos = v >= 0;
            const grad  = ctx2.createLinearGradient(0, isPos ? midY - barH : midY, 0, isPos ? midY : midY + barH);
            grad.addColorStop(0, isPos ? '#7e57c2' : '#ef5350');
            grad.addColorStop(1, isPos ? '#4a2080' : '#8b2020');
            ctx2.fillStyle = grad;
            ctx2.fillRect(x, isPos ? midY - barH : midY, barW - 2, barH);
        });
    }

    // ── Feature Table ────────────────────────────────────────
    const rows = [
        ['Tên file',            doc.filename || '–'],
        ['Nhạc cụ',             `<span class="dd-tag">${doc.instrument || '–'}</span>`],
        ['Họ nhạc cụ',          (fam).replaceAll('_', ' ')],
        ['Nốt gán nhãn',        doc.labeled_note || 'unknown'],
        ['Nốt ước lượng (F0)',  doc.dominant_note || 'unknown'],
        ['Dominant F0',         doc.dominant_f0_hz != null ? `${fmt(doc.dominant_f0_hz, 2)} Hz` : '–'],
        ['Âm vực',              doc.pitch_range || 'unknown'],
        ['Duration',            doc.duration != null ? `${fmt(doc.duration)} s` : '–'],
        ['Sample Rate',         doc.sample_rate != null ? `${doc.sample_rate} Hz` : '–'],
        ['Spectral Centroid',   doc.spectral_centroid != null ? `${fmt(doc.spectral_centroid, 1)} Hz` : '–'],
        ['ZCR',                 doc.zcr != null ? fmt(doc.zcr, 5) : '–'],
        ['RMS Energy',          doc.rms != null ? fmt(doc.rms, 5) : '–'],
        ['Onset Strength',      doc.onset_strength != null ? fmt(doc.onset_strength, 4) : '–'],
        ['Feature Dim',         (doc.feature_vector || []).length ? `${doc.feature_vector.length}D` : '–'],
        ['Ngày thêm',           doc.created_at ? new Date(doc.created_at).toLocaleString('vi-VN') : '–'],
        ['FAISS index',         doc.faiss_index != null ? doc.faiss_index : '–'],
    ];

    $('ddTable').innerHTML = rows.map(([k, v]) =>
        `<tr><td>${k}</td><td>${v}</td></tr>`
    ).join('');

    // ── Feature Vector chips ─────────────────────────────────
    const vec    = doc.feature_vector || [];
    const SHOW   = 30;
    const chips  = vec.slice(0, SHOW).map((v, i) =>
        `<span class="dd-vec-chip" title="dim ${i}">${Number(v).toFixed(3)}</span>`
    ).join('');
    const more   = vec.length > SHOW
        ? `<span class="dd-vec-more">+${vec.length - SHOW} more</span>`
        : '';
    $('ddVecWrap').innerHTML = chips + more;
}

// ── Bind Delete button inside Detail Drawer ──
$('ddDeleteBtn').addEventListener('click', async () => {
    if (!currentDrawerRecordId) return;
    const ok = confirm("Bạn có chắc chắn muốn xóa bản ghi này khỏi cơ sở dữ liệu và đĩa cứng không?");
    if (!ok) return;

    showOverlay('🗑 Đang xóa bản ghi...');
    try {
        const res = await fetch(`${API}/api/records/${currentDrawerRecordId}`, { method: 'DELETE' }).then(r => r.json());
        hideOverlay();
        if (res.deleted) {
            closeDetailDrawer();
            // Refresh database view if active
            if ($('tab-database').classList.contains('active')) {
                loadDatabase(dbCurrentPage);
            }
            loadStats();
            alert("✓ Đã xóa bản ghi thành công.");
        } else {
            alert(`✗ Không thể xóa: ${res.error}`);
        }
    } catch (e) {
        hideOverlay();
        alert(`✗ Lỗi khi xóa: ${e.message}`);
    }
});

