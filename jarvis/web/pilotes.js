'use strict';
// ---- Pilotes : dernière vérification de DriverWatch (status.json du PC : donnée, texte seul) ; « Go » = driverwatch_update_all (N2) ----
// « avail » : version plus récente mais retard sous le seuil DriverWatch (statut ok). « Go » (update-all) ne traite que critical et moderate.
const DRV_KIND = {
  critical: ['bad', 'Urgent'], moderate: ['warn', 'En retard'], avail: ['avail', 'Mise à jour dispo'],
  unknown: ['none', 'Inconnu'], ignored: ['none', 'Ignorée'], ok: ['ok', 'À jour'],
};
function driverKind(p) {
  if (p.ignored) return 'ignored';
  if (p.newer) return p.status === 'critical' || p.status === 'moderate' ? p.status : 'avail';
  return p.status === 'unknown' ? 'unknown' : 'ok';
}
// Icône et marque : correspondance sur nom/catégorie/source vers des icônes et classes à nous (jamais un chemin construit).
const DRV_CATS = { DISPLAY: 'Affichage', NET: 'Réseau', BLUETOOTH: 'Bluetooth', MEDIA: 'Audio', SYSTEM: 'Système' };
const DRV_BRANDS = [['nvidia', 'NVIDIA'], ['intel', 'Intel'], ['amd', 'AMD'], ['realtek', 'Realtek'], ['logitech', 'Logitech'],
  ['tailscale', 'Tailscale'], ['qualcomm', 'Qualcomm'], ['mediatek', 'MediaTek'], ['samsung', 'Samsung'], ['microsoft', 'Microsoft']];
