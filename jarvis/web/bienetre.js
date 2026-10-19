'use strict';
// ---- Bien-être du PC : bilan quotidien du projet bien-etre-pc (JSON écrit par `python -m bienetre` : donnée, texte seul) ----
let bienetreTimer = 0;
async function loadBienetre() {
  clearTimeout(bienetreTimer);
  const err = $('bienetre-error'), state = $('bienetre-state'), list = $('bienetre-list');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren();
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
    const prev = d.previous ? `, contre ${d.previous.counts['problème']} et ${d.previous.counts['à surveiller']} le ${new Date(`${d.previous.day}T00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })}` : '';
    const strip = el('div', 'strip');
    strip.append(stat('Problèmes', String(d.counts['problème']), prev ? `Aujourd'hui${prev}` : undefined, '', d.counts['problème'] ? 'alarm' : 'hero'),
      stat('À surveiller', String(d.counts['à surveiller'])), stat('Tout va bien', String(d.counts.OK), `${d.counts['non mesuré']} non mesuré(s)`));
    const note = d.running ? 'Nouvelle mesure en cours…' : d.error ? `Mesure du jour : ${d.error}.` : `Bilan du ${when}, renouvelé chaque jour.`;
    const row = (i) => {
      const k = i.statut === 'problème' ? 'bad' : i.statut === 'à surveiller' ? 'warn' : 'none';
      const li = el('li', `be-item be-card-${k}`);
      const head = el('div', 'be-head'), t = el('p', 'be-title');
      t.append(el('strong', '', i.composant), el('span', 'be-point', i.point));
      head.append(t, el('span', `badge be-${k}`, i.statut));
      li.append(head, el('p', 'be-value', i.valeur));
      if (i.statut !== 'OK' && i.conseil) {
        const tip = el('p', 'be-tip');
        tip.append(el('span', 'be-tip-l', 'Conseil'), document.createTextNode(i.conseil));
        li.append(tip);
      }
      return li;
    };
    const section = (title, items) => {
      if (!items.length) return [];
      const ul = el('ul', 'plain be-list');
      ul.append(...items.map(row));
      return [el('h2', 'section', title), ul];
    };
    const by = (...st) => d.items.filter((i) => st.includes(i.statut));
    const ok = by('OK');
    const okList = el('ul', 'plain be-list');
    okList.append(...ok.map(row));
    const okBlock = el('details', 'panel');
    okBlock.append(el('summary', '', `Points en bon état (${ok.length})`), okList);
    list.replaceChildren(el('p', 'muted', note), strip, ...section('À améliorer', by('problème', 'à surveiller')),
      ...section('Non mesurés', by('non mesuré')), ...(ok.length ? [okBlock] : []));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Bien-être indisponible', e);
  }
}
