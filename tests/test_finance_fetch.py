"""Récupération IMAP des rapports : lecture seule, expéditeur = le compte, rapport reconnu, écriture atomique sous nom fixe."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import finance_fetch
from jarvis.tools import mail
from tests.test_finance import report
from tests.test_mail import FakeImap


def mine(raw: bytes, sender="moi") -> bytes:
    return f"From: {sender}\r\n".encode() + raw


class FetchTest(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        (d / "mail.json").write_text(json.dumps({"host": "imap.example.org", "user": "moi"}), encoding="utf-8")
        self.dest = d / "finance"
        FakeImap.calls = []
        FakeImap.mails = [mine(report(39)), mine(report(40)), mine(report(41), "Mallory <m@example.org>"), mine(b"pas un rapport")]
        for p in (mock.patch.object(mail, "CONFIG", d / "mail.json"), mock.patch.object(finance_fetch.imaplib, "IMAP4_SSL", FakeImap),
                  mock.patch.object(finance_fetch, "get_secret", return_value="mdp")):
            p.start()
            self.addCleanup(p.stop)

    def test_nominal_ecrit_les_rapports_du_compte_seulement(self):
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 2)
        self.assertEqual(sorted(f.name for f in self.dest.iterdir()), ["semaine-2026-39.eml", "semaine-2026-40.eml"])
        self.assertIn(("select", "INBOX", True), FakeImap.calls)
        self.assertTrue(all("PEEK" in c[1] for c in FakeImap.calls if c[0] == "fetch"))

    def test_objet_autre_que_depenses_ignore(self):
        veille = report(41).replace("[D=C3=A9penses]".encode(), b"[Veille_IA]")
        FakeImap.mails = [mine(veille)]
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 0)

    def test_recherche_imap_par_mot_entier(self):
        finance_fetch.fetch_reports(self.dest)
        search = next(c for c in FakeImap.calls if c[0] == "search")
        self.assertIn('"Semaine"', search[1:])  # Gmail compare des mots entiers : « penses] » ne trouve rien

    def test_relance_remplace_sans_doublon(self):
        finance_fetch.fetch_reports(self.dest)
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 2)
        self.assertEqual(len(list(self.dest.iterdir())), 2)

    def test_trop_gros_ignore(self):
        FakeImap.mails = [mine(report(40, extra="x" * 200_000))]
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 0)

    def test_date_hors_fenetre_ou_futur_ignoree(self):
        FakeImap.mails = [mine(report(40).replace(b"2026", y)) for y in (b"9999", b"2000")]
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 0)

    def test_dossier_plafonne(self):
        self.dest.mkdir()
        for i in range(finance_fetch.MAX_STORED):
            (self.dest / f"semaine-1999-{i:02}.eml").write_bytes(b"x")
        (self.dest / "autre.eml").write_bytes(b"x")  # hors motif : ne compte pas et n'est jamais supprimé
        self.assertEqual(finance_fetch.fetch_reports(self.dest), 2)  # le plus ancien cède la place, pas de saturation silencieuse
        names = sorted(f.name for f in self.dest.glob("semaine-*.eml"))
        self.assertEqual(len(names), finance_fetch.MAX_STORED)
        self.assertIn("semaine-2026-40.eml", names)
        self.assertTrue((self.dest / "autre.eml").exists())

    def test_adresse_invalide_refusee_sans_connexion(self):
        for user in ('a"b', "a\r\nb", "é@x.org"):
            with mock.patch.object(finance_fetch.mail, "load_config", return_value=("h", user)), self.assertRaises(RuntimeError):
                finance_fetch.fetch_reports(self.dest)
        self.assertEqual(FakeImap.calls, [])

    def test_erreur_disque_sur_un_mail_nempeche_pas_les_autres(self):
        real = finance_fetch.os.replace
        calls = []
        def flaky(a, b):
            calls.append(a)
            if len(calls) == 1:
                raise PermissionError
            return real(a, b)
        with mock.patch.object(finance_fetch.os, "replace", flaky):
            self.assertEqual(finance_fetch.fetch_reports(self.dest), 1)
        self.assertEqual([f.suffix for f in self.dest.iterdir()], [".eml"])

    def test_fetch_mails_generique_pour_la_veille(self):
        from jarvis.core import veille
        from tests.test_veille import issue
        FakeImap.mails = [mine(issue()), mine(issue("[Veille Plugins] Semaine 40 – Top 3")), mine(report(40)),
                          mine(issue("[Veille IA] Semaine 41"), "Mallory <m@example.org>")]
        self.assertEqual(finance_fetch.fetch_mails(self.dest, '"[Veille"', veille.parse, veille.name), 2)
        self.assertEqual(sorted(f.name for f in self.dest.iterdir()), ["veille-actus-2026-40.eml", "veille-plugins-2026-40.eml"])

    def test_mot_de_passe_absent(self):
        with mock.patch.object(finance_fetch, "get_secret", return_value=None), self.assertRaises(RuntimeError):
            finance_fetch.fetch_reports(self.dest)
        self.assertEqual(FakeImap.calls, [])


if __name__ == "__main__":
    unittest.main()
