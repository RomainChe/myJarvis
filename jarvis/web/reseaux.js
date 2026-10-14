'use strict';
// ---- Réseaux : publications et planning de lol-clipper (lecture seule) -----------------------------------------------
const PLATFORMS = { youtube: 'YouTube', tiktok: 'TikTok', all: 'YouTube + TikTok' };
const fmtDate = (iso) => new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
function socialRow(r, withLink) {
  const li = el('li', 'row');
  li.append(el('div', 'tool', r.title), el('div', 'meta', `${PLATFORMS[r.platform] ?? r.platform} · ${fmtDate(r.at)}${r.privacy ? ` · ${r.privacy}` : ''}${Number.isInteger(r.views) ? ` · ${r.views} vues` : ''}`));
  if (withLink && typeof r.url === 'string' && URL.canParse(r.url) && new URL(r.url).protocol === 'https:') {
    const a = el('a', '', 'Ouvrir');
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
    err.hidden = r.data.configured;
    err.textContent = 'Dossier de lol-clipper introuvable.';
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
