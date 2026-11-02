'use strict';
// Lancé par tests/test_iacompare.py (node --test) : moyenne, qualité/prix, modèles masqués et duel du comparatif des IA.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = {};
vm.runInNewContext(`${fs.readFileSync(`${__dirname}/../jarvis/web/comparatif.js`, 'utf8')}
this.api = { iacAvg, iacValue, iacRanked };`, ctx);
const { iacAvg, iacValue, iacRanked } = ctx.api;

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

test('une version précédente plus forte que sa suivante reste visible, signalée par `beats`', () => {
  const models = [M('sol', 80, 80, { prev: 'astra' }), { ...M('astra', 90, 90), gen: 'previous' }, { ...M('vieux', 99, 99), gen: 'previous' }, { ...M('peu', 99), gen: 'previous' }, M('autre', 70, 70, { prev: 'peu' })];
  const r = iacRanked(models, ['code', 'general'], { old: false, all: true });
  assert.deepStrictEqual(r.rows.map((x) => x.m.id), ['astra', 'sol', 'autre']); // « peu » : un seul domaine commun, pas de comparaison
  assert.strictEqual(r.rows[0].beats.id, 'sol');
  assert.strictEqual(r.rows[1].beats, null);
  assert.ok(r.rows.every((x) => x.m.id !== 'peu'));
});

test('deux notes égales : le modèle aux plus nombreux tests passe devant', () => {
  const few = { ...M('few', 80), scores: { code: { score: 80, n: 1 } } }, many = { ...M('many', 80), scores: { code: { score: 80, n: 4 } } };
  const r = iacRanked([few, many], ['code'], { old: false, all: true });
  assert.deepStrictEqual(r.rows.map((x) => x.m.id), ['many', 'few']);
  assert.deepStrictEqual(r.rows.map((x) => x.n), [4, 1]);
});
