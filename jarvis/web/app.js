// PWA JARVIS : un seul module, sans dépendance. Tout contenu serveur passe par textContent.
const $ = (id) => document.getElementById(id);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- Stockage du token : IndexedDB uniquement ------------------------------------------------
const idb = () => new Promise((resolve, reject) => {
  const req = indexedDB.open('jarvis', 1);
  req.onupgradeneeded = () => req.result.createObjectStore('kv');
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});
async function kv(mode, fn) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('kv', mode);
    const r = fn(tx.objectStore('kv'));
    tx.oncomplete = () => { db.close(); resolve(r.result); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}
const getToken = () => kv('readonly', (s) => s.get('token')).catch(() => null);
const setToken = (t) => kv('readwrite', (s) => s.put(t, 'token'));
const clearToken = () => kv('readwrite', (s) => s.delete('token')).catch(() => {});

let token = null;
let currentDevice = null;

// ---- Utilitaires d'affichage -----------------------------------------------------------------
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
let toastTimer = 0;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
}
function setStatus(msg) {
  const s = $('status');
  s.textContent = msg || '';
  s.hidden = !msg;
}
function fmtTime(v) {
  if (v === null || v === undefined || v === '') return '—';
  let d;
  if (typeof v === 'number') d = new Date(v < 1e12 ? v * 1000 : v);
  else if (/^\d+(\.\d+)?$/.test(String(v))) { const n = Number(v); d = new Date(n < 1e12 ? n * 1000 : n); }
  else d = new Date(String(v));
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
const clip = (s, n) => { const t = String(s ?? ''); return t.length > n ? `${t.slice(0, n)}…` : t; };

// ---- Appels API ------------------------------------------------------------------------------
async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(path, {
      method, headers, cache: 'no-store', credentials: 'omit',
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    setStatus('Hors ligne : le PC est injoignable.');
    throw new Error('network');
  }
  setStatus('');
  if (res.status === 401 && auth) { await signOut(); throw new Error('unauthorized'); }
  if (res.status === 429) toast('Jarvis est occupé, réessayez dans un instant.');
  const data = await res.json().catch(() => null);
  return { status: res.status, ok: res.ok, data };
}
async function signOut() {
  token = null;
  currentDevice = null;
  await clearToken();
  if (self.caches) { for (const k of await caches.keys()) await caches.delete(k); }
  // Rien de l'ancienne session ne reste dans le DOM masqué (réponses, journal, appareils).
  $('log').replaceChildren();
  $('log-empty').hidden = false;
  $('audit-list').replaceChildren();
  $('devices-list').replaceChildren();
  $('overlay').hidden = true;
  $('app').inert = false;
  setBusy(false);
  setStatus('Non autorisé : associez de nouveau cet appareil.');
  showEnroll();
}

// ---- Enrôlement ------------------------------------------------------------------------------
function guessName() {
  const ua = navigator.userAgent || '';
  if (/Android/i.test(ua)) return 'Téléphone Android';
  if (/Windows/i.test(ua)) return 'PC Windows';
  return 'Appareil';
}
function showEnroll() {
  $('app').hidden = true;
  $('enroll').hidden = false;
  if (!$('enroll-name').value) $('enroll-name').value = guessName();
}
async function enroll(code, name) {
  const err = $('enroll-error');
  err.hidden = true;
  $('enroll-submit').disabled = true;
  try {
    const r = await api('/api/enroll', { method: 'POST', body: { code, name }, auth: false });
    if (r.ok && r.data && r.data.token) {
      token = r.data.token;
      await setToken(token);
      setStatus('');
      showApp();
      return;
    }
    err.textContent = r.status === 429 ? 'Trop de tentatives, patientez un instant.' : 'Code refusé ou expiré. Générez-en un nouveau sur le PC.';
  } catch {
    err.textContent = 'Impossible de joindre le PC.';
  }
  err.hidden = false;
  $('enroll-submit').disabled = false;
  $('enroll-code').focus();
}
$('enroll-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const code = $('enroll-code').value.trim();
  const name = $('enroll-name').value.trim() || guessName();
  if (code) enroll(code, name);
});

// ---- Navigation ------------------------------------------------------------------------------
const views = { chat: $('view-chat'), audit: $('view-audit'), devices: $('view-devices') };
function show(name) {
  for (const [k, v] of Object.entries(views)) v.hidden = k !== name;
  document.querySelectorAll('.tab').forEach((t) => {
    if (t.dataset.view === name) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
  });
  if (name === 'audit') loadAudit();
  if (name === 'devices') loadDevices();
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => show(t.dataset.view)));

