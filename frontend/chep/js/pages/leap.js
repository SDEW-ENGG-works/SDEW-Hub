// LEAP page: upload a History file to my.leap-india.com, submit after the user's OK,
// then check every invoice against LEAP's "Pending Inwards at C2" report.

let _leapTimer = null;
appState.leapRun = null;
appState.leapVerifyFilter = 'problems';

async function loadLeapPage(runId) {
    if (runId) appState.leapRun = runId;
    try {
        const runs = await api('/api/chep/runs');
        const sel = document.getElementById('leap-run');
        if (!appState.leapRun && runs.length) appState.leapRun = runs[0].id;
        sel.innerHTML = runs.map(r => {
            const st = r.leap_status ? ` · ${leapStatusText(r)}` : '';
            return `<option value="${r.id}" ${r.id === appState.leapRun ? 'selected' : ''}>${esc(r.file_name)} — ${shortDate(r.doc_date)} · ${inr(r.summary?.invoices || 0, 0)} invoices${esc(st)}</option>`;
        }).join('') || '<option value="">No CHEP file made yet</option>';
    } catch (e) { showToast(e.message, 'danger'); }
    await pollLeap();
}

async function refreshLeap() {
    const btn = document.getElementById('btn-leap-refresh');
    setBusy(btn, true, 'Refreshing…');
    try {
        appState.leapRun = parseInt(document.getElementById('leap-run').value, 10) || appState.leapRun;
        await loadLeapPage();
        refreshBootstrap();
    } finally { setBusy(btn, false); }
}

function leapStatusText(r) {
    const l = r.leap || {};
    return { verified: `LEAP ✓ ${l.confirmed} confirmed`, problems: `LEAP: ${l.missing || 0} missing`,
        error: 'LEAP: stopped with error' }[r.leap_status] || r.leap_status;
}

async function startLeap(mode) {
    const runId = parseInt(document.getElementById('leap-run').value, 10);
    if (!runId) return;
    if (mode === 'upload' && !await confirmBox('Upload this file to LEAP?',
        'The app logs in to LEAP and uploads the file. Nothing is submitted until you press "Submit to LEAP" here.')) return;
    try {
        await apiJson('/api/chep/leap/start', 'POST', { run_id: runId, mode, headed: document.getElementById('leap-headed').checked });
        appState.leapRun = runId;
        pollLeap();
    } catch (e) { showToast(e.message, 'danger', 7000); }
}

async function leapDecide(choice) {
    if (choice === 'submit' && !await confirmBox('Submit to LEAP?',
        'LEAP will create the transfers to TAFE for these rows. This cannot be undone from the app.')) return;
    try { await apiJson('/api/chep/leap/decide', 'POST', { choice }); pollLeap(); }
    catch (e) { showToast(e.message, 'danger'); }
}

async function leapCancel() {
    try { await apiJson('/api/chep/leap/cancel', 'POST'); pollLeap(); } catch (e) { showToast(e.message, 'danger'); }
}

async function pollLeap() {
    clearTimeout(_leapTimer);
    let d;
    try { d = await api('/api/chep/leap/status'); } catch (e) { return; }
    renderLeap(d);
    const busy = d.state && ['running', 'waiting'].includes(d.state.phase);
    const onPage = document.getElementById('leap-view').classList.contains('active');
    if (busy) _leapTimer = setTimeout(pollLeap, onPage ? (d.remote ? 2500 : 1500) : 5000);
    const badge = document.getElementById('leap-badge');
    badge.style.display = busy ? '' : 'none';
    badge.textContent = d.state?.phase === 'waiting' ? '!' : '…';
}

const STEP_ICON = { todo: '○', doing: '◔', waiting: '!', done: '✓', error: '✕', skip: '–' };

