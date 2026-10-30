// Admin page: users, their password and the pages (boxes) they may open.
const A = { users: [], pages: [], editing: null };

async function loadUsers() {
    try {
        const d = await api('/api/admin/users');
        A.users = d.users; A.pages = d.pages;
        document.getElementById('admin-info').innerHTML = `Admin login: <b>${esc(d.admin)}</b>.` +
            (d.shared ? ' The old shared password (APP_PASSWORD) also still works and opens every page - remove it from the env once everyone has their own login.' : '');
        const name = k => (A.pages.find(p => p.key === k) || {}).name || k;
        document.getElementById('users-tbody').innerHTML = A.users.length ? A.users.map(u => `
            <tr class="${u.active ? '' : 'off'}">
                <td class="strong">${esc(u.username)}</td>
                <td><div class="acc-tags">${u.access.map(k => `<span class="acc-tag">${esc(name(k))}</span>`).join('')}</div></td>
                <td>${u.active ? '<span class="status-badge active">Active</span>' : '<span class="status-badge inactive">Off</span>'}</td>
                <td>${esc(when(u.last_login)) || '<span class="muted">never</span>'}</td>
                <td>${esc(u.note || '')}</td>
                <td><div class="row-btns">
                    <button class="btn btn-outline btn-sm" onclick="openUser(${u.id})">Edit</button>
                    <button class="btn btn-danger-text btn-sm" onclick="deleteUser(${u.id})">Delete</button></div></td>
            </tr>`).join('') : `<tr><td colspan="6" class="muted-cell">No users yet - press + Create user</td></tr>`;
    } catch (e) {
        document.getElementById('users-tbody').innerHTML = `<tr><td colspan="6" class="muted-cell">${esc(e.message)}</td></tr>`;
    }
}

function openUser(id) {
    const u = id ? A.users.find(x => x.id === id) : null;
    A.editing = u;
    document.getElementById('user-title').textContent = u ? `Edit ${u.username}` : 'Create user';
    const nm = document.getElementById('u-name');
    nm.value = u ? u.username : ''; nm.disabled = !!u;
    document.getElementById('u-pass').value = '';
    document.getElementById('u-pass-label').textContent = u ? 'New password (leave empty to keep)' : 'Password';
    document.getElementById('u-note').value = u ? (u.note || '') : '';
    document.getElementById('u-active').checked = u ? !!u.active : true;
    document.getElementById('u-active-row').style.display = u ? '' : 'none';
    const have = new Set(u ? u.access : []);
    document.getElementById('u-access').innerHTML = A.pages.map(p =>
        `<label><input type="checkbox" value="${esc(p.key)}" ${have.has(p.key) ? 'checked' : ''}> ${esc(p.name)}</label>`).join('');
    openModal('user-modal');
    setTimeout(() => (u ? document.getElementById('u-pass') : nm).focus(), 50);
}

function tickAll(on) {
    document.querySelectorAll('#u-access input').forEach(c => { c.checked = on; });
}

async function saveUser(e) {
    e.preventDefault();
    const access = [...document.querySelectorAll('#u-access input:checked')].map(c => c.value);
    const body = { password: document.getElementById('u-pass').value, access, note: document.getElementById('u-note').value };
    const btn = document.getElementById('u-save');
    btn.disabled = true;
    try {
        if (A.editing) {
            body.active = document.getElementById('u-active').checked;
            if (!body.password) delete body.password;
            await apiJson(`/api/admin/users/${A.editing.id}`, 'PUT', body);
            showToast(`${esc(A.editing.username)} saved`, 'success');
        } else {
            body.username = document.getElementById('u-name').value.trim();
            await apiJson('/api/admin/users', 'POST', body);
            showToast(`User ${esc(body.username)} created`, 'success');
        }
        closeModal('user-modal');
        loadUsers();
    } catch (err) {
        showToast(err.message, 'danger', 7000);
    }
    btn.disabled = false;
}

