'use strict';
// ---- Démarrage -------------------------------------------------------------------------------
window.addEventListener('offline', () => { setStatus('Hors ligne.'); setLink(false); });
window.addEventListener('online', () => { setStatus(''); setLink(true); });
tickClock();
setInterval(tickClock, 10000);
setInterval(() => { if (!$('app').hidden && !document.hidden) loadMic(); }, 15000); // coupé depuis le PC : le bouton suit

(async function start() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  // Le fragment est lu puis effacé AVANT tout le reste : même avec un token déjà présent, le code ne reste pas
  // dans la barre d'adresse ni dans l'historique.
  const code = new URLSearchParams(location.hash.slice(1)).get('code');
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  token = await getToken();
  if (token) {
    // D6 : token renouvelé à chaque ouverture (90 jours glissants) ; hors ligne, l'ancien reste valable.
    try {
      const r = await api('/api/token', { method: 'POST', body: {} });
      if (r.ok && r.data?.token) { token = r.data.token; await setToken(token); }
    } catch { /* hors ligne ou 401 (api() a déjà déconnecté) */ }
    if (token) showApp();
    return;
  }
  if (code) {
    showEnroll();
    await enroll(code.trim(), $('enroll-name').value.trim() || guessName());
    return;
  }
  showEnroll();
})();
