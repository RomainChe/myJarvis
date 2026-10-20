'use strict';
// Navigation télécommande dans les sites de SiteActivity (Bowd, OpenFlix), faits pour la souris :
// les flèches vont à l'élément cliquable le plus proche dans leur direction, OK le clique.
// Injecté par SiteActivity (page principale seulement : les lecteurs en iframe passent par le pointeur Java).
// pick() est sans DOM, testé par tests/tv_sitenav.test.js.

const SiteNav = {
  DIRS: { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' },

  // Indice du rectangle {left, top, right, bottom} le plus proche de cur dans la direction dir, ou -1.
  // Distance le long de la direction + 2 × décalage en travers : on préfère l'élément aligné au plus proche en diagonale.
  pick(cur, rects, dir) {
    const h = dir === 'left' || dir === 'right';
    const sign = dir === 'left' || dir === 'up' ? -1 : 1;
    const [a0, a1, b0, b1] = h ? ['left', 'right', 'top', 'bottom'] : ['top', 'bottom', 'left', 'right'];
    const mid = (r, k0, k1) => (r[k0] + r[k1]) / 2;
    let best = -1;
    let bestScore = Infinity;
    rects.forEach((r, i) => {
      if (sign * (mid(r, a0, a1) - mid(cur, a0, a1)) <= 0) return;
      const gap = sign > 0 ? r[a0] - cur[a1] : cur[a0] - r[a1];
      const score = Math.max(0, gap) + 2 * Math.abs(mid(r, b0, b1) - mid(cur, b0, b1));
      if (score < bestScore) { bestScore = score; best = i; }
    });
    return best;
  },
};

if (typeof module === 'object') module.exports = SiteNav;

if (typeof window === 'object' && !window.__jarvisNav) {
  window.__jarvisNav = true;
  const SEL = 'a[href],button,input,select,textarea,video,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[onclick],'
    + '[tabindex]:not([tabindex="-1"])';
  const style = document.createElement('style');
  style.textContent = '.__jarvis-focus{outline:4px solid #4da3ff!important;outline-offset:2px!important;border-radius:6px}';
  document.documentElement.appendChild(style);
  let cur = null;

  const typing = (e) => !!e && (e.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName));

  // Cibles : éléments interactifs, plus le plus haut d'une zone « cursor: pointer » (div cliquables des sites React).
  // ponytail: getComputedStyle sur toute la page à chaque appui ; cache invalidé par MutationObserver si la TV rame
  const targets = () => {
    const out = [];
    for (const e of document.body.querySelectorAll('*')) {
      const s = getComputedStyle(e);
      if (s.visibility === 'hidden' || e.disabled) continue;
      const pointer = s.cursor === 'pointer' && getComputedStyle(e.parentElement).cursor !== 'pointer';
      if (!pointer && !e.matches(SEL)) continue;
      const r = e.getBoundingClientRect();
      if (r.width > 4 && r.height > 4) out.push([e, r]);
    }
    return out;
  };

  const select = (e) => {
    if (cur) cur.classList.remove('__jarvis-focus');
    cur = e;
    e.classList.add('__jarvis-focus');
    if (document.activeElement !== e && typing(document.activeElement)) document.activeElement.blur();
    e.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
  };

  addEventListener('keydown', (ev) => {
    if (cur && !cur.isConnected) cur = null;
    const dir = SiteNav.DIRS[ev.key];
    if (dir) {
      if (document.fullscreenElement) return; // lecteur plein écran : les flèches sont à lui
      if (typing(document.activeElement) && (dir === 'left' || dir === 'right')) return; // curseur dans le texte
      const list = targets();
      let i;
      if (cur) i = SiteNav.pick(cur.getBoundingClientRect(), list.map((t) => t[1]), dir);
      else i = list.findIndex((t) => t[1].top >= 0 && t[1].bottom <= innerHeight); // premier appui : premier élément visible
      if (i < 0) return; // rien dans cette direction : défilement normal de la page
      ev.preventDefault();
      ev.stopImmediatePropagation();
      select(list[i][0]);
    } else if (ev.key === 'Enter' && cur) {
      if (typing(cur)) {
        // OK sur un champ : on y entre (clavier de la TV ou du téléphone) ; déjà dedans, Entrée valide le formulaire.
        if (document.activeElement !== cur) { ev.preventDefault(); cur.focus(); }
        return;
      }
      ev.preventDefault();
      ev.stopImmediatePropagation();
      cur.click();
    }
  }, true);
}
