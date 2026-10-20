'use strict';
// Maquette : données fictives, aucun appel au Core. « H » ou ?horsligne simule le Core injoignable.

// Rangée 0 : pastilles du haut ; l'accueil s'ouvre sur la première appli.
const rowEls = [...document.querySelectorAll('.tiles')];
const tiles = rowEls.map((row) => [...row.querySelectorAll('.tile')]);
const HOME = { r: 1, c: 0 };
const last = {};
let pos = HOME;
let toastTimer;

// Logo absent (tv/logos/ n'est pas dans Git) : la tuile affiche le nom. Une image peut avoir échoué avant ce script.
function logoToText(img) {
  const span = document.createElement('span');
  span.className = 'big';
  span.textContent = img.alt;
  img.replaceWith(span);
}
document.querySelectorAll('.tile img').forEach((img) => {
  if (img.complete && !img.naturalWidth) logoToText(img);
  else img.addEventListener('error', () => logoToText(img));
});

function tileName(el) {
  const img = el.querySelector('img');
  return img ? img.alt : (el.querySelector('.big') || el).textContent;
}

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
  if (main.contains(sec)) reveal(main, 'scrollTop', 'clientHeight', sec.offsetTop - main.offsetTop, sec.offsetHeight, 0);
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
  } else if (el.dataset.app && window.JarvisTV) {
    // Dans l'APK : le pont Java lance l'appli (liste blanche côté Java). Sur PC : simple message.
    if (!window.JarvisTV.launch(el.dataset.app)) toast('Application absente de la TV');
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
    // Retour : revient sur la première appli ; l'accueil ne se ferme jamais.
    e.preventDefault();
    focusAt(HOME);
  } else if (e.key === 'h' || e.key === 'H') {
    setOffline(!document.body.classList.contains('offline'));
  }
});

// La souris et le Tab ne doivent pas désynchroniser la position mémorisée.
tiles.forEach((row, r) => row.forEach((t, c) => {
  t.style.setProperty('--c', t.dataset.color); // teinte de la tuile (pastille d'icône, reflet)
  t.addEventListener('focus', () => {
    pos = { r, c };
    last[r] = c;
    document.getElementById('hero').textContent = tileName(t);
    document.body.style.setProperty('--glow', t.dataset.color);
  });
  t.addEventListener('click', () => activate(t));
}));

function greeting(h) {
  if (h >= 5 && h < 12) return 'Bonjour';
  if (h >= 12 && h < 18) return 'Bon après-midi';
  if (h >= 18 && h < 23) return 'Bonsoir';
  return 'Bonne nuit';
}

function tick() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  document.getElementById('date').textContent = now.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long' });
  document.getElementById('greet').textContent = greeting(now.getHours());
}

tick();
setInterval(tick, 10000);
setOffline(new URLSearchParams(location.search).has('horsligne'));
focusAt(pos);
