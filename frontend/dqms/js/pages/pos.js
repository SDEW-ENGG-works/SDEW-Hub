// POs page: PO line item numbers (from the hub's shared POs - PO .htm / TAFE export - or typed by hand).

async function loadPos() {
    try {
        const d = await api('/api/dqms/pos');
        document.getElementById('pos-tbody').innerHTML = d.pos.length ? d.pos.map(p =>
            `<tr><td class="strong">${esc(p.po_no)}</td><td>${esc(p.plant)}</td><td class="num">${p.items}</td>
                <td class="wrap">${esc(p.source)}</td><td>${esc(when(p.uploaded_at))}</td></tr>`).join('')
            : `<tr><td colspan="5" class="muted-cell">No PO loaded — drop a PO .htm or TAFE PO export on any upload box of the hub</td></tr>`;
        document.getElementById('typed-tbody').innerHTML = d.typed.length ? d.typed.map(t =>
            `<tr><td>${esc(t.po_no)}</td><td class="mono">${esc(t.part)}</td><td class="num strong">${t.item}</td>
                <td class="num">${t.po_item ?? '<span class="muted">not in PO</span>'}</td><td>${esc(when(t.updated_at))}</td>
                <td><button class="btn btn-danger-text btn-sm" data-po="${esc(t.po_no)}" data-part="${esc(t.part)}" onclick="clearTyped(this.dataset.po, this.dataset.part)">Use the PO again</button></td></tr>`).join('')
            : `<tr><td colspan="6" class="muted-cell">None</td></tr>`;
        if (document.getElementById('po-search').value.trim()) searchPo();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function searchPo() {
    const q = document.getElementById('po-search').value.trim();
    const tb = document.getElementById('po-items-tbody');
    if (!q) { tb.innerHTML = `<tr><td colspan="6" class="muted-cell">Type a part number above</td></tr>`; return; }
    const d = await api(`/api/dqms/pos?q=${encodeURIComponent(q)}`);
    tb.innerHTML = d.items.length ? d.items.map(i =>
        `<tr><td class="mono strong">${esc(i.part)}</td><td>${esc(i.descr)}</td><td>${esc(i.po_no)}</td><td>${esc(i.plant || '')}</td>
            <td class="num">${i.item}</td>
            <td><input class="cell-input w-line ${i.typed != null ? 'typed' : ''}" value="${i.typed ?? ''}" placeholder="—"
                data-po="${esc(i.po_no)}" data-part="${esc(i.part)}" onchange="setTyped(this.dataset.po, this.dataset.part, this.value)"></td></tr>`).join('')
        : `<tr><td colspan="6" class="muted-cell">Not found</td></tr>`;
}

async function setTyped(po, part, val) {
    try {
        await apiJson('/api/dqms/pos/line', 'PUT', { po_no: po, part, item: val.trim() });
        showToast('Saved', 'success');
        loadPos();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
function clearTyped(po, part) { setTyped(po, part, ''); }

async function importSupp() {
    try {
        const r = await apiJson('/api/dqms/pos/import-supp', 'POST', {});
        showToast(`${r.pos} POs, ${r.items} line items imported from the Supplementary Bill app.`, 'success');
        await refreshBootstrap();
        loadPos();
    } catch (e) {
        showToast(e.message, 'danger', 7000);
    }
}
