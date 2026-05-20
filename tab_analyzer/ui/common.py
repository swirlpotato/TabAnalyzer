"""Shared Qt imports, constants, and helpers for the UI package."""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import traceback
import wave
import json
import zipfile
import html
from datetime import datetime
from fractions import Fraction
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import pi, sin
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import Iterable, NamedTuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from PyQt6.QtCore import QElapsedTimer, QEvent, QObject, QPoint, QPointF, QRect, QSize, QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

try:  # QtMultimedia can be unavailable on some minimal Python installs.
    from PyQt6.QtMultimedia import (
        QAudioInput,
        QAudioOutput,
        QMediaCaptureSession,
        QMediaDevices,
        QMediaFormat,
        QMediaPlayer,
        QMediaRecorder,
    )
except Exception:  # noqa: BLE001 - UI shows a graceful recording-unavailable state.
    QAudioInput = None
    QAudioOutput = None
    QMediaCaptureSession = None
    QMediaDevices = None
    QMediaFormat = None
    QMediaPlayer = None
    QMediaRecorder = None

from ..analysis import (
    Candidate,
    SCALE_PATTERNS,
    candidate_display_label,
    candidate_display_name,
    interval_name,
    pitch_class_name,
)
from ..chord_positions import (
    CHORD_POSITION_CATEGORIES,
    ChordPosition,
    MAX_CHORD_POSITIONS,
    MAX_DISPLAY_FRET,
    MAX_FRET_SPAN,
    MUTED,
    chord_position_display_name,
    filter_chord_positions,
    generate_chord_positions,
    group_chord_positions_by_category,
)
from ..chord_finder import (
    CHORD_FINDER_TYPES,
    ChordMatch,
    find_chords_by_filter,
    find_chords_containing_pitches,
)
from ..gp_loader import MeasureData, SegmentData, SongData, default_track_index, list_tracks, load_gp_file, retune_song
from ..i18n import apply_translations, current_language, tr
from ..midi_player import MidiOutput, TICKS_PER_QUARTER, TabMidiPlayer
from ..scale_blocks import (
    ScaleBlock,
    ScaleBlockUsage,
    ScaleSpan,
    dedupe_repeated_pitch_positions,
    generate_scale_position_blocks,
    infer_preferred_scale,
    infer_scale_blocks,
    infer_song_scale_block_usages,
    scale_block_spans,
)
from ..songsterr import (
    COOKIE_STORE_PATH,
    SONGSTERR_BASE_URL,
    SongsterrAuthError,
    SongsterrError,
    details_path_for_gp,
    download_guitar_pro,
    load_details_file,
    load_cookie_header,
    save_details_file,
    save_cookie_header,
    search_tabs,
    selected_measure_range_from_details,
    songsterr_page_url,
    update_selected_measure_range,
    update_youtube_default_video,
    update_youtube_sync_offset,
)
from ..theory import TheoryExplainer
from ..tunings import TuningPreset, load_tuning_presets
from ..version import __version__
from ..youtube_sync import (
    AUTO_SYNC_MAX_PLAY_SECONDS,
    AUTO_SYNC_MIN_PLAY_SECONDS,
    AUTO_SYNC_PRE_ROLL_SECONDS,
    AUTO_SYNC_SEARCH_RADIUS_SECONDS,
    AUTO_SYNC_TARGET_PLAY_SECONDS,
    SYNC_STEP_MS,
    SyncEstimate,
    YouTubeSyncError,
    capture_system_audio,
    estimate_sync_offset,
    round_sync_milliseconds,
    song_seconds_for_ticks,
    ticks_for_song_seconds,
)
from .chord_search import (
    MAX_CHORD_FINDER_RESULTS,
    _ChordFinderSearchParams,
    _ChordFinderSearchResult,
    _ChordFinderSearchWorker,
    _chord_finder_search_results,
)
from .icons import _delete_recording_icon, _draw_post_it_icon, _icon_button, _player_icon, _post_it_icon_rect
from .memo_io import (
    _legacy_memo_path_for_tab,
    _measure_note_text,
    _memo_autosave_path,
    _memo_path_for_tab,
    _read_memo_package,
    _render_markdown_preview,
    _write_memo_package,
)
from .youtube import (
    YOUTUBE_VIEW_HEIGHT,
    YOUTUBE_VIEW_PIP_MARGIN,
    YOUTUBE_VIEW_WIDTH,
    _allow_qt_webengine_autoplay,
    _make_youtube_view_non_interactive,
    _set_webengine_autoplay_allowed,
    _set_youtube_view_size,
    _youtube_player_html,
    _youtube_player_url,
    _youtube_video_candidates,
)
from .tuner import ChromaticTunerDialog
from .vst_host import VstHostDialog


PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent.parent
SONGSTERR_DOWNLOAD_DIR = PROJECT_ROOT_PATH / "Downloads"
RECENT_FILES_PATH = COOKIE_STORE_PATH.with_name("recent_files.json")
MAX_RECENT_FILES = 10
ABOUT_URL = "https://github.com/swirlpotato/TabAnalyzer"
SONGSTERR_AD_HOST_SUFFIXES = (
    "2mdn.net",
    "aaxads.com",
    "adform.net",
    "adnxs.com",
    "adsafeprotected.com",
    "adsrvr.org",
    "amazon-adsystem.com",
    "casalemedia.com",
    "criteo.com",
    "criteo.net",
    "doubleclick.net",
    "googlesyndication.com",
    "googletagmanager.com",
    "googletagservices.com",
    "lijit.com",
    "media.net",
    "moatads.com",
    "openx.net",
    "outbrain.com",
    "pubmatic.com",
    "quantserve.com",
    "rubiconproject.com",
    "scorecardresearch.com",
    "smartadserver.com",
    "taboola.com",
    "yieldmo.com",
)
SONGSTERR_AD_HOSTS = {
    "adservice.google.com",
    "fundingchoicesmessages.google.com",
    "imasdk.googleapis.com",
}


def _is_songsterr_ad_request_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    if not normalized:
        return False
    if normalized in SONGSTERR_AD_HOSTS:
        return True
    return any(normalized == suffix or normalized.endswith(f".{suffix}") for suffix in SONGSTERR_AD_HOST_SUFFIXES)


def _trf(template: str, **values: object) -> str:
    return tr(template).format(**values)


def _about_html(version: str, url: str = ABOUT_URL) -> str:
    text = _trf("Tab Analyzer\n\nVersion: {version}\n{url}", version=version, url=url)
    escaped_text = html.escape(text).replace("\n", "<br>")
    escaped_url = html.escape(url)
    link = f'<a href="{html.escape(url, quote=True)}">{escaped_url}</a>'
    return f'<div style="font-size: 12pt;">{escaped_text.replace(escaped_url, link)}</div>'


def _open_external_url(url: QUrl | str) -> bool:
    target = url if isinstance(url, QUrl) else QUrl(str(url))
    return QDesktopServices.openUrl(target)


MAX_DISPLAY_CANDIDATES = 12
CHORD_DEGREE_LABELS = {
    0: "1",
    1: "b2",
    2: "2",
    3: "b3",
    4: "3",
    5: "4",
    6: "b5",
    7: "5",
    8: "b6",
    9: "6",
    10: "b7",
    11: "7",
}

SCALE_POSITION_ROOT_OPTIONS = (
    (0, "C"),
    (1, "C#/Db"),
    (2, "D"),
    (3, "D#/Eb"),
    (4, "E"),
    (5, "F"),
    (6, "F#/Gb"),
    (7, "G"),
    (8, "G#/Ab"),
    (9, "A"),
    (10, "A#/Bb"),
    (11, "B"),
)

SCALE_POSITION_ORDER = (
    "major",
    "natural minor",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "locrian",
    "harmonic minor",
    "melodic minor",
    "phrygian dominant",
    "major pentatonic",
    "minor pentatonic",
    "blues",
    "major blues",
)

SCALE_POSITION_PATTERN_BY_NAME = dict(SCALE_PATTERNS)
SCALE_POSITION_PATTERNS = tuple(
    (name, SCALE_POSITION_PATTERN_BY_NAME[name])
    for name in SCALE_POSITION_ORDER
    if name in SCALE_POSITION_PATTERN_BY_NAME
)[:50]
SCALE_POSITION_DISPLAY_NAMES = {
    "natural minor": "minor (natural minor)",
}
SCALE_POSITION_ROOT_LABELS = dict(SCALE_POSITION_ROOT_OPTIONS)
DEFAULT_FINDER_STRING_PITCHES_HIGH_TO_LOW = (64, 59, 55, 50, 45, 40)
DEFAULT_FINDER_FRET_COUNT = 24


def fretboard_string_label(midi_note: int, string_index: int, prefer_flats: bool | None) -> str:
    name = pitch_class_name(midi_note % 12, prefer_flats)
    if string_index == 0 and name:
        return name[0].lower() + name[1:]
    return name


def tab_note_text(note) -> str:
    if getattr(note, "is_muted", False):
        return "x"
    text = str(note.fret)
    if "ghost_note" in getattr(note, "techniques", ()):
        return f"({text})"
    return text


