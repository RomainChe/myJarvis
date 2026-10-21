'use strict';
// Lancé par tests/test_tv_maquette.py (node --test).
const test = require('node:test');
const assert = require('node:assert');
const SiteNav = require('../android-tv/app/src/main/assets/sitenav.js');

const R = (x, y, w = 100, h = 50) => ({ x, y, w, h });
// Barre de menu, puis une rangée de cartes, puis une rangée décalée.
const rects = [R(0, 0), R(150, 0), R(300, 0), R(0, 200), R(150, 200), R(300, 200), R(500, 400)];

test('gauche/droite : voisin de la rangée, rien au bord', () => {
  assert.strictEqual(SiteNav.pick(rects, rects[0], 'right'), 1);
  assert.strictEqual(SiteNav.pick(rects, rects[4], 'left'), 3);
  assert.strictEqual(SiteNav.pick(rects, rects[2], 'right'), -1);
  assert.strictEqual(SiteNav.pick(rects, rects[3], 'left'), -1);
});

test('gauche/droite ne partent jamais en diagonale', () => {
  assert.strictEqual(SiteNav.pick(rects, rects[5], 'right'), -1); // la carte décalée est plus bas, pas dans la rangée
});

test('haut/bas : élément en face, sinon le plus proche', () => {
  assert.strictEqual(SiteNav.pick(rects, rects[1], 'down'), 4);
  assert.strictEqual(SiteNav.pick(rects, rects[5], 'up'), 2);
  assert.strictEqual(SiteNav.pick(rects, rects[5], 'down'), 6);
  assert.strictEqual(SiteNav.pick(rects, rects[0], 'up'), -1);
});

test('une rangée proche passe avant un élément aligné mais lointain', () => {
  const r = [R(0, 0), R(60, 120), R(0, 900)];
  assert.strictEqual(SiteNav.pick(r, r[0], 'down'), 1);
});

test('un élément chevauchant l\'actuel n\'est pas « devant » lui', () => {
  const r = [R(0, 0, 300, 300), R(10, 10, 280, 40)];
  assert.strictEqual(SiteNav.pick(r, r[0], 'down'), -1);
});
