'use strict';
// ---- Finances : rapports hebdo (lecture seule, données sensibles : rien n'est gardé hors de la vue ouverte) ---------
const eur = (n) => (Number.isFinite(n) ? n.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' }) : '—');
const money = (n, cur) => {
  if (!Number.isFinite(n)) return '—';
  try { return n.toLocaleString('fr-FR', { style: 'currency', currency: cur }); } catch { return eur(n); } // devise inconnue
};
function clearFinance() {
  for (const id of ['fin-accounts', 'fin-tx', 'fin-consent', 'fin-crypto', 'fin-cycle', 'fin-portfolio']) $(id).replaceChildren();
  $('fin-bank').hidden = $('fin-crypto').hidden = $('fin-cycle').hidden = $('fin-portfolio').hidden = $('fin-invest').hidden = true;
  $('fin-bank-at').textContent = '';
}
// D3 : Finances s'ouvre 10 min après une signature de la clé d'accès (un token volé ne lit rien). Vrai si déverrouillé.
async function unlockFinance() {
  const ch = await api('/api/passkey/challenge', { method: 'POST', body: { action: 'finance' } });
  if (!ch.ok) { toast('Enregistrez d’abord une clé d’accès (Réglages) pour ouvrir Finances.'); return false; }
  const assertion = await getAssertion(ch.data);
  if (!assertion) { toast('Clé d’accès non validée.'); return false; }
  const ok = (await api('/api/finance/unlock', { method: 'POST', body: { assertion } })).ok;
  if (!ok) toast('Déverrouillage refusé.');
  return ok;
}
$('fin-unlock').addEventListener('click', async () => {
  $('fin-unlock').disabled = true;
  try { if (await unlockFinance()) await loadFinance(); } catch { /* api() a déjà prévenu */ } finally { $('fin-unlock').disabled = false; }
});
async function loadFinance() {
  const err = $('fin-error'), state = $('fin-state');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…';
  $('fin-unlock').hidden = true;
  try {
    const b = await api('/api/finance/bank');
    if (b.status === 403) { clearFinance(); state.textContent = 'Finances verrouillées.'; $('fin-unlock').hidden = false; return; }
    if (!b.ok) throw new Error('bad');
    if (views.finance.hidden) return; // vue quittée pendant le chargement
    renderBank(b.data?.bank); renderCrypto(b.data?.crypto); renderPortfolio(b.data?.portfolio);
    $('fin-invest').hidden = $('fin-crypto').hidden && $('fin-portfolio').hidden; // partie Investissement : titres-PEA puis Ledger
    state.hidden = !!b.data?.bank || !$('fin-crypto').hidden || !$('fin-portfolio').hidden ? true : false;
    if (!state.hidden) state.textContent = 'Aucune donnée bancaire : lance « python -m jarvis bank fetch ».';
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Finances indisponibles', e);
  }
}

// Logos locaux (liste fixe : une valeur venue de l'API ne construit jamais un chemin)
const LOGOS = { 'Crédit Mutuel': 'bank-cm.svg', 'Trade Republic': 'bank-tr.svg', BTC: 'coin-btc.svg', ETH: 'coin-eth.svg' };
function cardTitle(text, logo) {
  const h = el('h2', 'with-logo');
  if (logo) { const i = el('img', 'logo'); i.src = `/${logo}`; i.alt = ''; i.width = i.height = 22; h.append(i); }
  h.append(document.createTextNode(text));
  return h;
}
// Comptes Enable Banking : libellés = contenu externe, posés en textContent seulement
const CONSENT_WARN = 10; // jours : en dessous, la commande de renouvellement s'affiche
function renderBank(b) {
  if (!b) return;
  const at = new Date(b.fetched_at);
  $('fin-bank-at').textContent = Number.isNaN(at.getTime()) ? '' : `Comptes mis à jour le ${at.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' })}`;
  $('fin-consent').replaceChildren(...(b.consent || []).map((c) => {
    const late = !Number.isInteger(c.days_left) || c.days_left < CONSENT_WARN;
    const li = el('li', late ? 'warn' : 'muted', !Number.isInteger(c.days_left) ? `${c.bank} : échéance du consentement inconnue`
      : c.days_left < 0 ? `${c.bank} : consentement expiré` : `${c.bank} : consentement valable encore ${c.days_left} j`);
    if (late && c.renew) li.append(el('code', '', c.renew)); // construite et filtrée côté serveur (banking.renew_cmd)
    return li;
  }));
  $('fin-accounts').replaceChildren(...b.accounts.map((a) => {
    const s = el('section', 'panel hud stat');
    s.append(cardTitle(a.bank, LOGOS[a.bank]), el('p', 'big', money(a.balance, a.currency)), el('p', 'muted', a.name));
    return s;
  }));
  $('fin-tx').replaceChildren(...(b.transactions.length ? b.transactions.slice(0, 6).map((t) => {
    const li = el('li');
    const what = el('span', 'tx-what', t.label || '—');
    what.append(el('small', 'muted', `${t.date} · ${t.account}`));
    li.append(what, el('span', t.amount > 0 ? 'tx-amt pos' : 'tx-amt', money(t.amount, t.currency)));
    return li;
  }) : [el('li', 'muted', 'Aucune opération sur 90 jours.')]));
  renderCycle(b.cycle);
  $('fin-bank').hidden = false;
}

// Bilan du cycle de paie (calculé par budget.py) : libellés bancaires posés en textContent seulement
const fdate = (d) => (d ? `le ${d.slice(8, 10)}/${d.slice(5, 7)}` : '');
function cycPanel(accent, title, sub) {
  const p = el('section', `panel hud cyc ${accent}`);
  p.append(el('h2', '', title));
  if (sub) p.append(el('p', 'muted', sub));
  return p;
}
function cycLine(r, withCat) {
  const li = el('li', 'cyc-line');
  const what = el('span', 'tx-what', `${r.emoji} ${r.name}`);
  const meta = [r.detail, fdate(r.date)].filter(Boolean).join(' · ');
  if (meta || r.bank) {
    const s = el('small', 'muted', meta);
    if (r.bank) s.append(el('span', `bank ${r.bank === 'Trade Republic' ? 'tr' : 'cm'}`, ` ● ${r.bank}`));
    what.append(s);
  }
  const amt = el('span', 'cyc-amt', eur(r.amount));
  if (withCat && r.cat) { const c = el('span', 'cat', r.cat); c.dataset.cat = r.cat; amt.append(c); }
  li.append(what, amt);
  return li;
}
function cycTotal(label, value, cls = '') {
  const li = el('li', 'cyc-line cyc-total');
  li.append(el('span', '', label), el('span', `cyc-amt ${cls}`, eur(value)));
  return li;
}
function cycList(rows, withCat, total) {
  const u = el('ul', 'plain cyc-list');
  u.append(...rows.map((r) => cycLine(r, withCat)));
  if (total) u.append(total);
  return u;
}
function renderCycle(c) {
  const box = $('fin-cycle');
  box.replaceChildren();
  box.hidden = !c;
  if (!c) return;
  const stat = (t, v, sub, cls = '') => {
    const s = el('section', 'panel hud stat');
    s.append(el('h2', '', t), el('p', 'big', v), el('p', `muted ${cls}`, sub));
    return s;
  };
  const strip = el('div', 'strip cyc-top');
  strip.append(stat('💰 Paie reçue', eur(c.pay.amount), fdate(c.pay.date)), stat('🏠 Charges fixes', eur(c.fixed.total), `${c.fixed.pct} % de la paie`),
    stat('🌱 Épargne', eur(c.saving.total), `taux ${c.saving.rate} %`), stat('📉 Reste fin de cycle', eur(c.left), c.left < 0 ? 'dépassement' : 'disponible', c.left < 0 ? 'warn' : 'ok'));
  const where = cycPanel('', '🧭 Où est partie la paie');
  const bar = el('div', 'cyc-stack');
  for (const [cls, v] of [['fx', c.fixed.total], ['sv', c.saving.total], ['cs', c.conso.total]]) {
    const s = el('span', cls);
    s.style.flexGrow = String(Math.max(0, v));
    bar.append(s);
  }
  where.append(bar, el('p', 'muted', `Fixes ${eur(c.fixed.total)} · Épargne ${eur(c.saving.total)} · Consommation ${eur(c.conso.total)}`));
  if (c.left < 0) where.append(el('p', 'warn', `Les sorties dépassent la paie de ${eur(-c.left)}${c.covered.total ? `, couvert par ${eur(c.covered.total)} venus de ton autre compte` : ''}.`));
  const fixed = cycPanel('fx', '🏠 Charges fixes', `${c.fixed.pct} % de ta paie`);
  fixed.append(cycList(c.fixed.items, false, cycTotal('Total', c.fixed.total)));
  const saving = cycPanel('sv', '🌱 Épargne', `taux d'épargne ${c.saving.rate} %`);
  const rate = el('ul', 'plain meters');
  rate.append(meter('Taux d\'épargne', Math.min(100, c.saving.rate), `${c.saving.rate} % · repère 20 %`, false));
  saving.append(cycList(c.saving.items, false, cycTotal('Total épargné', c.saving.total, 'ok')), rate);
  const top = Math.max(1, ...c.conso.cats.map((x) => x.amount));
  const cons = cycPanel('cs', '🛍️ Consommation', 'par catégorie, remboursements d\'amis déduits');
  const cats = el('ul', 'plain cyc-list');
  cats.append(...c.conso.cats.map((x) => {
    const li = el('li', 'cyc-line'), tag = el('span', 'cat', x.name), w = el('div', 'meter-bar'), f = el('span');
    tag.dataset.cat = f.dataset.cat = x.name;
    f.style.width = `${(x.amount / top) * 100}%`;
    w.append(f);
    const amt = el('span', 'cyc-amt', eur(x.amount));
    if (x.prev != null) amt.append(el('small', 'muted', `préc. ${eur(x.prev)}`));
    li.append(tag, w, amt);
    return li;
  }));
  cats.append(cycTotal('Total consommation', c.conso.total, 'gold'));
  cons.append(cats);
  if (c.conso.refunds.items.length) {
    const rf = el('p', 'cyc-refund');
    rf.append(el('strong', 'ok', `🤝 Remboursements d'amis −${eur(c.conso.refunds.total)}`), el('small', 'muted', c.conso.refunds.items.map((r) => `${r.name} ${eur(r.amount)}`).join(', ')));
    cons.append(rf);
  }
  const detail = cycPanel('cs', '🧾 Le détail');
  detail.append(cycList(c.conso.detail, true));
  const points = cycPanel('info', '💡 Ce qui ressort');
  points.append(...c.points.map((x) => el('p', 'cyc-point', `${x.icon} ${x.text}`)));
  const more = [];
  if (c.subs.length) { const p = cycPanel('sub', '🔁 Abonnements & prélèvements'); p.append(cycList(c.subs)); more.push(p); }
  if (c.week) { const p = cycPanel('info', '📅 Dernière semaine', `dépenses : ${eur(c.week.spent)}`); p.append(cycList([...c.week.top, ...c.week.internal])); more.push(p); }
  const [subs, week] = [more.find((p) => p.classList.contains('sub')), more.find((p) => p.classList.contains('info'))];
  const row1 = el('div', 'cyc-grid'), row2 = el('div', 'cyc-grid');
  row1.append(fixed, saving, cons);
  row2.append(detail, points, ...(subs ? [subs] : []));
  box.append(strip, where, row1, row2, ...(week ? [week] : []));
  if (c.recos.length) { const p = cycPanel('reco', '🎯 Recommandations'); p.append(...c.recos.map((t) => el('p', 'cyc-point', t))); box.append(p); } // dernier, hors grille
}

// Ledger : soldes lus en tâche de fond par le serveur ; première lecture en cours = l'onglet se recharge une fois
let cryptoRetry;
// Portefeuille Trade Republic (export CSV importé) : noms = contenu externe, posés en textContent seulement
function renderPortfolio(p) {
  const box = $('fin-portfolio');
  box.replaceChildren();
  box.hidden = !p?.accounts?.length;
  if (box.hidden) return;
  const pct = (n) => `${n >= 0 ? '+' : ''}${n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} %`;
  for (const a of p.accounts) {
    const s = el('section', 'panel hud stat');
    const up = a.gain >= 0;
    s.append(cardTitle(a.name, LOGOS['Trade Republic']), el('p', 'big', eur(a.value)),
      el('p', `muted ${up ? 'ok' : 'warn'}`, `${a.pct == null ? '' : pct(a.pct)} · ${up ? '+' : ''}${eur(a.gain)}`),
      el('p', 'muted', `investi ${eur(a.invested)}${a.dividends ? ` · dividendes ${eur(a.dividends)}` : ''}${a.realized ? ` · réalisé ${eur(a.realized)}` : ''}`));
    if (a.missing) s.append(el('p', 'muted warn', `${a.missing} ligne(s) sans cours, comptée(s) à leur prix d'achat`));
    box.append(s);
  }
}
function renderCrypto(c) {
  clearTimeout(cryptoRetry);
  if (!c) return;
  const qty = (a) => `${a.amount.toLocaleString('fr-FR', { maximumFractionDigits: 8 })} ${a.asset}`;
  const cards = c.assets.map((a) => {
    const s = el('section', 'panel hud stat');
    s.append(cardTitle(`Ledger · ${a.name}`, LOGOS[a.asset]), el('p', 'big', money(a.eur, 'EUR')), el('p', 'muted', qty(a)));
    if (Number.isFinite(a.gain)) { // prix de revient Binance (Auto-Invest + conversions) ; cours rafraîchi toutes les 15 min
      const up = a.gain >= 0;
      s.append(el('p', `muted ${up ? 'ok' : 'warn'}`, `${up ? '+' : ''}${a.pct.toLocaleString('fr-FR', { maximumFractionDigits: 2 })} % · ${up ? '+' : ''}${eur(a.gain)}`),
        el('p', 'muted', `investi ${eur(a.invested)}`));
    }
    return s;
  });
  const note = c.errors.join(' · ') || (c.refreshing && !cards.length ? 'Ledger : lecture en cours…' : '');
  if (note) cards.push(el('p', 'muted', note));
  $('fin-crypto').replaceChildren(...cards);
  $('fin-crypto').hidden = !cards.length;
  if (c.refreshing && !c.assets.length) cryptoRetry = setTimeout(() => { if (!views.finance.hidden) loadFinance(); }, 15000);
}
