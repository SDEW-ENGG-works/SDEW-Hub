// Get data: Tally pull, Fetch GRIN (shared with the Supplementary Bill), payment files.

let _tallyTimer = null, _grinTimer = null;

async function loadSources() {
    try {
        const s = await api('/api/grin/sources');
        const t = s.tally;
        document.getElementById('tally-kv').innerHTML = `
            <dt>Tally server</dt><dd>${esc(t.url)}</dd>
            <dt>Companies</dt><dd>${t.companies.length ? esc(t.companies.map(c => c.name + (c.location ? ` (${c.location})` : '')).join(', ')) : 'the company open in Tally'}</dd>
            <dt>Pulled from Tally</dt><dd>${t.n ? `${inr(t.n, 0)} invoices, ${dmy(t.first)} to ${dmy(t.last)} · ${esc(when(t.pulled))}` : 'not yet'}</dd>
            <dt>Sales Register upload</dt><dd>${s.sales.n ? `${inr(s.sales.n, 0)} TAFE invoices, ${dmy(s.sales.first)} to ${dmy(s.sales.last)}` : 'none'}</dd>`;
        showTally(t.status);
        const g = s.grin;
        document.getElementById('grin-kv').innerHTML = `
            <dt>GRIN loaded</dt><dd>${g.n ? `${inr(g.n, 0)} GRINs for ${inr(g.invoices, 0)} invoices` : 'none'}</dd>
            <dt>GRIN dates</dt><dd>${g.first ? `${dmy(g.first)} to <b>${dmy(g.last)}</b>` : '—'}</dd>
            <dt>Last fetched</dt><dd>${esc(when(g.updated)) || '—'}</dd>`;
        showGrin(g.portal);
        document.getElementById('pay-kv').innerHTML = `
            <dt>TAFE payment lines</dt><dd>${s.payments.n ? `${inr(s.payments.n, 0)} lines in ${s.payments.vouchers} vouchers, ${dmy(s.payments.first)} to <b>${dmy(s.payments.last)}</b>` : 'none — drop a PaymentDetailsExport'}</dd>
            <dt>Invoice register</dt><dd>${s.register.n ? `${inr(s.register.n, 0)} invoices, ${inr(s.register.marked, 0)} marked paid (up to ${dmy(s.register.last)})` : 'none — optional, gives invoice values and older payments'}</dd>`;
        document.getElementById('pay-files').innerHTML = s.files.length ? s.files.map(f => `<tr><td>${esc(when(f.loaded_at))}</td>
            <td><span class="status-badge sent">${esc(f.kind)}</span></td><td>${esc(f.name)}</td>
            <td>${dmy(f.period_from)} – ${dmy(f.period_to)}</td><td class="num">${inr(f.rows, 0)}</td></tr>`).join('')
            : `<tr><td colspan="5" class="muted-cell">No payment files yet</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function showLog(id, lines) {
    const el = document.getElementById(id);
    if (lines && lines.length) {
        el.style.display = '';
        el.textContent = lines.join('\n');
        el.scrollTop = el.scrollHeight;
    }
}

function showTally(st) {
    const b = document.getElementById('tally-badge');
    if (st.running) { b.className = 'status-badge sent'; b.textContent = 'Reading Tally…'; }
    else if (st.error) { b.className = 'status-badge inactive'; b.textContent = 'Last pull stopped'; }
    else if (st.finished) { b.className = 'status-badge active'; b.textContent = `Last pull ${when(st.finished)}`; }
    else { b.className = 'status-badge muted'; b.textContent = 'Ready'; }
    showLog('tally-log', st.error ? [...st.log] : st.log);
    document.getElementById('btn-tally').disabled = !!st.running;
}

function showGrin(st) {
    const b = document.getElementById('grin-badge');
    if (!st.available) { b.className = 'status-badge warn'; b.textContent = 'Playwright not installed'; }
    else if (st.running) { b.className = 'status-badge sent'; b.textContent = 'Fetching…'; }
    else if (st.error) { b.className = 'status-badge inactive'; b.textContent = 'Last fetch stopped'; }
    else { b.className = 'status-badge active'; b.textContent = st.finished ? `Last fetch ${when(st.finished)}` : 'Ready'; }
    showLog('grin-log', st.log);
    document.getElementById('btn-grin').disabled = !!st.running;
}

async function tallyTest() {
    try {
        const r = await apiJson('/api/grin/tally/test', 'POST', {});
        showToast(`Tally answered. Companies open: <b>${esc(r.companies.join(', ') || 'none')}</b>`, 'success', 7000);
    } catch (e) {
        showToast(e.message, 'danger', 9000);
    }
}

async function tallyPull() {
    try {
        await apiJson('/api/grin/tally/pull', 'POST', {
            from: document.getElementById('tally-from').value, to: document.getElementById('tally-to').value });
        pollTally();
    } catch (e) {
        showToast(e.message, 'danger', 8000);
    }
}

function pollTally() {
    clearInterval(_tallyTimer);
    _tallyTimer = setInterval(async () => {
        try {
            const st = await api('/api/grin/tally/pull');
            showTally(st);
            if (!st.running) {
                clearInterval(_tallyTimer);
                if (st.error) showToast(esc(st.error), 'danger', 9000);
                else showToast(`Tally: ${st.result ? st.result.invoices : 0} TAFE invoices read`, 'success');
                loadSources();
                loadStatus(0);
            }
        } catch (e) { clearInterval(_tallyTimer); }
    }, 1500);
}

async function grinFetch() {
    document.getElementById('btn-grin').disabled = true;
    showToast('Fetching GRIN from TAFE Channel…', 'info');
    try {
        const r = await apiJson('/api/supp/grin/sync', 'POST', {
            from: document.getElementById('grin-from').value, to: document.getElementById('grin-to').value,
            headed: document.getElementById('grin-headed').checked });
        if (r.done) {           // website: the fetch already ran inside the request
            showGrin(Object.assign({ available: true }, r));
            showToast(r.error ? esc(r.error) : 'GRIN fetched', r.error ? 'danger' : 'success', 9000);
            loadSources();
            loadStatus(0);
            return;
        }
        pollGrin();
    } catch (e) {
        document.getElementById('btn-grin').disabled = false;
        showToast(e.message, 'danger', 8000);
    }
}

function pollGrin() {
    clearInterval(_grinTimer);
    _grinTimer = setInterval(async () => {
        try {
            const st = await api('/api/supp/grin/sync');
            showGrin(Object.assign({ available: true }, st));
            if (!st.running) {
                clearInterval(_grinTimer);
                if (st.error) showToast(esc(st.error), 'danger', 9000);
                else showToast('GRIN fetched', 'success');
                loadSources();
                loadStatus(0);
            }
        } catch (e) { clearInterval(_grinTimer); }
    }, 2000);
}

async function uploadFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const box = document.getElementById('upload-results');
    box.innerHTML = '';
    for (const f of files) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        try {
            const r = await api(`/api/grin/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = r.kind;
            row.querySelector('.msg').textContent = r.message;
        } catch (e) {
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.message;
        }
    }
    document.getElementById('file-input').value = '';
    loadSources();
    loadStatus(0);
}

function initDropzone() {
    const dz = document.getElementById('dropzone');
    ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
    dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files));
}