function showApp() {
  $('enroll').hidden = true;
  $('app').hidden = false;
  $('enroll-submit').disabled = false;
  show('chat');
  api('/api/ping').then((r) => { if (r.ok && r.data) currentDevice = r.data.device ?? null; }).catch(() => {});
}

// ---- Chat ------------------------------------------------------------------------------------
function addMsg(kind, text) {
  $('log-empty').hidden = true;
  const m = el('p', `msg ${kind}`, text);
  $('log').appendChild(m);
  m.scrollIntoView({ block: 'end' });
}
let busy = false;
function setBusy(b) {
  busy = b;
  $('chat-send').disabled = b;
  $('thinking').hidden = !b;
}
async function sendChat(text) {
  addMsg('user', text);
  setBusy(true);
  try {
    const r = await api('/api/chat', { method: 'POST', body: { text } });
    if (r.status === 429) { addMsg('note', 'Jarvis est occupé avec une autre demande.'); return; }
    if (!r.ok || !r.data || !r.data.job) { addMsg('fail', 'La demande a échoué.'); return; }
    await pollJob(r.data.job);
  } catch (e) {
    if (e.message === 'network') addMsg('fail', 'PC injoignable : JARVIS et la domotique sont peut-être à l\'arrêt.');
  } finally {
    setBusy(false);
    $('chat-input').focus();
  }
}
async function pollJob(job) {
  const seen = new Set();
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    const r = await api(`/api/chat/${encodeURIComponent(job)}`);
    if (!r.ok || !r.data) { addMsg('fail', 'La réponse est introuvable.'); return; }
    const p = r.data.pending;
    if (p && p.id && !seen.has(p.id)) {
      seen.add(p.id);
      await handlePending(p);
      continue;
    }
    if (r.data.status === 'done') {
      addMsg('jarvis', typeof r.data.answer === 'string' && r.data.answer ? r.data.answer : 'Terminé.');
      return;
    }
    await wait(700);
  }
  addMsg('fail', 'Jarvis ne répond pas.');
}
async function handlePending(p) {
  const choice = await confirmDialog(p);
  if (choice === 'expired') { addMsg('note', 'Demande expirée, rien n\'a été fait.'); return; }
  const approve = choice === 'approve';
  const r = await api(`/api/confirm/${encodeURIComponent(p.id)}`, { method: 'POST', body: { approve } });
  if (r.status === 404) addMsg('note', 'Demande expirée, rien n\'a été fait.');
  else if (!approve) addMsg('note', 'Annulé, rien n\'a été fait.');
}
$('chat-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const text = $('chat-input').value.trim();
  if (!text || busy) return;
  $('chat-input').value = '';
  sendChat(text.slice(0, 1000));
});
$('chat-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('chat-form').requestSubmit(); }
});

// ---- Dialogue de confirmation N2 (DESIGN_SYSTEM §3.4) -----------------------------------------
function confirmDialog(p) {
  return new Promise((resolve) => {
    const overlay = $('overlay');
    const deny = $('dlg-deny');
    const ok = $('dlg-ok');
    const origin = document.activeElement;
    let left = Math.max(1, Math.floor(Number(p.expires_in) || 60));
    let done = false;
    $('dlg-tool').textContent = String(p.tool ?? '');
    $('dlg-preview').textContent = String(p.preview ?? '');
    const tick = () => {
      $('dlg-timer').textContent = `Expire dans ${left} s`;
      if (left === 10) $('dlg-alert').textContent = 'Plus que 10 secondes pour répondre.';
    };
    const finish = (value) => {
      if (done) return;
      done = true;
      clearInterval(timer);
      clearTimeout(arm);
      deny.disabled = true; ok.disabled = true;
      overlay.removeEventListener('keydown', onKey);
      overlay.hidden = true;
      $('app').inert = false;
      deny.disabled = false; ok.disabled = false;
      $('dlg-alert').textContent = '';
      if (origin && origin.focus) origin.focus();
      resolve(value);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); finish('deny'); return; }
      if (e.key !== 'Tab') return;
      const first = deny, last = ok;
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    const timer = setInterval(() => { left -= 1; if (left <= 0) finish('expired'); else tick(); }, 1000);
    // Confirmer ne s'active qu'après 500 ms : un tap lancé avant l'apparition du dialogue n'approuve rien.
    ok.disabled = true;
    const arm = setTimeout(() => { ok.disabled = false; }, 500);
    deny.onclick = () => finish('deny');
    ok.onclick = () => finish('approve');
    overlay.addEventListener('keydown', onKey);
    $('app').inert = true;
    overlay.hidden = false;
    tick();
    deny.focus(); // Refuser a le focus par défaut
  });
}

