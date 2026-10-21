// GRIN page: fetch from TAFE Channel, month coverage, search.

let _syncTimer = null;

async function loadGrin() {
    try {
        const d = await api('/api/supp/grin/summary');
        document.getElementById('grin-months-tbody').innerHTML = d.months.length ? d.months.map(m => `
            <tr><td><b>${esc(m.month)}</b></td><td class="num">${inr(m.lines, 0)}</td><td class="num">${inr(m.grins, 0)}</td>
            <td class="num">${inr(m.portal, 0)}</td><td class="num">${inr(m.upload, 0)}</td>
            <td class="num">${m.open_lots ? `<span class="status-badge warn">${inr(m.open_lots, 0)}</span>` : '0'}</td>
            <td>${esc(when(m.updated))}</td></tr>`).join('')
            : `<tr><td colspan="7" class="muted-cell">No GRIN yet</td></tr>`;
        showSyncStatus(d.portal);
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function showSyncStatus(st) {
    const badge = document.getElementById('portal-status');
    if (!st.available) {
        badge.className = 'status-badge warn';
        badge.textContent = 'Playwright not installed';
    } else if (st.running) {
        badge.className = 'status-badge sent';
        badge.textContent = 'Fetching…';
    } else if (st.error) {
        badge.className = 'status-badge inactive';
        badge.textContent = 'Last fetch stopped';
    } else {
        badge.className = 'status-badge active';
        badge.textContent = st.finished ? `Last fetch ${when(st.finished)}` : 'Ready';
    }
    const log = document.getElementById('sync-log');
    if (st.log && st.log.length) {
        log.style.display = '';
        log.textContent = st.log.join('\n');
        log.scrollTop = log.scrollHeight;
    }
    document.getElementById('btn-sync').disabled = !!st.running;
}

async function startSync() {
    const body = {
        from: document.getElementById('sync-from').value,
        to: document.getElementById('sync-to').value,
        headed: document.getElementById('sync-headed').checked,
    };
    const btn = document.getElementById('btn-sync');
    btn.disabled = true;
    showToast('Fetching GRIN from TAFE Channel…', 'info');
    try {
        const r = await apiJson('/api/supp/grin/sync', 'POST', body);
        if (r.done) {           // website: the fetch already ran inside the request
            r.available = true;
            showSyncStatus(r);
            await refreshBootstrap();
            renderUploadStats();
            loadGrin();
            showToast(r.error ? `GRIN fetch stopped: ${esc(r.error)}` : 'GRIN fetched. Press Calculate bill to update the bill.', r.error ? 'danger' : 'success', 9000);
            return;
        }
        pollSync();
    } catch (e) {
        btn.disabled = false;
        showToast(e.message, 'danger', 7000);
    }
}

function pollSync() {
    clearInterval(_syncTimer);
    _syncTimer = setInterval(async () => {
        try {
            const st = await api('/api/supp/grin/sync');
            st.available = true;
            showSyncStatus(st);
            if (!st.running) {
                clearInterval(_syncTimer);
                await refreshBootstrap();
                renderUploadStats();
                loadGrin();
                showToast(st.error ? `GRIN fetch stopped: ${st.error}` : 'GRIN fetched. Press Calculate bill to update the bill.', st.error ? 'danger' : 'success', 6000);
            }
        } catch (e) {
            clearInterval(_syncTimer);
        }
    }, 2500);
}

async function searchGrin() {
    const q = document.getElementById('grin-search').value.trim();
    const tbody = document.getElementById('grin-tbody');
    if (q.length < 3) { tbody.innerHTML = `<tr><td colspan="11" class="muted-cell">Type at least 3 characters</td></tr>`; return; }
    try {
        const list = await api(`/api/supp/grin/search?q=${encodeURIComponent(q)}`);
        tbody.innerHTML = list.length ? list.map(g => `
            <tr><td><b>${esc(g.grin_no)}</b></td><td>${dmy(g.grin_date)}</td><td>${esc(g.invoice_no)}</td><td>${esc(g.plant)}</td>
            <td>${esc(g.po_no)}</td><td>${esc(g.part_no)}</td><td>${esc(g.part_desc)}</td>
            <td class="num">${qty(g.grin_qty)}</td><td class="num">${qty(g.accepted_qty)}</td><td class="num">${qty(g.rejected_qty)}</td>
            <td><span class="status-badge ${g.source === 'Portal' ? 'sent' : 'muted'}">${esc(g.source)}</span></td></tr>`).join('')
            : `<tr><td colspan="11" class="muted-cell">Nothing found</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function initGrinDates() {
    const to = new Date();
    const from = new Date(to.getTime() - 45 * 86400000);
    document.getElementById('sync-to').value = to.toISOString().slice(0, 10);
    document.getElementById('sync-from').value = from.toISOString().slice(0, 10);
}
