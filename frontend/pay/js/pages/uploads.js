// Uploads page (and the drop box on the Check page): register + payment exports.

async function uploadFiles(fileList, from = '', handles = null) {
    const files = [...fileList];
    if (!files.length) return;
    const box = document.getElementById(from ? `upload-results-${from}` : 'upload-results');
    box.innerHTML = '';
    let ok = 0, salesFile = false, payFile = false;
    for (const [fi, f] of files.entries()) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        // show how long it has been reading, and give up with a clear message after 10 minutes
        const t0 = Date.now();
        const tick = setInterval(() => {
            row.querySelector('.msg').textContent = `Reading… ${Math.round((Date.now() - t0) / 1000)} s`;
        }, 1000);
        const ctl = new AbortController();
        const stop = setTimeout(() => ctl.abort(), 600000);
        try {
            const r = await api(`/api/pay/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f, signal: ctl.signal });
            clearInterval(tick);
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = r.kind;
            row.querySelector('.msg').textContent = r.message;
            ok++;
            if ((r.kind || '').startsWith('Sales')) salesFile = true; else payFile = true;
            // remember where the register / sales file is on this computer, for "Save to my file"
            const kind = (r.kind || '').startsWith('Sales') ? 'sales' : (r.kind || '').startsWith('Register') ? 'register' : '';
            if (kind && handles && handles[fi]) {
                try {
                    const h = await handles[fi];
                    if (h && h.kind === 'file') {
                        await fsFile.link(kind, h, f, r.file_id);
                        row.querySelector('.msg').textContent += ' · linked to your file (Save writes into it)';
                    }
                } catch (e) { /* no link - Download still works */ }
            } else if (kind) {
                await fsFile.unlink(kind);
            }
        } catch (e) {
            clearInterval(tick);
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.name === 'AbortError'
                ? 'No answer from the server after 10 minutes - check that it is running and try again'
                : (e.message === 'Failed to fetch' ? 'Server not reachable - is the app running?' : e.message);
        } finally {
            clearTimeout(stop);
        }
    }
    document.querySelectorAll('input[type=file]').forEach(i => { i.value = ''; });
    await refreshBootstrap();
    renderSources();
    loadFiles();
    if (salesFile) {
        await refreshSales();
        if (from === 'sales' || !payFile) {
            if (from !== 'sales') switchView('sales');
            await runSalesCheck();
        }
    }
    if (!payFile) return;
    if (appState.register && (appState.payments || {}).n) {
        if (from !== 'sales') await runCheck();
    } else {
        showToast(appState.register ? 'Now drop the TAFE payment details export.' : 'Now drop the invoice register.', 'info', 5000);
    }
}

async function loadFiles() {
    try {
        const files = await api('/api/pay/files');
        document.getElementById('files-tbody').innerHTML = files.length ? files.map(f => {
            const i = f.info || {};
            const det = f.kind === 'Payments'
                ? `Vendor ${esc(i.vendor)} · ${shortDate(i.period_from)} to ${shortDate(i.period_to)} · ${(i.vouchers || []).length} vouchers · ${inr(i.added || 0, 0)} new lines`
                : f.kind.startsWith('Sales')
                ? `${esc(i.sheet || '')} · ${inr(i.lines || 0, 0)} lines · ${inr(i.with_grn || 0, 0)} with GRN NO · ${inr(i.with_qty || 0, 0)} with GRN QTY`
                : `${esc(i.sheet || '')} · ${inr(i.marked || 0, 0)} marked · ${inr(i.unmarked || 0, 0)} not marked`;
            const cls = f.kind === 'Payments' ? 'sent' : f.kind.startsWith('Sales') ? 'warn' : 'active';
            return `<tr><td>${esc(when(f.uploaded_at))}</td><td><span class="status-badge ${cls}">${esc(f.kind)}</span></td>
                <td><a href="/api/pay/files/${f.id}/download" title="Download this version">${esc(f.name)}</a></td><td class="num">${inr(f.rows, 0)}</td><td>${det}</td></tr>`;
        }).join('') : `<tr><td colspan="5" class="muted-cell">Nothing uploaded yet</td></tr>`;
        document.getElementById('vouchers-loaded-tbody').innerHTML = appState.vouchers.length ? appState.vouchers.map(v => `
            <tr><td><b>${esc(v.pv)}</b></td><td>${dotted(v.pv_date)}</td><td class="num">${inr(v.amount)}</td><td class="num">${inr(v.lines, 0)}</td></tr>`).join('')
            : `<tr><td colspan="4" class="muted-cell">No payment export loaded</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function initDropzones() {
    ['dropzone', 'dropzone-check', 'dropzone-sales'].forEach(id => {
        const dz = document.getElementById(id);
        ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
        ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
        const from = id.replace('dropzone', '').replace('-', '');
        dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files, from, fsFile.handlesFromDrop(e)));
        // click: open the file with the browser's file picker that can also save back into it (Chrome / Edge)
        dz.addEventListener('click', async e => {
            if (!fsFile.supported) return;
            e.preventDefault();
            try {
                const { handles, files } = await fsFile.pick(id !== 'dropzone-sales');
                uploadFiles(files, from, handles);
            } catch (err) {
                if (err.name !== 'AbortError') showToast(err.message, 'danger');
            }
        });
    });
}
