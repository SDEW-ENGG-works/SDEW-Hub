// Uploads page: one drop box for POs, GRIN files and the Sales Register.

function renderUploadStats() {
    const c = appState.counts || {};
    const set = (id, v) => { document.getElementById(id).textContent = v; };
    set('up-pos', inr(c.pos || 0, 0));
    set('up-pos-sub', c.po_parts ? `${inr(c.po_parts, 0)} part prices` : '');
    set('up-grin', inr(c.grin || 0, 0));
    set('up-grin-sub', c.grin ? `${shortDate(c.grin_first)} to ${shortDate(c.grin_last)}` : '');
    set('up-sales', inr(c.sales || 0, 0));
    set('up-sales-sub', c.sales ? `${shortDate(c.sales_first)} to ${shortDate(c.sales_last)}` : '');
    set('up-files', inr(c.files || 0, 0));
    set('po-count-badge', inr(c.pos || 0, 0));
    set('grin-count-badge', inr(c.grin || 0, 0));
}

async function uploadFiles(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    const box = document.getElementById('upload-results');
    box.innerHTML = '';
    let ok = 0;
    for (const f of files) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        try {
            const r = await api(`/api/supp/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = r.kind;
            row.querySelector('.msg').textContent = r.message + (r.warnings && r.warnings.length ? ` · ${r.warnings.length} line(s) not read` : '');
            ok++;
        } catch (e) {
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.message;
        }
    }
    document.getElementById('file-input').value = '';
    await refreshBootstrap();
    renderUploadStats();
    loadFiles();
    if (ok) showToast(`${ok} file(s) loaded. Press <b>Calculate bill</b> on the Bill page to update the bill.`, 'success', 5000);
}

async function loadFiles() {
    try {
        const files = await api('/api/supp/files');
        document.getElementById('files-tbody').innerHTML = files.length ? files.map(f => {
            const i = f.info || {};
            const det = f.kind === 'PO' ? `PO ${esc(i.po_no)} · ${esc(i.plant || 'plant ?')}`
                : f.kind === 'GRIN' ? `${esc(i.source || '')} · ${shortDate(i.first)} to ${shortDate(i.last)} · ${inr(i.added || 0, 0)} new`
                : f.kind === 'Sales' ? `${esc((i.sheets || []).join(', '))}` : '';
            return `<tr><td>${esc(when(f.uploaded_at))}</td><td><span class="status-badge sent">${esc(f.kind)}</span></td>
                <td>${esc(f.name)}</td><td class="num">${inr(f.rows, 0)}</td><td>${det}</td></tr>`;
        }).join('') : `<tr><td colspan="5" class="muted-cell">Nothing uploaded yet</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function initDropzone() {
    const dz = document.getElementById('dropzone');
    ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
    dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files));
}
