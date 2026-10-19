import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jarvis.core import devices
from jarvis.core.devices import TOKEN_TTL_S, Devices


class TokenTtl(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = Devices(str(Path(self.dir.name) / "d.db"))
        self.t = 1_000_000.0
        patch = mock.patch.object(devices, "_now", lambda: self.t)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(self.d.db.close)

    def enroll(self, name="tel"):
        return self.d.enroll(self.d.new_code(), name)

    def test_usage_renouvelle_la_duree(self):
        id_, token = self.enroll()
        self.t += TOKEN_TTL_S - 1
        token = self.d.rotate(id_, token)  # D6 : la durée se renouvelle par rotation du token, pas par simple usage
        self.t += TOKEN_TTL_S - 1
        self.assertIsNotNone(self.d.check(token))

    def test_inutilise_90_jours_refuse(self):
        _, token = self.enroll()
        self.t += TOKEN_TTL_S + 1
        self.assertIsNone(self.d.check(token))

    def test_revoke_all(self):
        _, a = self.enroll("a")
        _, b = self.enroll("b")
        self.assertEqual(self.d.revoke_all(), 2)
        self.assertIsNone(self.d.check(a))
        self.assertIsNone(self.d.check(b))
        self.assertEqual(self.d.revoke_all(), 0)


if __name__ == "__main__":
    unittest.main()
