'use strict';
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
  $('dg-voyage').hidden = true;
  $('dg-hotel').hidden = true;
  $('dg-conso').hidden = true;
}
$('dg-fin-show').addEventListener('click', async () => {
  const run = digestRun;
  $('dg-fin-show').hidden = true;
  let b = null, f = null, failed = false;
  try {
    let r = await api('/api/finance/bank');
    if (r.status === 403) { // D3 : le clic sert de geste pour la clé d'accès
      if (!await unlockFinance()) { if (run === digestRun) { $('dg-fin').textContent = 'Verrouillé.'; $('dg-fin-show').hidden = false; } return; }
      r = await api('/api/finance/bank');
    }
    if (!r.ok || !r.data) throw new Error('bad');
    b = r.data.bank;
  } catch { failed = true; }
  if (!b) try { f = (await getData('/api/finance')).latest; failed = false; } catch { failed = true; }
  if (run !== digestRun || views.chat.hidden) return;
  if (b) {
    $('dg-left').textContent = eur(b.total);
    const at = new Date(b.fetched_at);
    $('dg-fin').textContent = `Solde des comptes · dépensé cette semaine : ${eur(b.week_spent)}${Number.isNaN(at.getTime()) ? '' : ` · maj ${at.toLocaleString('fr-FR', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })}`}`;
  } else if (f) {
    $('dg-left').textContent = eur(f.left_to_live);
    $('dg-fin').textContent = `Reste à vivre · dépensé S${f.week} : ${eur(f.spent?.amount)}`;
  } else $('dg-fin').textContent = failed ? 'Indisponible.' : 'Aucun rapport.';
});
async function loadDigest() {
  clearDigest();
  if (!token || !wide.matches) return;
  const run = digestRun;
  const [so, ve, vo, co] = await Promise.allSettled([getData('/api/social'), getData('/api/veille'), getData('/api/voyages'), getData('/api/conso')]);
  if (run !== digestRun || views.chat.hidden) return;
  const yt = so.value?.youtube;
  if (yt && !yt.error) {
    $('dg-subs').textContent = `${yt.subs} abonnés`;
    const d7 = yt.delta?.d7;
    $('dg-social').textContent = `YouTube${d7 ? ` · 7 j : ${d7.subs >= 0 ? '+' : ''}${d7.subs}` : ''}`;
  } else $('dg-social').textContent = so.status === 'rejected' ? 'Indisponible.' : 'Statistiques YouTube indisponibles.';
  const deal = vo.value?.deal; // bon plan Japon (sous 650 €, escales respectées) : carré affiché seulement s'il existe
  $('dg-voyage').hidden = !deal;
  if (deal) {
    const day = (d) => new Date(`${d}T00:00`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
    const stops = deal.stops ? ` · ${deal.stops} escale${deal.stops > 1 ? 's' : ''}` : ' · direct';
    $('dg-voy-price').textContent = eur(deal.price);
    $('dg-voy-info').textContent = `${deal.origin} → ${deal.dest} · ${day(deal.depart_date)} → ${day(deal.return_date)}${stops}`;
    const ok = typeof deal.link === 'string' && URL.canParse(deal.link) && new URL(deal.link).protocol === 'https:';
    $('dg-voy-link').replaceChildren(...(ok ? [(() => {
      const li = el('li'), a = el('a', '', "Voir l'offre");
      a.href = deal.link; a.target = '_blank'; a.rel = 'noopener noreferrer';
      li.append(a, el('span', 'muted', new URL(deal.link).hostname));
      return li;
    })()] : []));
  }
  const today = co.value?.periods?.jour; // carré affiché seulement s'il existe une mesure du jour
  $('dg-conso').hidden = today?.kwh == null;
  if (today?.kwh != null) {
    $('dg-conso-kwh').textContent = kwh(today.kwh);
    $('dg-conso-info').textContent = ["aujourd'hui", today.eur != null ? `≈ ${eur(today.eur)}` : '', today.partial ? 'mesure partielle' : ''].filter(Boolean).join(' · ');
  }
  const hotels = vo.value?.hotels; // dernier relevé d'hôtels (hotel-price-tracker) : carré affiché seulement s'il existe
  $('dg-hotel').hidden = !hotels?.configured;
  if (hotels?.configured) {
    const cur = hotels.devise === 'EUR' ? '€' : hotels.devise, n = (v) => `${Math.round(v)} ${cur}`;
    const st = hotels.etapes ?? [], from = st[0]?.chk_in, to = st[st.length - 1]?.chk_out;
    $('dg-hotel-price').textContent = n(hotels.total_recommande);
    $('dg-hotel-info').textContent = [from && to ? `${from} → ${to}` : '', `moins cher ${n(hotels.total_moins_cher)}`,
      'trajets compris', hotels.complet ? '' : 'incomplet'].filter(Boolean).join(' · ');
  }
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
