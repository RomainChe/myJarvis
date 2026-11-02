'use strict';
// ---- Comparatif des IA (section de Veille IA) : notes sur 100 par domaine, relevées chaque jour par le Core ----
// Données des sources publiques (Epoch AI, LMArena, Artificial Analysis) : nombres et noms affichés en texte seul.
const IAC_BADGES = { claude_code: 'Claude Code', copilot: 'Copilot' };
const IAC_GAP = 20; // points sous la moyenne du top 5 : au-delà, un modèle est masqué (sauf « tous les modèles »)
const IAC_VIEWS = [['rank', 'Classement'], ['duel', 'Duel'], ['price', 'Prix et vitesse']];
const IAC_OPTS = [['delta', 'Écart de version'], ['price', 'Prix'], ['speed', 'Vitesse'], ['old', 'Anciennes versions'], ['all', 'Tous les modèles']];
// Profil du verdict : écart de note maximal toléré avec le meilleur modèle actuel (le taux d'erreur d'un modèle = 100 − sa note).
const IAC_PROFILES = [['safe', 'Fiabilité d\'abord', 5], ['balanced', 'Équilibré', 10], ['eco', 'Économie', 20]];
const IAC_BUDGETS = [1, 2, 5, 10], IAC_SPEEDS = [50, 100, 150];
const iac = { data: null, prefs: { view: 'rank', off: [], delta: false, price: true, speed: true, old: false, all: false, duel: [], sort: 'avg', profile: 'safe', budget: null, minSpeed: null } };
const IAC_SORTS = ['avg', 'price', 'tps'];

// Moyenne des domaines cochés disponibles pour ce modèle (null s'il n'en a aucun).
function iacAvg(m, doms) {
  const v = doms.map((d) => m.scores?.[d]?.score).filter((x) => typeof x === 'number');
  return v.length ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 10) / 10 : null;
}
// Taux d'erreur (% de réponses ratées) et multiple d'erreurs par rapport au meilleur modèle (1 = autant).
const iacErr = (avg) => Math.round((100 - avg) * 10) / 10;
const iacErrX = (avg, ref) => (ref < 100 ? Math.round(((100 - avg) / (100 - ref)) * 10) / 10 : null);
// Nombre de tests derrière la note (sert à départager deux notes égales : plus de tests = note plus solide).
const iacTests = (m, doms) => doms.reduce((n, d) => n + (m.scores?.[d]?.n ?? 0), 0);
// Modèles du classement : notés, version actuelle (sauf « anciennes versions »), triés ; ceux trop loin du top 5 sont masqués (sauf « tous »).
function iacRanked(models, doms, opts) {
  const all = models.map((m) => ({ m, avg: iacAvg(m, doms), n: iacTests(m, doms) }))
    .filter((x) => x.avg !== null && (opts.old || x.m.gen === 'current'))
    .sort((a, b) => b.avg - a.avg || b.n - a.n || a.m.name.localeCompare(b.m.name));
  const top = all.filter((x) => x.m.gen === 'current').slice(0, 5);
  const floor = top.length ? top.reduce((s, x) => s + x.avg, 0) / top.length - IAC_GAP : -Infinity;
  return { rows: opts.all ? all : all.filter((x) => x.avg >= floor), hidden: all.filter((x) => x.avg < floor).length };
}
// Verdict prix et vitesse : seuls les modèles actuels assez fiables (écart de note du profil) et dans les plafonds (budget, vitesse)
// peuvent être « meilleur choix », « moins cher » ou « plus rapide ». `cheapestAny` et `fastestAny` disent qui a été écarté.
function iacVerdicts(models, doms, prefs) {
  const cur = models.filter((m) => m.gen === 'current').map((m) => ({ m, avg: iacAvg(m, doms) })).filter((x) => x.avg !== null);
  if (!cur.length) return null;
  const ref = cur.reduce((a, b) => (b.avg > a.avg ? b : a));
  const gap = (IAC_PROFILES.find((p) => p[0] === prefs.profile) ?? IAC_PROFILES[0])[2], floor = ref.avg - gap;
  const within = (x) => (prefs.budget == null || (typeof x.m.price_mix === 'number' && x.m.price_mix <= prefs.budget))
    && (prefs.minSpeed == null || (typeof x.m.tps === 'number' && x.m.tps >= prefs.minSpeed));
  const pool = cur.filter((x) => x.avg >= floor && within(x));
  const first = (list, key, low) => list.filter((x) => typeof x.m[key] === 'number')
    .sort((a, b) => (low ? a.m[key] - b.m[key] : b.m[key] - a.m[key]) || b.avg - a.avg)[0]?.m ?? null;
  const pick = pool.filter((x) => x.m.price_mix > 0).sort((a, b) => b.avg / b.m.price_mix - a.avg / a.m.price_mix)[0]?.m ?? null;
  return { ref: ref.m, refAvg: ref.avg, gap, floor, pool: new Set(pool.map((x) => x.m.id)), pick,
    cheapest: first(pool, 'price_mix', true), fastest: first(pool, 'tps', false),
    cheapestAny: first(cur.filter(within), 'price_mix', true), fastestAny: first(cur.filter(within), 'tps', false) };
}

