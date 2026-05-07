"""Lightweight runtime UI translation helpers."""

from __future__ import annotations

from functools import lru_cache
import json
import locale
from pathlib import Path
from typing import Iterable


LOCALE_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LANGUAGE = "en"
LANGUAGE_ALIASES = {
    "chinese": "zh",
    "french": "fr",
    "japanese": "ja",
    "korean": "ko",
    "spanish": "es",
    "thai": "th",
    "vietnamese": "vi",
}
CHORD_NAME_TERMS = frozenset(
    {
        "Major",
        "Minor",
        "Power 5",
        "5",
        "6",
        "6/9",
        "7",
        "7#11",
        "7#5",
        "7#5#9",
        "7#5b9",
        "7#9",
        "7#9b13",
        "7alt",
        "7b13",
        "7b5",
        "7b5b9",
        "7b9",
        "7b9b13",
        "7sus4",
        "7sus4b9",
        "7sus4b9b13",
        "9",
        "9#11",
        "9#5",
        "9b5",
        "9sus4",
        "11",
        "13",
        "13#11",
        "13b9",
        "13sus4",
        "add",
        "add9",
        "add11",
        "aug",
        "aug7",
        "dim",
        "dim7",
        "dimMaj7",
        "m6",
        "m6/9",
        "m7",
        "m7add11",
        "m7add13",
        "m7b5",
        "m9",
        "m9b5",
        "m11",
        "m11b5",
        "m13",
        "madd9",
        "madd11",
        "maj7",
        "maj7#5",
        "maj7#11",
        "maj9",
        "maj9#11",
        "maj11",
        "maj13",
        "mMaj7",
        "mMaj9",
        "power",
        "quartal",
        "sus",
        "sus2",
        "sus4",
    }
)


def _available_languages() -> tuple[str, ...]:
    try:
        languages = tuple(sorted(path.stem for path in LOCALE_DIR.glob("*.json") if path.is_file()))
    except OSError:
        languages = ()
    return languages or (DEFAULT_LANGUAGE,)


SUPPORTED_LANGUAGES = _available_languages()


def _normalize_language(language: str | None) -> str:
    code = (language or "").lower().replace("-", "_")
    primary = code.split("_", 1)[0]
    primary = LANGUAGE_ALIASES.get(primary, primary)
    if primary in SUPPORTED_LANGUAGES:
        return primary
    return DEFAULT_LANGUAGE


def current_language() -> str:
    code = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "").lower()
    return _normalize_language(code)


def tr(text: str, language: str | None = None) -> str:
    if text in CHORD_NAME_TERMS:
        return text
    return _language_map(language or current_language()).get(text, text)


def _language_map(language: str) -> dict[str, str]:
    language = _normalize_language(language)
    english_map = _load_language_file(DEFAULT_LANGUAGE)
    if language == DEFAULT_LANGUAGE:
        return english_map
    merged = dict(english_map)
    merged.update(_load_language_file(language))
    return merged


@lru_cache(maxsize=None)
def _load_language_file(language: str) -> dict[str, str]:
    path = LOCALE_DIR / f"{language}.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}


def apply_translations(root, language: str | None = None) -> None:
    lang = language or current_language()
    try:
        from PyQt6.QtGui import QAction
        from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QMenu, QTabWidget, QTextEdit, QWidget
    except Exception:
        return

    widgets: Iterable[QWidget] = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget.toolTip():
            widget.setToolTip(tr(widget.toolTip(), lang))
        if widget.windowTitle():
            widget.setWindowTitle(tr(widget.windowTitle(), lang))
        if isinstance(widget, QLabel) and widget.text():
            widget.setText(tr(widget.text(), lang))
        if isinstance(widget, QAbstractButton) and widget.text():
            widget.setText(tr(widget.text(), lang))
        if isinstance(widget, QLineEdit) and widget.placeholderText():
            widget.setPlaceholderText(tr(widget.placeholderText(), lang))
        if isinstance(widget, QTextEdit) and widget.placeholderText():
            widget.setPlaceholderText(tr(widget.placeholderText(), lang))
        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                widget.setItemText(index, tr(widget.itemText(index), lang))
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                widget.setTabText(index, tr(widget.tabText(index), lang))

    actions = []
    menus = []
    if hasattr(root, "findChildren"):
        actions.extend(root.findChildren(QAction))
        menus.extend(root.findChildren(QMenu))
    for action in actions:
        if action.text():
            action.setText(tr(action.text(), lang))
        if action.toolTip():
            action.setToolTip(tr(action.toolTip(), lang))
    for menu in menus:
        if menu.title():
            menu.setTitle(tr(menu.title(), lang))
        if menu.toolTip():
            menu.setToolTip(tr(menu.toolTip(), lang))
