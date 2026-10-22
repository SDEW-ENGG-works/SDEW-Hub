// Sales marking page: GRN NO / GRN DATE / GRN QTY in the TAFE SALES DETAILS file from the hub's GRIN lines.

const salesState = { file: null, grin: null, run: null, cat: '', offset: 0 };
let _grinTimer = null;

const SALES_INFO = {
    'Fill GRN': { cls: 'active', help: 'TAFE has GRINed it and the file has no GRN yet — GRN NO, GRN DATE and GRN QTY (accepted) are written.' },
    'Add GRN QTY': { cls: 'active', help: 'GRN NO in the file agrees with TAFE — only the accepted quantity is added in GRN QTY.' },
    'Short / rejected': { cls: 'warn', help: 'TAFE accepted less than the invoice quantity. The accepted quantity is written as it is — follow up the shortage / rejection.' },
    'Inspection open': { cls: 'warn', help: 'GRIN made but TAFE has not finished inspection (accepted and rejected are 0) — GRN NO and date are written, GRN QTY is left blank.' },
    'GRN no differs': { cls: 'inactive', help: 'The GRN NO typed in the file is not the TAFE GRIN for this invoice + part (often rows shifted by one). Not changed unless you tick it.' },
    'GRN QTY differs': { cls: 'inactive', help: 'GRN QTY in the file is not the accepted quantity on TAFE GRIN. Not changed unless you tick it.' },
    'Already complete': { cls: 'sent', help: 'GRN NO, date and GRN QTY already agree with TAFE — nothing to do.' },
    'GRIN pending': { cls: 'muted', help: 'TAFE plant invoice with no GRIN yet in the hub (GRIN data date shown above). Fetch GRIN again later.' },
    'Not in GRIN data': { cls: 'inactive', help: 'No matching TAFE GRIN line for this row — the file may have a GRN the hub never fetched, or the part is different. Check by hand.' },
    'Not a GRIN party': { cls: 'muted', help: 'R&D, FED, J REHAB, TI Clean Mobility, Simpson … — no TAFE GRIN for these parties. Left as they are.' },
};
const SALES_ORDER = Object.keys(SALES_INFO);
const SALES_LOCKED = new Set(['Already complete', 'GRIN pending', 'Not in GRIN data', 'Not a GRIN party']);

function salesBadge(c) {
    return `<span class="status-badge ${(SALES_INFO[c] || {}).cls || 'muted'}">${esc(c)}</span>`;
}

async function refreshSales() {
    try {
        const d = await api('/api/pay/sales/bootstrap');
        salesState.file = d.file;
        salesState.grin = d.grin;
        salesState.run = d.run;
    } catch (e) {
        showToast(`Could not load sales data: ${e.message}`, 'danger');
    }
}

function renderSales() {
    const f = salesState.file, g = salesState.grin || {}, run = salesState.run;
    document.getElementById('src-sales').classList.toggle('ready', !!f);
    document.getElementById('src-sales-sub').textContent = f ? f.name : 'Not uploaded';
    document.getElementById('src-sales-body').innerHTML = f ? `
        <span class="chip"><b>${inr(f.info.lines, 0)}</b> lines</span>
        <span class="chip"><b>${inr(f.info.with_grn, 0)}</b> with GRN NO</span>
        <span class="chip"><b>${inr(f.info.with_qty, 0)}</b> with GRN QTY</span>
        ${f.info.has_qty_col ? '' : '<span class="chip warn-chip">No GRN QTY column</span>'}` : '';
    document.getElementById('src-grin').classList.toggle('ready', !!g.n);
    document.getElementById('src-grin-sub').textContent = g.n ? `GRIN up to ${shortDate(g.last)} · fetched ${when(g.updated)}` : 'No GRIN in the hub yet';
    document.getElementById('src-grin-body').innerHTML = g.n ? `
        <span class="chip"><b>${inr(g.grins, 0)}</b> GRINs</span>
        <span class="chip"><b>${inr(g.n, 0)}</b> lines</span>` : '';

    const set = (id, v) => { document.getElementById(id).textContent = v; };
    document.getElementById('btn-sales-marked').disabled = !run;
    document.getElementById('btn-sales-report').disabled = !run;
    if (!run) {
        ['ss-mark', 'ss-agree', 'ss-look', 'ss-pending'].forEach(id => set(id, '—'));
        document.getElementById('sales-count-badge').textContent = '0';
        document.getElementById('grin-extra-card').style.display = 'none';
        renderSalesPills();
        return;
    }
    const s = run.summary, c = s.cats;
    const n = k => (c[k] || {}).n || 0;
    set('ss-mark', inr(s.to_mark, 0));
    set('ss-mark-sub', `${inr(c['Fill GRN'].marking, 0)} new GRN · ${inr(c['Add GRN QTY'].marking, 0)} GRN QTY only`);
    set('ss-agree', `${inr(s.agree, 0)}`);
    set('ss-agree-sub', `of ${inr(s.typed, 0)} GRN NOs typed by hand`);
    set('ss-look', inr(n('GRN no differs') + n('GRN QTY differs') + n('Short / rejected') + n('Not in GRIN data'), 0));
    set('ss-look-sub', `${inr(n('GRN no differs'), 0)} GRN no · ${inr(n('Short / rejected'), 0)} short · ${inr(n('Not in GRIN data'), 0)} not in GRIN`);
    set('ss-pending', inr(n('GRIN pending'), 0));
    set('ss-pending-sub', `GRIN data up to ${dmy(s.grin_upto)}`);
    document.getElementById('sales-count-badge').textContent = inr(s.to_mark, 0);

    const extra = s.grin_not_in_file || [];
    document.getElementById('grin-extra-card').style.display = extra.length ? '' : 'none';
    document.getElementById('grin-extra-hint').textContent =
        `${inr(s.grin_not_in_file_n, 0)} GRIN line(s) since the file's first invoice whose invoice number is not in the file (newest first${s.grin_not_in_file_n > extra.length ? `, first ${extra.length} shown` : ''}). Usually invoices not yet added to the file, or typed with another number.`;
    document.getElementById('grin-extra-tbody').innerHTML = extra.map(g => `
        <tr><td><b>${esc(g.grin_no)}</b></td><td>${dmy(g.grin_date)}</td><td>${esc(g.invoice_no)}</td><td>${esc(g.part_no)}</td>
        <td class="num">${qty(g.grin_qty)}</td><td>${esc(g.plant)}</td></tr>`).join('');
    renderSalesPills();
}