const iacDoms = () => (iac.data?.domains ?? []).map((d) => d.id).filter((d) => !iac.prefs.off.includes(d));
const fmtNum = (v, n = 1) => (typeof v === 'number' ? v.toLocaleString('fr-FR', { maximumFractionDigits: n }) : '—');
const fmtUsd = (v) => (typeof v === 'number' ? `${v.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} $` : '—');
// Couleur d'une cellule : teinte 0 (rouge) → 125 (vert) selon t entre 0 et 1.
const iacHue = (t) => Math.round(Math.max(0, Math.min(1, t)) * 125);
function iacHeat(td, t) { td.classList.add('iac-heat'); td.style.setProperty('--h', String(iacHue(t))); return td; }
const iacHuePrice = (p) => 1 - (Math.log10(Math.max(p, 0.1)) + 1) / 2.4; // 0,1 $ = vert, 25 $ = rouge
const iacHueSpeed = (t) => (t - 40) / 200;
function iacSave() { kv('readwrite', (s) => s.put(JSON.stringify(iac.prefs), 'iacompare')).catch(() => {}); }
async function iacLoadPrefs() {
  try {
    const p = JSON.parse(await kv('readonly', (s) => s.get('iacompare')) || '{}');
    if (p && typeof p === 'object') {
      for (const k of ['delta', 'price', 'speed', 'old', 'all']) if (typeof p[k] === 'boolean') iac.prefs[k] = p[k];
      if (IAC_VIEWS.some(([v]) => v === p.view)) iac.prefs.view = p.view;
      if (IAC_SORTS.includes(p.sort)) iac.prefs.sort = p.sort;
      if (IAC_PROFILES.some(([v]) => v === p.profile)) iac.prefs.profile = p.profile;
      if (IAC_BUDGETS.includes(p.budget) || p.budget === null) iac.prefs.budget = p.budget;
      if (IAC_SPEEDS.includes(p.minSpeed) || p.minSpeed === null) iac.prefs.minSpeed = p.minSpeed;
      if (Array.isArray(p.off)) iac.prefs.off = p.off.filter((x) => typeof x === 'string');
      if (Array.isArray(p.duel)) iac.prefs.duel = p.duel.filter((x) => typeof x === 'string').slice(0, 3);
    }
  } catch { /* préférences illisibles : valeurs par défaut */ }
}

