'use strict';
// ---- Réseaux : publications et planning de lol-clipper (lecture seule) -----------------------------------------------
const PLATFORMS = { youtube: 'YouTube', tiktok: 'TikTok', all: 'YouTube + TikTok' };
const fmtDate = (iso) => new Date(iso).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
const PRIVACY = { public: 'Public', private: 'Privée', unlisted: 'Non répertoriée' };
// « 2026-10-18_18h21_Renekton_compilation » -> « Renekton » + « compilation » (la date est déjà dans la colonne Publiée).
function pubName(raw) {
  const words = String(raw ?? '').replace(/^\d{4}-\d{2}-\d{2}_\d{2}h\d{2}_?/, '').split('_').filter(Boolean);
  const name = words[0] ? words[0][0].toUpperCase() + words[0].slice(1) : String(raw ?? '');
  return [name, words.slice(1).join(' ')];
}
function socialRow(r, withLink) {
  const li = el('li', 'row pub');
  const [name, kind] = pubName(r.title);
  const link = withLink && typeof r.url === 'string' && URL.canParse(r.url) && new URL(r.url).protocol === 'https:';
  const title = el(link ? 'a' : 'span', 'pub-title', name);
  if (kind) title.append(el('span', 'pub-kind', ` · ${kind}`));
  title.title = String(r.title ?? '');
  if (link) { title.href = r.url; title.target = '_blank'; title.rel = 'noopener noreferrer'; }
  const meta = el('div', 'pub-meta'), plat = el('span', 'pub-plat');
  plat.append(icon(r.platform === 'tiktok' ? 'note' : 'play'), document.createTextNode(PLATFORMS[r.platform] ?? r.platform));
  meta.append(el('span', 'pub-when', fmtDate(r.at)), plat);
  if (r.privacy) meta.append(el('span', `badge status${Object.hasOwn(PRIVACY, r.privacy) ? ` ${r.privacy}` : ''}`, Object.hasOwn(PRIVACY, r.privacy) ? PRIVACY[r.privacy] : r.privacy)); // classe tirée de la table seulement
  li.append(title, meta, el('span', 'pub-views', Number.isInteger(r.views) ? `${r.views.toLocaleString('fr-FR')} vues` : ''));
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
