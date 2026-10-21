// POs page: every uploaded PO, its plant and its revised prices.

async function loadPos() {
    try {
        appState.pos = await api('/api/supp/pos');
        renderPos();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function renderPos() {
    const q = document.getElementById('po-search').value.trim().toLowerCase();
    const plants = (appState.settings && appState.settings.plants || []).map(p => p.code);
    const list = appState.pos.filter(p => !q || `${p.po_no} ${p.plant}`.toLowerCase().includes(q));
    document.getElementById('pos-tbody').innerHTML = list.length ? list.map(p => `
        <tr class="clickable" onclick="openPo('${esc(p.po_no)}')">
            <td><b>${esc(p.po_no)}</b></td>
            <td onclick="event.stopPropagation()">
                <select class="plant-select" onchange="setPoPlant('${esc(p.po_no)}', this.value)">
                    <option value="">?</option>
                    ${plants.map(c => `<option ${c === p.plant ? 'selected' : ''}>${esc(c)}</option>`).join('')}
                </select>
            </td>
            <td>${esc(p.po_date)}</td><td>${esc(p.valid_till)}</td>
            <td class="num">${p.items}</td><td class="num">${p.revised}</td>
            <td class="num">${p.bill_lines ? `<b>${inr(p.bill_lines, 0)}</b>` : '<span class="stat-sub">0</span>'}</td>
            <td>${esc(when(p.uploaded_at))}</td>
            <td onclick="event.stopPropagation()"><button class="btn-icon btn-icon-danger" title="Remove PO" onclick="deletePo('${esc(p.po_no)}')">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path></svg></button></td>
        </tr>`).join('') : `<tr><td colspan="9" class="muted-cell">No POs yet — upload them on the Uploads page</td></tr>`;
}

async function setPoPlant(po, plant) {
    try {
        await apiJson(`/api/supp/pos/${po}`, 'PUT', { plant });
        const p = appState.pos.find(x => x.po_no === po);
        if (p) p.plant = plant;
        showToast(`PO ${po} set to ${plant || '?'}`, 'success');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function deletePo(po) {
    if (!(await confirmBox(`Remove PO ${po}?`, 'Its prices are removed from the app. Upload the file again to bring them back.'))) return;
    try {
        await api(`/api/supp/pos/${po}`, { method: 'DELETE' });
        showToast(`PO ${po} removed`, 'success');
        await refreshBootstrap();
        renderUploadStats();
        loadPos();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function openPo(po) {
    try {
        const h = await api(`/api/supp/pos/${po}`);
        document.getElementById('po-modal-title').textContent = `PO ${h.po_no} · ${h.plant || 'plant ?'}`;
        document.getElementById('po-modal-sub').textContent = `PO date ${h.po_date} · valid till ${h.valid_till} · ${h.bill_to}`;
        document.getElementById('po-items-tbody').innerHTML = h.items.map(it => {
            const diff = (it.old !== null && it.new !== null) ? it.new - it.old : null;
            const blocks = it.blocks.map(b => `${b.frm} – ${b.to}: ${Object.entries(b.conds).map(([k, v]) => `${k} ${inr(v)}`).join(' + ')}`).join('<br>');
            return `<tr><td>${it.item}</td><td><b>${esc(it.part)}</b></td><td>${esc(it.descr)}</td>
                <td class="num">${inr(it.old)}</td><td class="num ${it.override ? 'yellow' : ''}">${inr(it.new)}</td>
                <td class="num strong">${diff === null ? '' : inr(diff)}</td><td class="stat-sub">${blocks}</td></tr>`;
        }).join('');
        openModal('po-modal');
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
