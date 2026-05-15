"""PyQt6 user interface for the tab analyzer."""

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
    download_guitar_pro,
    load_details_file,
    load_cookie_header,
    save_details_file,
    save_cookie_header,
    search_tabs,
    songsterr_page_url,
    update_youtube_default_video,
    update_youtube_sync_offset,
)
from ..theory import TheoryExplainer
from ..tunings import TuningPreset, load_tuning_presets
from ..version import __version__
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


class AnalysisProgressDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        window_title: str = "Analyzing",
        title_prefix: str = "Analyzing",
        initial_detail: str = "Preparing the file.",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(window_title))
        self.setModal(True)
        self.setFixedSize(340, 132)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._title_prefix = tr(title_prefix)
        self.title_label = QLabel(f"{self._title_prefix}... 0%")
        self.detail_label = QLabel(tr(initial_detail))
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self._busy_limit = 90

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        title_font = QFont("Segoe UI", 12, QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setStyleSheet("color: #596579;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.detail_label)

        self._timer = QTimer(self)
        self._timer.setInterval(650)
        self._timer.timeout.connect(self._advance_busy_progress)
        self._timer.start()

    def set_progress(self, value: int, detail: str) -> None:
        value = max(0, min(100, int(value)))
        if value < self.progress_bar.value() and value < 100:
            value = self.progress_bar.value()
        self.progress_bar.setValue(value)
        self.title_label.setText(f"{self._title_prefix}... {value}%")
        if detail:
            self.detail_label.setText(tr(detail))
        if value >= 100:
            self._timer.stop()

    def _advance_busy_progress(self) -> None:
        value = self.progress_bar.value()
        if value <= 0 or value >= self._busy_limit:
            return
        next_value = min(self._busy_limit, value + 10)
        self.progress_bar.setValue(next_value)
        self.title_label.setText(f"{self._title_prefix}... {next_value}%")


class _LoadWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: Path, track_index: int | None, include_tracks: bool) -> None:
        super().__init__()
        self.path = path
        self.track_index = track_index
        self.include_tracks = include_tracks

    def run(self) -> None:
        try:
            if self.include_tracks:
                self.progress.emit(10, "Reading file information.")
                tracks = list_tracks(self.path)
                self.progress.emit(30, "Finding guitar tracks.")
                selected_track = default_track_index(self.path)
                self.progress.emit(40, "Analyzing tabs and notes.")
                song = load_gp_file(self.path, track_index=selected_track)
                self.progress.emit(90, "Preparing analysis results.")
                self.finished.emit(("file", self.path, tracks, selected_track, song))
                return

            track_index = int(self.track_index or 0)
            self.progress.emit(10, "Preparing the selected track.")
            self.progress.emit(30, "Analyzing tabs and notes.")
            song = load_gp_file(self.path, track_index=track_index)
            self.progress.emit(90, "Preparing analysis results.")
            self.finished.emit(("track", self.path, None, track_index, song))
        except Exception as exc:  # noqa: BLE001 - relay parser/load errors to the UI thread.
            self.failed.emit(str(exc))


class _SongsterrWorker(QObject):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    authFailed = pyqtSignal()

    def __init__(self, mode: str, *, query: str = "", result: object | None = None, cookie: str | None = None) -> None:
        super().__init__()
        self.mode = mode
        self.query = query
        self.result = result
        self.cookie = cookie

    def run(self) -> None:
        try:
            if self.mode == "search":
                self.progress.emit(15, "Searching songs on Songsterr.")
                results = search_tabs(self.query)
                self.progress.emit(90, "Preparing search results.")
                self.finished.emit(("search", self.query, results))
                return

            if self.result is None:
                raise SongsterrError("No Songsterr song was selected for download.")
            self.progress.emit(15, "Requesting the Guitar Pro file from Songsterr.")
            path = download_guitar_pro(
                self.result,
                SONGSTERR_DOWNLOAD_DIR,
                cookie=self.cookie,
            )
            self.progress.emit(90, "Preparing the downloaded file.")
            self.finished.emit(("download", self.result, path))
        except SongsterrAuthError:
            self.authFailed.emit()
        except SongsterrError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - network/backend errors should be visible in the UI.
            self.failed.emit(str(exc))


class TabCanvas(QWidget):
    selectionChanged = pyqtSignal(object, object, str, object)
    memoClicked = pyqtSignal(int)
    zoomWheelRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.zoom = 1.0
        self.selected_measure_index: int | None = None
        self.selected_segment: SegmentData | None = None
        self.selected_candidate: Candidate | None = None
        self.selected_kind = "scale"
        self._measure_layouts: list[_MeasureLayout] = []
        self._candidate_hits: list[_CandidateHit] = []
        self._memo_icon_hits: list[_MemoIconHit] = []
        self._memo_measure_numbers: set[int] = set()
        self._content_height = 320
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(960, max(320, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_measure_index = None
        self.selected_segment = None
        self.selected_candidate = None
        self._rebuild_layout()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.65, min(2.4, zoom))
        self._rebuild_layout()
        self.update()

    def set_memo_measure_numbers(self, measure_numbers: set[int]) -> None:
        self._memo_measure_numbers = set(measure_numbers)
        self.update()

    def set_selected_measure_index(self, measure_index: int, emit: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            return
        measure_index = max(0, min(measure_index, len(self.song.track.measures) - 1))
        measure = self.song.track.measures[measure_index]
        candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
        self.selected_measure_index = measure_index
        self.selected_candidate = candidate
        self.selected_kind = "scale"
        self.selected_segment = None
        if emit:
            self.selectionChanged.emit(measure, candidate, "scale", None)
        self.update()

    def layout_for_measure(self, measure_index: int) -> _MeasureLayout | None:
        for layout in self._measure_layouts:
            if layout.index == measure_index:
                return layout
        return None

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None:
            return
        position = event.position().toPoint()

        for hit in reversed(self._memo_icon_hits):
            if hit.rect.contains(position):
                measure = self.song.track.measures[hit.measure_index]
                candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
                self._select(hit.measure_index, candidate, "scale", None)
                self.memoClicked.emit(hit.measure_index)
                return

        for hit in reversed(self._candidate_hits):
            if hit.rect.contains(position):
                self._select(hit.measure_index, hit.candidate, hit.kind, hit.segment)
                return

        for layout in self._measure_layouts:
            if layout.rect.contains(position):
                measure = self.song.track.measures[layout.index]
                candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
                self._select(layout.index, candidate, "scale", None)
                return

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoomWheelRequested.emit(10 if delta > 0 else -10)
                event.accept()
                return
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))
        self._candidate_hits = []
        self._memo_icon_hits = []

        if self.song is None:
            self._draw_empty(painter)
            return

        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            self._draw_measure(painter, layout, measure)

    def _select(
        self,
        measure_index: int,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None,
    ) -> None:
        if self.song is None:
            return
        self.selected_measure_index = measure_index
        self.selected_candidate = candidate
        self.selected_kind = kind
        self.selected_segment = segment
        self.selectionChanged.emit(self.song.track.measures[measure_index], candidate, kind, segment)
        self.update()

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Open a Guitar Pro file"))

    def _draw_measure(self, painter: QPainter, layout: _MeasureLayout, measure: MeasureData) -> None:
        rect = layout.rect
        selected = layout.index == self.selected_measure_index
        background = QColor("#ffffff") if not selected else QColor("#edf4ff")
        border = QColor("#c7d1df") if not selected else QColor("#3d7edb")

        painter.setPen(QPen(border, 1.4 if selected else 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        title_font = QFont("Segoe UI", max(8, int(9 * self.zoom)))
        painter.setFont(title_font)
        painter.setPen(QColor("#2e3a4f"))
        title = f"M{measure.number}  {measure.time_signature}"
        painter.drawText(rect.adjusted(8, 4, -8, 0), Qt.AlignmentFlag.AlignLeft, title)
        self._draw_memo_icon(painter, rect, layout.index, measure)

        self._draw_tab_lines(painter, rect, measure)
        self._draw_segment_changes(painter, rect, layout.index, measure)
        self._draw_analysis_chips(painter, rect, layout.index, measure)

    def _draw_memo_icon(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        font = QFont("Segoe UI", max(8, int(9 * self.zoom)))
        metrics = QFontMetrics(font)
        title = f"M{measure.number}  {measure.time_signature}"
        size = max(12, int(14 * self.zoom))
        x = rect.left() + 12 + metrics.horizontalAdvance(title)
        y = rect.top() + max(4, int(5 * self.zoom))
        icon_rect = _post_it_icon_rect(x, y, size)
        _draw_post_it_icon(painter, icon_rect, measure.number in self._memo_measure_numbers)
        self._memo_icon_hits.append(_MemoIconHit(icon_rect.adjusted(-3, -3, 3, 3), measure_index))

    def _draw_tab_lines(self, painter: QPainter, rect: QRect, measure: MeasureData) -> None:
        if self.song is None:
            return

        left_pad = int(34 * self.zoom)
        right_pad = int(10 * self.zoom)
        tab_top = rect.top() + int(30 * self.zoom)
        string_gap = max(8, int(10 * self.zoom))
        line_width = max(1, int(1.2 * self.zoom))
        tab_left = rect.left() + left_pad
        tab_right = rect.right() - right_pad
        note_pad = max(8, int(12 * self.zoom))
        tab_width = max(40, tab_right - tab_left - (note_pad * 2))

        painter.setPen(QPen(QColor("#96a1b2"), line_width))
        label_font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(label_font)
        string_names = self.song.track.string_names
        for string_index, name in enumerate(string_names):
            y = tab_top + (string_index * string_gap)
            painter.drawLine(tab_left, y, tab_right, y)
            painter.setPen(QColor("#6b7280"))
            painter.drawText(rect.left() + 8, y + 4, name[:-1] if len(name) > 1 else name)
            painter.setPen(QPen(QColor("#96a1b2"), line_width))

        painter.setPen(QPen(QColor("#7d8797"), line_width))
        painter.drawLine(tab_left, tab_top, tab_left, tab_top + (len(string_names) - 1) * string_gap)
        painter.drawLine(tab_right, tab_top, tab_right, tab_top + (len(string_names) - 1) * string_gap)

        note_font = QFont("Consolas", max(8, int(9 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(note_font)
        metrics = QFontMetrics(note_font)
        for beat in measure.beats:
            if not beat.notes:
                continue
            beat_ratio = min(1.0, max(0.0, beat.start_in_measure / measure.length_ticks))
            x = tab_left + note_pad + int(beat_ratio * tab_width)
            for note in beat.notes:
                y = tab_top + ((note.string - 1) * string_gap)
                text = tab_note_text(note)
                text_rect = QRect(
                    x - metrics.horizontalAdvance(text) // 2 - 3,
                    y - metrics.height() // 2,
                    metrics.horizontalAdvance(text) + 6,
                    metrics.height(),
                )
                painter.setPen(QColor("#111827"))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_analysis_chips(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(font)
        metrics = QFontMetrics(font)

        y = rect.top() + int(126 * self.zoom)
        if self.zoom < 0.9:
            y = rect.top() + int(114 * self.zoom)

        scale_color = QColor("#cb3a31")
        chord_color = QColor("#2468d8")
        next_y = self._draw_chip_row(
            painter,
            rect.left() + 8,
            y,
            rect.width() - 16,
            "S",
            measure.analysis.scale_candidates,
            scale_color,
            metrics,
            measure_index,
            "scale",
            None,
        )
        self._draw_chip_row(
            painter,
            rect.left() + 8,
            next_y + 3,
            rect.width() - 16,
            "C",
            measure.analysis.chord_candidates,
            chord_color,
            metrics,
            measure_index,
            "chord",
            None,
        )

    def _draw_chip_row(
        self,
        painter: QPainter,
        x: int,
        y: int,
        width: int,
        prefix: str,
        candidates: tuple[Candidate, ...],
        color: QColor,
        metrics: QFontMetrics,
        measure_index: int,
        kind: str,
        segment: SegmentData | None,
    ) -> int:
        painter.setPen(QColor("#5f6b7c"))
        chip_height = metrics.height() + 4
        line_step = chip_height + 4
        prefix_rect = QRect(x, y, 18, chip_height)
        painter.drawText(prefix_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, prefix)
        row_x = x + 20
        cursor_x = row_x
        cursor_y = y
        max_x = x + width
        row_width = max(42, max_x - row_x)

        if not candidates:
            painter.drawText(QRect(cursor_x, y, width - 20, chip_height), Qt.AlignmentFlag.AlignVCenter, "-")
            return y + line_step

        for candidate in self._display_candidates(candidates, kind):
            label = self._candidate_label(candidate)
            chip_width = min(max(metrics.horizontalAdvance(label) + 12, 42), row_width)
            if cursor_x > row_x and cursor_x + chip_width > max_x:
                cursor_x = row_x
                cursor_y += line_step
            if cursor_x + chip_width > max_x:
                chip_width = max(42, max_x - cursor_x)
            chip_rect = QRect(cursor_x, cursor_y, chip_width, chip_height)
            painter.setPen(QPen(color, 1))
            fill = QColor(color)
            fill.setAlpha(24)
            painter.setBrush(fill)
            painter.drawRoundedRect(chip_rect, 5, 5)
            painter.setPen(color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            visible_label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, chip_width - 10)
            painter.drawText(chip_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignCenter, visible_label)
            self._candidate_hits.append(_CandidateHit(chip_rect, measure_index, candidate, kind, segment))
            cursor_x += chip_width + 4
        return cursor_y + line_step

    def _draw_segment_changes(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        if len(measure.segments) <= 1:
            return

        tab_left, tab_right = self._tab_x_bounds(rect)
        tab_width = max(40, tab_right - tab_left)
        row_height = max(12, int(15 * self.zoom))
        gap = max(2, int(3 * self.zoom))
        scale_y = rect.top() + int(86 * self.zoom)
        chord_y = scale_y + row_height + gap
        scale_color = QColor("#cb3a31")
        chord_color = QColor("#2468d8")
        marker_color = QColor("#2f3746")
        font = QFont("Segoe UI", max(6, int(7 * self.zoom)))
        painter.setFont(font)
        metrics = QFontMetrics(font)

        previous_scale = ""
        previous_chord = ""
        for segment in measure.segments:
            x1 = tab_left + int((segment.start_in_measure / measure.length_ticks) * tab_width)
            x2 = tab_left + int((segment.end_in_measure / measure.length_ticks) * tab_width)
            segment_width = max(8, x2 - x1)
            scale = segment.analysis.scale_candidates[0] if segment.analysis.scale_candidates else None
            chord = segment.analysis.chord_candidates[0] if segment.analysis.chord_candidates else None
            scale_name = scale.name if scale else ""
            chord_name = chord.name if chord else ""

            if segment.index > 0 and (scale_name != previous_scale or chord_name != previous_chord):
                painter.setPen(QPen(marker_color, 1.2))
                painter.drawLine(x1, scale_y - 3, x1, chord_y + row_height + 2)

            if scale is not None:
                self._draw_segment_chip(
                    painter,
                    QRect(x1, scale_y, segment_width, row_height),
                    scale,
                    scale_color,
                    metrics,
                    measure_index,
                    "scale",
                    segment,
                )
            if chord is not None:
                self._draw_segment_chip(
                    painter,
                    QRect(x1, chord_y, segment_width, row_height),
                    chord,
                    chord_color,
                    metrics,
                    measure_index,
                    "chord",
                    segment,
                )

            previous_scale = scale_name
            previous_chord = chord_name

    def _draw_segment_chip(
        self,
        painter: QPainter,
        chip_rect: QRect,
        candidate: Candidate,
        color: QColor,
        metrics: QFontMetrics,
        measure_index: int,
        kind: str,
        segment: SegmentData,
    ) -> None:
        if chip_rect.width() < 8:
            return

        fill = QColor(color)
        fill.setAlpha(20)
        painter.setPen(QPen(color, 0.8))
        painter.setBrush(fill)
        painter.drawRoundedRect(chip_rect, 4, 4)

        if chip_rect.width() >= 28:
            painter.setPen(color)
            label = self._short_candidate_label(candidate)
            visible_label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, chip_rect.width() - 4)
            painter.drawText(chip_rect.adjusted(2, 0, -2, 0), Qt.AlignmentFlag.AlignCenter, visible_label)

        self._candidate_hits.append(_CandidateHit(chip_rect, measure_index, candidate, kind, segment))

    def _short_candidate_label(self, candidate: Candidate) -> str:
        name = candidate_display_name(candidate, self._prefer_flats())
        name = name.replace("natural minor", "min")
        name = name.replace("harmonic minor", "hmin")
        name = name.replace("phrygian dominant", "phr dom")
        name = name.replace("locrian natural 6", "loc n6")
        name = name.replace("ionian augmented", "ion aug")
        name = name.replace("dorian #4", "dor #4")
        name = name.replace("lydian #2", "lyd #2")
        name = name.replace("altered diminished", "alt dim")
        name = name.replace("melodic minor", "mmin")
        name = name.replace("major pentatonic", "maj p")
        name = name.replace("minor pentatonic", "min p")
        return f"{name} {candidate.score}"

    def _candidate_label(self, candidate: Candidate) -> str:
        return candidate_display_label(candidate, self._prefer_flats())

    def _display_candidates(self, candidates: tuple[Candidate, ...], kind: str) -> tuple[Candidate, ...]:
        if kind != "scale":
            return candidates[:MAX_DISPLAY_CANDIDATES]

        display: list[Candidate] = []
        seen_pitch_sets: set[tuple[int, ...]] = set()
        for candidate in candidates:
            key = tuple(sorted(candidate.pitch_classes))
            if key in seen_pitch_sets:
                continue
            seen_pitch_sets.add(key)
            display.append(candidate)
            if len(display) >= MAX_DISPLAY_CANDIDATES:
                break
        return tuple(display)

    def _prefer_flats(self) -> bool | None:
        return self.song.track.prefer_flats if self.song is not None else None

    def _tab_x_bounds(self, rect: QRect) -> tuple[int, int]:
        left_pad = int(34 * self.zoom)
        right_pad = int(10 * self.zoom)
        return rect.left() + left_pad, rect.right() - right_pad

    def _rebuild_layout(self) -> None:
        self._measure_layouts = []
        if self.song is None:
            self._content_height = 320
            self.setMinimumHeight(self._content_height)
            return

        width = max(360, self.width())
        margin = int(12 * self.zoom)
        x = margin
        y = margin
        max_width = width - (margin * 2)
        chip_metrics = QFontMetrics(QFont("Segoe UI", max(7, int(8 * self.zoom))))
        row_height = 0

        for index, measure in enumerate(self.song.track.measures):
            note_slots = max(1, sum(1 for beat in measure.beats if beat.notes))
            change_slots = max(1, len(measure.segments) * 2)
            desired_width = int(max(172 * self.zoom, 58 * self.zoom + max(note_slots, change_slots) * 35 * self.zoom))
            measure_width = min(max_width, desired_width)
            measure_height = self._measure_row_height(measure, measure_width, chip_metrics)
            if x > margin and x + measure_width > width - margin:
                x = margin
                y += row_height + margin
                row_height = 0
            self._measure_layouts.append(_MeasureLayout(index, QRect(x, y, measure_width, measure_height)))
            row_height = max(row_height, measure_height)
            x += measure_width + margin

        self._content_height = max(320, y + row_height + margin)
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _measure_row_height(self, measure: MeasureData, measure_width: int, metrics: QFontMetrics) -> int:
        chip_width = measure_width - 16
        scale_lines = self._chip_line_count(measure.analysis.scale_candidates, chip_width, metrics, "scale")
        chord_lines = self._chip_line_count(measure.analysis.chord_candidates, chip_width, metrics, "chord")
        extra_lines = max(0, scale_lines + chord_lines - 2)
        return int(190 * self.zoom) + extra_lines * (metrics.height() + 8)

    def _chip_line_count(
        self,
        candidates: tuple[Candidate, ...],
        width: int,
        metrics: QFontMetrics,
        kind: str,
    ) -> int:
        display_candidates = self._display_candidates(candidates, kind)
        if not display_candidates:
            return 1
        row_width = max(42, width - 20)
        lines = 1
        cursor_width = 0
        for candidate in display_candidates:
            label = self._candidate_label(candidate)
            chip_width = min(max(metrics.horizontalAdvance(label) + 12, 42), row_width)
            if cursor_width > 0 and cursor_width + chip_width > row_width:
                lines += 1
                cursor_width = 0
            cursor_width += chip_width + 4
        return lines


class TabScoreWidget(QWidget):
    selectionChanged = pyqtSignal(int, int)
    zoomWheelRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.zoom = 1.0
        self.selected_start = 0
        self.selected_end = 0
        self.playback_tick: int | None = None
        self._measure_layouts: list[_MeasureLayout] = []
        self._content_size = QSize(960, 260)
        self._drag_anchor: int | None = None
        self._dragging = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return self._content_size

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_start = 0
        self.selected_end = 0
        self.playback_tick = None
        self._rebuild_layout()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.6, min(2.2, zoom))
        self._rebuild_layout()
        self.update()

    def set_selected_range(self, start: int, end: int, emit: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            self.selected_start = 0
            self.selected_end = 0
            self.update()
            return
        count = len(self.song.track.measures)
        start = max(0, min(start, count - 1))
        end = max(0, min(end, count - 1))
        if end < start:
            start, end = end, start
        changed = (start, end) != (self.selected_start, self.selected_end)
        self.selected_start = start
        self.selected_end = end
        if changed:
            self.update()
            if emit:
                self.selectionChanged.emit(start, end)

    def set_playback_tick(self, tick: int | None) -> None:
        self.playback_tick = tick
        self.update()

    def layout_for_tick(self, tick: int) -> _MeasureLayout | None:
        if self.song is None or not self._measure_layouts:
            return None
        last_layout: _MeasureLayout | None = None
        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            measure_start = measure.start_tick
            measure_end = measure.start_tick + measure.length_ticks
            if measure_start <= tick < measure_end:
                return layout
            last_layout = layout
        return last_layout if tick >= self.song.track.measures[-1].start_tick else None

    def layout_for_measure(self, measure_index: int) -> _MeasureLayout | None:
        for layout in self._measure_layouts:
            if layout.index == measure_index:
                return layout
        return None

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None:
            return
        position = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._measure_index_at(position)
            if index is not None:
                self._drag_anchor = index
                self._dragging = True
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.set_selected_range(self.selected_start, index, emit=True)
                else:
                    self.set_selected_range(index, index, emit=True)
                return

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None or not self._dragging or self._drag_anchor is None:
            return
        index = self._measure_index_at(event.position().toPoint())
        if index is None:
            return
        self.set_selected_range(self._drag_anchor, index, emit=True)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_anchor = None
            return

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoomWheelRequested.emit(10 if delta > 0 else -10)
                event.accept()
                return
        super().wheelEvent(event)

    def _measure_index_at(self, position: QPoint) -> int | None:
        for layout in self._measure_layouts:
            if layout.rect.contains(position):
                return layout.index
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfaf6"))
        if self.song is None:
            self._draw_empty(painter)
            return
        self._draw_systems(painter)
        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            self._draw_measure(painter, layout, measure)

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Open a Guitar Pro file"))

    def _draw_measure(self, painter: QPainter, layout: _MeasureLayout, measure: MeasureData) -> None:
        if self.song is None:
            return
        rect = layout.rect
        selected = self.selected_start <= layout.index <= self.selected_end
        tab_left, tab_right, tab_top, string_gap = self._tab_geometry(rect)
        string_count = len(self.song.track.string_names)
        tab_bottom = tab_top + ((string_count - 1) * string_gap)

        if selected:
            highlight = QColor("#ffd46f")
            highlight.setAlpha(85)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            painter.drawRect(QRect(tab_left + 1, rect.top() + int(19 * self.zoom), max(1, tab_right - tab_left - 1), tab_bottom - rect.top() + int(22 * self.zoom)))

        title_font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#445065"))
        title = f"{measure.number}"
        painter.drawText(QRect(tab_left + 4, rect.top() + 2, max(24, rect.width() - 8), int(17 * self.zoom)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        bar_pen = QPen(QColor("#424b59"), max(1, int(1.2 * self.zoom)))
        painter.setPen(bar_pen)
        if self._is_row_start(layout):
            painter.drawLine(tab_left, tab_top, tab_left, tab_bottom)
        painter.drawLine(tab_right, tab_top, tab_right, tab_bottom)

        self._draw_notes(painter, rect, measure, tab_left, tab_right, tab_top, string_gap)
        self._draw_playback_cursor(painter, layout, measure, tab_left, tab_right, tab_top, string_gap)

    def _draw_systems(self, painter: QPainter) -> None:
        if self.song is None:
            return

        line_pen = QPen(QColor("#7e8796"), max(1, int(1.05 * self.zoom)))
        label_font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(label_font)
        rows = self._row_groups()
        for row in rows:
            first = row[0]
            last = row[-1]
            tab_left, _right, tab_top, string_gap = self._tab_geometry(first.rect)
            tab_right = self._tab_geometry(last.rect)[1]
            label_x = max(2, tab_left - int(38 * self.zoom))
            for string_index, name in enumerate(self.song.track.string_names):
                y = tab_top + (string_index * string_gap)
                painter.setPen(QColor("#5e6775"))
                painter.drawText(QRect(label_x, y - 8, int(30 * self.zoom), 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name[:-1] if len(name) > 1 else name)
                painter.setPen(line_pen)
                painter.drawLine(tab_left, y, tab_right, y)

    def _draw_notes(
        self,
        painter: QPainter,
        rect: QRect,
        measure: MeasureData,
        tab_left: int,
        tab_right: int,
        tab_top: int,
        string_gap: int,
    ) -> None:
        tab_width = max(1, tab_right - tab_left)
        note_font = QFont("Consolas", max(9, int(11 * self.zoom)), QFont.Weight.DemiBold)
        note_metrics = QFontMetrics(note_font)
        note_positions = self._note_positions(measure, tab_left, tab_width, tab_top, string_gap)
        beat_positions = self._beat_positions(note_positions)

        self._draw_rhythm_notation(painter, measure, beat_positions, tab_top, string_gap)
        self._draw_technique_spans(painter, beat_positions, rect.top(), tab_top)
        self._draw_note_relationships(painter, note_positions, note_metrics)

        for x, y, note, _beat in note_positions:
            self._draw_note_technique_symbols(painter, note, x, y, note_metrics)

        painter.setFont(note_font)
        for x, y, note, _beat in note_positions:
            text = tab_note_text(note)
            width = note_metrics.horizontalAdvance(text) + 8
            text_rect = QRect(x - width // 2, y - note_metrics.height() // 2, width, note_metrics.height())
            painter.setPen(QColor("#171923"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _note_positions(
        self,
        measure: MeasureData,
        tab_left: int,
        tab_width: int,
        tab_top: int,
        string_gap: int,
    ) -> list[tuple[int, int, object, BeatData]]:
        note_pad = max(10, int(14 * self.zoom))
        effective_width = max(1, tab_width - (note_pad * 2))
        note_font = QFont("Consolas", max(9, int(11 * self.zoom)), QFont.Weight.DemiBold)
        note_metrics = QFontMetrics(note_font)
        min_gap = max(4, int(6 * self.zoom))
        beat_items: list[tuple[int, BeatData, tuple[object, ...], int]] = []
        for beat in measure.beats:
            if not beat.notes:
                continue
            ratio = min(1.0, max(0.0, beat.start_in_measure / measure.length_ticks))
            x = tab_left + note_pad + int(ratio * effective_width)
            half_width = max(
                1,
                max((note_metrics.horizontalAdvance(tab_note_text(note)) + 8) // 2 for note in beat.notes),
            )
            beat_items.append((x, beat, tuple(beat.notes), half_width))

        adjusted_by_beat = self._spread_close_beat_positions(
            beat_items,
            tab_left + note_pad,
            tab_left + note_pad + effective_width,
            min_gap,
        )

        positions: list[tuple[int, int, object, BeatData]] = []
        for raw_x, beat, notes, _half_width in beat_items:
            x = adjusted_by_beat.get(id(beat), raw_x)
            for note in beat.notes:
                y = tab_top + ((note.string - 1) * string_gap)
                positions.append((x, y, note, beat))
        return positions

    def _spread_close_beat_positions(
        self,
        beat_items: list[tuple[int, BeatData, tuple[object, ...], int]],
        min_x: int,
        max_x: int,
        min_gap: int,
    ) -> dict[int, int]:
        if not beat_items:
            return {}

        ordered = sorted(beat_items, key=lambda item: (item[1].start_in_measure, item[0]))
        half_widths = [half_width for _x, _beat, _notes, half_width in ordered]
        total_text_width = sum(half_width * 2 for half_width in half_widths)
        available_width = max(1, max_x - min_x)
        local_gap = min_gap
        if len(ordered) > 1 and total_text_width + (min_gap * (len(ordered) - 1)) > available_width:
            local_gap = max(0, (available_width - total_text_width) // (len(ordered) - 1))

        adjusted: list[tuple[BeatData, int, int]] = []
        previous_right: int | None = None
        for item, half_width in zip(ordered, half_widths):
            raw_x, beat, _notes, _half_width = item
            target_x = max(min_x + half_width, raw_x)
            if previous_right is not None:
                target_x = max(target_x, previous_right + local_gap + half_width)
            adjusted.append((beat, target_x, half_width))
            previous_right = target_x + half_width

        overflow = adjusted[-1][1] + adjusted[-1][2] - max_x
        if overflow > 0:
            adjusted = [(beat, x - overflow, half_width) for beat, x, half_width in adjusted]

        adjusted_by_beat: dict[int, int] = {}
        previous_right = None
        for beat, x, half_width in adjusted:
            target_x = max(min_x + half_width, x)
            if previous_right is not None:
                target_x = max(target_x, previous_right + local_gap + half_width)
            adjusted_by_beat[id(beat)] = target_x
            previous_right = target_x + half_width
        return adjusted_by_beat

    def _beat_positions(self, positions: list[tuple[int, int, object, BeatData]]) -> list[tuple[int, BeatData]]:
        seen: set[int] = set()
        beat_positions: list[tuple[int, BeatData]] = []
        for x, _y, _note, beat in positions:
            key = id(beat)
            if key in seen:
                continue
            seen.add(key)
            beat_positions.append((x, beat))
        return sorted(beat_positions, key=lambda item: (item[1].start_in_measure, item[0]))

    def _draw_rhythm_notation(
        self,
        painter: QPainter,
        measure: MeasureData,
        beat_positions: list[tuple[int, BeatData]],
        tab_top: int,
        string_gap: int,
    ) -> None:
        if not beat_positions or self.song is None:
            return

        string_count = len(self.song.track.string_names)
        tab_bottom = tab_top + ((string_count - 1) * string_gap)
        stem_top = tab_bottom + int(8 * self.zoom)
        stem_bottom = tab_bottom + int(28 * self.zoom)
        beam_gap = max(3, int(4 * self.zoom))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rhythm_pen = QPen(QColor("#535353"), max(1, int(1.05 * self.zoom)))
        rhythm_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(rhythm_pen)
        painter.setBrush(QColor("#535353"))

        for x, beat in beat_positions:
            if beat.duration_ticks >= 3840:
                painter.drawEllipse(QPointF(x, stem_top + int(4 * self.zoom)), max(3, int(4 * self.zoom)), max(2, int(2.5 * self.zoom)))
                continue
            painter.drawLine(x, stem_top, x, stem_bottom)
            if beat.duration_ticks >= 1920:
                painter.drawEllipse(QPointF(x, stem_top + int(3 * self.zoom)), max(3, int(4 * self.zoom)), max(2, int(2.5 * self.zoom)))

        self._draw_rhythm_beams(painter, beat_positions, stem_bottom, beam_gap)
        self._draw_tuplet_labels(painter, beat_positions, stem_bottom)
        painter.restore()

    def _draw_rhythm_beams(
        self,
        painter: QPainter,
        beat_positions: list[tuple[int, BeatData]],
        stem_bottom: int,
        beam_gap: int,
    ) -> None:
        runs = self._rhythm_beam_runs(beat_positions)
        beam_height = max(2, int(3 * self.zoom))
        for run in runs:
            if len(run) == 1:
                x, beat = run[0]
                for level in range(self._rhythm_beam_count(beat.duration_ticks)):
                    y = stem_bottom - (level * beam_gap)
                    painter.drawRect(QRect(x, y - beam_height // 2, int(10 * self.zoom), beam_height))
                continue

            min_count = min(self._rhythm_beam_count(beat.duration_ticks) for _x, beat in run)
            start_x = run[0][0]
            end_x = run[-1][0]
            for level in range(min_count):
                y = stem_bottom - (level * beam_gap)
                painter.drawRect(QRect(start_x, y - beam_height // 2, max(1, end_x - start_x), beam_height))
            for x, beat in run:
                extra = self._rhythm_beam_count(beat.duration_ticks) - min_count
                for level in range(extra):
                    y = stem_bottom - ((min_count + level) * beam_gap)
                    painter.drawRect(QRect(x, y - beam_height // 2, int(10 * self.zoom), beam_height))

    def _rhythm_beam_runs(self, beat_positions: list[tuple[int, BeatData]]) -> list[list[tuple[int, BeatData]]]:
        runs: list[list[tuple[int, BeatData]]] = []
        current: list[tuple[int, BeatData]] = []
        expected_next: int | None = None
        for item in beat_positions:
            _x, beat = item
            if self._rhythm_beam_count(beat.duration_ticks) <= 0:
                if current:
                    runs.append(current)
                    current = []
                expected_next = beat.start_in_measure + beat.duration_ticks
                continue
            if current and expected_next is not None and abs(beat.start_in_measure - expected_next) > 1:
                runs.append(current)
                current = []
            current.append(item)
            expected_next = beat.start_in_measure + beat.duration_ticks
        if current:
            runs.append(current)
        return runs

    def _draw_tuplet_labels(self, painter: QPainter, beat_positions: list[tuple[int, BeatData]], stem_bottom: int) -> None:
        groups = self._tuplet_groups(beat_positions)
        if not groups:
            return
        color = QColor("#2f3746")
        bracket_pen = QPen(color, max(1, int(1.35 * self.zoom)))
        bracket_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(bracket_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        bracket_y = stem_bottom + int(10 * self.zoom)
        hook_top = stem_bottom + int(2 * self.zoom)
        overhang = max(3, int(4 * self.zoom))
        label_gap = max(3, int(4 * self.zoom))
        for label, start_x, end_x in groups:
            if end_x <= start_x:
                continue
            bracket_start = start_x - overhang
            bracket_end = end_x + overhang
            rect = QRect(
                int((start_x + end_x) / 2) - metrics.horizontalAdvance(label) // 2 - 4,
                bracket_y - metrics.height() // 2,
                metrics.horizontalAdvance(label) + 8,
                metrics.height(),
            )

            painter.setPen(bracket_pen)
            painter.drawLine(bracket_start, bracket_y, max(bracket_start, rect.left() - label_gap), bracket_y)
            painter.drawLine(min(bracket_end, rect.right() + label_gap), bracket_y, bracket_end, bracket_y)
            painter.drawLine(bracket_start, hook_top, bracket_start, bracket_y)
            painter.drawLine(bracket_end, hook_top, bracket_end, bracket_y)
            painter.drawLine(bracket_start, hook_top, bracket_start + overhang, hook_top)
            painter.drawLine(bracket_end - overhang, hook_top, bracket_end, hook_top)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#fff5d8"))
            painter.drawRoundedRect(rect.adjusted(-1, 0, 1, 0), 2, 2)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _tuplet_groups(self, beat_positions: list[tuple[int, BeatData]]) -> list[tuple[str, int, int]]:
        groups: list[tuple[str, int, int]] = []
        index = 0
        while index < len(beat_positions):
            _x, beat = beat_positions[index]
            tuplet_info = self._tuplet_info_for_beat(beat)
            if tuplet_info is None:
                index += 1
                continue
            label, target_count = tuplet_info
            start_index = index
            expected_next = beat.start_in_measure + beat.duration_ticks
            index += 1
            while index < len(beat_positions):
                _next_x, next_beat = beat_positions[index]
                next_tuplet_info = self._tuplet_info_for_beat(next_beat)
                if next_tuplet_info is None or next_tuplet_info[0] != label:
                    break
                if abs(next_beat.start_in_measure - expected_next) > 1:
                    break
                expected_next = next_beat.start_in_measure + next_beat.duration_ticks
                index += 1
            run_count = index - start_index
            if run_count >= target_count * 2:
                continue
            for group_start in range(start_index, index, target_count):
                group_end = min(group_start + target_count, index) - 1
                if group_end > group_start:
                    groups.append((label, beat_positions[group_start][0], beat_positions[group_end][0]))
        return groups

    def _tuplet_info_for_beat(self, beat: BeatData) -> tuple[str, int] | None:
        if beat.tuplet is not None:
            numerator, _denominator = beat.tuplet
            if numerator > 1:
                return str(numerator), numerator
        label = self._tuplet_label_for_duration(beat.duration_ticks)
        if label is None:
            return None
        return label, int(label)

    def _tuplet_label_for_duration(self, duration_ticks: int) -> str | None:
        standard = {30, 60, 120, 240, 480, 960, 1920, 3840}
        for label, numerator, denominator in (("3", 3, 2), ("5", 5, 4), ("6", 6, 4), ("7", 7, 4)):
            base = duration_ticks * numerator / denominator
            if any(abs(base - value) <= 1 for value in standard):
                return label
        return None

    def _rhythm_beam_count(self, duration_ticks: int) -> int:
        if duration_ticks <= 60:
            return 4
        if duration_ticks <= 120:
            return 3
        if duration_ticks <= 240:
            return 2
        if duration_ticks <= 480:
            return 1
        return 0

    def _draw_technique_spans(
        self,
        painter: QPainter,
        beat_positions: list[tuple[int, BeatData]],
        row_top: int,
        tab_top: int,
    ) -> None:
        specs = (("palm_mute", "PM"), ("let_ring", "let ring"))
        base_y = max(row_top + int(16 * self.zoom), tab_top - int(18 * self.zoom))
        drawn_lane = 0
        for technique, label in specs:
            spans = self._technique_spans(beat_positions, technique)
            if not spans:
                continue
            y = base_y - int(drawn_lane * 12 * self.zoom)
            for start_x, end_x in spans:
                self._draw_dashed_span_text(painter, label, start_x, end_x, y, QColor("#666666"))
            drawn_lane += 1

    def _technique_spans(self, beat_positions: list[tuple[int, BeatData]], technique: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start_x: int | None = None
        end_x: int | None = None
        expected_next: int | None = None
        for x, beat in beat_positions:
            has_technique = any(technique in getattr(note, "techniques", ()) for note in beat.notes)
            is_contiguous = expected_next is None or abs(beat.start_in_measure - expected_next) <= 1
            if has_technique and (start_x is None or is_contiguous):
                if start_x is None:
                    start_x = x
                end_x = x + int(22 * self.zoom)
            else:
                if start_x is not None and end_x is not None:
                    spans.append((start_x, end_x))
                start_x = x if has_technique else None
                end_x = x + int(22 * self.zoom) if has_technique else None
            expected_next = beat.start_in_measure + beat.duration_ticks
        if start_x is not None and end_x is not None:
            spans.append((start_x, end_x))
        return spans

    def _draw_note_relationships(
        self,
        painter: QPainter,
        positions: list[tuple[int, int, object, BeatData]],
        note_metrics: QFontMetrics,
    ) -> None:
        by_string: dict[int, list[tuple[int, int, object, BeatData]]] = {}
        for position in positions:
            _x, _y, note, _beat = position
            by_string.setdefault(note.string, []).append(position)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        relation_pen = QPen(QColor("#202633"), max(1, int(1.25 * self.zoom)))
        relation_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(relation_pen)

        for string_positions in by_string.values():
            ordered = sorted(string_positions, key=lambda item: (item[3].start_in_measure, item[0]))
            for left, right in zip(ordered, ordered[1:]):
                left_x, left_y, left_note, _left_beat = left
                right_x, right_y, right_note, _right_beat = right
                if right_x <= left_x:
                    continue
                left_techniques = set(left_note.techniques)
                right_techniques = set(right_note.techniques)

                if "slide" in left_techniques:
                    self._draw_slide_mark_before_note(painter, right_note, right_x, right_y, note_metrics)
                if "tie" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "hammer_on" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "pull_off" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
        painter.restore()

    def _draw_slur_connection(
        self,
        painter: QPainter,
        left_x: int,
        left_y: int,
        right_x: int,
        right_y: int,
        label: str,
    ) -> None:
        start_x = left_x + int(5 * self.zoom)
        end_x = right_x - int(5 * self.zoom)
        if end_x <= start_x:
            return
        base_y = min(left_y, right_y) - int(5 * self.zoom)
        height = max(int(4 * self.zoom), min(int(7 * self.zoom), (end_x - start_x) // 7))
        path = QPainterPath(QPointF(start_x, base_y))
        path.quadTo(QPointF((start_x + end_x) / 2, base_y - height), QPointF(end_x, base_y))
        pen = painter.pen()
        pen.setWidth(max(1, int(1.35 * self.zoom)))
        painter.setPen(pen)
        painter.drawPath(path)
        if label:
            font = QFont("Segoe UI", max(6, int(7 * self.zoom)), QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            label_rect = QRect(
                int((start_x + end_x) / 2) - metrics.horizontalAdvance(label) // 2,
                base_y - height - metrics.height() + 2,
                metrics.horizontalAdvance(label) + 2,
                metrics.height(),
            )
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_slide_connection(
        self,
        painter: QPainter,
        left_x: int,
        left_y: int,
        right_x: int,
        right_y: int,
        left_fret: int,
        right_fret: int,
    ) -> None:
        start_x = left_x + int(8 * self.zoom)
        end_x = right_x - int(8 * self.zoom)
        if end_x <= start_x:
            return
        offset = int(4 * self.zoom)
        if right_fret >= left_fret:
            painter.drawLine(start_x, left_y + offset, end_x, right_y - offset)
        else:
            painter.drawLine(start_x, left_y - offset, end_x, right_y + offset)

    def _draw_slide_out(self, painter: QPainter, x: int, y: int) -> None:
        painter.drawLine(x + int(8 * self.zoom), y + int(4 * self.zoom), x + int(22 * self.zoom), y - int(7 * self.zoom))

    def _draw_beat_technique_symbols(
        self,
        painter: QPainter,
        beat: BeatData,
        x: int,
        row_top: int,
        tab_top: int,
    ) -> None:
        techniques = self._beat_techniques(beat)
        techniques = [technique for technique in techniques if technique in {"palm_mute", "let_ring"}]
        if not techniques:
            return

        symbol_y = max(row_top + int(16 * self.zoom), tab_top - int(18 * self.zoom))
        slot = max(42, int(54 * self.zoom))
        limited = techniques[:5]
        start_x = x - ((len(limited) - 1) * slot) // 2
        for index, technique in enumerate(limited):
            self._draw_technique_symbol(painter, technique, start_x + (index * slot), symbol_y)

    def _beat_techniques(self, beat: BeatData) -> list[str]:
        priority = {
            "palm_mute": 0,
            "let_ring": 1,
            "bend": 2,
            "release_bend": 3,
            "vibrato": 9,
            "staccato": 10,
            "accent": 11,
            "harmonic": 12,
            "tapping": 13,
            "trill": 14,
            "tremolo_picking": 15,
        }
        found: set[str] = set()
        for note in beat.notes:
            found.update(note.techniques)
        found.discard("dead_note")
        found.discard("ghost_note")
        found.difference_update({"slide", "hammer_on", "pull_off", "legato", "tie"})
        if "release_bend" in found:
            found.discard("bend")
        return sorted(found, key=lambda item: (priority.get(item, 99), item))

    def _beat_bend_semitones(self, beat: BeatData) -> float | None:
        values = [note.bend_semitones for note in beat.notes if note.bend_semitones is not None]
        return max(values) if values else None

    def _draw_note_technique_symbols(
        self,
        painter: QPainter,
        note: object,
        x: int,
        y: int,
        note_metrics: QFontMetrics,
    ) -> None:
        techniques = set(getattr(note, "techniques", ()))
        visible = {
            "accent",
            "bend",
            "harmonic",
            "release_bend",
            "staccato",
            "tapping",
            "tremolo_picking",
            "trill",
            "vibrato",
        }
        if not techniques.intersection(visible):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#161616")
        gray = QColor("#535353")
        pen = QPen(color, max(1, int(1.15 * self.zoom)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        text_width = note_metrics.horizontalAdvance(tab_note_text(note)) + int(6 * self.zoom)
        text_half = max(5, text_width // 2)
        lane = 0

        def next_above_y() -> int:
            nonlocal lane
            symbol_y = y - int((17 + (lane * 11)) * self.zoom)
            lane += 1
            return symbol_y

        if "harmonic" in techniques:
            self._draw_harmonic_symbol(painter, x - text_half - int(5 * self.zoom), y)

        if "bend" in techniques or "release_bend" in techniques:
            self._draw_bend_symbol(
                painter,
                x + text_half + int(3 * self.zoom),
                y,
                release="release_bend" in techniques,
                semitones=getattr(note, "bend_semitones", None),
            )

        if "tapping" in techniques:
            self._draw_tapping_symbol(painter, x, next_above_y())
        if "trill" in techniques:
            self._draw_trill_symbol(painter, x, next_above_y())
        if "vibrato" in techniques:
            vibrato_pen = QPen(gray, max(2, int(2.4 * self.zoom)))
            vibrato_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            vibrato_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(vibrato_pen)
            self._draw_wavy_symbol(
                painter,
                x + text_half + int(3 * self.zoom),
                next_above_y(),
                int(24 * self.zoom),
                max(1, int(1.8 * self.zoom)),
            )
            painter.setPen(pen)
        if "accent" in techniques:
            self._draw_accent_symbol(painter, x, next_above_y())
        if "staccato" in techniques:
            self._draw_staccato_symbol(painter, x, next_above_y())
        if "tremolo_picking" in techniques:
            self._draw_tremolo_symbol(painter, x + text_half + int(6 * self.zoom), y + int(14 * self.zoom))

        painter.restore()

    def _draw_slide_mark_before_note(
        self,
        painter: QPainter,
        note: object,
        x: int,
        y: int,
        note_metrics: QFontMetrics,
    ) -> None:
        text_width = note_metrics.horizontalAdvance(tab_note_text(note)) + int(6 * self.zoom)
        text_half = max(5, text_width // 2)
        self._draw_slide_mark(painter, x - text_half - int(5 * self.zoom), y)

    def _draw_slide_mark(self, painter: QPainter, x: int, y: int) -> None:
        length = max(8, int(10 * self.zoom))
        height = max(8, int(11 * self.zoom))
        painter.drawLine(x - length, y + height // 2, x, y - height // 2)

    def _draw_technique_symbol(
        self,
        painter: QPainter,
        technique: str,
        x: int,
        y: int,
        bend_semitones: float | None = None,
    ) -> None:
        painter.save()
        color = QColor("#161616")
        accent = QColor("#666666")
        pen_width = max(1, int(1.1 * self.zoom))
        painter.setPen(QPen(color, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if technique == "bend":
            self._draw_bend_symbol(painter, x, y, release=False, semitones=bend_semitones)
        elif technique == "release_bend":
            self._draw_bend_symbol(painter, x, y, release=True, semitones=bend_semitones)
        elif technique == "vibrato":
            vibrato_pen = QPen(accent, max(2, int(2.4 * self.zoom)))
            vibrato_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            vibrato_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(vibrato_pen)
            self._draw_wavy_symbol(painter, x - int(8 * self.zoom), y, int(22 * self.zoom), max(1, int(1.8 * self.zoom)))
        elif technique == "staccato":
            self._draw_staccato_symbol(painter, x, y)
        elif technique == "accent":
            self._draw_accent_symbol(painter, x, y)
        elif technique == "harmonic":
            self._draw_harmonic_symbol(painter, x, y)
        elif technique == "tapping":
            self._draw_tapping_symbol(painter, x, y)
        elif technique == "trill":
            self._draw_trill_symbol(painter, x, y)
        elif technique == "tremolo_picking":
            self._draw_tremolo_symbol(painter, x, y)
        elif technique == "palm_mute":
            self._draw_dashed_text_symbol(painter, "P.M.", x, y, accent)
        elif technique == "let_ring":
            self._draw_dashed_text_symbol(painter, "let ring", x, y, accent)
        painter.restore()

    def _draw_bend_symbol(
        self,
        painter: QPainter,
        x: int,
        y: int,
        release: bool,
        semitones: float | None = None,
    ) -> None:
        scale = self.zoom * 0.5
        pen = QPen(painter.pen().color(), max(1, int(1.15 * scale)))
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        start = QPointF(x, y - int(2 * scale))
        peak = QPointF(x + int(37 * scale), y - int(43 * scale))
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(x + int(20 * scale), y - int(2 * scale)),
            QPointF(x + int(37 * scale), y - int(18 * scale)),
            peak,
        )
        painter.drawPath(path)
        self._draw_bend_arrow_triangle(painter, peak, up=True, scale=scale)

        if release:
            end = QPointF(x + int(72 * scale), y - int(16 * scale))
            release_path = QPainterPath(peak)
            release_path.cubicTo(
                QPointF(x + int(59 * scale), y - int(43 * scale)),
                QPointF(x + int(72 * scale), y - int(33 * scale)),
                end,
            )
            painter.drawPath(release_path)
            self._draw_bend_arrow_triangle(painter, end, up=False, scale=scale)

        label = self._bend_amount_label(semitones)
        if label:
            font = QFont("Segoe UI", max(5, int(6 * scale)), QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            label_x = int(peak.x()) - metrics.horizontalAdvance(label) // 2
            label_y = int(peak.y()) - metrics.height() - int(2 * scale)
            painter.drawText(
                QRect(label_x, label_y, metrics.horizontalAdvance(label) + 2, metrics.height()),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _draw_bend_arrow_triangle(self, painter: QPainter, tip: QPointF, up: bool, scale: float | None = None) -> None:
        scale = self.zoom if scale is None else scale
        size = max(2, int(4.1 * scale))
        half = max(2, int(4 * scale))
        path = QPainterPath(tip)
        if up:
            path.lineTo(QPointF(tip.x() - half, tip.y() + size))
            path.lineTo(QPointF(tip.x() + half, tip.y() + size))
        else:
            path.lineTo(QPointF(tip.x() - half, tip.y() - size))
            path.lineTo(QPointF(tip.x() + half, tip.y() - size))
        path.closeSubpath()
        color = painter.pen().color()
        old_brush = painter.brush()
        old_pen = painter.pen()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _draw_harmonic_symbol(self, painter: QPainter, x: int, y: int) -> None:
        size = max(4, int(4.2 * self.zoom))
        path = QPainterPath(QPointF(x, y - size))
        path.lineTo(QPointF(x + size, y))
        path.lineTo(QPointF(x, y + size))
        path.lineTo(QPointF(x - size, y))
        path.closeSubpath()
        old_pen = painter.pen()
        old_brush = painter.brush()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b0b2b6"))
        painter.drawPath(path)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _draw_accent_symbol(self, painter: QPainter, x: int, y: int) -> None:
        span = max(5, int(6 * self.zoom))
        rise = max(2, int(3 * self.zoom))
        old_pen = painter.pen()
        accent_pen = QPen(QColor("#161616"), max(1, int(1.15 * self.zoom)))
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        accent_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(accent_pen)
        painter.drawLine(x - span, y - rise, x + span, y)
        painter.drawLine(x - span, y + rise, x + span, y)
        painter.setPen(old_pen)

    def _draw_staccato_symbol(self, painter: QPainter, x: int, y: int) -> None:
        radius = max(2, int(2.4 * self.zoom))
        old_brush = painter.brush()
        old_pen = painter.pen()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#161616"))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _bend_amount_label(self, semitones: float | None) -> str:
        if semitones is None or semitones <= 0:
            return ""
        fraction = Fraction(semitones / 2).limit_denominator(4)
        whole = fraction.numerator // fraction.denominator
        remainder = fraction - whole
        if remainder == 0:
            return str(whole)
        text = f"{remainder.numerator}/{remainder.denominator}"
        return f"{whole} {text}" if whole else text

    def _draw_wavy_symbol(self, painter: QPainter, x: int, y: int, width: int, amplitude: int) -> None:
        path = QPainterPath(QPointF(x, y))
        steps = max(6, int(width / max(3, int(3.5 * self.zoom))))
        segment = width / steps
        for index in range(steps):
            start_x = x + (index * segment)
            mid_x = start_x + segment / 2
            end_x = start_x + segment
            direction = -1 if index % 2 == 0 else 1
            path.quadTo(QPointF(mid_x, y + (direction * amplitude)), QPointF(end_x, y))
        painter.drawPath(path)

    def _draw_text_symbol(self, painter: QPainter, text: str, x: int, y: int) -> QRect:
        font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        rect = QRect(
            x - metrics.horizontalAdvance(text) // 2,
            y - metrics.height() // 2,
            metrics.horizontalAdvance(text) + 2,
            metrics.height(),
        )
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        return rect

    def _draw_tapping_symbol(self, painter: QPainter, x: int, y: int) -> None:
        font = QFont("Segoe UI", max(8, int(9 * self.zoom)), QFont.Weight.Bold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = "T"
        painter.drawText(
            QRect(
                x - metrics.horizontalAdvance(text) // 2,
                y - metrics.height() // 2,
                metrics.horizontalAdvance(text) + 2,
                metrics.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    def _draw_tremolo_symbol(self, painter: QPainter, x: int, y: int) -> None:
        old_pen = painter.pen()
        tremolo_pen = QPen(QColor("#a5a7ab"), max(1, int(1.05 * self.zoom)))
        tremolo_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(tremolo_pen)
        span = max(8, int(10 * self.zoom))
        offset = max(3, int(4 * self.zoom))
        for index in range(3):
            yy = y - offset + (index * offset)
            painter.drawLine(x - span // 2, yy + offset // 2, x + span // 2, yy - offset // 2)
        painter.setPen(old_pen)

    def _draw_trill_symbol(self, painter: QPainter, x: int, y: int) -> None:
        rect = self._draw_text_symbol(painter, "tr", x - int(5 * self.zoom), y)
        self._draw_wavy_symbol(
            painter,
            rect.right() + int(2 * self.zoom),
            y,
            int(19 * self.zoom),
            int(3 * self.zoom),
        )

    def _draw_dashed_text_symbol(self, painter: QPainter, text: str, x: int, y: int, color: QColor) -> None:
        painter.setPen(QPen(color, max(1, int(1.2 * self.zoom))))
        rect = self._draw_text_symbol(painter, text, x, y)
        dash_pen = QPen(color, max(1, int(1 * self.zoom)))
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dash_pen)
        line_y = y + int(5 * self.zoom)
        painter.drawLine(rect.right() + int(3 * self.zoom), line_y, rect.right() + int(46 * self.zoom), line_y)

    def _draw_dashed_span_text(self, painter: QPainter, text: str, start_x: int, end_x: int, y: int, color: QColor) -> None:
        painter.save()
        painter.setPen(QPen(color, max(1, int(1.05 * self.zoom))))
        rect = self._draw_text_symbol(painter, text, start_x, y)
        dash_pen = QPen(color, max(1, int(1 * self.zoom)))
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        dash_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(dash_pen)
        line_y = y + int(5 * self.zoom)
        line_start = rect.right() + int(4 * self.zoom)
        line_end = max(line_start + int(12 * self.zoom), end_x)
        painter.drawLine(line_start, line_y, line_end, line_y)
        painter.restore()

    def _draw_playback_cursor(
        self,
        painter: QPainter,
        layout: _MeasureLayout,
        measure: MeasureData,
        tab_left: int,
        tab_right: int,
        tab_top: int,
        string_gap: int,
    ) -> None:
        if self.playback_tick is None:
            return
        measure_start = measure.start_tick
        measure_end = measure.start_tick + measure.length_ticks
        if self.playback_tick < measure_start or self.playback_tick > measure_end:
            return
        ratio = (self.playback_tick - measure_start) / max(1, measure.length_ticks)
        x = tab_left + int(max(0.0, min(1.0, ratio)) * max(1, tab_right - tab_left))
        painter.setPen(QPen(QColor("#d92727"), max(2, int(2 * self.zoom))))
        painter.drawLine(x, tab_top - int(18 * self.zoom), x, tab_top + ((len(self.song.track.string_names) - 1) * string_gap) + int(12 * self.zoom) if self.song else layout.rect.bottom())

    def _tab_geometry(self, rect: QRect) -> tuple[int, int, int, int]:
        top = rect.top() + int(54 * self.zoom)
        string_gap = max(10, int(13 * self.zoom))
        return rect.left(), rect.right(), top, string_gap

    def _rebuild_layout(self) -> None:
        self._measure_layouts = []
        if self.song is None:
            self._content_size = QSize(max(360, self.width()), 260)
            self.setMinimumWidth(0)
            self.setMinimumHeight(self._content_size.height())
            self.updateGeometry()
            return

        margin = int(12 * self.zoom)
        label_width = int(42 * self.zoom)
        system_gap = int(24 * self.zoom)
        available_width = max(260, self.width() - (margin * 2))
        system_left = margin + label_width
        system_right = margin + available_width
        system_width = max(160, system_right - system_left)
        x = system_left
        y = margin
        string_count = max(1, len(self.song.track.string_pitches))
        row_height = int((88 + (string_count * 15)) * self.zoom)
        for index, measure in enumerate(self.song.track.measures):
            note_slots = max(2, sum(1 for beat in measure.beats if beat.notes))
            width = int(max(118 * self.zoom, 34 * self.zoom + note_slots * 34 * self.zoom))
            width = min(width, system_width)
            if x > system_left and x + width > system_right:
                x = system_left
                y += row_height + system_gap
            self._measure_layouts.append(_MeasureLayout(index, QRect(x, y, width, row_height)))
            x += width
        self._content_size = QSize(max(360, self.width()), max(240, y + row_height + margin))
        self.setMinimumWidth(0)
        self.setMinimumHeight(self._content_size.height())
        self.updateGeometry()

    def _row_groups(self) -> list[list[_MeasureLayout]]:
        rows: list[list[_MeasureLayout]] = []
        for layout in self._measure_layouts:
            if not rows or rows[-1][0].rect.top() != layout.rect.top():
                rows.append([layout])
            else:
                rows[-1].append(layout)
        return rows

    def _is_row_start(self, layout: _MeasureLayout) -> bool:
        return not any(
            other.index < layout.index and other.rect.top() == layout.rect.top()
            for other in self._measure_layouts
        )


class StandaloneMetronome(QObject):
    tickingChanged = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.output = MidiOutput()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.bpm = 120
        self.beats_per_bar = 4
        self.beat_index = 0
        self.ticking = False

    def set_bpm(self, bpm: int) -> None:
        self.bpm = max(20, min(500, int(bpm)))
        self.timer.setInterval(self._interval_ms())

    def set_beats_per_bar(self, beats: int) -> None:
        self.beats_per_bar = max(1, min(12, int(beats)))

    def start(self) -> None:
        if self.ticking:
            return
        self.beat_index = 0
        self.timer.setInterval(self._interval_ms())
        self.timer.start()
        self.ticking = True
        self.tickingChanged.emit(True)
        self._tick()

    def stop(self) -> None:
        if not self.ticking:
            return
        self.timer.stop()
        self.output.all_notes_off()
        self.ticking = False
        self.tickingChanged.emit(False)

    def toggle(self) -> None:
        if self.ticking:
            self.stop()
        else:
            self.start()

    def close(self) -> None:
        self.stop()
        self.output.close()

    def _interval_ms(self) -> int:
        return max(1, round(60000 / max(1, self.bpm)))

    def _tick(self) -> None:
        note = 76 if self.beat_index == 0 else 77
        velocity = 112 if self.beat_index == 0 else 80
        self.output.note_on(note, velocity, channel=9)
        QTimer.singleShot(70, lambda item=note: self.output.note_off(item, channel=9))
        self.beat_index = (self.beat_index + 1) % self.beats_per_bar


class RecordingController(QObject):
    recordingChanged = pyqtSignal(bool)
    statusChanged = pyqtSignal(str)
    recordingSaved = pyqtSignal(object)
    playbackChanged = pyqtSignal(bool)
    playbackPositionChanged = pyqtSignal(int)
    playbackDurationChanged = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.available = all(
            item is not None
            for item in (QAudioInput, QAudioOutput, QMediaCaptureSession, QMediaDevices, QMediaFormat, QMediaPlayer, QMediaRecorder)
        )
        self.capture_session = None
        self.recorder = None
        self.audio_input = None
        self.player = None
        self.audio_output = None
        self.recording = False
        self.playing = False
        self.last_recording: Path | None = None
        self.playback_file: Path | None = None
        self._recording_saved_emitted: Path | None = None
        if self.available:
            self.capture_session = QMediaCaptureSession(self)
            self.recorder = QMediaRecorder(self)
            self.capture_session.setRecorder(self.recorder)
            media_format = QMediaFormat()
            media_format.setFileFormat(QMediaFormat.FileFormat.Wave)
            media_format.setAudioCodec(QMediaFormat.AudioCodec.Wave)
            self.recorder.setMediaFormat(media_format)
            self.recorder.setQuality(QMediaRecorder.Quality.HighQuality)
            self.player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.playbackStateChanged.connect(self._on_player_state_changed)
            self.player.positionChanged.connect(lambda position: self.playbackPositionChanged.emit(int(position)))
            self.player.durationChanged.connect(lambda duration: self.playbackDurationChanged.emit(int(duration)))

    def audio_inputs(self):
        if not self.available:
            return []
        return list(QMediaDevices.audioInputs())

    def start_recording(self, device, song_path: Path | None) -> None:
        if not self.available or self.capture_session is None or self.recorder is None:
            self.statusChanged.emit(tr("Recording unavailable"))
            return
        if self.recording:
            return
        try:
            self.stop_playback()
            self.audio_input = QAudioInput(device, self)
            self.capture_session.setAudioInput(self.audio_input)
            directory = (song_path.parent if song_path is not None else Path.cwd()) / "recordings"
            directory.mkdir(parents=True, exist_ok=True)
            stem = song_path.stem if song_path is not None else "tab"
            self.last_recording = directory / f"{stem}_recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
            self._recording_saved_emitted = None
            self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self.last_recording)))
            self.recorder.record()
            self.recording = True
            self.recordingChanged.emit(True)
            self.statusChanged.emit(_trf("Recording: {name}", name=self.last_recording.name))
        except Exception as exc:  # noqa: BLE001 - multimedia backend errors should be visible.
            self.statusChanged.emit(_trf("Recording failed: {error}", error=exc))

    def stop_recording(self) -> None:
        if not self.available or self.recorder is None or not self.recording:
            return
        self.recorder.stop()
        self.recording = False
        self.recordingChanged.emit(False)
        if self.last_recording is not None:
            self.statusChanged.emit(_trf("Recording saved: {name}", name=self.last_recording.name))
            self._emit_recording_saved()

    def play_last_recording(self, start_position: int = 0) -> None:
        self.toggle_play_recording(self.last_recording, start_position)

    def toggle_play_recording(self, path: Path | None = None, start_position: int = 0) -> None:
        if self.playing:
            self.stop_playback()
            return
        self.play_recording(path or self.last_recording, start_position)

    def play_recording(self, path: Path | None, start_position: int = 0) -> None:
        if not self.available or self.player is None or path is None:
            self.statusChanged.emit(tr("No recording to play"))
            return
        if not path.exists():
            self.statusChanged.emit(_trf("Recording file missing: {name}", name=path.name))
            return
        self.last_recording = path
        self.playback_file = path
        source = QUrl.fromLocalFile(str(path))
        if self.player.source() != source:
            self.player.setSource(source)
        self.player.setPosition(max(0, int(start_position)))
        self.player.play()
        self.statusChanged.emit(_trf("Playing recording: {name}", name=path.name))

    def set_playback_position(self, position: int) -> None:
        if self.available and self.player is not None:
            self.player.setPosition(max(0, int(position)))

    def stop_playback(self) -> None:
        if self.player is not None:
            self.player.stop()
        if self.playing:
            self.playing = False
            self.playbackChanged.emit(False)

    def close(self) -> None:
        self.stop_recording()
        self.stop_playback()

    def _on_recorder_state_changed(self, state) -> None:
        if QMediaRecorder is not None and state != QMediaRecorder.RecorderState.RecordingState and self.recording:
            self.recording = False
            self.recordingChanged.emit(False)
            if self.last_recording is not None:
                self.statusChanged.emit(_trf("Recording saved: {name}", name=self.last_recording.name))
                self._emit_recording_saved()

    def _on_player_state_changed(self, state) -> None:
        playing = QMediaPlayer is not None and state == QMediaPlayer.PlaybackState.PlayingState
        if self.playing != playing:
            self.playing = playing
            self.playbackChanged.emit(playing)

    def _emit_recording_saved(self) -> None:
        if self.last_recording is None or self._recording_saved_emitted == self.last_recording:
            return
        self._recording_saved_emitted = self.last_recording
        self.recordingSaved.emit(self.last_recording)


class YouTubeTabPlayer(QObject):
    positionChanged = pyqtSignal(int)
    playingChanged = pyqtSignal(bool)
    finished = pyqtSignal()
    availabilityChanged = pyqtSignal(bool)
    videoReady = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.view = None
        self._web_profile = None
        self._html_server: ThreadingHTTPServer | None = None
        self._html_server_thread: Thread | None = None
        self._html_origin = ""
        self.available = False
        self.playback_available = False
        self.error = ""
        self.details: dict = {}
        self.video_id = ""
        self._video_candidates: list[str] = []
        self._failed_video_ids: set[str] = set()
        self._loaded_video_id = ""
        self._loading_video = False
        self._pending_player_script = ""
        self._ready_video_id = ""
        self.offset_seconds = 0.0
        self.song: SongData | None = None
        self.start_tick = 0
        self.end_tick = 0
        self.current_tick = 0.0
        self.speed_percent = 100
        self.repeat = False
        self.playing = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._tick)
        self.error_timer = QTimer(self)
        self.error_timer.setInterval(750)
        self.error_timer.timeout.connect(self._poll_youtube_error)
        self.clock = QElapsedTimer()
        self._load_web_engine()

    def set_details(self, details: dict | None) -> None:
        self.details = details if isinstance(details, dict) else {}
        self._failed_video_ids.clear()
        self._pending_player_script = ""
        self._loading_video = False
        self._loaded_video_id = ""
        self._ready_video_id = ""
        self.error_timer.stop()
        self.error = ""
        youtube = self.details.get("youtube") if isinstance(self.details, dict) else None
        if not isinstance(youtube, dict):
            self.video_id = ""
            self._video_candidates = []
            self.playback_available = False
            self.offset_seconds = 0.0
            self.availabilityChanged.emit(False)
            return
        self._video_candidates = _youtube_video_candidates(youtube)
        self.video_id = self._video_candidates[0] if self._video_candidates else ""
        sync = youtube.get("sync")
        try:
            self.offset_seconds = float(sync.get("offset_seconds", 0.0)) if isinstance(sync, dict) else 0.0
        except (TypeError, ValueError):
            self.offset_seconds = 0.0
        self.playback_available = bool(self.video_id and self.available)
        if self.playback_available:
            self._load_video(self.video_id)
        self.availabilityChanged.emit(self.playback_available)

    def start(
        self,
        song: SongData,
        start_measure_index: int,
        end_measure_index: int,
        *,
        repeat: bool,
        speed_percent: int,
        play_from_measure_index: int | None = None,
        play_from_tick: int | None = None,
    ) -> None:
        if not self.playback_available or not self.video_id or not song.track.measures:
            return
        self.stop(emit=False)
        start_measure_index, end_measure_index = self._clamp_range(start_measure_index, end_measure_index, len(song.track.measures))
        measures = song.track.measures[start_measure_index : end_measure_index + 1]
        self.song = song
        self.repeat = repeat
        self.speed_percent = max(25, min(300, int(speed_percent)))
        self.start_tick = measures[0].start_tick
        self.end_tick = measures[-1].start_tick + measures[-1].length_ticks
        self.current_tick = float(self._play_from_tick(song, start_measure_index, end_measure_index, play_from_measure_index, play_from_tick))
        loaded = self._load_video(self.video_id)
        self._run_or_queue_js(
            f"playAt({self._tick_to_seconds(self.current_tick):.3f}, {self.speed_percent / 100.0:.3f});",
            defer=loaded,
        )
        self._start_youtube_error_poll()
        self.clock.start()
        self.timer.start()
        self.playing = True
        self.playingChanged.emit(True)
        self.positionChanged.emit(int(self.current_tick))

    def stop(self, emit: bool = True) -> None:
        self.timer.stop()
        self._pending_player_script = ""
        self._run_js("pauseVideo();")
        was_playing = self.playing
        self.playing = False
        if emit and was_playing:
            self.playingChanged.emit(False)
            self.finished.emit()

    def set_speed_percent(self, value: int) -> None:
        self.speed_percent = max(25, min(300, int(value)))
        if self.playing:
            self._run_js(f"setRate({self.speed_percent / 100.0:.3f});")

    def set_offset_milliseconds(self, value: int) -> None:
        self.offset_seconds = int(value) / 1000.0
        if self.playing:
            self._run_js(f"seekToSeconds({self._tick_to_seconds(self.current_tick):.3f});")

    def close(self) -> None:
        self.stop(emit=False)
        self.error_timer.stop()
        if self._html_server is not None:
            self._html_server.shutdown()
            self._html_server.server_close()
            self._html_server = None
            self._html_server_thread = None
            self._html_origin = ""

    def _tick(self) -> None:
        if self.song is None or not self.playing:
            return
        elapsed_ms = max(0, self.clock.restart())
        ticks_per_ms = (self.song.tempo * (self.speed_percent / 100.0) * TICKS_PER_QUARTER) / 60000.0
        self.current_tick += elapsed_ms * ticks_per_ms
        if self.current_tick >= self.end_tick:
            if self.repeat:
                self.current_tick = float(self.start_tick)
                self._run_js(f"seekToSeconds({self._tick_to_seconds(self.current_tick):.3f});")
                self.clock.restart()
                self.positionChanged.emit(self.start_tick)
                return
            self.positionChanged.emit(self.end_tick)
            self.stop()
            return
        self.positionChanged.emit(int(self.current_tick))

    def _load_web_engine(self) -> None:
        _allow_qt_webengine_autoplay()
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception as exc:  # noqa: BLE001 - WebEngine is optional.
            self.error = str(exc)
            self.available = False
            return

        self._web_profile = QWebEngineProfile(f"tab-analyzer-youtube-{os.getpid()}-{id(self)}", self)
        _set_webengine_autoplay_allowed(self._web_profile.settings(), QWebEngineSettings)
        self.view = QWebEngineView(self.parent_widget)
        self.view.setPage(QWebEnginePage(self._web_profile, self.view))
        self.view.loadFinished.connect(self._on_youtube_load_finished)
        _set_webengine_autoplay_allowed(self.view.settings(), QWebEngineSettings)
        _set_webengine_autoplay_allowed(self.view.page().settings(), QWebEngineSettings)
        _make_youtube_view_non_interactive(self.view)
        _set_youtube_view_size(self.view)
        self.view.hide()
        self.available = True

    def _load_video(self, video_id: str, status_message: str = "") -> bool:
        if self.view is None:
            return False
        if self._loaded_video_id == video_id:
            return False
        origin = self._ensure_html_server()
        if not origin:
            return False
        self._loading_video = True
        self._ready_video_id = ""
        self.view.load(QUrl(_youtube_player_url(origin, video_id, status_message)))
        self._loaded_video_id = video_id
        self._start_youtube_error_poll()
        return True

    def _ensure_html_server(self) -> str:
        if self._html_server is not None and self._html_origin:
            return self._html_origin

        origin_holder: dict[str, str] = {}

        class YouTubeHtmlHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib callback name.
                parsed = urlparse(self.path)
                if parsed.path != "/youtube-player":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                video_id = (parse_qs(parsed.query).get("video_id") or [""])[0].strip()
                if not video_id:
                    self.send_error(HTTPStatus.BAD_REQUEST)
                    return
                status_message = (parse_qs(parsed.query).get("status") or [""])[0].strip()
                payload = _youtube_player_html(video_id, origin_holder["origin"], status_message).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args) -> None:
                return

        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), YouTubeHtmlHandler)
        except OSError as exc:
            self.error = str(exc)
            return ""
        server.daemon_threads = True
        self._html_server = server
        self._html_origin = f"http://127.0.0.1:{server.server_port}"
        origin_holder["origin"] = self._html_origin
        self._html_server_thread = Thread(target=server.serve_forever, name="TabAnalyzerYouTubeHtmlServer", daemon=True)
        self._html_server_thread.start()
        return self._html_origin

    def _on_youtube_load_finished(self, ok: bool) -> None:
        self._loading_video = False
        if not ok:
            self.error = "YouTube player page could not be loaded."
            self.playback_available = False
            self.availabilityChanged.emit(False)
            return
        if self._pending_player_script:
            script = self._pending_player_script
            self._pending_player_script = ""
            self._run_js(script)
        self._start_youtube_error_poll()

    def _start_youtube_error_poll(self) -> None:
        if self.view is None or not self.video_id:
            return
        if not self.error_timer.isActive():
            self.error_timer.start()

    def _poll_youtube_error(self) -> None:
        if self.view is None or not self.video_id:
            self.error_timer.stop()
            return
        self._run_js_result(
            "({"
            "error: document.body ? (document.body.dataset.youtubeError || '') : '', "
            "ready: document.body ? (document.body.dataset.youtubeReady || '') : '', "
            "videoId: document.body ? (document.body.dataset.youtubeErrorVideoId || document.body.dataset.youtubeVideoId || '') : ''"
            "})",
            self._on_youtube_player_state,
        )

    def _on_youtube_player_state(self, state: object) -> None:
        if not isinstance(state, dict):
            return
        state_video_id = str(state.get("videoId") or "").strip()
        if state_video_id and state_video_id != self._loaded_video_id:
            return
        error_code = str(state.get("error") or "").strip()
        if error_code:
            self._handle_youtube_error(error_code)
            return
        if str(state.get("ready") or "").strip() == "1":
            self._handle_youtube_ready(state_video_id or self._loaded_video_id)

    def _handle_youtube_ready(self, video_id: str) -> None:
        video_id = str(video_id or "").strip()
        if not video_id or self._ready_video_id == video_id:
            return
        self._ready_video_id = video_id
        self.error = ""
        self.videoReady.emit(video_id)

    def _handle_youtube_error(self, error_code: str) -> None:
        failed_video_id = self._loaded_video_id or self.video_id
        if failed_video_id:
            self._failed_video_ids.add(failed_video_id)
        self.error = f"YouTube error {error_code}"
        next_video_id = self._next_video_candidate()
        if next_video_id:
            self.video_id = next_video_id
            self.playback_available = True
            loaded = self._load_video(next_video_id, tr("Changing to another video."))
            if self.playing:
                self._run_or_queue_js(
                    f"playAt({self._tick_to_seconds(self.current_tick):.3f}, {self.speed_percent / 100.0:.3f});",
                    defer=loaded,
                )
            self.availabilityChanged.emit(True)
            return

        self.error_timer.stop()
        self.playback_available = False
        self._set_youtube_message(tr("No replacement video is available."))
        was_playing = self.playing
        self.stop(emit=False)
        self.availabilityChanged.emit(False)
        if was_playing:
            self.playingChanged.emit(False)
            self.finished.emit()

    def _next_video_candidate(self) -> str:
        for candidate in self._video_candidates:
            if candidate not in self._failed_video_ids:
                return candidate
        return ""

    def _run_or_queue_js(self, script: str, *, defer: bool) -> None:
        if defer or self._loading_video:
            self._pending_player_script = script
            return
        self._run_js(script)

    def _set_youtube_message(self, message: str) -> None:
        self._run_js(f"setStatus({json.dumps(message)});")

    def _run_js(self, script: str) -> None:
        if self.view is None:
            return
        try:
            self.view.page().runJavaScript(script)
        except RuntimeError:
            return

    def _run_js_result(self, script: str, callback) -> None:
        if self.view is None:
            return
        try:
            self.view.page().runJavaScript(script, callback)
        except TypeError:
            self.error_timer.stop()
        except RuntimeError:
            return

    def _tick_to_seconds(self, tick: float) -> float:
        if self.song is None:
            return max(0.0, self.offset_seconds)
        song_seconds = (tick / TICKS_PER_QUARTER) * (60.0 / max(1, self.song.tempo))
        return max(0.0, song_seconds + self.offset_seconds)

    def _play_from_tick(
        self,
        song: SongData,
        start_measure_index: int,
        end_measure_index: int,
        play_from_measure_index: int | None,
        play_from_tick: int | None,
    ) -> int:
        if play_from_tick is not None:
            return max(self.start_tick, min(int(play_from_tick), self.end_tick))
        if play_from_measure_index is None:
            return self.start_tick
        play_from_measure_index = max(start_measure_index, min(play_from_measure_index, end_measure_index))
        return song.track.measures[play_from_measure_index].start_tick

    def _clamp_range(self, start_index: int, end_index: int, measure_count: int) -> tuple[int, int]:
        start = max(0, min(start_index, measure_count - 1))
        end = max(0, min(end_index, measure_count - 1))
        if end < start:
            start, end = end, start
        return start, end


class SongsterrPagePanel(QWidget):
    playbackPositionChanged = pyqtSignal(object)

    _STAGE_BRIDGE_SCRIPT = """
(function () {
    try {
        Object.defineProperty(window, "__STAGE__", {
            get: function () { return "tab-analyzer"; },
            set: function () {},
            configurable: false
        });
        window.__TAB_ANALYZER_SONGSTERR__ = true;
    } catch (error) {}
})();
"""

    _AD_CLEANUP_SCRIPT = r"""
(function () {
    if (window.__TAB_ANALYZER_SONGSTERR_AD_CLEANUP__) {
        return;
    }
    window.__TAB_ANALYZER_SONGSTERR_AD_CLEANUP__ = true;

    const STYLE_ID = "tab-analyzer-songsterr-ad-cleanup-style";
    const AD_HOST_PATTERN = /(2mdn\.net|aaxads\.com|adform\.net|adnxs\.com|adsafeprotected\.com|adsrvr\.org|adservice\.google\.com|amazon-adsystem\.com|casalemedia\.com|criteo\.com|criteo\.net|doubleclick\.net|fundingchoicesmessages\.google\.com|googlesyndication\.com|googletagmanager\.com|googletagservices\.com|imasdk\.googleapis\.com|lijit\.com|media\.net|moatads\.com|openx\.net|outbrain\.com|pubmatic\.com|quantserve\.com|rubiconproject\.com|scorecardresearch\.com|smartadserver\.com|taboola\.com|yieldmo\.com)/i;
    const AD_TOKEN_PATTERN = /(^|[\s_-])(ad|ads|advert|advertisement|adslot|ad-unit|adunit|ad-container|adcontainer|ad-banner|adbanner|gpt-ad|adsbygoogle|google-auto-placed)([\s_-]|$)/i;
    const AD_IFRAME_SELECTOR = [
        'iframe[src*="2mdn.net"]',
        'iframe[src*="adform.net"]',
        'iframe[src*="adnxs.com"]',
        'iframe[src*="adsafeprotected.com"]',
        'iframe[src*="adsrvr.org"]',
        'iframe[src*="amazon-adsystem.com"]',
        'iframe[src*="criteo.com"]',
        'iframe[src*="doubleclick.net"]',
        'iframe[src*="googlesyndication.com"]',
        'iframe[src*="googletagservices.com"]',
        'iframe[src*="openx.net"]',
        'iframe[src*="pubmatic.com"]',
        'iframe[src*="rubiconproject.com"]',
        'iframe[src*="smartadserver.com"]'
    ].join(',');
    const HIDE_SELECTOR = [
        'ins.adsbygoogle',
        '.adsbygoogle',
        '.google-auto-placed',
        '[id^="google_ads_iframe_"]',
        '[id*="div-gpt-ad"]',
        '[data-ad-client]',
        '[data-ad-slot]',
        AD_IFRAME_SELECTOR,
        '.video-ads',
        '.ytp-ad-image-overlay',
        '.ytp-ad-module',
        '.ytp-ad-overlay-container',
        '.ytp-ad-player-overlay',
        '.ytp-ad-text-overlay'
    ].join(',');
    const PROTECTED_SELECTOR = [
        '#apptab',
        '#tablature',
        '#tablist'
    ].join(',');
    const COLLAPSED_STYLE_PROPS = [
        "display",
        "visibility",
        "opacity",
        "pointer-events",
        "width",
        "height",
        "min-width",
        "min-height",
        "max-width",
        "max-height",
        "margin",
        "padding",
        "border",
        "overflow"
    ];
    const COLLAPSE_CSS = `
${HIDE_SELECTOR} {
    display: none !important;
    visibility: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    width: 0 !important;
    height: 0 !important;
    min-width: 0 !important;
    min-height: 0 !important;
    max-width: 0 !important;
    max-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    overflow: hidden !important;
}
`;

    function installStyle() {
        const root = document.head || document.documentElement;
        if (!root || document.getElementById(STYLE_ID)) {
            return;
        }
        const style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = COLLAPSE_CSS;
        root.appendChild(style);
    }

    function attrString(element) {
        if (!element) {
            return "";
        }
        const className = typeof element.className === "string"
            ? element.className
            : String(element.getAttribute("class") || "");
        return [
            element.id,
            className,
            element.getAttribute("aria-label"),
            element.getAttribute("data-ad-client"),
            element.getAttribute("data-ad-format"),
            element.getAttribute("data-ad-slot"),
            element.getAttribute("data-google-query-id")
        ].filter(Boolean).join(" ");
    }

    function srcLooksLikeAd(element) {
        const src = String(
            element.getAttribute("src")
            || element.getAttribute("data-src")
            || element.getAttribute("href")
            || ""
        );
        return AD_HOST_PATTERN.test(src);
    }

    function hasAdToken(element) {
        return AD_TOKEN_PATTERN.test(attrString(element));
    }

    function containsAdFrame(element) {
        try {
            return !!element.querySelector(AD_IFRAME_SELECTOR);
        } catch (error) {
            return false;
        }
    }

    function isProtectedSongsterrContent(element) {
        if (!element) {
            return false;
        }
        try {
            return !!(
                element.closest(PROTECTED_SELECTOR)
                || (element.matches(PROTECTED_SELECTOR))
                || element.querySelector(PROTECTED_SELECTOR)
            );
        } catch (error) {
            return false;
        }
    }

    function isBottomAdSlot(element) {
        if (!element || element === document.body || element === document.documentElement) {
            return false;
        }
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width < 20 || rect.height < 12 || rect.height > window.innerHeight * 0.5) {
            return false;
        }
        const style = window.getComputedStyle(element);
        const isAnchored = style.position === "fixed" || style.position === "sticky";
        const isNearBottom = rect.top >= window.innerHeight * 0.45 || Math.abs(window.innerHeight - rect.bottom) <= 180;
        return isAnchored && isNearBottom && (hasAdToken(element) || containsAdFrame(element));
    }

    function collapseElement(element) {
        if (!element || element === document.body || element === document.documentElement || isProtectedSongsterrContent(element)) {
            return;
        }
        element.setAttribute("data-tab-analyzer-ad-hidden", "1");
        element.style.setProperty("display", "none", "important");
        element.style.setProperty("visibility", "hidden", "important");
        element.style.setProperty("opacity", "0", "important");
        element.style.setProperty("pointer-events", "none", "important");
        element.style.setProperty("width", "0", "important");
        element.style.setProperty("height", "0", "important");
        element.style.setProperty("min-width", "0", "important");
        element.style.setProperty("min-height", "0", "important");
        element.style.setProperty("max-width", "0", "important");
        element.style.setProperty("max-height", "0", "important");
        element.style.setProperty("margin", "0", "important");
        element.style.setProperty("padding", "0", "important");
        element.style.setProperty("border", "0", "important");
        element.style.setProperty("overflow", "hidden", "important");
    }

    function adRootFor(element) {
        let root = element;
        for (let depth = 0; depth < 4; depth += 1) {
            const parent = root && root.parentElement;
            if (!parent || parent === document.body || parent === document.documentElement) {
                break;
            }
            if (isProtectedSongsterrContent(parent)) {
                break;
            }
            const rect = parent.getBoundingClientRect();
            const compactWrapper = rect.height <= 360 && rect.width <= Math.max(window.innerWidth, 720)
                && (parent.children.length <= 4 || hasAdToken(parent) || containsAdFrame(parent));
            if (hasAdToken(parent) || parent.matches(".adsbygoogle, .google-auto-placed") || compactWrapper) {
                root = parent;
                continue;
            }
            break;
        }
        return root || element;
    }

    function hide(element) {
        const root = adRootFor(element);
        if (!isProtectedSongsterrContent(root)) {
            collapseElement(root);
        }
    }

    function restoreCollapsedElement(element) {
        if (!element || element === document.body || element === document.documentElement) {
            return;
        }
        if (element.getAttribute("data-tab-analyzer-ad-hidden") !== "1") {
            return;
        }
        element.removeAttribute("data-tab-analyzer-ad-hidden");
        COLLAPSED_STYLE_PROPS.forEach((property) => {
            element.style.removeProperty(property);
        });
    }

    function restoreProtectedContent() {
        try {
            document.querySelectorAll(PROTECTED_SELECTOR).forEach((protectedElement) => {
                let current = protectedElement;
                while (current && current !== document.body && current !== document.documentElement) {
                    restoreCollapsedElement(current);
                    current = current.parentElement;
                }
                protectedElement.querySelectorAll('[data-tab-analyzer-ad-hidden="1"]').forEach(restoreCollapsedElement);
            });
        } catch (error) {}
    }

    function cleanupAds() {
        installStyle();
        try {
            document.querySelectorAll(HIDE_SELECTOR).forEach(hide);
            document.querySelectorAll("iframe, ins, aside, section, div").forEach((element) => {
                if (srcLooksLikeAd(element) || hasAdToken(element) || containsAdFrame(element) || isBottomAdSlot(element)) {
                    hide(element);
                }
            });
            restoreProtectedContent();
        } catch (error) {}
    }

    let cleanupScheduled = false;
    function scheduleCleanup() {
        if (cleanupScheduled) {
            return;
        }
        cleanupScheduled = true;
        window.setTimeout(() => {
            cleanupScheduled = false;
            cleanupAds();
        }, 80);
    }

    cleanupAds();
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", cleanupAds, { once: true });
    }
    window.addEventListener("load", cleanupAds, { once: true });
    try {
        const observerRoot = document.documentElement || document;
        new MutationObserver(scheduleCleanup).observe(observerRoot, { childList: true, subtree: true, attributes: true });
    } catch (error) {}
})();
"""

    _PLAYBACK_STATE_SCRIPT = """
(function () {
    const store = window.__store__;
    if (!store || typeof store.get !== "function") {
        return { available: false, reason: "store" };
    }
    const state = store.get();
    const cursorState = state && state.cursor && state.cursor.position;
    const part = state && state.part && state.part.current;
    const measures = part && Array.isArray(part.measures) ? part.measures : [];
    const player = state && state.player ? state.player : {};
    const shouldPlay = !!player.shouldPlay || !!(player.instance && player.instance.isPlaying);
    if (!cursorState || !measures.length) {
        return {
            available: false,
            reason: "part",
            shouldPlay: shouldPlay
        };
    }
    let cursorValue = cursorState.cursor;
    if (player && player.instance && typeof player.instance.getCursor === "function") {
        const liveCursor = player.instance.getCursor();
        if (Number.isFinite(Number(liveCursor))) {
            cursorValue = liveCursor;
        }
    }
    const cursor = Number(cursorValue);
    if (!Number.isFinite(cursor)) {
        return { available: false, reason: "cursor", shouldPlay: shouldPlay };
    }
    const layoutPlaybackState = function (position) {
        for (let measureIndex = 0; measureIndex < measures.length; measureIndex += 1) {
            const measure = measures[measureIndex];
            const layouts = Array.isArray(measure && measure.layouts) ? measure.layouts : [];
            const beatLayouts = [];
            for (const layout of layouts) {
                const items = Array.isArray(layout && layout.beatsLayouts) ? layout.beatsLayouts : [];
                for (const item of items) {
                    if (!item || item.isAddable) {
                        continue;
                    }
                    const duration = Number(item.duration);
                    const occurrences = Array.isArray(item.occurrences) ? item.occurrences : [];
                    if (!Number.isFinite(duration) || duration <= 0 || duration > 3600000 || !occurrences.length) {
                        continue;
                    }
                    beatLayouts.push({ item: item, duration: duration, occurrences: occurrences });
                }
            }
            if (!beatLayouts.length) {
                continue;
            }
            const occurrenceCount = Math.max(...beatLayouts.map((beat) => beat.occurrences.length));
            for (let occurrenceIndex = 0; occurrenceIndex < occurrenceCount; occurrenceIndex += 1) {
                const firstBeat = beatLayouts[0];
                const lastBeat = beatLayouts[beatLayouts.length - 1];
                const start = Number(firstBeat.occurrences[Math.min(occurrenceIndex, firstBeat.occurrences.length - 1)]);
                const lastStart = Number(lastBeat.occurrences[Math.min(occurrenceIndex, lastBeat.occurrences.length - 1)]);
                const end = lastStart + lastBeat.duration;
                if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
                    continue;
                }
                if (position >= start && position < end) {
                    return {
                available: true,
                measureIndex: measureIndex,
                ratio: Math.max(0, Math.min(0.999999, (position - start) / (end - start))),
                cursor: position,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "layout"
            };
                }
            }
        }
        return null;
    };
    const durationUnits = function (duration) {
        if (!Array.isArray(duration) || duration.length < 2) {
            return 0;
        }
        const numerator = Number(duration[0]);
        const denominator = Number(duration[1]);
        if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator === 0) {
            return 0;
        }
        return Math.max(0, (4 * 960 * numerator) / denominator);
    };
    const measureLength = function (measure, signature) {
        const nextSignature = Array.isArray(measure && measure.signature) ? measure.signature : signature;
        const voices = Array.isArray(measure && measure.voices) ? measure.voices : [];
        let longest = 0;
        for (const voice of voices) {
            const beats = Array.isArray(voice && voice.beats) ? voice.beats : [];
            let total = 0;
            for (const beat of beats) {
                total += durationUnits(beat && beat.duration);
            }
            if (total > longest) {
                longest = total;
            }
        }
        if (longest > 0) {
            return { length: longest, signature: nextSignature };
        }
        const numerator = Number(nextSignature && nextSignature[0]) || 4;
        const denominator = Number(nextSignature && nextSignature[1]) || 4;
        return { length: Math.max(1, (4 * 960 * numerator) / denominator), signature: nextSignature };
    };
    const tempoAtMeasure = function (measureIndex) {
        const automations = part && part.automations && Array.isArray(part.automations.tempo)
            ? part.automations.tempo
            : [];
        let bpm = 120;
        for (const automation of automations) {
            const automationMeasure = Number(automation && automation.measure);
            const automationBpm = Number(automation && automation.bpm);
            if (Number.isFinite(automationMeasure) && automationMeasure <= measureIndex && Number.isFinite(automationBpm) && automationBpm > 0) {
                bpm = automationBpm;
            }
        }
        return bpm;
    };
    const measureDurationMs = function (measure, signature, measureIndex) {
        const current = measureLength(measure, signature);
        const bpm = tempoAtMeasure(measureIndex);
        return {
            duration: (current.length / 960) * (60000 / bpm),
            signature: current.signature
        };
    };
    const beatStartRatio = function (measure, voiceIndex, beatIndex, signature) {
        const current = measureLength(measure, signature);
        const length = Math.max(1, current.length);
        const voices = Array.isArray(measure && measure.voices) ? measure.voices : [];
        const voice = voices[Math.max(0, voiceIndex)] || voices[0];
        const beats = Array.isArray(voice && voice.beats) ? voice.beats : [];
        let start = 0;
        const end = Math.max(0, Math.min(beatIndex, beats.length));
        for (let index = 0; index < end; index += 1) {
            start += durationUnits(beats[index] && beats[index].duration);
        }
        return Math.max(0, Math.min(0.999999, start / length));
    };
    const editorCursor = state && state.editorUI && Array.isArray(state.editorUI.cursor)
        && Array.isArray(state.editorUI.cursor[0])
        ? state.editorUI.cursor[0]
        : null;
    if (!shouldPlay && editorCursor) {
        const editorMeasureIndex = Number(editorCursor[1]);
        if (Number.isInteger(editorMeasureIndex) && editorMeasureIndex >= 0 && editorMeasureIndex < measures.length) {
            const editorVoiceIndex = Number.isInteger(Number(editorCursor[2])) ? Number(editorCursor[2]) : 0;
            const editorBeatIndex = Number.isInteger(Number(editorCursor[3])) ? Number(editorCursor[3]) : 0;
            return {
                available: true,
                measureIndex: editorMeasureIndex,
                ratio: beatStartRatio(measures[editorMeasureIndex], editorVoiceIndex, editorBeatIndex, [4, 4]),
                cursor: cursor,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "editor"
            };
        }
    }
    if (shouldPlay) {
        const layoutState = layoutPlaybackState(cursor);
        if (layoutState) {
            return layoutState;
        }
    }
    let signature = [4, 4];
    let start = 0;
    const position = Math.max(0, cursor);
    for (let index = 0; index < measures.length; index += 1) {
        const current = measureDurationMs(measures[index], signature, index);
        signature = current.signature;
        const length = Math.max(1, current.duration);
        const isLast = index === measures.length - 1;
        if (position < start + length || isLast) {
            const ratio = Math.max(0, Math.min(0.999999, (position - start) / length));
            return {
                available: true,
                measureIndex: index,
                ratio: ratio,
                cursor: position,
                shouldPlay: shouldPlay,
                speed: Number(player.speed) || 100,
                source: "timeline"
            };
        }
        start += length;
    }
    return { available: false, reason: "range", shouldPlay: shouldPlay };
})();
"""

    def __init__(self) -> None:
        super().__init__()
        self._url = ""
        self._web_profile = None
        self._ad_request_interceptor = None
        self.view = None
        self._poll_in_flight = False
        self._last_state_key: tuple[int, int, bool] | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(90)
        self._poll_timer.timeout.connect(self._poll_playback_state)
        self.fallback_browser = QTextBrowser()
        self.fallback_browser.setOpenExternalLinks(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if self._load_web_engine():
            layout.addWidget(self.view, 1)
        else:
            layout.addWidget(self.fallback_browser, 1)
            self._update_fallback_html()

    def set_url(self, url: str) -> None:
        target = str(url or "").strip()
        if target == self._url:
            return
        self._url = target
        self._last_state_key = None
        self._poll_in_flight = False
        if self.view is not None:
            if target:
                self.view.load(QUrl(target))
                self._poll_timer.start()
            else:
                self._poll_timer.stop()
                self.view.setHtml("")
                self.playbackPositionChanged.emit(None)
            return
        self._poll_timer.stop()
        self.playbackPositionChanged.emit(None)
        self._update_fallback_html()

    def current_url(self) -> str:
        return self._url

    def shutdown(self) -> None:
        self._poll_timer.stop()
        if self.view is None:
            return
        try:
            self.view.stop()
        except RuntimeError:
            return

    def _load_web_engine(self) -> bool:
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception:
            return False
        try:
            from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInterceptor
        except Exception:
            QWebEngineUrlRequestInterceptor = None

        try:
            storage_root = Path.home() / ".tab_analyzer" / "songsterr_web_sessions"
            storage_root.mkdir(parents=True, exist_ok=True)
            profile = QWebEngineProfile(f"tab-analyzer-songsterr-page-{os.getpid()}-{id(self)}", self)
            profile.setPersistentStoragePath(str(storage_root))
            profile.setCachePath(str(storage_root / "page_cache"))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
            if QWebEngineUrlRequestInterceptor is not None:
                class SongsterrAdRequestInterceptor(QWebEngineUrlRequestInterceptor):
                    def interceptRequest(self, info) -> None:  # noqa: N802 - Qt API name.
                        try:
                            host = info.requestUrl().host()
                        except Exception:
                            return
                        if _is_songsterr_ad_request_host(host):
                            info.block(True)

                self._ad_request_interceptor = SongsterrAdRequestInterceptor(profile)
                profile.setUrlRequestInterceptor(self._ad_request_interceptor)
            try:
                from PyQt6.QtWebEngineCore import QWebEngineScript

                bridge_script = QWebEngineScript()
                bridge_script.setName("TabAnalyzerSongsterrBridge")
                bridge_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                bridge_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                bridge_script.setRunsOnSubFrames(False)
                bridge_script.setSourceCode(self._STAGE_BRIDGE_SCRIPT)
                profile.scripts().insert(bridge_script)

                ad_cleanup_script = QWebEngineScript()
                ad_cleanup_script.setName("TabAnalyzerSongsterrAdCleanup")
                ad_cleanup_script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
                ad_cleanup_script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
                ad_cleanup_script.setRunsOnSubFrames(True)
                ad_cleanup_script.setSourceCode(self._AD_CLEANUP_SCRIPT)
                profile.scripts().insert(ad_cleanup_script)
            except Exception:
                pass
            self._web_profile = profile
            self.view = QWebEngineView(self)
            self.view.setPage(QWebEnginePage(profile, self.view))
        except Exception:
            self._web_profile = None
            self._ad_request_interceptor = None
            self.view = None
            return False
        return True

    def _poll_playback_state(self) -> None:
        if self.view is None or not self._url or self._poll_in_flight:
            return
        try:
            page = self.view.page()
        except RuntimeError:
            self._poll_timer.stop()
            return
        self._poll_in_flight = True
        try:
            page.runJavaScript(self._PLAYBACK_STATE_SCRIPT, self._on_playback_state_polled)
        except RuntimeError:
            self._poll_in_flight = False
            self._poll_timer.stop()

    def _on_playback_state_polled(self, state: object) -> None:
        self._poll_in_flight = False
        if not isinstance(state, dict) or not state.get("available"):
            should_play = bool(state.get("shouldPlay")) if isinstance(state, dict) else False
            key = (-1, -1, should_play)
            if key != self._last_state_key:
                self._last_state_key = key
                self.playbackPositionChanged.emit(None)
            return

        try:
            measure_index = int(state.get("measureIndex", 0))
            ratio = float(state.get("ratio", 0.0))
        except (TypeError, ValueError):
            return
        should_play = bool(state.get("shouldPlay"))
        tick_bucket = int(max(0.0, min(0.999999, ratio)) * 3840)
        key = (measure_index, tick_bucket, should_play)
        if key == self._last_state_key:
            return
        self._last_state_key = key
        self.playbackPositionChanged.emit(
            {
                "measureIndex": measure_index,
                "ratio": ratio,
                "shouldPlay": should_play,
            }
        )

    def _update_fallback_html(self) -> None:
        if not self._url:
            self.fallback_browser.setHtml("")
            return
        safe_url = html.escape(self._url, quote=True)
        safe_text = html.escape(self._url)
        self.fallback_browser.setHtml(
            "<div style='font-family: Segoe UI, sans-serif; font-size: 12pt; padding: 20px;'>"
            "<p>PyQt6-WebEngine is unavailable, so the Songsterr page can be opened in an external browser.</p>"
            f"<p><a href='{safe_url}'>{safe_text}</a></p>"
            "</div>"
        )


class MemoEditorWidget(QWidget):
    textChanged = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._syncing = False
        self._asset_base_dir: Path | None = None
        self.title_label = QLabel("M-")
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setPlaceholderText("Markdown memo")
        self.editor.textChanged.connect(self._on_text_changed)
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(700)
        self.preview_timer.timeout.connect(self._update_preview)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title_label.setStyleSheet("font-weight: 600; color: #253044;")
        layout.addWidget(self.title_label)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.preview)
        splitter.setSizes([520, 360])
        layout.addWidget(splitter, 1)

    def set_measure(self, measure_number: int | None, text: str) -> None:
        self._syncing = True
        self.title_label.setText(_trf("M{measure_number} Memo", measure_number=measure_number) if measure_number is not None else "M-")
        self.editor.setPlainText(text)
        self._syncing = False
        self._update_preview()

    def set_asset_base_dir(self, path: Path | None) -> None:
        self._asset_base_dir = path
        self.preview.setSearchPaths([str(path)] if path is not None else [])
        self._update_preview()

    def text(self) -> str:
        return self.editor.toPlainText()

    def has_editor_focus(self) -> bool:
        return self.editor.hasFocus()

    def _on_text_changed(self) -> None:
        if not self._syncing:
            self.preview_timer.start()
            self.textChanged.emit()

    def _update_preview(self) -> None:
        text = self.text()
        html_preview = _render_markdown_preview(text)
        if html_preview is None:
            self.preview.setMarkdown(text)
        else:
            self.preview.setHtml(html_preview)


class RecordingListRow(QWidget):
    playRequested = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)

    def __init__(self, path: Path, label: str) -> None:
        super().__init__()
        self.path = path
        self.delete_button = QPushButton()
        self.delete_button.setIcon(_delete_recording_icon())
        self.delete_button.setToolTip(tr("Delete recording file"))
        self.delete_button.setFixedSize(26, 26)
        self.delete_button.setIconSize(QSize(18, 18))
        self.delete_button.clicked.connect(lambda: self.deleteRequested.emit(self.path))
        self.label = QLabel(label)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.label.setStyleSheet("padding-left: 2px;")
        self.label.mousePressEvent = self.mousePressEvent  # type: ignore[method-assign]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.label, 1)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.playRequested.emit(self.path)
            event.accept()
            return
        super().mousePressEvent(event)


class TabPlaybackPanel(QWidget):
    selectionChanged = pyqtSignal(int, int)
    playbackMeasureChanged = pyqtSignal(int)
    playbackTickChanged = pyqtSignal(object)
    zoomWheelRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.selected_start = 0
        self.selected_end = 0
        self._syncing_selection = False
        self._syncing_repeat_toggle = False
        self._midi_warning_shown = False
        self._mix_click_after_recording = False
        self._playback_measure_index: int | None = None
        self._syncing_youtube_sync_spin = False
        self.details: dict = {}

        self.player = TabMidiPlayer()
        self.youtube_player = YouTubeTabPlayer(self)
        self.practice_metronome = StandaloneMetronome()
        self.tab_metronome = StandaloneMetronome()
        self.recorder = RecordingController()
        self.score = TabScoreWidget()
        self.score_scroll = QScrollArea()
        self.recording_tab = QWidget()
        self.play_button = _icon_button(_player_icon("play"), "Play")
        self.midi_radio = QRadioButton("MIDI")
        self.youtube_radio = QRadioButton("YouTube")
        self.repeat_check = QCheckBox("Repeat selection")
        self.metronome_check = QCheckBox("Metronome")
        self.repeat_start_spin = QSpinBox()
        self.repeat_end_spin = QSpinBox()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_label = QLabel("100%")
        self.speed_down_button = QPushButton("-")
        self.speed_reset_button = QPushButton("100%")
        self.speed_up_button = QPushButton("+")
        self.youtube_sync_spin = QSpinBox()
        self.youtube_sync_down_button = QPushButton("-")
        self.youtube_sync_up_button = QPushButton("+")
        self.record_metronome_check = QCheckBox("Record click")
        self.metronome_button = _icon_button(_player_icon("metronome"), "Metronome F9")
        self.record_button = _icon_button(_player_icon("record"), "Record F10")
        self.record_stop_button = _icon_button(_player_icon("stop"), "Stop recording F11")
        self.record_play_button = _icon_button(_player_icon("play"), "Play recording F12")
        self.record_playback_slider = QSlider(Qt.Orientation.Horizontal)
        self.recording_list = QListWidget()
        self.delete_all_recordings_button = QPushButton("Delete all recordings")
        self.record_input_combo = QComboBox()
        self.record_bpm_spin = QSpinBox()
        self.record_beats_spin = QSpinBox()
        self.shortcut_label = QLabel("F9 Metronome - F10 Record - F11 Stop - F12 Play")
        self.record_status_label = QLabel()
        self.midi_status_label = QLabel()
        self.youtube_status_label = QLabel()
        self._syncing_record_slider = False
        self.playback_shortcut: QShortcut | None = None

        self._build_ui()
        self.score.selectionChanged.connect(self._on_score_selection_changed)
        self.score.zoomWheelRequested.connect(self.zoomWheelRequested.emit)
        self.play_button.clicked.connect(self._play)
        self.repeat_check.toggled.connect(self._on_repeat_toggled)
        self.metronome_check.toggled.connect(self._on_tab_metronome_changed)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.repeat_start_spin.valueChanged.connect(self._on_repeat_range_changed)
        self.repeat_end_spin.valueChanged.connect(self._on_repeat_range_changed)
        self.player.positionChanged.connect(self._on_playback_position_changed)
        self.player.playingChanged.connect(self._on_playing_changed)
        self.youtube_player.positionChanged.connect(self._on_playback_position_changed)
        self.youtube_player.playingChanged.connect(self._on_playing_changed)
        self.youtube_player.availabilityChanged.connect(self._on_youtube_availability_changed)
        self.youtube_player.videoReady.connect(self._on_youtube_video_ready)
        self.midi_radio.toggled.connect(self._on_playback_source_changed)
        self.speed_down_button.clicked.connect(lambda: self._adjust_speed(-1))
        self.speed_reset_button.clicked.connect(lambda: self.speed_slider.setValue(100))
        self.speed_up_button.clicked.connect(lambda: self._adjust_speed(1))
        self.youtube_sync_down_button.clicked.connect(lambda: self._adjust_youtube_sync(-10))
        self.youtube_sync_up_button.clicked.connect(lambda: self._adjust_youtube_sync(10))
        self.youtube_sync_spin.valueChanged.connect(self._on_youtube_sync_changed)
        self.metronome_button.clicked.connect(self._toggle_practice_metronome)
        self.record_button.clicked.connect(self._start_recording)
        self.record_stop_button.clicked.connect(self._stop_recording)
        self.record_play_button.clicked.connect(self._toggle_recording_playback)
        self.record_playback_slider.sliderMoved.connect(self._on_record_playback_slider_moved)
        self.record_playback_slider.valueChanged.connect(self._on_record_playback_slider_value_changed)
        self.delete_all_recordings_button.clicked.connect(self._delete_all_recordings)
        self.record_bpm_spin.valueChanged.connect(self._on_record_metronome_changed)
        self.record_beats_spin.valueChanged.connect(self._on_record_metronome_changed)
        self.practice_metronome.tickingChanged.connect(self._on_practice_metronome_changed)
        self.recorder.recordingChanged.connect(self._on_recording_changed)
        self.recorder.statusChanged.connect(self.record_status_label.setText)
        self.recorder.recordingSaved.connect(self._on_recording_saved)
        self.recorder.playbackChanged.connect(self._on_recording_playback_changed)
        self.recorder.playbackPositionChanged.connect(self._on_recording_playback_position_changed)
        self.recorder.playbackDurationChanged.connect(self._on_recording_playback_duration_changed)
        self._install_playback_shortcuts()
        self._install_recording_shortcuts()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.play_button)
        self.youtube_radio.setEnabled(False)
        self.midi_radio.setChecked(True)
        controls.addWidget(self.youtube_radio)
        controls.addWidget(self.midi_radio)
        controls.addWidget(QLabel("Sync"))
        for button in (self.youtube_sync_down_button, self.youtube_sync_up_button):
            button.setFixedSize(26, 26)
        self.youtube_sync_spin.setRange(-300000, 300000)
        self.youtube_sync_spin.setSingleStep(10)
        self.youtube_sync_spin.setSuffix(" ms")
        self.youtube_sync_spin.setKeyboardTracking(False)
        self.youtube_sync_spin.setFixedWidth(88)
        controls.addWidget(self.youtube_sync_down_button)
        controls.addWidget(self.youtube_sync_spin)
        controls.addWidget(self.youtube_sync_up_button)
        controls.addWidget(self.repeat_check)
        controls.addWidget(QLabel("Start"))
        self.repeat_start_spin.setRange(1, 1)
        self.repeat_start_spin.setKeyboardTracking(False)
        controls.addWidget(self.repeat_start_spin)
        controls.addWidget(QLabel("End"))
        self.repeat_end_spin.setRange(1, 1)
        self.repeat_end_spin.setKeyboardTracking(False)
        controls.addWidget(self.repeat_end_spin)
        controls.addWidget(self.metronome_check)
        controls.addSpacing(8)
        controls.addWidget(QLabel("Speed"))
        self.speed_slider.setRange(50, 200)
        self.speed_slider.setValue(100)
        self.speed_slider.setFixedWidth(130)
        for button in (self.speed_down_button, self.speed_up_button):
            button.setFixedSize(26, 26)
        self.speed_reset_button.setFixedWidth(48)
        controls.addWidget(self.speed_down_button)
        controls.addWidget(self.speed_slider)
        controls.addWidget(self.speed_up_button)
        controls.addWidget(self.speed_reset_button)
        controls.addWidget(self.speed_label)
        controls.addStretch(1)
        self.midi_status_label.setText(tr("MIDI OK") if self.player.is_midi_available else tr("No MIDI output"))
        self.midi_status_label.setStyleSheet("color: #596579;")
        controls.addWidget(self.midi_status_label)
        self.youtube_status_label.setStyleSheet("color: #596579;")
        controls.addWidget(self.youtube_status_label)
        layout.addLayout(controls)
        self._update_youtube_sync_controls()
        self._build_recording_tab()

        self.score_scroll.setWidgetResizable(True)
        self.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.score_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.score_scroll.setWidget(self.score)
        self.score_scroll.installEventFilter(self)
        self.score_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.score_scroll, 1)
        self._position_youtube_view()

    def _build_recording_tab(self) -> None:
        layout = QVBoxLayout(self.recording_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        transport.addWidget(self.metronome_button)
        transport.addWidget(self.record_button)
        self.record_stop_button.setEnabled(False)
        transport.addWidget(self.record_stop_button)
        transport.addWidget(self.record_play_button)
        transport.addStretch(1)
        layout.addLayout(transport)

        self.record_playback_slider.setRange(0, 0)
        self.record_playback_slider.setEnabled(False)
        layout.addWidget(self.record_playback_slider)

        options = QHBoxLayout()
        options.setSpacing(8)
        options.addWidget(self.record_metronome_check)
        options.addWidget(QLabel("Input"))
        self.record_input_combo.setMinimumWidth(180)
        options.addWidget(self.record_input_combo, 1)
        options.addWidget(QLabel("BPM"))
        self.record_bpm_spin.setRange(40, 250)
        self.record_bpm_spin.setValue(120)
        self.record_bpm_spin.setFixedWidth(88)
        options.addWidget(self.record_bpm_spin)
        options.addWidget(QLabel("Beats"))
        self.record_beats_spin.setRange(1, 12)
        self.record_beats_spin.setValue(4)
        self.record_beats_spin.setFixedWidth(70)
        options.addWidget(self.record_beats_spin)
        layout.addLayout(options)

        self.recording_list.setAlternatingRowColors(True)
        layout.addWidget(self.recording_list, 1)
        self.delete_all_recordings_button.setEnabled(False)
        layout.addWidget(self.delete_all_recordings_button)

        self.shortcut_label.setStyleSheet("color: #596579;")
        layout.addWidget(self.shortcut_label)
        self.record_status_label.setStyleSheet("color: #596579;")
        layout.addWidget(self.record_status_label)
        self._refresh_audio_inputs()
        self._refresh_recording_files()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_youtube_view()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if (watched is self.score_scroll or watched is self.score_scroll.viewport()) and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        }:
            QTimer.singleShot(0, self._position_youtube_view)
        return super().eventFilter(watched, event)

    def set_song(self, song: SongData | None) -> None:
        self._stop()
        self.song = song
        self.details = load_details_file(song.path) if song is not None else {}
        self._playback_measure_index = None
        self.score.set_song(song)
        self.youtube_player.set_details(self.details)
        self._sync_youtube_sync_spin()
        count = len(song.track.measures) if song is not None else 1
        self.repeat_start_spin.setRange(1, max(1, count))
        self.repeat_end_spin.setRange(1, max(1, count))
        self.set_selected_measure_range(0, 0, notify=False)
        self.midi_status_label.setText(
            _trf("MIDI OK - {tempo} BPM", tempo=song.tempo) if song is not None and self.player.is_midi_available else tr("No MIDI output")
        )
        self._update_youtube_status()
        if song is not None:
            self.record_bpm_spin.setValue(max(40, min(250, song.tempo)))
            self.record_beats_spin.setValue(self._song_beats_per_bar(song))
            self._on_record_metronome_changed()
        self._refresh_recording_files()

    def set_selected_measure_range(self, start: int, end: int, notify: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            return
        count = len(self.song.track.measures)
        start = max(0, min(start, count - 1))
        end = max(0, min(end, count - 1))
        if end < start:
            start, end = end, start
        self.selected_start = start
        self.selected_end = end
        self._syncing_selection = True
        self.repeat_start_spin.setValue(start + 1)
        self.repeat_end_spin.setValue(end + 1)
        self.score.set_selected_range(start, end, emit=False)
        self._syncing_selection = False
        if notify:
            self.selectionChanged.emit(start, end)

    def current_measure_index(self) -> int:
        return self.selected_start

    def selected_measure_range(self) -> tuple[int, int]:
        return self.selected_start, self.selected_end

    def stop_playback(self) -> None:
        self._stop()

    def set_zoom(self, zoom: float) -> None:
        self.score.set_zoom(zoom)

    def zoom_percent(self) -> int:
        return round(self.score.zoom * 100)

    def scroll_measure_into_view(self, measure_index: int) -> None:
        layout = self.score.layout_for_measure(measure_index)
        if layout is None:
            return
        self._scroll_score_layout_into_view(layout)

    def shutdown(self) -> None:
        self.player.close()
        self.youtube_player.close()
        self.practice_metronome.close()
        self.tab_metronome.close()
        self.recorder.close()

    def _refresh_audio_inputs(self) -> None:
        self.record_input_combo.clear()
        if not self.recorder.available:
            self.record_input_combo.addItem(tr("Recording unavailable"), None)
            self.record_input_combo.setEnabled(False)
            self.record_status_label.setText(tr("No QtMultimedia"))
            return
        devices = self.recorder.audio_inputs()
        if not devices:
            self.record_input_combo.addItem(tr("No input device"), None)
            self.record_input_combo.setEnabled(False)
            return
        for device in devices:
            self.record_input_combo.addItem(device.description(), device)

    def _recordings_directory(self) -> Path:
        if self.song is not None:
            return self.song.path.parent / "recordings"
        return Path.cwd() / "recordings"

    def _recordings_directories(self) -> tuple[Path, ...]:
        directories: list[Path] = []
        if self.song is not None:
            directories.append(self.song.path.parent / "recordings")
        cwd_recordings = Path.cwd() / "recordings"
        if cwd_recordings not in directories:
            directories.append(cwd_recordings)
        return tuple(directories)

    def _refresh_recording_files(self) -> None:
        current_path = self.recorder.last_recording
        self.recording_list.clear()
        files = [
            path
            for directory in self._recordings_directories()
            if directory.exists()
            for path in directory.glob("*.wav")
        ]
        files = sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files:
            item = QListWidgetItem()
            row = RecordingListRow(path, self._recording_item_label(path))
            row.playRequested.connect(self._play_recording_path)
            row.deleteRequested.connect(self._delete_recording_path)
            item.setSizeHint(row.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.recording_list.addItem(item)
            self.recording_list.setItemWidget(item, row)
            if current_path is not None and path == current_path:
                item.setSelected(True)
        self.delete_all_recordings_button.setEnabled(bool(files))

    def _recording_item_label(self, path: Path) -> str:
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return path.name

    def _install_recording_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_F9), self, activated=self._toggle_practice_metronome)
        QShortcut(QKeySequence(Qt.Key.Key_F10), self, activated=self._start_recording)
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, activated=self._stop_recording)
        QShortcut(QKeySequence(Qt.Key.Key_F12), self, activated=self._toggle_recording_playback)

    def _install_playback_shortcuts(self) -> None:
        self.playback_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self.playback_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.playback_shortcut.activated.connect(self._play)

    def _toggle_practice_metronome(self) -> None:
        self._on_record_metronome_changed()
        self.practice_metronome.toggle()

    def _on_record_metronome_changed(self) -> None:
        self.practice_metronome.set_bpm(self.record_bpm_spin.value())
        self.practice_metronome.set_beats_per_bar(self.record_beats_spin.value())

    def _start_recording(self) -> None:
        device = self.record_input_combo.currentData()
        if device is None:
            self.record_status_label.setText(tr("No input device"))
            return
        self._mix_click_after_recording = self.record_metronome_check.isChecked() or self.practice_metronome.ticking
        if self.record_metronome_check.isChecked() and not self.practice_metronome.ticking:
            self.practice_metronome.start()
        self.recorder.start_recording(device, self.song.path if self.song is not None else None)

    def _stop_recording(self) -> None:
        self.recorder.stop_recording()
        if self._mix_click_after_recording:
            bpm = self.record_bpm_spin.value()
            beats = self.record_beats_spin.value()
            QTimer.singleShot(900, lambda: self._mix_recording_metronome(bpm, beats))

    def _mix_recording_metronome(self, bpm: int, beats: int) -> None:
        self._mix_click_after_recording = False
        if self.recorder.last_recording is None:
            return
        if _mix_metronome_clicks_into_wav(self.recorder.last_recording, bpm, beats):
            self.record_status_label.setText(_trf("Recording saved with click: {name}", name=self.recorder.last_recording.name))
        self._refresh_recording_files()

    def _toggle_recording_playback(self) -> None:
        self.recorder.toggle_play_recording(self.recorder.last_recording, self.record_playback_slider.value())

    def _play_recording_path(self, path: object) -> None:
        if not isinstance(path, Path):
            path = Path(str(path))
        self.record_playback_slider.setValue(0)
        self.recorder.play_recording(path, 0)

    def _delete_recording_path(self, path: object) -> None:
        target = path if isinstance(path, Path) else Path(str(path))
        if self._delete_recording_file(target):
            self.record_status_label.setText(_trf("Recording deleted: {name}", name=target.name))
        self._refresh_recording_files()

    def _delete_all_recordings(self) -> None:
        files = [
            path
            for directory in self._recordings_directories()
            if directory.exists()
            for path in directory.glob("*.wav")
        ]
        files = sorted(set(files))
        if not files:
            self._refresh_recording_files()
            return
        result = QMessageBox.question(
            self,
            tr("Delete all recordings"),
            _trf("Recording files {count} will be deleted. Continue?", count=len(files)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        deleted = sum(1 for path in files if self._delete_recording_file(path))
        self.record_status_label.setText(_trf("Recordings {count} deleted", count=deleted))
        self._refresh_recording_files()

    def _delete_recording_file(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if self.recorder.playback_file is not None:
            try:
                current = self.recorder.playback_file.resolve()
            except OSError:
                current = self.recorder.playback_file
            if current == resolved:
                self.recorder.stop_playback()
                self._reset_recording_playback_ui()
        try:
            path.unlink()
        except OSError as exc:
            QMessageBox.warning(self, tr("Delete recording failed"), f"{path.name}\n\n{exc}")
            return False
        if self.recorder.last_recording is not None:
            try:
                last = self.recorder.last_recording.resolve()
            except OSError:
                last = self.recorder.last_recording
            if last == resolved:
                self.recorder.last_recording = None
        return True

    def _reset_recording_playback_ui(self) -> None:
        self.record_playback_slider.setRange(0, 0)
        self.record_playback_slider.setEnabled(False)
        self.record_play_button.setIcon(_player_icon("play"))
        self.record_play_button.setToolTip(tr("Play recording F12"))

    def _on_recording_saved(self, path: object) -> None:
        if isinstance(path, Path):
            self.recorder.last_recording = path
        self._refresh_recording_files()

    def _on_recording_playback_changed(self, playing: bool) -> None:
        self.record_play_button.setIcon(_player_icon("play", "#2563eb" if playing else "#111827"))
        self.record_play_button.setToolTip(tr("Stop recording playback F12") if playing else tr("Play recording F12"))

    def _on_recording_playback_position_changed(self, position: int) -> None:
        if self.record_playback_slider.isSliderDown():
            return
        self._syncing_record_slider = True
        self.record_playback_slider.setValue(max(0, min(position, self.record_playback_slider.maximum())))
        self._syncing_record_slider = False

    def _on_recording_playback_duration_changed(self, duration: int) -> None:
        self._syncing_record_slider = True
        self.record_playback_slider.setRange(0, max(0, int(duration)))
        self.record_playback_slider.setEnabled(duration > 0)
        self._syncing_record_slider = False

    def _on_record_playback_slider_moved(self, value: int) -> None:
        if self.recorder.playing:
            self.recorder.set_playback_position(value)

    def _on_record_playback_slider_value_changed(self, value: int) -> None:
        if self._syncing_record_slider:
            return
        if self.recorder.playing:
            self.recorder.set_playback_position(value)

    def _on_tab_metronome_changed(self, enabled: bool) -> None:
        self.player.set_metronome_enabled(enabled)
        self._update_youtube_metronome()

    def _on_youtube_availability_changed(self, available: bool) -> None:
        was_enabled = self.youtube_radio.isEnabled()
        self.youtube_radio.setEnabled(available)
        if available:
            if not was_enabled:
                self.youtube_radio.setChecked(True)
        else:
            self.midi_radio.setChecked(True)
        self._update_youtube_metronome()
        self._update_youtube_status()
        self._update_youtube_sync_controls()

    def _update_youtube_status(self) -> None:
        if self.youtube_player.video_id and self.youtube_player.playback_available:
            self.youtube_status_label.setText(_trf("YouTube OK - {video_id}", video_id=self.youtube_player.video_id))
        elif self.youtube_player.video_id:
            self.youtube_status_label.setText(tr("YouTube unavailable"))
        else:
            self.youtube_status_label.setText(tr("No YouTube"))
        self._update_youtube_sync_controls()
        if self.youtube_player.view is not None:
            self._position_youtube_view()
            show_error_message = bool(self.youtube_player.error and self.youtube_player.video_id and not self.youtube_player.playback_available)
            self.youtube_player.view.setVisible((self.youtube_radio.isChecked() and self.youtube_radio.isEnabled()) or show_error_message)

    def _position_youtube_view(self) -> None:
        view = self.youtube_player.view
        if view is None:
            return
        viewport = self.score_scroll.viewport()
        top_left = viewport.mapTo(self, QPoint(0, 0))
        width = YOUTUBE_VIEW_WIDTH
        height = YOUTUBE_VIEW_HEIGHT
        x = top_left.x() + max(0, viewport.width() - width - YOUTUBE_VIEW_PIP_MARGIN)
        y = top_left.y() + max(0, viewport.height() - height - YOUTUBE_VIEW_PIP_MARGIN)
        view.setGeometry(x, y, width, height)
        view.raise_()

    def _on_playback_source_changed(self, _checked: bool) -> None:
        self._update_youtube_status()
        if not self._is_tab_playing() or self.song is None:
            self._update_youtube_metronome()
            return
        tick = self._current_playback_tick()
        current = self._measure_index_for_tick(tick)
        repeat = self.repeat_check.isChecked()
        end = self.repeat_end_spin.value() - 1 if repeat else len(self.song.track.measures) - 1
        start = self.repeat_start_spin.value() - 1 if repeat else current
        self._start_playback(start, end, repeat=repeat, play_from=current, play_from_tick=tick)

    def _use_youtube_source(self) -> bool:
        return self.youtube_radio.isChecked() and self.youtube_radio.isEnabled()

    def _is_tab_playing(self) -> bool:
        return self.player.playing or self.youtube_player.playing

    def _current_playback_tick(self) -> int:
        if self.youtube_player.playing:
            return int(self.youtube_player.current_tick)
        return int(self.player.current_tick)

    def _on_practice_metronome_changed(self, ticking: bool) -> None:
        self.metronome_button.setStyleSheet("background: #fee2e2;" if ticking else "")

    def _sync_tab_metronome_settings(self) -> None:
        if self.song is None:
            return
        bpm = round(self.song.tempo * (self.speed_slider.value() / 100.0))
        self.tab_metronome.set_bpm(bpm)
        self.tab_metronome.set_beats_per_bar(self._song_beats_per_bar(self.song))

    def _should_run_youtube_metronome(self) -> bool:
        return (
            self.song is not None
            and self.metronome_check.isChecked()
            and self._use_youtube_source()
            and self.youtube_player.playing
        )

    def _update_youtube_metronome(self) -> None:
        if self._should_run_youtube_metronome():
            self._sync_tab_metronome_settings()
            if not self.tab_metronome.ticking:
                self.tab_metronome.start()
            return
        self.tab_metronome.stop()

    def _on_recording_changed(self, recording: bool) -> None:
        self.record_button.setEnabled(not recording)
        self.record_stop_button.setEnabled(recording)
        self.record_button.setStyleSheet("background: #fee2e2;" if recording else "")

    def _song_beats_per_bar(self, song: SongData) -> int:
        if not song.track.measures:
            return 4
        try:
            return max(1, min(12, int(song.track.measures[0].time_signature.split("/", 1)[0])))
        except (ValueError, IndexError):
            return 4

    def _sync_youtube_sync_spin(self) -> None:
        youtube = self.details.get("youtube") if isinstance(self.details, dict) else None
        sync = youtube.get("sync") if isinstance(youtube, dict) else None
        try:
            offset_ms = int(round(float(sync.get("offset_seconds", 0.0)) * 1000 / 10) * 10) if isinstance(sync, dict) else 0
        except (TypeError, ValueError):
            offset_ms = 0
        self._syncing_youtube_sync_spin = True
        self.youtube_sync_spin.setValue(max(self.youtube_sync_spin.minimum(), min(self.youtube_sync_spin.maximum(), offset_ms)))
        self._syncing_youtube_sync_spin = False
        self.youtube_player.set_offset_milliseconds(self.youtube_sync_spin.value())
        self._update_youtube_sync_controls()

    def _update_youtube_sync_controls(self) -> None:
        enabled = bool(self.song is not None and self.youtube_player.video_id and self.youtube_player.available)
        for widget in (self.youtube_sync_spin, self.youtube_sync_down_button, self.youtube_sync_up_button):
            widget.setEnabled(enabled)

    def _round_to_sync_step(self, value: int) -> int:
        sign = -1 if value < 0 else 1
        rounded = ((abs(int(value)) + 5) // 10) * 10
        return sign * rounded

    def _adjust_youtube_sync(self, delta_ms: int) -> None:
        self.youtube_sync_spin.setValue(self.youtube_sync_spin.value() + delta_ms)

    def _on_youtube_sync_changed(self, value: int) -> None:
        rounded = max(self.youtube_sync_spin.minimum(), min(self.youtube_sync_spin.maximum(), self._round_to_sync_step(value)))
        if rounded != value:
            self._syncing_youtube_sync_spin = True
            self.youtube_sync_spin.setValue(rounded)
            self._syncing_youtube_sync_spin = False
            value = rounded
        self.youtube_player.set_offset_milliseconds(value)
        if self._syncing_youtube_sync_spin or self.song is None:
            return
        if update_youtube_sync_offset(self.details, value / 1000.0):
            save_details_file(self.song.path, self.details)

    def _adjust_speed(self, delta_percent: int) -> None:
        self.speed_slider.setValue(self.speed_slider.value() + delta_percent)

    def _on_youtube_video_ready(self, video_id: str) -> None:
        if self.song is None:
            return
        if update_youtube_default_video(self.details, video_id):
            save_details_file(self.song.path, self.details)

    def _on_score_selection_changed(self, start: int, end: int) -> None:
        was_playing = self._is_tab_playing()
        repeat_was_checked = self.repeat_check.isChecked()

        self.set_selected_measure_range(start, end, notify=True)
        if start != end:
            self._set_repeat_checked(True)
        if not was_playing or self.song is None:
            return

        if repeat_was_checked and start == end:
            self._set_repeat_checked(False)
            self._start_playback(start, len(self.song.track.measures) - 1, repeat=False, play_from=start)
            return

        if self.repeat_check.isChecked():
            self._start_playback(start, end, repeat=True, play_from=start)
            return

        self._start_playback(start, len(self.song.track.measures) - 1, repeat=False, play_from=start)

    def _on_repeat_range_changed(self, _value: int) -> None:
        if self._syncing_selection or self.song is None:
            return
        start = self.repeat_start_spin.value() - 1
        end = self.repeat_end_spin.value() - 1
        self.set_selected_measure_range(start, end, notify=True)
        if self._is_tab_playing():
            self._set_repeat_checked(True)
            self._restart_playback_for_repeat_mode(True)

    def _on_repeat_toggled(self, enabled: bool) -> None:
        if self._syncing_repeat_toggle or self.song is None:
            return
        if self._is_tab_playing():
            self._restart_playback_for_repeat_mode(enabled)

    def _play(self) -> None:
        if self._is_tab_playing():
            self._stop()
            return
        if self.song is None or not self.song.track.measures:
            return
        if self.repeat_check.isChecked():
            start = self.repeat_start_spin.value() - 1
            end = self.repeat_end_spin.value() - 1
            repeat = True
        else:
            start = self.selected_start
            end = len(self.song.track.measures) - 1
            repeat = False
        self._start_playback(start, end, repeat=repeat, play_from=start)

    def _start_playback(self, start: int, end: int, *, repeat: bool, play_from: int, play_from_tick: int | None = None) -> None:
        if self.song is None or not self.song.track.measures:
            return
        self.player.stop(emit=False)
        self.youtube_player.stop(emit=False)
        self.tab_metronome.stop()
        if self._use_youtube_source():
            if not self.youtube_player.playback_available or not self.youtube_player.video_id:
                QMessageBox.warning(
                    self,
                    tr("YouTube unavailable"),
                    tr("YouTube playback information is unavailable, so MIDI playback will be used."),
                )
                self.midi_radio.setChecked(True)
            else:
                self.youtube_player.start(
                    self.song,
                    start,
                    end,
                    repeat=repeat,
                    speed_percent=self.speed_slider.value(),
                    play_from_measure_index=play_from,
                    play_from_tick=play_from_tick,
                )
                self._update_youtube_metronome()
                return
        if not self.player.is_midi_available and not self._midi_warning_shown:
            QMessageBox.warning(
                self,
                tr("MIDI output unavailable"),
                _trf(
                    "The MIDI device could not be opened, so only the cursor will move.\n\n{error}",
                    error=self.player.midi_error,
                ),
            )
            self._midi_warning_shown = True
        self.player.start(
            self.song,
            start,
            end,
            repeat=repeat,
            speed_percent=self.speed_slider.value(),
            metronome=self.metronome_check.isChecked(),
            play_from_measure_index=play_from,
            play_from_tick=play_from_tick,
        )

    def _restart_playback_for_repeat_mode(self, repeat: bool) -> None:
        if self.song is None or not self.song.track.measures:
            return
        tick = self._current_playback_tick()
        measures = self.song.track.measures
        if repeat:
            start = self.repeat_start_spin.value() - 1
            end = self.repeat_end_spin.value() - 1
            start, end = self._clamped_measure_range(start, end)
            range_start_tick = measures[start].start_tick
            range_end_tick = measures[end].start_tick + measures[end].length_ticks
            play_tick = tick if range_start_tick <= tick < range_end_tick else range_start_tick
            self._start_playback(start, end, repeat=True, play_from=start, play_from_tick=play_tick)
            return

        current = self._measure_index_for_tick(tick)
        self._start_playback(
            current,
            len(measures) - 1,
            repeat=False,
            play_from=current,
            play_from_tick=tick,
        )

    def _set_repeat_controls(self, start: int, end: int) -> None:
        if self.song is None:
            return
        start, end = self._clamped_measure_range(start, end)
        self._syncing_selection = True
        self.repeat_start_spin.setValue(start + 1)
        self.repeat_end_spin.setValue(end + 1)
        self._syncing_selection = False

    def _set_repeat_checked(self, checked: bool) -> None:
        if self.repeat_check.isChecked() == checked:
            return
        self._syncing_repeat_toggle = True
        self.repeat_check.setChecked(checked)
        self._syncing_repeat_toggle = False

    def _clamped_measure_range(self, start: int, end: int) -> tuple[int, int]:
        if self.song is None or not self.song.track.measures:
            return 0, 0
        count = len(self.song.track.measures)
        start = max(0, min(start, count - 1))
        end = max(0, min(end, count - 1))
        if end < start:
            start, end = end, start
        return start, end

    def _measure_index_for_tick(self, tick: int) -> int:
        if self.song is None or not self.song.track.measures:
            return 0
        measures = self.song.track.measures
        for index, measure in enumerate(measures):
            start_tick = measure.start_tick
            end_tick = measure.start_tick + measure.length_ticks
            if start_tick <= tick < end_tick:
                return index
        return len(measures) - 1 if tick >= measures[-1].start_tick else 0

    def _stop(self) -> None:
        self.player.stop()
        self.youtube_player.stop()
        self.tab_metronome.stop()
        self._playback_measure_index = None
        self.score.set_playback_tick(None)
        self.playbackTickChanged.emit(None)

    def _on_speed_changed(self, value: int) -> None:
        self.speed_label.setText(f"{value}%")
        self.player.set_speed_percent(value)
        self.youtube_player.set_speed_percent(value)
        self._update_youtube_metronome()

    def _on_playback_position_changed(self, tick: int) -> None:
        self.score.set_playback_tick(tick)
        self.playbackTickChanged.emit(tick)
        if self.song is not None and self.song.track.measures:
            measure_index = self._measure_index_for_tick(tick)
            if measure_index != self._playback_measure_index:
                self._playback_measure_index = measure_index
                self.playbackMeasureChanged.emit(measure_index)
        self._scroll_playback_measure_into_view(tick)

    def _scroll_playback_measure_into_view(self, tick: int) -> None:
        layout = self.score.layout_for_tick(tick)
        if layout is None:
            return
        self._scroll_score_layout_into_view(layout)

    def _scroll_score_layout_into_view(self, layout: _MeasureLayout) -> None:
        scroll_bar = self.score_scroll.verticalScrollBar()
        viewport_height = self.score_scroll.viewport().height()
        padding = int(24 * self.score.zoom)
        target_top = max(0, layout.rect.top() - padding)
        target_bottom = layout.rect.bottom() + padding
        visible_top = scroll_bar.value()
        visible_bottom = visible_top + viewport_height
        target_value = visible_top
        if target_top < visible_top:
            target_value = target_top
        elif target_bottom > visible_bottom:
            target_value = target_bottom - viewport_height
        target_value = self._scroll_value_avoiding_youtube_pip(layout, target_value, padding)
        scroll_bar.setValue(target_value)

    def _scroll_value_avoiding_youtube_pip(self, layout: _MeasureLayout, scroll_value: int, padding: int) -> int:
        pip_rect = self._youtube_pip_viewport_rect()
        if pip_rect is None:
            return scroll_value
        layout_view_rect = QRect(
            layout.rect.left(),
            layout.rect.top() - scroll_value,
            layout.rect.width(),
            layout.rect.height(),
        ).adjusted(-padding, -padding, padding, padding)
        if not layout_view_rect.intersects(pip_rect):
            return scroll_value
        if layout_view_rect.height() > pip_rect.top():
            return scroll_value
        avoid_value = layout.rect.bottom() + padding - pip_rect.top()
        scroll_bar = self.score_scroll.verticalScrollBar()
        if avoid_value > scroll_bar.maximum():
            return scroll_value
        return max(scroll_value, max(0, avoid_value))

    def _youtube_pip_viewport_rect(self) -> QRect | None:
        if not self._use_youtube_source() or self.youtube_player.view is None:
            return None
        viewport = self.score_scroll.viewport()
        return QRect(
            max(0, viewport.width() - YOUTUBE_VIEW_WIDTH - YOUTUBE_VIEW_PIP_MARGIN),
            max(0, viewport.height() - YOUTUBE_VIEW_HEIGHT - YOUTUBE_VIEW_PIP_MARGIN),
            YOUTUBE_VIEW_WIDTH,
            YOUTUBE_VIEW_HEIGHT,
        )

    def _on_playing_changed(self, playing: bool) -> None:
        active = self._is_tab_playing()
        self.play_button.setIcon(_player_icon("play", "#2563eb" if active else "#111827"))
        self.play_button.setToolTip(tr("Stop") if active else tr("Play"))
        self.play_button.setStyleSheet("background: #dbeafe;" if active else "")
        self._update_youtube_metronome()


class FretboardWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.measure: MeasureData | None = None
        self.segment: SegmentData | None = None
        self.candidate: Candidate | None = None
        self.kind = "scale"
        self.playback_tick: int | None = None
        self.selected_scale_block_index: int | None = None
        self._scale_block_button_hits: list[tuple[QRect, int]] = []
        self.setFixedHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.measure = None
        self.segment = None
        self.candidate = None
        self.playback_tick = None
        self.selected_scale_block_index = None
        self._scale_block_button_hits = []
        self.update()

    def set_selection(
        self,
        measure: MeasureData | None,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None = None,
    ) -> None:
        self.measure = measure
        self.segment = segment
        self.candidate = candidate
        self.kind = kind
        self.selected_scale_block_index = None
        self.update()

    def set_playback_tick(self, tick: object) -> None:
        self.playback_tick = int(tick) if tick is not None else None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, block_index in self._scale_block_button_hits:
            if rect.contains(position):
                self.selected_scale_block_index = block_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._draw_fretboard(painter)

    def _draw_fretboard(self, painter: QPainter) -> None:
        self._scale_block_button_hits = []
        if self.song is None:
            painter.setPen(QColor("#657083"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Fretboard"))
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        scale_blocks = self._current_scale_blocks(fret_count)
        show_scale_buttons = self.kind == "scale" and len(scale_blocks) > 1
        left = 56
        right = 28
        top = 44
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        title = self._selection_title()
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(16, 10, self.width() - 32, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        self._draw_scale_blocks(painter, board, fret_count, fret_gap, scale_blocks)

        painter.setPen(QPen(QColor("#9aa6b7"), 1))
        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_candidate_notes(painter, board, fret_count, fret_gap, string_gap)
        self._draw_measure_fingering(painter, board, fret_count, fret_gap, string_gap)
        self._draw_current_playback_notes(painter, board, fret_count, fret_gap, string_gap)
        self._draw_scale_block_buttons(painter, board, scale_blocks)

    def _draw_scale_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.kind != "scale" or self.measure is None or self.candidate is None or self.song is None:
            return

        if not blocks:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        active_block_index = self._active_scale_block_index(blocks)
        visible_blocks = blocks
        if len(blocks) > 1 and active_block_index is not None:
            visible_blocks = tuple(block for block in blocks if block.index == active_block_index)
        spans = scale_block_spans(
            visible_blocks,
            self.candidate,
            self.song.track.string_pitches,
            fret_count,
        )
        if not spans:
            return

        row_height = max(14, min(30, int(string_gap * 0.58)))
        block_color = QColor(250, 204, 21, 165)

        painter.setPen(Qt.PenStyle.NoPen)
        for span in spans:
            painter.setBrush(block_color)
            painter.drawRoundedRect(
                self._scale_span_rect(board, fret_gap, string_gap, span.string_index, span.start_fret, span.end_fret, row_height),
                5,
                5,
            )

    def _current_scale_blocks(self, fret_count: int) -> tuple[ScaleBlock, ...]:
        if self.kind != "scale" or self.measure is None or self.candidate is None or self.song is None:
            return ()
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        notes = tuple(note for note in notes if 0 <= note.fret <= fret_count)
        if not notes:
            return ()
        return infer_scale_blocks(
            notes,
            self.candidate,
            self.song.track.string_pitches,
            fret_count,
        )

    def _active_scale_block_index(self, blocks: tuple[ScaleBlock, ...]) -> int | None:
        if not blocks:
            return None
        block_indexes = {block.index for block in blocks}
        if self.selected_scale_block_index in block_indexes:
            return self.selected_scale_block_index
        return max(
            blocks,
            key=lambda block: (
                self._scale_block_played_note_count(block),
                len(block.played_positions),
                -block.first_order,
                -block.start_fret,
                -block.index,
            ),
        ).index

    def _scale_block_played_note_count(self, block: ScaleBlock) -> int:
        if self.measure is None:
            return len(block.played_positions)
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        positions = set(block.played_positions)
        return sum(1 for note in notes if (int(note.string) - 1, int(note.fret)) in positions)

    def _draw_scale_block_buttons(
        self,
        painter: QPainter,
        board: QRect,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        self._scale_block_button_hits = []
        if self.kind != "scale" or len(blocks) <= 1:
            return

        active_block_index = self._active_scale_block_index(blocks)
        ordered = sorted(blocks, key=lambda block: (block.start_fret, block.end_fret, block.first_order, block.index))
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        for display_number, block in enumerate(ordered, start=1):
            text = f"{display_number}: {block.start_fret}-{block.end_fret}"
            width = max(54, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = block.index == active_block_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._scale_block_button_hits.append((rect, block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _scale_block_overlap_rects(
        self,
        spans: tuple[ScaleSpan, ...],
        board: QRect,
        fret_gap: float,
        string_gap: float,
        row_height: int,
    ) -> list[QRect]:
        overlap_rects: list[QRect] = []
        for left_index, left_span in enumerate(spans):
            for right_span in spans[left_index + 1:]:
                if left_span.block_index == right_span.block_index or left_span.string_index != right_span.string_index:
                    continue
                overlap_start = max(left_span.start_fret, right_span.start_fret)
                overlap_end = min(left_span.end_fret, right_span.end_fret)
                if overlap_start > overlap_end:
                    continue
                overlap_rects.append(
                    self._scale_span_rect(
                        board,
                        fret_gap,
                        string_gap,
                        left_span.string_index,
                        overlap_start,
                        overlap_end,
                        row_height,
                    )
                )
        return overlap_rects

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)

    def _draw_candidate_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.candidate is None or self.song is None:
            return

        pcs = set(self.candidate.pitch_classes)
        color = QColor("#f9a8d4") if self.kind == "scale" else QColor("#2468d8")
        root_color = QColor("#be185d") if self.kind == "scale" else QColor("#174ea6")
        missing_chord_root = self.kind == "chord" and not self._root_is_played()

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for fret in range(fret_count + 1):
                pc = (open_midi + fret) % 12
                if pc not in pcs:
                    continue
                x = int(board.left() + (fret * fret_gap if fret == 0 else (fret - 0.5) * fret_gap))
                is_root = pc == self.candidate.root_pc
                dot_color = root_color if is_root else color
                text_color = QColor("#ffffff") if is_root or self.kind != "scale" else QColor("#3b1426")
                if is_root and missing_chord_root:
                    dot_color = QColor("#174ea6")
                    text_color = QColor("#ffffff")
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(dot_color)
                radius = 12 if is_root else 10
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(text_color)
                label = self._fretboard_degree_label((pc - self.candidate.root_pc) % 12, pc)
                painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, label)

    def _draw_measure_fingering(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.measure is None or self.song is None:
            return

        notes = self.segment.notes if self.segment is not None else self.measure.notes
        played_by_position: dict[tuple[int, int], object] = {}
        for note in notes:
            played_by_position.setdefault((note.string, note.fret), note)
        if not played_by_position:
            return

        candidate_pcs = set(self.candidate.pitch_classes) if self.candidate is not None else set()
        inside_fill = QColor("#16a34a")
        inside_border = QColor("#0f6f34")
        outside_fill = QColor("#f9a8d4")
        outside_border = QColor("#be185d")
        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for (string_number, fret), note in sorted(played_by_position.items()):
            if fret < 0 or fret > fret_count:
                continue
            string_index = string_number - 1
            if string_index < 0 or string_index >= len(self.song.track.string_pitches):
                continue

            inside_candidate = self.candidate is None or (note.midi % 12) in candidate_pcs
            x = int(board.left() + (fret * fret_gap if fret == 0 else (fret - 0.5) * fret_gap))
            y = int(board.top() + string_index * string_gap)
            show_degree = self.candidate is not None and self.kind in {"scale", "chord"}
            radius = 15 if show_degree else 13
            interval = (note.midi - self.candidate.root_pc) % 12 if show_degree else 0
            is_scale_root = show_degree and self.kind == "scale" and interval == 0
            is_chord_root = show_degree and self.kind == "chord" and interval == 0
            if is_chord_root:
                fill = QColor("#dc2626")
                border = QColor("#991b1b")
            elif is_scale_root:
                fill = QColor("#dc2626")
                border = QColor("#991b1b")
            else:
                fill = inside_fill if inside_candidate else outside_fill
                border = inside_border if inside_candidate else outside_border
            painter.setPen(QPen(border, 2))
            painter.setBrush(fill)
            painter.drawEllipse(QPoint(x, y), radius, radius)
            painter.setPen(QColor("#111827") if not inside_candidate and not is_scale_root and not is_chord_root else QColor("#ffffff"))
            circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
            if show_degree:
                painter.setFont(fret_font)
                painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, str(fret))
                painter.setFont(degree_font)
                degree = self._fretboard_degree_label(interval, note.midi % 12)
                painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)
            else:
                painter.setFont(fret_font)
                painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, str(fret))

    def _current_playback_notes(self) -> tuple[object, ...]:
        if self.measure is None or self.playback_tick is None:
            return ()
        measure_start = self.measure.start_tick
        measure_end = self.measure.start_tick + self.measure.length_ticks
        if not (measure_start <= self.playback_tick < measure_end):
            return ()
        return tuple(
            note
            for note in self.measure.notes
            if note.start_tick <= self.playback_tick < note.start_tick + max(1, note.duration_ticks)
        )

    def _draw_current_playback_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.song is None:
            return
        notes = self._current_playback_notes()
        if not notes:
            return

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        for note in notes:
            if note.fret < 0 or note.fret > fret_count:
                continue
            string_index = int(note.string) - 1
            if string_index < 0 or string_index >= len(self.song.track.string_pitches):
                continue
            x = self._fret_center_x(board, fret_gap, int(note.fret))
            y = int(board.top() + string_index * string_gap)
            radius = 20
            painter.setPen(QPen(QColor("#f5d0fe"), 3))
            painter.setBrush(QColor("#7e22ce"))
            painter.drawEllipse(QPoint(x, y), radius, radius)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, str(note.fret))

    def _root_is_played(self) -> bool:
        if self.kind != "chord" or self.candidate is None or self.measure is None:
            return False
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        return any(note.midi % 12 == self.candidate.root_pc for note in notes)

    def _fretboard_degree_label(self, interval: int, note_pc: int) -> str:
        if self.kind == "chord":
            return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]
        if self.candidate is None:
            return ""
        return interval_name(self.candidate.root_pc, note_pc)

    def _selection_title(self) -> str:
        if self.candidate is None:
            return f"{self.song.title} - {self.song.track.name}" if self.song else tr("Fretboard")
        measure_text = f"M{self.measure.number}" if self.measure else ""
        if self.measure is not None and self.segment is not None:
            start_percent = round((self.segment.start_in_measure / self.measure.length_ticks) * 100)
            end_percent = round((self.segment.end_in_measure / self.measure.length_ticks) * 100)
            measure_text = f"{measure_text} {start_percent}-{end_percent}%"
        kind_text = tr("Scale") if self.kind == "scale" else tr("Chord")
        prefer_flats = self.song.track.prefer_flats if self.song is not None else None
        notes = " ".join(pitch_class_name(pc, prefer_flats) for pc in self.candidate.pitch_classes)
        name = candidate_display_name(self.candidate, prefer_flats)
        return f"{measure_text}  {kind_text}: {name} ({self.candidate.score})  {notes}"


class ScalePositionWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.root_pc = 0
        self.scale_name = SCALE_POSITION_PATTERNS[0][0]
        self.scale_intervals = SCALE_POSITION_PATTERNS[0][1]
        self.selected_scale_block_index: int | None = None
        self._scale_block_button_hits: list[tuple[QRect, int]] = []
        self.setMinimumHeight(244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(960, 260)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_scale_block_index = None
        self._scale_block_button_hits = []
        self.update()

    def set_scale(self, root_pc: int, scale_name: str) -> None:
        self.root_pc = root_pc % 12
        self.scale_name = scale_name
        self.scale_intervals = SCALE_POSITION_PATTERN_BY_NAME.get(scale_name, self.scale_intervals)
        self.selected_scale_block_index = None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, block_index in self._scale_block_button_hits:
            if rect.contains(position):
                self.selected_scale_block_index = block_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._scale_block_button_hits = []
        if self.song is None:
            self._draw_empty(painter)
            return
        self._draw_fretboard(painter)

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Scale view"))

    def _draw_fretboard(self, painter: QPainter) -> None:
        if self.song is None:
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        scale_blocks = self._scale_blocks(fret_count)
        left = 56
        right = 28
        top = 42
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            QRect(16, 10, self.width() - 32, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title(),
        )

        self._draw_scale_blocks(painter, board, fret_count, fret_gap, scale_blocks)

        painter.setPen(QPen(QColor("#9aa6b7"), 1))
        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_scale_notes(painter, board, fret_count, fret_gap, string_gap, scale_blocks)
        self._draw_scale_block_buttons(painter, board, scale_blocks)

    def _title(self) -> str:
        prefer_flats = self.song.track.prefer_flats if self.song is not None else None
        root = SCALE_POSITION_ROOT_LABELS.get(self.root_pc, pitch_class_name(self.root_pc, prefer_flats))
        scale = SCALE_POSITION_DISPLAY_NAMES.get(self.scale_name, self.scale_name)
        notes = " ".join(
            pitch_class_name((self.root_pc + interval) % 12, prefer_flats)
            for interval in self.scale_intervals
        )
        return f"{root} {scale}   {notes}"

    def _draw_scale_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.song is None:
            return

        pitch_classes = {(self.root_pc + interval) % 12 for interval in self.scale_intervals}
        active_block_index = self._active_scale_block_index(blocks)
        active_blocks = tuple(block for block in blocks if block.index == active_block_index)
        inactive_blocks = tuple(block for block in blocks if block.index != active_block_index)
        candidate = self._candidate()

        inactive_positions = self._scale_note_positions(
            inactive_blocks,
            candidate,
            pitch_classes,
            fret_count,
        )
        active_positions = self._scale_note_positions(
            active_blocks,
            candidate,
            pitch_classes,
            fret_count,
        )
        if not active_positions and not inactive_positions:
            active_positions = {
                (string_index, fret)
                for string_index, open_midi in enumerate(self.song.track.string_pitches)
                for fret in range(fret_count + 1)
                if (open_midi + fret) % 12 in pitch_classes
            }

        self._draw_scale_note_positions(
            painter,
            board,
            fret_gap,
            string_gap,
            inactive_positions - active_positions,
            root_color=QColor("#174ea6"),
            note_color=QColor("#bfdbfe"),
            root_text_color=QColor("#ffffff"),
            note_text_color=QColor("#17345d"),
            root_radius=10,
            note_radius=8,
        )
        self._draw_scale_note_positions(
            painter,
            board,
            fret_gap,
            string_gap,
            active_positions,
            root_color=QColor("#8f1d18"),
            note_color=QColor("#cb3a31"),
            root_text_color=QColor("#ffffff"),
            note_text_color=QColor("#ffffff"),
            root_radius=11,
            note_radius=9,
        )

    def _scale_note_positions(
        self,
        blocks: tuple[ScaleBlock, ...],
        candidate: Candidate,
        pitch_classes: set[int],
        fret_count: int,
    ) -> set[tuple[int, int]]:
        if self.song is None or not blocks:
            return set()

        positions: set[tuple[int, int]] = set()
        positions_by_block: dict[int, set[tuple[int, int]]] = {}
        for span in scale_block_spans(
            blocks,
            candidate,
            self.song.track.string_pitches,
            fret_count,
        ):
            open_midi = self.song.track.string_pitches[span.string_index]
            for fret in range(span.start_fret, span.end_fret + 1):
                if (open_midi + fret) % 12 in pitch_classes:
                    positions_by_block.setdefault(span.block_index, set()).add((span.string_index, fret))

        for block_positions in positions_by_block.values():
            preferred_notes = 2 if "pentatonic" in self.scale_name.lower() else 3
            positions.update(
                dedupe_repeated_pitch_positions(
                    block_positions,
                    self.song.track.string_pitches,
                    preferred_notes_per_string=preferred_notes,
                )
            )
        return positions

    def _draw_scale_note_positions(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        positions: set[tuple[int, int]],
        root_color: QColor,
        note_color: QColor,
        root_text_color: QColor,
        note_text_color: QColor,
        root_radius: int,
        note_radius: int,
    ) -> None:
        if self.song is None or not positions:
            return

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for _position_string, fret in sorted(position for position in positions if position[0] == string_index):
                pc = (open_midi + fret) % 12
                x = self._fret_center_x(board, fret_gap, fret)
                is_root = pc == self.root_pc
                radius = root_radius if is_root else note_radius
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(root_color if is_root else note_color)
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(root_text_color if is_root else note_text_color)
                painter.drawText(
                    QRect(x - radius, y - radius, radius * 2, radius * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    interval_name(self.root_pc, pc),
                )

    def _candidate(self) -> Candidate:
        root = SCALE_POSITION_ROOT_LABELS.get(self.root_pc, pitch_class_name(self.root_pc))
        return Candidate(
            kind="scale",
            name=f"{root} {self.scale_name}",
            root_pc=self.root_pc,
            intervals=self.scale_intervals,
            score=100,
            matched_notes=0,
            total_notes=0,
            outside_notes=0,
        )

    def _scale_blocks(self, fret_count: int) -> tuple[ScaleBlock, ...]:
        if self.song is None:
            return ()
        return generate_scale_position_blocks(
            self._candidate(),
            self.song.track.string_pitches,
            fret_count,
        )

    def _visible_scale_blocks(self, blocks: tuple[ScaleBlock, ...]) -> tuple[ScaleBlock, ...]:
        if not blocks:
            return ()
        active_block_index = self._active_scale_block_index(blocks)
        if active_block_index is None:
            return ()
        return tuple(block for block in blocks if block.index == active_block_index)

    def _active_scale_block_index(self, blocks: tuple[ScaleBlock, ...]) -> int | None:
        if not blocks:
            return None
        block_indexes = {block.index for block in blocks}
        if self.selected_scale_block_index in block_indexes:
            return self.selected_scale_block_index
        return min(blocks, key=lambda block: (block.start_fret, block.end_fret, block.index)).index

    def _draw_scale_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.song is None or not blocks:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        positions = self._scale_note_positions(
            self._visible_scale_blocks(blocks),
            self._candidate(),
            {(self.root_pc + interval) % 12 for interval in self.scale_intervals},
            fret_count,
        )
        if not positions:
            return

        frets_by_string: dict[int, list[int]] = {}
        for string_index, fret in positions:
            frets_by_string.setdefault(string_index, []).append(fret)

        row_height = max(14, min(30, int(string_gap * 0.58)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(250, 204, 21, 165))
        for string_index, frets in sorted(frets_by_string.items()):
            painter.drawRoundedRect(
                self._scale_span_rect(board, fret_gap, string_gap, string_index, min(frets), max(frets), row_height),
                5,
                5,
            )

    def _draw_scale_block_buttons(
        self,
        painter: QPainter,
        board: QRect,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        self._scale_block_button_hits = []
        if len(blocks) <= 1:
            return

        active_block_index = self._active_scale_block_index(blocks)
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        ordered = sorted(blocks, key=lambda block: (block.start_fret, block.end_fret, block.index))
        for display_number, block in enumerate(ordered, start=1):
            text = f"{display_number}: {block.start_fret}-{block.end_fret}"
            width = max(54, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = block.index == active_block_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._scale_block_button_hits.append((rect, block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)


class SongScaleUsageWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.preferred_scale: Candidate | None = None
        self.usages: tuple[ScaleBlockUsage, ...] = ()
        self.visible_count = 5
        self.selected_usage_index: int | None = None
        self._usage_button_hits: list[tuple[QRect, int]] = []
        self.setMinimumHeight(244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(960, 260)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_usage_index = None
        self._usage_button_hits = []
        self.preferred_scale = None
        self.usages = ()
        if song is not None:
            self.preferred_scale = infer_preferred_scale(song.track.measures)
            self.usages = infer_song_scale_block_usages(
                song.track.measures,
                song.track.string_pitches,
                song.track.fret_count,
                self.preferred_scale,
            )
        self.update()

    def set_visible_count(self, count: int) -> None:
        self.visible_count = max(1, count)
        if self.selected_usage_index not in {usage.block.index for usage in self._visible_usages()}:
            self.selected_usage_index = None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, usage_index in self._usage_button_hits:
            if rect.contains(position):
                self.selected_usage_index = usage_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._usage_button_hits = []
        if self.song is None:
            self._draw_empty(painter, tr("Open a file to show song scale blocks."))
            return
        if self.preferred_scale is None or not self.usages:
            self._draw_empty(painter, tr("No song scale blocks to show."))
            return
        self._draw_fretboard(painter)

    def _draw_empty(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_fretboard(self, painter: QPainter) -> None:
        if self.song is None or self.preferred_scale is None:
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        usages = self._visible_usages()
        if not usages:
            self._draw_empty(painter, tr("No song scale blocks to show."))
            return

        left = 56
        right = 28
        top = 42
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            QRect(16, 10, self.width() - 32, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title(),
        )

        self._draw_usage_blocks(painter, board, fret_count, fret_gap, string_gap, usages)

        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_usage_notes(painter, board, fret_count, fret_gap, string_gap, usages)
        self._draw_usage_buttons(painter, board, usages)

    def _title(self) -> str:
        if self.song is None or self.preferred_scale is None:
            return tr("Song scale view")
        name = candidate_display_name(self.preferred_scale, self.song.track.prefer_flats)
        total = sum(usage.selected_count for usage in self.usages)
        return _trf("Best scale: {name} - selected measures {count}", name=name, count=total)

    def _visible_usages(self) -> tuple[ScaleBlockUsage, ...]:
        return self.usages[: self.visible_count]

    def _active_usage_index(self, usages: tuple[ScaleBlockUsage, ...]) -> int | None:
        if not usages:
            return None
        usage_indexes = {usage.block.index for usage in usages}
        if self.selected_usage_index in usage_indexes:
            return self.selected_usage_index
        return usages[0].block.index

    def _draw_usage_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        active_usage_index = self._active_usage_index(usages)
        row_height = max(14, min(30, int(string_gap * 0.58)))
        painter.setPen(Qt.PenStyle.NoPen)
        ordered_usages = tuple(usage for usage in usages if usage.block.index != active_usage_index)
        ordered_usages += tuple(usage for usage in usages if usage.block.index == active_usage_index)
        for usage in ordered_usages:
            color = QColor(239, 68, 68, 130) if usage.block.index == active_usage_index else QColor(250, 204, 21, 165)
            self._draw_usage_block_spans(
                painter,
                board,
                fret_count,
                fret_gap,
                string_gap,
                row_height,
                usage,
                color,
            )

    def _draw_usage_block_spans(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        row_height: int,
        usage: ScaleBlockUsage,
        color: QColor,
    ) -> None:
        if self.song is None:
            return
        spans = scale_block_spans(
            (usage.block,),
            usage.candidate,
            self.song.track.string_pitches,
            fret_count,
        )
        painter.setBrush(color)
        for span in spans:
            painter.drawRoundedRect(
                self._scale_span_rect(
                    board,
                    fret_gap,
                    string_gap,
                    span.string_index,
                    span.start_fret,
                    span.end_fret,
                    row_height,
                ),
                5,
                5,
            )

    def _draw_usage_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        if self.song is None or self.preferred_scale is None:
            return
        positions: set[tuple[int, int]] = set()
        pitch_classes = set(self.preferred_scale.pitch_classes)
        preferred_notes = 2 if "pentatonic" in self.preferred_scale.name.lower() else 3
        for usage in usages:
            block_positions: set[tuple[int, int]] = set()
            for span in scale_block_spans((usage.block,), usage.candidate, self.song.track.string_pitches, fret_count):
                open_midi = self.song.track.string_pitches[span.string_index]
                for fret in range(span.start_fret, span.end_fret + 1):
                    if (open_midi + fret) % 12 in pitch_classes:
                        block_positions.add((span.string_index, fret))
            positions.update(
                dedupe_repeated_pitch_positions(
                    block_positions,
                    self.song.track.string_pitches,
                    preferred_notes_per_string=preferred_notes,
                )
            )
        if not positions:
            return

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for _position_string, fret in sorted(position for position in positions if position[0] == string_index):
                pc = (open_midi + fret) % 12
                x = self._fret_center_x(board, fret_gap, fret)
                is_root = pc == self.preferred_scale.root_pc
                radius = 11 if is_root else 9
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(QColor("#8f1d18") if is_root else QColor("#cb3a31"))
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    QRect(x - radius, y - radius, radius * 2, radius * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    interval_name(self.preferred_scale.root_pc, pc),
                )

    def _draw_usage_buttons(
        self,
        painter: QPainter,
        board: QRect,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        self._usage_button_hits = []
        if not usages:
            return

        active_usage_index = self._active_usage_index(usages)
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        for display_number, usage in enumerate(usages, start=1):
            text = f"{display_number}: {usage.block.start_fret}-{usage.block.end_fret} ({usage.selected_count})"
            width = max(72, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = usage.block.index == active_usage_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._usage_button_hits.append((rect, usage.block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)


class ChordPositionsWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.measure: MeasureData | None = None
        self.candidate: Candidate | None = None
        self.positions: tuple[ChordPosition, ...] = ()
        self.root_string_filter: int | None = None
        self.category_filter: str | None = None
        self._content_height = 320
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(380, max(300, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.measure = None
        self.candidate = None
        self.positions = ()
        self._rebuild_layout()
        self.update()

    def set_selection(self, song: SongData | None, measure: MeasureData | None, candidate: Candidate | None) -> None:
        self.song = song
        self.measure = measure
        self.candidate = candidate if candidate is not None and candidate.kind == "chord" else None
        if self.song is not None and self.candidate is not None:
            self.positions = generate_chord_positions(
                self.candidate,
                self.song.track.string_pitches,
                self.song.track.fret_count,
                max_positions=MAX_CHORD_POSITIONS * len(CHORD_POSITION_CATEGORIES),
            )
        else:
            self.positions = ()
        self._rebuild_layout()
        self.update()

    def set_root_string_filter(self, string_number: int | None) -> None:
        self.root_string_filter = string_number
        self._rebuild_layout()
        self.update()

    def set_category_filter(self, category: str | None) -> None:
        self.category_filter = category
        self._rebuild_layout()
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))

        if self.song is None:
            self._draw_empty(painter, "Open a file to show chord positions.")
            return
        if self.candidate is None:
            self._draw_empty(painter, "Click a measure chord chip to show playable positions.")
            return
        if not self.positions:
            self._draw_empty(painter, "No chord positions were found within the current limits.")
            return

        self._draw_title(painter)
        visible_positions = self._visible_positions()
        if not visible_positions:
            self._draw_message(painter, 58, self._empty_filter_message())
            return

        y = 50
        card_height = self._card_height()
        next_index = 1
        triad_message = self._triad_message(visible_positions)
        if triad_message is not None:
            self._draw_category_header(painter, y, "Triad")
            y += 30
            self._draw_category_message(painter, y, triad_message)
            y += 42
        for category, positions in self._visible_groups(visible_positions):
            self._draw_category_header(painter, y, category)
            y += 30
            for position in positions:
                rect = QRect(10, y, max(260, self.width() - 20), card_height)
                self._draw_position_card(painter, rect, next_index, position)
                next_index += 1
                y += card_height + 10

    def _rebuild_layout(self) -> None:
        visible_positions = self._visible_positions()
        if not self.positions or not visible_positions:
            self._content_height = 320
        else:
            group_count = len(self._visible_groups(visible_positions))
            triad_message_count = 1 if self._triad_message(visible_positions) is not None else 0
            self._content_height = (
                60
                + len(visible_positions) * (self._card_height() + 10)
                + (group_count + triad_message_count) * 30
                + triad_message_count * 42
                + 16
            )
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _card_height(self) -> int:
        return 230

    def _draw_empty(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(self.rect().adjusted(18, 18, -18, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_message(self, painter: QPainter, y: int, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRect(18, y, self.width() - 36, 120),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            tr(text),
        )

    def _draw_category_header(self, painter: QPainter, y: int, category: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf5"))
        painter.drawRoundedRect(rect, 6, 6)
        count = len([position for position in self._visible_positions() if category in position.categories])
        count_text = f"  {count}" if count else ""
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{tr(category)}{count_text}")

    def _draw_category_message(self, painter: QPainter, y: int, text: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 34)
        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#657083"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_title(self, painter: QPainter) -> None:
        if self.song is None or self.candidate is None:
            return
        measure_text = f"M{self.measure.number}  " if self.measure is not None else ""
        title = f"{measure_text}{_trf('{name} Chord positions', name=candidate_display_name(self.candidate, self.song.track.prefer_flats))}"
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(14, 10, self.width() - 28, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

    def _draw_position_card(self, painter: QPainter, rect: QRect, index: int, position: ChordPosition) -> None:
        if self.song is None or self.candidate is None:
            return

        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        title = (
            f"{index}. "
            f"{chord_position_display_name(self.candidate, position, self.song.track.prefer_flats)}"
            f" - {tr(position.label)}"
        )
        painter.drawText(
            rect.adjusted(10, 7, -10, -rect.height() + 41),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            title,
        )

        fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
        missing = self._missing_text(position)
        barre = _trf(" - barre {fret} frets", fret=position.barre_fret) if position.barre_fret is not None else ""
        range_start, range_end = self._display_fret_range(position)
        meta = (
            _trf("Fingers {count}", count=position.finger_count)
            + (_trf(" + muted {count}", count=position.muted_finger_count) if position.muted_finger_count else "")
            + barre
            + _trf(" - {start}-{end} frets - {frets} - omitted {missing}", start=range_start, end=range_end, frets=fret_text, missing=missing)
        )
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#526071"))
        painter.drawText(rect.adjusted(10, 45, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, meta)

        board = rect.adjusted(54, 80, -18, -28)
        if board.width() <= 120 or board.height() <= 80:
            return
        self._draw_mini_fretboard(painter, board, position, range_start, range_end)

    def _draw_mini_fretboard(
        self,
        painter: QPainter,
        board: QRect,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / MAX_FRET_SPAN

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(board.adjusted(-4, -8, 4, 8), 5, 5)

        self._draw_mini_barre(painter, board, fret_gap, string_gap, position, range_start, range_end)

        for fret_offset in range(MAX_FRET_SPAN + 1):
            x = int(board.left() + fret_offset * fret_gap)
            is_nut = range_start == 0 and fret_offset == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())

        painter.setFont(QFont("Segoe UI", 8))
        for fret in self._mini_visible_fret_labels(range_start, range_end):
            x = self._mini_fret_center_x(board, fret_gap, fret, range_start)
            painter.setPen(QColor("#697586"))
            painter.drawText(QRect(int(x - fret_gap / 2), board.bottom() + 12, int(fret_gap), 16), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(board.left() - 48, y - 9, 28, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self.song.track.prefer_flats),
            )
            self._draw_open_or_mute(painter, board.left() - 13, y, position, string_index, range_start)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_position_notes(painter, board, fret_gap, string_gap, position, range_start, range_end)

    def _draw_open_or_mute(
        self,
        painter: QPainter,
        x: int,
        y: int,
        position: ChordPosition,
        string_index: int,
        range_start: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return
        fret = position.frets_high_to_low[string_index]
        if fret == MUTED:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.setPen(QColor("#9b1c1c"))
            painter.drawText(QRect(x - 7, y - 10, 14, 20), Qt.AlignmentFlag.AlignCenter, "x")
        elif fret == 0 and range_start != 0:
            interval = (self.song.track.string_pitches[string_index] - self.candidate.root_pc) % 12
            self._draw_note_marker(
                painter,
                x,
                y,
                "0",
                self._chord_position_degree_label(interval),
                False,
                13,
                is_root=interval == 0,
            )

    def _draw_mini_barre(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if position.barre_fret is None or not (range_start <= position.barre_fret <= range_end):
            return
        strings = [index for index, fret in enumerate(position.frets_high_to_low) if fret == position.barre_fret]
        if len(strings) < 2:
            return
        x = self._mini_fret_center_x(board, fret_gap, position.barre_fret, range_start)
        top = int(board.top() + min(strings) * string_gap) - 15
        bottom = int(board.top() + max(strings) * string_gap) + 15
        painter.setPen(QPen(QColor("#b45309"), 1.2))
        painter.setBrush(QColor(250, 204, 21, 150))
        painter.drawRoundedRect(QRect(x - 15, top, 30, bottom - top), 13, 13)

    def _draw_position_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return

        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for string_index, fret in enumerate(position.frets_high_to_low):
            if fret < 0 or not (range_start <= fret <= range_end):
                continue
            x = self._mini_fret_center_x(board, fret_gap, fret, range_start)
            y = int(board.top() + string_index * string_gap)
            is_barre = position.barre_fret == fret
            interval = (self.song.track.string_pitches[string_index] + fret - self.candidate.root_pc) % 12
            degree = self._chord_position_degree_label(interval)
            self._draw_note_marker(
                painter,
                x,
                y,
                str(fret),
                degree,
                is_barre,
                15,
                fret_font,
                degree_font,
                is_root=interval == 0,
            )

    def _draw_note_marker(
        self,
        painter: QPainter,
        x: int,
        y: int,
        fret_text: str,
        degree: str,
        is_barre: bool,
        radius: int,
        fret_font: QFont | None = None,
        degree_font: QFont | None = None,
        is_root: bool = False,
    ) -> None:
        if is_root:
            fill = QColor("#dc2626")
            border = QColor("#991b1b")
        elif is_barre:
            fill = QColor("#fde68a")
            border = QColor("#b45309")
        else:
            fill = QColor("#16a34a")
            border = QColor("#0f6f34")
        painter.setPen(QPen(border, 2))
        painter.setBrush(fill)
        painter.drawEllipse(QPoint(x, y), radius, radius)

        text_color = QColor("#111827") if is_barre and not is_root else QColor("#ffffff")
        painter.setPen(text_color)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setFont(fret_font or QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, fret_text)
        painter.setFont(degree_font or QFont("Segoe UI", 5, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)

    def _chord_position_degree_label(self, interval: int) -> str:
        return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]

    def _mini_visible_fret_labels(self, range_start: int, range_end: int) -> range:
        if range_start == 0:
            return range(1, range_end + 2)
        return range(range_start, range_end + 1)

    def _mini_fret_center_x(self, board: QRect, fret_gap: float, fret: int, range_start: int) -> int:
        if fret == 0:
            return int(board.left())
        if range_start == 0:
            return int(board.left() + (fret - 0.5) * fret_gap)
        return int(board.left() + (fret - range_start + 0.5) * fret_gap)

    def _visible_positions(self) -> tuple[ChordPosition, ...]:
        return filter_chord_positions(
            self.positions,
            self.root_string_filter,
            self.category_filter,
            max_positions=MAX_CHORD_POSITIONS,
        )

    def _visible_groups(
        self,
        visible_positions: tuple[ChordPosition, ...],
    ) -> tuple[tuple[str, tuple[ChordPosition, ...]], ...]:
        if self.category_filter is not None:
            return ((self.category_filter, visible_positions),)
        return group_chord_positions_by_category(visible_positions)

    def _triad_message(self, visible_positions: tuple[ChordPosition, ...]) -> str | None:
        return None

    def _empty_filter_message(self) -> str:
        parts: list[str] = []
        if self.root_string_filter is not None:
            parts.append(_trf("root on string {number}", number=self.root_string_filter))
        if self.category_filter is not None:
            parts.append(_trf("{category} category", category=tr(self.category_filter)))
        if parts:
            return _trf("No {filters} chord positions were found.", filters=" ".join(parts))
        return tr("No chord positions to show.")

    def _display_fret_range(self, position: ChordPosition) -> tuple[int, int]:
        if position.fretted_count == 0:
            return 0, MAX_FRET_SPAN - 1
        if position.open_count and position.max_fret <= MAX_FRET_SPAN - 1:
            return 0, MAX_FRET_SPAN - 1
        start = max(1, position.min_fret)
        return start, start + MAX_FRET_SPAN - 1

    def _missing_text(self, position: ChordPosition) -> str:
        if self.candidate is None:
            return "-"
        missing = [self._chord_position_degree_label(interval) for interval in position.missing_intervals]
        return ", ".join(missing) if missing else tr("None")


class ChordFinderWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.selected_positions: list[tuple[int, int]] = []
        self.root_filter: int | None = None
        self.type_filter: str | None = None
        self.matches: tuple[ChordMatch, ...] = ()
        self.entries: tuple[tuple[ChordMatch, ChordPosition], ...] = ()
        self.match_count = 0
        self._position_cache: dict[tuple[int, str, tuple[int, ...], tuple[int, ...], int], tuple[ChordPosition, ...]] = {}
        self._searching = False
        self._search_token = 0
        self._chord_search_thread: QThread | None = None
        self._chord_search_worker: _ChordFinderSearchWorker | None = None
        self._pending_search_params: _ChordFinderSearchParams | None = None
        self._note_hits: list[tuple[QRect, int, int]] = []
        self._content_height = 560
        self.fretboard_scroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self.fretboard_scroll.valueChanged.connect(lambda _value: self.update())
        self.fretboard_scroll.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumWidth(320)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._rebuild_layout()

    def sizeHint(self) -> QSize:
        return QSize(380, max(420, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self._position_cache = {}
        string_count = len(self._string_pitches())
        display_fret_count = self._display_fret_count()
        self.selected_positions = [
            (string_index, fret)
            for string_index, fret in self.selected_positions
            if 0 <= string_index < string_count and 0 <= fret <= display_fret_count
        ]
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def set_root_filter(self, root_pc: int | None, clear_selection: bool = False) -> None:
        self.root_filter = root_pc
        if clear_selection:
            self.selected_positions = []
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def set_type_filter(self, type_suffix: str | None, clear_selection: bool = False) -> None:
        self.type_filter = type_suffix
        if clear_selection:
            self.selected_positions = []
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def shutdown(self) -> None:
        self._pending_search_params = None
        self._search_token += 1
        if self._chord_search_thread is not None and self._chord_search_thread.isRunning():
            self._chord_search_thread.quit()
            self._chord_search_thread.wait(2000)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_fretboard_scrollbar()
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, string_index, fret in self._note_hits:
            if rect.contains(position):
                selected_position = (string_index, fret)
                if selected_position in self.selected_positions:
                    self.selected_positions.remove(selected_position)
                else:
                    self.selected_positions = [
                        (selected_string_index, selected_fret)
                        for selected_string_index, selected_fret in self.selected_positions
                        if selected_string_index != string_index
                    ]
                    self.selected_positions.append(selected_position)
                self._rebuild_matches()
                self._rebuild_layout()
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))
        self._draw_title(painter)
        self._draw_fretboard(painter)
        self._draw_results(painter)

    def _rebuild_matches(self) -> None:
        params = self._search_params()
        self._search_token += 1
        self._pending_search_params = None
        if params is None:
            self._searching = False
            self.matches = ()
            self.entries = ()
            self.match_count = 0
            return

        self._searching = True
        self.matches = ()
        self.entries = ()
        self.match_count = 0
        if self._chord_search_thread is not None and self._chord_search_thread.isRunning():
            self._pending_search_params = params
            return
        self._start_chord_search(params)

    def _search_params(self) -> _ChordFinderSearchParams | None:
        if len(self.selected_positions) == 1:
            return None
        note_pcs = self._selected_note_pcs()
        if not note_pcs and (self.root_filter is None or self.type_filter is None):
            return None
        return _ChordFinderSearchParams(
            note_pcs=note_pcs,
            selected_positions=tuple(self.selected_positions),
            root_filter=self.root_filter,
            type_filter=self.type_filter,
            string_pitches=self._string_pitches(),
            fret_count=self._fret_count(),
        )

    def _start_chord_search(self, params: _ChordFinderSearchParams) -> None:
        token = self._search_token
        thread = QThread(self)
        worker = _ChordFinderSearchWorker(token, params)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_chord_search_finished)
        worker.failed.connect(self._on_chord_search_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_chord_search_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._chord_search_thread = thread
        self._chord_search_worker = worker
        thread.start()

    def _on_chord_search_finished(self, token: int, result: object) -> None:
        if token != self._search_token or not isinstance(result, _ChordFinderSearchResult):
            return
        self._searching = False
        self.matches = result.matches
        self.entries = result.entries
        self.match_count = result.match_count
        self._rebuild_layout()
        self.update()

    def _on_chord_search_failed(self, token: int, message: str) -> None:
        if token != self._search_token:
            return
        self._searching = False
        self.matches = ()
        self.entries = ()
        self.match_count = 0
        self._rebuild_layout()
        self.update()

    def _on_chord_search_thread_finished(self) -> None:
        self._chord_search_thread = None
        self._chord_search_worker = None
        if self._pending_search_params is None:
            return
        params = self._pending_search_params
        self._pending_search_params = None
        self._search_token += 1
        self._start_chord_search(params)

    def _rebuild_layout(self) -> None:
        self._sync_fretboard_scrollbar()
        result_y = self._results_start_y()
        if not self.entries:
            self._content_height = max(460, result_y + 112)
        else:
            self._content_height = (
                result_y
                + 42
                + len(self.entries) * (self._card_height() + 10)
                + 18
            )
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _card_height(self) -> int:
        return 230

    def _string_pitches(self) -> tuple[int, ...]:
        if self.song is not None:
            return self.song.track.string_pitches
        return DEFAULT_FINDER_STRING_PITCHES_HIGH_TO_LOW

    def _fret_count(self) -> int:
        if self.song is not None:
            return self.song.track.fret_count
        return DEFAULT_FINDER_FRET_COUNT

    def _display_fret_count(self) -> int:
        return min(MAX_DISPLAY_FRET, max(12, self._fret_count()))

    def _prefer_flats(self) -> bool | None:
        return self.song.track.prefer_flats if self.song is not None else None

    def _selected_note_pcs(self) -> tuple[int, ...]:
        pitches = self._string_pitches()
        seen: set[int] = set()
        note_pcs: list[int] = []
        for string_index, fret in self.selected_positions:
            if string_index < 0 or string_index >= len(pitches):
                continue
            pc = (pitches[string_index] + fret) % 12
            if pc in seen:
                continue
            seen.add(pc)
            note_pcs.append(pc)
        return tuple(note_pcs)

    def _selected_note_names(self) -> str:
        return " ".join(self._pitch_name(pc) for pc in self._selected_note_pcs())

    def _board_viewport_rect(self) -> QRect:
        string_count = max(1, len(self._string_pitches()))
        board_height = max(104, (string_count - 1) * 24)
        return QRect(56, 64, max(240, self.width() - 84), board_height)

    def _board_virtual_width(self, viewport_width: int) -> int:
        return max(viewport_width * 2, 600)

    def _sync_fretboard_scrollbar(self) -> None:
        viewport = self._board_viewport_rect()
        virtual_width = self._board_virtual_width(viewport.width())
        maximum = max(0, virtual_width - viewport.width())
        self.fretboard_scroll.setGeometry(QRect(viewport.left(), viewport.bottom() + 48, viewport.width(), 16))
        self.fretboard_scroll.setRange(0, maximum)
        self.fretboard_scroll.setPageStep(viewport.width())
        self.fretboard_scroll.setSingleStep(max(16, viewport.width() // 10))
        self.fretboard_scroll.setVisible(maximum > 0)

    def _board_metrics(self) -> tuple[QRect, QRect, int, float, float]:
        string_count = max(1, len(self._string_pitches()))
        viewport = self._board_viewport_rect()
        virtual_width = self._board_virtual_width(viewport.width())
        scroll_offset = min(self.fretboard_scroll.value(), max(0, virtual_width - viewport.width()))
        board = QRect(viewport.left() - scroll_offset, viewport.top(), virtual_width, viewport.height())
        fret_count = self._display_fret_count()
        fret_gap = board.width() / max(1, fret_count)
        string_gap = board.height() / max(1, string_count - 1)
        return viewport, board, fret_count, fret_gap, string_gap

    def _results_start_y(self) -> int:
        board = self._board_viewport_rect()
        return board.bottom() + 82

    def _draw_title(self, painter: QPainter) -> None:
        selected_notes = self._selected_note_names()
        title = _trf("{notes} containing chords", notes=selected_notes) if selected_notes else self._filter_title()
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(14, 10, self.width() - 28, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#657083"))
        painter.drawText(
            QRect(14, 34, self.width() - 28, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            _trf(
                "{strings} strings - {frets} frets - selected {selected}",
                strings=len(self._string_pitches()),
                frets=self._display_fret_count(),
                selected=len(self.selected_positions),
            ),
        )

    def _draw_fretboard(self, painter: QPainter) -> None:
        self._sync_fretboard_scrollbar()
        viewport, board, fret_count, fret_gap, string_gap = self._board_metrics()
        pitches = self._string_pitches()
        if viewport.width() <= 80 or viewport.height() <= 80 or not pitches:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(viewport.adjusted(-4, -8, 4, 8), 5, 5)

        for string_index, open_midi in enumerate(pitches):
            y = int(viewport.top() + string_index * string_gap)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(viewport.left() - 50, y - 9, 30, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self._prefer_flats()),
            )

        painter.save()
        painter.setClipRect(viewport.adjusted(-2, -8, 2, 66))

        for fret in range(fret_count + 1):
            x = int(board.left() + fret * fret_gap)
            is_nut = fret == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 12, int(fret_gap * 2), 16),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, _open_midi in enumerate(pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._build_note_hits(board, fret_count, fret_gap, string_gap)
        self._draw_selected_notes(painter, board, fret_gap, string_gap)
        painter.restore()

    def _build_note_hits(self, board: QRect, fret_count: int, fret_gap: float, string_gap: float) -> None:
        self._note_hits = []
        hit_radius = max(12, min(20, int(fret_gap * 0.55)))
        for string_index, _open_midi in enumerate(self._string_pitches()):
            y = int(board.top() + string_index * string_gap)
            for fret in range(fret_count + 1):
                x = self._fret_center_x(board, fret_gap, fret)
                self._note_hits.append((QRect(x - hit_radius, y - hit_radius, hit_radius * 2, hit_radius * 2), string_index, fret))

    def _draw_selected_notes(self, painter: QPainter, board: QRect, fret_gap: float, string_gap: float) -> None:
        pitches = self._string_pitches()
        for string_index, fret in self.selected_positions:
            if string_index >= len(pitches) or fret > self._display_fret_count():
                continue
            pc = (pitches[string_index] + fret) % 12
            x = self._fret_center_x(board, fret_gap, fret)
            y = int(board.top() + string_index * string_gap)
            self._draw_selected_note_marker(painter, x, y, self._pitch_name(pc), str(fret))

    def _draw_selected_note_marker(self, painter: QPainter, x: int, y: int, note_text: str, fret_text: str) -> None:
        radius = 15
        painter.setPen(QPen(QColor("#0f6f34"), 2))
        painter.setBrush(QColor("#16a34a"))
        painter.drawEllipse(QPoint(x, y), radius, radius)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setPen(QColor("#ffffff"))
        note_font_size = 7 if len(note_text) >= 2 else 8
        painter.setFont(QFont("Segoe UI", note_font_size, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, note_text)
        painter.setFont(QFont("Segoe UI", 6, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, fret_text)

    def _draw_results(self, painter: QPainter) -> None:
        y = self._results_start_y()
        selected_notes = self._selected_note_names()
        if self._searching:
            self._draw_message(painter, y, "Searching chords...")
            return
        if len(self.selected_positions) == 1:
            self._draw_message(painter, y, "Select two or more notes to find chords.")
            return
        if not selected_notes and (self.root_filter is None or self.type_filter is None):
            self._draw_message(painter, y, "No selected notes")
            return
        if not self.entries:
            self._draw_message(painter, y, "No chords match the filters.")
            return

        summary = (
            _trf("Selected notes {notes} - chords {count}", notes=selected_notes, count=self.match_count)
            if selected_notes
            else _trf("{filter} - chords {count}", filter=self._filter_title(), count=self.match_count)
        )
        if self.match_count > len(self.entries):
            summary += _trf(" - top {count} shown", count=len(self.entries))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf5"))
        header_rect = QRect(10, y, max(260, self.width() - 20), 24)
        painter.drawRoundedRect(header_rect, 6, 6)
        painter.setPen(QColor("#253044"))
        painter.drawText(header_rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, summary)
        y += 36

        card_height = self._card_height()
        for index, (match, position) in enumerate(self.entries, start=1):
            rect = QRect(10, y, max(260, self.width() - 20), card_height)
            self._draw_match_card(painter, rect, index, match, position)
            y += card_height + 10

    def _draw_message(self, painter: QPainter, y: int, text: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 72)
        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor("#657083"))
        painter.drawText(rect.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_match_card(
        self,
        painter: QPainter,
        rect: QRect,
        index: int,
        match: ChordMatch,
        position: ChordPosition,
    ) -> None:
        prefer_flats = self._prefer_flats()
        chord_name = candidate_display_name(match.candidate, prefer_flats)
        root = pitch_class_name(match.candidate.root_pc, prefer_flats)
        notes = " ".join(pitch_class_name(pc, prefer_flats) for pc in match.candidate.pitch_classes)
        roles = self._selected_roles_text(match)
        meta = _trf("Root {root} - type {type}", root=root, type=match.chord_type.display_name)
        if roles:
            meta += _trf(" - selected notes {roles}", roles=roles)

        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            rect.adjusted(10, 7, -10, -rect.height() + 41),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            f"{index}. {chord_name}",
        )
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#526071"))
        painter.drawText(
            rect.adjusted(10, 45, -10, -rect.height() + 74),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            _trf("{meta} - notes {notes}", meta=meta, notes=notes),
        )

        range_start, range_end = self._display_fret_range(position)
        fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
        missing = self._missing_text(position)
        barre = _trf(" - barre {fret} frets", fret=position.barre_fret) if position.barre_fret is not None else ""
        position_meta = (
            _trf("Fingers {count}", count=position.finger_count)
            + (_trf(" + muted {count}", count=position.muted_finger_count) if position.muted_finger_count else "")
            + barre
            + _trf(" - {start}-{end} frets - {frets} - omitted {missing}", start=range_start, end=range_end, frets=fret_text, missing=missing)
        )
        painter.setPen(QColor("#526071"))
        painter.drawText(rect.adjusted(10, 64, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, position_meta)

        board = rect.adjusted(54, 96, -18, -28)
        if board.width() <= 120 or board.height() <= 80:
            return
        self._draw_match_mini_fretboard(painter, board, match.candidate, position, range_start, range_end)

    def _positions_for_match(self, match: ChordMatch) -> tuple[ChordPosition, ...]:
        key = (
            match.candidate.root_pc,
            match.chord_type.suffix,
            match.candidate.intervals,
            self._string_pitches(),
            self._fret_count(),
        )
        if key not in self._position_cache:
            positions = generate_chord_positions(
                match.candidate,
                self._string_pitches(),
                self._fret_count(),
                max_positions=MAX_CHORD_POSITIONS * len(CHORD_POSITION_CATEGORIES),
            )
            self._position_cache[key] = tuple(
                position for position in positions if self._barre_open_strings_are_playable(position)
            )
        return self._position_cache[key]

    def _position_contains_selected_frets(self, position: ChordPosition) -> bool:
        for string_index, fret in self.selected_positions:
            if string_index < 0 or string_index >= len(position.frets_high_to_low):
                return False
            if position.frets_high_to_low[string_index] != fret:
                return False
        return True

    def _selected_fret_span_can_fit(self) -> bool:
        fretted = [fret for _string_index, fret in self.selected_positions if fret > 0]
        if not fretted:
            return True
        if 0 in [fret for _string_index, fret in self.selected_positions] and max(fretted) > MAX_FRET_SPAN - 1:
            return False
        return max(fretted) - min(fretted) <= MAX_FRET_SPAN - 1

    def _barre_open_strings_are_playable(self, position: ChordPosition) -> bool:
        if position.barre_fret is None:
            return True
        barre_strings = [
            string_index
            for string_index, fret in enumerate(position.frets_high_to_low)
            if fret == position.barre_fret
        ]
        if len(barre_strings) < 2:
            return True
        thinnest_barred_string = min(barre_strings)
        return all(
            fret != 0
            for string_index, fret in enumerate(position.frets_high_to_low)
            if string_index < thinnest_barred_string
        )

    def _match_key(self, match: ChordMatch) -> tuple[int, str, tuple[int, ...]]:
        return (match.candidate.root_pc, match.chord_type.suffix, match.candidate.intervals)

    def _selected_roles_text(self, match: ChordMatch) -> str:
        parts = [
            f"{self._pitch_name(note_pc)}={self._chord_position_degree_label(interval)}"
            for note_pc, interval in zip(match.selected_note_pcs, match.selected_intervals)
        ]
        return ", ".join(parts)

    def _filter_title(self) -> str:
        root = tr("All")
        if self.root_filter is not None:
            root = pitch_class_name(self.root_filter, self._prefer_flats())
        chord_type = tr("All")
        if self.type_filter is not None:
            for item in CHORD_FINDER_TYPES:
                if item.suffix == self.type_filter:
                    chord_type = item.display_name
                    break
        if self.root_filter is None and self.type_filter is None:
            return tr("Chord finder")
        return f"{root} {chord_type}".strip()

    def _pitch_name(self, pitch_class: int) -> str:
        return pitch_class_name(pitch_class, self._prefer_flats())

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_match_mini_fretboard(
        self,
        painter: QPainter,
        board: QRect,
        candidate: Candidate,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        string_pitches = self._string_pitches()
        string_count = len(string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / MAX_FRET_SPAN

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(board.adjusted(-4, -8, 4, 8), 5, 5)

        self._draw_match_mini_barre(painter, board, fret_gap, string_gap, position, range_start, range_end)

        for fret_offset in range(MAX_FRET_SPAN + 1):
            x = int(board.left() + fret_offset * fret_gap)
            is_nut = range_start == 0 and fret_offset == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())

        painter.setFont(QFont("Segoe UI", 8))
        for fret in self._match_visible_fret_labels(range_start, range_end):
            x = self._match_fret_center_x(board, fret_gap, fret, range_start)
            painter.setPen(QColor("#697586"))
            painter.drawText(QRect(int(x - fret_gap / 2), board.bottom() + 12, int(fret_gap), 16), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, open_midi in enumerate(string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(board.left() - 48, y - 9, 28, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self._prefer_flats()),
            )
            self._draw_match_open_or_mute(painter, board.left() - 13, y, candidate, position, string_index, range_start)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_match_position_notes(painter, board, fret_gap, string_gap, candidate, position, range_start, range_end)

    def _draw_match_open_or_mute(
        self,
        painter: QPainter,
        x: int,
        y: int,
        candidate: Candidate,
        position: ChordPosition,
        string_index: int,
        range_start: int,
    ) -> None:
        fret = position.frets_high_to_low[string_index]
        if fret == MUTED:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.setPen(QColor("#9b1c1c"))
            painter.drawText(QRect(x - 7, y - 10, 14, 20), Qt.AlignmentFlag.AlignCenter, "x")
        elif fret == 0 and range_start != 0:
            interval = (self._string_pitches()[string_index] - candidate.root_pc) % 12
            self._draw_chord_position_marker(
                painter,
                x,
                y,
                "0",
                self._chord_position_degree_label(interval),
                False,
                13,
                is_root=interval == 0,
            )

    def _draw_match_mini_barre(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if position.barre_fret is None or not (range_start <= position.barre_fret <= range_end):
            return
        strings = [index for index, fret in enumerate(position.frets_high_to_low) if fret == position.barre_fret]
        if len(strings) < 2:
            return
        x = self._match_fret_center_x(board, fret_gap, position.barre_fret, range_start)
        top = int(board.top() + min(strings) * string_gap) - 15
        bottom = int(board.top() + max(strings) * string_gap) + 15
        painter.setPen(QPen(QColor("#b45309"), 1.2))
        painter.setBrush(QColor(250, 204, 21, 150))
        painter.drawRoundedRect(QRect(x - 15, top, 30, bottom - top), 13, 13)

    def _draw_match_position_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        candidate: Candidate,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for string_index, fret in enumerate(position.frets_high_to_low):
            if fret < 0 or not (range_start <= fret <= range_end):
                continue
            x = self._match_fret_center_x(board, fret_gap, fret, range_start)
            y = int(board.top() + string_index * string_gap)
            is_barre = position.barre_fret == fret
            interval = (self._string_pitches()[string_index] + fret - candidate.root_pc) % 12
            degree = self._chord_position_degree_label(interval)
            self._draw_chord_position_marker(
                painter,
                x,
                y,
                str(fret),
                degree,
                is_barre,
                15,
                fret_font,
                degree_font,
                is_root=interval == 0,
            )

    def _draw_chord_position_marker(
        self,
        painter: QPainter,
        x: int,
        y: int,
        fret_text: str,
        degree: str,
        is_barre: bool,
        radius: int,
        fret_font: QFont | None = None,
        degree_font: QFont | None = None,
        is_root: bool = False,
    ) -> None:
        if is_root:
            fill = QColor("#dc2626")
            border = QColor("#991b1b")
        elif is_barre:
            fill = QColor("#fde68a")
            border = QColor("#b45309")
        else:
            fill = QColor("#16a34a")
            border = QColor("#0f6f34")
        painter.setPen(QPen(border, 2))
        painter.setBrush(fill)
        painter.drawEllipse(QPoint(x, y), radius, radius)

        text_color = QColor("#111827") if is_barre and not is_root else QColor("#ffffff")
        painter.setPen(text_color)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setFont(fret_font or QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, fret_text)
        painter.setFont(degree_font or QFont("Segoe UI", 5, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)

    def _chord_position_degree_label(self, interval: int) -> str:
        return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]

    def _match_visible_fret_labels(self, range_start: int, range_end: int) -> range:
        if range_start == 0:
            return range(1, range_end + 2)
        return range(range_start, range_end + 1)

    def _match_fret_center_x(self, board: QRect, fret_gap: float, fret: int, range_start: int) -> int:
        if fret == 0:
            return int(board.left())
        if range_start == 0:
            return int(board.left() + (fret - 0.5) * fret_gap)
        return int(board.left() + (fret - range_start + 0.5) * fret_gap)

    def _display_fret_range(self, position: ChordPosition) -> tuple[int, int]:
        if position.fretted_count == 0:
            return 0, MAX_FRET_SPAN - 1
        if position.open_count and position.max_fret <= MAX_FRET_SPAN - 1:
            return 0, MAX_FRET_SPAN - 1
        start = max(1, position.min_fret)
        return start, start + MAX_FRET_SPAN - 1

    def _missing_text(self, position: ChordPosition) -> str:
        missing = [self._chord_position_degree_label(interval) for interval in position.missing_intervals]
        return ", ".join(missing) if missing else tr("None")

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        if fret_count >= 12:
            x = self._fret_center_x(board, fret_gap, 12)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)


class TabAnalyzerWindow(QMainWindow):
    def __init__(self, initial_file: str | Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Tab Analyzer")
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1280, 860)

        self.tab_canvas = TabCanvas()
        self.top_tabs = QTabWidget()
        self.analysis_scroll = QScrollArea()
        self.analysis_tab_index = -1
        self.tab_playback_tab_index = -1
        self.songsterr_tab_index = -1
        self.tab_playback_panel = TabPlaybackPanel()
        self.songsterr_panel = SongsterrPagePanel()
        self.fretboard = FretboardWidget()
        self.scale_position_widget = ScalePositionWidget()
        self.scale_position_panel = QWidget()
        self.scale_root_combo = QComboBox()
        self.scale_type_combo = QComboBox()
        self.song_scale_usage_widget = SongScaleUsageWidget()
        self.song_scale_usage_panel = QWidget()
        self.song_scale_count_spin = QSpinBox()
        self.theory_explainer = TheoryExplainer()
        self.theory_browser = QTextBrowser()
        self.memo_editor = MemoEditorWidget()
        self.measure_tabs = QTabWidget()
        self.song_browser = QTextBrowser()
        self.chord_positions_widget = ChordPositionsWidget()
        self.chord_positions_scroll = QScrollArea()
        self.chord_positions_panel = QWidget()
        self.root_string_combo = QComboBox()
        self.category_combo = QComboBox()
        self.chord_finder_widget = ChordFinderWidget()
        self.chord_finder_scroll = QScrollArea()
        self.chord_finder_panel = QWidget()
        self.chord_finder_root_combo = QComboBox()
        self.chord_finder_type_combo = QComboBox()
        self.right_tabs = QTabWidget()
        self.tuning_presets = load_tuning_presets()
        self.track_combo = QComboBox()
        self.tuning_combo = QComboBox()
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(65, 240)
        self.zoom_slider.setValue(100)
        self.zoom_label = QLabel("100%")
        self.current_file: Path | None = None
        self.source_song: SongData | None = None
        self.song: SongData | None = None
        self.memo_path: Path | None = None
        self.memo_autosave_path: Path | None = None
        self.measure_memos: dict[int, str] = {}
        self.current_memo_measure_index: int | None = None
        self.memo_dirty = False
        self.memo_text_pending = False
        self.memo_icon_refresh_pending = False
        self.memo_asset_dir: Path | None = None
        self.memo_autosave_timer = QTimer(self)
        self.memo_sync_timer = QTimer(self)
        self.manual_dialog: QDialog | None = None
        self.about_dialog: QDialog | None = None
        self.tuner_dialog: ChromaticTunerDialog | None = None
        self.vst_host_dialog: VstHostDialog | None = None
        self._preserving_playback_selection = False
        self._songsterr_playback_measure_index: int | None = None
        self._songsterr_playback_base_tick: int | None = None
        self._songsterr_playback_speed_percent = 100.0
        self._songsterr_playback_clock = QElapsedTimer()
        self._songsterr_playback_tick_timer = QTimer(self)
        self._load_thread: QThread | None = None
        self._load_worker: _LoadWorker | None = None
        self._load_progress_dialog: AnalysisProgressDialog | None = None
        self._songsterr_thread: QThread | None = None
        self._songsterr_worker: _SongsterrWorker | None = None
        self._songsterr_progress_dialog: AnalysisProgressDialog | None = None
        self.recent_files_menu: QMenu | None = None

        self._build_ui()
        self.tab_canvas.selectionChanged.connect(self._on_selection_changed)
        self.tab_canvas.memoClicked.connect(self._open_memo_for_measure)
        self.tab_playback_panel.selectionChanged.connect(self._on_tab_block_selection_changed)
        self.tab_playback_panel.playbackMeasureChanged.connect(self._on_tab_playback_measure_changed)
        self.tab_playback_panel.playbackTickChanged.connect(self.fretboard.set_playback_tick)
        self.songsterr_panel.playbackPositionChanged.connect(self._on_songsterr_playback_position_changed)
        self._songsterr_playback_tick_timer.setInterval(25)
        self._songsterr_playback_tick_timer.timeout.connect(self._advance_songsterr_playback_tick)
        self.tab_canvas.zoomWheelRequested.connect(self._adjust_zoom_by_delta)
        self.tab_playback_panel.zoomWheelRequested.connect(self._adjust_zoom_by_delta)
        self.analysis_scroll.viewport().installEventFilter(self)
        self.tab_playback_panel.score_scroll.viewport().installEventFilter(self)
        self.memo_editor.textChanged.connect(self._on_memo_text_changed)
        self.memo_sync_timer.setInterval(5000)
        self.memo_sync_timer.timeout.connect(self._sync_memo_if_editor_active)
        self.memo_sync_timer.start()
        self.memo_autosave_timer.setInterval(10000)
        self.memo_autosave_timer.timeout.connect(self._autosave_memo)
        self.memo_autosave_timer.start()
        self._update_theory_panel(None, None, "scale", None)
        self._update_song_panel()
        self._update_chord_position_panel(None, None)
        self.right_tabs.setCurrentIndex(0)
        apply_translations(self)

        if initial_file:
            self.load_file(initial_file)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if watched is self.analysis_scroll.viewport() or watched is self.tab_playback_panel.score_scroll.viewport():
                delta = event.angleDelta().y()
                if delta:
                    self._adjust_zoom_by_delta(10 if delta > 0 else -10)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _build_ui(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        extras_menu = self.menuBar().addMenu("Additional Features")
        help_menu = self.menuBar().addMenu("Help")

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction(tr("File Open"), self)
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)
        toolbar.addAction(open_action)
        self.recent_files_menu = file_menu.addMenu("Recent files")
        self._refresh_recent_files_menu()
        close_file_action = QAction("Close file", self)
        close_file_action.triggered.connect(self._close_file)
        file_menu.addAction(close_file_action)
        file_menu.addSeparator()
        songsterr_action = QAction("Search Songsterr tabs", self)
        songsterr_action.triggered.connect(self._search_songsterr)
        file_menu.addAction(songsterr_action)
        toolbar.addAction(songsterr_action)
        songsterr_login_action = QAction("Songsterr login", self)
        songsterr_login_action.triggered.connect(self._login_songsterr)
        file_menu.addAction(songsterr_login_action)
        toolbar.addAction(songsterr_login_action)
        file_menu.addSeparator()
        memo_save_action = QAction("Save memo", self)
        memo_save_action.setShortcut(QKeySequence("Ctrl+S"))
        memo_save_action.triggered.connect(self._save_memo)
        file_menu.addAction(memo_save_action)
        memo_save_as_action = QAction("Save memo as", self)
        memo_save_as_action.triggered.connect(self._save_memo_as)
        file_menu.addAction(memo_save_as_action)
        memo_load_action = QAction("Load memo", self)
        memo_load_action.setShortcut(QKeySequence("Ctrl+L"))
        memo_load_action.triggered.connect(self._load_memo_from_dialog)
        file_menu.addAction(memo_load_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        tuner_action = QAction("Chromatic tuner", self)
        tuner_action.triggered.connect(self._open_chromatic_tuner)
        extras_menu.addAction(tuner_action)
        vst_action = QAction("VST Effect Rack", self)
        vst_action.triggered.connect(self._open_vst_effect_rack)
        extras_menu.addAction(vst_action)
        help_action = QAction("Manual", self)
        help_action.triggered.connect(self._open_manual)
        help_menu.addAction(help_action)
        about_action = QAction("About", self)
        about_action.triggered.connect(self._open_about)
        help_menu.addAction(about_action)
        toolbar.addSeparator()

        zoom_out = QPushButton("-")
        zoom_out.setFixedWidth(30)
        zoom_out.clicked.connect(lambda: self.zoom_slider.setValue(max(65, self.zoom_slider.value() - 10)))
        zoom_in = QPushButton("+")
        zoom_in.setFixedWidth(30)
        zoom_in.clicked.connect(lambda: self.zoom_slider.setValue(min(240, self.zoom_slider.value() + 10)))
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        self.zoom_slider.setFixedWidth(180)
        toolbar.addWidget(QLabel("Zoom"))
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(self.zoom_slider)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(self.zoom_label)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Track"))
        self.track_combo.setMinimumWidth(300)
        self.track_combo.currentIndexChanged.connect(self._on_track_changed)
        toolbar.addWidget(self.track_combo)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Tuning"))
        self.tuning_combo.addItem("From file", None)
        for preset in self.tuning_presets:
            self.tuning_combo.addItem(preset.display_name, preset.id)
        self.tuning_combo.setMinimumWidth(230)
        self.tuning_combo.currentIndexChanged.connect(self._on_tuning_changed)
        toolbar.addWidget(self.tuning_combo)

        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.analysis_scroll.setWidgetResizable(True)
        self.analysis_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.analysis_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.analysis_scroll.setWidget(self.tab_canvas)
        self.analysis_tab_index = self.top_tabs.addTab(self.analysis_scroll, "Analysis measures")
        self.tab_playback_tab_index = self.top_tabs.addTab(self.tab_playback_panel, "Tab player")
        self.top_tabs.currentChanged.connect(self._on_top_tab_changed)
        top_layout.addWidget(self.top_tabs)

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(top_container)
        self.theory_browser.setOpenExternalLinks(True)
        self._populate_scale_position_controls()
        self.scale_root_combo.currentIndexChanged.connect(self._on_scale_position_filter_changed)
        self.scale_type_combo.currentIndexChanged.connect(self._on_scale_position_filter_changed)
        scale_filter_layout = QHBoxLayout()
        scale_filter_layout.setContentsMargins(8, 6, 8, 4)
        scale_filter_layout.setSpacing(8)
        scale_filter_layout.addWidget(QLabel("ROOT"))
        self.scale_root_combo.setMinimumWidth(110)
        scale_filter_layout.addWidget(self.scale_root_combo, 0)
        scale_filter_layout.addWidget(QLabel("Type"))
        self.scale_type_combo.setMinimumWidth(220)
        scale_filter_layout.addWidget(self.scale_type_combo, 1)
        scale_position_layout = QVBoxLayout(self.scale_position_panel)
        scale_position_layout.setContentsMargins(0, 0, 0, 0)
        scale_position_layout.setSpacing(0)
        scale_position_layout.addLayout(scale_filter_layout)
        scale_position_layout.addWidget(self.scale_position_widget, 1)
        self.song_scale_count_spin.setRange(1, 20)
        self.song_scale_count_spin.setValue(5)
        self.song_scale_count_spin.valueChanged.connect(self._on_song_scale_count_changed)
        song_scale_filter_layout = QHBoxLayout()
        song_scale_filter_layout.setContentsMargins(8, 6, 8, 4)
        song_scale_filter_layout.setSpacing(8)
        song_scale_filter_layout.addWidget(QLabel("Shown"))
        song_scale_filter_layout.addWidget(self.song_scale_count_spin, 0)
        song_scale_filter_layout.addStretch(1)
        song_scale_usage_layout = QVBoxLayout(self.song_scale_usage_panel)
        song_scale_usage_layout.setContentsMargins(0, 0, 0, 0)
        song_scale_usage_layout.setSpacing(0)
        song_scale_usage_layout.addLayout(song_scale_filter_layout)
        song_scale_usage_layout.addWidget(self.song_scale_usage_widget, 1)
        self.measure_tabs.addTab(self.fretboard, "Fretboard")
        self.measure_tabs.addTab(self.scale_position_panel, "Scale view")
        self.measure_tabs.addTab(self.song_scale_usage_panel, "Song scale view")
        self.measure_tabs.addTab(self.theory_browser, "Measure notes")
        self.measure_tabs.addTab(self.memo_editor, "Memo")
        self.measure_tabs.setFixedHeight(336)
        left_splitter.addWidget(self.measure_tabs)
        left_splitter.setSizes([510, 336])

        self.song_browser.setOpenExternalLinks(True)
        self.chord_positions_scroll.setWidgetResizable(True)
        self.chord_positions_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chord_positions_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chord_positions_scroll.setWidget(self.chord_positions_widget)
        self.root_string_combo.currentIndexChanged.connect(self._on_root_string_filter_changed)
        self.category_combo.currentIndexChanged.connect(self._on_category_filter_changed)
        self._populate_root_string_combo(6)
        self._populate_category_combo()
        chord_filter_layout = QHBoxLayout()
        chord_filter_layout.setContentsMargins(8, 8, 8, 4)
        chord_filter_layout.addWidget(QLabel("Root string"))
        chord_filter_layout.addWidget(self.root_string_combo, 1)
        chord_filter_layout.addWidget(QLabel("Type"))
        chord_filter_layout.addWidget(self.category_combo, 1)
        chord_panel_layout = QVBoxLayout(self.chord_positions_panel)
        chord_panel_layout.setContentsMargins(0, 0, 0, 0)
        chord_panel_layout.setSpacing(0)
        chord_panel_layout.addLayout(chord_filter_layout)
        chord_panel_layout.addWidget(self.chord_positions_scroll)

        self.chord_finder_scroll.setWidgetResizable(True)
        self.chord_finder_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chord_finder_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chord_finder_scroll.setWidget(self.chord_finder_widget)
        self.chord_finder_root_combo.currentIndexChanged.connect(self._on_chord_finder_root_filter_changed)
        self.chord_finder_type_combo.currentIndexChanged.connect(self._on_chord_finder_type_filter_changed)
        self._populate_chord_finder_controls()
        chord_finder_filter_layout = QHBoxLayout()
        chord_finder_filter_layout.setContentsMargins(8, 8, 8, 4)
        chord_finder_filter_layout.addWidget(QLabel("Root"))
        self.chord_finder_root_combo.setMinimumWidth(105)
        chord_finder_filter_layout.addWidget(self.chord_finder_root_combo, 1)
        chord_finder_filter_layout.addWidget(QLabel("Type"))
        self.chord_finder_type_combo.setMinimumWidth(120)
        chord_finder_filter_layout.addWidget(self.chord_finder_type_combo, 1)
        chord_finder_panel_layout = QVBoxLayout(self.chord_finder_panel)
        chord_finder_panel_layout.setContentsMargins(0, 0, 0, 0)
        chord_finder_panel_layout.setSpacing(0)
        chord_finder_panel_layout.addLayout(chord_finder_filter_layout)
        chord_finder_panel_layout.addWidget(self.chord_finder_scroll)

        self.right_tabs.addTab(self.song_browser, "Song analysis")
        self.right_tabs.addTab(self.chord_positions_panel, "Chord positions")
        self.right_tabs.addTab(self.chord_finder_panel, "Chord finder")
        self.right_tabs.addTab(self.tab_playback_panel.recording_tab, "Recording")
        self.right_tabs.setMinimumWidth(330)
        self.right_tabs.setMaximumWidth(560)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.right_tabs)
        main_splitter.setSizes([920, 360])
        self.setCentralWidget(main_splitter)
        self.setStatusBar(QStatusBar())

    def load_file(self, path: str | Path) -> None:
        if not self._maybe_save_memo_changes():
            return
        self.current_file = Path(path)
        self._start_load_worker(self.current_file, None, include_tracks=True)

    def _close_file(self) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            QMessageBox.information(self, tr("Analyzing"), tr("Close the window after tab file analysis finishes."))
            return
        if not self._maybe_save_memo_changes():
            return
        self.current_file = None
        self.source_song = None
        self._set_current_song(None)
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        self.track_combo.blockSignals(False)
        self.tuning_combo.blockSignals(True)
        self.tuning_combo.setCurrentIndex(0)
        self.tuning_combo.blockSignals(False)
        self.current_memo_measure_index = None
        self._load_memo_for_current_file()
        self._update_theory_panel(None, None, "scale", None)
        self._update_song_panel()
        self._update_chord_position_panel(None, None)
        self.right_tabs.setCurrentIndex(0)
        self.setWindowTitle("Tab Analyzer")
        self.statusBar().clearMessage()

    def _refresh_recent_files_menu(self) -> None:
        if self.recent_files_menu is None:
            return
        self.recent_files_menu.clear()
        recent_files = load_recent_files()
        if not recent_files:
            empty_action = QAction(tr("No recent files"), self)
            empty_action.setEnabled(False)
            self.recent_files_menu.addAction(empty_action)
            return
        for file_path in recent_files:
            action = QAction(str(file_path), self)
            action.setToolTip(str(file_path))
            action.triggered.connect(lambda _checked=False, path=file_path: self._open_recent_file(path))
            self.recent_files_menu.addAction(action)

    def _add_recent_file(self, path: str | Path) -> None:
        add_recent_file(path)
        self._refresh_recent_files_menu()

    def _remove_recent_file(self, path: str | Path) -> None:
        remove_recent_file(path)
        self._refresh_recent_files_menu()

    def _open_recent_file(self, path: str | Path) -> None:
        file_path = Path(path)
        if not file_path.exists():
            self._remove_recent_file(file_path)
            QMessageBox.warning(
                self,
                tr("Recent files"),
                _trf("The file could not be found and was removed from recent files.\n\n{path}", path=file_path),
            )
            return
        self.load_file(file_path)

    def _load_selected_track(self) -> None:
        if self.current_file is None:
            return
        track_index = self.track_combo.currentData()
        if track_index is None:
            track_index = 0
        self._start_load_worker(self.current_file, int(track_index), include_tracks=False)

    def _start_load_worker(self, path: Path, track_index: int | None, include_tracks: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            QMessageBox.information(self, tr("Analyzing"), tr("Another tab file is already being analyzed."))
            return

        self._set_loading_enabled(False)
        self._show_load_progress()
        self._load_worker = _LoadWorker(path, track_index, include_tracks)
        self._load_thread = QThread(self)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.failed.connect(self._on_load_failed)
        self._load_worker.finished.connect(self._load_thread.quit)
        self._load_worker.failed.connect(self._load_thread.quit)
        self._load_thread.finished.connect(self._load_worker.deleteLater)
        self._load_thread.finished.connect(self._on_load_thread_finished)
        self._load_thread.start()

    def _show_load_progress(self) -> None:
        dialog = AnalysisProgressDialog(self)
        self._load_progress_dialog = dialog
        dialog.set_progress(10, "Starting analysis.")
        dialog.show()
        self._center_load_progress()
        QTimer.singleShot(0, self._center_load_progress)

    def _center_load_progress(self) -> None:
        dialog = self._load_progress_dialog
        if dialog is None:
            return
        dialog.adjustSize()
        parent_rect = self.frameGeometry()
        dialog_rect = dialog.frameGeometry()
        dialog_rect.moveCenter(parent_rect.center())
        dialog.move(dialog_rect.topLeft())

    def _on_load_progress(self, value: int, detail: str) -> None:
        if self._load_progress_dialog is not None:
            self._load_progress_dialog.set_progress(value, detail)

    def _on_load_finished(self, result: object) -> None:
        if self._load_progress_dialog is not None:
            self._load_progress_dialog.set_progress(100, "Done.")
        mode, path, tracks, selected_track, song = result
        if Path(path) != self.current_file:
            return
        if mode == "file" and tracks is not None:
            self._populate_track_combo(tracks, int(selected_track))
        self._finish_loaded_song(song)
        if mode == "file":
            self._add_recent_file(path)

    def _on_load_failed(self, message: str) -> None:
        self._close_load_progress()
        self._set_loading_enabled(True)
        QMessageBox.critical(self, tr("Load failed"), message)

    def _on_load_thread_finished(self) -> None:
        self._close_load_progress()
        self._set_loading_enabled(True)
        self._load_thread = None
        self._load_worker = None

    def _close_load_progress(self) -> None:
        if self._load_progress_dialog is None:
            return
        self._load_progress_dialog.close()
        self._load_progress_dialog.deleteLater()
        self._load_progress_dialog = None

    def _start_songsterr_worker(
        self,
        mode: str,
        *,
        query: str = "",
        result: object | None = None,
        cookie: str | None = None,
    ) -> None:
        if self._songsterr_thread is not None and self._songsterr_thread.isRunning():
            QMessageBox.information(self, tr("Processing Songsterr"), tr("A Songsterr task is already running."))
            return
        self._show_songsterr_progress("Searching songs on Songsterr." if mode == "search" else "Downloading the file from Songsterr.")
        self._songsterr_worker = _SongsterrWorker(mode, query=query, result=result, cookie=cookie)
        self._songsterr_thread = QThread(self)
        self._songsterr_worker.moveToThread(self._songsterr_thread)
        self._songsterr_thread.started.connect(self._songsterr_worker.run)
        self._songsterr_worker.progress.connect(self._on_songsterr_progress)
        self._songsterr_worker.finished.connect(self._on_songsterr_finished)
        self._songsterr_worker.failed.connect(self._on_songsterr_failed)
        self._songsterr_worker.authFailed.connect(self._on_songsterr_auth_failed)
        self._songsterr_worker.finished.connect(self._songsterr_thread.quit)
        self._songsterr_worker.failed.connect(self._songsterr_thread.quit)
        self._songsterr_worker.authFailed.connect(self._songsterr_thread.quit)
        self._songsterr_thread.finished.connect(self._songsterr_worker.deleteLater)
        self._songsterr_thread.finished.connect(self._on_songsterr_thread_finished)
        self._songsterr_thread.start()

    def _show_songsterr_progress(self, detail: str) -> None:
        dialog = AnalysisProgressDialog(
            self,
            window_title="Processing Songsterr",
            title_prefix="Processing Songsterr",
            initial_detail=detail,
        )
        self._songsterr_progress_dialog = dialog
        dialog.set_progress(10, detail)
        dialog.show()
        self._center_songsterr_progress()
        QTimer.singleShot(0, self._center_songsterr_progress)

    def _center_songsterr_progress(self) -> None:
        dialog = self._songsterr_progress_dialog
        if dialog is None:
            return
        dialog.adjustSize()
        parent_rect = self.frameGeometry()
        dialog_rect = dialog.frameGeometry()
        dialog_rect.moveCenter(parent_rect.center())
        dialog.move(dialog_rect.topLeft())

    def _on_songsterr_progress(self, value: int, detail: str) -> None:
        if self._songsterr_progress_dialog is not None:
            self._songsterr_progress_dialog.set_progress(value, detail)

    def _on_songsterr_finished(self, result: object) -> None:
        if self._songsterr_progress_dialog is not None:
            self._songsterr_progress_dialog.set_progress(100, "Done.")
        self._close_songsterr_progress()
        mode, _request, payload = result
        if mode == "search":
            results = payload
            if not results:
                QMessageBox.information(self, "Songsterr", tr("No tabs were found for that search."))
                self.statusBar().clearMessage()
                return
            selected = self._choose_songsterr_result(results)
            if selected is None:
                self.statusBar().clearMessage()
                return
            self.statusBar().showMessage(_trf("Exporting from Songsterr: {artist} - {title}", artist=selected.artist, title=selected.title))
            cookie = load_cookie_header() or os.environ.get("SONGSTERR_COOKIE")
            current_thread = self._songsterr_thread
            if current_thread is not None:
                current_thread.finished.connect(lambda: self._start_songsterr_worker("download", result=selected, cookie=cookie))
            else:
                self._start_songsterr_worker("download", result=selected, cookie=cookie)
            return

        path = payload
        self.statusBar().showMessage(_trf("Downloaded {name}", name=path.name))
        self.load_file(path)

    def _on_songsterr_failed(self, message: str) -> None:
        self._close_songsterr_progress()
        QMessageBox.warning(self, tr("Songsterr failed"), message)
        self.statusBar().clearMessage()

    def _on_songsterr_auth_failed(self) -> None:
        self._close_songsterr_progress()
        QMessageBox.warning(
            self,
            tr("Songsterr export requires login"),
            tr(
                "A tab was found on Songsterr, but Guitar Pro export requires login or export permission.\n\n"
                "This app only uses Songsterr's official export API. If your account already has permission, "
                "log in first with the Songsterr login button at the top."
            ),
        )
        self.statusBar().clearMessage()

    def _on_songsterr_thread_finished(self) -> None:
        self._songsterr_thread = None
        self._songsterr_worker = None

    def _close_songsterr_progress(self) -> None:
        if self._songsterr_progress_dialog is None:
            return
        self._songsterr_progress_dialog.close()
        self._songsterr_progress_dialog.deleteLater()
        self._songsterr_progress_dialog = None

    def _set_loading_enabled(self, enabled: bool) -> None:
        self.track_combo.setEnabled(enabled)
        self.tuning_combo.setEnabled(enabled)

    def _finish_loaded_song(self, song: SongData) -> None:
        self.source_song = song
        self._apply_selected_tuning()
        if self.song is None:
            return
        self._load_memo_for_current_file()
        self._update_theory_panel(None, None, "scale", None)
        self._update_song_panel()
        self._update_chord_position_panel(None, None)
        self.right_tabs.setCurrentIndex(0)
        self.setWindowTitle(f"Tab Analyzer - {self.song.title}")
        self.statusBar().showMessage(
            _trf(
                "Loaded {file} - {track} - {measures} measures - tuning {tuning}",
                file=self.song.path.name,
                track=self.song.track.name,
                measures=len(self.song.track.measures),
                tuning=self._current_tuning_name(),
            )
        )

    def _load_memo_for_current_file(self) -> None:
        if self.current_file is None:
            self.memo_path = None
            self.memo_autosave_path = None
            self.measure_memos = {}
            self.memo_dirty = False
            self.memo_text_pending = False
            self.memo_icon_refresh_pending = False
            self._clear_memo_asset_dir()
            self._refresh_memo_icons()
            self._sync_memo_editor()
            return
        target_path = _memo_path_for_tab(self.current_file)
        if self.memo_path == target_path:
            self._refresh_memo_icons()
            self._sync_memo_editor()
            return

        self._clear_memo_asset_dir()
        self.memo_path = target_path
        self.memo_autosave_path = _memo_autosave_path(self.current_file)
        self.measure_memos = {}
        legacy_path = _legacy_memo_path_for_tab(self.current_file)
        load_path = self.memo_path if self.memo_path.exists() else legacy_path if legacy_path.exists() else None
        if load_path is not None:
            try:
                self.memo_asset_dir = self._make_memo_asset_dir() if load_path.suffix.lower() == ".mmdx" else None
                self.measure_memos = _read_memo_package(load_path, self.memo_asset_dir)
            except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
                self._clear_memo_asset_dir()
                self.measure_memos = {}
                QMessageBox.warning(self, tr("Load memo failed"), f"{load_path.name}\n\n{exc}")
        self.memo_dirty = False
        self.memo_text_pending = False
        self.memo_icon_refresh_pending = False

        if self.memo_autosave_path.exists():
            memo_mtime = load_path.stat().st_mtime if load_path is not None else 0
            if self.memo_autosave_path.stat().st_mtime >= memo_mtime:
                result = QMessageBox.question(
                    self,
                    tr("Autosaved memo"),
                    tr("An autosaved memo was found. Load it?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if result == QMessageBox.StandardButton.Yes:
                    try:
                        self._clear_memo_asset_dir()
                        self.memo_asset_dir = self._make_memo_asset_dir()
                        self.measure_memos = _read_memo_package(self.memo_autosave_path, self.memo_asset_dir)
                        self.memo_dirty = True
                    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
                        self._clear_memo_asset_dir()
                        QMessageBox.warning(self, tr("Load autosaved memo failed"), str(exc))
                else:
                    self.memo_autosave_path.unlink(missing_ok=True)

        self.current_memo_measure_index = self.tab_canvas.selected_measure_index
        self._refresh_memo_icons()
        self._sync_memo_editor()

    def _maybe_save_memo_changes(self) -> bool:
        self._sync_current_memo_from_editor(force=True)
        if not self.memo_dirty:
            return True
        result = QMessageBox.question(
            self,
            tr("Save memo"),
            tr("Save memo changes?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Yes:
            return self._save_memo()
        return True

    def _save_memo(self) -> bool:
        self._sync_current_memo_from_editor(force=True)
        if self.memo_path is None:
            return self._save_memo_as()
        if self.memo_path.suffix.lower() != ".mmdx":
            self.memo_path = self.memo_path.with_suffix(".mmdx")
        try:
            _write_memo_package(self.memo_path, self.current_file, self.measure_memos, self._memo_base_dirs())
            self.memo_dirty = False
            self.memo_text_pending = False
            self.memo_icon_refresh_pending = False
            if self.memo_autosave_path is not None:
                self.memo_autosave_path.unlink(missing_ok=True)
            self.statusBar().showMessage(_trf("Memo saved: {name}", name=self.memo_path.name))
            self._refresh_memo_icons()
            return True
        except OSError as exc:
            QMessageBox.warning(self, tr("Save memo failed"), str(exc))
            return False

    def _save_memo_as(self) -> bool:
        self._sync_current_memo_from_editor(force=True)
        start = str(self.memo_path or (Path.cwd() / "memo.mmdx"))
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save memo as"),
            start,
            f"{tr('Tab Analyzer Memo')} (*.mmdx);;{tr('All files')} (*.*)",
        )
        if not path:
            return False
        self.memo_path = Path(path)
        if self.memo_path.suffix.lower() != ".mmdx":
            self.memo_path = self.memo_path.with_suffix(".mmdx")
        return self._save_memo()

    def _load_memo_from_dialog(self) -> None:
        if not self._maybe_save_memo_changes():
            return
        start = str((self.memo_path or Path.cwd()).parent if self.memo_path else Path.cwd())
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Load memo"),
            start,
            f"{tr('Tab Analyzer Memo')} (*.mmdx);;{tr('Legacy Markdown')} (*.md);;{tr('All files')} (*.*)",
        )
        if not path:
            return
        loaded_path = Path(path)
        try:
            self._clear_memo_asset_dir()
            self.memo_asset_dir = self._make_memo_asset_dir() if loaded_path.suffix.lower() == ".mmdx" else None
            self.measure_memos = _read_memo_package(loaded_path, self.memo_asset_dir)
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, tr("Load memo failed"), str(exc))
            return
        except zipfile.BadZipFile as exc:
            QMessageBox.warning(self, tr("Load memo failed"), str(exc))
            return
        self.memo_path = loaded_path if loaded_path.suffix.lower() == ".mmdx" else loaded_path.with_suffix(".mmdx")
        self.memo_dirty = False
        self.memo_text_pending = False
        self.memo_icon_refresh_pending = False
        self._refresh_memo_icons()
        self._sync_memo_editor()
        self.statusBar().showMessage(_trf("Memo loaded: {name}", name=self.memo_path.name))

    def _autosave_memo(self) -> None:
        self._sync_current_memo_from_editor(force=True)
        if not self.memo_dirty or self.memo_autosave_path is None:
            return
        try:
            _write_memo_package(self.memo_autosave_path, self.current_file, self.measure_memos, self._memo_base_dirs())
        except OSError:
            return

    def _open_memo_for_measure(self, measure_index: int) -> None:
        self._set_current_memo_measure_index(measure_index)
        index = self.measure_tabs.indexOf(self.memo_editor)
        if index >= 0:
            self.measure_tabs.setCurrentIndex(index)

    def _set_current_memo_measure_index(self, measure_index: int | None) -> None:
        if measure_index != self.current_memo_measure_index:
            self._sync_current_memo_from_editor(force=True)
        self.current_memo_measure_index = measure_index
        self._sync_memo_editor()

    def _sync_memo_editor(self) -> None:
        self.memo_editor.set_asset_base_dir(self._memo_preview_base_dir())
        if self.song is None or self.current_memo_measure_index is None:
            self.memo_editor.set_measure(None, "")
            return
        if not 0 <= self.current_memo_measure_index < len(self.song.track.measures):
            self.memo_editor.set_measure(None, "")
            return
        measure_number = self.song.track.measures[self.current_memo_measure_index].number
        self.memo_editor.set_measure(measure_number, self.measure_memos.get(measure_number, ""))

    def _on_memo_text_changed(self) -> None:
        self.memo_text_pending = True
        self.memo_dirty = True
        self.memo_icon_refresh_pending = True

    def _sync_memo_if_editor_active(self) -> None:
        if self.memo_editor.has_editor_focus():
            self._sync_current_memo_from_editor()

    def _sync_current_memo_from_editor(self, force: bool = False) -> bool:
        if not force and not self.memo_text_pending:
            return False
        if self.song is None or self.current_memo_measure_index is None:
            self.memo_text_pending = False
            return False
        if not 0 <= self.current_memo_measure_index < len(self.song.track.measures):
            self.memo_text_pending = False
            return False
        measure_number = self.song.track.measures[self.current_memo_measure_index].number
        text = self.memo_editor.text().rstrip()
        before = self.measure_memos.get(measure_number, "")
        if _measure_note_text(text):
            self.measure_memos[measure_number] = text
        else:
            self.measure_memos.pop(measure_number, None)
        self.memo_text_pending = False
        changed = before != self.measure_memos.get(measure_number, "")
        if changed:
            self.memo_dirty = True
            self.memo_icon_refresh_pending = True
        if force or self.memo_icon_refresh_pending:
            self.memo_icon_refresh_pending = False
            self._refresh_memo_icons()
        return changed

    def _refresh_memo_icons(self) -> None:
        self.tab_canvas.set_memo_measure_numbers({number for number, text in self.measure_memos.items() if _measure_note_text(text)})

    def _memo_base_dirs(self) -> tuple[Path, ...]:
        dirs: list[Path] = []
        for item in (
            self.memo_asset_dir,
            self.memo_path.parent if self.memo_path is not None else None,
            self.current_file.parent if self.current_file is not None else None,
        ):
            if item is not None and item not in dirs:
                dirs.append(item)
        return tuple(dirs)

    def _memo_preview_base_dir(self) -> Path | None:
        if self.memo_asset_dir is not None:
            return self.memo_asset_dir
        if self.memo_path is not None:
            return self.memo_path.parent
        if self.current_file is not None:
            return self.current_file.parent
        return None

    def _make_memo_asset_dir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="tab_analyzer_memo_"))

    def _clear_memo_asset_dir(self) -> None:
        if self.memo_asset_dir is not None:
            shutil.rmtree(self.memo_asset_dir, ignore_errors=True)
            self.memo_asset_dir = None

    def _manual_path_for_current_language(self) -> Path:
        language_path = PROJECT_ROOT_PATH / "docs" / f"manual_{current_language()}.html"
        if language_path.exists():
            return language_path
        if MANUAL_EN_PATH.exists():
            return MANUAL_EN_PATH
        return MANUAL_PATH

    def _open_manual(self) -> None:
        manual_path = self._manual_path_for_current_language()
        self._ensure_manual_file(manual_path)
        dialog = self.manual_dialog
        if dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("Tab Analyzer Manual"))
            dialog.resize(980, 720)
            browser = QTextBrowser(dialog)
            browser.setOpenExternalLinks(True)
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(browser)
            dialog.finished.connect(lambda _result: setattr(self, "manual_dialog", None))
            self.manual_dialog = dialog
        browser = self.manual_dialog.findChild(QTextBrowser)
        if browser is not None:
            browser.setSource(QUrl.fromLocalFile(str(manual_path)))
        self.manual_dialog.show()
        self.manual_dialog.raise_()
        self.manual_dialog.activateWindow()

    def _ensure_manual_file(self, manual_path: Path) -> None:
        if manual_path.exists():
            return
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        title = tr("Tab Analyzer Manual")
        message = tr("Preparing the manual file.")
        manual_path.write_text(
            f"""<!doctype html>
<html lang="{html.escape(current_language())}">
<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></body>
</html>
""",
            encoding="utf-8",
        )

    def _open_chromatic_tuner(self) -> None:
        dialog = self.tuner_dialog
        if dialog is None:
            dialog = ChromaticTunerDialog(self)
            dialog.finished.connect(lambda _result: setattr(self, "tuner_dialog", None))
            self.tuner_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_vst_effect_rack(self) -> None:
        dialog = self.vst_host_dialog
        if dialog is None:
            dialog = VstHostDialog(self)
            dialog.finished.connect(lambda _result: setattr(self, "vst_host_dialog", None))
            self.vst_host_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_about(self) -> None:
        dialog = self.about_dialog
        if dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("About Tab Analyzer"))
            dialog.resize(460, 220)

            browser = QTextBrowser(dialog)
            browser.setOpenLinks(False)
            browser.setOpenExternalLinks(False)
            browser.anchorClicked.connect(_open_external_url)
            browser.setHtml(_about_html(__version__))

            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
            buttons.rejected.connect(dialog.close)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(browser)
            layout.addWidget(buttons)
            dialog.finished.connect(lambda _result: setattr(self, "about_dialog", None))
            self.about_dialog = dialog
        else:
            dialog.setWindowTitle(tr("About Tab Analyzer"))
            browser = dialog.findChild(QTextBrowser)
            if browser is not None:
                browser.setHtml(_about_html(__version__))

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _populate_track_combo(self, tracks, selected_track: int) -> None:
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for track in tracks:
            self.track_combo.addItem(track.display_name, track.index)
        selected_index = self.track_combo.findData(selected_track)
        self.track_combo.setCurrentIndex(max(0, selected_index))
        self.track_combo.blockSignals(False)

    def _open_file_dialog(self) -> None:
        start_dir = str(Path.cwd())
        if self.song is not None:
            start_dir = str(self.song.path.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Open Guitar Pro file"),
            start_dir,
            f"{tr('Guitar Pro files')} (*.gp *.gp3 *.gp4 *.gp5 *.gpx);;{tr('All files')} (*.*)",
        )
        if path:
            self.load_file(path)

    def _login_songsterr(self) -> None:
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
            from PyQt6.QtWebEngineWidgets import QWebEngineView
        except Exception as exc:  # noqa: BLE001 - report the actual WebEngine import problem.
            install_command = f'"{sys.executable}" -m pip install PyQt6-WebEngine'
            QMessageBox.warning(
                self,
                tr("Songsterr login unavailable"),
                _trf(
                    "PyQt6-WebEngine is required to open Songsterr login, but the import failed.\n\n"
                    "Current app Python:\n{python}\n\n"
                    "To install into this Python:\n{command}\n\n"
                    "{error_type}:\n{error}",
                    python=sys.executable,
                    command=install_command,
                    error_type=type(exc).__name__,
                    error=exc,
                ),
            )
            return

        try:
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("Songsterr login"))
            dialog.resize(980, 720)

            storage_root = Path.home() / ".tab_analyzer" / "songsterr_web_sessions"
            storage_root.mkdir(parents=True, exist_ok=True)
            session_root = Path(tempfile.mkdtemp(prefix="session_", dir=storage_root))
            profile = QWebEngineProfile(f"tab-analyzer-songsterr-{os.getpid()}-{id(dialog)}", dialog)
            profile.setPersistentStoragePath(str(session_root / "storage"))
            profile.setCachePath(str(session_root / "cache"))
            profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

            popup_windows: list[QDialog] = []

            class SongsterrLoginView(QWebEngineView):
                def createWindow(self, _window_type):  # type: ignore[override]
                    popup = QDialog(dialog)
                    popup.setWindowTitle(tr("Songsterr login"))
                    popup.resize(980, 720)
                    popup_view = SongsterrLoginView(popup)
                    popup_page = QWebEnginePage(profile, popup_view)
                    popup_view.setPage(popup_page)
                    popup_layout = QVBoxLayout(popup)
                    popup_layout.setContentsMargins(0, 0, 0, 0)
                    popup_layout.addWidget(popup_view)
                    popup_page.windowCloseRequested.connect(popup.close)
                    popup.finished.connect(lambda _result, item=popup: popup_windows.remove(item) if item in popup_windows else None)
                    popup_windows.append(popup)
                    popup.show()
                    return popup_view

            view = SongsterrLoginView(dialog)
            view.setPage(QWebEnginePage(profile, view))
        except Exception as exc:  # noqa: BLE001 - show WebEngine runtime initialization failures.
            QMessageBox.warning(
                self,
                tr("Songsterr login unavailable"),
                _trf(
                    "PyQt6-WebEngine is installed, but browser initialization failed.\n\n"
                    "Current app Python:\n{python}\n\n"
                    "{error_type}:\n{error}\n\n"
                    "{traceback}",
                    python=sys.executable,
                    error_type=type(exc).__name__,
                    error=exc,
                    traceback=traceback.format_exc(),
                ),
            )
            return

        cookies: dict[str, str] = {}

        def decode_qbyte(value) -> str:
            try:
                return bytes(value).decode("utf-8", errors="replace")
            except TypeError:
                return str(value)

        def is_songsterr_cookie(cookie) -> bool:
            domain = str(cookie.domain() or "").lower().lstrip(".")
            if domain:
                return domain.endswith("songsterr.com")
            return view.url().host().lower().endswith("songsterr.com")

        def on_cookie_added(cookie) -> None:
            if not is_songsterr_cookie(cookie):
                return
            name = decode_qbyte(cookie.name()).strip()
            value = decode_qbyte(cookie.value()).strip()
            if name and value:
                cookies[name] = value

        def on_cookie_removed(cookie) -> None:
            if not is_songsterr_cookie(cookie):
                return
            name = decode_qbyte(cookie.name()).strip()
            if name:
                cookies.pop(name, None)

        cookie_store = profile.cookieStore()
        cookie_store.cookieAdded.connect(on_cookie_added)
        cookie_store.cookieRemoved.connect(on_cookie_removed)
        cookie_store.loadAllCookies()

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText(tr("Login done"))

        def accept_after_cookie_flush() -> None:
            cookie_store.loadAllCookies()
            QTimer.singleShot(500, dialog.accept)

        button_box.accepted.connect(accept_after_cookie_flush)
        button_box.rejected.connect(dialog.reject)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view)
        layout.addWidget(button_box)

        view.load(QUrl(f"{SONGSTERR_BASE_URL}/signin"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            shutil.rmtree(session_root, ignore_errors=True)
            return
        for popup in tuple(popup_windows):
            popup.close()

        if not cookies:
            shutil.rmtree(session_root, ignore_errors=True)
            QMessageBox.warning(self, tr("Songsterr login"), tr("Songsterr cookies were not found. Log in and click again."))
            return

        cookie_header = "; ".join(f"{name}={value}" for name, value in sorted(cookies.items()))
        try:
            save_cookie_header(cookie_header)
        except SongsterrError as exc:
            shutil.rmtree(session_root, ignore_errors=True)
            QMessageBox.warning(self, tr("Songsterr login"), str(exc))
            return

        shutil.rmtree(session_root, ignore_errors=True)
        self.statusBar().showMessage(tr("Songsterr login cookie saved"))
        QMessageBox.information(self, tr("Songsterr login"), tr("Songsterr login information was saved."))

    def _search_songsterr(self) -> None:
        default_query = self._default_songsterr_query()
        query, ok = QInputDialog.getText(
            self,
            tr("Search Songsterr tabs"),
            tr("Search query"),
            text=default_query,
        )
        if not ok:
            return
        query = " ".join(query.split())
        if not query:
            QMessageBox.information(self, "Songsterr", tr("Enter a search query."))
            return

        self.statusBar().showMessage(_trf("Searching Songsterr: {query}", query=query))
        self._start_songsterr_worker("search", query=query)

    def _default_songsterr_query(self) -> str:
        if self.song is not None:
            return " ".join(part for part in (self.song.artist, self.song.title) if part).strip()
        if self.current_file is not None:
            return self.current_file.stem.replace("-", " ")
        return ""

    def _choose_songsterr_result(self, results) -> object | None:
        if len(results) == 1:
            return results[0]
        labels = [result.display_label for result in results]
        label, ok = QInputDialog.getItem(
            self,
            tr("Songsterr search results"),
            tr("Select tab to open"),
            labels,
            0,
            False,
        )
        if not ok:
            return None
        try:
            return results[labels.index(label)]
        except ValueError:
            return None

    def _on_zoom_changed(self, value: int) -> None:
        self.zoom_label.setText(f"{value}%")
        if self.top_tabs.currentIndex() == self.tab_playback_tab_index:
            self.tab_playback_panel.set_zoom(value / 100)
        elif self.top_tabs.currentIndex() == self.analysis_tab_index:
            self.tab_canvas.set_zoom(value / 100)

    def _adjust_zoom_by_delta(self, delta: int) -> None:
        self.zoom_slider.setValue(max(65, min(240, self.zoom_slider.value() + delta)))

    def _set_toolbar_zoom_percent(self, value: int) -> None:
        value = max(65, min(240, int(value)))
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_label.setText(f"{value}%")
        self.zoom_slider.blockSignals(False)

    def _on_track_changed(self, _index: int | None = None) -> None:
        if self.current_file is None:
            return
        self._load_selected_track()

    def _on_tuning_changed(self, _index: int | None = None) -> None:
        if self.source_song is None:
            return
        self._apply_selected_tuning()
        self._update_theory_panel(None, None, "scale", None)
        self._update_song_panel()
        self._update_chord_position_panel(None, None)
        self.right_tabs.setCurrentIndex(0)
        if self.song is not None:
            self.statusBar().showMessage(
                _trf(
                    "Tuning: {tuning} - global scale {scale}",
                    tuning=self._current_tuning_name(),
                    scale=self.song.global_scale.name if self.song.global_scale else "-",
                )
            )

    def _on_top_tab_changed(self, index: int) -> None:
        if self.song is None or not self.song.track.measures:
            return

        if index == self.analysis_tab_index:
            self._stop_songsterr_tick_interpolation()
            self.tab_playback_panel.stop_playback()
            self._set_toolbar_zoom_percent(round(self.tab_canvas.zoom * 100))
            measure_index = self.tab_playback_panel.current_measure_index()
            self._preserving_playback_selection = True
            try:
                self.tab_canvas.set_selected_measure_index(measure_index, emit=True)
            finally:
                self._preserving_playback_selection = False
            QTimer.singleShot(0, lambda item=measure_index: self._scroll_analysis_measure_into_view(item))
            return

        if index == self.tab_playback_tab_index:
            self._songsterr_playback_measure_index = None
            self._stop_songsterr_tick_interpolation()
            self.fretboard.set_playback_tick(None)
            self._set_toolbar_zoom_percent(self.tab_playback_panel.zoom_percent())
            measure_index = self.tab_playback_panel.current_measure_index()
            QTimer.singleShot(0, lambda item=measure_index: self.tab_playback_panel.scroll_measure_into_view(item))
            return

        if index == self.songsterr_tab_index:
            self._songsterr_playback_measure_index = None
            self.tab_playback_panel.stop_playback()

    def _scroll_analysis_measure_into_view(self, measure_index: int) -> None:
        layout = self.tab_canvas.layout_for_measure(measure_index)
        if layout is None:
            return
        scroll_bar = self.analysis_scroll.verticalScrollBar()
        viewport_height = self.analysis_scroll.viewport().height()
        padding = int(24 * self.tab_canvas.zoom)
        target_top = max(0, layout.rect.top() - padding)
        target_bottom = layout.rect.bottom() + padding
        visible_top = scroll_bar.value()
        visible_bottom = visible_top + viewport_height
        if target_top < visible_top:
            scroll_bar.setValue(target_top)
        elif target_bottom > visible_bottom:
            scroll_bar.setValue(target_bottom - viewport_height)

    def _on_root_string_filter_changed(self, _index: int | None = None) -> None:
        string_number = self.root_string_combo.currentData()
        self.chord_positions_widget.set_root_string_filter(
            int(string_number) if string_number is not None else None
        )

    def _on_category_filter_changed(self, _index: int | None = None) -> None:
        category = self.category_combo.currentData()
        self.chord_positions_widget.set_category_filter(str(category) if category is not None else None)

    def _on_chord_finder_root_filter_changed(self, _index: int | None = None) -> None:
        root_pc = self.chord_finder_root_combo.currentData()
        self.chord_finder_widget.set_root_filter(int(root_pc) if root_pc is not None else None, clear_selection=True)

    def _on_chord_finder_type_filter_changed(self, _index: int | None = None) -> None:
        type_suffix = self.chord_finder_type_combo.currentData()
        self.chord_finder_widget.set_type_filter(str(type_suffix) if type_suffix is not None else None, clear_selection=True)

    def _apply_selected_tuning(self) -> None:
        if self.source_song is None:
            return

        preset = self._selected_tuning_preset()
        try:
            song = self.source_song if preset is None else retune_song(self.source_song, preset.midi_high_to_low)
        except ValueError as exc:
            QMessageBox.warning(self, tr("Tuning mismatch"), str(exc))
            self.tuning_combo.setCurrentIndex(0)
            song = self.source_song

        self._set_current_song(song)

    def _set_current_song(self, song: SongData | None) -> None:
        self.song = song
        self._songsterr_playback_measure_index = None
        self._stop_songsterr_tick_interpolation()
        self.tab_canvas.set_song(song)
        self.tab_playback_panel.set_song(song)
        self._update_songsterr_tab(song)
        self.fretboard.set_song(song)
        self.scale_position_widget.set_song(song)
        self.song_scale_usage_widget.set_song(song)
        self.chord_finder_widget.set_song(song)
        self._populate_root_string_combo(len(song.track.string_pitches) if song is not None else 6)

    def _update_songsterr_tab(self, song: SongData | None) -> None:
        details = load_details_file(song.path) if song is not None else {}
        url = songsterr_page_url(details)
        if not url:
            self._hide_songsterr_tab()
            return
        self.songsterr_panel.set_url(url)
        index = self.top_tabs.indexOf(self.songsterr_panel)
        if index < 0:
            index = self.top_tabs.addTab(self.songsterr_panel, "Songsterr")
        else:
            self.top_tabs.setTabText(index, "Songsterr")
        self.songsterr_tab_index = index

    def _hide_songsterr_tab(self) -> None:
        index = self.top_tabs.indexOf(self.songsterr_panel)
        if index >= 0:
            self.top_tabs.removeTab(index)
        self.songsterr_tab_index = -1
        self._songsterr_playback_measure_index = None
        self._stop_songsterr_tick_interpolation()
        self.songsterr_panel.set_url("")

    def _selected_tuning_preset(self) -> TuningPreset | None:
        preset_id = self.tuning_combo.currentData()
        if preset_id is None:
            return None
        for preset in self.tuning_presets:
            if preset.id == preset_id:
                return preset
        return None

    def _current_tuning_name(self) -> str:
        preset = self._selected_tuning_preset()
        if preset is not None:
            return preset.display_name
        if self.song is None:
            return tr("From file")
        return _trf("From file ({tuning})", tuning=" ".join(reversed(self.song.track.string_names)))

    def _populate_root_string_combo(self, string_count: int) -> None:
        current = self.root_string_combo.currentData()
        self.root_string_combo.blockSignals(True)
        self.root_string_combo.clear()
        self.root_string_combo.addItem(tr("All"), None)
        for string_number in range(string_count, 0, -1):
            self.root_string_combo.addItem(_trf("{number} string", number=string_number), string_number)
        index = self.root_string_combo.findData(current)
        self.root_string_combo.setCurrentIndex(index if index >= 0 else 0)
        self.root_string_combo.blockSignals(False)
        selected = self.root_string_combo.currentData()
        self.chord_positions_widget.set_root_string_filter(int(selected) if selected is not None else None)

    def _populate_category_combo(self) -> None:
        current = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem(tr("All"), None)
        for category in CHORD_POSITION_CATEGORIES:
            self.category_combo.addItem(tr(category), category)
        index = self.category_combo.findData(current)
        self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.blockSignals(False)
        selected = self.category_combo.currentData()
        self.chord_positions_widget.set_category_filter(str(selected) if selected is not None else None)

    def _populate_chord_finder_controls(self) -> None:
        current_root = self.chord_finder_root_combo.currentData()
        current_type = self.chord_finder_type_combo.currentData()

        self.chord_finder_root_combo.blockSignals(True)
        self.chord_finder_root_combo.clear()
        self.chord_finder_root_combo.addItem(tr("All"), None)
        for root_pc, label in SCALE_POSITION_ROOT_OPTIONS:
            self.chord_finder_root_combo.addItem(label, root_pc)
        root_index = self.chord_finder_root_combo.findData(current_root)
        self.chord_finder_root_combo.setCurrentIndex(root_index if root_index >= 0 else 0)
        self.chord_finder_root_combo.blockSignals(False)

        self.chord_finder_type_combo.blockSignals(True)
        self.chord_finder_type_combo.clear()
        self.chord_finder_type_combo.addItem(tr("All"), None)
        for chord_type in CHORD_FINDER_TYPES:
            self.chord_finder_type_combo.addItem(tr(chord_type.display_name), chord_type.suffix)
        type_index = self.chord_finder_type_combo.findData(current_type)
        self.chord_finder_type_combo.setCurrentIndex(type_index if type_index >= 0 else 0)
        self.chord_finder_type_combo.blockSignals(False)

        selected_root = self.chord_finder_root_combo.currentData()
        selected_type = self.chord_finder_type_combo.currentData()
        self.chord_finder_widget.set_root_filter(int(selected_root) if selected_root is not None else None)
        self.chord_finder_widget.set_type_filter(str(selected_type) if selected_type is not None else None)

    def _populate_scale_position_controls(self) -> None:
        current_root = self.scale_root_combo.currentData()
        current_scale = self.scale_type_combo.currentData()

        self.scale_root_combo.blockSignals(True)
        self.scale_root_combo.clear()
        for root_pc, label in SCALE_POSITION_ROOT_OPTIONS:
            self.scale_root_combo.addItem(label, root_pc)
        root_index = self.scale_root_combo.findData(current_root)
        self.scale_root_combo.setCurrentIndex(root_index if root_index >= 0 else 0)
        self.scale_root_combo.blockSignals(False)

        self.scale_type_combo.blockSignals(True)
        self.scale_type_combo.clear()
        for name, _intervals in SCALE_POSITION_PATTERNS:
            display_name = SCALE_POSITION_DISPLAY_NAMES.get(name, name)
            self.scale_type_combo.addItem(tr(display_name), name)
        scale_index = self.scale_type_combo.findData(current_scale)
        self.scale_type_combo.setCurrentIndex(scale_index if scale_index >= 0 else 0)
        self.scale_type_combo.blockSignals(False)

        self._sync_scale_position_widget()

    def _on_scale_position_filter_changed(self, _index: int | None = None) -> None:
        self._sync_scale_position_widget()

    def _on_song_scale_count_changed(self, value: int) -> None:
        self.song_scale_usage_widget.set_visible_count(value)

    def _sync_scale_position_widget(self) -> None:
        root_pc = self.scale_root_combo.currentData()
        scale_name = self.scale_type_combo.currentData()
        if root_pc is None or scale_name is None:
            return
        self.scale_position_widget.set_scale(int(root_pc), str(scale_name))

    def _on_selection_changed(
        self,
        measure: MeasureData,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None,
    ) -> None:
        index = self._measure_index(measure)
        if index is not None:
            if not self._preserving_playback_selection:
                self.tab_playback_panel.set_selected_measure_range(index, index, notify=False)
            self._set_current_memo_measure_index(index)
            if self.top_tabs.currentIndex() == self.tab_playback_tab_index:
                QTimer.singleShot(0, lambda item=index: self.tab_playback_panel.scroll_measure_into_view(item))
        self.fretboard.set_selection(measure, candidate, kind, segment)
        self._update_theory_panel(measure, candidate, kind, segment)
        if kind == "chord":
            self._update_chord_position_panel(measure, candidate)
            self.right_tabs.setCurrentIndex(1)
        if candidate is None:
            self.statusBar().showMessage(_trf("M{measure}: no notes", measure=measure.number))
            return
        segment_text = ""
        if segment is not None:
            start_percent = round((segment.start_in_measure / measure.length_ticks) * 100)
            end_percent = round((segment.end_in_measure / measure.length_ticks) * 100)
            segment_text = f" {start_percent}-{end_percent}%"
        self.statusBar().showMessage(
            _trf(
                "M{measure}{segment}: {kind} {candidate} ({score}/100)",
                measure=measure.number,
                segment=segment_text,
                kind=tr(kind.capitalize()) if kind in {"scale", "chord"} else kind,
                candidate=candidate.name,
                score=candidate.score,
            )
        )

    def _on_tab_block_selection_changed(self, start: int, end: int) -> None:
        if self.song is None or not self.song.track.measures:
            return
        measures = self.song.track.measures
        start = max(0, min(start, len(measures) - 1))
        end = max(0, min(end, len(measures) - 1))
        if end < start:
            start, end = end, start
        first_measure = measures[start]
        candidate = first_measure.analysis.scale_candidates[0] if first_measure.analysis.scale_candidates else None
        self.tab_canvas.set_selected_measure_index(start, emit=False)
        self._set_current_memo_measure_index(start)
        if self.top_tabs.currentIndex() == self.analysis_tab_index:
            QTimer.singleShot(0, lambda item=start: self._scroll_analysis_measure_into_view(item))
        self.fretboard.set_selection(first_measure, candidate, "scale", None)
        self.theory_browser.setHtml(self.theory_explainer.explain_tab_selection(self.song, start, end))
        fretboard_index = self.measure_tabs.indexOf(self.fretboard)
        if fretboard_index >= 0:
            self.measure_tabs.setCurrentIndex(fretboard_index)
        if start == end:
            self.statusBar().showMessage(_trf("M{measure}: tab block selected", measure=first_measure.number))
        else:
            self.statusBar().showMessage(_trf("M{start}-M{end}: tab block selected", start=first_measure.number, end=measures[end].number))

    def _on_tab_playback_measure_changed(self, measure_index: int) -> None:
        self._select_fretboard_scale_measure(measure_index)

    def _select_fretboard_scale_measure(self, measure_index: int) -> MeasureData | None:
        if self.song is None or not self.song.track.measures:
            return None
        measures = self.song.track.measures
        measure_index = max(0, min(measure_index, len(measures) - 1))
        measure = measures[measure_index]
        candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
        self.fretboard.set_selection(measure, candidate, "scale", None)
        return measure

    def _on_songsterr_playback_position_changed(self, state: object) -> None:
        if self.song is None or not self.song.track.measures:
            return
        if self.songsterr_tab_index < 0 or self.top_tabs.currentIndex() != self.songsterr_tab_index:
            return
        if not isinstance(state, dict):
            self._songsterr_playback_measure_index = None
            self._stop_songsterr_tick_interpolation()
            self.fretboard.set_playback_tick(None)
            return

        try:
            measure_index = int(state.get("measureIndex", 0))
            ratio = float(state.get("ratio", 0.0))
        except (TypeError, ValueError):
            return

        measures = self.song.track.measures
        if bool(state.get("shouldPlay")) and state.get("source") == "time":
            tick_from_time = self._songsterr_playback_tick_from_state(state)
            if tick_from_time is not None:
                measure_index = self._measure_index_for_playback_tick(tick_from_time)
                measure = measures[measure_index]
                if self._songsterr_playback_measure_index != measure_index or self.fretboard.measure is not measure:
                    self._songsterr_playback_measure_index = measure_index
                    self._select_fretboard_scale_measure(measure_index)
                self._set_songsterr_playback_tick(tick_from_time, state)
                return

        measure_index = max(0, min(measure_index, len(measures) - 1))
        measure = measures[measure_index]
        if self._songsterr_playback_measure_index != measure_index or self.fretboard.measure is not measure:
            self._songsterr_playback_measure_index = measure_index
            self._select_fretboard_scale_measure(measure_index)

        if not bool(state.get("shouldPlay")):
            self._stop_songsterr_tick_interpolation()
            self.fretboard.set_playback_tick(None)
            return

        ratio = max(0.0, min(0.999999, ratio))
        local_offset = int(round(ratio * measure.length_ticks))
        local_offset = max(0, min(local_offset, max(0, measure.length_ticks - 1)))
        self._set_songsterr_playback_tick(measure.start_tick + local_offset, state)

    def _set_songsterr_playback_tick(self, tick: int, state: dict) -> None:
        self.fretboard.set_playback_tick(tick)
        self._songsterr_playback_base_tick = tick
        self._songsterr_playback_speed_percent = self._songsterr_speed_percent_from_state(state)
        self._songsterr_playback_clock.restart()
        if not self._songsterr_playback_tick_timer.isActive():
            self._songsterr_playback_tick_timer.start()

    def _songsterr_speed_percent_from_state(self, state: dict) -> float:
        try:
            speed = float(state.get("speed", 100))
        except (TypeError, ValueError):
            return 100.0
        return max(15.0, min(200.0, speed))

    def _stop_songsterr_tick_interpolation(self) -> None:
        self._songsterr_playback_tick_timer.stop()
        self._songsterr_playback_base_tick = None
        self._songsterr_playback_speed_percent = 100.0

    def _advance_songsterr_playback_tick(self) -> None:
        if self.song is None or not self.song.track.measures:
            self._stop_songsterr_tick_interpolation()
            return
        if self.songsterr_tab_index < 0 or self.top_tabs.currentIndex() != self.songsterr_tab_index:
            self._stop_songsterr_tick_interpolation()
            return
        tick = self._songsterr_interpolated_playback_tick()
        if tick is None:
            return
        measure_index = self._measure_index_for_playback_tick(tick)
        measure = self.song.track.measures[measure_index]
        if self._songsterr_playback_measure_index != measure_index or self.fretboard.measure is not measure:
            self._songsterr_playback_measure_index = measure_index
            self._select_fretboard_scale_measure(measure_index)
        self.fretboard.set_playback_tick(tick)

    def _songsterr_interpolated_playback_tick(self, elapsed_ms: int | None = None) -> int | None:
        if self.song is None or self._songsterr_playback_base_tick is None or not self.song.track.measures:
            return None
        if elapsed_ms is None:
            elapsed_ms = self._songsterr_playback_clock.elapsed()
        ticks_per_ms = (
            self.song.tempo
            * (self._songsterr_playback_speed_percent / 100.0)
            * TICKS_PER_QUARTER
            / 60000.0
        )
        tick = int(round(self._songsterr_playback_base_tick + max(0, elapsed_ms) * ticks_per_ms))
        measures = self.song.track.measures
        first_tick = measures[0].start_tick
        last_tick = measures[-1].start_tick + max(1, measures[-1].length_ticks) - 1
        return max(first_tick, min(tick, last_tick))

    def _songsterr_playback_tick_from_state(self, state: dict) -> int | None:
        if self.song is None or not self.song.track.measures:
            return None
        cursor_ms = state.get("cursorMs")
        if cursor_ms is None:
            return None
        try:
            milliseconds = float(cursor_ms)
        except (TypeError, ValueError):
            return None
        if milliseconds < 0:
            return None
        tick = int(round(milliseconds * self.song.tempo * TICKS_PER_QUARTER / 60000.0))
        measures = self.song.track.measures
        first_tick = measures[0].start_tick
        last_tick = measures[-1].start_tick + max(1, measures[-1].length_ticks) - 1
        return max(first_tick, min(tick, last_tick))

    def _measure_index_for_playback_tick(self, tick: int) -> int:
        if self.song is None or not self.song.track.measures:
            return 0
        measures = self.song.track.measures
        for index, measure in enumerate(measures):
            start_tick = measure.start_tick
            end_tick = measure.start_tick + measure.length_ticks
            if start_tick <= tick < end_tick:
                return index
        return len(measures) - 1 if tick >= measures[-1].start_tick else 0

    def _measure_index(self, measure: MeasureData) -> int | None:
        if self.song is None:
            return None
        for index, item in enumerate(self.song.track.measures):
            if item is measure or item.number == measure.number:
                return index
        return None

    def _update_theory_panel(
        self,
        measure: MeasureData | None,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None,
    ) -> None:
        self.theory_browser.setHtml(
            self.theory_explainer.explain_selection(self.song, measure, candidate, kind, segment)
        )

    def _update_song_panel(self) -> None:
        self.song_browser.setHtml(self.theory_explainer.explain_song(self.song))

    def _update_chord_position_panel(
        self,
        measure: MeasureData | None,
        candidate: Candidate | None,
    ) -> None:
        chord = candidate if candidate is not None and candidate.kind == "chord" else None
        self.chord_positions_widget.set_selection(self.song, measure, chord)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._load_thread is not None and self._load_thread.isRunning():
            QMessageBox.information(self, tr("Analyzing"), tr("Close the window after tab file analysis finishes."))
            event.ignore()
            return
        if self._songsterr_thread is not None and self._songsterr_thread.isRunning():
            QMessageBox.information(self, tr("Processing Songsterr"), tr("Close the window after the Songsterr task finishes."))
            event.ignore()
            return
        if not self._maybe_save_memo_changes():
            event.ignore()
            return
        if self.tuner_dialog is not None:
            self.tuner_dialog.close()
        self.chord_finder_widget.shutdown()
        self._stop_songsterr_tick_interpolation()
        self.tab_playback_panel.shutdown()
        self.songsterr_panel.shutdown()
        self._clear_memo_asset_dir()
        super().closeEvent(event)


def run_app(initial_file: str | Path | None = None) -> int:
    _allow_qt_webengine_autoplay()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv if sys.argv else ["TabAnalyzer"])
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = TabAnalyzerWindow(initial_file=initial_file)
    window.show()
    return app.exec()
