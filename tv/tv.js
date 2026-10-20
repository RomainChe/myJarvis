'use strict';
// Maquette : données fictives, aucun appel au Core. « H » ou ?horsligne simule le Core injoignable.

// Rangée 0 : pastilles du haut ; l'accueil s'ouvre sur la première appli.
const rowEls = [...document.querySelectorAll('.tiles')];
const tiles = rowEls.map((row) => [...row.querySelectorAll('.tile')]);
const APPS = 1;
const HOME = { r: APPS, c: 0 };
const last = {};
let pos = HOME;
let toastTimer;
let moving = null; // tuile appli en cours de déplacement
let pressed = false; // Entrée enfoncée sur cette page : un relâchement orphelin ne lance rien
let held = false; // Entrée maintenue : l'appui long a ouvert le déplacement, le relâchement ne lance rien
let holdTimer;
const HOLD_MS = 600;

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

// Liaison au Core (APK seulement) : le pont Java fait l'appel ; la page ne voit ni l'adresse ni la clé,
// et affiche ce qui revient en textContent seulement. Sur PC (maquette), pas de pont : données fictives.
const linked = !!(window.JarvisTV && window.JarvisTV.core);
const waiting = new Map();
let seq = 0;

function core(route, text) {
  return new Promise((resolve) => {
    const id = String(++seq);
    waiting.set(id, resolve);
    window.JarvisTV.core(id, route, text || '');
  });
}

window.onCore = (id, status, body) => {
  const done = waiting.get(id);
  waiting.delete(id);
  if (done) done({ status, body });
};

function parse(r) {
  try { return r.status === 200 ? JSON.parse(r.body) : null; } catch (e) { return null; }
}

const deg = (v) => (Number.isFinite(v) ? `${Math.round(v)}°` : '?');

let refreshTimer;
let saying = false; // une commande à la fois : un invité qui martèle une tuile n'empile pas les appels

async function refresh() {
  const r = await core('tv');
  if (r.status === 401 || r.status === 403) { // clé expirée (90 jours) ou révoquée : inutile de réessayer chaque minute
    clearInterval(refreshTimer);
    setOffline(true);
    document.getElementById('status').textContent = 'JARVIS hors ligne · clé TV à renouveler';
    return;
  }
  const d = parse(r);
  setOffline(!d);
  if (!d) return;
  const w = d.weather;
  if (w && Number.isFinite(w.temp_c)) {
    document.getElementById('wx-temp').textContent = `${Math.round(w.temp_c)} °C`;
    document.getElementById('wx-sub').textContent = `${String(w.sky).slice(0, 30)} · ${deg(w.min_c)} / ${deg(w.max_c)}`;
  }
  document.getElementById('rem-sub').textContent = !Number.isInteger(d.reminders) ? 'Indisponible'
    : d.reminders ? `${d.reminders} à venir` : "Aucun aujourd'hui";
}

async function say(text) {
  if (saying) return;
  saying = true;
  try {
    const d = parse(await core('say', text));
    toast(d && typeof d.answer === 'string' ? d.answer.slice(0, 160) : 'JARVIS ne répond pas');
  } finally {
    saying = false;
  }
}

function activate(el) {
  if (el.classList.contains('jarvis') && document.body.classList.contains('offline')) {
    toast('JARVIS est hors ligne : action indisponible');
  } else if (el.dataset.cmd && linked) {
    say(el.dataset.cmd);
  } else if (el.classList.contains('jarvis') && linked) {
    toast('Pas encore branché');
  } else if (el.dataset.app && window.JarvisTV) {
    // Dans l'APK : le pont Java lance l'appli (liste blanche côté Java). Sur PC : simple message.
    if (!window.JarvisTV.launch(el.dataset.app)) toast('Application absente de la TV');
  } else {
    toast(el.dataset.say);
  }
}