function renderSalesPills() {
    const run = salesState.run;
    const c = run ? run.summary.cats : {};
    const pill = (key, label, count) => `<button class="cat-pill ${salesState.cat === key ? 'active' : ''}" data-c="${esc(key)}">
        ${esc(label)}<span class="pill-count">${inr(count, 0)}</span></button>`;
    document.getElementById('sales-pills').innerHTML = !run ? '' :
        pill('', 'All', run.summary.lines) + pill('marking', 'Being written', run.summary.to_mark) +
        SALES_ORDER.filter(k => (c[k] || {}).n).map(k => pill(k, k, c[k].n)).join('');
    document.querySelectorAll('#sales-pills .cat-pill').forEach(b => b.onclick = () => {
        salesState.cat = b.dataset.c;
        renderSalesPills();
        loadSalesLines(0);
    });
    const help = document.getElementById('sales-help');
    const info = SALES_INFO[salesState.cat];
    if (run && info) {
        const cc = c[salesState.cat];
        const bulk = SALES_LOCKED.has(salesState.cat) ? '' : `
            <div class="btn-row">
                <button class="btn btn-outline btn-sm" onclick="setSalesCategory('mark')">Tick all ${inr(cc.n, 0)}</button>
                <button class="btn btn-outline btn-sm" onclick="setSalesCategory('skip')">Untick all</button>
            </div>`;
        help.innerHTML = `<span>${esc(info.help)}</span>${bulk}`;
        help.style.display = '';
    } else {
        help.style.display = 'none';
    }
}

