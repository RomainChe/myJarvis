"""Phase 3, étape 3 : chat et confirmations N2 par l'API (vrai serveur local ; le LLM et l'exécution sont simulés)."""
import time
import unittest
from unittest import mock

from jarvis.core import chat as chat_mod
from jarvis.core.tools import REGISTRY
from test_server import ServerBase

def kill_call():  # `test_llm.call` ne sait pas passer un argument nommé « name »
    return {"function": {"name": "kill_process", "arguments": {"pid": 4242, "name": "notepad.exe"}}}


UNROUTED = "fais quelque chose d'inhabituel"  # ni phrase ni motif du routeur : part au LLM


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("délai dépassé")


class ChatBase(ServerBase):
    def setUp(self):
        super().setUp()
        self.device, self.token = self.enroll("tel")
        self.calls = []

    def start(self, text=UNROUTED, token=None):
        status, body, _ = self.call("POST", "/api/chat", {"text": text}, token=token or self.token)
        return status, body

    def poll(self, job, token=None):
        return self.call("GET", f"/api/chat/{job}", token=token or self.token)

    def done(self, job):
        return wait_for(lambda: (lambda r: r[1] if r[1] and r[1]["status"] == "done" else None)(self.poll(job)))

    def pending(self, job):
        return wait_for(lambda: self.poll(job)[1]["pending"])

    def decide(self, cid, approve, token=None):
        return self.call("POST", f"/api/confirm/{cid}", {"approve": approve}, token=token or self.token)

    def fake_ask(self, tool_name="kill_process", args=None, level="confirm"):
        """Un LLM simulé qui demande l'outil `tool_name` à travers la garde de confirmation."""
        def ask(text, *, audit, confirm, strong_auth, source):
            self.calls.append(source)
            tool = REGISTRY[tool_name]
            ok = (confirm if level == "confirm" else strong_auth)(tool, args or {"pid": 4242, "name": "notepad.exe"})
            return "confirmé" if ok else "refusé"
        return mock.patch.object(chat_mod, "ask", ask)


