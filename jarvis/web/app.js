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
    setLink(false);
    throw new Error('network');
  }
  setStatus('');
  setLink(true);
  if (res.status === 401 && auth) { await signOut(); throw new Error('unauthorized'); }
  if (res.status === 429) toast('Jarvis est occupé, réessayez dans un instant.');
  const data = await res.json().catch(() => null);
  return { status: res.status, ok: res.ok, data };
}
const unavailable = (what, e) => (e.message === 'network' ? `${what} : PC injoignable.`
  : `${what} : le serveur JARVIS répond mal (redémarrage nécessaire après une mise à jour ?).`);
async function signOut() {
  token = null;
  currentDevice = null;
  await clearToken();
  if (self.caches) { for (const k of await caches.keys()) await caches.delete(k); }
  // Rien de l'ancienne session ne reste dans le DOM masqué (réponses, journal, appareils).
  $('log').replaceChildren();
  $('audit-list').replaceChildren();
  $('devices-list').replaceChildren();
  $('sys-list').replaceChildren();
  for (const id of ['st-loc', 'st-weather', 'st-up']) $(id).textContent = '—';
  for (const id of ['st-sky', 'st-net', 'sys-error']) $(id).textContent = '';
  clearTimeout(homeTimer);
  $('levels-list').replaceChildren();
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
const views = { chat: $('view-chat'), devices: $('view-devices'), settings: $('view-settings'), audit: $('view-audit'), social: $('view-social'), finance: $('view-finance'), veille: $('view-veille') };
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
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => show(t.dataset.view)));

// Raccourcis clavier (bureau) : Alt+1..7 suit l'ordre du menu, « / » met le focus sur la saisie du chat.
const tabOrder = [...document.querySelectorAll('.tab')].map((t) => t.dataset.view);
document.addEventListener('keydown', (e) => {
  if ($('app').hidden || !$('overlay').hidden || e.ctrlKey || e.metaKey) return;
  if (e.altKey && /^[1-7]$/.test(e.key)) { e.preventDefault(); show(tabOrder[Number(e.key) - 1]); return; }
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
  let approve = choice === 'approve';
  let assertion;
  if (approve && p.webauthn) { // N3 : la clé d'accès signe le défi de CETTE demande
    assertion = await getAssertion(p.webauthn);
    if (!assertion) { approve = false; toast('Clé d\'accès non validée : action annulée.'); }
  }
  const r = await api(`/api/confirm/${encodeURIComponent(p.id)}`, { method: 'POST', body: { approve, assertion } });
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
      groups.get(key).push(row);
    }
    const out = [];
    for (const [src, list] of groups) {
      const g = el('section', 'group');
      const panel = el('div', 'panel hud cards');
      g.append(el('h2', '', src), panel);
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
  const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  const hm = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  return d ? `${d} j ${hm}` : hm;
}
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
    $('st-up').textContent = Number.isInteger(d.uptime_s) ? fmtUptime(d.uptime_s) : '—';
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
    $('sys-error').textContent = 'État du système indisponible.';
  } catch (e) {
    $('sys-error').hidden = false;
    $('sys-error').textContent = unavailable('Tableau de bord indisponible', e);
    if (!$('sys-list').querySelector('.gauge')) $('sys-list').replaceChildren(); // plus de « Chargement… » à côté de l'erreur
  }
  if (!token) return; // déconnecté pendant la requête : ne pas réarmer le minuteur
  clearTimeout(homeTimer); // un chargement lancé entre-temps par show() a pu armer le sien : une seule boucle
  homeTimer = setTimeout(() => { if (!views.chat.hidden && !document.hidden) loadHome(); else if (!views.chat.hidden) homeTimer = setTimeout(loadHome, 5000); }, 5000);
}

