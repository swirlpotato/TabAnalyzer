from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from tab_analyzer.ui import _read_memo_package, _write_memo_package
except Exception as exc:  # noqa: BLE001 - UI helpers require PyQt6 in the test environment.
    raise unittest.SkipTest(f"PyQt6 UI helpers unavailable: {exc}") from exc


class MemoPackageTests(unittest.TestCase):
    def test_mmdx_stores_each_measure_as_its_own_markdown_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "outside.png"
            image.write_bytes(b"fake image")
            package = root / "memo_song.mmdx"

            _write_memo_package(
                package,
                root / "song.gp5",
                {
                    1: f"Opening note\n\n## M26\nThis is normal memo text.\n\n![pick]({image})",
                    25: "Measure 25 memo",
                },
                (root,),
            )

            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("M1.md", names)
                self.assertIn("M25.md", names)
                self.assertNotIn("M26.md", names)
                self.assertTrue(any(name.startswith("M1_outside") for name in names))
                self.assertIn("## M26", archive.read("M1.md").decode("utf-8"))

            loaded = _read_memo_package(package)
            self.assertIn("## M26", loaded[1])
            self.assertEqual(loaded[25], "Measure 25 memo")


if __name__ == "__main__":
    unittest.main()