function renderLeap(d) {
    const s = d.state || {};
    const warn = document.getElementById('leap-unavailable');
    // the website keeps the button on while the PC is off (the job waits) - the yellow box says so
    warn.style.display = d.reason ? '' : 'none';
    warn.querySelector('.card-title').textContent = d.available ? 'The SDEW PC is not connected' : 'LEAP automation is not ready';
    warn.querySelector('span').textContent = d.reason || '';
    const note = document.getElementById('leap-remote-note');
    const pcOn = d.remote && d.agent && d.agent.online && d.runner !== 'cloud';
    const cloud = d.remote && d.runner === 'cloud';
    note.style.display = pcOn || cloud ? '' : 'none';
    if (pcOn) note.querySelector('span').innerHTML = `The upload runs on the SDEW PC <b>${esc(d.agent.host)}</b> — you can follow every step and press Submit from here.`;
    if (cloud) note.querySelector('span').innerHTML = `The upload runs in a <b>cloud browser on Vercel</b> — no PC needed. Follow every step and press Submit here.`;
    const busy = ['running', 'waiting'].includes(s.phase);
    document.getElementById('btn-leap-upload').disabled = !d.available || busy;
    document.getElementById('btn-leap-verify').disabled = !d.available || busy;
    document.getElementById('btn-leap-cancel').style.display = busy ? '' : 'none';

    const card = document.getElementById('leap-progress');
    if (!s.phase || s.phase === 'idle') { card.style.display = 'none'; document.getElementById('leap-verify-card').style.display = 'none'; return; }
    card.style.display = '';
    const phaseText = { running: 'Working…', waiting: 'Waiting for your OK', done: 'Finished', error: 'Stopped with an error', cancelled: 'Cancelled — nothing more sent' }[s.phase] || s.phase;
    document.getElementById('leap-title').textContent = `${s.mode === 'verify' ? 'Check' : 'Upload'}: ${s.file_name}`;
    const ph = document.getElementById('leap-phase');
    ph.textContent = phaseText;
    ph.className = 'status-badge ' + ({ running: 'sent', waiting: 'warn', done: 'active', error: 'inactive', cancelled: 'muted' }[s.phase] || 'muted');

    document.getElementById('leap-steps').innerHTML = (s.steps || []).map(st => `
        <li class="leap-step ${st.status}"><span class="ico">${STEP_ICON[st.status] || '○'}</span>
            <div><div class="lbl">${esc(st.label)}</div>${st.detail ? `<div class="det">${esc(st.detail)}</div>` : ''}</div></li>`).join('');

    // counts + submit box for the part waiting
    const box = document.getElementById('leap-submit-box');
    const part = s.current !== null && s.current !== undefined ? (s.parts || [])[s.current] : null;
    if (s.phase === 'waiting' && part) {
        const ok = s.check_ok;
        box.style.display = '';
        box.className = 'leap-submit ' + (ok ? 'ok' : 'bad');
        box.innerHTML = `
            <div class="leap-counts">
                <div><span>Our file</span><b>${part.rows}</b></div>
                <div><span>ALL</span><b>${part.all ?? '—'}</b></div>
                <div><span>CLEAN</span><b>${part.clean ?? '—'}</b></div>
                <div class="${part.error ? 'red' : ''}"><span>ERROR</span><b>${part.error ?? '—'}</b></div>
            </div>
            <p>${ok ? 'LEAP read every row and found no errors. Press <b>Submit to LEAP</b> to create the transfers.'
                : '<b>Counts do not match or LEAP shows errors.</b> Better cancel and fix the file. Submit anyway only if you are sure.'}</p>
            ${(part.errors || []).length ? `<div class="leap-errors"><b>Rows LEAP marked as errors:</b><ul>${part.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
            <div class="btn-row">
                <button class="btn ${ok ? 'btn-primary' : 'btn-danger'}" onclick="leapDecide('submit')">Submit to LEAP${(s.parts || []).length > 1 ? ` (part ${s.current + 1} of ${s.parts.length})` : ''}</button>
                <button class="btn btn-outline" onclick="leapDecide('cancel')">Cancel — don't submit</button>
            </div>`;
    } else box.style.display = 'none';

    _leapLive = { busy, phase: s.phase };
    refreshLeapShot();

    const log = document.getElementById('leap-log');
    log.textContent = (s.log || []).join('\n');
    log.scrollTop = log.scrollHeight;
    renderLeapVerify(s.verify, s.retry_run_id);
}

function setLeapFilter(f) { appState.leapVerifyFilter = f; pollLeap(); }

function renderLeapVerify(v, retryId) {
    const card = document.getElementById('leap-verify-card');
    if (!v) { card.style.display = 'none'; return; }
    card.style.display = '';
    const set = (id, x) => { document.getElementById(id).textContent = x; };
    set('lv-confirmed', inr(v.confirmed, 0));
    set('lv-missing', inr(v.missing, 0));
    set('lv-other', inr((v.short || 0) + (v.extra || 0), 0));
    set('lv-sub', `${v.invoices} invoices checked against ${v.report_file || 'the report'} · ${when(v.checked_at)}`);
    const rb = document.getElementById('lv-retry');
    rb.style.display = retryId ? '' : 'none';
    rb.onclick = () => downloadRun(retryId);
    const f = appState.leapVerifyFilter;
    const lines = (v.lines || []).filter(l => f === 'all' || (f === 'problems' ? l.status !== 'confirmed' : l.status === f));
    document.getElementById('lv-pills').innerHTML = [['problems', 'Problems'], ['all', 'All'], ['confirmed', 'Confirmed']]
        .map(([k, t]) => `<button class="cat-pill ${f === k ? 'active' : ''}" onclick="setLeapFilter('${k}')">${t}</button>`).join('');
    const cls = { confirmed: 'active', missing: 'inactive', short: 'warn', extra: 'warn' };
    const label = { confirmed: 'Confirmed', missing: 'Missing', short: 'Less in LEAP', extra: 'More in LEAP (twice?)' };
    const fmt = o => Object.entries(o || {}).map(([k, q]) => `${k} × ${q}`).join(', ');
    document.getElementById('lv-tbody').innerHTML = lines.length ? lines.map(l => `
        <tr><td class="strong">${esc(l.invoice)}</td><td>${esc(l.customer)}</td><td class="wrap">${esc(l.part)}</td>
            <td><span class="status-badge ${cls[l.status]}">${label[l.status]}</span></td>
            <td class="sku-list">${esc(fmt(l.expected))}</td><td class="sku-list">${esc(fmt(l.found))}</td>
            <td class="sku-list">${esc((l.documents || []).join(', '))}</td></tr>`).join('')
        : `<tr><td colspan="7" class="muted-cell">${f === 'problems' ? 'No problems — every invoice is in LEAP' : 'Nothing to show'}</td></tr>`;
}


// ---- live view: screenshots of the hidden LEAP browser (works for whoever opens this page,
// whether the PC or the cloud browser does the upload)
let _leapLive = { busy: false, phase: 'idle' };
let _leapShotUrl = null, _leapShotBusy = false, _leapShotAt = 0;
async function refreshLeapShot(force) {
    const box = document.getElementById('leap-live-box');
    const want = document.getElementById('leap-headed').checked && _leapLive.phase && _leapLive.phase !== 'idle';
    if (!want) { box.style.display = 'none'; return; }
    if (_leapShotBusy || (!force && !_leapLive.busy && _leapShotUrl && Date.now() - _leapShotAt < 15000)) return;
    _leapShotBusy = true;
    try {
        const r = await fetch('/api/chep/leap/shot?t=' + Date.now(), { cache: 'no-store' });
        if (r.status === 200) {
            const url = URL.createObjectURL(await r.blob());
            document.getElementById('leap-live').src = url;
            if (_leapShotUrl) URL.revokeObjectURL(_leapShotUrl);
            _leapShotUrl = url;
            _leapShotAt = Date.now();
            document.getElementById('leap-live-time').textContent = new Date().toLocaleTimeString();
            box.style.display = '';
        } else if (!_leapShotUrl) box.style.display = 'none';
    } catch (e) { /* next poll */ } finally { _leapShotBusy = false; }
}