// ---- Réseaux : publications et planning de lol-clipper (lecture seule) -----------------------------------------------
const PLATFORMS = { youtube: 'YouTube', tiktok: 'TikTok', all: 'YouTube + TikTok' };
const fmtDate = (iso) => new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
function socialRow(r, withLink) {
  const li = el('li', 'row');
  li.append(el('div', 'tool', r.title), el('div', 'meta', `${PLATFORMS[r.platform] ?? r.platform} · ${fmtDate(r.at)}${r.privacy ? ` · ${r.privacy}` : ''}${Number.isInteger(r.views) ? ` · ${r.views} vues` : ''}`));
  if (withLink && typeof r.url === 'string' && URL.canParse(r.url) && new URL(r.url).protocol === 'https:') {
    const a = el('a', '', 'Ouvrir');
    a.href = r.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    li.append(a);
  }
  return li;
}
async function loadSocial() {
  const err = $('social-error');
  try {
    const r = await api('/api/social');
    if (!r.ok || !r.data) throw new Error('bad');
    err.hidden = r.data.configured;
    err.textContent = 'Dossier de lol-clipper introuvable.';
    const fill = (id, rows, empty, link) => $(id).replaceChildren(...(rows.length ? rows.map((x) => socialRow(x, link)) : [el('li', 'row muted', empty)]));
    const yt = r.data.youtube;
    $('social-yt').hidden = !yt;
    if (yt) {
      const d = (x) => (x ? `${x.subs >= 0 ? '+' : ''}${x.subs}` : '…');
      const n = (x) => (Number.isFinite(x) ? x.toLocaleString('fr-FR') : '—');
      $('yt-subs').textContent = yt.error ? '—' : n(yt.subs);
      $('yt-views').textContent = yt.error ? '—' : n(yt.views);
      $('yt-videos').textContent = yt.error ? '—' : n(yt.videos);
      $('yt-d7').textContent = yt.error ? '—' : `${d(yt.delta?.d7)} en 7 j`;
      $('yt-d30').textContent = yt.error ? '' : `${d(yt.delta?.d30)} en 30 j`;
      $('yt-detail').hidden = !yt.error;
      $('yt-detail').textContent = yt.error === 'reconnexion' ? 'Reconnexion de lol-clipper à faire (droit youtube.readonly).' : 'Statistiques indisponibles.';
    }
    fill('social-todo', r.data.scheduled, 'Rien de programmé.', false);
    fill('social-done', r.data.published, 'Aucune publication.', true);
  } catch (e) {
    err.hidden = false;
    err.textContent = unavailable('Réseaux indisponibles', e);
  }
}

