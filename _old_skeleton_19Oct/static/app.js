"use strict";
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {credentials: "same-origin", ...opts});
  if (res.status === 401) { showLogin(); throw new Error("login"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
const post = (path, body) => api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});

/* ---------- login ---------- */
function showLogin() { $("#login").hidden = false; $("#pw").focus(); }
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await post("/api/login", {password: $("#pw").value}); $("#login").hidden = true; render(); }
  catch (err) { $("#loginMsg").textContent = err.message === "login" ? "Wrong password." : err.message; }
});
$("#logout").addEventListener("click", async () => { await post("/api/logout"); showLogin(); });

/* ---------- the order-to-payment chain ---------- */
const STAGES = [
  {route: "pos", name: "POs & pricing", table: "pos", app: "supp", src: "Supplementary Bill app"},
  {route: "drs", name: "Delivery requests", table: "drs", app: "dqms", src: "DQMS app (DR PDFs)"},
  {route: "invoices", name: "Invoices", table: "invoices", app: null, src: "Tally sync - later"},
  {route: "chep", name: "Dispatch & CHEP", table: "chep_transfers", app: "chep", src: "CHEP Transfer app"},
  {route: "dqms", name: "DQMS upload", table: "dqms_uploads", app: "dqms", src: "DQMS Upload app"},
  {route: "grin", name: "GRIN", table: "grin", app: "supp", src: "Supplementary Bill app"},
  {route: "supp", name: "Supplementary bill", table: null, app: "supp", src: "Supplementary Bill app"},
];
const APP_NAMES = {supp: "Supplementary Bill", chep: "CHEP Transfer", dqms: "DQMS Upload"};

/* ---------- pages ---------- */
async function pageHome() {
  const [st, ex, oi] = await Promise.all([api("/api/status"), api("/api/exceptions"), api("/api/open-items")]);
  const chain = STAGES.map((s, i) => {
    const n = s.table ? (st.counts[s.table] ?? 0) : "";
    const cls = s.app ? "old" : "todo";
    return `<a class="stage ${cls}" href="#/${s.route}"><span class="bar"></span>
      <div class="n">Step ${i + 1}</div><div class="name">${s.name}</div>
      <div class="count">${n === "" ? "&nbsp;" : n}</div><div class="src">${s.src}</div></a>`;
  }).join("");
  const exRows = ex.rules.filter((r) => r.count).map((r) =>
    `<li><span class="tag">${esc(r.module)}</span><span class="grow">${esc(r.title)}</span><span class="num">${r.count}</span></li>`).join("");
  const open = oi.items.filter((i) => i.status === "open").slice(0, 8).map((i) =>
    `<li><span class="tag">${esc(i.module)}</span><span class="grow">${esc(i.title)}<small>${esc(i.detail)}</small></span></li>`).join("");
  const apps = st.legacy.map((a) =>
    `<li><span class="grow"><span class="dot ${a.running ? "up" : "down"}"></span>${esc(a.name)}
      <small>${a.copied ? `Port ${a.port} - ${a.running ? "running" : "stopped"}` : "Not copied yet - run setup"}</small></span>
      ${a.copied && !a.running ? `<button class="btn small" data-start="${a.key}">Start</button>` : ""}</li>`).join("");
  main.innerHTML = `
    <h1>Order to payment</h1>
    <p class="lead">Every TAFE order moves through these seven steps. Counts are records in the hub's own database; steps still run inside the copied apps until their data is moved over.</p>
    <div class="chain">${chain}</div>
    <div class="legend"><span class="l-old">Runs in a copied app for now</span><span class="l-todo">Not built yet</span><span class="l-live">Fully in the hub</span></div>
    <div class="cols">
      <section class="panel"><h2>Needs attention</h2>
        ${exRows ? `<ul class="list">${exRows}</ul>` : `<p class="lead">Nothing flagged. Checks run on hub data, so this fills up once invoices, CHEP and GRIN records are moved in.</p>`}
        <p><a href="#/exceptions">See all checks</a></p></section>
      <section class="panel"><h2>Open items</h2><ul class="list">${open || "<li>None open.</li>"}</ul>
        <p><a href="#/open-items">All open items</a></p></section>
    </div>
    <section class="panel" style="margin-top:22px"><h2>Copied apps</h2><ul class="list">${apps}</ul></section>`;
  main.querySelectorAll("[data-start]").forEach((b) => b.addEventListener("click", () => startApp(b.dataset.start)));
}

