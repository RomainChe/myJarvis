'use strict';
// ---- Comparatif des IA (section de Veille IA) : notes sur 100 par domaine, relevées chaque jour par le Core ----
// Données des sources publiques (Epoch AI, LMArena, Artificial Analysis) : nombres et noms affichés en texte seul.
const IAC_BADGES = { claude_code: 'Claude Code', copilot: 'Copilot' };
const IAC_GAP = 20; // points sous la moyenne du top 5 : au-delà, un modèle est masqué (sauf bon rapport qualité/prix)
const IAC_VIEWS = [['rank', 'Classement'], ['duel', 'Duel'], ['price', 'Prix et vitesse']];
const IAC_OPTS = [['delta', 'Écart de version'], ['price', 'Prix'], ['speed', 'Vitesse'], ['old', 'Anciennes versions'], ['all', 'Tous les modèles']];
const iac = { data: null, prefs: { view: 'rank', off: [], delta: true, price: true, speed: false, old: false, all: false, duel: [], sort: 'avg' } };
const IAC_SORTS = ['avg', 'value', 'price', 'tps'];

// Moyenne des domaines cochés disponibles pour ce modèle (null s'il n'en a aucun).
function iacAvg(m, doms) {
  const v = doms.map((d) => m.scores?.[d]?.score).filter((x) => typeof x === 'number');
  return v.length ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 10) / 10 : null;
}
// Rapport qualité/prix ramené sur 100 (meilleur = 100) : moyenne des domaines cochés ÷ prix mixte par million de tokens.
function iacValue(models, doms) {
  const raw = new Map();
  for (const m of models) {
    const a = iacAvg(m, doms);
    if (a !== null && m.price_mix > 0) raw.set(m.id, a / m.price_mix);
  }
  const best = Math.max(0, ...raw.values());
  return new Map([...raw].map(([id, v]) => [id, best ? Math.round((v / best) * 100) : 0]));
}
// Nombre de tests derrière la note (sert à départager deux notes égales : plus de tests = note plus solide).
const iacTests = (m, doms) => doms.reduce((n, d) => n + (m.scores?.[d]?.n ?? 0), 0);
// Modèles du classement : notés, version actuelle (sauf « anciennes versions »), triés ; ceux trop loin du top 5
// sont masqués, sauf s'ils sont dans les 3 meilleurs rapports qualité/prix (ou « tous les modèles »).
// Une version précédente plus forte que sa version suivante (sur leurs domaines communs) et du niveau du top 5 n'est pas « ancienne » : elle reste visible (`beats` = la suivante).
function iacRanked(models, doms, opts) {
  const avgOf = new Map(models.map((m) => [m.id, iacAvg(m, doms)]));
  const next = new Map(models.filter((m) => m.prev).map((m) => [m.prev, m]));
  // Comparaison équitable : seulement sur les domaines notés pour les deux modèles (au moins 2).
  const beats = (m) => {
    const n = next.get(m.id), common = n ? doms.filter((d) => m.scores?.[d] && n.scores?.[d]) : [];
    const mean = (x) => common.reduce((t, d) => t + x.scores[d].score, 0) / common.length;
    return common.length >= 2 && mean(m) > mean(n) ? n : null;
  };
  const all = models.map((m) => ({ m, avg: avgOf.get(m.id), n: iacTests(m, doms), beats: m.gen === 'current' ? null : beats(m) })).filter((x) => x.avg !== null);
  const top = all.filter((x) => x.m.gen === 'current').sort((a, b) => b.avg - a.avg).slice(0, 5);
  const inTop = (x) => top.length < 5 || x.avg >= top[4].avg; // une ancienne version n'est visible que si elle entrerait dans le top 5
  const scored = all.filter((x) => opts.old || x.m.gen === 'current' || (x.beats && inTop(x)))
    .sort((a, b) => b.avg - a.avg || b.n - a.n || a.m.name.localeCompare(b.m.name));
  const floor = top.length ? top.reduce((s, x) => s + x.avg, 0) / top.length - IAC_GAP : -Infinity;
  const value = iacValue(models.filter((m) => opts.old || m.gen === 'current' || beats(m)), doms);
  const bestValue = new Set([...value].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([id]) => id));
  const hidden = scored.filter((x) => x.avg < floor && !bestValue.has(x.m.id)).length;
  return { rows: opts.all ? scored : scored.filter((x) => x.avg >= floor || bestValue.has(x.m.id)), hidden, value, bestValue };
}

