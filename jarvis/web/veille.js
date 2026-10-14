'use strict';
// ---- Veille IA : envois hebdo du projet veille-ia (contenu écrit par un agent qui lit le web : texte seul, liens https) ----
const VEILLE = { actus: 'Actus IA', plugins: 'Plugins' };
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
      const d = el('details', 'panel hud');
      d.open = i === 0;
      d.append(el('summary', '', `${VEILLE[it.kind] ?? it.kind} · semaine ${it.week} · ${it.year}`));
      const safe = (l) => l && typeof l.url === 'string' && URL.canParse(l.url) && new URL(l.url).protocol === 'https:';
      const anchor = (l) => {
        const a = el('a', '', l.label);
        a.href = l.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
        return [a, el('span', 'muted', ` · ${new URL(l.url).hostname}`)]; // destination réelle, pas le champ du serveur
      };
      const items = it.items ?? [], used = new Set();
      if (items.length) {
        for (const x of items) {
          const c = el('article', 'veille-item');
          c.append(el('h3', 'veille-title', x.lines[0]));
          for (const t of x.lines.slice(1)) c.append(el('p', 'veille-block', t));
          if (safe(x.link)) { used.add(x.link.url); c.append(el('p', 'veille-block', '')); c.lastChild.append(...anchor(x.link)); }
          d.append(c);
        }
      } else for (const b of it.blocks) d.append(el('p', 'veille-block', b));
      const links = el('ul', 'plain veille-links');
      for (const l of it.links) {
        if (!safe(l) || used.has(l.url)) continue;
        const li = el('li');
        li.append(...anchor(l));
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