function driverIcon(p) {
  const n = String(p.name).toLowerCase();
  if (p.category === 'BLUETOOTH' || n.includes('bluetooth')) return 'bt';
  if (/wi-?fi|wlan|802\.11/.test(n)) return 'wifi';
  if (/tunnel|vpn|tailscale|wireguard/.test(n)) return 'shield';
  if (p.category === 'NET') return 'ethernet';
  if (p.category === 'DISPLAY') return 'gpu';
  if (/headset|headphone|casque/.test(n)) return 'headset';
  return p.category === 'MEDIA' ? 'speaker' : 'chip';
}
function driverBrand(p) {
  const hay = `${p.name} ${p.source || ''}`.toLowerCase();
  return DRV_BRANDS.find(([k]) => new RegExp(`\\b${k}\\b`).test(hay)) || null;
}
function driverRow(p, compact) {
  const [k, label] = DRV_KIND[driverKind(p)], brand = driverBrand(p);
  const li = el('li', `be-item drv drv-${k}${compact ? ' drv-compact' : ''}`);
  const tile = el('span', `drv-ico${brand ? ` b-${brand[0]}` : ''}`);
  tile.append(icon(driverIcon(p)));
  const t = el('p', 'be-title');
  t.append(el('strong', '', p.name), el('span', 'be-point', [brand && brand[1], DRV_CATS[p.category] || p.category].filter(Boolean).join(' · ')));
  const head = el('div', 'be-head');
  head.append(tile, t, el('span', 'badge drv-badge', label));
  const ver = el('p', 'drv-ver');
  li.append(head, ver);
  if (!p.newer || !p.latest) { ver.textContent = p.installed || 'version inconnue'; return li; }
  ver.append(el('span', '', p.installed), el('span', 'drv-arrow', ' → '), el('strong', '', p.latest));
  if (!compact && p.days > 0) {
    const age = el('div', 'drv-age'), fill = el('span');
    age.setAttribute('aria-hidden', 'true'); // le texte voisin donne le retard
    fill.style.width = `${Math.min(100, p.days / 3.65)}%`; // retard rapporté à un an ; API DOM : compatible CSP
    age.append(fill);
    li.append(age, el('p', 'be-point', `${p.days} j de retard${p.source ? ` · source : ${p.source}` : ''}`));
  }
  return li;
}
let driversTimer = 0;
async function loadDrivers() {
  clearTimeout(driversTimer);
  const err = $('drivers-error'), state = $('drivers-state'), list = $('drivers-list'), go = $('drivers-go'), hero = $('drivers-hero');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren(); go.hidden = true; hero.hidden = true;
  try {
    const r = await api('/api/drivers');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.drivers.hidden) return; // vue quittée pendant le chargement
    const d = r.data;
    if (!d.configured) { state.textContent = 'Projet DriverWatch introuvable sur le PC.'; return; }
    if (d.offline) { state.textContent = 'PC injoignable : état des pilotes indisponible.'; return; }
    if (d.checking) driversTimer = setTimeout(loadDrivers, 30000); // vérification en cours (quelques minutes) : on relit
    if (!d.at) { state.textContent = d.checking ? 'Première vérification en cours (quelques minutes)…' : 'Aucune vérification pour le moment.'; return; }
    state.hidden = true;
    const when = new Date(d.at).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    const by = { critical: [], moderate: [], avail: [], unknown: [], ignored: [], ok: [] }; // ordre d'affichage
    for (const p of d.drivers) by[driverKind(p)].push(p);
    const late = by.critical.length + by.moderate.length, avail = by.avail.length, ok = by.ok.length, known = late + avail + ok;
    const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
    const score = known ? Math.round(100 * ok / known) : 100; // part des pilotes connus sans mise à jour en attente
    $('drivers-gauge').replaceChildren(gauge('Santé', score, `${ok} sur ${known} à jour`, late > 0));
    hero.className = `panel drv-hero drv-${by.critical.length ? 'bad' : late ? 'warn' : avail ? 'avail' : 'ok'}`;
    $('drivers-headline').textContent = late ? plural(late, 'pilote à mettre à jour', 'pilotes à mettre à jour')
      : avail ? plural(avail, 'mise à jour disponible', 'mises à jour disponibles') : 'Tous les pilotes sont à jour';
    const parts = [late && `${late} en retard`, avail && plural(avail, 'disponible', 'disponibles'), `${ok} à jour`,
      by.unknown.length && plural(by.unknown.length, 'inconnu', 'inconnus'), by.ignored.length && plural(by.ignored.length, 'ignoré', 'ignorés')];
    $('drivers-sub').textContent = `${parts.filter(Boolean).join(' · ')}. ${d.checking ? 'Nouvelle vérification en cours…' : `Vérifié le ${when}.`}`;
    hero.hidden = false;
    go.hidden = !late;
    go.textContent = `Go : mettre à jour ${late > 1 ? `les ${late} pilotes` : 'le pilote'}`;
    const todo = [...by.critical, ...by.moderate, ...by.avail], rest = [...by.unknown, ...by.ignored, ...by.ok];
    const blocks = [];
    if (todo.length) {
      const ul = el('ul', 'plain be-list');
      ul.append(...todo.map((p) => driverRow(p, false)));
      blocks.push(el('h2', 'drv-sec', 'À traiter'), ul);
      if (avail) blocks.push(el('p', 'muted drv-note', 'Mises à jour non urgentes : « Go » ne les installe qu\'après 6 mois de retard.'));
    }
    if (rest.length) {
      const ul = el('ul', 'plain drv-rest');
      ul.append(...rest.map((p) => driverRow(p, true)));
      blocks.push(el('h2', 'drv-sec', todo.length ? 'Le reste' : 'Pilotes'), ul);
    }
    list.replaceChildren(...blocks);
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Pilotes indisponibles', e);
  }
}
$('drivers-go').addEventListener('click', async () => {
  if (busy) { toast('Jarvis est occupé avec une autre demande.'); return; }
  const out = $('drivers-result'), go = $('drivers-go');
  const say = (kind, text) => { out.textContent = kind === 'jarvis' && text.includes('lancée') ? 'Mise à jour lancée : accepte la demande Windows (UAC) sur le PC.' : text; };
  say('note', 'Envoi…');
  setBusy(true);
  go.disabled = true;
  try {
    const r = await api('/api/drivers/update', { method: 'POST', body: {} });
    if (r.status === 429) { say('note', 'Jarvis est occupé avec une autre demande.'); return; }
    if (!r.ok || !r.data || !r.data.job) { say('fail', 'Demande refusée.'); return; }
    await pollJob(r.data.job, say); // N2 : la PWA demande la confirmation
  } catch (err) {
    if (err.message === 'network') say('fail', 'PC injoignable.');
  } finally {
    setBusy(false);
    go.disabled = false;
  }
});
