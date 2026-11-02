'use strict';
// Lancé par tests/test_iacompare.py (node --test) : moyenne, qualité/prix, modèles masqués et duel du comparatif des IA.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = {};
vm.runInNewContext(`${fs.readFileSync(`${__dirname}/../jarvis/web/comparatif.js`, 'utf8')}
this.api = { iacAvg, iacValue, iacRanked, iacDuelDomains };`, ctx);
const { iacAvg, iacValue, iacRanked, iacDuelDomains } = ctx.api;

const s = (code, general) => ({ ...(code === undefined ? {} : { code: { score: code, n: 2 } }), ...(general === undefined ? {} : { general: { score: general, n: 2 } }) });
const M = (id, code, general, extra = {}) => ({ id, name: id, gen: 'current', scores: s(code, general), ...extra });

test('moyenne des domaines cochés disponibles', () => {
  assert.strictEqual(iacAvg(M('a', 80, 60), ['code', 'general']), 70);
  assert.strictEqual(iacAvg(M('a', 80), ['code', 'general']), 80);
  assert.strictEqual(iacAvg(M('a', 80), ['general']), null);
});

test('qualité/prix : meilleur = 100, sans prix = absent', () => {
  const v = iacValue([M('opus', 90, 90, { price_mix: 10 }), M('haiku', 60, 60, { price_mix: 2 }), M('sans', 70, 70)], ['code']);
  assert.strictEqual(v.get('haiku'), 100);
  assert.strictEqual(v.get('opus'), 30);
  assert.strictEqual(v.has('sans'), false);
});

test('modèles loin du top 5 masqués, sauf bon rapport qualité/prix ou « tous »', () => {
  const models = [90, 88, 86, 84, 82].map((x, i) => M(`top${i}`, x, undefined, { price_mix: 20 }))
    .concat([M('loin', 40), M('pascher', 55, undefined, { price_mix: 0.5 }), M('vieux', 95, undefined, { gen: 'previous' })]);
  const r = iacRanked(models, ['code'], { old: false, all: false });
  const ids = r.rows.map((x) => x.m.id);
  assert.deepStrictEqual(ids, ['top0', 'top1', 'top2', 'top3', 'top4', 'pascher']);
  assert.strictEqual(r.hidden, 1);
  assert.ok(r.bestValue.has('pascher'));
  assert.strictEqual(iacRanked(models, ['code'], { old: false, all: true }).rows.length, 7);
  assert.strictEqual(iacRanked(models, ['code'], { old: true, all: false }).rows[0].m.id, 'vieux');
});

test('duel : domaines notés pour tous les modèles choisis', () => {
  assert.deepStrictEqual(iacDuelDomains([M('a', 80, 60), M('b', 70)], ['code', 'general']), ['code']);
  assert.deepStrictEqual(iacDuelDomains([M('a', 80, 60), M('b', 70, 50)], ['code', 'general']), ['code', 'general']);
});