// ---- Finances : rapports hebdo (lecture seule, données sensibles : rien n'est gardé hors de la vue ouverte) ---------
const eur = (n) => (Number.isFinite(n) ? n.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' }) : '—');
function clearFinance() {
  for (const id of ['fin-cards', 'fin-cats', 'fin-trend']) $(id).replaceChildren();
  $('fin-body').hidden = true;
  $('fin-left').textContent = $('fin-balance').textContent = $('fin-period').textContent = '';
}
async function loadFinance() {
  const err = $('fin-error'), state = $('fin-state');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…';
  try {
    const r = await api('/api/finance');
    if (!r.ok || !r.data) throw new Error('bad');
    const d = r.data.latest;
    if (views.finance.hidden) return; // vue quittée pendant le chargement
    if (!d) { state.textContent = r.data.configured ? 'Aucun rapport reconnu.' : 'Dossier des rapports introuvable.'; return; }
    state.hidden = true; $('fin-body').hidden = false;
    $('fin-period').textContent = `Semaine ${d.week}${d.period ? ` · ${d.period}` : ''}`;
    const card = (title, c) => {
      const s = el('section', 'panel hud stat');
      s.append(el('h2', '', title), el('p', 'big', eur(c?.amount)), el('p', 'muted', Number.isInteger(c?.vs_pct) ? `${c.vs_pct > 0 ? '+' : ''}${c.vs_pct} % vs sem. préc.` : ''));
      return s;
    };
    $('fin-cards').replaceChildren(card('Dépenses', d.spent), card('Épargne', d.saved), card('Consommation', d.consumed), card('Entrées', d.income));
    $('fin-left').textContent = eur(d.left_to_live) + (Number.isFinite(d.per_day) ? ` · ≈ ${eur(d.per_day)}/jour` : '');
    $('fin-balance').textContent = Number.isFinite(d.balance) ? `Total disponible : ${eur(d.balance)}` : '';
    $('fin-cats').replaceChildren(...(d.categories.length ? d.categories.map((c) => meter(c.name, c.pct, `${eur(c.amount)} · ${c.pct} %`)) : [el('li', 'muted', 'Aucune catégorie.')]));
    const top = Math.max(1, ...r.data.trend.map((t) => t.spent ?? 0));
    $('fin-trend').replaceChildren(...r.data.trend.map((t) => meter(`S${t.week}`, ((t.spent ?? 0) / top) * 100, eur(t.spent), false)));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Finances indisponibles', e);
  }
}

// ---- Veille IA : envois hebdo du projet veille-ia (contenu écrit par un agent qui lit le web : texte seul, liens https) ----
const VEILLE = { actus: 'Actus IA', plugins: 'Plugins' };
async function loadVeille() {
  const err = $('veille-error'), state = $('veille-state'), list = $('veille-list');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren();
  try {
    const r = await api('/api/veille');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.veille.hidden) return; // vue quittée pendant le chargement
    if (!r.data.issues.length) { state.textContent = r.data.configured ? 'Aucun envoi reconnu.' : 'Dossier de la veille introuvable.'; return; }
    state.hidden = true;
    list.replaceChildren(...r.data.issues.map((it, i) => {
      const d = el('details', 'panel hud');
      d.open = i === 0;
      d.append(el('summary', '', `${VEILLE[it.kind] ?? it.kind} · semaine ${it.week} · ${it.year}`));
      const safe = (l) => l && typeof l.url === 'string' && URL.canParse(l.url) && new URL(l.url).protocol === 'https:';
      const anchor = (l) => {
        const a = el('a', '', l.label);
        a.href = l.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        return [a, el('span', 'muted', ` · ${new URL(l.url).hostname}`)]; // destination réelle, pas le champ du serveur
      };
      const items = it.items ?? [], used = new Set();
      if (items.length) {
        for (const x of items) {
          const c = el('article', 'veille-item');
          c.append(el('h3', 'veille-title', x.lines[0]));
          for (const t of x.lines.slice(1)) c.append(el('p', 'veille-block', t));
          if (safe(x.link)) { used.add(x.link.url); c.append(el('p', 'veille-block', '')); c.lastChild.append(...anchor(x.link)); }
          d.append(c);
        }
      } else for (const b of it.blocks) d.append(el('p', 'veille-block', b));
      const links = el('ul', 'plain veille-links');
      for (const l of it.links) {
        if (!safe(l) || used.has(l.url)) continue;
        const li = el('li');
        li.append(...anchor(l));
        links.append(li);
      }
      if (links.children.length) d.append(el('h3', 'veille-src', items.length ? 'Rapport complet' : 'Sources'), links);
      return d;
    }));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Veille indisponible', e);
  }
}

