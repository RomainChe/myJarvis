'use strict';
// Lancé par tests/test_bienetre_ui.py (node --test) : score et icônes de l'onglet Bien-être.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = {};
vm.runInNewContext(`${fs.readFileSync(`${__dirname}/../jarvis/web/bienetre.js`, 'utf8')}
this.api = { bienetreScore, bienetreIcon };`, ctx);
const { bienetreScore, bienetreIcon } = ctx.api;

test('score : part des points mesurés en bon état', () => {
  assert.strictEqual(bienetreScore({ OK: 6, 'à surveiller': 2, 'problème': 2, 'non mesuré': 5 }), 60);
  assert.strictEqual(bienetreScore({ OK: 0, 'à surveiller': 1, 'problème': 0, 'non mesuré': 0 }), 0);
  assert.strictEqual(bienetreScore({ OK: 0, 'à surveiller': 0, 'problème': 0, 'non mesuré': 3 }), 100);
});
test('icône par composant, puce par défaut', () => {
  assert.strictEqual(bienetreIcon('Carte graphique'), 'gpu');
  assert.strictEqual(bienetreIcon('Réseau Wi-Fi'), 'wifi');
  assert.strictEqual(bienetreIcon('Processeur'), 'chip');
});
