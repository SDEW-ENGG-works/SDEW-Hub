// History page: every template made - download again or delete.

async function loadRuns() {
    const tb = document.getElementById('runs-tbody');
    try {
        const runs = await api('/api/dqms/runs');
        tb.innerHTML = runs.length ? runs.map(r => {
            const s = r.summary || {};
            const invs = r.invoices || [];
            const list = invs.length > 4 ? `${invs.slice(0, 3).join(', ')} … ${invs[invs.length - 1]}` : invs.join(', ');
            return `<tr><td>${esc(when(r.created_at))}</td><td class="strong">${esc(r.file_name)}</td>
                <td class="wrap" title="${esc(invs.join(', '))}">${esc(list)}</td>
                <td class="num">${inr(s.invoices || 0, 0)}</td><td class="num">${inr(s.rows || 0, 0)}</td>
                <td class="num">${inr(s.value || 0)}</td><td class="wrap">${esc(s.report || '')}</td>
                <td class="row-actions">
                    <button class="btn btn-outline btn-sm" onclick="downloadRun(${r.id})">Download</button>
                    <button class="btn btn-danger-text btn-sm" onclick="deleteRun(${r.id})">Delete</button></td></tr>`;
        }).join('') : `<tr><td colspan="8" class="muted-cell">No template made yet</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function deleteRun(id) {
    if (!await confirmBox('Delete this file?', 'Its invoices go back to the "Not in a file" list on the Create page.')) return;
    await apiJson(`/api/dqms/runs/${id}`, 'DELETE');
    await refreshBootstrap();
    loadRuns();
}