// ---- Œil de Jarvis : anneaux ondulants de particules autour d'une sphère de points (canvas, décoratif) ---------
// Animé seulement quand le dashboard est visible ; une seule image fixe si l'utilisateur réduit les animations.
const eye = $('eye'), eyeCtx = eye.getContext('2d');
const still = matchMedia('(prefers-reduced-motion: reduce)'), dark = matchMedia('(prefers-color-scheme: dark)');
// Chaque anneau est un ruban de 5 fils : les points suivent un fil (léger flou), d'où des lignes nettes qui se croisent.
const RINGS = Array.from({ length: 4 }, (_, k) => ({
  p: k * 1.7, s: 0.5 + k * 0.17, b: 0.94 + k * 0.035,
  dots: Array.from({ length: 1400 }, () => [Math.random() * Math.PI * 2, (Math.floor(Math.random() * 5) - 2) / 2 + (Math.random() - 0.5) * 0.06, Math.random()]),
}));
const SPHERE = Array.from({ length: 260 }, (_, i) => { // sphère de Fibonacci
  const y = 1 - (2 * i + 1) / 260, r = Math.sqrt(1 - y * y), a = i * 2.39996;
  return [Math.cos(a) * r, y, Math.sin(a) * r];
});
let eyeFrame = 0;
function drawEye(t) {
  const size = eye.clientWidth, dpr = devicePixelRatio || 1;
  if (!size) return;
  if (eye.width !== Math.round(size * dpr)) eye.width = eye.height = Math.round(size * dpr);
  const c = eyeCtx, R = size * 0.4, mid = size / 2, dot = 0.6 + size / 380; // points plus gros quand l'œil grandit
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, size, size);
  c.fillStyle = getComputedStyle(eye).color;
  c.globalCompositeOperation = dark.matches ? 'lighter' : 'source-over';
  for (const g of RINGS) {
    for (const [a, d, f] of g.dots) {
      const w = t * g.s;
      const r = R * (g.b + 0.06 * Math.sin(3 * a + w + g.p) + 0.04 * Math.sin(5 * a - w * 1.3 + g.p * 2) + 0.015 * Math.sin(9 * a + w * 2));
      const thick = R * 0.07 * Math.sin(2 * a + w * 0.8 + g.p); // ruban qui se tord : les fils se croisent quand il s'annule
      const rr = r + d * thick;
      c.globalAlpha = (0.2 + 0.7 * f) * (0.55 + 0.45 * Math.abs(Math.sin(2 * a + w * 0.8 + g.p)));
      c.fillRect(mid + Math.cos(a) * rr, mid + Math.sin(a) * rr, dot, dot);
    }
  }
  const sr = R * 0.2, rot = t * 0.4, cr = Math.cos(rot), sn = Math.sin(rot);
  for (const [x, y, z] of SPHERE) {
    const xr = x * cr - z * sn, zr = x * sn + z * cr;
    c.globalAlpha = 0.25 + 0.5 * (zr + 1) / 2;
    c.fillRect(mid + xr * sr, mid + y * sr, dot, dot);
  }
  c.globalAlpha = 0.18;
  c.strokeStyle = c.fillStyle;
  c.beginPath(); c.arc(mid, mid, R * 0.34, 0, Math.PI * 2); c.stroke();
  c.globalAlpha = 1;
}
function startEye() {
  cancelAnimationFrame(eyeFrame);
  if (still.matches) { drawEye(0); return; }
  const loop = (ms) => {
    if (views.chat.hidden || document.hidden || $('app').hidden) return; // relancé par show('chat') ou au retour sur l'onglet
    drawEye(ms / 1000);
    eyeFrame = requestAnimationFrame(loop);
  };
  eyeFrame = requestAnimationFrame(loop);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && !views.chat.hidden) startEye(); });
new ResizeObserver(() => { if (still.matches) drawEye(0); }).observe(eye);