async function startApp(key) {
  const r = await post(`/api/legacy/${key}/start`);
  toast(r.message);
  setTimeout(render, 2500);
}

function toast(msg) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status");
    t.style.cssText = "position:fixed;bottom:18px;right:18px;background:#1e2a32;color:#fff;padding:10px 16px;border-radius:8px;z-index:20";
    document.body.appendChild(t); }
  t.textContent = msg; t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 3500);
}

/* Generic table view of a hub table */
async function tableView(el, table, opts = {}) {
  let offset = 0, q = "";
  const pageSize = 200;
  async function load() {
    const d = await api(`/api/table/${table}?limit=${pageSize}&offset=${offset}&q=${encodeURIComponent(q)}`);
    const head = d.columns.map((c) => `<th>${esc(c)}</th>`).join("") + (d.editable ? "<th></th>" : "");
    const body = d.rows.map((r, i) => `<tr>${d.columns.map((c) => {
      const v = r[c]; const isNum = typeof v === "number";
      return `<td class="${isNum ? "numc" : ""}" title="${esc(v)}">${esc(v)}</td>`; }).join("")}
      ${d.editable ? `<td><button class="btn small" data-edit="${i}">Edit</button></td>` : ""}</tr>`).join("");
    el.innerHTML = `
      <div class="toolbar"><input type="search" placeholder="Search" value="${esc(q)}" aria-label="Search ${table}">
        <span class="grow"></span><span>${d.total} rows</span>
        ${offset > 0 ? `<button class="btn small" data-p="-1">Previous</button>` : ""}
        ${offset + pageSize < d.total ? `<button class="btn small" data-p="1">Next</button>` : ""}
        ${d.editable ? `<button class="btn primary small" data-add>Add</button>` : ""}</div>
      <div class="grid-wrap">${d.rows.length ? `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`
        : `<div class="empty">${esc(opts.empty || "No rows yet.")}</div>`}</div>`;
    const s = $("input[type=search]", el);
    s.addEventListener("change", () => { q = s.value; offset = 0; load(); });
    el.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => { offset += +b.dataset.p * pageSize; load(); }));
    el.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => editRow(d, d.rows[+b.dataset.edit], load)));
    const add = $("[data-add]", el); if (add) add.addEventListener("click", () => editRow(d, null, load));
  }
  await load();
}

function editRow(d, row, reload) {
  const dlg = document.createElement("dialog");
  const cols = d.columns.filter((c) => !(c === "id" && !row));
  dlg.innerHTML = `<form method="dialog"><h2>${row ? "Edit" : "Add"} - ${esc(d.table)}</h2>
    <div class="form-grid">${cols.map((c) => `<label for="f_${c}">${esc(c)}</label>
      <input id="f_${c}" name="${c}" value="${esc(row ? row[c] : "")}" ${c === "id" ? "readonly" : ""}>`).join("")}</div>
    <p class="msg-err"></p>
    <div class="dlg-actions">${row ? `<button class="btn" value="delete" type="button" data-del>Delete</button>` : ""}
      <span style="flex:1"></span><button class="btn" value="cancel">Cancel</button>
      <button class="btn primary" type="submit" value="save" data-save>Save</button></div></form>`;
  document.body.appendChild(dlg); dlg.showModal();
  dlg.addEventListener("close", () => dlg.remove());
  $("[data-save]", dlg).addEventListener("click", async (e) => {
    e.preventDefault();
    const out = {}; cols.forEach((c) => (out[c] = $(`#f_${c}`, dlg).value));
    try { await post(`/api/table/${d.table}`, {row: out, original_key: row ? row[d.key] : null}); dlg.close(); reload(); }
    catch (err) { $(".msg-err", dlg).textContent = err.message; }
  });
  const del = $("[data-del]", dlg);
  if (del) del.addEventListener("click", async () => {
    if (!confirm("Delete this row?")) return;
    await post(`/api/table/${d.table}/delete`, {key: row[d.key]}); dlg.close(); reload();
  });
}