class ChatTest(ChatBase):
    def test_authentification_obligatoire(self):
        self.assertEqual(self.call("POST", "/api/chat", {"text": "x"})[0], 401)
        self.assertEqual(self.call("GET", "/api/chat/abc")[0], 401)
        self.assertEqual(self.call("POST", "/api/confirm/abc", {"approve": True})[0], 401)

    def test_intention_simple_sans_llm_source_pwa(self):
        with mock.patch.object(chat_mod, "execute", return_value={"tv": "on"}) as execute, \
                mock.patch.object(chat_mod, "ask") as ask:
            status, body = self.start("allume la télé")
            self.assertEqual(status, 202)
            self.assertEqual(self.done(body["job"])["answer"], "{'tv': 'on'}")
        ask.assert_not_called()
        self.assertEqual(execute.call_args.args[0], "tv_on")
        self.assertEqual(execute.call_args.kwargs["source"], f"pwa:{self.device}")

    def test_confirmation_n2_approuvee_une_seule_fois(self):
        with self.fake_ask():
            job = self.start()[1]["job"]
            pending = self.pending(job)
            self.assertEqual(pending["tool"], "kill_process")
            self.assertIn("notepad.exe", pending["preview"])  # aperçu calculé par le serveur
            self.assertEqual(self.decide(pending["id"], True)[0], 200)
            self.assertEqual(self.done(job)["answer"], "confirmé")
            self.assertEqual(self.decide(pending["id"], True)[0], 404)  # rejeu
        self.assertEqual(self.calls, [f"pwa:{self.device}/llm"])

    def test_refus_expiration_et_valeurs_non_booleennes(self):
        with self.fake_ask():
            job = self.start()[1]["job"]
            cid = self.pending(job)["id"]
            for bad in ("true", 1, "oui", None):
                self.assertEqual(self.decide(cid, bad)[0], 422, bad)  # seul `true` confirme
            self.assertEqual(self.decide(cid, False)[0], 200)
            self.assertEqual(self.done(job)["answer"], "refusé")
        with self.fake_ask(), mock.patch.object(chat_mod, "CONFIRM_TTL_S", 0.3):
            job = self.start()[1]["job"]
            self.pending(job)
            self.assertEqual(self.done(job)["answer"], "refusé")  # personne n'a répondu
        rows = str(self.audit.last(30))
        self.assertIn("expirée", rows)

    def test_un_autre_appareil_ne_voit_ni_n_approuve(self):
        _, other = self.enroll("autre")
        with self.fake_ask():
            job = self.start()[1]["job"]
            cid = self.pending(job)["id"]
            self.assertEqual(self.poll(job, token=other)[0], 404)
            self.assertEqual(self.decide(cid, True, token=other)[0], 404)
            self.assertEqual(self.decide(cid, False)[0], 200)
            self.done(job)

    def test_une_seule_demande_a_la_fois(self):
        with self.fake_ask():
            job = self.start()[1]["job"]
            cid = self.pending(job)["id"]
            self.assertEqual(self.start()[0], 429)
            self.decide(cid, False)
            self.done(job)
            second = self.start()
            self.assertEqual(second[0], 202)  # le verrou est rendu
            self.decide(self.pending(second[1]["job"])["id"], False)
            self.done(second[1]["job"])

    def test_n3_toujours_refuse(self):
        with self.fake_ask("kill_process", level="strong"):
            job = self.start()[1]["job"]
            self.assertEqual(self.done(job)["answer"], "refusé")

    def test_erreur_du_llm_rend_le_verrou(self):
        with mock.patch.object(chat_mod, "ask", side_effect=RuntimeError("secret interne")):
            job = self.start()[1]["job"]
            self.assertEqual(self.done(job)["answer"], "Erreur interne : RuntimeError")  # pas le message
            self.assertEqual(self.start()[0], 202)

    def test_journal_longueur_et_hash_jamais_le_texte(self):
        secret = "mot de passe : hunter2-vraiment-secret"
        with mock.patch.object(chat_mod, "ask", return_value="ok"):
            self.done(self.start(secret)[1]["job"])
        rows = str(self.audit.last(10))
        self.assertIn("sha256", rows)
        self.assertIn(str(len(secret)), rows)
        self.assertNotIn("hunter2", rows)
        self.assertTrue(self.audit.verify())

    def test_entrees_invalides(self):
        for body in ({"text": ""}, {"text": "x" * 1001}, {}, {"text": 5}):
            self.assertEqual(self.call("POST", "/api/chat", body, token=self.token)[0], 422, body)
        for job in ("inconnu", "a" * 65, "..%2f..", "x.y"):
            self.assertEqual(self.poll(job)[0], 404, job)
        self.assertEqual(self.decide("inconnu", True)[0], 404)


class EndToEndTest(ChatBase):
    """Vrai `llm.ask` avec un modèle simulé : la garde de permissions protège aussi le canal web."""

    def llm(self, *replies):
        from functools import partial
        from jarvis.core import llm
        from test_llm import FakeOllama
        return mock.patch.object(chat_mod, "ask", partial(llm.ask, send=FakeOllama(*replies), gaming=lambda: False))

    def test_action_n2_apres_contenu_externe_jamais_proposee(self):  # injection : un résultat d'outil réclame une action N2
        from test_llm import call, reply
        from jarvis.core import ha
        from jarvis.tools.pc import apps
        with self.llm(reply(call("tv_status")), reply(kill_call()),
                      reply(content="fini")),                 mock.patch.object(ha, "state", return_value={"state": "on", "attributes": {}}),                 mock.patch.object(apps, "_kill") as kill:
            job = self.start()[1]["job"]
            result = self.done(job)
            self.assertEqual(result["answer"], "fini")
            self.assertIsNone(result["pending"])  # aucune confirmation n'a même été demandée
        kill.assert_not_called()
        self.assertIn("contenu externe", str(self.audit.last(20)))

    def test_n2_refuse_ou_approuve_depuis_l_app(self):
        from test_llm import call, reply
        from jarvis.tools.pc import apps
        for approve, expected_calls in ((False, 0), (True, 1)):
            with self.llm(reply(kill_call()), reply(content="terminé")),                     mock.patch.object(apps, "_kill") as kill:
                job = self.start()[1]["job"]
                self.assertEqual(self.decide(self.pending(job)["id"], approve)[0], 200)
                self.assertEqual(self.done(job)["answer"], "terminé")
            self.assertEqual(kill.call_count, expected_calls, approve)
        self.assertIn(f"pwa:{self.device}/llm", str(self.audit.last(30)))


if __name__ == "__main__":
    unittest.main()
