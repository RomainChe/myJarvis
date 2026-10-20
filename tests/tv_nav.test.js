'use strict';
// Lancé par tests/test_tv_maquette.py (node --test).
const test = require('node:test');
const assert = require('node:assert');
const TvNav = require('../tv/nav.js');

const rows = [[100, 300, 500, 700], [200, 400], [100, 300, 500, 700, 900]];

test('gauche/droite restent dans la rangée, sans boucler', () => {
  assert.deepStrictEqual(TvNav.next(rows, { r: 0, c: 0 }, 'left'), { r: 0, c: 0 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 0, c: 3 }, 'right'), { r: 0, c: 3 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 0, c: 1 }, 'right'), { r: 0, c: 2 });
});

test('haut/bas visent la tuile la plus proche à l\'écran', () => {
  assert.deepStrictEqual(TvNav.next(rows, { r: 0, c: 3 }, 'down', {}), { r: 1, c: 1 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 1, c: 0 }, 'down', {}), { r: 2, c: 0 });
});

test('une rangée déjà visitée reprend sa colonne', () => {
  assert.deepStrictEqual(TvNav.next(rows, { r: 1, c: 0 }, 'down', { 2: 4 }), { r: 2, c: 4 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 2, c: 0 }, 'up', { 1: 9 }), { r: 1, c: 1 });
});

test('les bords et les touches inconnues ne bougent pas le focus', () => {
  assert.deepStrictEqual(TvNav.next(rows, { r: 0, c: 2 }, 'up', {}), { r: 0, c: 2 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 2, c: 2 }, 'down', {}), { r: 2, c: 2 });
  assert.deepStrictEqual(TvNav.next(rows, { r: 1, c: 1 }, 'ok', {}), { r: 1, c: 1 });
});