class _MeasureLayout(NamedTuple):
    index: int
    rect: QRect


class _CandidateHit(NamedTuple):
    rect: QRect
    measure_index: int
    candidate: Candidate
    kind: str
    segment: SegmentData | None


class _MemoIconHit(NamedTuple):
    rect: QRect
    measure_index: int


APP_ICON_PATH = PROJECT_ROOT_PATH / "assets" / "app_icon.png"


def _recent_files_store_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else RECENT_FILES_PATH


def _normalized_recent_file_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def load_recent_files(path: str | Path | None = None) -> tuple[Path, ...]:
    store_path = _recent_files_store_path(path)
    if not store_path.exists():
        return ()
    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    raw_files = data.get("files") if isinstance(data, dict) else data
    if not isinstance(raw_files, list):
        return ()

    files: list[Path] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, str) or not item.strip():
            continue
        recent_path = _normalized_recent_file_path(item)
        key = str(recent_path).casefold()
        if key in seen:
            continue
        seen.add(key)
        files.append(recent_path)
        if len(files) >= MAX_RECENT_FILES:
            break
    return tuple(files)


def save_recent_files(files: Iterable[str | Path], path: str | Path | None = None) -> Path:
    store_path = _recent_files_store_path(path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in files:
        recent_path = _normalized_recent_file_path(item)
        key = str(recent_path).casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(str(recent_path))
        if len(normalized) >= MAX_RECENT_FILES:
            break
    store_path.write_text(json.dumps({"files": normalized}, ensure_ascii=False, indent=2), encoding="utf-8")
    return store_path


def add_recent_file(file_path: str | Path, path: str | Path | None = None) -> tuple[Path, ...]:
    recent_path = _normalized_recent_file_path(file_path)
    existing = [item for item in load_recent_files(path) if str(item).casefold() != str(recent_path).casefold()]
    updated = (recent_path, *existing)
    save_recent_files(updated, path)
    return tuple(updated[:MAX_RECENT_FILES])


def remove_recent_file(file_path: str | Path, path: str | Path | None = None) -> tuple[Path, ...]:
    recent_path = _normalized_recent_file_path(file_path)
    updated = tuple(item for item in load_recent_files(path) if str(item).casefold() != str(recent_path).casefold())
    save_recent_files(updated, path)
    return updated


APP_ICON_ICO_PATH = PROJECT_ROOT_PATH / "assets" / "app_icon.ico"
MANUAL_PATH = PROJECT_ROOT_PATH / "docs" / "manual.html"
MANUAL_EN_PATH = PROJECT_ROOT_PATH / "docs" / "manual_en.html"
def _mix_metronome_clicks_into_wav(path: Path, bpm: int, beats_per_bar: int) -> bool:
    if not path.exists():
        return False
    try:
        with wave.open(str(path), "rb") as source:
            params = source.getparams()
            frames = bytearray(source.readframes(source.getnframes()))
    except (OSError, wave.Error):
        return False
    if params.sampwidth != 2 or params.framerate <= 0 or params.nchannels <= 0:
        return False

    frame_count = params.nframes
    interval = 60.0 / max(40, min(250, bpm))
    click_length = max(1, int(params.framerate * 0.055))
    beat_index = 0
    position_seconds = 0.0
    while int(position_seconds * params.framerate) < frame_count:
        start_frame = int(position_seconds * params.framerate)
        frequency = 1560 if beat_index == 0 else 1040
        amplitude = 7600 if beat_index == 0 else 5200
        for offset in range(click_length):
            frame = start_frame + offset
            if frame >= frame_count:
                break
            envelope = 1.0 - (offset / click_length)
            sample = int(sin((2 * pi * frequency * offset) / params.framerate) * amplitude * envelope)
            for channel in range(params.nchannels):
                byte_index = ((frame * params.nchannels) + channel) * params.sampwidth
                current = int.from_bytes(frames[byte_index : byte_index + 2], "little", signed=True)
                mixed = max(-32768, min(32767, current + sample))
                frames[byte_index : byte_index + 2] = int(mixed).to_bytes(2, "little", signed=True)
        beat_index = (beat_index + 1) % max(1, beats_per_bar)
        position_seconds += interval

    try:
        with wave.open(str(path), "wb") as target:
            target.setparams(params)
            target.writeframes(bytes(frames))
    except (OSError, wave.Error):
        return False
    return True


__all__ = [
    name
    for name in globals()
    if name == "__version__" or not (name.startswith("__") and name.endswith("__"))
]
