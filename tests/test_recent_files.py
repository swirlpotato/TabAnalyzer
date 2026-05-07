import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tab_analyzer.ui import (
    MAX_RECENT_FILES,
    TabAnalyzerWindow,
    add_recent_file,
    load_recent_files,
    remove_recent_file,
    save_recent_files,
)


class RecentFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_recent_files_are_saved_deduped_and_limited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "recent_files.json"
            files = [Path(temp_dir) / f"song-{index}.gp" for index in range(12)]

            save_recent_files(files, store)

            loaded = load_recent_files(store)
            self.assertEqual(len(loaded), MAX_RECENT_FILES)
            self.assertEqual(loaded[0], files[0].resolve(strict=False))

    def test_add_recent_file_moves_existing_path_to_top(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "recent_files.json"
            first = Path(temp_dir) / "first.gp"
            second = Path(temp_dir) / "second.gp"

            save_recent_files((first, second), store)
            updated = add_recent_file(second, store)

            self.assertEqual(updated[0], second.resolve(strict=False))
            self.assertEqual(len(updated), 2)

    def test_remove_recent_file_updates_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "recent_files.json"
            first = Path(temp_dir) / "first.gp"
            second = Path(temp_dir) / "second.gp"
            save_recent_files((first, second), store)

            updated = remove_recent_file(first, store)

            self.assertEqual(updated, (second.resolve(strict=False),))
            self.assertEqual(load_recent_files(store), updated)

    def test_recent_files_menu_is_under_open_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Path(temp_dir) / "recent_files.json"
            save_recent_files((Path(temp_dir) / "song.gp",), store)
            with patch("tab_analyzer.ui.RECENT_FILES_PATH", store):
                window = TabAnalyzerWindow()
                try:
                    file_menu = window.menuBar().actions()[0].menu()

                    self.assertIs(file_menu.actions()[1].menu(), window.recent_files_menu)
                    self.assertIn("song.gp", window.recent_files_menu.actions()[0].text())
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
