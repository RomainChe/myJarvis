'use strict';
// Lancé par tests/test_tv_maquette.py (node --test).
const test = require('node:test');
const assert = require('node:assert');
const SiteNav = require('../android-tv/app/src/main/assets/sitenav.js');

const box = (left, top, w = 100, h = 100) => ({ left, top, right: left + w, bottom: top + h });
// Grille 3 × 2 : rangée 0 en y = 0, rangée 1 en y = 200 ; colonnes x = 0, 200, 400.
const grid = [box(0, 0), box(200, 0), box(400, 0), box(0, 200), box(200, 200), box(400, 200)];

test('les flèches vont à la voisine alignée', () => {
  assert.strictEqual(SiteNav.pick(grid[1], grid, 'right'), 2);
  assert.strictEqual(SiteNav.pick(grid[1], grid, 'left'), 0);
  assert.strictEqual(SiteNav.pick(grid[1], grid, 'down'), 4);
  assert.strictEqual(SiteNav.pick(grid[4], grid, 'up'), 1);
});

test('rien dans la direction : -1 (la page défile normalement)', () => {
  assert.strictEqual(SiteNav.pick(grid[0], grid, 'left'), -1);
  assert.strictEqual(SiteNav.pick(grid[0], grid, 'up'), -1);
  assert.strictEqual(SiteNav.pick(grid[5], grid, 'down'), -1);
  assert.strictEqual(SiteNav.pick(grid[0], [], 'right'), -1);
});

test('aligné plutôt que plus proche en diagonale', () => {
  const cur = box(0, 0);
  const diagonale = box(110, 150); // plus près le long de x, mais décalée en travers
  const alignee = box(300, 0);
  assert.strictEqual(SiteNav.pick(cur, [diagonale, alignee], 'right'), 1);
});

test('bouton large sous une rangée de petites affiches', () => {
  const affiches = [box(0, 0, 50, 80), box(60, 0, 50, 80), box(120, 0, 50, 80)];
  const bouton = box(0, 120, 400, 40);
  assert.strictEqual(SiteNav.pick(affiches[2], affiches.concat(bouton), 'down'), 3);
  assert.strictEqual(SiteNav.pick(bouton, affiches.concat(bouton), 'up'), 2); // centre x = 200 : l'affiche la plus à droite
});
