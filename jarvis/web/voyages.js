'use strict';
// ---- Voyages : prix suivis par flight-price-tracker (CSV écrit par son workflow : donnée, texte seul, liens https) ----
const day = (d) => new Date(`${d}T00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
const stat = (title, big, sub) => {
  const s = el('section', 'panel hud stat');
  s.append(el('h2', '', title), el('p', 'big', big));
  if (sub) s.append(el('p', 'muted', sub));
  return s;
};
async function loadVoyages() {
  const err = $('voyages-error'), state = $('voyages-state'), list = $('voyages-list');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren();
  try {
    const r = await api('/api/voyages');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.voyages.hidden) return; // vue quittée pendant le chargement
    if (!r.data.searches.length) { state.textContent = r.data.configured ? 'Aucun prix relevé.' : 'Projet flight-price-tracker introuvable.'; return; }
    state.hidden = true;
    const sync = r.data.sync_error ? r.data.sync_error
      : r.data.synced_at ? `Synchronisé avec GitHub le ${new Date(r.data.synced_at).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' })}`
      : 'Copie locale (non synchronisée avec GitHub)';
    list.replaceChildren(el('p', 'muted', sync), ...r.data.searches.map((s, i) => {
      const d = el('details', 'panel hud');
      d.open = i === 0; // la recherche la plus récente = destination en cours
      d.append(el('summary', '', `${s.name} · ${eur(s.best.price)}`));
      const delta = s.previous == null ? 'Premier relevé' : s.best.price === s.previous ? 'Stable depuis le relevé précédent'
        : `${s.best.price < s.previous ? '▼' : '▲'} ${eur(Math.abs(s.best.price - s.previous))} depuis le relevé précédent`;
      const strip = el('div', 'strip');
      strip.append(stat('Meilleur prix', eur(s.best.price), delta), stat('Plus bas observé', eur(s.lowest), `${s.history.length} relevé(s)`),
        stat('Dernier relevé', day(s.last_run)));
      const b = s.best, offer = el('p', 'voy-offer');
      const stops = b.stops == null ? '' : b.stops ? ` · ${b.stops} escale${b.stops > 1 ? 's' : ''}` : ' · direct';
      const dur = b.duration_min ? ` · ${Math.floor(b.duration_min / 60)} h ${String(b.duration_min % 60).padStart(2, '0')}` : '';
      offer.append(el('strong', '', `${b.origin} → ${b.dest}`), el('span', '', ` · ${day(b.depart_date)} → ${day(b.return_date)}${b.airlines ? ` · ${b.airlines}` : ''}${stops}${dur} · ${b.source}`));
      if (b.link && URL.canParse(b.link) && new URL(b.link).protocol === 'https:') {
        const a = el('a', '', "Voir l'offre");
        a.href = b.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
        offer.append(el('br'), a, el('span', 'muted', ` · ${new URL(b.link).hostname}`));
      }
      const by = el('ul', 'plain voy-origins');
      for (const o of s.by_origin) {
        const li = el('li');
        li.append(el('span', '', o.origin), el('span', 'voy-price', eur(o.price)));
        by.append(li);
      }
      d.append(strip, el('h3', 'voy-h', 'Meilleure offre'), offer, el('h3', 'voy-h', 'Par aéroport de départ'), by);
      return d;
    }));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Voyages indisponibles', e);
  }
}
$('voy-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (busy) { toast('Jarvis est occupé avec une autre demande.'); return; }
  const out = $('voy-result'), say = (_kind, text) => { out.textContent = text; };
  const v = (id) => $(id).value.trim();
  say('note', 'Envoi…');
  setBusy(true);
  $('voy-submit').disabled = true;
  try {
    const r = await api('/api/voyages/destination', { method: 'POST', body: {
      destination: v('voy-dest'), origins: v('voy-origins'), depart_from: v('voy-from'), depart_to: v('voy-to'),
      stay_days: v('voy-stays'), return_date: v('voy-back'), alert_below: Math.trunc(Number(v('voy-alert'))) || 0 } });
    if (r.status === 429) { say('note', 'Jarvis est occupé avec une autre demande.'); return; }
    if (!r.ok || !r.data || !r.data.job) { say('fail', 'Formulaire refusé : vérifie les champs.'); return; }
    await pollJob(r.data.job, say);
    if (!views.voyages.hidden) loadVoyages();
  } catch (err) {
    if (err.message === 'network') say('fail', 'PC injoignable.');
  } finally {
    setBusy(false);
    $('voy-submit').disabled = false;
  }
});
