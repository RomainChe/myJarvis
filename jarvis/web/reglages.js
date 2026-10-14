'use strict';
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
  loadMemory();
  loadReminders();
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

// ---- Souvenirs et rappels : lecture et suppression par numéro (le texte ne va jamais au journal) ----
function listRow(text, meta, label, onDelete) {
  const li = el('li', 'row');
  const body = el('div', 'row-body');
  body.append(el('p', 'row-text', text));
  if (meta) body.append(el('p', 'muted', meta));
  li.append(body);
  if (onDelete) {
    const b = el('button', 'btn', label);
    b.type = 'button';
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        const r = await api(onDelete.path, { method: 'POST', body: { id: onDelete.id } });
        if (!r.ok && r.status !== 404) throw new Error('bad');
        li.remove();
        toast('Fait.');
      } catch (e) {
        b.disabled = false;
        toast(unavailable('Action impossible', e));
      }
    });
    li.append(b);
  }
  return li;
}
async function loadList(path, listId, stateId, pick, empty) {
  const ul = $(listId), state = $(stateId);
  try {
    const r = await api(path);
    if (!r.ok || !r.data) throw new Error('bad');
    const rows = pick(r.data);
    ul.replaceChildren(...rows);
    state.textContent = rows.length ? '' : empty;
  } catch (e) {
    ul.replaceChildren();
    state.textContent = unavailable('Indisponible', e);
  }
}
const loadMemory = () => loadList('/api/memory', 'memory-list', 'memory-state',
  (d) => d.facts.map((f) => listRow(f.text, `n° ${f.id}`, 'Oublier', { path: '/api/memory/forget', id: f.id })),
  'Rien de retenu pour le moment.');
const KINDS = { timer: 'Minuteur', reminder: 'Rappel', briefing: 'Briefing' };
const loadReminders = () => loadList('/api/reminders', 'rem-list', 'rem-state',
  (d) => d.reminders.map((x) => listRow(x.kind === 'briefing' ? 'Briefing du matin' : x.label,
    `${KINDS[x.kind] ?? x.kind} · ${fmtTime(x.due)}`, 'Annuler', x.kind === 'briefing' ? null : { path: '/api/reminders/cancel', id: x.id })),
  'Aucun rappel en attente.');
