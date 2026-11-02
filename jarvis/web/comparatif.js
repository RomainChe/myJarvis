'use strict';
// ---- Comparatif des IA (section de Veille IA) : notes sur 100 par domaine, relevées chaque jour par le Core ----
// Données des sources publiques (Epoch AI, LMArena, Artificial Analysis) : nombres et noms affichés en texte seul.
const IAC_BADGES = { claude_code: 'Claude Code', copilot: 'Copilot' };
const IAC_GAP = 20; // points sous la moyenne du top 5 : au-delà, un modèle est masqué (sauf bon rapport qualité/prix)
const IAC_VIEWS = [['rank', 'Classement'], ['duel', 'Duel'], ['price', 'Prix et vitesse']];
const IAC_OPTS = [['delta', 'Écart de version'], ['price', 'Prix'], ['speed', 'Vitesse'], ['old', 'Anciennes versions'], ['all', 'Tous les modèles']];
const iac = { data: null, prefs: { view: 'rank', off: [], delta: true, price: true, speed: false, old: false, all: false, duel: [] } };

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
// Modèles du classement : notés, version actuelle (sauf « anciennes versions »), triés ; ceux trop loin du top 5
// sont masqués, sauf s'ils sont dans les 3 meilleurs rapports qualité/prix (ou « tous les modèles »).
function iacRanked(models, doms, opts) {
  const scored = models.map((m) => ({ m, avg: iacAvg(m, doms) })).filter((x) => x.avg !== null)
    .filter((x) => opts.old || x.m.gen === 'current').sort((a, b) => b.avg - a.avg);
  const top = scored.filter((x) => x.m.gen === 'current').slice(0, 5);
  const floor = top.length ? top.reduce((s, x) => s + x.avg, 0) / top.length - IAC_GAP : -Infinity;
  const value = iacValue(models.filter((m) => opts.old || m.gen === 'current'), doms);
  const bestValue = new Set([...value].sort((a, b) => b[1] - a[1]).slice(0, 3).map(([id]) => id));
  const hidden = scored.filter((x) => x.avg < floor && !bestValue.has(x.m.id)).length;
  return { rows: opts.all ? scored : scored.filter((x) => x.avg >= floor || bestValue.has(x.m.id)), hidden, value, bestValue };
}
// Domaines notés pour tous les modèles du duel ; 3 modèles seulement s'ils en partagent au moins deux.
function iacDuelDomains(models, doms) {
  return doms.filter((d) => models.every((m) => typeof m.scores?.[d]?.score === 'number'));
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

function iacMeter(label, d, cls = '') {
  const li = el('li', cls), head = el('div', 'meter-head');
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
function iacRank() {
  const doms = iacDoms(), byId = new Map(iac.data.models.map((m) => [m.id, m]));
  const { rows, hidden, value, bestValue } = iacRanked(iac.data.models, doms, iac.prefs);
  const list = el('ol', 'plain iac-list');
  rows.forEach(({ m, avg }, i) => {
    const li = el('li'), d = el('details', 'iac-item'), sum = el('summary', 'iac-row');
    const name = el('div', 'iac-name'), tags = el('div', 'iac-tags');
    name.append(el('span', 'iac-pos', String(i + 1)), brandMark(`${m.name} ${m.lab}`), el('strong', '', m.name));
    if (m.gen !== 'current') tags.append(el('span', 'badge d-neutral', 'version précédente'));
    for (const b of m.badges ?? []) if (IAC_BADGES[b]) tags.append(el('span', 'badge n1', IAC_BADGES[b]));
    if (bestValue.has(m.id)) tags.append(el('span', 'badge d-ok', 'bon rapport qualité/prix'));
    sum.append(name, tags, el('span', `badge score ${avg >= 80 ? 'hi' : avg >= 60 ? 'mid' : 'lo'}`, fmtNum(avg)));
    d.append(sum);
    const meters = el('ul', 'meters iac-meters');
    for (const dm of iac.data.domains.filter((x) => doms.includes(x.id))) meters.append(iacMeter(dm.label, m.scores?.[dm.id]));
    d.append(meters);
    const facts = [];
    if (iac.prefs.delta && m.prev && byId.get(m.prev)) {
      const ds = doms.filter((x) => typeof m.delta?.[x] === 'number').map((x) => {
        const v = m.delta[x], lab = iac.data.domains.find((y) => y.id === x)?.label ?? x;
        return `${lab} ${v > 0 ? '+' : ''}${fmtNum(v)}`;
      });
      if (ds.length) facts.push(`vs ${byId.get(m.prev).name} : ${ds.join(' · ')}`);
    }
    if (iac.prefs.price && typeof m.price_mix === 'number') facts.push(`${fmtUsd(m.price_mix)} / M tokens · qualité/prix ${value.get(m.id) ?? '—'}`);
    if (iac.prefs.speed && typeof m.tps === 'number') facts.push(`${fmtNum(m.tps, 0)} tokens/s`);
    for (const f of facts) d.append(el('p', 'iac-fact muted', f));
    const more = el('details', 'iac-more');
    more.append(el('summary', '', 'Détail par test'), iacDetail(m, doms));
    d.append(more);
    li.append(d);
    list.append(li);
  });
  const out = [list];
  if (!rows.length) out.unshift(el('p', 'muted', 'Aucune note pour ces domaines.'));
  if (hidden && !iac.prefs.all) out.push(el('p', 'muted iac-note', `${hidden} modèle${hidden > 1 ? 's' : ''} masqué${hidden > 1 ? 's' : ''} : à plus de ${IAC_GAP} points du top 5, sans bon rapport qualité/prix.`));
  return out;
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
      const next = [...pick]; next[i] = sel.value;
      iac.prefs.duel = next.filter(Boolean).slice(0, 3); iacSave(); iacRender();
    });
    form.append(lab);
  }
  let chosen = pick.map((id) => scored.find((m) => m.id === id)).filter(Boolean);
  const out = [form];
  if (chosen.length === 3 && iacDuelDomains(chosen, doms).length < 2) {
    out.push(el('p', 'muted iac-note', 'Le 3e modèle n\'a pas assez de domaines notés en commun : duel à deux.'));
    chosen = chosen.slice(0, 2);
  }
  const common = iacDuelDomains(chosen, doms);
  if (!common.length) { out.push(el('p', 'muted', 'Aucun domaine noté en commun.')); return out; }
  for (const d of iac.data.domains.filter((x) => common.includes(x.id))) {
    const p = el('section', 'iac-duel-dom'), best = Math.max(...chosen.map((m) => m.scores[d.id].score));
    p.append(el('h3', '', d.label));
    const ul = el('ul', 'meters');
    for (const m of chosen) ul.append(iacMeter(m.name, m.scores[d.id], m.scores[d.id].score === best ? 'win' : ''));
    p.append(ul);
    out.push(p);
  }
  return out;
}
function iacPrice() {
  const doms = iacDoms(), models = iac.data.models.filter((m) => iac.prefs.old || m.gen === 'current');
  const value = iacValue(models, doms);
  const rows = models.filter((m) => typeof m.price_mix === 'number' || typeof m.tps === 'number')
    .sort((a, b) => (value.get(b.id) ?? -1) - (value.get(a.id) ?? -1));
  if (!rows.length) return [el('p', 'muted', 'Prix et vitesse viennent d\'Artificial Analysis : clé non configurée ou aucun modèle reconnu.')];
  const wrap = el('div', 'iac-table-wrap'), t = el('table', 'iac-table'), head = el('tr');
  const cols = [['Modèle', ''], ['Qualité/prix', 'num']];
  if (iac.prefs.price) cols.push(['Prix mixte ($/M)', 'num'], ['Entrée', 'num'], ['Sortie', 'num']);
  if (iac.prefs.speed) cols.push(['Tokens/s', 'num'], ['1er token (s)', 'num']);
  for (const [c, cls] of cols) head.append(el('th', cls, c));
  const thead = el('thead'), body = el('tbody');
  thead.append(head);
  for (const m of rows) {
    const tr = el('tr'), cells = [m.name, value.has(m.id) ? String(value.get(m.id)) : '—'];
    if (iac.prefs.price) cells.push(fmtUsd(m.price_mix), fmtUsd(m.price_in), fmtUsd(m.price_out));
    if (iac.prefs.speed) cells.push(fmtNum(m.tps, 0), fmtNum(m.ttft, 2));
    cells.forEach((c, i) => tr.append(el(i ? 'td' : 'th', i ? 'num' : '', c)));
    body.append(tr);
  }
  t.append(thead, body);
  wrap.append(t);
  return [wrap, el('p', 'muted iac-note', 'Prix mixte : 3 tokens lus pour 1 écrit. Qualité/prix : moyenne des domaines cochés ÷ prix mixte, meilleur = 100.')];
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