// ---- Résumé du dashboard (bureau ≥ 1200 px seulement) : réseaux, finances, 2 sources de la veille ----------------
// Chargé une fois à l'ouverture du dashboard, sans minuteur. Finances masquées : lues seulement sur clic
// (écran d'accueil visible par un tiers, revue Sécurité constat 1). Vidé dès qu'on quitte la vue.
const wide = matchMedia('(min-width: 1200px)');
let digestRun = 0;
const getData = (path) => api(path).then((r) => { if (!r.ok || !r.data) throw new Error('bad'); return r.data; });
function clearDigest() {
  digestRun++; // une réponse arrivée après coup est ignorée
  $('dg-subs').textContent = '—';
  $('dg-left').textContent = '•••• €';
  $('dg-fin-show').hidden = false;
  for (const id of ['dg-social', 'dg-fin', 'dg-veille-state']) $(id).textContent = '';
  $('dg-veille').replaceChildren();
}
$('dg-fin-show').addEventListener('click', async () => {
  const run = digestRun;
  $('dg-fin-show').hidden = true;
  let f = null, failed = false;
  try { f = (await getData('/api/finance')).latest; } catch { failed = true; }
  if (run !== digestRun || views.chat.hidden) return;
  if (f) {
    $('dg-left').textContent = eur(f.left_to_live);
    $('dg-fin').textContent = `Reste à vivre · dépensé S${f.week} : ${eur(f.spent?.amount)}`;
  } else $('dg-fin').textContent = failed ? 'Indisponible.' : 'Aucun rapport.';
});
async function loadDigest() {
  clearDigest();
  if (!token || !wide.matches) return;
  const run = digestRun;
  const [so, ve] = await Promise.allSettled([getData('/api/social'), getData('/api/veille')]);
  if (run !== digestRun || views.chat.hidden) return;
  const yt = so.value?.youtube;
  if (yt && !yt.error) {
    $('dg-subs').textContent = `${yt.subs} abonnés`;
    const d7 = yt.delta?.d7;
    $('dg-social').textContent = `YouTube${d7 ? ` · 7 j : ${d7.subs >= 0 ? '+' : ''}${d7.subs}` : ''}`;
  } else $('dg-social').textContent = so.status === 'rejected' ? 'Indisponible.' : 'Statistiques YouTube indisponibles.';
  const next = so.value?.scheduled?.[0];
  if (next) $('dg-social').textContent += ` · prochaine : ${fmtDate(next.at)}`;
  const issue = ve.value?.issues?.[0];
  const links = (issue?.links ?? []).filter((l) => typeof l.url === 'string' && URL.canParse(l.url) && new URL(l.url).protocol === 'https:').slice(0, 2);
  $('dg-veille-state').textContent = ve.status === 'rejected' ? 'Indisponible.' : !issue ? 'Aucun envoi.' : `${VEILLE[issue.kind] ?? issue.kind} · semaine ${issue.week}`;
  $('dg-veille').replaceChildren(...links.map((l) => {
    const host = new URL(l.url).hostname; // destination réelle, pas le champ du serveur
    const li = el('li'), a = el('a', '', l.label || host);
    a.href = l.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    li.append(a, el('span', 'muted', host));
    return li;
  }));
}
wide.addEventListener('change', () => { if (!views.chat.hidden) loadDigest(); });

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
  } catch (e) {
    ul.replaceChildren(el('li', 'error', unavailable('Liste indisponible', e)));
  }
}

// ---- Micro de Jarvis : actif par défaut, coupable ici ; réarmer exige la clé d'accès si l'appareil en a une ----------
function paintMic(on, state) {
  const b = $('mic');
  b.hidden = false;
  b.setAttribute('aria-pressed', String(on));
  const label = on ? `Micro actif${state === 'écoute' ? ' (écoute)' : ''}` : 'Micro coupé';
  b.title = label;
  b.setAttribute('aria-label', `Micro de Jarvis : ${label}. ${on ? 'Appuyer pour couper.' : 'Appuyer pour réactiver.'}`);
}
async function loadMic() {
  try {
    const r = await api('/api/mic');
    if (r.ok && r.data && r.data.available) { paintMic(r.data.on === true, r.data.state); }
    else $('mic').hidden = true;
  } catch { /* hors ligne : le bouton garde son dernier état */ }
}
$('mic').addEventListener('click', async () => {
  const b = $('mic');
  const on = b.getAttribute('aria-pressed') !== 'true'; // état voulu
  b.disabled = true;
  try {
    const body = { on };
    if (on) { // réarmer : toujours un défi signé (sans clé d'accès, le serveur refuse)
      const ch = await api('/api/mic/challenge', { method: 'POST', body: {} });
      body.assertion = ch.ok ? await getAssertion(ch.data) : null;
      if (!body.assertion) { toast('Clé d’accès non validée : micro inchangé.'); return; }
    }
    const r = await api('/api/mic', { method: 'POST', body });
    toast(r.ok ? (on ? 'Micro réactivé.' : 'Micro coupé.') : 'Changement refusé.');
  } catch { /* api() a déjà prévenu */ } finally {
    b.disabled = false;
    loadMic();
  }
});

// ---- Clés d'accès (WebAuthn) -----------------------------------------------------------------
const b64uToBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0));
const bytesToB64u = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const credRef = (c) => ({ type: c.type, id: b64uToBytes(c.id) });