async function loadSalesLines(offset = 0) {
    salesState.offset = offset;
    const tbody = document.getElementById('sales-tbody');
    if (!salesState.run) {
        tbody.innerHTML = `<tr><td colspan="15" class="muted-cell">Upload the sales file, then press Check GRN</td></tr>`;
        document.getElementById('sales-total-text').textContent = '';
        document.getElementById('sales-pager').innerHTML = '';
        return;
    }
    const q = encodeURIComponent(document.getElementById('sales-search').value.trim());
    try {
        const d = await api(`/api/pay/sales/lines?cat=${encodeURIComponent(salesState.cat)}&q=${q}&limit=${PAGE}&offset=${offset}`);
        tbody.innerHTML = d.lines.length ? d.lines.map(l => {
            const canTick = l.grin_no && !SALES_LOCKED.has(l.cat);
            const box = canTick
                ? `<input type="checkbox" class="mark-box" data-seq="${l.seq}" ${l.action === 'mark' ? 'checked' : ''}>`
                : (l.cat === 'Already complete' ? '<span class="tick-done">✓</span>' : '');
            const differs = l.sheet_gno && l.grin_no && l.sheet_gno !== l.grin_no;
            return `<tr class="${l.action === 'mark' ? 'row-mark' : ''}">
                <td class="center">${box}</td><td>${salesBadge(l.cat)}</td><td class="num">${l.row}</td><td><b>${esc(l.inv)}</b></td>
                <td>${dmy(l.inv_date)}</td><td>${esc(l.part)}</td><td class="num">${l.qty != null ? qty(l.qty) : ''}</td>
                <td class="${differs ? 'bad' : ''}">${esc(l.sheet_gno) || '<span class="stat-sub">blank</span>'}</td><td>${esc(l.sheet_gdate)}</td>
                <td class="num">${l.sheet_gqty != null ? qty(l.sheet_gqty) : ''}</td>
                <td><b>${esc(l.grin_no)}</b></td><td>${dmy(l.grin_date)}</td>
                <td class="num">${l.acc_qty != null ? qty(l.acc_qty) : ''}</td><td class="num">${l.rej_qty ? qty(l.rej_qty) : ''}</td>
                <td class="wrap stat-sub">${esc(l.note)}</td></tr>`;
        }).join('') : `<tr><td colspan="15" class="muted-cell">Nothing here</td></tr>`;
        tbody.querySelectorAll('.mark-box').forEach(cb => cb.onchange = () => setSalesAction(cb));
        document.getElementById('sales-total-text').innerHTML = `<b>${inr(d.total, 0)}</b> lines`;
        pager(document.getElementById('sales-pager'), d.total, offset, o => loadSalesLines(o));
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function setSalesAction(cb) {
    try {
        salesState.run = await apiJson(`/api/pay/sales/lines/${cb.dataset.seq}`, 'PUT', { action: cb.checked ? 'mark' : 'skip' });
        cb.closest('tr').classList.toggle('row-mark', cb.checked);
        renderSales();
    } catch (e) {
        cb.checked = !cb.checked;
        showToast(e.message, 'danger');
    }
}

async function setSalesCategory(action) {
    try {
        salesState.run = await apiJson('/api/pay/sales/category', 'PUT', { cat: salesState.cat, action });
        renderSales();
        loadSalesLines(salesState.offset);
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function runSalesCheck() {
    if (!salesState.file) return showToast('Upload the TAFE SALES DETAILS file first.', 'danger');
    const btn = document.getElementById('btn-sales-check');
    setBusy(btn, true, 'Checking…');
    try {
        salesState.run = await apiJson('/api/pay/sales/check', 'POST', {});
        salesState.cat = salesState.run.summary.to_mark ? 'marking' : '';
        renderSales();
        loadSalesLines(0);
        const s = salesState.run.summary;
        showToast(`${inr(s.to_mark, 0)} lines to write · ${inr(s.cats['GRN no differs'].n, 0)} GRN no differs · ${inr(s.cats['GRIN pending'].n, 0)} GRIN pending`, 'success', 5000);
    } catch (e) {
        showToast(e.message, 'danger');
    } finally {
        setBusy(btn, false);
    }
}

// Fetch GRIN = the hub's TAFE Channel fetch (Supplementary Bill > GRIN). On the website the SDEW PC does it.
async function salesFetchGrin() {
    const btn = document.getElementById('btn-grin-fetch');
    btn.disabled = true;
    const g = salesState.grin || {};
    const to = new Date().toISOString().slice(0, 10);
    const last = g.last ? new Date(`${g.last}T00:00:00`) : new Date();
    last.setDate(last.getDate() - 45);
    const from = last.toISOString().slice(0, 10);
    try {
        const r = await apiJson('/api/supp/grin/sync', 'POST', { from, to });
        showGrinLog(r);
        if (r.done) return grinFetched(r);
        _grinTimer = setInterval(async () => {
            try {
                const st = await api('/api/supp/grin/sync');
                showGrinLog(st);
                if (!st.running) {
                    clearInterval(_grinTimer);
                    grinFetched(st);
                }
            } catch (e) {
                clearInterval(_grinTimer);
                btn.disabled = false;
                showToast(e.message, 'danger');
            }
        }, 3000);
    } catch (e) {
        btn.disabled = false;
        showToast(e.message, 'danger');
    }
}

function showGrinLog(st) {
    const box = document.getElementById('grin-fetch-log');
    const log = (st && st.log) || [];
    box.style.display = log.length ? '' : 'none';
    box.textContent = log.join('\n');
    box.scrollTop = box.scrollHeight;
}

async function grinFetched(st) {
    document.getElementById('btn-grin-fetch').disabled = false;
    if (st && st.error) { showToast(`Fetch GRIN: ${esc(st.error)}`, 'danger', 7000); return; }
    await refreshSales();
    renderSales();
    showToast(`GRIN fetched — data up to ${shortDate((salesState.grin || {}).last)}. Checking the sales file again…`, 'success');
    if (salesState.file) runSalesCheck();
}

async function downloadSalesMarked() {
    const run = salesState.run;
    if (!run) return;
    const name = await downloadFile('/api/pay/sales/export/marked', document.getElementById('btn-sales-marked'), 'TAFE_SALES_DETAILS_GRN.xlsx');
    if (name) {
        showToast(`${inr(run.summary.to_mark, 0)} lines written in <b>${esc(name)}</b>. That file is now the sales file — the next check starts from it.`, 'success', 7000);
        await refreshSales();
        renderSales();
    }
}

function downloadSalesReport() {
    downloadFile('/api/pay/sales/export/report', document.getElementById('btn-sales-report'), 'Sales_GRN_Check.xlsx');
}
