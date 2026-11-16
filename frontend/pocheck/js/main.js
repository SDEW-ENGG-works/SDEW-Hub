// PO Price Check: uploads (TAFE Excel, new PO .htm, old PO .htm) and the two checks.
const PC = { which: null, data: null, filter: 'issues' };

const LABELS = {
    excel: {
        different: ['red', 'Different'], not_amended: ['amber', 'Not amended in PO'], old_differs: ['amber', 'Existing differs'],
        not_in_po: ['grey', 'Not in POs'], not_in_excel: ['blue', 'Not in Excel'], same: ['green', 'Same'],
    },
    changes: {
        decreased: ['red', 'Decreased'], increased: ['amber', 'Increased'], new_part: ['blue', 'New part'], removed: ['red', 'Removed'],
        no_old: ['grey', 'No old price'], same: ['green', 'No change'],
    },
};
const ISSUES = { excel: ['different', 'not_amended', 'old_differs'], changes: ['decreased', 'increased', 'new_part', 'removed'] };
const pill = (which, s) => { const l = LABELS[which][s] || ['grey', s]; return `<span class="pc-b ${l[0]}">${esc(l[1])}</span>`; };
const money = v => (v === null || v === undefined || v === '') ? '' : inr(v);
const d = iso => iso ? dmy(iso) : '';

async function loadFiles() {
    let f;
    try { f = await api('/api/pocheck/files'); } catch (e) { showToast(e.message, 'danger'); return; }
    for (const k of ['excel', 'new', 'old']) {
        const list = f[k] || [];
        document.getElementById(`n-${k}`).textContent = list.length ? `· ${list.length} file${list.length > 1 ? 's' : ''}` : '';
        document.getElementById(`f-${k}`).innerHTML = list.map(x => `<li title="${esc(x.name)}"><span>${esc(k === 'excel' ? (x.doc || x.name) : x.po_no)}</span>
            <span class="n">${x.count} ${k === 'excel' ? 'parts' : 'lines'} <button title="Remove" onclick="removeFile(${x.id})">✕</button></span></li>`).join('')
            || '<li><span class="muted">nothing yet</span></li>';
    }
}