function iacToggle(label, on, onClick, cls = '') {
  const b = el('button', `chip tog${cls ? ` ${cls}` : ''}`, label);
  b.type = 'button';
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  b.addEventListener('click', onClick);
  return b;
}
function iacFilters() {
  const box = $('iac-filters');
  const seg = el('div', 'seg iac-seg');
  seg.setAttribute('role', 'group'); seg.setAttribute('aria-label', 'Vue du comparatif');
  for (const [v, label] of IAC_VIEWS) {
    const b = el('button', 'n0', label);
    b.type = 'button';
    b.setAttribute('aria-pressed', iac.prefs.view === v ? 'true' : 'false');
    b.addEventListener('click', () => { iac.prefs.view = v; iacSave(); iacRender(); });
    seg.append(b);
  }
  const doms = el('div', 'chips'), opts = el('div', 'chips');
  doms.setAttribute('role', 'group'); doms.setAttribute('aria-label', 'Domaines comparés');
  opts.setAttribute('role', 'group'); opts.setAttribute('aria-label', 'Informations affichées');
  for (const d of iac.data.domains) {
    const has = iac.data.models.some((m) => m.scores?.[d.id]), on = has && !iac.prefs.off.includes(d.id);
    const b = iacToggle(has ? d.label : `${d.label} · aucune donnée`, on, () => {
      iac.prefs.off = on ? [...iac.prefs.off, d.id] : iac.prefs.off.filter((x) => x !== d.id);
      if (!iacDoms().length) iac.prefs.off = iac.prefs.off.filter((x) => x !== d.id); // au moins un domaine
      iacSave(); iacRender();
    }, 'dom');
    if (!has) { b.disabled = true; b.title = 'Aucun modèle n\'a de note pour ce domaine'; }
    doms.append(b);
  }
  for (const [k, label] of IAC_OPTS) opts.append(iacToggle(label, iac.prefs[k], () => { iac.prefs[k] = !iac.prefs[k]; iacSave(); iacRender(); }));
  box.replaceChildren(seg, doms, opts);
}

