'use strict';
// Lancé par tests/test_drivers_tab.py (node --test) : classement et icônes de l'onglet Pilotes.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = { $: () => ({ addEventListener() {} }) };
vm.runInNewContext(`${fs.readFileSync(`${__dirname}/../jarvis/web/pilotes.js`, 'utf8')}
this.api = { driverKind, driverIcon, driverBrand };`, ctx);
const { driverKind, driverIcon, driverBrand } = ctx.api;

test('version plus récente sous le seuil : « disponible », jamais « à jour »', () => {
  assert.strictEqual(driverKind({ status: 'ok', newer: true }), 'avail');
  assert.strictEqual(driverKind({ status: 'ok', newer: false }), 'ok');
  assert.strictEqual(driverKind({ status: 'moderate', newer: true }), 'moderate');
  assert.strictEqual(driverKind({ status: 'critical', newer: true }), 'critical');
  assert.strictEqual(driverKind({ status: 'critical', newer: true, ignored: true }), 'ignored');
  assert.strictEqual(driverKind({ status: 'unknown', newer: false }), 'unknown');
});

test('icône et marque par nom et catégorie', () => {
  assert.strictEqual(driverIcon({ name: 'Intel(R) Wireless Bluetooth(R)', category: 'BLUETOOTH' }), 'bt');
  assert.strictEqual(driverIcon({ name: 'Intel(R) Wi-Fi 6E AX211', category: 'NET' }), 'wifi');
  assert.strictEqual(driverIcon({ name: 'Realtek 2.5GbE', category: 'NET' }), 'ethernet');
  assert.strictEqual(driverIcon({ name: 'X', category: 'DISPLAY' }), 'gpu');
  assert.strictEqual(driverIcon({ name: 'Inconnu', category: 'AUTRE' }), 'chip');
  assert.strictEqual(driverBrand({ name: 'GeForce', source: 'NVIDIA' })[1], 'NVIDIA');
  assert.strictEqual(driverBrand({ name: 'Pointel device' }), null); // mot entier seulement
});
