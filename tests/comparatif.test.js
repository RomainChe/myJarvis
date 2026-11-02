'use strict';
// Lancé par tests/test_iacompare.py (node --test) : moyenne, taux d'erreur, classement, verdict prix et vitesse du comparatif des IA.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const ctx = {};
vm.runInNewContext(`${fs.readFileSync(`${__dirname}/../jarvis/web/comparatif.js`, 'utf8')}
this.api = { iacAvg, iacRanked, iacVerdicts, iacErr, iacErrX };`, ctx);
const { iacAvg, iacRanked, iacVerdicts, iacErr, iacErrX } = ctx.api;

const s = (code, general) => ({ ...(code === undefined ? {} : { code: { score: code, n: 2 } }), ...(general === undefined ? {} : { general: { score: general, n: 2 } }) });
const M = (id, code, general, extra = {}) => ({ id, name: id, gen: 'current', scores: s(code, general), ...extra });

test('moyenne des domaines cochés disponibles', () => {
  assert.strictEqual(iacAvg(M('a', 80, 60), ['code', 'general']), 70);
  assert.strictEqual(iacAvg(M('a', 80), ['code', 'general']), 80);
  assert.strictEqual(iacAvg(M('a', 80), ['general']), null);
});

test("taux d'erreur = 100 − note, multiple d'erreurs par rapport au meilleur", () => {
  assert.strictEqual(iacErr(82.6), 17.4);
  assert.strictEqual(iacErrX(70.6, 82.6), 1.7); // Haiku : 29,4 % d'erreurs contre 17,4 %
  assert.strictEqual(iacErrX(82.6, 82.6), 1);
  assert.strictEqual(iacErrX(90, 100), null); // meilleur parfait : pas de multiple
});

test('classement : versions actuelles seulement, les précédentes avec « anciennes versions »', () => {
  const models = [M('nouveau', 80, 80), { ...M('ancien', 95, 95), gen: 'previous' }];
  assert.deepStrictEqual(iacRanked(models, ['code'], { old: false, all: true }).rows.map((x) => x.m.id), ['nouveau']);
  assert.deepStrictEqual(iacRanked(models, ['code'], { old: true, all: true }).rows.map((x) => x.m.id), ['ancien', 'nouveau']);
});

test('modèles loin du top 5 masqués, sauf « tous »', () => {
  const models = [90, 88, 86, 84, 82].map((x, i) => M(`top${i}`, x, undefined, { price_mix: 20 })).concat([M('loin', 40), M('pascher', 55, undefined, { price_mix: 0.5 })]);
  const r = iacRanked(models, ['code'], { old: false, all: false });
  assert.deepStrictEqual(r.rows.map((x) => x.m.id), ['top0', 'top1', 'top2', 'top3', 'top4']);
  assert.strictEqual(r.hidden, 2);
  assert.strictEqual(iacRanked(models, ['code'], { old: false, all: true }).rows.length, 7);
});

test('deux notes égales : le modèle aux plus nombreux tests passe devant', () => {
  const few = { ...M('few', 80), scores: { code: { score: 80, n: 1 } } }, many = { ...M('many', 80), scores: { code: { score: 80, n: 4 } } };
  const r = iacRanked([few, many], ['code'], { old: false, all: true });
  assert.deepStrictEqual(r.rows.map((x) => x.m.id), ['many', 'few']);
  assert.deepStrictEqual(r.rows.map((x) => x.n), [4, 1]);
});

// Cas réel : Haiku est très bon marché mais fait beaucoup plus d'erreurs qu'Opus.
const P = (id, g, price, tps, extra = {}) => M(id, undefined, g, { price_mix: price, tps, ...extra });
const FLOTTE = [P('opus', 82.6, 8, 96), P('sol', 82.6, 4, 77), P('haiku', 70.6, 0.2, 181), P('mini', 77.3, 1.69, 248), { ...P('vieux', 95, 0.1, 500), gen: 'previous' }];
const prefs = (over = {}) => ({ profile: 'safe', budget: null, minSpeed: null, ...over });

test("profil « fiabilité d'abord » : Haiku n'est ni meilleur choix, ni moins cher, ni plus rapide", () => {
  const v = iacVerdicts(FLOTTE, ['general'], prefs());
  assert.strictEqual(v.ref.id, 'opus');
  assert.strictEqual(v.gap, 5);
  assert.deepStrictEqual([...v.pool].sort(), ['opus', 'sol']);
  assert.strictEqual(v.pick.id, 'sol');
  assert.strictEqual(v.cheapest.id, 'sol');
  assert.strictEqual(v.fastest.id, 'opus');
  assert.strictEqual(v.cheapestAny.id, 'haiku'); // signalé comme écarté, pas gagnant
  assert.strictEqual(v.fastestAny.id, 'mini');
});

test('profil « économie » : Haiku redevient éligible ; la version précédente ne gagne jamais', () => {
  const v = iacVerdicts(FLOTTE, ['general'], prefs({ profile: 'eco' }));
  assert.strictEqual(v.cheapest.id, 'haiku');
  assert.strictEqual(v.fastest.id, 'mini');
  assert.ok(!v.pool.has('vieux'));
});

test('budget et vitesse minimale restreignent le verdict ; aucun modèle = verdict vide', () => {
  const v = iacVerdicts(FLOTTE, ['general'], prefs({ profile: 'balanced', budget: 5, minSpeed: 100 }));
  assert.deepStrictEqual([...v.pool], ['mini']);
  assert.strictEqual(v.pick.id, 'mini');
  const none = iacVerdicts(FLOTTE, ['general'], prefs({ budget: 1, minSpeed: 100 }));
  assert.strictEqual(none.pool.size, 0);
  assert.strictEqual(none.pick, null);
  assert.strictEqual(iacVerdicts([], ['general'], prefs()), null);
});
