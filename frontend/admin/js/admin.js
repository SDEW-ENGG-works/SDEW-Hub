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

document.addEventListener('DOMContentLoaded', loadUsers);
