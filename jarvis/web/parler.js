// Bouton « parler » : enregistre avec le micro du téléphone, le PC transcrit (Whisper), le texte part dans le chat.
// L'audio n'est jamais gardé : un Blob en mémoire, envoyé à /api/stt, puis oublié. Un appui démarre, un appui arrête.
'use strict';
(() => {
  const talk = $('chat-talk');
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return; // HTTP clair ou vieux navigateur : bouton caché
  talk.hidden = false;
  const MAX_MS = 25000; // le serveur refuse au-delà de 30 s
  let rec = null;
  let timer = null;
  let sending = false;

  function setRecording(on) {
    talk.setAttribute('aria-pressed', String(on));
    talk.setAttribute('aria-label', on ? 'Arrêter et envoyer' : 'Parler avec le micro du téléphone');
  }

  async function send(blob) {
    sending = true;
    talk.disabled = true;
    try {
      const r = await api('/api/stt', { method: 'POST', body: blob });
      if (r.status === 503) toast('Reconnaissance vocale indisponible sur le PC.');
      else if (r.status === 413) toast('Message trop long : 30 secondes au plus.');
      else if (!r.ok || !r.data) toast('Je n’ai pas pu écouter.');
      else if (!r.data.text) toast('Je n’ai rien entendu.');
      else if (busy) toast('Jarvis est occupé avec une autre demande.');
      else sendChat(r.data.text.slice(0, 1000));
    } catch { /* api() a déjà signalé le réseau */ } finally {
      sending = false;
      talk.disabled = false;
    }
  }

  async function start() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      toast('Micro refusé : autorise-le dans les réglages du navigateur.');
      return;
    }
    const type = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((t) => MediaRecorder.isTypeSupported(t));
    const chunks = [];
    rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop()); // coupe le micro (voyant du téléphone) dès la fin
      const blob = new Blob(chunks, { type: rec.mimeType });
      rec = null;
      if (blob.size) send(blob);
    };
    rec.start();
    setRecording(true);
    timer = setTimeout(stop, MAX_MS);
  }

  function stop() {
    clearTimeout(timer);
    setRecording(false);
    if (rec && rec.state !== 'inactive') rec.stop();
  }

  talk.addEventListener('click', () => {
    if (sending) return;
    if (rec) stop(); else start();
  });
})();
