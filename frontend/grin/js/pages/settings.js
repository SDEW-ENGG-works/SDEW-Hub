// Settings: rules, reminder mail text, Tally companies.

const S = { companies: [] };
const S_FIELDS = ['wait_days', 'credit_days', 'resend_days', 'from_date', 'test_to', 'escalate_after', 'escalate_cc',
    'mail_subject', 'mail_intro', 'signature', 'tally_url'];

async function loadSettingsPage() {
    try {
        const d = await api('/api/grin/settings');
        const s = d.settings;
        appState.grinSettings = s;
        S_FIELDS.forEach(f => { document.getElementById(`s-${f}`).value = s[f] ?? ''; });
        document.getElementById('s-track_plants_without_grin').checked = !!s.track_plants_without_grin;
        document.getElementById('s-ignore_doc_types').value = (s.ignore_doc_types || []).join(', ');
        S.companies = (s.tally_companies || []).map(c => ({ ...c }));
        renderCompanies();
        document.getElementById('smtp-state').innerHTML = d.smtp.ready
            ? `<span class="status-badge active">Ready</span> sending through <b>${esc(d.smtp.host)}:${d.smtp.port}</b> as <b>${esc(d.smtp.sender)}</b>`
            : `<span class="status-badge warn">Not set up</span> add these lines to <b>.env</b> in the SDEWHub folder:`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

function renderCompanies() {
    document.getElementById('companies-tbody').innerHTML = S.companies.length ? S.companies.map((c, i) => `<tr>
        <td><input value="${esc(c.name)}" oninput="S.companies[${i}].name=this.value" placeholder="exact Tally company name"></td>
        <td><input value="${esc(c.location || '')}" oninput="S.companies[${i}].location=this.value" placeholder="Chennai"></td>
        <td><button class="btn btn-danger-text btn-sm" onclick="S.companies.splice(${i},1);renderCompanies()">Remove</button></td></tr>`).join('')
        : `<tr><td colspan="3" class="muted-cell">The company open in Tally is read</td></tr>`;
}

function addCompany() {
    S.companies.push({ name: '', location: '' });
    renderCompanies();
}

async function saveSettings() {
    const body = {};
    S_FIELDS.forEach(f => { body[f] = document.getElementById(`s-${f}`).value; });
    body.track_plants_without_grin = document.getElementById('s-track_plants_without_grin').checked;
    body.ignore_doc_types = document.getElementById('s-ignore_doc_types').value.split(',').map(x => x.trim()).filter(Boolean);
    body.tally_companies = S.companies.filter(c => c.name.trim());
    try {
        const r = await apiJson('/api/grin/settings', 'PUT', body);
        appState.grinSettings = r.settings;
        showToast('Settings saved', 'success');
        loadSettingsPage();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