// Options du serveur -> signature de la clé d'accès ; null si l'utilisateur annule ou si l'appareil ne sait pas.
async function getAssertion(o) {
  try {
    const cred = await navigator.credentials.get({ publicKey: {
      challenge: b64uToBytes(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: 'required',
      allowCredentials: o.allowCredentials.map(credRef),
    } });
    const r = cred.response;
    return { id: bytesToB64u(cred.rawId), clientDataJSON: bytesToB64u(r.clientDataJSON),
             authenticatorData: bytesToB64u(r.authenticatorData), signature: bytesToB64u(r.signature) };
  } catch {
    return null;
  }
}
async function registerPasskey() {
  const opts = await api('/api/passkey/options', { method: 'POST', body: {} });
  if (!opts.ok) { toast('Sur le PC, lancez « python -m jarvis passkey add » avec l\'identifiant de cet appareil (onglet Appareils).'); return; }
  const o = opts.data;
  let cred;
  try {
    cred = await navigator.credentials.create({ publicKey: {
      challenge: b64uToBytes(o.challenge), rp: o.rp, timeout: o.timeout, attestation: 'none',
      user: { ...o.user, id: b64uToBytes(o.user.id) }, pubKeyCredParams: o.pubKeyCredParams,
      authenticatorSelection: o.authenticatorSelection, excludeCredentials: o.excludeCredentials.map(credRef),
    } });
  } catch (e) { // InvalidStateError : le téléphone a déjà une clé pour ce PC (excludeCredentials) ; NotAllowedError : annulé
    toast(e && e.name === 'InvalidStateError' ? 'Une clé d\'accès existe déjà sur cet appareil : rien à faire.'
      : e && e.name === 'NotAllowedError' ? 'Enregistrement annulé ou délai dépassé.' : `Enregistrement impossible sur cet appareil (${e && e.name || 'erreur inconnue'}).`);
    return;
  }
  const r = await api('/api/passkey', { method: 'POST', body: {
    clientDataJSON: bytesToB64u(cred.response.clientDataJSON), attestationObject: bytesToB64u(cred.response.attestationObject),
  } });
  toast(r.ok ? 'Clé d\'accès enregistrée.' : 'Enregistrement refusé.');
  loadSettings();
}
$('passkey-add').addEventListener('click', registerPasskey);

// ---- Réglages : niveaux des outils -------------------------------------------------------------
async function applyLevel(row, level) {
  const body = { tool: row.tool, level };
  if (level < row.level) { // abaisser = N3 : défi lié à (outil, niveau), signé par la clé d'accès
    const ch = await api('/api/levels/challenge', { method: 'POST', body });
    if (!ch.ok) { toast('Enregistrez d\'abord une clé d\'accès pour abaisser un niveau.'); return; }
    body.assertion = await getAssertion(ch.data);
    if (!body.assertion) { toast('Clé d\'accès non validée : niveau inchangé.'); return; }
  }
  const r = await api('/api/levels', { method: 'POST', body });
  toast(r.ok ? `${row.title ?? row.tool} : N${level}` : 'Changement refusé.');
  await loadSettings();
  // Le focus revient sur le niveau en vigueur de cet outil (la liste vient d'être redessinée).
  const pressed = [...document.querySelectorAll('#levels-list .seg button[aria-pressed="true"]')].find((b) => b.dataset.tool === row.tool);
  if (pressed) pressed.focus();
}
const LEVEL_HELP = ['Lecture, automatique', 'Action courante, automatique', 'Demande une confirmation', 'Confirmation et clé d’accès'];
function levelRow(row) {
  const title = String(row.title ?? row.tool);
  const li = el('li', 'row lv');
  const text = el('div', 'lv-text');
  text.append(el('span', 'lv-title', title));
  if (row.description) text.append(el('span', 'lv-desc', String(row.description)));
  const seg = el('div', 'seg');
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', `Niveau : ${title}`);
  for (let n = 0; n <= 3; n += 1) {
    const b = el('button', `n${n}`, `N${n}`);
    b.type = 'button';
    b.dataset.tool = String(row.tool);
    b.title = n < row.floor ? `Jamais sous N${row.floor} pour cet outil` : LEVEL_HELP[n];
    b.setAttribute('aria-pressed', String(n === row.level));
    b.disabled = n < row.floor;
    b.addEventListener('click', () => { if (n !== row.level) applyLevel(row, n); });
    seg.append(b);
  }
  li.append(text, seg);
  return li;
}
const pushSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
async function loadPush() {
  const state = $('push-state');
  const btn = $('push-toggle');
  btn.hidden = true;
  if (!pushSupported()) { state.textContent = 'Notifications indisponibles sur ce navigateur.'; return; }
  const reg = await navigator.serviceWorker.ready;
  const [local, remote] = [await reg.pushManager.getSubscription(), await api('/api/push')];
  if (!remote.ok || !remote.data) { state.textContent = 'État indisponible.'; return; }
  const on = Boolean(local) && remote.data.subscribed === true;
  state.textContent = on ? 'Activées : vous êtes prévenu quand une action attend votre confirmation.'
    : Notification.permission === 'denied' ? 'Bloquées dans les réglages du navigateur.' : 'Désactivées.';
  btn.textContent = on ? 'Désactiver les notifications' : 'Activer les notifications';
  btn.hidden = Notification.permission === 'denied';
  btn.onclick = async () => {
    btn.disabled = true;
    try { await togglePush(reg, on ? local : null, local, remote.data.key); } catch { toast('Notifications : échec.'); }
    btn.disabled = false;
    loadPush();
  };
}
async function togglePush(reg, active, existing, key) {
  if (active) { // abonnement connu des deux côtés : on le coupe
    await active.unsubscribe();
    await api('/api/push/unsubscribe', { method: 'POST', body: {} });
    return;
  }
  if (await Notification.requestPermission() !== 'granted') { toast('Notifications refusées.'); return; }
  // Abonnement local que le PC a oublié (purgé, base remise à zéro) : on le réenregistre au lieu d'en créer un autre.
  const sub = (existing || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64uToBytes(key) })).toJSON();
  const r = await api('/api/push', { method: 'POST', body: { endpoint: sub.endpoint, p256dh: sub.keys.p256dh, auth: sub.keys.auth } });
  if (!r.ok) toast('Abonnement refusé par le PC.');
}
async function loadSettings() {
  loadPush().catch(() => { $('push-state').textContent = 'État indisponible.'; });
  const box = $('levels-list');
  box.replaceChildren(el('p', 'muted', 'Chargement…'));
  try {
    const [pk, lv] = await Promise.all([api('/api/passkey'), api('/api/levels')]);
    const enabled = pk.ok && pk.data && pk.data.enabled === true;
    const registered = pk.ok && pk.data && pk.data.registered === true;
    $('passkey-state').textContent = !pk.ok ? 'État indisponible.' : !enabled
      ? 'Indisponible ici : les clés d\'accès exigent l\'adresse HTTPS Tailscale du PC.'
      : registered ? 'Une clé d\'accès protège cet appareil.' : 'Aucune clé d\'accès : les actions critiques (N3) et l\'abaissement des niveaux sont refusés.';
    $('passkey-add').hidden = !enabled || !window.PublicKeyCredential;
    const rows = lv.ok && lv.data && Array.isArray(lv.data.levels) ? lv.data.levels : null;
    if (!rows) { box.replaceChildren(el('p', 'error', 'Niveaux indisponibles pour le moment.')); return; }
    const groups = new Map();
    for (const row of rows) {
      const g = String(row.group ?? 'Autres');
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(row);
    }
    box.replaceChildren(...[...groups].map(([name, list]) => {
      const g = el('section', 'lv-group');
      const ul = el('ul', 'panel hud plain cards two');
      ul.append(...list.sort((a, b) => String(a.title).localeCompare(String(b.title), 'fr')).map(levelRow));
      g.append(el('h3', '', name), ul);
      return g;
    }));
  } catch (e) {
    box.replaceChildren(el('p', 'error', unavailable('Réglages indisponibles', e)));
  }
}

// ---- Démarrage -------------------------------------------------------------------------------
window.addEventListener('offline', () => { setStatus('Hors ligne.'); setLink(false); });
window.addEventListener('online', () => { setStatus(''); setLink(true); });
tickClock();
setInterval(tickClock, 10000);
setInterval(() => { if (!$('app').hidden && !document.hidden) loadMic(); }, 15000); // coupé depuis le PC : le bouton suit

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
