// Get data: Tally pull, Fetch GRIN (shared with the Supplementary Bill), payment files.

let _tallyTimer = null, _grinTimer = null;

async function loadSources(keepTallyLog) {
    try {
        const s = await api('/api/grin/sources');
        const t = s.tally;
        document.getElementById('tally-kv').innerHTML = `
            <dt>Tally server</dt><dd>${esc(t.url)}</dd>
            <dt>Companies</dt><dd>${t.companies.length ? esc(t.companies.map(c => c.name + (c.location ? ` (${c.location})` : '')).join(', ')) : 'the company open in Tally'}</dd>
            <dt>Pulled from Tally</dt><dd>${t.n ? `${inr(t.n, 0)} invoices, ${dmy(t.first)} to ${dmy(t.last)} · ${esc(when(t.pulled))}` : 'not yet'}</dd>
            <dt>Sales Register upload</dt><dd>${s.sales.n ? `${inr(s.sales.n, 0)} TAFE invoices, ${dmy(s.sales.first)} to ${dmy(s.sales.last)}` : 'none'}</dd>
            `;
        if (!keepTallyLog) showTally(t.status);
        if (ON_SITE) bridgePing().then(p => {
            const kv = document.getElementById('tally-kv');
            kv.insertAdjacentHTML('beforeend', `<dt>This computer</dt><dd>${p
                ? (p.tally_ok ? `<span class="status-badge active">Tally bridge on</span> ${esc(p.host)} - ${esc((p.companies || []).join(', ') || 'no company open')}`
                    : `<span class="status-badge warn">Bridge on, Tally not answering</span> ${esc(p.host)}`)
                : `<span class="status-badge inactive">Tally bridge off</span> <a href="${BRIDGE_DL}" download>download SDEW-Tally-Bridge.exe</a> and double-click it once`}</dd>`);
        });
        const g = s.grin;
        document.getElementById('grin-kv').innerHTML = `
            <dt>GRIN loaded</dt><dd>${g.n ? `${inr(g.n, 0)} GRINs for ${inr(g.invoices, 0)} invoices` : 'none'}</dd>
            <dt>GRIN dates</dt><dd>${g.first ? `${dmy(g.first)} to <b>${dmy(g.last)}</b>` : '—'}</dd>
            <dt>Last fetched</dt><dd>${esc(when(g.updated)) || '—'}</dd>
            ${g.portal.remote ? `<dt>Done by</dt><dd>${g.portal.method === 'pc' ? pcAgent(g.portal.agent) : 'this website (no browser) - start the SDEW PC hub to let the PC do it'}</dd>` : ''}`;
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

// ---------- Pull from Tally ----------
// On the website the BROWSER asks this computer's Tally through the Tally bridge (tools/tally_bridge.py on
// http://localhost:9001), so every computer pulls its own Tally. On the PC hub (localhost:8050) the server does it.
const BRIDGE = 'http://localhost:9001';
const ON_SITE = !['localhost', '127.0.0.1'].includes(location.hostname);
const BRIDGE_DL = '/assets/SDEW-Tally-Bridge.exe';
const BRIDGE_HELP = `Tally bridge is not running on this computer. <a href="${BRIDGE_DL}" download><b>Download SDEW-Tally-Bridge.exe</b></a>, ` +
    'double-click it once (Windows may say "unknown publisher": More info > Run anyway). It then runs in the background and ' +
    'starts with Windows. Press Pull from Tally again.';

async function bridgePing() {
    try {
        const r = await fetch(`${BRIDGE}/ping`, { cache: 'no-store' });
        return r.ok ? await r.json() : null;
    } catch (e) { return null; }
}

async function gzipB64(text) {
    if (typeof CompressionStream === 'undefined') return null;
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'));
    const buf = new Uint8Array(await new Response(stream).arrayBuffer());
    let bin = '';
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return btoa(bin);
}

async function tallyTest() {
    if (ON_SITE) {
        const p = await bridgePing();
        if (!p) return showToast(BRIDGE_HELP, 'danger', 12000);
        if (!p.tally_ok) return showToast(esc(p.error), 'danger', 12000);
        return showToast(`Tally on <b>${esc(p.host)}</b> answered. Companies open: <b>${esc((p.companies || []).join(', ') || 'none')}</b>`, 'success', 8000);
    }
    try {
        const r = await apiJson('/api/grin/tally/test', 'POST', {});
        showToast(`Tally answered. Companies open: <b>${esc(r.companies.join(', ') || 'none')}</b>`, 'success', 7000);
    } catch (e) {
        showToast(e.message, 'danger', 9000);
    }
}

async function tallyPull() {
    if (!ON_SITE) return tallyPullServer();
    const btn = document.getElementById('btn-tally'), badge = document.getElementById('tally-badge');
    const lines = [];
    const log = t => { lines.push(`${new Date().toLocaleTimeString('en-GB')}  ${t}`); showLog('tally-log', lines); };
    btn.disabled = true;
    badge.className = 'status-badge sent'; badge.textContent = 'Reading Tally…';
    let total = 0, host = '';
    const from = document.getElementById('tally-from').value, to = document.getElementById('tally-to').value;
    try {
        const p = await bridgePing();
        if (!p) throw new Error(BRIDGE_HELP);
        if (!p.tally_ok) throw new Error(p.error);
        host = p.host;
        log(`This computer: ${host} - Tally companies open: ${(p.companies || []).join(', ') || 'none'}`);
        const plan = await apiJson('/api/grin/tally/plan', 'POST', { from, to });
        for (const c of plan.chunks) {
            let res = null, how = '';
            for (const mode of ['collection', 'daybook']) {
                const r = await fetch(`${BRIDGE}/tally`, { method: 'POST', body: c[mode] });
                const text = await r.text();
                if (!r.ok) throw new Error((() => { try { return JSON.parse(text).error; } catch (e) { return text; } })());
                const gz = await gzipB64(text);
                res = await apiJson('/api/grin/tally/ingest', 'POST',
                    Object.assign({ company: c.company, from: c.from, to: c.to, mode }, gz ? { gz } : { text }));
                how = mode === 'daybook' ? 'day book' : 'collection';
                if (res.error && mode === 'collection') { log(`collection request refused (${res.error.slice(0, 100)}) - trying Day Book`); continue; }
                if (res.error) throw new Error(res.error);
                if (res.usable) break;
            }
            total += res.invoices || 0;
            log(`${c.company || 'open company'} ${dmy(c.from)} - ${dmy(c.to)}: ${res.vouchers} vouchers, ${res.invoices} TAFE sales invoices (${how})`);
        }
        log(`Done - ${total} TAFE invoices read from ${host}`);
        await apiJson('/api/grin/tally/done', 'POST', { invoices: total, from, to, host });
        badge.className = 'status-badge active'; badge.textContent = `Last pull ${when(new Date().toISOString())}`;
        showToast(`Tally (${esc(host)}): ${total} TAFE invoices read`, 'success');
    } catch (e) {
        log(`Stopped: ${e.message.replace(/<[^>]+>/g, '')}`);
        badge.className = 'status-badge inactive'; badge.textContent = 'Last pull stopped';
        showToast(e.message, 'danger', 12000);
    }
    btn.disabled = false;
    loadSources(true);
    loadStatus(0);
}

async function tallyPullServer() {
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

function pcAgent(a) {
    if (!a) return '<span class="status-badge warn">SDEW PC never connected</span> start the hub there with USE_CLOUD_DB=1';
    return a.online ? `<span class="status-badge active">SDEW PC online</span> ${esc(a.host)}`
        : `<span class="status-badge inactive">SDEW PC offline</span> last seen ${esc(when(a.at))} - start start.bat there`;
}

// ---------- Fetch payments from TAFE Channel ----------
let _payTimer = null;
function showPay(st) {
    const b = document.getElementById('pay-badge');
    if (st.running) { b.className = 'status-badge sent'; b.textContent = 'Fetching…'; }
    else if (st.error) { b.className = 'status-badge inactive'; b.textContent = 'Last fetch stopped'; }
    else if (st.finished) { b.className = 'status-badge active'; b.textContent = `Last fetch ${when(st.finished)}`; }
    else { b.className = 'status-badge muted'; b.textContent = 'Ready'; }
    showLog('pay-log', st.log);
    document.getElementById('btn-pay').disabled = !!st.running;
}
async function payFetch() {
    document.getElementById('btn-pay').disabled = true;
    showPay({ running: true, log: ['Logging in to TAFE Channel…'] });
    try {
        const r = await apiJson('/api/grin/payments/fetch', 'POST', {
            from: document.getElementById('pay-from').value, to: document.getElementById('pay-to').value });
        showPay(r);
        if (r.done) {
            showToast(r.error ? esc(r.error) : 'Payments loaded from TAFE Channel', r.error ? 'danger' : 'success', 9000);
            loadSources(true); loadStatus(0);
            return;
        }
        clearInterval(_payTimer);
        _payTimer = setInterval(async () => {
            try {
                const st = await api('/api/grin/payments/fetch');
                showPay(st);
                if (!st.running) {
                    clearInterval(_payTimer);
                    showToast(st.error ? esc(st.error) : 'Payments loaded (by the SDEW PC)', st.error ? 'danger' : 'success', 9000);
                    loadSources(true); loadStatus(0);
                }
            } catch (e) { clearInterval(_payTimer); }
        }, 2000);
    } catch (e) {
        showPay({ error: e.message, log: [`Stopped: ${e.message}`] });
        showToast(e.message, 'danger', 9000);
    }
}
