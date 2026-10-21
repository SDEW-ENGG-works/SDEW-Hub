// Shared helpers (same as SDEW Supplementary Bill): escaping, money / date formatting, API calls, toasts, confirm.

const appState = {
    settings: null, template: null, counts: {},
    batch: null,          // packing list on the Create page
    choices: {},          // line key -> CHEP size picked by hand
    selected: new Set(),  // ticked sheets
    preview: null,
};
const PAGE = 200;

function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function inr(n, dec = 2) {
    if (n === null || n === undefined || n === '') return '';
    return (parseFloat(n) || 0).toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function rupees(n) { return `₹${inr(n)}`; }
function qty(n) { return (parseFloat(n) || 0).toLocaleString('en-IN', { maximumFractionDigits: 3 }); }

// 'yyyy-mm-dd' -> '04-Apr-26'
function shortDate(iso) {
    if (!iso) return '';
    const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
    if (isNaN(d)) return String(iso);
    return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: '2-digit' }).replace(/ /g, '-');
}
// 'yyyy-mm-dd' -> '06/04/2026'
function dmy(iso) {
    if (!iso || iso.length < 10) return iso || '';
    return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
}
function when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

async function api(path, opts = {}) {
    const res = await fetch(path, opts);
    if (res.status === 401) { location.replace('/login.html'); throw new Error('Please log in'); }
    const isJson = (res.headers.get('content-type') || '').includes('json');
    const data = isJson ? await res.json() : await res.blob();
    if (!res.ok) throw new Error((data && data.error) || `Server error ${res.status}`);
    return data;
}
const apiJson = (path, method, body) =>
    api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

let _debounceTimer;
function debounced(fn, ms = 300) {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(fn, ms);
}

function setBusy(btn, busy, text) {
    if (!btn) return;
    if (busy) {
        btn.dataset.label = btn.innerHTML;
        btn.classList.add('loading');
        if (text) btn.textContent = text;
    } else {
        btn.classList.remove('loading');
        if (btn.dataset.label) btn.innerHTML = btn.dataset.label;
    }
}

function pager(el, total, offset, onPage) {
    if (total <= PAGE) { el.innerHTML = ''; return; }
    const page = Math.floor(offset / PAGE) + 1, pages = Math.ceil(total / PAGE);
    el.innerHTML = `
        <button class="btn btn-outline btn-sm" ${page <= 1 ? 'disabled' : ''} data-o="${offset - PAGE}">‹ Prev</button>
        <span>Page ${page} of ${pages}</span>
        <button class="btn btn-outline btn-sm" ${page >= pages ? 'disabled' : ''} data-o="${offset + PAGE}">Next ›</button>`;
    el.querySelectorAll('button').forEach(b => b.onclick = () => onPage(parseInt(b.dataset.o, 10)));
}

function howBadge(h) {
    const map = { 'packing list': ['active', 'Packing list'], 'part history': ['warn', 'Part history'],
        'chosen': ['sent', 'Chosen'], 'missing': ['inactive', 'Choose size'], 'carton': ['muted', 'Carton only'],
        'already': ['muted', 'Already sent'] };
    const [cls, label] = map[h] || ['muted', h];
    return `<span class="status-badge ${cls}">${esc(label)}</span>`;
}

// ---------- toasts ----------
function showToast(message, type = 'info', ms = 3600) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, ms);
}

// ---------- modals ----------
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

let _confirmResolve = null;
function confirmBox(title, text) {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    openModal('confirm-modal');
    return new Promise(r => { _confirmResolve = r; });
}
function closeConfirm(ok) {
    closeModal('confirm-modal');
    if (_confirmResolve) _confirmResolve(ok);
    _confirmResolve = null;
}
