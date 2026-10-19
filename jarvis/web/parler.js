// Bouton « parler ». Voie 1 : dictée du navigateur (SpeechRecognition) ; sur Chrome/Android l'audio passe par les serveurs de
// Google (accepté par le propriétaire le 2026-10-19), le texte part dans le chat. Voie 2, sans dictée : enregistre avec le micro,
// le PC transcrit (Whisper) via /api/stt ; l'audio n'est jamais gardé (Blob en mémoire). Un appui démarre, un appui arrête.
'use strict';
(() => {
  const talk = $('chat-talk');
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR && (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)) return; // HTTP clair ou vieux navigateur : bouton caché
  talk.hidden = false;
  let sr = null;

  function dictate() {
    if (sr) { sr.stop(); return; }
    sr = new SR();
    sr.lang = 'fr-FR';
    sr.onresult = (e) => {
      const text = e.results[0][0].transcript.trim();
      if (!text) toast('Je n’ai rien entendu.');
      else if (busy) toast('Jarvis est occupé avec une autre demande.');
      else sendChat(text.slice(0, 1000));
    };
    sr.onerror = (e) => toast(['not-allowed', 'service-not-allowed'].includes(e.error) ? 'Micro refusé : autorise-le dans les réglages du navigateur.'
      : e.error === 'no-speech' ? 'Je n’ai rien entendu.' : 'Je n’ai pas pu écouter.');
    sr.onend = () => { sr = null; setRecording(false); };
    sr.start();
    setRecording(true);
  }
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
    if (SR) return dictate();
    if (sending) return;
    if (rec) stop(); else start();
  });
})();