// ---- Journal ---------------------------------------------------------------------------------
function decisionClass(d) {
  const s = String(d ?? '').toLowerCase();
  if (/refus|deny|denied|reject|block|bloqu/.test(s)) return 'd-bad';
  if (/confirm|approv|ok/.test(s)) return 'd-ok';
  if (/auto/.test(s)) return 'd-neutral';
  return 'd-warn';
}
async function loadAudit() {
  const box = $('audit-list');
  box.replaceChildren(el('p', 'muted', 'Chargement…'));
  try {
    const r = await api('/api/audit');
    const rows = r.ok && r.data && Array.isArray(r.data.rows) ? r.data.rows.slice(0, 50) : null;
    if (!rows) { box.replaceChildren(el('p', 'error', 'Journal indisponible pour le moment.')); return; }
    if (!rows.length) { box.replaceChildren(el('p', 'muted', 'Aucune action pour l\'instant.')); return; }
    const groups = new Map();
    for (const row of rows) {
      const key = String(row.source ?? 'inconnu').split('/')[0] || 'inconnu';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(row);
    }
    const out = [];
    for (const [src, list] of groups) {
      const g = el('section', 'group');
      g.appendChild(el('h2', '', src));
      for (const row of list) {
        // Le serveur envoie le niveau comme un entier (0 à 3, ou null) : « N2 », jamais « N? » pour un vrai niveau.
        const lvl = Number.isInteger(row.level) && row.level >= 0 && row.level <= 3 ? `N${row.level}` : 'N?';
        const item = el('article', 'row');
        item.appendChild(el('div', 'tool', String(row.tool ?? '')));
        const meta = el('div', 'meta');
        meta.appendChild(el('span', '', fmtTime(row.ts)));
        meta.appendChild(el('span', `badge ${lvl.toLowerCase()}`, lvl));
        meta.appendChild(el('span', decisionClass(row.decision), `Décision : ${row.decision ?? '—'}`));
        item.appendChild(meta);
        if (row.result) item.appendChild(el('div', 'meta', clip(row.result, 120)));
        g.appendChild(item);
      }
      out.push(g);
    }
    box.replaceChildren(...out);
  } catch {
    box.replaceChildren(el('p', 'error', 'Journal indisponible : PC injoignable.'));
  }
}

// ---- Appareils -------------------------------------------------------------------------------
async function loadDevices() {
  const ul = $('devices-list');
  ul.replaceChildren(el('li', 'muted', 'Chargement…'));
  try {
    const r = await api('/api/devices');
    const list = r.ok && r.data && Array.isArray(r.data.devices) ? r.data.devices : null;
    if (!list) { ul.replaceChildren(el('li', 'error', 'Liste indisponible pour le moment.')); return; }
    if (!list.length) { ul.replaceChildren(el('li', 'muted', 'Aucun appareil.')); return; }
    const cur = r.data.current ?? currentDevice;
    ul.replaceChildren(...list.map((d) => {
      const isCur = cur !== null && cur !== undefined && d.id === cur;
      const li = el('li', `row${isCur ? ' current' : ''}${d.revoked ? ' revoked' : ''}`);
      li.appendChild(el('div', 'tool', String(d.name ?? 'Appareil')));
      const meta = el('div', 'meta');
      meta.appendChild(el('span', '', `Dernier usage : ${fmtTime(d.last_used)}`));
      if (isCur) meta.appendChild(el('span', 'badge d-ok', 'Cet appareil'));
      if (d.revoked) meta.appendChild(el('span', 'badge d-bad', 'Révoqué'));
      li.appendChild(meta);
      return li;
    }));
  } catch {
    ul.replaceChildren(el('li', 'error', 'Liste indisponible : PC injoignable.'));
  }
}

// ---- Démarrage -------------------------------------------------------------------------------
window.addEventListener('offline', () => setStatus('Hors ligne.'));
window.addEventListener('online', () => setStatus(''));

(async function start() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  // Le fragment est lu puis effacé AVANT tout le reste : même avec un token déjà présent, le code ne reste pas
  // dans la barre d'adresse ni dans l'historique.
  const code = new URLSearchParams(location.hash.slice(1)).get('code');
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  token = await getToken();
  if (token) { showApp(); return; }
  if (code) {
    showEnroll();
    await enroll(code.trim(), $('enroll-name').value.trim() || guessName());
    return;
  }
  showEnroll();
})();
