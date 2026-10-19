'use strict';
// ---- Résumé du dashboard (bureau ≥ 1200 px seulement) : réseaux, finances, 3 articles de la veille, mini-PC ----------------
// Chargé une fois à l'ouverture du dashboard, sans minuteur. Finances affichées d'emblée (choix du propriétaire, 2026-10-19,
// à la place du masquage de la revue Sécurité constat 1). Vidé dès qu'on quitte la vue.
const wide = matchMedia('(min-width: 1200px)');
let digestRun = 0;
const getData = (path) => api(path).then((r) => { if (!r.ok || !r.data) throw new Error('bad'); return r.data; });
function clearDigest() {
  digestRun++; // une réponse arrivée après coup est ignorée
  $('dg-subs').textContent = $('dg-left').textContent = '—';
  for (const id of ['dg-social', 'dg-fin', 'dg-veille-state']) $(id).textContent = '';
  for (const id of ['dg-veille', 'dg-mp-gauges', 'dg-mp-list', 'dg-conso-bars']) $(id).replaceChildren();
  $('dg-voyage').hidden = $('dg-minipc').hidden = $('dg-conso').hidden = true;
}
// Solde des comptes, sinon reste à vivre du dernier rapport hebdo
async function digestFinance() {
  try { const b = (await getData('/api/finance/bank')).bank; if (b) return { b }; } catch { /* rapport hebdo en repli */ }
  return { f: (await getData('/api/finance')).latest };
}
async function loadDigest() {
  clearDigest();
  if (!token || !wide.matches) return;
  const run = digestRun;
  const [so, ve, vo, co, mp, fi] = await Promise.allSettled([getData('/api/social'), getData('/api/veille'), getData('/api/voyages'),
    getData('/api/conso'), getData('/api/minipc'), digestFinance()]);
  if (run !== digestRun || views.chat.hidden) return;
  const yt = so.value?.youtube;
  if (yt && !yt.error) {
    $('dg-subs').textContent = `${yt.subs} abonnés`;
    const d7 = yt.delta?.d7;
    $('dg-social').textContent = `YouTube${d7 ? ` · 7 j : ${d7.subs >= 0 ? '+' : ''}${d7.subs}` : ''}`;
  } else $('dg-social').textContent = so.status === 'rejected' ? 'Indisponible.' : 'Statistiques YouTube indisponibles.';
  const { b, f } = fi.value ?? {};
  if (b) {
    $('dg-left').textContent = eur(b.total);
    const at = new Date(b.fetched_at);
    $('dg-fin').textContent = `Solde des comptes · dépensé cette semaine : ${eur(b.week_spent)}${Number.isNaN(at.getTime()) ? '' : ` · maj ${at.toLocaleString('fr-FR', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })}`}`;
  } else if (f) {
    $('dg-left').textContent = eur(f.left_to_live);
    $('dg-fin').textContent = `Reste à vivre · dépensé S${f.week} : ${eur(f.spent?.amount)}`;
  } else $('dg-fin').textContent = fi.status === 'rejected' ? 'Indisponible.' : 'Aucun rapport.';
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
    const week = (co.value.series ?? []).slice(-7), top = Math.max(0.01, ...week.map((x) => x.kwh ?? 0)); // 7 derniers jours, aujourd'hui à droite
    $('dg-conso-bars').replaceChildren(...week.map((x, i) => {
      const bar = el('span', `${x.kwh == null ? 'none' : ''}${i === week.length - 1 ? ' today' : ''}`);
      bar.style.height = `${x.kwh == null ? 100 : Math.max(6, Math.round((x.kwh / top) * 100))}%`;
      return bar;
    }));
  }
  const m = mp.value; // santé du serveur : tuile affichée seulement si le Core répond
  $('dg-minipc').hidden = !m;
  if (m) {
    const n = m.problems.length, plur = (k, w) => `${k} ${w}${k > 1 ? 's' : ''}`;
    $('dg-mp-state').textContent = n ? plur(n, 'problème') : 'Tout va bien';
    $('dg-minipc').classList.toggle('bad', n > 0);
    const used = m.disk_total_gb ? 100 - (100 * m.disk_free_gb) / m.disk_total_gb : null;
    $('dg-mp-gauges').replaceChildren(...[
      m.ram_pct != null && gauge('RAM', m.ram_pct, ''),
      used != null && gauge('Disque', used, `${m.disk_free_gb} Go libres`),
      m.temp_c != null && gauge('Temp.', m.temp_c, `${m.temp_c} °C`, m.temp_c >= 80, `${Math.round(m.temp_c)}°`)].filter(Boolean));
    const lines = [...m.problems.map((p) => ['alert', 'bad', `${p.name} : ${p.problem}`]),
      m.reboot && ['alert', 'bad', 'Redémarrage requis'],
      m.updates && (m.updates.count ? ['alert', 'warn', `${plur(m.updates.count, 'mise')} à jour${m.updates.security ? ` dont ${m.updates.security} de sécurité` : ''}`] : ['check', 'ok', 'Système à jour']),
      m.backup_age_h != null ? ['check', m.backup_age_h > 48 ? 'warn' : 'ok', `Sauvegarde il y a ${m.backup_age_h} h`] : ['alert', 'bad', 'Aucune sauvegarde'],
      m.restart_at && ['repeat', '', `Core relancé le ${fmtDate(m.restart_at * 1000)}`]].filter(Boolean);
    $('dg-mp-list').replaceChildren(...lines.map(([ico, cls, text]) => {
      const li = el('li', cls), i = icon(ico);
      li.append(i, el('span', '', text));
      return li;
    }));
  }
  const next = so.value?.scheduled?.[0];
  if (next) $('dg-social').textContent += ` · prochaine : ${fmtDate(next.at)}`;
  const issue = ve.value?.issues?.[0];
  const ok = (l) => l && typeof l.url === 'string' && URL.canParse(l.url) && new URL(l.url).protocol === 'https:';
  const titled = (issue?.items ?? []).filter((x) => ok(x.link) && x.lines?.[0]).map((x) => ({ url: x.link.url, label: x.lines[0].replace(MARK_RE, '').replace(SCORE, '').replace(/[\s:·|(]+\)?\s*$/, '') }));
  const links = (titled.length ? titled : (issue?.links ?? []).filter(ok)).slice(0, 3);
  $('dg-veille-state').textContent = ve.status === 'rejected' ? 'Indisponible.' : !issue ? 'Aucun envoi.' : `${VEILLE[issue.kind] ?? issue.kind} · semaine ${issue.week}`;
  $('dg-veille').replaceChildren(...links.map((l) => {
    const host = new URL(l.url).hostname; // destination réelle, pas le champ du serveur
    const li = el('li'), text = el('div', 'dg-news'), a = el('a', '', l.label || host);
    a.href = l.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    text.append(a, el('span', 'muted', host));
    li.append(brandMark(l.label || ''), text);
    return li;
  }));
}
wide.addEventListener('change', () => { if (!views.chat.hidden) loadDigest(); });
