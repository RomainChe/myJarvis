import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import keyring.errors

from jarvis.core import agentlink as al
from jarvis.core import tools
from jarvis.core.tools import Level, Tool

KEY = "k" * 40


def fake_tool(run, level=Level.N1, **kw):
    return Tool("t", "d", level, {"x": int}, run, **kw)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.t = [1_000_000.0]
        self.replay = al.Replay(lambda: self.t[0])
        self.log = mock.Mock()
        self.registry = {"t": fake_tool(lambda x: {"double": x * 2}), "other": fake_tool(lambda x: x)}
        self.allowed = {"t"}

    def send(self, req, key=KEY, sig=None):
        raw = json.dumps(req).encode()
        return al.handle(KEY, self.replay, raw, al.sign(key, raw, al.REQ) if sig is None else sig, self.registry,
                         self.allowed, __import__("threading").Lock(), self.log)

    def req(self, **kw):
        return {"op": "run", "tool": "t", "args": {"x": 4}, "ts": self.t[0], "nonce": "n" * 32, **kw}


class HandleTest(Fixture):
    def test_nominal(self):
        signed, reply = self.send(self.req())
        self.assertTrue(signed)
        self.assertEqual(reply, {"nonce": "n" * 32, "ok": True, "result": {"double": 8}})
        self.log.assert_called_once_with("run", "t", {"x": 4}, True)

    def test_signature_fausse_ou_corps_trop_gros(self):
        self.assertEqual(self.send(self.req(), key="autre" * 10)[0], False)
        self.assertEqual(self.send(self.req(), sig="")[0], False)
        big = b" " * (al.BODY_MAX + 1)
        self.assertFalse(al.handle(KEY, self.replay, big, al.sign(KEY, big, al.REQ), self.registry, self.allowed, None, self.log)[0])

    def test_rejeu_et_horodatage_perime_refuses(self):
        self.assertTrue(self.send(self.req())[0])
        self.assertFalse(self.send(self.req())[0])  # même nonce
        self.assertFalse(self.send(self.req(nonce="m" * 32, ts=self.t[0] - al.SKEW_S - 1))[0])
        self.assertFalse(self.send(self.req(nonce="short"))[0])

    def test_ts_non_fini_et_requete_anterieure_au_demarrage_refuses(self):
        for ts in (float("nan"), float("inf"), True, self.t[0] - 1):  # -1 : avant le démarrage de l'agent
            self.assertFalse(self.send(self.req(ts=ts, nonce="q" * 32))[0], ts)

    def test_signature_de_requete_ne_vaut_pas_reponse_et_non_ascii(self):
        raw = b"{}"
        self.assertFalse(al.verify(KEY, raw, al.sign(KEY, raw, al.REQ), al.REP))
        self.assertFalse(al.verify(KEY, raw, "é", al.REQ))

    def test_outil_hors_liste_blanche(self):
        signed, reply = self.send(self.req(tool="other"))
        self.assertTrue(signed)
        self.assertFalse(reply["ok"])
        self.log.assert_not_called()

    def test_arguments_invalides_et_erreur_d_outil(self):
        self.assertFalse(self.send(self.req(args={"x": "4"}))[1]["ok"])
        self.registry["t"] = fake_tool(lambda x: 1 / 0)
        reply = self.send(self.req(nonce="p" * 32))[1]
        self.assertFalse(reply["ok"])
        self.assertIn("ZeroDivisionError", reply["error"])

    def test_resultat_non_serialisable(self):
        self.registry["t"] = fake_tool(lambda x: b"octets")
        self.assertFalse(self.send(self.req())[1]["ok"])

    def test_describe_et_secrets_masques_dans_la_trace(self):
        self.registry["t"] = Tool("t", "d", Level.N2, {"x": int}, lambda x: x, describe=lambda x: f"aperçu {x}",
                                  hidden=("x",))
        reply = self.send(self.req(op="describe"))[1]
        self.assertEqual(reply["result"], "aperçu 4")
        self.assertNotEqual(self.log.call_args.args[2], {"x": 4})


