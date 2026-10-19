'use strict';
// ---- Œil de Jarvis : anneaux ondulants de particules autour d'une sphère de points, cadran HUD gradué (canvas, décoratif) ----
// Animé seulement quand le dashboard est visible ; une seule image fixe si l'utilisateur réduit les animations.
// Quand Jarvis réfléchit, l'œil s'accélère et s'illumine (transition douce).
const eye = $('eye'), eyeCtx = eye.getContext('2d');
const still = matchMedia('(prefers-reduced-motion: reduce)'), dark = matchMedia('(prefers-color-scheme: dark)');
// Chaque anneau est un ruban de 5 fils : les points suivent un fil (léger flou), d'où des lignes nettes qui se croisent.
// Les points les plus vifs (4 %) sont tirés à part, en blanc : des étincelles qui courent sur les fils.
const RINGS = Array.from({ length: 4 }, (_, k) => {
  const all = Array.from({ length: 1400 }, () => [Math.random() * Math.PI * 2, (Math.floor(Math.random() * 5) - 2) / 2 + (Math.random() - 0.5) * 0.06, Math.random()]);
  return { p: k * 1.7, s: 0.5 + k * 0.17, b: 0.94 + k * 0.035, dots: all.filter((d) => d[2] < 0.96), sparks: all.filter((d) => d[2] >= 0.96) };
});
const SPHERE = Array.from({ length: 260 }, (_, i) => { // sphère de Fibonacci
  const y = 1 - (2 * i + 1) / 260, r = Math.sqrt(1 - y * y), a = i * 2.39996;
  return [Math.cos(a) * r, y, Math.sin(a) * r];
});
let eyeFrame = 0, energy = 0, clock = 0, lastMs = 0;
function ringDots(c, g, list, R, mid, w, dot) {
  for (const [a, d, f] of list) {
    const r = R * (g.b + 0.06 * Math.sin(3 * a + w + g.p) + 0.04 * Math.sin(5 * a - w * 1.3 + g.p * 2) + 0.015 * Math.sin(9 * a + w * 2));
    const twist = Math.sin(2 * a + w * 0.8 + g.p), rr = r + d * R * 0.07 * twist; // ruban qui se tord : les fils se croisent quand il s'annule
    c.globalAlpha = (0.2 + 0.7 * f) * (0.55 + 0.45 * Math.abs(twist));
    c.fillRect(mid + Math.cos(a) * rr, mid + Math.sin(a) * rr, dot, dot);
  }
}
function drawEye(t) {
  const size = eye.clientWidth, dpr = devicePixelRatio || 1;
  if (!size) return;
  if (eye.width !== Math.round(size * dpr)) eye.width = eye.height = Math.round(size * dpr);
  const c = eyeCtx, R = size * 0.37, mid = size / 2, dot = 0.6 + size / 380; // points plus gros quand l'œil grandit
  const color = getComputedStyle(eye).color, glow = dark.matches;
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, size, size);
  // Halo du noyau : plus intense quand Jarvis réfléchit.
  const halo = c.createRadialGradient(mid, mid, 0, mid, mid, R * 0.75);
  halo.addColorStop(0, color); halo.addColorStop(1, 'transparent');
  c.globalAlpha = (glow ? 0.16 : 0.08) + 0.14 * energy;
  c.fillStyle = halo;
  c.fillRect(mid - R, mid - R, R * 2, R * 2);
  c.fillStyle = c.strokeStyle = color;
  c.globalCompositeOperation = glow ? 'lighter' : 'source-over';
  for (const g of RINGS) ringDots(c, g, g.dots, R, mid, t * g.s, dot);
  c.fillStyle = glow ? '#FFFFFF' : color;
  for (const g of RINGS) ringDots(c, g, g.sparks, R, mid, t * g.s, dot * 1.3);
  c.fillStyle = color;
  // Sphère qui tourne et respire.
  const sr = R * (0.2 + 0.008 * Math.sin(t * 1.6)), rot = t * 0.4, cr = Math.cos(rot), sn = Math.sin(rot);
  for (const [x, y, z] of SPHERE) {
    const xr = x * cr - z * sn, zr = x * sn + z * cr;
    c.globalAlpha = 0.25 + 0.5 * (zr + 1) / 2 + 0.2 * energy;
    c.fillRect(mid + xr * sr, mid + y * sr, dot, dot);
  }
  c.lineWidth = 1;
  // Anneau intérieur en pointillés qui tourne.
  c.globalAlpha = 0.22 + 0.2 * energy;
  c.setLineDash([2, 6]); c.lineDashOffset = -t * 8;
  c.beginPath(); c.arc(mid, mid, R * 0.34, 0, Math.PI * 2); c.stroke();
  c.setLineDash([]);
  // Cadran HUD : 120 graduations (une longue toutes les 10) qui tournent lentement…
  const dial = R * 1.28, spin = t * 0.05;
  c.globalAlpha = 0.28;
  c.beginPath();
  for (let i = 0; i < 120; i += 1) {
    const a = spin + (i / 120) * Math.PI * 2, len = i % 10 ? R * 0.025 : R * 0.06, ca = Math.cos(a), sa = Math.sin(a);
    c.moveTo(mid + ca * dial, mid + sa * dial);
    c.lineTo(mid + ca * (dial - len), mid + sa * (dial - len));
  }
  c.stroke();
  // … et trois arcs de visée qui tournent dans l'autre sens.
  const arcR = R * 1.33, back = -t * 0.12 * (1 + 1.5 * energy);
  c.lineWidth = 1.5;
  c.globalAlpha = 0.55 + 0.35 * energy;
  for (let k = 0; k < 3; k += 1) {
    const a0 = back + (k * Math.PI * 2) / 3;
    c.beginPath(); c.arc(mid, mid, arcR, a0, a0 + 0.55); c.stroke();
  }
  c.globalAlpha = 1;
  c.globalCompositeOperation = 'source-over';
}
function startEye() {
  cancelAnimationFrame(eyeFrame);
  if (still.matches) { drawEye(0); return; }
  lastMs = 0;
  const loop = (ms) => {
    if (views.chat.hidden || document.hidden || $('app').hidden) return; // relancé par show('chat') ou au retour sur l'onglet
    const dt = lastMs ? Math.min(0.1, (ms - lastMs) / 1000) : 0;
    lastMs = ms;
    energy += (($('thinking').hidden ? 0 : 1) - energy) * Math.min(1, dt * 3); // ~0,3 s pour s'éveiller ou se calmer
    clock += dt * (1 + 1.4 * energy);
    drawEye(clock);
    eyeFrame = requestAnimationFrame(loop);
  };
  eyeFrame = requestAnimationFrame(loop);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && !views.chat.hidden) startEye(); });
new ResizeObserver(() => { if (still.matches) drawEye(0); }).observe(eye);