const iacDoms = () => (iac.data?.domains ?? []).map((d) => d.id).filter((d) => !iac.prefs.off.includes(d));
const fmtNum = (v, n = 1) => (typeof v === 'number' ? v.toLocaleString('fr-FR', { maximumFractionDigits: n }) : '—');
const fmtUsd = (v) => (typeof v === 'number' ? `${v.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} $` : '—');
function iacSave() { kv('readwrite', (s) => s.put(JSON.stringify(iac.prefs), 'iacompare')).catch(() => {}); }
async function iacLoadPrefs() {
  try {
    const p = JSON.parse(await kv('readonly', (s) => s.get('iacompare')) || '{}');
    if (p && typeof p === 'object') {
      for (const k of ['delta', 'price', 'speed', 'old', 'all']) if (typeof p[k] === 'boolean') iac.prefs[k] = p[k];
      if (IAC_VIEWS.some(([v]) => v === p.view)) iac.prefs.view = p.view;
      if (IAC_SORTS.includes(p.sort)) iac.prefs.sort = p.sort;
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
    const on = !iac.prefs.off.includes(d.id);
    doms.append(iacToggle(d.label, on, () => {
      iac.prefs.off = on ? [...iac.prefs.off, d.id] : iac.prefs.off.filter((x) => x !== d.id);
      if (!iacDoms().length) iac.prefs.off = iac.prefs.off.filter((x) => x !== d.id); // au moins un domaine
      iacSave(); iacRender();
    }, 'dom'));
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
const iacSpeed = (m) => (typeof m.tps === 'number' ? `${fmtNum(m.tps, 0)} tokens/s` : null);
function iacRank() {
  const doms = iacDoms(), byId = new Map(iac.data.models.map((m) => [m.id, m]));
  const { rows, hidden, value, bestValue } = iacRanked(iac.data.models, doms, iac.prefs);
  const list = el('ol', 'plain iac-list');
  let pos = 0, last = null;
  rows.forEach(({ m, avg, n, beats }, i) => {
    if (avg !== last) pos = i + 1; // ex æquo : même rang
    last = avg;
    const li = el('li'), d = el('details', 'iac-item'), sum = el('summary', 'iac-row');
    const name = el('div', 'iac-name'), tags = el('div', 'iac-tags');
    name.append(el('span', 'iac-pos', String(pos)), brandMark(`${m.name} ${m.lab}`), el('strong', '', m.name));
    if (beats) tags.append(el('span', 'badge d-ok', `plus fort que ${beats.name}`));
    else if (m.gen !== 'current') tags.append(el('span', 'badge d-neutral', 'version précédente'));
    for (const b of m.badges ?? []) if (IAC_BADGES[b]) tags.append(el('span', 'badge n1', IAC_BADGES[b]));
    if (bestValue.has(m.id)) tags.append(el('span', 'badge d-ok', 'bon rapport qualité/prix'));
    const sub = iac.data.domains.filter((x) => doms.includes(x.id) && m.scores?.[x.id])
      .map((x) => `${x.label} ${fmtNum(m.scores[x.id].score, 0)}`).join(' · ');
    const brief = [typeof m.price_mix === 'number' ? `${fmtUsd(m.price_mix)}/M` : null, iacSpeed(m)].filter(Boolean).join(' · ');
    sum.append(name, tags, el('span', `badge score ${avg >= 80 ? 'hi' : avg >= 60 ? 'mid' : 'lo'}`, fmtNum(avg)),
      el('div', 'iac-sub muted', [sub, `${n} test${n > 1 ? 's' : ''}`, brief].filter(Boolean).join(' · ')));
    d.append(sum);
    const meters = el('ul', 'meters iac-meters');
    for (const dm of iac.data.domains.filter((x) => doms.includes(x.id))) meters.append(iacMeter(dm.label, m.scores?.[dm.id]));
    d.append(meters);
    const facts = [];
    if (iac.prefs.delta && m.prev && byId.get(m.prev)) {
      const ds = doms.filter((x) => typeof m.delta?.[x] === 'number').map((x) => `${iacDomLabel(x)} ${m.delta[x] > 0 ? '+' : ''}${fmtNum(m.delta[x])}`);
      if (ds.length) facts.push(`vs ${byId.get(m.prev).name} : ${ds.join(' · ')}`);
    }
    if (iac.prefs.price && typeof m.price_mix === 'number') facts.push(`${fmtUsd(m.price_mix)} / M tokens · qualité/prix ${value.get(m.id) ?? '—'}`);
    if (iac.prefs.speed && iacSpeed(m)) facts.push(iacSpeed(m));
    for (const f of facts) d.append(el('p', 'iac-fact muted', f));
    const more = el('details', 'iac-more');
    more.append(el('summary', '', 'Détail par test'), iacDetail(m, doms));
    d.append(more);
    li.append(d);
    list.append(li);
  });
  const out = [el('p', 'muted iac-note', 'Note sur 100 = moyenne des domaines cochés ; chaque domaine = moyenne de tests publics (SWE-bench, GPQA, ARC-AGI…). Sous chaque nom : la note par domaine, le nombre de tests, le prix et la vitesse. Deux notes égales sont départagées par le nombre de tests. Ouvrir une ligne pour le détail.'), list];
  if (!rows.length) out.splice(1, 0, el('p', 'muted', 'Aucune note pour ces domaines.'));
  if (hidden && !iac.prefs.all) out.push(el('p', 'muted iac-note', `${hidden} modèle${hidden > 1 ? 's' : ''} masqué${hidden > 1 ? 's' : ''} : à plus de ${IAC_GAP} points du top 5, sans bon rapport qualité/prix.`));
  return out;
}

// ---- Duel : graphique à barres multiples (une couleur par modèle) ----
// groups : [{ title, note?, rows: [{ label, vals: [nombre|null par modèle], texts, max, low? }] }] ; low = plus petit est meilleur (prix).
function iacChart(groups, models) {
  const root = el('div', 'iac-chart'), legend = el('ul', 'plain iac-legend');
  models.forEach((m, i) => { const li = el('li'); li.append(el('i', `iac-sw s${i}`), el('span', '', m.name)); legend.append(li); });
  root.append(legend);
  for (const g of groups) {
    const sec = el('section', 'iac-chart-group');
    sec.append(el('h3', '', g.title));
    for (const r of g.rows) {
      const row = el('div', 'iac-bar-row'), known = r.vals.filter((v) => typeof v === 'number');
      const best = known.length > 1 ? (r.low ? Math.min(...known) : Math.max(...known)) : null;
      row.append(el('span', 'iac-bar-label', r.label));
      r.vals.forEach((v, i) => {
        const bar = el('div', `iac-bar s${i}`), track = el('span', 'track'), fill = el('i'), val = el('b', v === best ? 'win' : '', r.texts[i]);
        fill.style.width = `${typeof v === 'number' && r.max ? Math.max(2, Math.min(100, (v / r.max) * 100)) : 0}%`;
        track.append(fill);
        bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', `${models[i].name} : ${r.texts[i]}`);
        bar.append(track, val);
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
    lab.append(el('span', 'muted', i < 2 ? `Modèle ${i + 1}` : 'Modèle 3 (facultatif)'), sel);
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
  const value = iacValue(iac.data.models, doms), num = (k) => chosen.map((m) => (typeof m[k] === 'number' ? m[k] : null));
  const eff = [];
  const addEff = (label, vals, texts, low = false) => {
    if (vals.filter((v) => v !== null).length >= 2) eff.push({ label, vals, texts, low, max: Math.max(...vals.filter((v) => v !== null)) });
  };
  addEff('Qualité/prix (100 = meilleur)', chosen.map((m) => value.get(m.id) ?? null), chosen.map((m) => String(value.get(m.id) ?? '—')));
  addEff('Vitesse (tokens/s)', num('tps'), chosen.map((m) => fmtNum(m.tps, 0)));
  addEff('Prix mixte ($/M tokens, barre courte = moins cher)', num('price_mix'), chosen.map((m) => fmtUsd(m.price_mix)), true);
  if (eff.length) groups.push({ title: 'Efficacité : coût et vitesse', rows: eff, note: 'Prix mixte : 3 tokens lus pour 1 écrit. Qualité/prix mesure l\'économie, pas le niveau : un modèle cher mais très fiable y a un petit score.' });
  if (!groups.length) { out.push(el('p', 'muted', 'Aucun domaine noté en commun pour ces modèles.')); return out; }
  // Bilan : domaines gagnés par chaque modèle (égalité = personne).
  const wins = chosen.map(() => 0);
  for (const d of comparable) {
    const v = chosen.map((m) => sc(m, d.id) ?? -1), top = Math.max(...v);
    v.forEach((x, i) => { if (x === top && v.filter((y) => y === top).length === 1) wins[i] += 1; });
  }
  if (comparable.length) out.push(el('p', 'iac-wins', `Domaines gagnés (sur ${comparable.length}) : ${chosen.map((m, i) => `${m.name} ${wins[i]}`).join(' · ')}`));
  out.push(iacChart(groups, chosen));
  // Détail test par test : une ligne par test, une colonne par modèle.
  const tests = new Map();
  for (const d of comparable) chosen.forEach((m, i) => (m.scores[d.id]?.detail ?? []).forEach((t) => {
    const k = `${d.label} · ${t.test}`;
    if (!tests.has(k)) tests.set(k, chosen.map(() => null));
    tests.get(k)[i] = t.score;
  }));
  if (tests.size) {
    const more = el('details', 'iac-more'), wrap = el('div', 'iac-table-wrap'), t = el('table', 'iac-table'), hr = el('tr'), body = el('tbody');
    hr.append(el('th', '', 'Test'), ...chosen.map((m) => el('th', 'num', m.name)));
    for (const [k, vals] of tests) {
      const tr = el('tr'), known = vals.filter((v) => v !== null), best = Math.max(...known);
      tr.append(el('th', '', k), ...vals.map((v) => el('td', `num${v === best && known.length > 1 ? ' win' : ''}`, fmtNum(v))));
      body.append(tr);
    }
    const thead = el('thead'); thead.append(hr);
    t.append(thead, body); wrap.append(t);
    more.append(el('summary', '', 'Détail par test'), wrap);
    out.push(more);
  }
  return out;
}
function iacPrice() {
  const doms = iacDoms(), models = iac.data.models.filter((m) => iac.prefs.old || m.gen === 'current');
  const value = iacValue(models, doms), key = iac.prefs.sort;
  const get = { avg: (m) => iacAvg(m, doms), value: (m) => value.get(m.id), price: (m) => (typeof m.price_mix === 'number' ? -m.price_mix : null), tps: (m) => m.tps };
  const rows = models.filter((m) => typeof m.price_mix === 'number' || typeof m.tps === 'number')
    .sort((a, b) => (get[key](b) ?? -Infinity) - (get[key](a) ?? -Infinity));
  if (!rows.length) return [el('p', 'muted', 'Prix et vitesse viennent d\'Artificial Analysis : clé non configurée ou aucun modèle reconnu.')];
  const wrap = el('div', 'iac-table-wrap'), t = el('table', 'iac-table'), head = el('tr');
  const cols = [['Modèle', '', null], ['Note /100', 'num', 'avg'], ['Qualité/prix', 'num', 'value']];
  if (iac.prefs.price) cols.push(['Prix mixte ($/M)', 'num', 'price'], ['Entrée', 'num', null], ['Sortie', 'num', null]);
  cols.push(['Tokens/s', 'num', 'tps']);
  if (iac.prefs.speed) cols.push(['1er token (s)', 'num', null]);
  for (const [c, cls, k] of cols) {
    const th = el('th', cls);
    if (k) {
      const b = el('button', 'iac-sort', c + (k === key ? ' ▾' : ''));
      b.type = 'button'; b.title = 'Trier par ce critère';
      b.addEventListener('click', () => { iac.prefs.sort = k; iacSave(); iacRender(); });
      th.append(b);
    } else th.textContent = c;
    head.append(th);
  }
  const thead = el('thead'), body = el('tbody');
  thead.append(head);
  for (const m of rows) {
    const tr = el('tr'), cells = [m.name, fmtNum(iacAvg(m, doms)), value.has(m.id) ? String(value.get(m.id)) : '—'];
    if (iac.prefs.price) cells.push(fmtUsd(m.price_mix), fmtUsd(m.price_in), fmtUsd(m.price_out));
    cells.push(fmtNum(m.tps, 0));
    if (iac.prefs.speed) cells.push(fmtNum(m.ttft, 2));
    cells.forEach((c, i) => tr.append(el(i ? 'td' : 'th', i ? 'num' : '', c)));
    body.append(tr);
  }
  t.append(thead, body);
  wrap.append(t);
  return [el('p', 'muted iac-note', 'Lire ainsi : « Note » = le niveau du modèle (moins d\'erreurs) ; « Qualité/prix » = l\'économie (100 = meilleur rapport : moyenne des domaines cochés ÷ prix mixte). Un modèle cher et très fiable a une grosse note mais un petit score qualité/prix : choisir selon le besoin. Cliquer un titre pour trier.'), wrap,
    el('p', 'muted iac-note', 'Prix mixte : 3 tokens lus pour 1 écrit, en $ par million de tokens.')];
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
