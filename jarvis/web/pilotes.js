'use strict';
// ---- Pilotes : dernière vérification de DriverWatch (status.json du PC : donnée, texte seul) ; « Go » = driverwatch_update_all (N2) ----
const DRV = { critical: ['be-bad', 'retard critique'], moderate: ['be-warn', 'retard modéré'], unknown: ['be-none', 'inconnu'], ok: ['', 'à jour'] };
let driversTimer = 0;
async function loadDrivers() {
  clearTimeout(driversTimer);
  const err = $('drivers-error'), state = $('drivers-state'), list = $('drivers-list'), go = $('drivers-go');
  err.hidden = true; state.hidden = false; state.textContent = 'Chargement…'; list.replaceChildren(); go.hidden = true;
  try {
    const r = await api('/api/drivers');
    if (!r.ok || !r.data) throw new Error('bad');
    if (views.drivers.hidden) return; // vue quittée pendant le chargement
    const d = r.data;
    if (!d.configured) { state.textContent = 'Projet DriverWatch introuvable sur le PC.'; return; }
    if (d.offline) { state.textContent = 'PC éteint ou injoignable : état des pilotes indisponible.'; return; }
    if (d.checking) driversTimer = setTimeout(loadDrivers, 30000); // vérification en cours (quelques minutes) : on relit
    if (!d.at) { state.textContent = d.checking ? 'Première vérification en cours (quelques minutes)…' : 'Aucune vérification pour le moment.'; return; }
    state.hidden = true;
    const when = new Date(d.at).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
    const late = d.drivers.filter((p) => p.newer && !p.ignored && (p.status === 'critical' || p.status === 'moderate'));
    const n = (s) => d.drivers.filter((p) => p.status === s).length;
    const strip = el('div', 'strip');
    strip.append(stat('À mettre à jour', String(late.length), undefined, '', late.length ? 'alarm' : 'hero'),
      stat('À jour', String(n('ok'))), stat('Inconnus', String(n('unknown')), 'aucune source n\'a répondu'));
    const row = (p) => {
      const [k, label] = DRV[p.status];
      const li = el('li', `be-item${k ? ` be-card-${k.slice(3)}` : ''}`);
      const head = el('div', 'be-head'), t = el('p', 'be-title');
      t.append(el('strong', '', p.name), el('span', 'be-point', p.category));
      head.append(t, el('span', `badge ${k}`, p.ignored ? 'ignorée' : label));
      const v = p.newer && p.latest ? `${p.installed} → ${p.latest} (${p.days} j de retard)` : p.installed;
      li.append(head, el('p', 'be-value', v));
      if (p.source) li.append(el('p', 'be-point', `Source : ${p.source}`));
      return li;
    };
    const ul = el('ul', 'plain be-list');
    ul.append(...d.drivers.map(row));
    list.replaceChildren(el('p', 'muted', d.checking ? 'Nouvelle vérification en cours…' : `Vérifié le ${when}, renouvelé chaque jour.`), strip, ul);
    go.hidden = !late.length;
    go.textContent = `Go : mettre à jour ${late.length > 1 ? `les ${late.length} pilotes` : 'le pilote'}`;
  } catch (e) {
    state.hidden = true; err.hidden = false;
    err.textContent = unavailable('Pilotes indisponibles', e);
  }
}
$('drivers-go').addEventListener('click', async () => {
  if (busy) { toast('Jarvis est occupé avec une autre demande.'); return; }
  const out = $('drivers-result'), go = $('drivers-go');
  const say = (kind, text) => { out.textContent = kind === 'jarvis' && text.includes('lancée') ? 'Mise à jour lancée : accepte la demande Windows (UAC) sur le PC.' : text; };
  say('note', 'Envoi…');
  setBusy(true);
  go.disabled = true;
  try {
    const r = await api('/api/drivers/update', { method: 'POST', body: {} });
    if (r.status === 429) { say('note', 'Jarvis est occupé avec une autre demande.'); return; }
    if (!r.ok || !r.data || !r.data.job) { say('fail', 'Demande refusée.'); return; }
    await pollJob(r.data.job, say); // N2 : la PWA demande la confirmation
  } catch (err) {
    if (err.message === 'network') say('fail', 'PC injoignable.');
  } finally {
    setBusy(false);
    go.disabled = false;
  }
});
