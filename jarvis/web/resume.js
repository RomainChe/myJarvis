'use strict';
// ---- Résumé du dashboard (bureau ≥ 1200 px seulement) : réseaux, finances, 2 sources de la veille, mini-PC ----------------
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
  $('dg-minipc').hidden = true;
  $('dg-mp-list').replaceChildren();
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
  const [so, ve, vo, co, mp] = await Promise.allSettled([getData('/api/social'), getData('/api/veille'), getData('/api/voyages'), getData('/api/conso'), getData('/api/minipc')]);
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
  const m = mp.value; // santé du serveur : tuile affichée seulement si le Core répond
  $('dg-minipc').hidden = !m;
  if (m) {
    const n = m.problems.length, plur = (k, w) => `${k} ${w}${k > 1 ? 's' : ''}`;
    $('dg-mp-state').textContent = n ? plur(n, 'problème') : 'Tout va bien';
    const hw = [`disque ${m.disk_free_gb} Go libres`, m.temp_c != null && `${m.temp_c} °C`, m.ram_pct != null && `RAM ${m.ram_pct} %`,
      Number.isInteger(m.uptime_s) && `actif depuis ${Math.floor(m.uptime_s / 86400)} j`].filter(Boolean).join(' · ');
    const lines = [...m.problems.map((p) => ['error', `${p.name} : ${p.problem}`]),
      m.updates && ['', m.updates.count ? `${plur(m.updates.count, 'mise')} à jour${m.updates.security ? ` dont ${m.updates.security} de sécurité` : ''}` : 'Système à jour'],
      m.reboot && ['error', 'Redémarrage requis'], ['', hw],
      ['', m.backup_age_h != null ? `Sauvegarde il y a ${m.backup_age_h} h` : 'Aucune sauvegarde'],
      m.restart_at && ['', `Core relancé le ${fmtDate(m.restart_at * 1000)}`]].filter(Boolean);
    $('dg-mp-list').replaceChildren(...lines.map(([cls, text]) => el('li', cls, text)));
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