const iacDomLabel = (id) => iac.data.domains.find((d) => d.id === id)?.label ?? id;
function iacMeter(label, d) {
  const li = el('li'), head = el('div', 'meter-head');
  head.append(el('span', '', label), el('span', '', d ? fmtNum(d.score) : '—'));
  const bar = el('div', 'meter-bar'), fill = el('span');
  fill.style.width = `${d ? Math.max(0, Math.min(100, d.score)) : 0}%`;
  bar.append(fill);
  li.append(head, bar);
  if (d && d.n < 2) li.append(el('small', 'muted', 'peu de données'));
  return li;
}
function iacDetail(m, doms) {
  const ul = el('ul', 'plain iac-detail');
  for (const d of iac.data.domains.filter((x) => doms.includes(x.id))) {
    for (const t of m.scores?.[d.id]?.detail ?? []) {
      const li = el('li');
      li.append(el('span', '', `${d.label} · ${t.test}`), el('span', 'muted', t.source), el('b', '', fmtNum(t.score)));
      ul.append(li);
    }
  }
  return ul.children.length ? ul : el('p', 'muted', 'Aucun test pour ces domaines.');
}
function iacTable(head, body) {
  const wrap = el('div', 'iac-table-wrap'), t = el('table', 'iac-table'), thead = el('thead');
  thead.append(head);
  t.append(thead, body); wrap.append(t);
  return wrap;
}
function iacRank() {
  const doms = iacDoms(), byId = new Map(iac.data.models.map((m) => [m.id, m])), p = iac.prefs;
  const { rows, hidden } = iacRanked(iac.data.models, doms, p);
  const top = Math.max(0, ...rows.filter((x) => x.m.gen === 'current').map((x) => x.avg));
  const cols = ['', 'Modèle', 'Note /100', ...(p.price ? ['Prix $/M'] : []), ...(p.speed ? ['Tokens/s'] : []), ...(p.delta ? ['Écart de version'] : [])];
  const head = el('tr'), body = el('tbody');
  cols.forEach((c, i) => head.append(el('th', i > 2 && c !== 'Écart de version' ? 'num' : '', c)));
  let pos = 0, last = null;
  rows.forEach(({ m, avg, n }, i) => {
    if (avg !== last) pos = i + 1; // ex æquo : même rang
    last = avg;
    const tr = el('tr', 'iac-r'), det = el('tr', 'iac-det'), dc = el('td');
    det.hidden = true; dc.colSpan = cols.length;
    const cp = el('td'), cn = el('td'), btn = el('button', 'iac-open'), tags = el('span', 'iac-tags');
    cp.append(el('span', `iac-pos${pos <= 3 ? ` r${pos}` : ''}`, String(pos)));
    btn.type = 'button'; btn.setAttribute('aria-expanded', 'false');
    btn.append(brandMark(`${m.name} ${m.lab}`), el('strong', '', m.name));
    if (m.gen !== 'current') tags.append(el('span', 'badge d-neutral', 'version précédente'));
    for (const b of m.badges ?? []) if (IAC_BADGES[b]) tags.append(el('span', 'badge n1', IAC_BADGES[b]));
    cn.append(btn, tags);
    const cs = el('td', 'iac-scorecell'), bar = el('span', 'iac-meter1'), fill = el('i'), chip = el('span', 'iac-sc', fmtNum(avg));
    fill.style.width = `${Math.max(0, Math.min(100, avg))}%`; bar.append(fill);
    chip.style.setProperty('--h', String(iacHue((avg - (top - 25)) / 25)));
    chip.title = `${n} test${n > 1 ? 's' : ''} · ${fmtNum(iacErr(avg))} % d'erreurs`;
    const inner = el('div', 'iac-sc-in');
    inner.append(bar, chip); cs.append(inner);
    tr.append(cp, cn, cs);
    if (p.price) tr.append(el('td', 'num', fmtUsd(m.price_mix)));
    if (p.speed) tr.append(el('td', 'num', fmtNum(m.tps, 0)));
    if (p.delta) {
      const prev = m.prev && byId.get(m.prev), td = el('td');
      const ds = prev ? doms.filter((x) => typeof m.delta?.[x] === 'number').map((x) => `${iacDomLabel(x)} ${m.delta[x] > 0 ? '+' : ''}${fmtNum(m.delta[x])}`) : [];
      if (ds.length) {
        td.append(el('span', '', `vs ${prev.name} : ${ds.join(' · ')}`));
        if (iacTests(prev, doms) !== n) td.append(el('span', 'badge d-warn', 'tests différents'));
      } else td.textContent = '—';
      tr.append(td);
    }
    const meters = el('ul', 'meters iac-meters');
    for (const dm of iac.data.domains.filter((x) => doms.includes(x.id))) meters.append(iacMeter(dm.label, m.scores?.[dm.id]));
    dc.append(meters, iacDetail(m, doms));
    det.append(dc);
    btn.addEventListener('click', () => { det.hidden = !det.hidden; btn.setAttribute('aria-expanded', String(!det.hidden)); });
    body.append(tr, det);
  });
  const out = [el('p', 'muted iac-note', 'Note sur 100 = moyenne des domaines cochés (tests publics : SWE-bench, GPQA, ARC-AGI…) ; 100 − note = taux d\'erreur. Version actuelle de chaque IA seulement : « Anciennes versions » affiche les précédentes, notées sur d\'autres tests. Ouvrir une ligne pour le détail.')];
  out.push(rows.length ? iacTable(head, body) : el('p', 'muted', 'Aucune note pour ces domaines.'));
  if (hidden && !p.all) out.push(el('p', 'muted iac-note', `${hidden} modèle${hidden > 1 ? 's' : ''} masqué${hidden > 1 ? 's' : ''} : à plus de ${IAC_GAP} points du top 5.`));
  return out;
}