async function uploadFiles(fileList, kind) {
    const box = document.getElementById('upload-msgs');
    box.innerHTML = '';
    let ok = 0, bad = 0;
    for (const f of [...fileList]) {
        const row = document.createElement('div');
        row.className = 'upload-row';
        row.innerHTML = `<span class="status-badge muted">…</span><span class="file">${esc(f.name)}</span><span class="msg">Reading…</span>`;
        box.appendChild(row);
        try {
            const r = await api(`/api/pocheck/upload?kind=${kind}&name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
            row.querySelector('.status-badge').className = 'status-badge active';
            row.querySelector('.status-badge').textContent = 'OK';
            row.querySelector('.msg').textContent = r.message;
            ok++;
        } catch (e) {
            row.classList.add('err');
            row.querySelector('.status-badge').className = 'status-badge inactive';
            row.querySelector('.status-badge').textContent = 'Error';
            row.querySelector('.msg').textContent = e.message;
            bad++;
        }
    }
    showToast(`${ok} file(s) loaded${bad ? `, ${bad} not read` : ''}`, bad ? 'danger' : 'success');
    loadFiles();
    if (PC.which) runCheck(PC.which, true);
}

async function removeFile(id) {
    try { await api(`/api/pocheck/files?id=${id}`, { method: 'DELETE' }); } catch (e) { showToast(e.message, 'danger'); }
    loadFiles();
}

async function clearAll() {
    if (!(await confirmBox('Clear all uploads?', 'The Excel and PO files uploaded here are removed (the hub\'s PO data is not touched).'))) return;
    await api('/api/pocheck/files', { method: 'DELETE' });
    document.getElementById('result-card').style.display = 'none';
    PC.which = null;
    loadFiles();
}

async function runCheck(which, quiet) {
    PC.which = which;
    document.getElementById('btn-excel').classList.toggle('active', which === 'excel');
    document.getElementById('btn-changes').classList.toggle('active', which === 'changes');
    const card = document.getElementById('result-card');
    try {
        PC.data = await api(which === 'excel' ? '/api/pocheck/excel-check' : '/api/pocheck/price-changes');
    } catch (e) {
        if (!quiet) showToast(e.message, 'danger', 6000);
        card.style.display = 'none';
        return;
    }
    PC.filter = (ISSUES[which].some(k => PC.data.summary[k])) ? 'issues' : 'all';
    card.style.display = '';
    const s = PC.data.summary;
    if (which === 'excel') {
        document.getElementById('result-title').textContent = 'Excel verifier — TAFE Excel vs new PO';
        document.getElementById('result-hint').innerHTML = `Excel ${PC.data.excel.map(x => `<b>${esc(x.doc || x.name)}</b> (${x.parts} parts)`).join(', ')} against <b>${PC.data.pos}</b> new PO file(s).
            The PO price is taken on the Excel's <b>Price Effective Date</b> (revised) and on the day before (existing). PO price = Gross (basic) price.`;
    } else {
        document.getElementById('result-title').textContent = 'PO price changes — old PO vs new PO';
        document.getElementById('result-hint').innerHTML = `<b>${PC.data.pos}</b> new PO file(s), <b>${PC.data.old_files}</b> old PO file(s); POs without an old file use the hub's PO data.
            Old price = the old PO's price on the new price's "valid from" date. Average change of the changed parts: <b>${PC.data.avg_pct}%</b>.`;
    }
    const total = Object.values(s).reduce((a, b) => a + b, 0);
    const chips = [['issues', 'Needs a look', ISSUES[which].reduce((a, k) => a + (s[k] || 0), 0)], ['all', 'All', total]]
        .concat(Object.keys(LABELS[which]).filter(k => s[k]).map(k => [k, LABELS[which][k][1], s[k]]));
    document.getElementById('result-sum').innerHTML = chips.map(c => `<span class="pc-chip ${PC.filter === c[0] ? 'on' : ''}" onclick="setFilter('${c[0]}')">${esc(c[1])}<b>${c[2]}</b></span>`).join('');
    renderRows();
    if (!quiet) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setFilter(f) { PC.filter = f; runCheckChips(); renderRows(); }
function runCheckChips() {
    document.querySelectorAll('#result-sum .pc-chip').forEach(c => c.classList.toggle('on', c.getAttribute('onclick') === `setFilter('${PC.filter}')`));
}

function renderRows() {
    const which = PC.which, q = document.getElementById('result-q').value.trim().toLowerCase();
    let rows = (PC.data.rows || []).filter(r => PC.filter === 'all' ? true : PC.filter === 'issues' ? ISSUES[which].includes(r.status) : r.status === PC.filter);
    if (q) rows = rows.filter(r => [r.part, r.po_no, r.descr, r.plant].some(v => String(v || '').toLowerCase().includes(q)));
    const shown = rows.slice(0, 1500);
    let head, body;
    if (which === 'excel') {
        head = ['Result', 'Plant', 'PO', 'Line', 'Part', 'Description', 'Excel existing', 'Excel revised', 'Effective', 'PO before', 'PO from effective', 'PO latest', 'Note'];
        body = shown.map(r => `<tr><td>${pill(which, r.status)}</td><td>${esc(r.plant || '')}</td><td class="mono">${esc(r.po_no || '')}</td><td class="num">${esc(r.line || '')}</td>
            <td class="mono">${esc(r.part)}</td><td>${esc(r.descr || '')}</td><td class="num">${money(r.excel_old)}</td><td class="num"><b>${money(r.excel_new)}</b></td>
            <td>${d(r.effective)}</td><td class="num">${money(r.po_old)}</td><td class="num"><b>${money(r.po_new)}</b></td>
            <td class="num">${money(r.po_last)}${r.po_last_from ? ` <span class="muted">from ${d(r.po_last_from)}</span>` : ''}</td><td>${esc(r.note || '')}</td></tr>`);
    } else {
        head = ['Result', 'Plant', 'PO', 'Line', 'Part', 'Description', 'Old price', 'New price', 'Valid from', 'Change ₹', 'Change %', 'Old price from', 'Note'];
        body = shown.map(r => {
            const cls = r.change > 0 ? 'pc-up-pos' : r.change < 0 ? 'pc-up-neg' : '';
            const rev = (r.revisions || []).length > 1 ? '<br><span class="muted">' + r.revisions.map(x => `${inr(x.rate)} from ${d(x.frm)}`).join(' · ') + '</span>' : '';
            return `<tr><td>${pill(which, r.status)}</td><td>${esc(r.plant || '')}</td><td class="mono">${esc(r.po_no)}</td><td class="num">${esc(r.line || '')}</td>
            <td class="mono">${esc(r.part)}</td><td>${esc(r.descr || '')}</td><td class="num">${money(r.old_rate)}</td><td class="num"><b>${money(r.new_rate)}</b></td>
            <td>${d(r.valid_from)}</td><td class="num ${cls}">${r.change === undefined ? '' : (r.change > 0 ? '+' : '') + inr(r.change)}</td>
            <td class="num ${cls}">${r.pct === null || r.pct === undefined ? '' : (r.pct > 0 ? '+' : '') + r.pct.toFixed(2) + '%'}</td>
            <td>${esc(r.source || '')}</td><td>${esc(r.note || '')}${rev}</td></tr>`;
        });
    }
    document.getElementById('result-table').innerHTML = `<thead><tr>${head.map((h, i) => `<th class="${i >= 6 && i <= 11 && !/from|Effective|Valid/.test(h) ? 'num' : ''}">${esc(h)}</th>`).join('')}</tr></thead>
        <tbody>${body.join('') || `<tr><td colspan="${head.length}" class="muted-cell">Nothing here</td></tr>`}</tbody>`;
    document.getElementById('result-more').textContent = rows.length > shown.length ? `First ${shown.length} of ${rows.length} rows - Download Excel for all.` : '';
}

function downloadResult() {
    downloadFile(`/api/pocheck/export?which=${PC.which === 'excel' ? 'excel' : 'changes'}`, document.getElementById('btn-download'), 'po_check.xlsx');
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.dropzone[data-kind]').forEach(z => {
        z.addEventListener('dragover', e => { e.preventDefault(); z.classList.add('over'); });
        z.addEventListener('dragleave', () => z.classList.remove('over'));
        z.addEventListener('drop', e => { e.preventDefault(); z.classList.remove('over'); uploadFiles(e.dataTransfer.files, z.dataset.kind); });
    });
    loadFiles();
});
