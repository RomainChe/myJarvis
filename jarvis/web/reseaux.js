'use strict';
// ---- Réseaux : publications et planning de lol-clipper (lecture seule) -----------------------------------------------
const PLATFORMS = { youtube: 'YouTube', tiktok: 'TikTok', all: 'YouTube + TikTok' };
const fmtDate = (iso) => new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
function socialRow(r, withLink) {
  const li = el('li', 'row pub');
  const title = el('div', 'pub-title', r.title);
  title.title = String(r.title ?? '');
  const meta = el('div', 'pub-meta');
  meta.append(el('span', `badge plat ${r.platform === 'youtube' ? 'yt' : r.platform === 'tiktok' ? 'tt' : ''}`, PLATFORMS[r.platform] ?? r.platform), el('span', '', fmtDate(r.at)));
  if (r.privacy) meta.append(el('span', 'badge status', r.privacy));
  if (Number.isInteger(r.views)) meta.append(el('span', 'pub-views', `${r.views.toLocaleString('fr-FR')} vues`));
  li.append(title, meta);
  if (withLink && typeof r.url === 'string' && URL.canParse(r.url) && new URL(r.url).protocol === 'https:') {
    const a = el('a', 'link-btn', 'Ouvrir');
    a.href = r.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    li.append(a);
  }
  return li;
}
async function loadSocial() {
  const err = $('social-error');
  try {
    const r = await api('/api/social');
    if (!r.ok || !r.data) throw new Error('bad');
    const stale = r.data.stale; // présent seulement si le PC est injoignable : relevé gardé par le Core du mini-PC
    err.hidden = r.data.configured && stale === undefined;
    err.textContent = stale === undefined ? 'Dossier de lol-clipper introuvable.' : stale ? `PC éteint : relevé du ${fmtDate(stale)}.` : 'PC éteint : aucun relevé gardé.';
    const fill = (id, rows, empty, link) => $(id).replaceChildren(...(rows.length ? rows.map((x) => socialRow(x, link)) : [el('li', 'row muted', empty)]));
    const yt = r.data.youtube;
    $('social-yt').hidden = !yt;
    if (yt) {
      const d = (x) => (x ? `${x.subs >= 0 ? '+' : ''}${x.subs}` : '…');
      const n = (x) => (Number.isFinite(x) ? x.toLocaleString('fr-FR') : '—');
      $('yt-subs').textContent = yt.error ? '—' : n(yt.subs);
      $('yt-views').textContent = yt.error ? '—' : n(yt.views);
      $('yt-videos').textContent = yt.error ? '—' : n(yt.videos);
      $('yt-d7').textContent = yt.error ? '—' : `${d(yt.delta?.d7)} en 7 j`;
      $('yt-d30').textContent = yt.error ? '' : `${d(yt.delta?.d30)} en 30 j`;
      $('yt-detail').hidden = !yt.error;
      $('yt-detail').textContent = yt.error === 'reconnexion' ? 'Reconnexion de lol-clipper à faire (droit youtube.readonly).' : 'Statistiques indisponibles.';
    }
    fill('social-todo', r.data.scheduled, 'Rien de programmé.', false);
    fill('social-done', r.data.published, 'Aucune publication.', true);
  } catch (e) {
    err.hidden = false;
    err.textContent = unavailable('Réseaux indisponibles', e);
  }
}
