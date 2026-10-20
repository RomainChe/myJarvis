'use strict';
// Maquette : données fictives, aucun appel au Core. « H » ou ?horsligne simule le Core injoignable.

const rowEls = [...document.querySelectorAll('.row .tiles')];
const tiles = rowEls.map((row) => [...row.querySelectorAll('.tile')]);
const last = {};
let pos = { r: 0, c: 0 };
let toastTimer;

function centers() {
  return tiles.map((row) => row.map((t) => { const b = t.getBoundingClientRect(); return b.left + b.width / 2; }));
}

function focusAt(p) {
  pos = p;
  last[p.r] = p.c;
  const el = tiles[p.r][p.c];
  el.focus({ preventScroll: true });
  // Défilement maison (scrollIntoView décale aussi le body) : juste assez pour voir la tuile entière.
  const row = rowEls[p.r];
  reveal(row, 'scrollLeft', 'clientWidth', el.offsetLeft - row.offsetLeft, el.offsetWidth, 32);
  const main = document.getElementById('rows');
  const sec = row.parentElement;
  reveal(main, 'scrollTop', 'clientHeight', sec.offsetTop - main.offsetTop, sec.offsetHeight, 0);
}

function reveal(box, scroll, size, start, len, pad) {
  if (start - pad < box[scroll]) box[scroll] = Math.max(0, start - pad);
  else if (start + len + pad > box[scroll] + box[size]) box[scroll] = start + len + pad - box[size];
}

function toast(text) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

function setOffline(off) {
  document.body.classList.toggle('offline', off);
  document.getElementById('status').textContent = off ? 'JARVIS hors ligne' : 'JARVIS en ligne';
}

function activate(el) {
  if (el.classList.contains('jarvis') && document.body.classList.contains('offline')) {
    toast('JARVIS est hors ligne : action indisponible');
  } else {
    toast(el.dataset.say);
  }
}

document.addEventListener('keydown', (e) => {
  const dir = TvNav.KEYS[e.key];
  if (dir) {
    e.preventDefault();
    focusAt(TvNav.next(centers(), pos, dir, last));
  } else if (e.key === 'Enter') {
    e.preventDefault();
    activate(tiles[pos.r][pos.c]);
  } else if (e.key === 'Escape' || e.key === 'Backspace' || e.key === 'GoBack') {
    // Retour : remonte en haut à gauche ; l'accueil ne se ferme jamais.
    e.preventDefault();
    focusAt({ r: 0, c: 0 });
  } else if (e.key === 'h' || e.key === 'H') {
    setOffline(!document.body.classList.contains('offline'));
  }
});

// La souris et le Tab ne doivent pas désynchroniser la position mémorisée.
tiles.forEach((row, r) => row.forEach((t, c) => {
  t.addEventListener('focus', () => { pos = { r, c }; last[r] = c; });
  t.addEventListener('click', () => activate(t));
}));

function tick() {
  document.getElementById('clock').textContent = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
}

tick();
setInterval(tick, 10000);
setOffline(new URLSearchParams(location.search).has('horsligne'));
focusAt(pos);