// ---- Duel : graphique à barres multiples (une couleur et une lettre A/B/C par modèle) ----
// groups : [{ title, note?, rows: [{ label, vals: [nombre|null par modèle], texts, max, low? }] }] ; low = plus petit est meilleur (prix, erreurs).
const IAC_LETTERS = 'ABC';
function iacChart(groups, models) {
  const root = el('div', 'iac-chart'), legend = el('ul', 'plain iac-legend');
  models.forEach((m, i) => { const li = el('li'); li.append(el('i', `iac-sw s${i}`, IAC_LETTERS[i]), brandMark(`${m.name} ${m.lab}`), el('span', '', m.name)); legend.append(li); });
  root.append(legend);
  for (const g of groups) {
    const sec = el('section', 'iac-chart-group');
    sec.append(el('h3', '', g.title));
    for (const r of g.rows) {
      const row = el('div', 'iac-bar-row'), known = r.vals.filter((v) => typeof v === 'number');
      const best = known.length > 1 ? (r.low ? Math.min(...known) : Math.max(...known)) : null;
      row.append(el('span', 'iac-bar-label', r.label));
      r.vals.forEach((v, i) => {
        const bar = el('div', `iac-bar s${i}${v === best ? ' win' : ''}`), track = el('span', 'track'), fill = el('i'), val = el('b', v === best ? 'win' : '', `${v === best ? '★ ' : ''}${r.texts[i]}`);
        fill.style.width = `${typeof v === 'number' && r.max ? Math.max(2, Math.min(100, (v / r.max) * 100)) : 0}%`;
        track.append(fill);
        bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', `${IAC_LETTERS[i]}, ${models[i].name} : ${r.texts[i]}`);
        bar.append(el('i', `iac-sw s${i}`, IAC_LETTERS[i]), track, val);
        row.append(bar);
      });
      sec.append(row);
    }
    if (g.note) sec.append(el('p', 'muted iac-note', g.note));
    root.append(sec);
  }
  return root;
}
function iacDuel() {
  const doms = iacDoms(), scored = iac.data.models.filter((m) => Object.keys(m.scores ?? {}).length);
  if (scored.length < 2) return [el('p', 'muted', 'Pas assez de modèles notés pour un duel.')];
  const ids = new Set(scored.map((m) => m.id));
  let pick = iac.prefs.duel.filter((id) => ids.has(id));
  if (pick.length < 2) pick = iacRanked(iac.data.models, doms, { ...iac.prefs, all: true }).rows.slice(0, 2).map((x) => x.m.id);
  const form = el('div', 'iac-duel-pick');
  for (let i = 0; i < 3; i += 1) {
    const lab = el('label', 'iac-pick'), sel = el('select');
    lab.append(el('span', 'muted', `${IAC_LETTERS[i]} · ${i < 2 ? `Modèle ${i + 1}` : 'Modèle 3 (facultatif)'}`), sel);
    if (i === 2) sel.append(new Option('—', ''));
    for (const m of scored) sel.append(new Option(m.name, m.id));
    sel.value = pick[i] ?? '';
    sel.addEventListener('change', () => {
      const next = [pick[0], pick[1], pick[2]]; next[i] = sel.value;
      iac.prefs.duel = next.filter(Boolean).slice(0, 3); iacSave(); iacRender();
    });
    form.append(lab);
  }
  const chosen = pick.map((id) => scored.find((m) => m.id === id)).filter(Boolean);
  const out = [form];
  const sc = (m, d) => m.scores?.[d]?.score;
  const comparable = iac.data.domains.filter((d) => doms.includes(d.id) && chosen.filter((m) => typeof sc(m, d.id) === 'number').length >= 2);
  const groups = [];
  if (comparable.length) {
    groups.push({ title: 'Notes par domaine (sur 100)', rows: comparable.map((d) => ({
      label: d.label, max: 100, vals: chosen.map((m) => sc(m, d.id) ?? null), texts: chosen.map((m) => (typeof sc(m, d.id) === 'number' ? fmtNum(sc(m, d.id)) : 'non noté')) })) });
  }
  const avgs = chosen.map((m) => iacAvg(m, doms)), num = (k) => chosen.map((m) => (typeof m[k] === 'number' ? m[k] : null));
  const eff = [];
  const addEff = (label, vals, texts, low = false) => {
    if (vals.filter((v) => v !== null).length >= 2) eff.push({ label, vals, texts, low, max: Math.max(...vals.filter((v) => v !== null)) });
  };
  addEff('Taux d\'erreur (%, barre courte = moins d\'erreurs)', avgs.map((a) => (a === null ? null : iacErr(a))), avgs.map((a) => (a === null ? '—' : `${fmtNum(iacErr(a))} %`)), true);
  addEff('Vitesse (tokens/s)', num('tps'), chosen.map((m) => fmtNum(m.tps, 0)));
  addEff('Prix mixte ($/M tokens, barre courte = moins cher)', num('price_mix'), chosen.map((m) => fmtUsd(m.price_mix)), true);
  if (eff.length) groups.push({ title: 'Fiabilité, vitesse et coût', rows: eff, note: 'Taux d\'erreur = 100 − note générale des domaines cochés. Prix mixte : 3 tokens lus pour 1 écrit. Un modèle très bon marché peut avoir beaucoup plus d\'erreurs : lisez les deux.' });
  if (!groups.length) { out.push(el('p', 'muted', 'Aucun domaine noté en commun pour ces modèles.')); return out; }
  // Bilan : domaines gagnés par chaque modèle (égalité = personne).
  const wins = chosen.map(() => 0);
  for (const d of comparable) {
    const v = chosen.map((m) => sc(m, d.id) ?? -1), top = Math.max(...v);
    v.forEach((x, i) => { if (x === top && v.filter((y) => y === top).length === 1) wins[i] += 1; });
  }
  if (comparable.length) out.push(el('p', 'iac-wins', `Domaines gagnés (sur ${comparable.length}) : ${chosen.map((m, i) => `${IAC_LETTERS[i]} ${m.name} ${wins[i]}`).join(' · ')}`));
  out.push(iacChart(groups, chosen));
  // Détail test par test : une ligne par test, une colonne par modèle.
  const tests = new Map();
  for (const d of comparable) chosen.forEach((m, i) => (m.scores[d.id]?.detail ?? []).forEach((t) => {
    const k = `${d.label} · ${t.test}`;
    if (!tests.has(k)) tests.set(k, chosen.map(() => null));
    tests.get(k)[i] = t.score;
  }));
  if (tests.size) {
    const more = el('details', 'iac-more'), hr = el('tr'), body = el('tbody');
    hr.append(el('th', '', 'Test'), ...chosen.map((m, i) => el('th', 'num', `${IAC_LETTERS[i]} · ${m.name}`)));
    for (const [k, vals] of tests) {
      const tr = el('tr'), known = vals.filter((v) => v !== null), best = Math.max(...known);
      tr.append(el('th', '', k), ...vals.map((v) => el('td', `num${v === best && known.length > 1 ? ' win' : ''}`, fmtNum(v))));
      body.append(tr);
    }
    more.append(el('summary', '', 'Détail par test'), iacTable(hr, body));
    out.push(more);
  }
  return out;
}

