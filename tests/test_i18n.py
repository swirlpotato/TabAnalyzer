import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QTabWidget, QWidget

from tab_analyzer import i18n
from tab_analyzer.i18n import LOCALE_DIR, SUPPORTED_LANGUAGES, apply_translations, current_language, tr


class I18nTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_supported_languages_include_requested_locales(self):
        self.assertEqual(set(SUPPORTED_LANGUAGES), {"ko", "ja", "zh", "fr", "en", "es", "th", "vi"})
        self.assertEqual({path.stem for path in LOCALE_DIR.glob("*.json")}, set(SUPPORTED_LANGUAGES))
        self.assertFalse(hasattr(i18n, "_TRANSLATIONS"))

    def test_missing_language_falls_back_to_english(self):
        self.assertEqual(tr("재생", "de"), "Play")

    def test_source_language_uses_language_file(self):
        self.assertEqual(tr("재생", "ko"), "재생")
        self.assertEqual(tr("File", "ko"), "파일")
        self.assertEqual(tr("Open", "ko"), "열기")

    def test_windows_korean_locale_maps_to_ko(self):
        with patch("locale.getlocale", return_value=("Korean_Korea", "949")):
            self.assertEqual(current_language(), "ko")

    def test_supported_language_uses_language_file(self):
        self.assertEqual(tr("재생", "ja"), "再生")

    def test_apply_translations_updates_common_widgets(self):
        root = QWidget()
        label = QLabel("속도", root)
        button = QPushButton("재생", root)
        tabs = QTabWidget(root)
        tabs.addTab(QWidget(), "타브 플레이어")

        apply_translations(root, "en")

        self.assertEqual(label.text(), "Speed")
        self.assertEqual(button.text(), "Play")
        self.assertEqual(tabs.tabText(0), "Tab player")

    def test_apply_translations_updates_menu_titles(self):
        root = QWidget()
        menu = QMenu("매뉴얼", root)

        apply_translations(root, "en")

        self.assertEqual(menu.title(), "Manual")

    def test_apply_translations_updates_korean_menu_titles(self):
        root = QWidget()
        menu = QMenu("File", root)

        apply_translations(root, "ko")

        self.assertEqual(menu.title(), "파일")


if __name__ == "__main__":
    unittest.main()