/* Pages for hub-owned data: POs, DRs, invoices, GRIN */
const DATA_PAGES = {
  pos: {title: "POs & pricing", table: "pos", extra: ["po_lines", "po_prices"],
    lead: "Every TAFE PO with its lines and date-wise rates. This is the single price list the invoice, DQMS and supplementary bill checks use.",
    where: "PO files are still loaded in the Supplementary Bill app. Moving them here comes after the migration mapping."},
  drs: {title: "Delivery requests", table: "drs",
    lead: "TAFE's delivery requests: what to dispatch, how many bins, and the unit size DQMS needs.",
    where: "DR PDFs are read by the DQMS app today. Drop them on Drop files to keep them in one place."},
  invoices: {title: "Invoices", table: "invoices", extra: ["invoice_lines"],
    lead: "The record every later step hangs off. Once the Tally sync is built (on site at SDEW), invoices land here automatically.",
    where: "Until then, each app reads invoices from its own files: Sales Register (Supplementary Bill), packing list (CHEP), invoice PDFs (DQMS)."},
  grin: {title: "GRIN", table: "grin",
    lead: "TAFE's goods receipts, matched to our invoices. An invoice with no GRIN can't be claimed.",
    where: "GRIN is fetched and matched in the Supplementary Bill app today."},
};

async function pageData(key) {
  const p = DATA_PAGES[key];
  const tabs = [p.table, ...(p.extra || [])];
  main.innerHTML = `<h1>${p.title}</h1><p class="lead">${p.lead}</p><div class="note">${p.where}</div>
    <div class="tabs" role="tablist">${tabs.map((t, i) => `<button role="tab" class="${i ? "" : "on"}" data-t="${t}">${t}</button>`).join("")}</div>
    <div id="tv"></div>`;
  const show = (t) => tableView($("#tv"), t, {empty: "No records in the hub yet."});
  main.querySelectorAll("[data-t]").forEach((b) => b.addEventListener("click", () => {
    main.querySelectorAll("[data-t]").forEach((x) => x.classList.toggle("on", x === b)); show(b.dataset.t); }));
  await show(p.table);
}

/* Pages that run a copied app inside the hub */
const APP_PAGES = {
  chep: {title: "Dispatch & CHEP", app: "chep",
    lead: "Packing list to CHEP BulkTransfer file, LEAP upload and reconciliation."},
  dqms: {title: "DQMS upload", app: "dqms",
    lead: "Invoices, DRs and the batch report into TAFE Channel's DQMS bulk upload file."},
  supp: {title: "Supplementary bill", app: "supp",
    lead: "Rate revision claims: PO old and new rates, GRIN match, pending lists."},
};

async function pageApp(key) {
  const p = APP_PAGES[key];
  const {apps} = await api("/api/legacy");
  const a = apps.find((x) => x.key === p.app);
  let body;
  if (!a.copied) body = `<div class="note">This app hasn't been copied into the hub yet. Close the hub and run <b>python tools\\setup_from_existing.py</b>.</div>`;
  else if (!a.running) body = `<div class="status-line"><span><span class="dot down"></span>Stopped</span>
      <button class="btn primary" data-start="${a.key}">Start ${esc(a.name)}</button></div>`;
  else body = `<div class="status-line"><span><span class="dot up"></span>Running on port ${a.port}</span>
      <a class="btn small" href="${a.url}" target="_blank" rel="noopener">Open in its own tab</a>
      ${a.started_by_hub ? `<button class="btn small" data-stop="${a.key}">Stop</button>` : ""}</div>
      <iframe class="frame" src="${a.url}" title="${esc(a.name)}"></iframe>`;
  main.innerHTML = `<h1>${p.title}</h1><p class="lead">${p.lead} Running from the copy in legacy\\${esc(a.name.replace(/ /g, ""))}, so the original folder is untouched.</p>${body}`;
  main.querySelectorAll("[data-start]").forEach((b) => b.addEventListener("click", () => startApp(b.dataset.start)));
  main.querySelectorAll("[data-stop]").forEach((b) => b.addEventListener("click", async () => { toast((await post(`/api/legacy/${b.dataset.stop}/stop`)).message); setTimeout(render, 800); }));
}

