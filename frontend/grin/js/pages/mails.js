// Reminders: one mail per buyer, preview, send (SMTP) or download as .eml, history.

const M = { plan: null };

function mailAsOf() {
    const a = document.getElementById('as-of').value;
    return a ? `as_of=${a}` : '';
}

async function loadMails() {
    const box = document.getElementById('drafts');
    box.innerHTML = '<div class="card"><p class="hint">Working out who to remind…</p></div>';
    try {
        const p = await api(`/api/grin/mails/plan?${mailAsOf()}`);
        M.plan = p;
        const ready = p.drafts.filter(d => !d.problem);
        const nInv = p.drafts.reduce((a, d) => a + d.invoices.length, 0);
        document.getElementById('mail-badge').textContent = p.drafts.length;
        const b = [];
        if (p.test_to) b.push(`<div class="banner info"><b>Test mode:</b> every mail goes to <b>${esc(p.test_to)}</b>, not to the buyers. Clear it on Settings when you are happy.</div>`);
        if (!p.smtp.ready) b.push(`<div class="banner">Mail sending is not set up yet (SMTP in the hub's .env — see Settings). You can still <b>Download .eml</b> and send it from Outlook, then press <b>Mark sent</b> in the list below.</div>`);
        document.getElementById('mail-banners').innerHTML = b.join('');
        const btn = document.getElementById('btn-send-all');
        btn.disabled = !ready.length || !p.smtp.ready;
        btn.lastChild.textContent = ` Send all ready (${ready.length})`;
        box.innerHTML = p.drafts.length ? p.drafts.map(draftHtml).join('')
            : `<div class="card"><p class="hint">Nothing to send — no invoice is waiting for GRIN longer than the wait days (or all were reminded recently).</p></div>`;
        box.querySelectorAll('[data-act]').forEach(el => el.onclick = () => draftAction(el.dataset.act, el.dataset.key));
        const sk = document.getElementById('skipped-card');
        sk.style.display = p.skipped.length ? '' : 'none';
        document.getElementById('skipped-list').innerHTML = p.skipped.map(s => `<span class="chip">${esc(s.inv_no)} · ${esc(s.why)}</span>`).join('');
        document.getElementById('m-resend').textContent = (appState.grinSettings || {}).resend_days ?? 3;
    } catch (e) {
        box.innerHTML = `<div class="card"><p class="hint">${esc(e.message)}</p></div>`;
    }
    loadMailHistory();
}

function draftHtml(d) {
    const total = d.invoices.reduce((a, i) => a + (i.amount || 0), 0);
    return `<div class="draft" id="draft-${esc(d.key)}">
        <div class="draft-head">
            <div><div class="who">${esc(d.buyer || 'No buyer')} · ${esc(d.plant)} · ${d.invoices.length} invoice(s) · ₹${inr(total, 0)}</div>
                <div class="addr ${d.problem ? 'bad' : ''}">${d.problem ? esc(d.problem) : `To ${esc(d.to)}${d.cc ? ` · CC ${esc(d.cc)}` : ''}`}
                ${d.escalated.length ? ` · <b>escalation CC</b> for ${d.escalated.length} invoice(s)` : ''}</div></div>
            <div class="btn-row">
                <button class="btn btn-outline btn-sm" data-act="preview" data-key="${esc(d.key)}">Preview</button>
                <button class="btn btn-outline btn-sm" data-act="eml" data-key="${esc(d.key)}">Download .eml</button>
                ${d.problem ? `<button class="btn btn-outline btn-sm" onclick="switchView('buyers')">Add buyer</button>`
                    : `<button class="btn btn-primary btn-sm" data-act="send" data-key="${esc(d.key)}" ${M.plan.smtp.ready ? '' : 'disabled'}>Send</button>`}
            </div>
        </div>
        <div class="table-wrapper"><table class="data-table compact">
            <thead><tr><th>Invoice</th><th>Date</th><th>PO</th><th>Parts</th><th class="num">Value</th><th class="num">Days</th><th class="num">Reminder #</th></tr></thead>
            <tbody>${d.invoices.map(i => `<tr><td class="strong">${esc(i.inv_no)}</td><td>${dmy(i.inv_date)}</td><td>${esc(i.order_no || '')}</td>
                <td>${esc(i.parts)}</td><td class="num">${i.amount ? inr(i.amount) : ''}</td><td class="num">${i.age ?? ''}</td>
                <td class="num">${i.reminders + 1}</td></tr>`).join('')}</tbody></table></div>
    </div>`;
}

