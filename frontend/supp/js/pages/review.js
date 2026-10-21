// Review page: lines not in the bill, with the reason.

function renderReviewPills() {
    const s = appState.run && appState.run.summary;
    const plants = s ? s.plants.filter(p => Object.keys(p.cats).some(c => c !== 'Bill')) : [];
    const count = p => Object.entries(p.cats).filter(([k]) => k !== 'Bill').reduce((a, [, v]) => a + v.lines, 0);
    document.getElementById('review-plant-pills').innerHTML =
        `<button class="cat-pill ${!appState.reviewPlant ? 'active' : ''}" onclick="pickReviewPlant('')">All</button>` +
        plants.map(p => `<button class="cat-pill ${p.plant === appState.reviewPlant ? 'active' : ''}" onclick="pickReviewPlant('${esc(p.plant)}')">
            ${esc(p.plant)}<span class="pill-count">${inr(count(p), 0)}</span></button>`).join('');
}

function pickReviewPlant(p) {
    appState.reviewPlant = p;
    renderReviewPills();
    loadReview(0);
}

async function loadReview(offset = 0) {
    appState.reviewOffset = offset;
    const tbody = document.getElementById('review-tbody');
    if (!appState.run) {
        tbody.innerHTML = `<tr><td colspan="15" class="muted-cell">No bill yet — press Calculate bill on the Bill page</td></tr>`;
        return;
    }
    const cat = document.getElementById('review-cat').value;
    const q = encodeURIComponent(document.getElementById('review-search').value.trim());
    try {
        const d = await api(`/api/supp/bill/lines?plant=${encodeURIComponent(appState.reviewPlant)}&cat=${encodeURIComponent(cat)}&q=${q}&limit=${PAGE}&offset=${offset}`);
        // one chip per reason; all "PO … not uploaded" reasons together in one chip
        const chips = [];
        let poMissing = { n: 0, pos: 0 };
        d.reasons.forEach(r => {
            if (/^PO .* not uploaded$/.test(r.reason)) { poMissing.n += r.n; poMissing.pos++; }
            else chips.push({ label: r.reason, search: r.reason, n: r.n, v: r.v });
        });
        if (poMissing.n) chips.unshift({ label: `PO not uploaded (${poMissing.pos} POs)`, search: 'not uploaded', n: poMissing.n, v: 0 });
        document.getElementById('review-reasons').innerHTML = chips.map(c =>
            `<span class="chip click" data-s="${esc(c.search)}">${esc(c.label)} · <b>${inr(c.n, 0)}</b>${c.v ? ` · ${rupees(c.v)}` : ''}</span>`).join('');
        document.querySelectorAll('#review-reasons .chip').forEach(ch => ch.onclick = () => {
            document.getElementById('review-search').value = ch.dataset.s;
            loadReview(0);
        });
        tbody.innerHTML = d.lines.length ? d.lines.map(l => `
            <tr><td><b>${esc(l.plant)}</b></td><td>${catBadge(l.cat)}</td><td class="wrap">${esc(l.reason)}</td>
            <td>${esc(l.voucher)}</td><td>${shortDate(l.inv_date)}</td><td>${esc(l.po_no)}</td><td><b>${esc(l.part)}</b></td>
            <td class="wrap">${esc(l.descr)}</td><td class="num">${qty(l.qty)}</td><td class="num">${inr(l.rate)}</td>
            <td class="num">${inr(l.old_rate)}</td><td class="num">${inr(l.new_rate)}</td><td class="num strong">${inr(l.value)}</td>
            <td>${esc(l.grn_no)}</td><td class="wrap stat-sub">${esc(l.notes)}</td></tr>`).join('')
            : `<tr><td colspan="15" class="muted-cell">Nothing here</td></tr>`;
        document.getElementById('review-total-text').innerHTML = `<b>${inr(d.total, 0)}</b> lines`;
        pager(document.getElementById('review-pager'), d.total, offset, o => loadReview(o));
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
