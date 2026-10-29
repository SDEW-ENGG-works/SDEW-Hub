// "Save to my file": remembers WHERE the register / sales file came from on this computer and writes the marked
// version straight back into that same file (File System Access API - Chrome and Edge, on localhost or https).
//
// - The file is linked when it is chosen with the drop box (click) or dragged in.
// - The link is kept in this browser (IndexedDB), so after a reload "Save" still knows the file.
// - Before writing, the file on disk is compared with the one that was uploaded (size + time). If it was changed
//   in the meantime (e.g. rows coloured in Excel), nothing is written - upload it again first, so no work is lost.
// - Every uploaded version stays in the app (Uploads page > download), so an earlier version can always be taken back.

const fsFile = (() => {
    const supported = typeof window.showOpenFilePicker === 'function';
    const DB = 'sdew-pay-files', STORE = 'handles';
    const EXCEL = [{ description: 'Excel', accept: {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx', '.xlsm'],
        'application/vnd.ms-excel': ['.xls'] } }];

    function db() {
        return new Promise((ok, bad) => {
            const r = indexedDB.open(DB, 1);
            r.onupgradeneeded = () => r.result.createObjectStore(STORE);
            r.onsuccess = () => ok(r.result);
            r.onerror = () => bad(r.error);
        });
    }
    async function put(key, value) {
        try {
            const d = await db();
            await new Promise((ok, bad) => {
                const t = d.transaction(STORE, 'readwrite');
                value === undefined ? t.objectStore(STORE).delete(key) : t.objectStore(STORE).put(value, key);
                t.oncomplete = ok; t.onerror = () => bad(t.error);
            });
        } catch (e) { /* private window etc. - the link just is not remembered */ }
    }
    async function get(key) {
        try {
            const d = await db();
            return await new Promise((ok, bad) => {
                const r = d.transaction(STORE).objectStore(STORE).get(key);
                r.onsuccess = () => ok(r.result || null); r.onerror = () => bad(r.error);
            });
        } catch (e) { return null; }
    }

    // drop event: the handles must be taken synchronously, before any await
    function handlesFromDrop(e) {
        if (!supported || !e.dataTransfer || !e.dataTransfer.items) return null;
        const items = [...e.dataTransfer.items].filter(i => i.kind === 'file');
        if (!items.length || typeof items[0].getAsFileSystemHandle !== 'function') return null;
        return items.map(i => i.getAsFileSystemHandle());      // promises
    }

    async function pick(multiple = true) {
        const hs = await window.showOpenFilePicker({ multiple, types: EXCEL, excludeAcceptAllOption: false });
        const files = await Promise.all(hs.map(h => h.getFile()));
        return { handles: hs, files };
    }

    // after an upload: kind 'register' / 'sales'
    async function link(kind, handle, file, fileId) {
        if (!handle) return;
        await put(kind, { handle, name: file.name, size: file.size, lastModified: file.lastModified, fileId });
    }
    // after Save the app's copy of the register is the marked file (new id) - keep the link pointing at it
    async function setFileId(kind, fileId) {
        const rec = await get(kind);
        if (rec) await put(kind, { ...rec, fileId });
    }
    async function unlink(kind) { await put(kind, undefined); }
    async function info(kind) { return supported ? await get(kind) : null; }

    async function permission(handle) {
        const opts = { mode: 'readwrite' };
        if ((await handle.queryPermission(opts)) === 'granted') return true;
        return (await handle.requestPermission(opts)) === 'granted';
    }

    // write blob into the linked file. Returns the file name. Throws Error with a message for the user.
    // checks before anything is written: linked, allowed, still there, not changed since it was uploaded,
    // and it is the file the check was made from. Call it straight from the button click (permission prompt).
    async function allow(kind, usedFileId) {
        const rec = await get(kind);
        if (!rec) throw new Error('No file linked yet - choose the file with the drop box first (click it, or drag the file in).');
        if (usedFileId && rec.fileId && rec.fileId !== usedFileId) {
            throw new Error(`${rec.name} is not the file this check was made from. Drop the file again, check, then Save.`);
        }
        if (!(await permission(rec.handle))) throw new Error('The browser was not allowed to save into the file.');
        let now;
        try { now = await rec.handle.getFile(); } catch (e) { throw new Error(`${rec.name} cannot be found any more (moved or renamed?). Drop it again.`); }
        if (now.size !== rec.size || now.lastModified !== rec.lastModified) {
            throw new Error(`${rec.name} was changed after it was uploaded (edited in Excel?). Nothing was written, so ` +
                'your changes are safe. Drop the file again, check, then Save.');
        }
        return rec;
    }

    // write blob into the linked file (after allow). Returns the file name.
    async function save(kind, blob, usedFileId) {
        const rec = await allow(kind, usedFileId);
        const h = rec.handle;
        try {
            const w = await h.createWritable();
            await w.write(blob);
            await w.close();
        } catch (e) {
            const busy = /NoModificationAllowed|InvalidState|lock|in use|being used/i.test(`${e.name} ${e.message}`);
            throw new Error(busy ? `${rec.name} is open in Excel - close it there and press Save again.` : `Could not save into ${rec.name}: ${e.message}`);
        }
        const after = await h.getFile();
        await put(kind, { ...rec, size: after.size, lastModified: after.lastModified });
        return rec.name;
    }

    return { supported, handlesFromDrop, pick, link, setFileId, unlink, info, allow, save };
})();

// the marked file as a Blob (no browser download)
async function fetchBlob(url) {
    const res = await fetch(url);
    if (res.status === 401) { location.replace('/login.html'); throw new Error('Please log in'); }
    if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).error) || `Server error ${res.status}`);
    return res.blob();
}