// Ordre des applis mémorisé dans IndexedDB (seul stockage permis, voir tests/test_web_static.py).
// Stockage indisponible : l'ordre par défaut de index.html reste affiché.
function prefs(fn) {
  try {
    const req = indexedDB.open('jarvis-tv', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('prefs');
    req.onsuccess = () => fn(req.result.transaction('prefs', 'readwrite').objectStore('prefs'));
  } catch (e) {
    // pas de stockage : rien à faire
  }
}

function refreshApps() {
  tiles[APPS] = [...rowEls[APPS].querySelectorAll('.tile')];
}

function applyOrder(saved) {
  const byKey = new Map(tiles[APPS].map((t) => [t.dataset.app, t]));
  TvNav.order([...byKey.keys()], saved).forEach((k) => rowEls[APPS].append(byKey.get(k)));
  refreshApps();
  if (pos.r === APPS) focusAt(pos);
}

function startMoving(el) {
  moving = el;
  el.classList.add('moving');
  document.body.classList.add('reordering');
  toast('Gauche / droite : déplacer · Entrée : valider');
}

function stopMoving() {
  moving.classList.remove('moving');
  document.body.classList.remove('reordering');
  moving = null;
  const order = tiles[APPS].map((t) => t.dataset.app);
  prefs((store) => store.put(order, 'apps'));
  toast('Ordre des applis enregistré');
}

function moveApp(d) {
  const i = tiles[APPS].indexOf(moving);
  const j = i + d;
  if (j < 0 || j >= tiles[APPS].length) return;
  if (d < 0) tiles[APPS][j].before(moving);
  else tiles[APPS][j].after(moving);
  refreshApps();
  focusAt({ r: APPS, c: j });
}

document.addEventListener('keydown', (e) => {
  const dir = TvNav.KEYS[e.key];
  if (e.key === 'Enter') {
    // Appui simple : action au relâchement (keyup). Appui long sur une appli : déplacement.
    // Minuteur plutôt que la répétition : la WebView de la TV ne livre pas les keydown répétés.
    e.preventDefault();
    if (pressed) return;
    pressed = true;
    if (!moving && pos.r === APPS) {
      holdTimer = setTimeout(() => {
        held = true;
        startMoving(tiles[pos.r][pos.c]);
      }, HOLD_MS);
    }
    return;
  }
  if (moving) {
    // Mode déplacement : seules gauche/droite bougent l'appli ; Retour valide, Entrée valide au relâchement.
    e.preventDefault();
    if (dir === 'left' || dir === 'right') moveApp(dir === 'left' ? -1 : 1);
    else if (e.key === 'Escape' || e.key === 'Backspace' || e.key === 'GoBack') stopMoving();
  } else if (dir) {
    e.preventDefault();
    focusAt(TvNav.next(centers(), pos, dir, last));
  } else if (e.key === 'Escape' || e.key === 'Backspace' || e.key === 'GoBack') {
    // Retour : revient sur la première appli ; l'accueil ne se ferme jamais.
    e.preventDefault();
    focusAt(HOME);
  } else if (e.key === 'h' || e.key === 'H') {
    setOffline(!document.body.classList.contains('offline'));
  }
});

document.addEventListener('keyup', (e) => {
  if (e.key !== 'Enter' || !pressed) return;
  e.preventDefault();
  pressed = false;
  clearTimeout(holdTimer);
  if (held) held = false;
  else if (moving) stopMoving();
  else activate(tiles[pos.r][pos.c]);
});

// La souris et le Tab ne doivent pas désynchroniser la position mémorisée.
// La colonne est relue au focus : les applis peuvent avoir changé de place.
tiles.forEach((row, r) => row.forEach((t) => {
  t.style.setProperty('--c', t.dataset.color); // teinte de la tuile (pastille d'icône, reflet)
  t.addEventListener('focus', () => {
    const c = tiles[r].indexOf(t);
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
setOffline(linked || new URLSearchParams(location.search).has('horsligne')); // dans l'APK : hors ligne tant que le Core n'a pas répondu
if (linked) {
  document.getElementById('wx-temp').textContent = '—'; // la météo fictive de la maquette ne reste pas affichée
  document.getElementById('wx-sub').textContent = '';
  refresh();
  refreshTimer = setInterval(refresh, 60000);
}
focusAt(pos);
prefs((store) => {
  const req = store.get('apps');
  req.onsuccess = () => { if (req.result) applyOrder(req.result); };
});
