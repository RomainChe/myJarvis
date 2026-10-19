'use strict';
// ---- Veille IA : envois hebdo du projet veille-ia (contenu écrit par un agent qui lit le web : texte seul, liens https) ----
const VEILLE = { actus: 'Actus IA', plugins: 'Plugins' };
const SCORE = /\(?\bnote\s*:?\s*(\d{1,3})\)?|\(?(\d{1,3})\s*\/\s*100\)?/i, // « (note 92) » ou « 92/100 »
      SRC = /^sources?\s*:?$/i, WHY = /^pourquoi[^:]{0,30}:\s*/i;
// Pastille d'état en tête de titre (emoji de l'agent de veille) -> icône du thème.
// Logo du sujet de l'article (brands.svg, liste fixe) : le premier motif trouvé dans le titre gagne.
const BRANDS = [[/copilot/i, 'githubcopilot'], [/\bclaude\b/i, 'claude'], [/anthropic/i, 'anthropic'], [/gemini/i, 'googlegemini'],
  [/openai|chatgpt|\bgpt|\bsora\b|\bcodex\b/i, 'openai'], [/salesforce|agentforce/i, 'salesforce'], [/\bmeta\b|\bllama\b/i, 'meta'],
  [/nvidia/i, 'nvidia'], [/hugging ?face/i, 'huggingface'], [/perplexity/i, 'perplexity'], [/ollama/i, 'ollama'],
  [/github/i, 'github'], [/google|deepmind/i, 'google'], [/\bapple\b|\bsiri\b/i, 'apple'], [/\bgrok\b|\bxai\b/i, 'x']];
function brandMark(text) {
  const b = BRANDS.find(([re]) => re.test(text))?.[1];
  const chip = el('span', `brand ${b ? `b-${b}` : 'gen'}`), s = svg('svg', { class: 'i', 'aria-hidden': 'true' });
  s.append(svg('use', { href: b ? `/brands.svg#${b}` : '#i-spark' }));
  chip.append(s);
  return chip;
}
const MARK_RE = /^(\p{Extended_Pictographic})\uFE0F?\s*/u, MARKS = { '✅': ['check', 'ok'], '🔶': ['alert', 'warn'], '⚠': ['alert', 'warn'] };
async function loadVeille() {
  const err = $('veille-error'), state = $('veille-state'), list = $('veille-list');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren();
  try {
    const r = await api('/api/veille');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.veille.hidden) return; // vue quittée pendant le chargement
    if (!r.data.issues.length) { state.textContent = r.data.configured ? 'Aucun envoi reconnu.' : 'Dossier de la veille introuvable.'; return; }
    state.hidden = true;
    list.replaceChildren(...r.data.issues.map((it, i) => {
      const d = el('details', 'panel');
      d.open = i === 0;
      const sum = el('summary', '', `${VEILLE[it.kind] ?? it.kind} · semaine ${it.week} · ${it.year}`);
      if (it.items?.length) sum.append(el('span', 'sum-val', `${it.items.length} article${it.items.length > 1 ? 's' : ''}`));
      d.append(sum);
      const grid = el('div', 'veille-items');
      const safe = (l) => l && typeof l.url === 'string' && URL.canParse(l.url) && new URL(l.url).protocol === 'https:';
      const anchor = (l, cls) => {
        const a = el('a', cls, l.label);
        a.href = l.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        a.append(el('span', 'host', new URL(l.url).hostname), icon('ext')); // destination réelle, pas le champ du serveur
        return a;
      };
      const items = it.items ?? [], used = new Set();
      if (items.length) {
        for (const x of items) {
          const c = el('article', 'veille-item'), head = el('div', 'veille-head');
          let score = null;
          const take = (t) => {
            const m = SCORE.exec(t);
            if (!m || Number(m[1] ?? m[2]) > 100) return t;
            score = Number(m[1] ?? m[2]);
            return t.replace(m[0], '').replace(/^[\s:·|()-]+|[\s:·|(-]+$/g, ''); // garde la « ) » d'une parenthèse fermée
          };
          const title = take(x.lines[0]) || x.lines[0], rest = [];
          for (const t of x.lines.slice(1)) {
            if (safe(x.link) && SRC.test(t)) continue; // « Source » en texte brut : le bouton ci-dessous la remplace
            const r = score === null && t.length <= 24 ? take(t) : t;
            if (r) rest.push(r);
          }
          const h = el('h3', 'veille-title'), mark = MARK_RE.exec(title);
          if (mark && MARKS[mark[1]]) { const i = icon(MARKS[mark[1]][0]); i.classList.add(MARKS[mark[1]][1]); h.append(i); }
          h.append(document.createTextNode(mark ? title.slice(mark[0].length) : title));
          head.append(brandMark(title), h);
          if (score !== null) head.append(el('span', `badge score ${score >= 80 ? 'hi' : score >= 60 ? 'mid' : 'lo'}`, String(score)));
          c.append(head);
          for (const t of rest) {
            const w = WHY.exec(t);
            if (w) {
              const p = el('p', 'veille-why');
              p.append(el('strong', '', 'Pourquoi ça compte'), document.createTextNode(` ${t.slice(w[0].length)}`));
              c.append(p);
            } else c.append(el('p', 'veille-sum', t));
          }
          if (safe(x.link)) { used.add(x.link.url); c.append(anchor(x.link, 'lnk')); }
          grid.append(c);
        }
        d.append(grid);
      } else for (const b of it.blocks) d.append(el('p', 'veille-block', b));
      const links = el('ul', 'plain veille-links');
      for (const l of it.links) {
        if (!safe(l) || used.has(l.url)) continue;
        const li = el('li');
        li.append(anchor(l, 'lnk'));
        links.append(li);
      }
      if (links.children.length) d.append(el('h3', 'veille-src', items.length ? 'Rapport complet' : 'Sources'), links);
      return d;
    }));
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Veille indisponible', e);
  }
}
