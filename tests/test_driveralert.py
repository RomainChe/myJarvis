"""Alerte push des pilotes : une notification par version, seulement pour les pilotes importants."""
import tempfile
import unittest
from pathlib import Path

from jarvis.core import driveralert


def drv(id_="oem51.inf", latest="1.0", category="DISPLAY", status="moderate", newer=True, ignored=False):
    return {"id": id_, "latest": latest, "category": category, "status": status, "newer": newer, "ignored": ignored}


class DriverAlert(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "sub" / "alert.json"
        self.calls = []

    def run_check(self, *drivers):
        return driveralert.check({"drivers": list(drivers)}, lambda: self.calls.append(1), self.state)

    def test_meme_version_une_seule_notification(self):
        self.assertEqual(self.run_check(drv()), 1)
        self.assertEqual(self.run_check(drv()), 0)
        self.assertEqual(len(self.calls), 1)

    def test_nouvelle_version_renotifie(self):
        self.run_check(drv())
        self.assertEqual(self.run_check(drv(latest="2.0")), 1)
        self.assertEqual(len(self.calls), 2)

    def test_pilotes_non_importants_ignores(self):
        self.assertEqual(self.run_check(drv(category="MEDIA"), drv(status="ok"), drv(newer=False), drv(ignored=True)), 0)
        self.assertEqual(self.calls, [])

    def test_echec_du_push_renotifie_au_tour_suivant(self):
        def boom():
            raise OSError
        with self.assertRaises(OSError):
            driveralert.check({"drivers": [drv()]}, boom, self.state)
        self.assertEqual(self.run_check(drv()), 1)

    def test_etat_corrompu(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("[1]")
        self.assertEqual(self.run_check(drv()), 1)

    def test_relevé_vide(self):
        self.assertEqual(driveralert.check({}, lambda: self.calls.append(1), self.state), 0)


if __name__ == "__main__":
    unittest.main()
