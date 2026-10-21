// Parts page: CHEP size per part (learned from packing lists, or set by hand).

appState.parts = [];

async function loadParts() {
    try {
        appState.parts = await api('/api/chep/parts');
        renderParts();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function renderParts() {
    const q = document.getElementById('parts-search').value.trim().toLowerCase();
    const list = appState.parts.filter(p => !q || `${p.part} ${p.part_name}`.toLowerCase().includes(q));
    document.getElementById('parts-tbody').innerHTML = list.length ? list.map(p => `
        <tr><td class="strong">${esc(p.part)}</td><td>${esc(p.part_name || '')}</td>
            <td><select class="size-select" data-part="${esc(p.part)}" onchange="quickSetPart(this)">${sizeOptions(p.type, false)}</select></td>
            <td class="sku-list">${esc(skuText({ [p.type]: 1 }).replace(/ × 1/g, ''))}</td>
            <td>${p.source === 'manual' ? '<span class="status-badge sent">Set by hand</span>' : esc(p.source || '')}</td>
            <td>${esc(when(p.updated_at))}</td>
            <td class="row-actions"><button class="btn btn-danger-text btn-sm" data-part="${esc(p.part)}" onclick="deletePart(this.dataset.part)">Remove</button></td></tr>`).join('')
        : `<tr><td colspan="7" class="muted-cell">${appState.parts.length ? 'No match' : 'Upload a packing list — part sizes are learned from it'}</td></tr>`;
}

async function quickSetPart(sel) {
    const p = appState.parts.find(x => x.part === sel.dataset.part);
    try {
        await apiJson('/api/chep/parts', 'PUT', { part: p.part, type: sel.value, part_name: p.part_name });
        showToast(`${esc(p.part)} → ${esc(sizeLabel(sel.value))}`, 'success');
        loadParts();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function addPart() {
    document.getElementById('pm-part').value = '';
    document.getElementById('pm-name').value = '';
    document.getElementById('pm-type').innerHTML = sizeOptions('', false);
    openModal('part-modal');
}

async function savePart() {
    try {
        await apiJson('/api/chep/parts', 'PUT', {
            part: document.getElementById('pm-part').value,
            type: document.getElementById('pm-type').value,
            part_name: document.getElementById('pm-name').value,
        });
        closeModal('part-modal');
        await refreshBootstrap();
        loadParts();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function deletePart(part) {
    if (!await confirmBox(`Remove ${part}?`, 'Its CHEP size is learned again from the next packing list.')) return;
    await apiJson(`/api/chep/parts/${encodeURIComponent(part)}`, 'DELETE');
    await refreshBootstrap();
    loadParts();
}
