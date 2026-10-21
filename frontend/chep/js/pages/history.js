// History page: every CHEP template made, download again.

appState.runTicks = new Set();

async function loadRuns() {
    const tb = document.getElementById('runs-tbody');
    try {
        const runs = await api('/api/chep/runs');
        const ids = new Set(runs.map(r => r.id));
        appState.runTicks = new Set([...appState.runTicks].filter(id => ids.has(id)));
        appState.runCount = runs.length;
        tb.innerHTML = runs.length ? runs.map(r => {
            const s = r.summary || {};
            return `<tr><td><input type="checkbox" class="run-tick" value="${r.id}" ${appState.runTicks.has(r.id) ? 'checked' : ''} onchange="tickRun(${r.id}, this.checked)"></td><td>${esc(when(r.created_at))}</td><td class="strong">${esc(r.file_name)}</td>
                <td>${shortDate(r.doc_date)}</td><td>${esc(s.source || '')}</td><td>${esc((s.sheets || []).join(', '))}</td>
                <td class="num">${inr(s.invoices || 0, 0)}</td><td class="num">${inr(s.cheps || 0, 0)}</td><td class="num">${inr(s.rows || 0, 0)}</td>
                <td>${r.leap_status ? `<span class="status-badge ${{ verified: 'active', problems: 'warn', error: 'inactive' }[r.leap_status] || 'muted'}">${esc(leapStatusText(r))}</span>` : '<span class="muted">—</span>'}</td>
                <td class="row-actions">
                    <button class="btn btn-outline btn-sm" onclick="downloadRun(${r.id})">Download</button>
                    <button class="btn btn-outline btn-sm" onclick="switchView('leap'); loadLeapPage(${r.id})">LEAP</button>
                    <button class="btn btn-danger-text btn-sm" onclick="deleteRun(${r.id})">Delete</button></td></tr>`;
        }).join('') : `<tr><td colspan="11" class="muted-cell">No CHEP template made yet</td></tr>`;
        updateCombineButton();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function tickRun(id, on) {
    if (on) appState.runTicks.add(id); else appState.runTicks.delete(id);
    updateCombineButton();
}

function tickAllRuns(on) {
    document.querySelectorAll('.run-tick').forEach(cb => { cb.checked = on; tickRun(parseInt(cb.value, 10), on); });
}

function updateCombineButton() {
    const n = appState.runTicks.size;
    const btn = document.getElementById('btn-combine');
    btn.disabled = n < 2;
    btn.lastChild.textContent = n >= 2 ? ` Combine ${n} files & download` : ' Combine & download';
    document.getElementById('runs-all').checked = n > 0 && n === appState.runCount;
}

// Ticked files -> one CHEP template sheet (oldest first; an invoice in two files is taken once).
async function combineRuns() {
    const btn = document.getElementById('btn-combine');
    setBusy(btn, true, 'Combining…');
    try {
        const res = await fetch('/api/chep/runs/combine', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: [...appState.runTicks] }),
        });
        if (res.status === 401) { location.replace('/login.html'); return; }
        if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || `Server error ${res.status}`); }
        const blob = await res.blob();
        const cd = res.headers.get('Content-Disposition') || '';
        const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
        const name = m ? decodeURIComponent(m[1]) : 'BulkTransfer Template combined.xlsx';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
        const note = decodeURIComponent(res.headers.get('X-Combine-Note') || '');
        showToast(`<b>${esc(name)}</b>${note ? ' — ' + esc(note) : ''}`, 'success', 7000);
    } catch (e) {
        showToast(e.message, 'danger', 6000);
    } finally {
        setBusy(btn, false);
        updateCombineButton();
    }
}

async function deleteRun(id) {
    if (!await confirmBox('Delete this file?', 'It is removed from the history. The packing list stays.')) return;
    await apiJson(`/api/chep/runs/${id}`, 'DELETE');
    await refreshBootstrap();
    loadRuns();
}
