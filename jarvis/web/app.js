// PWA JARVIS, sans dépendance. Tout contenu serveur passe par textContent.
// Scripts classiques chargés dans l'ordre par index.html : les noms de haut niveau sont partagés
// (app.js = socle, un fichier par écran, start.js en dernier).
'use strict';
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
function setLink(on) {
  $('link').textContent = on ? 'En ligne' : 'Hors ligne';
  $('link').classList.toggle('off', !on);
}
function tickClock() {
  $('clock').textContent = new Date().toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
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
// Dernières lectures réussies, en mémoire seulement (jamais sur disque) : PC injoignable = on montre ces données, grisées.
const CACHEABLE = /^\/api\/(dashboard|social|voyages|finance|finance\/bank|bienetre|veille|audit|devices|levels|memory|reminders)$/;
const lastRead = new Map();
const hhmm = (t) => new Date(t).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  const raw = body instanceof Blob; // audio du bouton « parler » : envoyé tel quel, pas en JSON
  if (body !== undefined) headers['Content-Type'] = raw ? body.type.split(';')[0] : 'application/json';
  let res;
  try {
    res = await fetch(path, {
      method, headers, cache: 'no-store', credentials: 'omit',
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    });
  } catch {
    setLink(false);
    const hit = method === 'GET' ? lastRead.get(path) : undefined;
    if (hit) {
      setStatus(`Hors ligne : données de ${hhmm(hit.at)}.`);
      document.body.classList.add('stale');
      return { status: 200, ok: true, data: hit.data, stale: true };
    }
    setStatus('Hors ligne : le PC est injoignable.');
    throw new Error('network');
  }
  setStatus('');
  setLink(true);
  document.body.classList.remove('stale');
  if (res.status === 401 && auth) { await signOut(); throw new Error('unauthorized'); }
  if (res.status === 429) toast('Jarvis est occupé, réessayez dans un instant.');
  const data = await res.json().catch(() => null);
  if (res.ok && method === 'GET' && data && CACHEABLE.test(path)) lastRead.set(path, { data, at: Date.now() });
  return { status: res.status, ok: res.ok, data };
}
const unavailable = (what, e) => (e.message === 'network' ? `${what} : PC injoignable.`
  : `${what} : le serveur JARVIS répond mal (redémarrage nécessaire après une mise à jour ?).`);
async function signOut() {
  token = null;
  currentDevice = null;
  lastRead.clear();
  await clearToken();
  if (self.caches) { for (const k of await caches.keys()) await caches.delete(k); }
  // Rien de l'ancienne session ne reste dans le DOM masqué (réponses, journal, appareils).
  $('log').replaceChildren();
  $('audit-list').replaceChildren();
  $('devices-list').replaceChildren();
  $('sys-list').replaceChildren();
  for (const id of ['st-loc', 'st-weather', 'st-up']) $(id).textContent = '—';
  bootAt = null;
  for (const id of ['st-sky', 'st-net', 'sys-error']) $(id).textContent = '';
  clearTimeout(homeTimer);
  $('levels-list').replaceChildren();
  $('memory-list').replaceChildren();
  $('rem-list').replaceChildren();
  clearFinance();
  clearDigest();
  $('push-state').textContent = '';
  $('mic').hidden = true;
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
const views = { chat: $('view-chat'), devices: $('view-devices'), settings: $('view-settings'), audit: $('view-audit'), social: $('view-social'), finance: $('view-finance'), veille: $('view-veille'), voyages: $('view-voyages'), conso: $('view-conso'), bienetre: $('view-bienetre') };
function show(name) {
  for (const [k, v] of Object.entries(views)) v.hidden = k !== name;
  document.querySelectorAll('.tab').forEach((t) => {
    if (t.dataset.view === name) { t.setAttribute('aria-current', 'page'); t.scrollIntoView({ inline: 'nearest', block: 'nearest' }); } else t.removeAttribute('aria-current');
  });
  if (name === 'audit') loadAudit();
  if (name === 'devices') loadDevices();
  if (name === 'chat') { loadHome(); loadDigest(); startEye(); } else { clearTimeout(homeTimer); clearDigest(); }
  if (name === 'settings') loadSettings();
  if (name === 'social') loadSocial();
  if (name === 'finance') loadFinance(); else clearFinance();
  if (name === 'veille') loadVeille();
  if (name === 'voyages') loadVoyages();
  if (name === 'conso') loadConso();
  if (name === 'bienetre') loadBienetre(); else clearTimeout(bienetreTimer);
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => show(t.dataset.view)));

// Raccourcis clavier (bureau) : Alt+1..9 puis Alt+0 suivent l'ordre du menu, « / » met le focus sur la saisie du chat.
const tabOrder = [...document.querySelectorAll('.tab')].map((t) => t.dataset.view);
document.querySelectorAll('.tab').forEach((t, i) => { if (i < 10) t.setAttribute('aria-keyshortcuts', `Alt+${(i + 1) % 10}`); });
document.addEventListener('keydown', (e) => {
  if ($('app').hidden || !$('overlay').hidden || e.ctrlKey || e.metaKey) return;
  if (e.altKey && /^\d$/.test(e.key)) { e.preventDefault(); show(tabOrder[(Number(e.key) + 9) % 10]); return; }
  if (e.key === '/' && !e.altKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
    e.preventDefault(); show('chat'); $('chat-input').focus();
  }
});