async function draftAction(act, key) {
    const d = (M.plan.drafts || []).find(x => x.key === key);
    if (!d) return;
    if (act === 'preview') {
        const to = M.plan.test_to ? `${M.plan.test_to} (test mode — buyer: ${d.to || 'none'})` : (d.to || '—');
        document.getElementById('mail-meta').innerHTML = `<b>To:</b> ${esc(to)}<br>${d.cc && !M.plan.test_to ? `<b>CC:</b> ${esc(d.cc)}<br>` : ''}<b>From:</b> ${esc(M.plan.smtp.sender || '(SMTP not set)')}<br><b>Subject:</b> ${esc(d.subject)}`;
        document.getElementById('mail-preview').innerHTML = d.html;
        openModal('mail-modal');
    } else if (act === 'eml') {
        window.location.href = `/api/grin/mails/eml?key=${encodeURIComponent(key)}&${mailAsOf()}`;
        setTimeout(loadMailHistory, 1200);
    } else if (act === 'send') {
        if (!(await confirmBox('Send this mail?', `${d.invoices.length} invoice(s) to ${M.plan.test_to || d.to}`))) return;
        await sendDrafts([key]);
    }
}

async function sendAll() {
    const ready = (M.plan?.drafts || []).filter(d => !d.problem);
    if (!ready.length) return;
    const n = ready.reduce((a, d) => a + d.invoices.length, 0);
    if (!(await confirmBox('Send all GRIN reminders?', `${ready.length} mail(s), ${n} invoice(s)${M.plan.test_to ? ` — TEST MODE, all to ${M.plan.test_to}` : ''}`))) return;
    await sendDrafts(ready.map(d => d.key));
}

async function sendDrafts(keys) {
    const btn = document.getElementById('btn-send-all');
    setBusy(btn, true, 'Sending…');
    try {
        const asOf = document.getElementById('as-of').value;
        const r = await apiJson('/api/grin/mails/send', 'POST', { keys, as_of: asOf || undefined });
        const ok = r.results.filter(x => x.ok).length, bad = r.results.filter(x => !x.ok);
        if (ok) showToast(`${ok} mail(s) ${r.test_to ? 'sent to the test address' : 'sent'}`, 'success', 5000);
        bad.forEach(x => showToast(`Not sent: ${esc(x.error)}`, 'danger', 8000));
    } catch (e) {
        showToast(e.message, 'danger', 8000);
    }
    setBusy(btn, false);
    loadMails();
    loadStatus();
}

async function loadMailHistory() {
    try {
        const h = await api('/api/grin/mails/history');
        const cls = { Sent: 'active', Test: 'sent', Draft: 'warn', Failed: 'inactive' };
        document.getElementById('mail-history').innerHTML = h.length ? h.map(m => `<tr>
            <td>${esc(when(m.sent_at || m.created_at))}</td><td><span class="status-badge ${cls[m.status] || 'muted'}">${esc(m.status === 'Draft' ? '.eml saved' : m.status)}</span>${m.error ? `<span class="sub" title="${esc(m.error)}"> ${esc(m.error.slice(0, 60))}</span>` : ''}</td>
            <td>${esc(m.buyer || '')}</td><td>${esc(m.to_addr || '')}</td><td>${esc(m.cc || '')}</td>
            <td class="num">${m.invoices.length}</td><td style="white-space:normal;max-width:360px;font-size:0.74rem">${esc(m.invoices.join(', '))}</td>
            <td>${m.status === 'Draft' ? `<button class="btn btn-outline btn-sm" onclick="markSent(${m.id})">Mark sent</button>` : ''}</td></tr>`).join('')
            : `<tr><td colspan="8" class="muted-cell">No mails yet</td></tr>`;
    } catch (e) {
        showToast(e.message, 'danger');
    }
}

async function markSent(id) {
    try {
        await apiJson(`/api/grin/mails/${id}/sent`, 'POST', {});
        showToast('Marked as sent — these invoices count as reminded today', 'success');
        loadMails();
    } catch (e) {
        showToast(e.message, 'danger');
    }
}
