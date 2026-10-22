// The SDEW Hub strip at the top of every page (hub + Supplementary Bill + CHEP + DQMS + GRIN & Payments + Payments).
// - switches between the modules, shows how many checks need attention
// - one search box for invoice / part / PO / DR / GRIN numbers (opens the hub's Find page)
// - links like /supp/#pos open that tab of a module page, and the address follows the tab you open
(function () {
    const path = location.pathname;
    const here = path.startsWith('/supp') ? 'supp' : path.startsWith('/chep') ? 'chep' : path.startsWith('/dqms') ? 'dqms' : path.startsWith('/grin') ? 'grin' : path.startsWith('/pay') ? 'pay' : 'hub';
    const tabs = [
        ['hub', '/', 'Today', ''],
        ['supp', '/supp/', 'Supplementary Bill', 'Supp. Bill'],
        ['chep', '/chep/', 'CHEP Transfer', 'CHEP'],
        ['dqms', '/dqms/', 'DQMS Upload', 'DQMS'],
        ['grin', '/grin/', 'GRIN & Payments', 'GRIN'],
        ['pay', '/pay/', 'Payments', 'Payments'],
    ];
    const bar = document.createElement('div');
    bar.className = 'hub-bar';
    bar.innerHTML = `<div class="hub-bar-inner">
        <a class="hub-mark" href="/"><span class="sq">SD</span><span class="t">SDEW Hub</span></a>
        ${tabs.map(([k, href, long]) => `<a class="hub-tab ${k === here ? 'active' : ''}" href="${href}" data-mod="${k}">${long}</a>`).join('')}
        <span class="hub-spacer"></span>
        <form class="hub-search" id="hub-search-form" autocomplete="off">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.6" y2="16.6"></line></svg>
            <input type="search" id="hub-search-input" placeholder="Invoice, part, PO, DR, GRIN…" aria-label="Search the hub">
        </form>
        <span class="hub-db" id="hub-db" title="Where the hub keeps its data"></span>
        <button class="hub-out" id="hub-out" style="display:none" onclick="hubLogout()">Log out</button>
    </div>`;
    document.addEventListener('DOMContentLoaded', () => {
        document.body.insertBefore(bar, document.body.firstChild);
        document.getElementById('hub-search-form').addEventListener('submit', e => {
            e.preventDefault();
            const q = document.getElementById('hub-search-input').value.trim();
            if (!q) return;
            if (here === 'hub' && typeof window.hubFind === 'function') { window.hubFind(q); return; }
            location.href = '/#find=' + encodeURIComponent(q);
        });
        fetch('/api/auth').then(r => r.json()).then(a => {
            if (a.login) document.getElementById('hub-out').style.display = '';
        }).catch(() => { });
        if (here !== 'hub') hubBadges();
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

    window.hubBadges = function (data) {
        const apply = d => {
            const db = document.getElementById('hub-db');
            if (db && d.db_mode) db.textContent = d.db_mode === 'cloud' ? 'Cloud data' : 'Data on this PC';
            const per = {};
            (d.checks || []).forEach(c => {
                const m = c.module === 'pos' ? 'supp' : c.module;
                if (c.count) per[m] = (per[m] || 0) + 1;
            });
            document.querySelectorAll('.hub-tab[data-mod]').forEach(a => {
                const m = a.dataset.mod;
                const n = m === 'hub' ? (per.cross || 0) + (per.hub || 0) : per[m] || 0;
                a.querySelector('.n')?.remove();
                if (n) a.insertAdjacentHTML('beforeend', `<span class="n" title="${n} check(s) need attention">${n}</span>`);
            });
        };
        if (data) return apply(data);
        fetch('/api/hub/overview').then(r => r.ok ? r.json() : null).then(o => {
            if (o) apply({ db_mode: o.db_mode, checks: o.checks });
        }).catch(() => { });
    };

    window.hubLogout = async function () {
        try { await fetch('/api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
        location.replace('/login.html');
    };
})();