function showApp() {
  $('enroll').hidden = true;
  $('app').hidden = false;
  $('enroll-submit').disabled = false;
  show('chat');
  loadMic();
  api('/api/ping').then((r) => { if (r.ok && r.data) currentDevice = r.data.device ?? null; }).catch(() => {});
}

// ---- Chat ------------------------------------------------------------------------------------
function addMsg(kind, text) {
  const m = el('p', `msg ${kind}`, text);
  $('log').appendChild(m);
  m.scrollIntoView({ block: m.offsetHeight > $('log').clientHeight ? 'start' : 'end' }); // réponse plus haute que le journal : on lit depuis son début
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
async function pollJob(job, say = addMsg) {
  const seen = new Set();
  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    const r = await api(`/api/chat/${encodeURIComponent(job)}`);
    if (!r.ok || !r.data) { say('fail', 'La réponse est introuvable.'); return; }
    const p = r.data.pending;
    if (p && p.id && !seen.has(p.id)) {
      seen.add(p.id);
      await handlePending(p, say);
      continue;
    }
    if (r.data.status === 'done') {
      say('jarvis', typeof r.data.answer === 'string' && r.data.answer ? r.data.answer : 'Terminé.');
      return;
    }
    await wait(700);
  }
  say('fail', 'Jarvis ne répond pas.');
}
async function handlePending(p, say = addMsg) {
  const choice = await confirmDialog(p);
  if (choice === 'expired') { say('note', 'Demande expirée, rien n\'a été fait.'); return; }
  let approve = choice === 'approve';
  let assertion;
  if (approve && p.webauthn) { // N3 : la clé d'accès signe le défi de CETTE demande
    assertion = await getAssertion(p.webauthn);
    if (!assertion) { approve = false; toast('Clé d\'accès non validée : action annulée.'); }
  }
  const r = await api(`/api/confirm/${encodeURIComponent(p.id)}`, { method: 'POST', body: { approve, assertion } });
  if (r.status === 404) say('note', 'Demande expirée, rien n\'a été fait.');
  else if (!approve) say('note', 'Annulé, rien n\'a été fait.');
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
    const n3 = p.level === 3;
    $('dlg-badge').textContent = n3 ? 'Action critique · N3' : 'Action sensible · N2';
    $('dlg-badge').className = `badge ${n3 ? 'n3' : 'n2'}`;
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
      const list = groups.get(key), prev = list[list.length - 1];
      // Lectures (N0) identiques et consécutives : une ligne « ×N » (les actions N1+ restent toutes visibles)
      if (prev && row.level === 0 && prev.level === 0 && prev.tool === row.tool && prev.decision === row.decision) prev.n = (prev.n ?? 1) + 1;
      else list.push({ ...row });
    }
    const out = [];
    for (const [src, list] of groups) {
      const g = el('section', 'group');
      const panel = el('ul', 'panel hud plain au-list');
      const head = el('li', 'au-head');
      head.setAttribute('aria-hidden', 'true');
      head.append(...['Heure', 'Outil', 'Niveau', 'Décision', 'Détail'].map((t) => el('span', '', t)));
      panel.append(head);
      g.append(el('h2', '', src), panel);
      for (const row of list) {
        // Le serveur envoie le niveau comme un entier (0 à 3, ou null) : « N2 », jamais « N? » pour un vrai niveau.
        const lvl = Number.isInteger(row.level) && row.level >= 0 && row.level <= 3 ? `N${row.level}` : 'N?';
        const item = el('li', 'au-row');
        const tool = el('span', 'au-tool', String(row.tool ?? ''));
        tool.title = tool.textContent;
        if (row.n) tool.append(el('span', 'au-count', `×${row.n}`));
        const detail = el('span', 'au-detail', row.result ? clip(row.result, 120) : '');
        if (row.result) detail.title = clip(row.result, 400);
        item.append(el('span', 'au-time', fmtTime(row.ts)), tool, el('span', `badge au-lvl ${lvl.toLowerCase()}`, lvl),
          el('span', `au-dec ${decisionClass(row.decision)}`, String(row.decision ?? '—')), detail);
        panel.appendChild(item);
      }
      out.push(g);
    }
    box.replaceChildren(...out);
  } catch (e) {
    box.replaceChildren(el('p', 'error', unavailable('Journal indisponible', e)));
  }
}

