// Uploads page (and the drop box on the Check page): register + payment exports.

async function uploadFiles(fileList, from = '') {
    const files = [...fileList];
    if (!files.length) return;
    const box = document.getElementById(from ? `upload-results-${from}` : 'upload-results');
    box.innerHTML = '';
    let ok = 0, salesFile = false, payFile = false;
    for (const f of files) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        try {
            const r = await api(`/api/pay/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = r.kind;
            row.querySelector('.msg').textContent = r.message;
            ok++;
            if ((r.kind || '').startsWith('Sales')) salesFile = true; else payFile = true;
        } catch (e) {
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.message;
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
                <td>${esc(f.name)}</td><td class="num">${inr(f.rows, 0)}</td><td>${det}</td></tr>`;
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
        dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files, id.replace('dropzone', '').replace('-', '')));
    });
}
