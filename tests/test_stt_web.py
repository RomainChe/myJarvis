"""Bouton « parler » de la PWA : audio du téléphone -> /api/stt -> texte. Le texte n'est jamais journalisé ni exécuté ici."""
import io
import threading
import unittest
import wave

try:
    import av
    import numpy as np
except ImportError:
    raise unittest.SkipTest("av/numpy absents (extra `voice`)")
from jarvis import server
from tests.test_server import ServerBase


def clip(seconds: float, fmt: str = "webm", codec: str = "libopus") -> bytes:
    """Vrai conteneur encodé (silence) comme MediaRecorder en produit."""
    out = io.BytesIO()
    with av.open(out, "w", format=fmt) as container:
        stream = container.add_stream(codec, rate=48000)
        stream.layout = "mono"
        for _ in range(int(seconds * 50)):  # trames de 20 ms
            frame = av.AudioFrame.from_ndarray(np.zeros((1, 960), np.int16), format="s16", layout="mono")
            frame.sample_rate = 48000
            container.mux(stream.encode(frame))
        container.mux(stream.encode(None))
    return out.getvalue()


def wav(seconds: float) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return out.getvalue()


class FakeSTT:
    def __init__(self, text="allume le salon", error=None):
        self.text, self.error, self.heard = text, error, []
        self.gate = None  # Event : bloque la transcription (test du « occupé »)

    def transcribe(self, audio):
        if self.gate:
            self.gate.wait(5)
        if self.error:
            raise self.error
        self.heard.append(len(audio))
        return self.text


class SttWebTest(ServerBase):
    def setUp(self):
        self.stt = FakeSTT()
        super().setUp()
        self.token = self.enroll()[1]

    def post(self, body, kind="audio/webm", token="default"):
        return self.call("POST", "/api/stt", body, token=self.token if token == "default" else token, Content_Type=kind)

    def rows(self):
        return [r for r in self.audit.last(20) if r[2] == "stt"]

    def test_texte_renvoye_et_journal_sans_le_texte(self):
        status, body, _ = self.post(clip(1))
        self.assertEqual((status, body), (200, {"text": "allume le salon"}))
        self.assertAlmostEqual(self.stt.heard[0], 16000, delta=800)
        self.assertNotIn("salon", str(self.rows()[0]))

    def test_les_trois_formats_du_navigateur(self):
        self.assertEqual(self.post(clip(1, "webm"), "audio/webm;codecs=opus")[0], 200)
        self.assertEqual(self.post(clip(1, "ogg"), "audio/ogg")[0], 200)
        self.assertEqual(self.post(clip(1, "mp4", "aac"), "audio/mp4")[0], 200)

    def test_micro_autorise_pour_la_page(self):
        self.assertIn("microphone=(self)", self.post(clip(1))[2].getheader("Permissions-Policy"))

    def test_sans_jeton_refuse(self):
        self.assertEqual(self.post(clip(1), token=None)[0], 401)
        self.assertEqual(self.stt.heard, [])

    def test_cle_de_portee_voix_refusee(self):
        _, voice_token = self.devices.add_scoped("micro salon", "voice")
        self.assertEqual(self.post(clip(1), token=voice_token)[0], 403)
        self.assertEqual(self.stt.heard, [])

    def test_type_refuse(self):
        for kind in ("application/json", "text/plain", "audio/wav"):
            self.assertEqual(self.post(clip(1), kind)[0], 415, kind)

    def test_json_ailleurs_inchange(self):  # le type audio n'ouvre que /api/stt
        self.assertEqual(self.call("POST", "/api/chat", b"x", token=self.token, Content_Type="audio/webm")[0], 415)

    def test_trop_gros_et_trop_long(self):
        self.assertEqual(self.post(b"x" * (server.STT_BODY_MAX + 1))[0], 413)
        self.assertEqual(self.post(clip(server.STT_SECONDS_MAX + 2))[0], 413)
        self.assertEqual(self.stt.heard, [])
        self.assertEqual(self.rows()[0][5], "refusé")

    def test_contenu_qui_ne_correspond_pas_au_type(self):  # ffmpeg ne devine jamais le format
        for body in (wav(1), b"#EXTM3U\n#EXT-X-VERSION:3\nfile:///etc/passwd\n", clip(1, "ogg"), b"pas de l'audio"):
            self.assertEqual(self.post(body, "audio/webm")[0], 422)
        self.assertEqual(self.post(clip(1, "webm"), "audio/ogg")[0], 422)
        self.assertEqual(self.stt.heard, [])

    def test_codec_hors_liste(self):  # PCM dans du Matroska est valide, mais pas ce que produit MediaRecorder
        self.assertEqual(self.post(clip(1, "matroska", "pcm_s16le"))[0], 422)

    def test_rien_d_intelligible(self):
        self.stt.text = ""
        self.assertEqual(self.post(clip(1))[1], {"text": ""})

    def test_modele_indisponible(self):
        from jarvis.core.stt import STTError
        self.stt.error = STTError("modèle non vérifié")
        status, body, _ = self.post(clip(1))
        self.assertEqual(status, 503)
        self.assertNotIn("vérifié", str(body))

    def test_quota_par_minute(self):
        for _ in range(server.STT_MAX):
            self.assertEqual(self.post(clip(0.1))[0], 200)
        self.assertEqual(self.post(clip(0.1))[0], 429)

    def test_occupe_pas_de_file(self):  # une transcription en cours : la suivante est refusée tout de suite
        self.stt.gate = threading.Event()
        first = threading.Thread(target=lambda: self.post(clip(1)))
        first.start()
        threading.Event().wait(0.5)  # laisse la première requête prendre la place
        try:
            self.assertEqual(self.post(clip(1))[0], 503)
        finally:
            self.stt.gate.set()
            first.join(5)


class SttAbsentTest(ServerBase):
    def test_core_sans_micro(self):  # mini-PC : pas de Whisper, réponse claire
        token = self.enroll()[1]
        self.assertEqual(self.call("POST", "/api/stt", clip(1), token=token, Content_Type="audio/webm")[0], 503)


if __name__ == "__main__":
    unittest.main()
