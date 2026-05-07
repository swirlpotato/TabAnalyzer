import os
import json
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QTabWidget, QTextEdit, QWidget

from tab_analyzer import i18n
from tab_analyzer.i18n import LOCALE_DIR, SUPPORTED_LANGUAGES, apply_translations, current_language, tr


def _locale(language: str) -> dict[str, str]:
    return json.loads((LOCALE_DIR / f"{language}.json").read_text(encoding="utf-8"))


class I18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_supported_languages_include_requested_locales(self):
        self.assertEqual(set(SUPPORTED_LANGUAGES), {"ko", "ja", "zh", "fr", "en", "es", "th", "vi"})
        self.assertEqual({path.stem for path in LOCALE_DIR.glob("*.json")}, set(SUPPORTED_LANGUAGES))
        self.assertFalse(hasattr(i18n, "_TRANSLATIONS"))

    def test_missing_language_falls_back_to_english(self):
        self.assertEqual(tr("Play", "de"), "Play")

    def test_source_language_uses_language_file(self):
        ko = _locale("ko")
        self.assertEqual(tr("Play", "ko"), ko["Play"])
        self.assertEqual(tr("File", "ko"), ko["File"])
        self.assertEqual(tr("Open", "ko"), ko["Open"])

    def test_windows_korean_locale_maps_to_ko(self):
        with patch("locale.getlocale", return_value=("Korean_Korea", "949")):
            self.assertEqual(current_language(), "ko")

    def test_supported_language_uses_language_file(self):
        self.assertEqual(tr("Play", "ja"), _locale("ja")["Play"])

    def test_apply_translations_updates_common_widgets(self):
        ko = _locale("ko")
        root = QWidget()
        label = QLabel("Speed", root)
        button = QPushButton("Play", root)
        button.setToolTip("Play")
        editor = QTextEdit(root)
        editor.setPlaceholderText("Markdown memo")
        tabs = QTabWidget(root)
        tabs.addTab(QWidget(), "Tab player")

        apply_translations(root, "ko")

        self.assertEqual(label.text(), ko["Speed"])
        self.assertEqual(button.text(), ko["Play"])
        self.assertEqual(button.toolTip(), ko["Play"])
        self.assertEqual(editor.placeholderText(), ko["Markdown memo"])
        self.assertEqual(tabs.tabText(0), ko["Tab player"])

    def test_apply_translations_updates_menu_titles(self):
        ko = _locale("ko")
        root = QWidget()
        menu = QMenu("Manual", root)

        apply_translations(root, "ko")

        self.assertEqual(menu.title(), ko["Manual"])

    def test_apply_translations_updates_korean_menu_titles(self):
        ko = _locale("ko")
        root = QWidget()
        menu = QMenu("File", root)

        apply_translations(root, "ko")

        self.assertEqual(menu.title(), ko["File"])


if __name__ == "__main__":
    unittest.main()