// ---- Prix et vitesse : verdict par profil de fiabilité + tableau coloré ----
function iacSelect(label, id, options, value, fmt, onPick) {
  const lab = el('label', 'iac-pick'), sel = el('select');
  sel.id = id;
  sel.append(new Option('Aucun', ''));
  for (const o of options) sel.append(new Option(fmt(o), String(o)));
  sel.value = value == null ? '' : String(value);
  sel.addEventListener('change', () => { onPick(sel.value === '' ? null : Number(sel.value)); iacSave(); iacRender(); });
  lab.append(el('span', 'muted', label), sel);
  return lab;
}
function iacVerdictCard(title, m, v, doms, extra) {
  const card = el('div', 'iac-vcard');
  card.append(el('span', 'iac-vtitle', title));
  if (!m) { card.append(el('span', 'muted', 'Aucun modèle')); return card; }
  const avg = iacAvg(m, doms), x = iacErrX(avg, v.refAvg), name = el('strong', 'iac-vname');
  name.append(brandMark(`${m.name} ${m.lab}`), document.createTextNode(m.name));
  card.append(name, el('span', 'iac-vbig', extra),
    el('span', 'muted iac-vsub', `note ${fmtNum(avg)} · ${fmtNum(iacErr(avg))} % d'erreurs${x && x > 1 ? ` (${fmtNum(x)}× ${v.ref.name})` : ''}`));
  return card;
}
function iacPrice() {
  const doms = iacDoms(), p = iac.prefs, models = iac.data.models.filter((m) => p.old || m.gen === 'current');
  const v = iacVerdicts(iac.data.models, doms, p), key = p.sort;
  const get = { avg: (m) => iacAvg(m, doms), price: (m) => (typeof m.price_mix === 'number' ? -m.price_mix : null), tps: (m) => m.tps };
  const rows = models.filter((m) => iacAvg(m, doms) !== null && (typeof m.price_mix === 'number' || typeof m.tps === 'number'))
    .sort((a, b) => (get[key](b) ?? -Infinity) - (get[key](a) ?? -Infinity));
  if (!rows.length || !v) return [el('p', 'muted', 'Prix et vitesse viennent d\'Artificial Analysis : clé non configurée ou aucun modèle reconnu.')];
  // Réglages du verdict
  const set = el('div', 'iac-settings'), prof = el('div', 'seg iac-seg');
  prof.setAttribute('role', 'group'); prof.setAttribute('aria-label', 'Niveau de fiabilité exigé');
  for (const [id, label, gap] of IAC_PROFILES) {
    const b = el('button', 'n0', `${label} (−${gap} pts max)`);
    b.type = 'button'; b.setAttribute('aria-pressed', p.profile === id ? 'true' : 'false');
    b.addEventListener('click', () => { p.profile = id; iacSave(); iacRender(); });
    prof.append(b);
  }
  set.append(prof, iacSelect('Budget max ($/M tokens)', 'iac-budget', IAC_BUDGETS, p.budget, (o) => `${o} $`, (x) => { p.budget = x; }),
    iacSelect('Vitesse min (tokens/s)', 'iac-minspeed', IAC_SPEEDS, p.minSpeed, (o) => `${o}`, (x) => { p.minSpeed = x; }));
  const out = [set];
  const sentence = `Niveau exigé : au plus ${v.gap} points sous le meilleur (${v.ref.name}, ${fmtNum(v.refAvg)}) ; ${fmtNum(iacErr(v.refAvg))} % d'erreurs pour lui.`;
  out.push(el('p', 'muted iac-note', sentence));
  if (!v.pool.size) out.push(el('p', 'iac-warn', 'Aucun modèle ne respecte ce niveau avec ces plafonds : assouplissez le budget, la vitesse ou le profil.'));
  const cards = el('div', 'iac-verdict');
  cards.append(iacVerdictCard('Meilleur choix', v.pick, v, doms, v.pick ? `${fmtUsd(v.pick.price_mix)} /M` : ''),
    iacVerdictCard('Le moins cher', v.cheapest, v, doms, v.cheapest ? `${fmtUsd(v.cheapest.price_mix)} /M` : ''),
    iacVerdictCard('Le plus rapide', v.fastest, v, doms, v.fastest ? `${fmtNum(v.fastest.tps, 0)} tokens/s` : ''));
  out.push(cards);
  for (const [any, chosen, what, val] of [[v.cheapestAny, v.cheapest, 'le moins cher', (m) => `${fmtUsd(m.price_mix)}/M`], [v.fastestAny, v.fastest, 'le plus rapide', (m) => `${fmtNum(m.tps, 0)} tokens/s`]]) {
    if (!any || any.id === chosen?.id || v.pool.has(any.id)) continue;
    const x = iacErrX(iacAvg(any, doms), v.refAvg);
    out.push(el('p', 'iac-warn', `${any.name} est ${what} (${val(any)}) mais fait ${x ? `${fmtNum(x)}× plus d'erreurs` : 'plus d\'erreurs'} que ${v.ref.name} : écarté par ce profil.`));
  }
  // Tableau
  const cols = [['Modèle', '', null], ['Note /100', 'num', 'avg'], ['Erreurs', 'num', null], [`× ${v.ref.name}`, 'num', null]];
  if (p.price) cols.push(['Prix mixte ($/M)', 'num', 'price'], ['Entrée', 'num', null], ['Sortie', 'num', null]);
  cols.push(['Tokens/s', 'num', 'tps']);
  if (p.speed) cols.push(['1er token (s)', 'num', null]);
  cols.push(['Verdict', '', null]);
  const head = el('tr'), body = el('tbody');
  for (const [c, cls, k] of cols) {
    const th = el('th', cls);
    if (k) {
      const b = el('button', 'iac-sort', c + (k === key ? ' ▾' : ''));
      b.type = 'button'; b.title = 'Trier par ce critère';
      b.addEventListener('click', () => { p.sort = k; iacSave(); iacRender(); });
      th.append(b);
    } else th.textContent = c;
    head.append(th);
  }
  for (const m of rows) {
    const avg = iacAvg(m, doms), x = iacErrX(avg, v.refAvg), tr = el('tr'), name = el('th'), tags = el('td');
    name.append(el('span', 'iac-nm', ''));
    name.firstChild.append(brandMark(`${m.name} ${m.lab}`), document.createTextNode(m.name));
    tr.append(name, iacHeat(el('td', 'num', fmtNum(avg)), (avg - (v.refAvg - 25)) / 25),
      iacHeat(el('td', 'num', `${fmtNum(iacErr(avg))} %`), (avg - (v.refAvg - 25)) / 25),
      x === null ? el('td', 'num', '—') : iacHeat(el('td', 'num', `${fmtNum(x)}×`), 1 - (x - 1) / 3));
    if (p.price) {
      tr.append(typeof m.price_mix === 'number' ? iacHeat(el('td', 'num', fmtUsd(m.price_mix)), iacHuePrice(m.price_mix)) : el('td', 'num', '—'), el('td', 'num', fmtUsd(m.price_in)), el('td', 'num', fmtUsd(m.price_out)));
    }
    tr.append(typeof m.tps === 'number' ? iacHeat(el('td', 'num', fmtNum(m.tps, 0)), iacHueSpeed(m.tps)) : el('td', 'num', '—'));
    if (p.speed) tr.append(el('td', 'num', fmtNum(m.ttft, 2)));
    if (m.gen !== 'current') tags.append(el('span', 'badge d-neutral', 'version précédente'));
    else {
      if (m.id === v.pick?.id) tags.append(el('span', 'badge d-ok', 'meilleur choix'));
      if (m.id === v.cheapest?.id) tags.append(el('span', 'badge d-ok', 'moins cher'));
      if (m.id === v.fastest?.id) tags.append(el('span', 'badge n1', 'plus rapide'));
      if (avg < v.floor) tags.append(el('span', 'badge d-bad', 'niveau trop bas'));
    }
    tr.append(tags);
    body.append(tr);
  }
  out.push(iacTable(head, body), el('p', 'muted iac-note', 'Erreurs = 100 − note. Vert = bon, rouge = mauvais (prix : le moins cher est vert). Prix mixte : 3 tokens lus pour 1 écrit, en $ par million de tokens. Cliquer un titre pour trier.'));
  return out;
}
function iacFoot() {
  const foot = $('iac-foot'), parts = [];
  const srcs = el('p', 'iac-src');
  srcs.append(document.createTextNode('Sources : '));
  (iac.data.sources ?? []).forEach((s, i) => {
    if (i) srcs.append(document.createTextNode(' · '));
    const safe = typeof s.url === 'string' && URL.canParse(s.url) && new URL(s.url).protocol === 'https:';
    const a = el(safe ? 'a' : 'span', '', s.name);
    if (safe) { a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    srcs.append(a, document.createTextNode(` (${s.licence}, ${s.fetched ? `relevé ${fmtTime(s.fetched)}` : 'jamais relevé'})`));
  });
  parts.push(srcs);
  if (iac.data.unmatched?.length) parts.push(el('p', 'muted', `Nouveaux modèles bien classés à associer : ${iac.data.unmatched.join(', ')}.`));
  foot.replaceChildren(...parts);
}
function iacRender() {
  if (!iac.data) return;
  iacFilters();
  const view = { rank: iacRank, duel: iacDuel, price: iacPrice }[iac.prefs.view] ?? iacRank;
  $('iac-body').replaceChildren(...view());
  iacFoot();
}
async function loadIacompare() {
  const err = $('iac-error'), state = $('iac-state');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…';
  try {
    await iacLoadPrefs();
    const r = await api('/api/ia-compare');
    if (!r.ok || !r.data || !Array.isArray(r.data.models)) throw new Error('bad');
    if (views.veille.hidden) return; // vue quittée pendant le chargement
    iac.data = r.data;
    if (!r.data.updated) { state.textContent = 'Premier relevé des sources à 6 h (ou au prochain démarrage de Jarvis).'; }
    else state.textContent = `Mis à jour ${fmtTime(r.data.updated)}.`;
    iacRender();
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Comparatif indisponible', e);
  }
}
