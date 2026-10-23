// SDEW Hub - works like apps on a phone.
//   Home (/)        the Sri Durga logo + "SDEW Hub" and a grid of app icons. Tap one to open it.
//   Inside an app   a slim bar: "← Back" (to Home), the app's name, who is logged in, Log out.
// Users see only the apps the admin gave them (window.HUB_USER, put in the page by the server).
// Links like /supp/#pos open that tab of a module page, and the address follows the tab you open.
(function () {
    const path = location.pathname;
    const here = path.startsWith('/supp') ? 'supp' : path.startsWith('/chep') ? 'chep' : path.startsWith('/dqms') ? 'dqms'
        : path.startsWith('/grin') ? 'grin' : path.startsWith('/pay') ? 'pay' : path.startsWith('/admin') ? 'admin' : 'hub';
    const ME = window.HUB_USER || { access: null, admin: false, user: '' };
    const can = k => !ME.access || ME.access.includes(k);
    const ic = d => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
    // key, link, name, colour, icon, hub view
    const APPS = [
        ['today', '/#today', 'Today', '#1e3a5f', ic('<rect x="3" y="3" width="7" height="9"/><rect x="14" y="3" width="7" height="5"/><rect x="14" y="12" width="7" height="9"/><rect x="3" y="16" width="7" height="5"/>'), 'today'],
        ['supp', '/supp/', 'Supplementary Bill', '#2f6fb3', ic('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="13" y2="17"/>')],
        ['chep', '/chep/', 'CHEP Transfer', '#17806d', ic('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.3 7 12 12 20.7 7"/><line x1="12" y1="22" x2="12" y2="12"/>')],
        ['dqms', '/dqms/', 'DQMS Upload', '#6b46c1', ic('<polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.4 18.4A5 5 0 0 0 18 9h-1.3A8 8 0 1 0 3 16.3"/>')],
        ['grin', '/grin/', 'GRIN & Payments', '#c2410c', ic('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>')],
        ['pay', '/pay/', 'Payments', '#15803d', ic('<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="6" y1="15" x2="10" y2="15"/>')],
        ['find', '/#find', 'Find & trace', '#0e7490', ic('<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.6" y2="16.6"/>'), 'find'],
        ['drop', '/#drop', 'Drop files', '#475569', ic('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'), 'drop'],
        ['items', '/#items', 'Follow-ups', '#b45309', ic('<path d="M9 11l3 3L22 4"/><line x1="3" y1="6" x2="7" y2="6"/><line x1="3" y1="12" x2="7" y2="12"/><line x1="3" y1="18" x2="7" y2="18"/>'), 'items'],
        ['masters', '/#masters', 'Masters', '#334155', ic('<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'), 'masters'],
        ['admin', '/admin/', 'Admin', '#9f1239', ic('<path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/><circle cx="12" cy="11" r="3"/>')],
    ].filter(a => a[0] === 'admin' ? (ME.admin && ME.login) : can(a[0]));

    const hubView = () => decodeURIComponent(location.hash.replace('#', '')).split('=')[0];
    const isHome = () => here === 'hub' && (!hubView() || hubView() === 'home');
    const current = () => {
        if (here !== 'hub') return APPS.find(a => a[0] === here);
        const v = hubView() === 'inv' || hubView() === 'part' || hubView() === 'po' || hubView() === 'dr' ? 'find' : hubView();
        return APPS.find(a => a[5] === v);
    };
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const userBits = `${ME.user ? `<span class="hub-user">${esc(ME.user)}</span>` : ''}
        <button class="hub-out" id="hub-out" style="display:none" onclick="hubLogout()">Log out</button>`;

    // ---------- Home: the app grid
    const home = document.createElement('main');
    home.className = 'hub-home';
    home.innerHTML = `
        <div class="hub-home-top"><span class="hub-db" id="hub-db"></span>${userBits}</div>
        <div class="hub-home-brand">
            <img src="/assets/sdew-logo.jpg" alt="Sri Durga Engg. Works">
            <h1>SDEW Hub</h1>
            <p>Sri Durga Engg. Works · TAFE order to payment</p>
        </div>
        ${can('find') ? `<form class="hub-home-search" id="hub-search-form" autocomplete="off">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.6" y2="16.6"></line></svg>
            <input type="search" id="hub-search-input" placeholder="Search invoice, part, PO, DR, GRIN…" aria-label="Search the hub">
        </form>` : ''}
        <nav class="hub-apps" aria-label="Apps">
            ${APPS.map(a => `<a class="hub-app" href="${a[1]}" data-mod="${a[0]}">
                <span class="hub-app-ic" style="--c:${a[3]}">${a[4]}</span>
                <span class="hub-app-name">${a[2]}</span></a>`).join('')}
        </nav>`;

    // ---------- inside an app: back bar
    const bar = document.createElement('header');
    bar.className = 'hub-appbar';
    function drawBar() {
        const a = current();
        bar.innerHTML = `<div class="hub-appbar-in">
            <a class="hub-back" href="/" id="hub-back" title="Home - all apps">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/></svg>
                <span>Home</span></a>
            <span class="hub-appbar-title">${a ? `<span class="hub-app-ic sm" style="--c:${a[3]}">${a[4]}</span>${a[2]}` : 'SDEW Hub'}</span>
            <span class="hub-spacer"></span>
            <img class="hub-appbar-logo" src="/assets/sdew-logo.jpg" alt="Sri Durga Engg. Works">
            ${userBits}
        </div>`;
        bar.querySelector('#hub-back').addEventListener('click', e => {
            if (here === 'hub') { e.preventDefault(); location.hash = ''; }
        });
        showOut();
    }

    function layout() {
        const onHome = isHome();
        document.body.classList.toggle('hub-on-home', onHome);
        if (!onHome) drawBar();
    }

    let authInfo = null;
    function showOut() {
        if (authInfo && authInfo.login) document.querySelectorAll('#hub-out').forEach(b => { b.style.display = ''; });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.body.classList.add('hub-has-head', `hub-page-${here}`);
        document.body.insertBefore(bar, document.body.firstChild);
        if (here === 'hub') document.body.insertBefore(home, document.body.firstChild);
        layout();
        window.addEventListener('hashchange', layout);
        const f = document.getElementById('hub-search-form');
        if (f) f.addEventListener('submit', e => {
            e.preventDefault();
            const q = document.getElementById('hub-search-input').value.trim();
            if (!q) return;
            if (here === 'hub') { location.hash = 'find=' + encodeURIComponent(q); return; }
            location.href = '/#find=' + encodeURIComponent(q);
        });
        fetch('/api/auth').then(r => r.json()).then(a => { authInfo = a; showOut(); }).catch(() => { });
        if (here === 'hub' && can('today')) hubBadges();
        // module pages: open the tab named in the address (/supp/#pos) and keep the address in step
        if (here !== 'hub' && typeof window.switchView === 'function') {
            const orig = window.switchView;
            window.switchView = function (name) {
                orig(name);
                try { history.replaceState(null, '', '#' + name); } catch (e) { /* ignore */ }
            };
            const want = location.hash.replace('#', '');
            if (want && document.getElementById(`nav-${want}-btn`)) setTimeout(() => window.switchView(want), 60);
        }
    });

    // little numbers on the app icons: how many checks need attention there
    window.hubBadges = function (data) {
        const apply = d => {
            const db = document.getElementById('hub-db');
            if (db && d.db_mode) db.textContent = d.db_mode === 'cloud' ? 'Cloud data' : 'Data on this PC';
            const per = {};
            (d.checks || []).forEach(c => {
                const m = c.module === 'pos' ? 'supp' : (c.module === 'cross' || c.module === 'hub') ? 'today' : c.module;
                if (c.count) per[m] = (per[m] || 0) + 1;
            });
            if (d.open_items) per.items = (d.open_items || []).filter(x => x.status !== 'done').length;
            home.querySelectorAll('.hub-app[data-mod]').forEach(a => {
                const n = per[a.dataset.mod] || 0;
                a.querySelector('.n')?.remove();
                if (n) a.querySelector('.hub-app-ic').insertAdjacentHTML('beforeend', `<span class="n">${n}</span>`);
            });
        };
        if (data) return apply(data);
        fetch('/api/hub/overview').then(r => r.ok ? r.json() : null).then(o => {
            if (o) apply({ db_mode: o.db_mode, checks: o.checks, open_items: o.open_items });
        }).catch(() => { });
    };

    window.hubLogout = async function () {
        try { await fetch('/api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
        location.replace('/login.html');
    };
})();
