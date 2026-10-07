import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from jarvis.core.permissions import Refused
from jarvis.core.tools import REGISTRY, Level
from jarvis.tools.pc import screenshot
from pcbase import PcBase, no, yes

# 2 x 2 pixels BGRA : rouge, vert / bleu, blanc
PIXELS = bytes([0, 0, 255, 255, 0, 255, 0, 255, 255, 0, 0, 255, 255, 255, 255, 255])


class ScreenshotTest(PcBase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name, "Jarvis")
        patcher = mock.patch.object(screenshot, "SHOT_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_niveau_et_drapeau(self):
        tool = REGISTRY["screenshot"]
        self.assertEqual(tool.level, Level.N2)
        self.assertTrue(tool.private)

    def test_png_valide(self):
        png = screenshot._png(2, 2, PIXELS)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        pos, chunks = 8, {}
        while pos < len(png):
            size, kind = struct.unpack(">I4s", png[pos:pos + 8])
            data = png[pos + 8:pos + 8 + size]
            self.assertEqual(struct.unpack(">I", png[pos + 8 + size:pos + 12 + size])[0], zlib.crc32(kind + data))
            chunks[kind] = data
            pos += 12 + size
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[b"IHDR"]), (2, 2, 8, 2, 0, 0, 0))
        self.assertEqual(zlib.decompress(chunks[b"IDAT"]),
                         b"\0" + bytes([255, 0, 0, 0, 255, 0]) + b"\0" + bytes([0, 0, 255, 255, 255, 255]))

    def test_nominal_ecrit_un_png_sans_journaliser_le_chemin(self):
        with mock.patch.object(screenshot, "_capture", return_value=(2, 2, PIXELS)):
            result = self.run_tool("screenshot", confirm=yes)
        path = Path(result["path"])
        self.assertEqual(path.parent, self.dir)
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(result["bytes"], path.stat().st_size)
        self.assertNotIn(str(path), " ".join(str(row) for row in self.audit.last(5)))

    def test_ne_remplace_jamais_un_fichier(self):
        self.dir.mkdir(parents=True)
        with mock.patch.object(screenshot, "_capture", return_value=(2, 2, PIXELS)), \
                mock.patch.object(screenshot, "datetime") as clock:
            clock.now.return_value = __import__("datetime").datetime(2026, 1, 1, 12, 0, 0)
            self.run_tool("screenshot", confirm=yes)
            with self.assertRaises(FileExistsError):
                self.run_tool("screenshot", confirm=yes)

    def test_entree_invalide(self):
        with mock.patch.object(screenshot, "_capture") as capture:
            with self.assertRaises(ValueError):
                self.run_tool("screenshot", {"monitor": 1}, confirm=yes)
        capture.assert_not_called()

    def test_capture_reelle_en_memoire_seulement(self):
        try:
            w, h, pixels = screenshot._capture()
        except OSError:
            self.skipTest("pas de bureau interactif")
        self.assertEqual(len(pixels), w * h * 4)

    def _calls_gdi(self, bitblt_ok=True):
        gdi, user = mock.MagicMock(), mock.MagicMock()
        user.GetSystemMetrics.side_effect = [0, 0, 2, 2]
        gdi.SelectObject.return_value = 99
        gdi.BitBlt.return_value = bitblt_ok
        with mock.patch.object(screenshot, "_g32", gdi), mock.patch.object(screenshot, "_u32", user):
            try:
                screenshot._capture()
            except OSError:
                pass
        wanted = {"SelectObject", "GetDIBits", "DeleteObject", "DeleteDC"}
        return [(c[0], c[1][1] if c[0] == "SelectObject" else None) for c in gdi.mock_calls if c[0] in wanted]

    def test_bitmap_deselectionne_avant_getdibits_et_suppression(self):
        """S4 : SelectObject(ancien) -> GetDIBits -> DeleteObject(bitmap) -> DeleteDC."""
        calls = self._calls_gdi()
        names = [n for n, _ in calls]
        self.assertEqual(names[-4:], ["SelectObject", "GetDIBits", "DeleteObject", "DeleteDC"])
        self.assertEqual(calls[-4][1], 99)  # l'ancien objet du DC

    def test_bitmap_deselectionne_meme_si_bitblt_echoue(self):
        names = [n for n, _ in self._calls_gdi(bitblt_ok=False)]
        self.assertEqual(names[-3:], ["SelectObject", "DeleteObject", "DeleteDC"])
        self.assertNotIn("GetDIBits", names)

    def test_captures_repetees_ne_fuient_pas_d_objets_gdi(self):
        """S4 : le bitmap doit être désélectionné avant DeleteObject, sinon il fuit à chaque capture."""
        import ctypes
        user32, gdi_objects = ctypes.WinDLL("user32"), 0  # GR_GDIOBJECTS
        process = ctypes.WinDLL("kernel32").GetCurrentProcess()
        try:
            screenshot._capture()
        except OSError:
            self.skipTest("pas de bureau interactif")
        before = user32.GetGuiResources(process, gdi_objects)
        for _ in range(20):
            screenshot._capture()
        self.assertLess(user32.GetGuiResources(process, gdi_objects) - before, 5)

    def test_sans_confirmation_rien_n_est_capture(self):
        with mock.patch.object(screenshot, "_capture") as capture:
            with self.assertRaises(Refused):
                self.run_tool("screenshot", confirm=no)
        capture.assert_not_called()
        self.assertFalse(self.dir.exists())


if __name__ == "__main__":
    unittest.main()