// ---- Tableau de bord : bandeau d'état et système, rafraîchi toutes les 5 s tant que la vue est ouverte --------------
let homeTimer = 0;
function meter(label, value, text, hot = value >= 90) {
  const li = el('li');
  const head = el('div', 'meter-head');
  head.append(el('span', '', label), el('span', '', text));
  const bar = el('div', `meter-bar${hot ? ' hot' : ''}`);
  bar.setAttribute('role', 'progressbar');
  bar.setAttribute('aria-label', label);
  bar.setAttribute('aria-valuenow', String(Math.round(value)));
  bar.setAttribute('aria-valuemin', '0');
  bar.setAttribute('aria-valuemax', '100');
  const fill = el('span');
  fill.style.width = `${Math.max(0, Math.min(100, value))}%`; // pilotage par l'API DOM : compatible CSP sans inline
  bar.append(fill);
  li.append(head, bar);
  return li;
}
const SVGNS = 'http://www.w3.org/2000/svg';
function svg(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
}
// Jauge en anneau (pathLength 100 : le remplissage vaut directement le pourcentage). Texte lisible par les lecteurs d'écran.
function gauge(label, value, detail, hot = value >= 90) {
  const v = Number.isFinite(value) ? Math.max(0, Math.min(100, Math.round(value))) : 0; // jamais « NaN % »
  const li = el('li', 'gauge');
  li.setAttribute('role', 'img');
  li.setAttribute('aria-label', `${label} : ${v} %${detail ? `, ${detail}` : ''}`);
  const ring = svg('svg', { viewBox: '0 0 80 80', 'aria-hidden': 'true' });
  ring.append(svg('circle', { class: 'track', cx: 40, cy: 40, r: 33, pathLength: 100 }));
  ring.append(svg('circle', { class: `fill${hot ? ' hot' : ''}`, cx: 40, cy: 40, r: 33, pathLength: 100, 'stroke-dasharray': `${v} 100` }));
  const pct = el('span', 'pct', `${v}%`);
  pct.setAttribute('aria-hidden', 'true');
  const cap = el('span', 'cap', label);
  cap.setAttribute('aria-hidden', 'true');
  li.append(ring, pct, cap);
  return li;
}
function fmtUptime(s) {
  const d = Math.floor(s / 86400), p = (n) => String(n).padStart(2, '0');
  const hms = `${p(Math.floor(s % 86400 / 3600))}:${p(Math.floor(s % 3600 / 60))}:${p(s % 60)}`;
  return d ? `${d} j ${hms}` : hms;
}
// Uptime : lu une seule fois (premier tableau de bord reçu), puis compté localement chaque seconde.
let bootAt = null;
function tickUptime() {
  if (bootAt !== null) $('st-up').textContent = fmtUptime(Math.max(0, Math.floor((Date.now() - bootAt) / 1000)));
}
setInterval(() => { if (!document.hidden) tickUptime(); }, 1000);
async function loadHome() {
  clearTimeout(homeTimer);
  if (!token) return;
  try {
    const r = await api('/api/dashboard');
    if (!r.ok || !r.data) throw new Error('bad');
    const d = r.data;
    $('st-loc').textContent = d.location ?? 'Non configurée';
    $('st-weather').textContent = d.weather ? `${d.weather.temp_c} °C` : '—';
    $('st-sky').textContent = d.weather ? String(d.weather.sky) : d.location ? 'Météo indisponible' : '';
    $('st-net').textContent = d.network?.ms != null ? `Réseau : ${d.network.quality} · ${d.network.ms} ms` : 'Réseau : hors ligne';
    if (bootAt === null && Number.isInteger(d.uptime_s)) bootAt = Date.now() - d.uptime_s * 1000;
    tickUptime();
    const s = d.system;
    const rows = [];
    if (s) {
      rows.push(gauge('CPU', s.cpu_percent, ''));
      rows.push(gauge('RAM', s.ram.percent, `${s.ram.used_gb} sur ${s.ram.total_gb} Go`));
      rows.push(gauge('Disque', s.disk.percent, `${s.disk.free_gb} Go libres`));
      if (s.gpu) {
        rows.push(gauge('GPU', s.gpu.percent, `${s.gpu.temperature_c} °C`));
        if (s.gpu.vram_total_mb > 0) rows.push(gauge('VRAM', 100 * s.gpu.vram_used_mb / s.gpu.vram_total_mb, `${(s.gpu.vram_used_mb / 1024).toFixed(1)} sur ${(s.gpu.vram_total_mb / 1024).toFixed(1)} Go`));
      }
    }
    $('sys-list').replaceChildren(...rows);
    $('sys-error').hidden = rows.length > 0;
    $('sys-error').textContent = 'État du PC indisponible (PC éteint ?).';
  } catch (e) {
    $('sys-error').hidden = false;
    $('sys-error').textContent = unavailable('Tableau de bord indisponible', e);
    if (!$('sys-list').querySelector('.gauge')) $('sys-list').replaceChildren(); // plus de « Chargement… » à côté de l'erreur
  }
  if (!token) return; // déconnecté pendant la requête : ne pas réarmer le minuteur
  clearTimeout(homeTimer); // un chargement lancé entre-temps par show() a pu armer le sien : une seule boucle
  homeTimer = setTimeout(() => { if (!views.chat.hidden && !document.hidden) loadHome(); else if (!views.chat.hidden) homeTimer = setTimeout(loadHome, 5000); }, 5000);
}

