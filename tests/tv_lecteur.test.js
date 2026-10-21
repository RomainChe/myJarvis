'use strict';
// Lancé par tests/test_tv_maquette.py (node --test) : exécute VIDEO_JS tel qu'écrit dans SiteActivity.java.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const java = fs.readFileSync(path.join(__dirname, '../android-tv/app/src/main/java/fr/jarvis/tv/SiteActivity.java'), 'utf8');
const decl = java.match(/VIDEO_JS = ([\s\S]*?");/)[1];
const js = [...decl.matchAll(/"([^"]*)"/g)].map(m => m[1]).join('');

function run(action, document) {
  return new Function('document', 'return ' + js.replace('%s', action))(document);
}
function video(t, paused) {
  return { tagName: 'VIDEO', currentTime: t, paused, play() { this.paused = false; }, pause() { this.paused = true; } };
}

test('OK bascule lecture/pause sur la vidéo en plein écran', () => {
  const v = video(0, true);
  run("'toggle'", { fullscreenElement: v, querySelector: () => null });
  assert.strictEqual(v.paused, false);
  run("'toggle'", { fullscreenElement: v, querySelector: () => null });
  assert.strictEqual(v.paused, true);
});

test('gauche/droite : -10/+10 s, jamais avant 0 ; vidéo cherchée dans le conteneur plein écran', () => {
  const v = video(5, false);
  const doc = { fullscreenElement: { tagName: 'DIV', querySelector: () => v }, querySelector: () => null };
  run('10', doc);
  assert.strictEqual(v.currentTime, 15);
  run('-10', doc);
  run('-10', doc);
  assert.strictEqual(v.currentTime, 0);
});

test('sans vidéo : rien, renvoie false', () => {
  assert.strictEqual(run("'toggle'", { fullscreenElement: null, querySelector: () => null }), false);
});