async function pageExceptions() {
  const {rules} = await api("/api/exceptions");
  main.innerHTML = `<h1>Needs attention</h1>
    <p class="lead">Checks across all steps. Each one looks at hub data, so a check shows 0 until that data is in the hub.</p>
    ${rules.map((r) => `<section class="panel" style="margin-bottom:14px"><h2>${esc(r.title)} <span class="num">(${r.count})</span></h2>
      ${r.count ? `<div class="grid-wrap"><table><thead><tr><th>Ref</th><th>Date</th><th>Plant</th><th>Detail</th></tr></thead><tbody>
        ${r.items.map((i) => `<tr><td>${esc(i.ref)}</td><td>${esc(i.date)}</td><td>${esc(i.plant)}</td><td>${esc(i.detail)}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="lead" style="margin:0">Nothing flagged.</p>`}</section>`).join("")}`;
}

async function pageOpenItems() {
  const {items} = await api("/api/open-items");
  const row = (i) => `<li><span class="tag">${esc(i.module)}</span><span class="grow">${esc(i.title)}<small>${esc(i.detail)}</small></span>
    <button class="btn small" data-id="${i.id}" data-s="${i.status === "open" ? "done" : "open"}">${i.status === "open" ? "Mark done" : "Reopen"}</button></li>`;
  main.innerHTML = `<h1>Open items</h1><p class="lead">Questions and follow-ups carried over from the separate apps, in one list.</p>
    <form id="addItem" class="toolbar"><select name="module" aria-label="Module">
      ${["hub", "pos", "drs", "invoices", "chep", "dqms", "grin", "supp"].map((m) => `<option>${m}</option>`).join("")}</select>
      <input name="title" placeholder="What needs doing" required style="flex:1" aria-label="Title">
      <input name="detail" placeholder="Detail" style="flex:1" aria-label="Detail">
      <button class="btn primary">Add item</button></form>
    <section class="panel"><h2>Open</h2><ul class="list">${items.filter((i) => i.status === "open").map(row).join("") || "<li>None.</li>"}</ul></section>
    <section class="panel" style="margin-top:16px"><h2>Done</h2><ul class="list">${items.filter((i) => i.status !== "open").map(row).join("") || "<li>None yet.</li>"}</ul></section>`;
  $("#addItem").addEventListener("submit", async (e) => {
    e.preventDefault(); const f = new FormData(e.target);
    await post("/api/open-items", Object.fromEntries(f)); render(); });
  main.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", async () => {
    await post("/api/open-items", {id: +b.dataset.id, status: b.dataset.s}); render(); }));
}

async function pageMasters() {
  const tabs = [["plants", "Plants"], ["parts", "Parts"], ["crate_sizes", "Crate sizes"], ["part_corrections", "Part corrections"],
    ["fixed_rates", "Fixed rates"], ["reason_codes", "Reason codes"], ["settings", "Settings"]];
  main.innerHTML = `<h1>Masters</h1><p class="lead">One copy of the facts every step relies on. Fix a wrong part number or plant code here once, instead of in each app.</p>
    <div class="tabs" role="tablist">${tabs.map(([t, l], i) => `<button role="tab" class="${i ? "" : "on"}" data-t="${t}">${l}</button>`).join("")}</div><div id="tv"></div>`;
  const show = (t) => tableView($("#tv"), t);
  main.querySelectorAll("[data-t]").forEach((b) => b.addEventListener("click", () => {
    main.querySelectorAll("[data-t]").forEach((x) => x.classList.toggle("on", x === b)); show(b.dataset.t); }));
  await show("plants");
}

async function pageInbox() {
  main.innerHTML = `<h1>Drop files</h1>
    <p class="lead">Drop any SDEW or TAFE file here: POs, TAFE exports, GRIN, Sales Register, packing lists, LEAP MIS, DQMS report, DR and invoice PDFs. The hub works out what each file is and which step it belongs to.</p>
    <label class="drop" id="drop" tabindex="0">Drop files here or click to choose<input type="file" multiple hidden id="fileIn"></label>
    <h2>Received</h2><div id="tv"></div>`;
  const drop = $("#drop"), input = $("#fileIn");
  const send = async (files) => {
    for (const f of files) {
      try {
        const r = await api("/api/inbox", {method: "POST", headers: {"X-Filename": encodeURIComponent(f.name)}, body: f});
        toast(`${f.name}: ${r.label}${r.legacy ? ` - load it in ${APP_NAMES[r.legacy]}` : ""}`);
      } catch (err) { toast(`${f.name}: ${err.message}`); }
    }
    tableView($("#tv"), "inbox");
  };
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); send(e.dataTransfer.files); });
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
  input.addEventListener("change", () => send(input.files));
  await tableView($("#tv"), "inbox", {empty: "Nothing dropped yet."});
}

async function pageLegacyData() {
  main.innerHTML = `<h1>Old app data</h1><p class="lead">Read-only view of the databases copied from the separate apps. Use it to plan how each table moves into the hub.</p>
    <div class="tabs" role="tablist">${["supp", "chep", "dqms"].map((k, i) => `<button role="tab" class="${i ? "" : "on"}" data-k="${k}">${APP_NAMES[k]}</button>`).join("")}</div>
    <div id="lt"></div>`;
  const show = async (k) => {
    const {tables} = await api(`/api/legacy/${k}/tables`);
    const el = $("#lt");
    if (!tables.length) { el.innerHTML = `<div class="empty">No database copied for this app yet.</div>`; return; }
    el.innerHTML = `<div class="toolbar"><select id="tsel" aria-label="Table">${tables.map((t) => `<option value="${esc(t.table)}">${esc(t.table)} (${t.rows})</option>`).join("")}</select></div><div id="ltv"></div>`;
    const load = async () => {
      const d = await api(`/api/legacy/${k}/table/${$("#tsel").value}`);
      $("#ltv").innerHTML = `<div class="grid-wrap"><table><thead><tr>${d.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.rows.map((r) => `<tr>${d.columns.map((c) => `<td title="${esc(r[c])}">${esc(r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
        <p class="lead">Showing ${d.rows.length} of ${d.total}.</p>`;
    };
    $("#tsel").addEventListener("change", load); load();
  };
  main.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => {
    main.querySelectorAll("[data-k]").forEach((x) => x.classList.toggle("on", x === b)); show(b.dataset.k); }));
  show("supp");
}

/* ---------- router ---------- */
const ROUTES = {
  "": pageHome, inbox: pageInbox, exceptions: pageExceptions, "open-items": pageOpenItems,
  masters: pageMasters, "legacy-data": pageLegacyData,
  pos: () => pageData("pos"), drs: () => pageData("drs"), invoices: () => pageData("invoices"), grin: () => pageData("grin"),
  chep: () => pageApp("chep"), dqms: () => pageApp("dqms"), supp: () => pageApp("supp"),
};

async function badges() {
  try {
    const st = await api("/api/status");
    const e = $("#excBadge"), o = $("#openBadge");
    e.hidden = !st.exceptions; e.textContent = st.exceptions;
    o.hidden = !st.open_items; o.textContent = st.open_items;
    $("#logout").hidden = !st.login;
  } catch (_) { /* login shown */ }
}

async function render() {
  const key = location.hash.replace(/^#\/?/, "").split("?")[0];
  document.querySelectorAll(".side a:not(.brand)").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === `#/${key}`));
  try { await (ROUTES[key] || pageHome)(); badges(); }
  catch (err) { if (err.message !== "login") main.innerHTML = `<h1>Something went wrong</h1><p class="msg-err">${esc(err.message)}</p><p><a href="#/">Back to Today</a></p>`; }
  main.focus({preventScroll: true});
}
window.addEventListener("hashchange", render);
render();
