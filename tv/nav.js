'use strict';
// Navigation D-pad de l'interface TV, sans DOM (testée par tests/tv_nav.test.js).
// rows : abscisses du centre de chaque tuile, rangée par rangée ; last : dernière colonne visitée par rangée.

const TvNav = {
  KEYS: { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' },

  next(rows, pos, dir, last) {
    const { r, c } = pos;
    if (dir === 'left') return { r, c: Math.max(0, c - 1) };
    if (dir === 'right') return { r, c: Math.min(rows[r].length - 1, c + 1) };
    if (dir !== 'up' && dir !== 'down') return pos;
    const t = r + (dir === 'up' ? -1 : 1);
    if (t < 0 || t >= rows.length) return pos;
    // Une rangée déjà visitée reprend sa colonne (comme l'accueil Google TV), sinon la tuile la plus proche à l'écran.
    if (last && last[t] !== undefined) return { r: t, c: Math.min(last[t], rows[t].length - 1) };
    const x = rows[r][c];
    let best = 0;
    rows[t].forEach((tx, i) => { if (Math.abs(tx - x) < Math.abs(rows[t][best] - x)) best = i; });
    return { r: t, c: best };
  },
};

if (typeof module === 'object') module.exports = TvNav;
