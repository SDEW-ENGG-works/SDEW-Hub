// Buyers: who receives the GRIN reminder for each plant (or a single PO).

const B = { list: [], plants: [] };

async function loadBuyers() {
    try {
        const d = await api('/api/grin/buyers');
        B.list = d.buyers;
        B.plants = d.plants;
        const ua = document.getElementById('unassigned');
        if (d.unassigned.length) {
            ua.style.display = '';
            ua.innerHTML = `No buyer yet for: ${d.unassigned.map(u => `<b>${esc(u.plant)}</b> (${u.pending} not GRINed)`).join(', ')} — add them below so their reminders can be sent.`;
        } else ua.style.display = 'none';
        renderBuyers();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function plantOptions(sel) {
    return B.plants.map(p => `<option value="${esc(p.code)}" ${p.code === sel ? 'selected' : ''}>${esc(p.code)}${p.grin_plant ? ` (${esc(p.grin_plant)})` : ''}</option>`).join('');
}

function renderBuyers() {
    const tb = document.getElementById('buyers-tbody');
    tb.innerHTML = B.list.length ? B.list.map((b, i) => `<tr data-i="${i}">
        <td><select data-f="plant"><option value="">—</option>${plantOptions(b.plant)}</select></td>
        <td><input data-f="po_no" value="${esc(b.po_no || '')}" placeholder="all POs"></td>
        <td><input data-f="name" value="${esc(b.name || '')}"></td>
        <td><input data-f="email" type="email" value="${esc(b.email || '')}"></td>
        <td><input data-f="cc" value="${esc(b.cc || '')}"></td>
        <td><input data-f="note" value="${esc(b.note || '')}"></td>
        <td class="num">${b.pending || 0}</td>
        <td><div class="row-actions">
            <button class="btn btn-primary btn-sm" onclick="saveBuyer(${i})">Save</button>
            ${b.id ? `<button class="btn btn-danger-text btn-sm" onclick="deleteBuyer(${i})">Delete</button>` : ''}</div></td></tr>`).join('')
        : `<tr><td colspan="8" class="muted-cell">No buyers yet — press + Add buyer</td></tr>`;
}

function addBuyer() {
    const used = new Set(B.list.map(b => b.plant));
    const next = B.plants.find(p => p.grin_plant && !used.has(p.code));
    B.list.push({ plant: next ? next.code : '', po_no: '', name: '', email: '', cc: '', note: '', pending: 0 });
    renderBuyers();
}

async function saveBuyer(i) {
    const tr = document.querySelector(`#buyers-tbody tr[data-i="${i}"]`);
    const b = { id: B.list[i].id };
    tr.querySelectorAll('[data-f]').forEach(el => b[el.dataset.f] = el.value);
    try {
        await apiJson('/api/grin/buyers', 'POST', b);
        showToast('Buyer saved', 'success');
        loadBuyers();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function deleteBuyer(i) {
    const b = B.list[i];
    if (!(await confirmBox('Delete buyer?', `${b.name || b.email} (${b.plant}${b.po_no ? ' / PO ' + b.po_no : ''})`))) return;
    try {
        await api(`/api/grin/buyers/${b.id}`, { method: 'DELETE' });
        loadBuyers();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
