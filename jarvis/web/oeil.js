'use strict';
// ---- Œil de Jarvis : anneaux ondulants de particules autour d'une sphère de points (canvas, décoratif) ---------
// Animé seulement quand le dashboard est visible ; une seule image fixe si l'utilisateur réduit les animations.
const eye = $('eye'), eyeCtx = eye.getContext('2d');
const still = matchMedia('(prefers-reduced-motion: reduce)'), dark = matchMedia('(prefers-color-scheme: dark)');
// Chaque anneau est un ruban de 5 fils : les points suivent un fil (léger flou), d'où des lignes nettes qui se croisent.
const RINGS = Array.from({ length: 4 }, (_, k) => ({
  p: k * 1.7, s: 0.5 + k * 0.17, b: 0.94 + k * 0.035,
  dots: Array.from({ length: 1400 }, () => [Math.random() * Math.PI * 2, (Math.floor(Math.random() * 5) - 2) / 2 + (Math.random() - 0.5) * 0.06, Math.random()]),
}));
const SPHERE = Array.from({ length: 260 }, (_, i) => { // sphère de Fibonacci
  const y = 1 - (2 * i + 1) / 260, r = Math.sqrt(1 - y * y), a = i * 2.39996;
  return [Math.cos(a) * r, y, Math.sin(a) * r];
});
let eyeFrame = 0;
function drawEye(t) {
  const size = eye.clientWidth, dpr = devicePixelRatio || 1;
  if (!size) return;
  if (eye.width !== Math.round(size * dpr)) eye.width = eye.height = Math.round(size * dpr);
  const c = eyeCtx, R = size * 0.4, mid = size / 2, dot = 0.6 + size / 380; // points plus gros quand l'œil grandit
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, size, size);
  c.fillStyle = getComputedStyle(eye).color;
  c.globalCompositeOperation = dark.matches ? 'lighter' : 'source-over';
  for (const g of RINGS) {
    for (const [a, d, f] of g.dots) {
      const w = t * g.s;
      const r = R * (g.b + 0.06 * Math.sin(3 * a + w + g.p) + 0.04 * Math.sin(5 * a - w * 1.3 + g.p * 2) + 0.015 * Math.sin(9 * a + w * 2));
      const thick = R * 0.07 * Math.sin(2 * a + w * 0.8 + g.p); // ruban qui se tord : les fils se croisent quand il s'annule
      const rr = r + d * thick;
      c.globalAlpha = (0.2 + 0.7 * f) * (0.55 + 0.45 * Math.abs(Math.sin(2 * a + w * 0.8 + g.p)));
      c.fillRect(mid + Math.cos(a) * rr, mid + Math.sin(a) * rr, dot, dot);
    }
  }
  const sr = R * 0.2, rot = t * 0.4, cr = Math.cos(rot), sn = Math.sin(rot);
  for (const [x, y, z] of SPHERE) {
    const xr = x * cr - z * sn, zr = x * sn + z * cr;
    c.globalAlpha = 0.25 + 0.5 * (zr + 1) / 2;
    c.fillRect(mid + xr * sr, mid + y * sr, dot, dot);
  }
  c.globalAlpha = 0.18;
  c.strokeStyle = c.fillStyle;
  c.beginPath(); c.arc(mid, mid, R * 0.34, 0, Math.PI * 2); c.stroke();
  c.globalAlpha = 1;
}
function startEye() {
  cancelAnimationFrame(eyeFrame);
  if (still.matches) { drawEye(0); return; }
  const loop = (ms) => {
    if (views.chat.hidden || document.hidden || $('app').hidden) return; // relancé par show('chat') ou au retour sur l'onglet
    drawEye(ms / 1000);
    eyeFrame = requestAnimationFrame(loop);
  };
  eyeFrame = requestAnimationFrame(loop);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && !views.chat.hidden) startEye(); });
new ResizeObserver(() => { if (still.matches) drawEye(0); }).observe(eye);