class CallTest(Fixture):
    """Client et agent bout en bout, sans réseau."""

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict("os.environ", {al.URL_ENV: "http://100.64.0.9:8788"})
        self.env.start()
        self.addCleanup(self.env.stop)
        p = mock.patch.object(al, "get_secret", return_value=KEY)
        p.start()
        self.addCleanup(p.stop)
        self.tamper = lambda body: body

    def urlopen(self, req, timeout):
        signed, reply = al.handle(KEY, self.replay, req.data, req.headers["X-jarvis-sig"], self.registry, self.allowed,
                                  __import__("threading").Lock(), self.log)
        if not signed:
            raise OSError("401")
        body = self.tamper(json.dumps(reply).encode())

        class R(io.BytesIO):
            headers = {"X-Jarvis-Sig": al.sign(KEY, json.dumps(reply).encode(), al.REP)}

            def __enter__(s):
                return s

            def __exit__(s, *a):
                pass
        return R(body)

    def call(self, **kw):
        return al.call("run", "t", {"x": 5}, urlopen=self.urlopen, **kw)

    def test_aller_retour(self):
        with mock.patch.object(al.time, "time", return_value=self.t[0]):
            self.assertEqual(self.call(), {"double": 10})

    def test_reponse_alteree_refusee(self):
        self.tamper = lambda b: b.replace(b"10", b"99")
        with mock.patch.object(al.time, "time", return_value=self.t[0]), self.assertRaises(al.AgentError):
            self.call()

    def test_pc_injoignable_et_cle_absente(self):
        def down(req, timeout):
            raise ConnectionRefusedError
        with self.assertRaisesRegex(al.AgentError, "injoignable"):
            al.call("run", "t", {}, urlopen=down)
        with mock.patch.object(al, "get_secret", side_effect=keyring.errors.NoKeyringError), \
                self.assertRaisesRegex(al.AgentError, "clé"):
            self.call()
        with mock.patch.object(al, "get_secret", return_value=None), self.assertRaisesRegex(al.AgentError, "clé"):
            self.call()

    def test_url_publique_refusee(self):
        with mock.patch.dict("os.environ", {al.URL_ENV: "http://8.8.8.8:8788"}), self.assertRaises(ValueError):
            al.agent_url()


class ProxyTest(unittest.TestCase):
    def test_enregistrement_et_idempotence(self):
        entry = {"name": "zz_proxy_test", "description": "d", "level": 2, "params": {"path": "str"}, "hidden": [],
                 "describe": True, "private": True, "external": False, "taint_blocked": False, "owner_only": False}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict("os.environ", {al.URL_ENV: "http://localhost:1"}):
            cat = Path(d) / "c.json"
            cat.write_text(json.dumps([entry]))
            self.addCleanup(tools._registry.pop, "zz_proxy_test", None)
            self.assertEqual(al.register_proxies(cat), 1)
            self.assertEqual(al.register_proxies(cat), 0)
            t = tools.REGISTRY["zz_proxy_test"]
            self.assertEqual((t.level, t.params, t.private), (Level.N2, {"path": str}, True))
            with mock.patch.object(al, "call", return_value="résolu") as call:
                self.assertEqual(t.run(path="a"), "résolu")
                self.assertEqual(t.preview({"path": "a"}), "résolu")
            self.assertEqual(call.call_args_list[0].args[0], "run")
            self.assertEqual(call.call_args_list[1].args[0], "describe")

    def test_sans_url_aucun_outil(self):
        with mock.patch.dict("os.environ", {al.URL_ENV: ""}):
            self.assertEqual(al.register_proxies(), 0)

    @unittest.skipUnless(sys.platform == "win32", "outils PC : Windows seulement")
    def test_catalogue_a_jour(self):
        import jarvis.tools.pc  # noqa: F401
        pc = {n for n, t in tools.REGISTRY.items() if t.run.__module__.startswith("jarvis.tools.pc")}
        fresh = {e["name"]: e for e in al.build_catalog(tools.REGISTRY, pc)}
        saved = {e["name"]: e for e in json.loads(al.CATALOG.read_text(encoding="utf-8"))}
        self.assertFalse(pc - saved.keys(), "outil PC absent du catalogue : python -m jarvis.agent catalog")
        for name in fresh:
            self.assertEqual(fresh[name], saved[name], f"{name} a changé : python -m jarvis.agent catalog")


if __name__ == "__main__":
    unittest.main()
