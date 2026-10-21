'use strict';
// Navigation télécommande dans les sites ouverts par SiteActivity (Bowd, OpenFlix), injectée par SiteActivity.
// Les flèches passent à l'élément cliquable voisin (jamais de défilement libre), OK clique, et le focus reste
// dans la couche du dessus (popup, lecteur) : l'arrière-plan n'est plus atteignable. Testée par tests/tv_sitenav.test.js.
// En secours, appui long sur OK = pointeur (SiteActivity).

const SiteNav = {
  /** Index du rectangle {x, y, w, h} le plus proche de from dans la direction dir, ou -1. */
  pick(rects, from, dir) {
    const h = dir === 'left' || dir === 'right', s = dir === 'right' || dir === 'down' ? 1 : -1;
    const span = (r, horiz) => (horiz ? [r.x, r.x + r.w] : [r.y, r.y + r.h]);
    const [f0, f1] = span(from, h), [g0, g1] = span(from, !h);
    let best = -1, score = Infinity;
    rects.forEach((r, i) => {
      const [a0, a1] = span(r, h), [b0, b1] = span(r, !h);
      const ahead = s * (a0 + a1 - f0 - f1) / 2; // avance du centre dans la direction
      const gap = s > 0 ? a0 - f1 : f0 - a1; // écart entre bords en regard (négatif s'ils se chevauchent)
      if (ahead < 1 || gap < -Math.min(a1 - a0, f1 - f0) / 2) return;
      const side = Math.max(0, b0 - g1, g0 - b1); // décalage sur l'autre axe, nul si les deux se font face
      if (h && side > 0) return; // ←/→ restent dans la rangée, jamais en diagonale
      const sc = Math.max(0, gap) + 2 * side + Math.abs(b0 + b1 - g0 - g1) / 20;
      if (sc < score) { score = sc; best = i; }
    });
    return best;
  },
};

