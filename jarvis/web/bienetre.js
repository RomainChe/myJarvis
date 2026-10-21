'use strict';
// ---- Bien-être du PC : bilan quotidien du projet bien-etre-pc (JSON écrit par `python -m bienetre` : donnée, texte seul) ----
const BE_KIND = { 'problème': 'bad', 'à surveiller': 'warn', OK: 'ok' }; // autre statut (non mesuré) : neutre
// Santé = part des points mesurés en bon état ; 100 si rien de mesuré (comme Pilotes).
function bienetreScore(c) {
  const known = c.OK + c['à surveiller'] + c['problème'];
  return known ? Math.round(100 * c.OK / known) : 100;
}
// Icône d'après le nom du composant (jamais un chemin construit) ; défaut : puce.
const BE_ICONS = [[/gpu|graphi|vid[ée]o|nvidia|affichage/i, 'gpu'], [/wi-?fi|r[ée]seau|network/i, 'wifi'], [/bluetooth/i, 'bt'],
  [/audio|son|haut-parleur/i, 'speaker'], [/disque|stockage|ssd|nvme/i, 'server'], [/s[ée]curit|pare-feu|defender|antivirus/i, 'shield'],
  [/alimentation|[ée]nergie|batterie|ventilat|temp[ée]rature/i, 'bolt'], [/d[ée]marrage|uptime|activit[ée]/i, 'clock']];
function bienetreIcon(composant) {
  const m = BE_ICONS.find(([re]) => re.test(String(composant)));
  return m ? m[1] : 'chip';
}
let bienetreTimer = 0;
async function loadBienetre() {
  clearTimeout(bienetreTimer);
  const err = $('bienetre-error'), state = $('bienetre-state'), list = $('bienetre-list'), hero = $('bienetre-hero');
  err.hidden = true; hero.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren();
  try {
    const r = await api('/api/bienetre');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.bienetre.hidden) return; // vue quittée pendant le chargement
    const d = r.data;
    if (!d.configured) { state.textContent = 'Projet bien-etre-pc introuvable.'; return; }
    if (d.offline) { state.textContent = 'PC éteint ou injoignable : bilan indisponible.'; return; }
    if (d.running) bienetreTimer = setTimeout(loadBienetre, 15000); // mesure en cours (~5 s) : on relit
    if (!d.counts) { state.textContent = d.running ? 'Première mesure en cours…' : (d.error ?? 'Aucun bilan pour le moment.'); return; }
    state.hidden = true;
    const when = new Date(d.at).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    const c = d.counts, bad = c['problème'], warn = c['à surveiller'], ok = c.OK;
    const plural = (n, one, many) => `${n} ${n > 1 ? many : one}`;
    const prev = d.previous ? ` Veille : ${d.previous.counts['problème']} problème(s), ${d.previous.counts['à surveiller']} à surveiller.` : '';
    hero.className = `panel drv-hero drv-${bad ? 'bad' : warn ? 'warn' : 'ok'}`;
    $('bienetre-gauge').replaceChildren(gauge('Santé', bienetreScore(c), `${ok} sur ${ok + warn + bad} en bon état`, bad > 0));
    $('bienetre-headline').textContent = bad ? plural(bad, 'problème à traiter', 'problèmes à traiter')
      : warn ? plural(warn, 'point à surveiller', 'points à surveiller') : 'Tout va bien';
    const parts = [bad && plural(bad, 'problème', 'problèmes'), warn && `${warn} à surveiller`, `${ok} en bon état`, c['non mesuré'] && `${c['non mesuré']} non mesuré(s)`];
    const note = d.running ? 'Nouvelle mesure en cours…' : d.error ? `Mesure du jour : ${d.error}${d.error_at ? ` depuis ${new Date(d.error_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}` : ''}.` : `Bilan du ${when}, renouvelé chaque jour.`;
    $('bienetre-sub').textContent = `${parts.filter(Boolean).join(' · ')}. ${note}${prev}`;
    hero.hidden = false;
    const row = (i, compact) => {
      const k = BE_KIND[i.statut] || 'none';
      const li = el('li', `be-item drv drv-${k}${compact ? ' drv-compact' : ''}`);
      const tile = el('span', 'drv-ico');
      tile.append(icon(bienetreIcon(i.composant)));
      const head = el('div', 'be-head'), t = el('p', 'be-title');
      t.append(el('strong', '', i.composant), el('span', 'be-point', i.point));
      const badge = el('span', 'badge drv-badge be-badge', i.statut === 'OK' ? 'En bon état' : i.statut);
      badge.prepend(icon(k === 'ok' ? 'check' : k === 'none' ? 'clock' : 'alert')); // statut = icône + texte, pas la couleur seule
      head.append(tile, t, badge);
      li.append(head, el('p', 'be-value', i.valeur));
      if (i.statut !== 'OK' && i.conseil) {
        const tip = el('p', 'be-tip');
        tip.append(el('span', 'be-tip-l', 'Conseil'), document.createTextNode(i.conseil));
        li.append(tip);
      }
      return li;
    };
    const section = (title, items, compact, cls = 'plain be-list') => {
      if (!items.length) return [];
      const ul = el('ul', cls);
      ul.append(...items.map((i) => row(i, compact)));
      return [el('h2', 'drv-sec', title), ul];
    };
    const by = (...st) => d.items.filter((i) => st.includes(i.statut));
    list.replaceChildren(...section('À améliorer', by('problème', 'à surveiller'), false),
      ...section('En bon état', by('OK'), true, 'plain drv-rest'), ...section('Non mesurés', by('non mesuré'), true, 'plain drv-rest'));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Bien-être indisponible', e);
  }
}
