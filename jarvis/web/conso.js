'use strict';
// ---- Consommation : kWh de la prise du PC (cache local du Core, chiffres seulement) ----
const kwh = (n) => (Number.isFinite(n) ? `${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kWh` : 'indisponible');
function consoSub(p, label) {
  const parts = [];
  if (p.eur != null) parts.push(`≈ ${eur(p.eur)}`);
  if (p.prev_kwh != null) parts.push(`${label} : ${kwh(p.prev_kwh)}`);
  if (p.partial) parts.push(`mesuré sur ${Number(p.hours).toLocaleString('fr-FR')} h seulement`);
  return parts.join(' · ');
}
async function loadConso() {
  const err = $('conso-error'), state = $('conso-state'), strip = $('conso-strip'), bars = $('conso-bars');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; strip.replaceChildren(); bars.replaceChildren();
  try {
    const r = await api('/api/conso');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.conso.hidden) return;
    const d = r.data;
    state.hidden = d.configured;
    state.textContent = d.configured ? '' : "Aucune mesure : la prise du PC n'a pas encore été échantillonnée (donnée indisponible).";
    // Nœuds construits puis posés d'un coup : deux chargements en vol (onglet quitté puis rouvert) ne dupliquent rien.
    strip.replaceChildren(...[['jour', "Aujourd'hui", 'hier'], ['semaine', '7 jours', '7 jours avant'], ['mois', '30 jours', '30 jours avant']].map(([key, title, label]) => {
      const p = d.periods[key];
      return stat(title, kwh(p.kwh), consoSub(p, label), '', key === 'jour' ? 'hero' : '');
    }));
    const adv = d.advice?.items ?? [];
    $('conso-advice').replaceChildren(...(adv.length ? adv.map((a) => el('li', '', a.text))
      : [el('li', '', !d.advice?.available ? 'Conseils indisponibles : pas assez de mesures.' : d.advice.evaluable ? 'Rien d’anormal cette semaine.' : 'Pas assez de relevés complets sur 7 jours pour te conseiller.')]));
    const h = d.home, hs = $('conso-home-state');
    hs.textContent = h?.configured
      ? `${h.source}. Dernier jour relevé : ${h.last_day}${h.stale ? ' (ancien : le relevé de la veille manque)' : ''}.`
      : 'Aucun relevé du compteur : donnée indisponible (MyElectricalData non configuré ou injoignable).';
    $('conso-home-strip').replaceChildren(...(h?.configured ? [['jour', 'Hier', 'la veille'], ['semaine', '7 jours', '7 jours avant'], ['mois', '30 jours', '30 jours avant']] : []).map(([key, title, label]) => {
      const p = h.periods[key];
      const sub = [consoSub(p, label).replace(/ · mesuré sur .*$/, ''), p.pc_share != null ? `PC ${Math.round(p.pc_share * 100)} %${p.pc_partial ? ' (minimum)' : ''}` : '',
        p.prev_partial ? `période d'avant : ${p.prev_days} j seulement` : '',
        p.partial ? `${p.days} jours relevés seulement` : ''].filter(Boolean).join(' · ');
      return stat(title, kwh(p.kwh), sub);
    }));
    const max = Math.max(0.001, ...d.series.map((x) => x.kwh ?? 0));
    bars.replaceChildren(...d.series.map((x, i) => { // jour sans mesure = colonne hachurée ; dernier jour (en cours) = contour
      const none = x.kwh == null, b = el('span', `conso-bar${none ? ' none' : ''}${i === d.series.length - 1 ? ' today' : ''}`);
      b.style.height = none ? '100%' : `${Math.max(3, Math.round((x.kwh / max) * 100))}%`;
      b.title = `${x.day} : ${kwh(x.kwh)}`;
      return b;
    }));
    $('conso-max').textContent = kwh(max).replace(' kWh', '');
    $('conso-first').textContent = d.series[0] ? new Date(`${d.series[0].day}T00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) : '';
    $('conso-source').textContent = d.series.some((x) => x.kwh != null) ? d.source : `Aucune mesure sur 30 jours (donnée indisponible). ${d.source}`;
    $('conso-price').value = d.price_kwh ?? '';
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Consommation indisponible', e);
  }
}
$('conso-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const out = $('conso-result');
  try {
    const r = await api('/api/conso/tarif', { method: 'PUT', body: { price_kwh: Number($('conso-price').value) } });
    out.textContent = r.ok ? 'Prix enregistré.' : 'Prix refusé (entre 0 et 5 €).';
    if (r.ok) loadConso();
  } catch { out.textContent = 'Enregistrement impossible.'; }
});