if (typeof module === 'object') module.exports = SiteNav;
else if (!window.__jarvisNav) {
  const DIRS = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
  const SEL = 'a[href],button,input,select,textarea,[tabindex],[role=button],[role=link],[role=tab],[role=option],[onclick]';
  // Contenus d'un autre domaine (case Cloudflare d'OpenFlix, lecteur intégré) : le script ne peut pas y cliquer,
  // SiteActivity y fait un vrai tap (tap()).
  const EMBED = 'iframe,#turnstile-widget,.cf-turnstile';
  // Champ de saisie : le focus ouvre le clavier de la TV, qui capte alors les flèches. Il ne le reçoit que sur OK.
  const TEXT = 'input:not([type=button]):not([type=checkbox]):not([type=radio]):not([type=submit]),textarea,[contenteditable=""],[contenteditable=true]';
  const GROUP = '[role=menu],[role=menubar],[role=listbox],[role=tablist],[role=radiogroup],[role=toolbar],[role=grid]';
  const style = document.createElement('style');
  style.textContent = '[data-jarvis-focus]{scale:1.05;transition:scale .15s}'
    + '#jarvis-ring{position:fixed;z-index:2147483647;pointer-events:none;border:4px solid #fff;border-radius:10px;'
    + 'box-shadow:0 0 0 3px rgba(0,0,0,.7),0 0 28px rgba(255,255,255,.55);transition:all .12s;display:none}';
  document.head.appendChild(style);
  // Anneau de focus posé au-dessus de tout : un contour sur l'élément serait masqué par ses enfants (cartes d'OpenFlix).
  const ring = document.createElement('div');
  ring.id = 'jarvis-ring';
  document.body.appendChild(ring);
  let cur = null, curPage = '', inPage = false, last = null; // last : position du focus à l'image précédente
  const memo = new Map(); // dernière position du focus par page (hors popup), reprise au retour sur la page

  const rect = (e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };
  const shown = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    // Écrans précédents de Bowd (React Navigation) : restés dans le DOM sous l'écran courant, marqués aria-hidden.
    if (e.closest('[aria-hidden="true"],[inert]')) return false;
    return e.checkVisibility ? e.checkVisibility({ opacityProperty: true, visibilityProperty: true }) : getComputedStyle(e).visibility !== 'hidden';
  };

  (function follow() {
    const on = cur && cur.isConnected && shown(cur);
    ring.style.display = on ? 'block' : 'none';
    if (on) {
      const r = rect(cur);
      last = r;
      if (inPage) memo.set(location.href, r);
      Object.assign(ring.style, { left: r.x - 4 + 'px', top: r.y - 4 + 'px', width: r.w + 8 + 'px', height: r.h + 8 + 'px' });
    }
    requestAnimationFrame(follow);
  })();

  // Couche du dessus : boîte de dialogue déclarée, sinon le plus proche ancêtre de l'élément au centre qui flotte
  // (fixed, ou absolute avec un z-index : popup de Bowd) et couvre 40 % de l'écran (fond d'une popup, lecteur), sinon la page.
  function layer() {
    const modal = [...document.querySelectorAll('[aria-modal="true"],[role="dialog"]')].filter(shown).pop();
    if (modal) return modal;
    for (let n = document.elementFromPoint(innerWidth / 2, innerHeight / 2); n && n !== document.body; n = n.parentElement) {
      const r = n.getBoundingClientRect();
      const cs = getComputedStyle(n);
      const floats = cs.position === 'fixed' || (cs.position === 'absolute' && parseInt(cs.zIndex, 10) > 0);
      if (floats && r.width * r.height >= innerWidth * innerHeight * 0.4) return n;
    }
    return document.body;
  }

  // Cliquables de la couche : éléments focusables, ou au curseur « main » (cartes en <div> d'OpenFlix), sans doublon
  // emboîté de même taille (<a><button> d'OpenFlix), sans fond plein écran.
  function candidates(scope) {
    const out = [], ptr = new Map();
    for (const e of scope.querySelectorAll('*')) {
      const cs = getComputedStyle(e), p = cs.cursor === 'pointer';
      ptr.set(e, p);
      const focusable = (e.matches(SEL) && e.getAttribute('tabindex') !== '-1' && !e.disabled) || e.matches(EMBED);
      if (!focusable && !(p && !ptr.get(e.parentElement))) continue;
      if (cs.pointerEvents === 'none') continue; // menu replié d'OpenFlix : présent mais inerte
      if (e.matches(GROUP)) continue; // menu du profil Bowd : le focus va à ses éléments, pas au cadre
      if (!shown(e)) continue;
      const box = e.getBoundingClientRect();
      if (e.tagName === 'IFRAME' ? box.width < innerWidth / 2 // bannière de pub ; un lecteur est large
        : !e.matches(EMBED) && box.width * box.height > innerWidth * innerHeight * 0.6) continue; // fond cliquable d'une popup (« Fermer » de Bowd)
      const outer = out.length && out[out.length - 1];
      if (outer && outer.contains(e)) {
        const o = outer.getBoundingClientRect();
        if (Math.abs(o.x - box.x) + Math.abs(o.y - box.y) + Math.abs(o.width - box.width) + Math.abs(o.height - box.height) < 8) continue;
      }
      out.push(e);
    }
    return out;
  }

  function focus(e) {
    if (cur) cur.removeAttribute('data-jarvis-focus');
    cur = e;
    curPage = location.href;
    inPage = layer() === document.body;
    e.setAttribute('data-jarvis-focus', '');
    if (e.matches(EMBED) || e.matches(TEXT)) { // focus() y enverrait les flèches suivantes, hors de notre portée : anneau seulement
      document.activeElement.blur();
    } else {
      if (e.tabIndex < 0 && !e.hasAttribute('tabindex')) e.tabIndex = -1; // carte en <div> : sinon activeElement reste sur l'ancien
      e.focus({ preventScroll: true });
    }
    e.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });
  }

  // Point d'entrée d'une couche : le dernier focus de la page s'il y en a un, sinon son bouton de lecture (fiche d'un film,
  // comme une appli TV), sinon son premier élément visible.
  const PLAY = /^(regarder|reprendre|lecture|voir une publicit|ouvrir une pub)/i;
  function enter(list, scope) {
    const m = scope === document.body && memo.get(location.href);
    if (m) {
      const d = (e) => { const r = rect(e); return Math.hypot(r.x + r.w / 2 - m.x - m.w / 2, r.y + r.h / 2 - m.y - m.h / 2); };
      return focus(list.reduce((a, b) => (d(b) < d(a) ? b : a)));
    }
    const vis = list.filter((e) => { const r = e.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; });
    focus(vis.find((e) => PLAY.test((e.innerText || '').trim())) || vis[0] || list[0]);
  }

  // Lecteur vidéo à l'écran : ←/→ restent au site (±10 s sur Bowd), OK met en pause, ↑/↓ entrent dans ses contrôles.
  const videos = () => [...document.querySelectorAll('video'), // Bowd met sa vidéo dans un shadow DOM
    ...[...document.querySelectorAll('*')].flatMap((e) => (e.shadowRoot ? [...e.shadowRoot.querySelectorAll('video')] : []))];
  const playing = () => videos().find((v) => {
    const r = v.getBoundingClientRect();
    return r.width * r.height >= innerWidth * innerHeight * 0.6 && shown(v);
  });

  function release() {
    if (cur) { cur.removeAttribute('data-jarvis-focus'); cur.blur(); }
    cur = null;
  }

  // Après un OK, une popup ou une nouvelle page s'ouvre souvent : le focus y entre seul (sauf dans un lecteur).
  function settle() {
    if (playing()) return;
    const l = layer(), list = candidates(l);
    if (list.length && !list.includes(cur)) enter(list, l);
  }

  window.__jarvisNav = {
    /** Touche Retour : sort des contrôles du lecteur, ou ferme la popup du dessus par son bouton « Fermer » ;
     *  false = au WebView de revenir en arrière. */
    back() {
      const a = document.activeElement;
      if (a && a.matches(EMBED)) { a.blur(); return true; } // le focus était dans un lecteur intégré : on en ressort
      if (cur && cur.isConnected && playing()) { release(); return true; }
      const l = layer();
      if (l === document.body) return false;
      const close = candidates(l).find((e) => /^(fermer|close)/i.test(e.getAttribute('aria-label') || e.title || e.innerText || ''));
      if (!close) return false;
      close.click();
      setTimeout(settle, 400);
      return true;
    },

    /** Point à toucher pour OK sur un contenu d'un autre domaine, en fraction de l'écran ; null sinon. */
    tap() {
      if (!cur || !cur.isConnected || !cur.matches(EMBED) || !shown(cur)) return null;
      const r = rect(cur), v = visualViewport;
      const x = cur.tagName === 'IFRAME' ? r.x + r.w / 2 : r.x + 24; // la case Cloudflare est à gauche
      return [(x - v.offsetLeft) / v.width, (r.y + r.h / 2 - v.offsetTop) / v.height];
    },
  };

  // Champ focalisé par le site lui-même (page d'un genre de Bowd) : le clavier s'ouvrirait et la page se décalerait.
  addEventListener('focusin', (ev) => { if (ev.target !== cur && ev.target.matches && ev.target.matches(TEXT)) ev.target.blur(); }, true);

  addEventListener('keydown', (ev) => {
    const dir = DIRS[ev.key], ok = ev.key === 'Enter';
    if (!dir && !ok) return;
    const a = document.activeElement;
    const typing = a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
    if (typing && dir !== 'up' && dir !== 'down') return; // curseur et validation du champ : au site
    const l = layer(), list = candidates(l);
    let i = list.indexOf(a);
    if (i < 0) i = list.indexOf(cur);
    const v = i < 0 && dir !== 'up' && dir !== 'down' && playing();
    if (v && ok) { // OK = lecture/pause (Bowd ne le fait qu'avec Espace)
      ev.preventDefault();
      ev.stopImmediatePropagation();
      return v.paused ? v.play() : v.pause();
    }
    if (v || !list.length) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    // Élément redessiné par le site sur la même page (carrousel d'OpenFlix) : on repart de sa dernière position.
    const lost = i < 0 && cur && !cur.isConnected && curPage === location.href && last;
    const j = lost && dir ? SiteNav.pick(list.map(rect), lost, dir) : -1;
    if (j >= 0) {
      focus(list[j]);
    } else if (i < 0) { // nouvelle page ou popup : on y entre sans encore bouger
      enter(list, l);
    } else if (ok) {
      if (list[i].matches(EMBED)) return; // tap natif de SiteActivity
      if (list[i].matches(TEXT)) return list[i].focus(); // ouvre le clavier
      list[i].click();
      setTimeout(settle, 600);
      setTimeout(settle, 1500); // changement d'écran : l'ancien n'est masqué (aria-hidden) qu'à la fin de la transition
    } else {
      const j = SiteNav.pick(list.map(rect), rect(list[i]), dir);
      if (j >= 0) focus(list[j]);
    }
  }, true);
}