async function deleteUser(id) {
    const u = A.users.find(x => x.id === id);
    if (!(await confirmBox('Delete user?', `${u.username} can no longer log in.`))) return;
    try {
        await api(`/api/admin/users/${id}`, { method: 'DELETE' });
        loadUsers();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

// ------------------------------------------------------------------ safety: backups, cleared data, locked logins
const kb = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round((n || 0) / 1024)} KB`;
let _poll = null, _restoreName = '';

async function loadSafety() {
    let d;
    try { d = await api('/api/admin/safety'); } catch (e) {
        document.getElementById('backup-info').textContent = e.message; return;
    }
    const b = d.backup, last = b.last_nightly;
    const where = d.remote
        ? `Backups are made by the hub on the SDEW PC${d.agent && d.agent.online ? ` (${esc(d.agent.host)}, online)` : ' — <b>the PC is not connected now</b>'}.`
        : `Backups are saved in <b>${esc(b.dir)}</b>.`;
    document.getElementById('backup-info').innerHTML = `${where} Every night after ${b.hour}:00 (or as soon as the PC hub starts if it was off), kept ${b.keep_days} days. ` +
        (b.copy_dir ? `A copy goes to <b>${esc(b.copy_dir)}</b>. ` : 'No second copy yet — set <b>BACKUP_COPY_DIR</b> in .env on the PC (e.g. a Google Drive folder). ') +
        (last ? `Last nightly backup: <b>${esc(when(last.at))}</b>.` : '<b>No nightly backup yet.</b>');
    document.getElementById('backups-tbody').innerHTML = d.backups.length ? d.backups.map(x => `
        <tr style="${x.gone ? 'opacity:.5' : ''}"><td>${esc(when(x.at))}</td><td>${esc(x.reason)}</td><td>${esc(x.user || '')}</td>
            <td class="num">${(x.rows || 0).toLocaleString('en-IN')}</td><td class="num">${kb(x.size)}</td>
            <td>${x.copy ? (x.copy.startsWith('FAILED') ? '<span class="status-badge warn">copy failed</span>' : '<span class="status-badge active">yes</span>') : ''}</td>
            <td><div class="row-btns">${x.gone ? '<span class="muted">deleted (older than kept)</span>' : `
                ${!d.remote && x.here ? `<a class="btn btn-outline btn-sm" href="/api/admin/backup/file?name=${encodeURIComponent(x.name)}">Download</a>` : ''}
                <button class="btn btn-danger-text btn-sm" onclick="askRestore('${esc(x.name)}', '${esc(when(x.at))}')">Restore</button>`}</div></td></tr>`).join('')
        : '<tr><td colspan="7" class="muted-cell">No backups yet — press Back up now</td></tr>';
    document.getElementById('wipes-tbody').innerHTML = d.wipes.length ? d.wipes.map(w => `
        <tr><td>${esc(when(w.at))}</td><td>${esc(w.user || '')}</td><td>${esc(w.module)}</td><td>${esc(w.what)} <span class="muted">(${esc(JSON.parse(w.tables || '[]').join(', '))})</span></td>
            <td class="num">${(w.rows || 0).toLocaleString('en-IN')}</td>
            <td>${w.restored_at ? `<span class="muted">put back ${esc(when(w.restored_at))}</span>` : `<button class="btn btn-outline btn-sm" onclick="putBack(${w.id})">Put back</button>`}</td></tr>`).join('')
        : '<tr><td colspan="6" class="muted-cell">Nothing cleared</td></tr>';
    const lk = document.getElementById('locked-card');
    lk.style.display = d.locked.length ? '' : 'none';
    document.getElementById('locked-tbody').innerHTML = d.locked.map(l => `
        <tr><td class="strong">${esc(l.username)}</td><td>${esc(when(l.until))}</td><td>${l.fails}</td>
            <td><button class="btn btn-outline btn-sm" onclick="unlockLogin('${esc(l.username)}')">Unlock</button></td></tr>`).join('');
    showJob(d.job);
}

function showJob(st) {
    const box = document.getElementById('backup-log'), btn = document.getElementById('btn-backup');
    if (!st || (!st.running && !(st.log || []).length)) { box.style.display = 'none'; btn.disabled = false; return; }
    box.style.display = '';
    box.textContent = (st.log || []).join('\n') + (st.error ? `\nERROR: ${st.error}` : '');
    box.scrollTop = box.scrollHeight;
    btn.disabled = !!st.running;
    clearTimeout(_poll);
    if (st.running) _poll = setTimeout(async () => {
        try { const s = await api('/api/admin/backup/status'); if (s.running) showJob(s); else loadSafety(); } catch (e) { /* ignore */ }
    }, 2000);
}

async function backupNow() {
    try { showJob(await apiJson('/api/admin/backup', 'POST', {})); showToast('Backup started', 'success'); }
    catch (e) { showToast(e.message, 'danger', 8000); }
}

function askRestore(name, at) {
    _restoreName = name;
    document.getElementById('restore-text').innerHTML = `All data of the hub goes back to the backup of <b>${esc(at)}</b>. ` +
        'A backup of the data as it is now is made first, so this can be undone. Logins, the backup list and the activity list stay as they are.';
    document.getElementById('restore-confirm').value = '';
    openModal('restore-modal');
}

async function doRestore() {
    try {
        const st = await apiJson('/api/admin/restore', 'POST', { name: _restoreName, confirm: document.getElementById('restore-confirm').value });
        closeModal('restore-modal');
        showToast('Restore started — keep this page open', 'success');
        showJob(st);
    } catch (e) { showToast(e.message, 'danger', 8000); }
}

async function putBack(id) {
    if (!(await confirmBox('Put the cleared rows back?', 'Rows that are still there, or were added since, are kept.'))) return;
    try { const r = await apiJson(`/api/admin/wipes/${id}/restore`, 'POST', {}); showToast(`${r.rows} rows put back`, 'success'); loadSafety(); }
    catch (e) { showToast(e.message, 'danger', 8000); }
}

async function unlockLogin(username) {
    try { await apiJson('/api/admin/unlock', 'POST', { username }); showToast(`${esc(username)} unlocked`, 'success'); loadSafety(); }
    catch (e) { showToast(e.message, 'danger'); }
}

document.addEventListener('DOMContentLoaded', () => { loadUsers(); loadSafety(); });
