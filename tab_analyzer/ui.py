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
from datetime import datetime
from fractions import Fraction
from math import pi, sin
from pathlib import Path, PurePosixPath
from typing import NamedTuple
from urllib.parse import unquote

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSize, QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut
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
    QScrollArea,
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

from .analysis import (
    Candidate,
    SCALE_PATTERNS,
    candidate_display_label,
    candidate_display_name,
    interval_name,
    pitch_class_name,
)
from .chord_positions import (
    CHORD_POSITION_CATEGORIES,
    ChordPosition,
    MAX_CHORD_POSITIONS,
    MAX_FRET_SPAN,
    MUTED,
    chord_position_display_name,
    filter_chord_positions,
    generate_chord_positions,
    group_chord_positions_by_category,
)
from .gp_loader import MeasureData, SegmentData, SongData, default_track_index, list_tracks, load_gp_file, retune_song
from .midi_player import MidiOutput, TabMidiPlayer
from .scale_blocks import (
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
from .songsterr import (
    SONGSTERR_BASE_URL,
    SongsterrAuthError,
    SongsterrError,
    download_guitar_pro,
    load_cookie_header,
    save_cookie_header,
    search_tabs,
)
from .theory import TheoryExplainer
from .tunings import TuningPreset, load_tuning_presets
from .version import __version__


PROJECT_ROOT_PATH = Path(__file__).resolve().parent.parent
SONGSTERR_DOWNLOAD_DIR = PROJECT_ROOT_PATH / "Downloads"

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
    "major pentatonic",
    "minor pentatonic",
    "blues",
    "major blues",
    "dorian",
    "mixolydian",
    "phrygian",
    "lydian",
    "locrian",
    "harmonic minor",
    "melodic minor",
    "phrygian dominant",
    "lydian dominant",
    "altered",
    "diminished half-whole",
    "diminished whole-half",
    "whole tone",
    "bebop dominant",
    "major bebop",
    "harmonic major",
    "double harmonic",
    "hungarian minor",
    "gypsy",
    "dorian b2",
    "locrian #2",
    "lydian augmented",
    "mixolydian b6",
    "locrian natural 6",
    "dorian #4",
    "lydian #2",
    "altered diminished",
    "ionian augmented",
    "dorian b5",
    "phrygian b4",
    "lydian diminished",
    "mixolydian b2",
    "augmented",
    "suspended pentatonic",
    "yo pentatonic",
    "hirajoshi",
    "in",
    "insen",
    "iwato",
    "neapolitan major",
    "neapolitan minor",
    "persian",
    "enigmatic",
    "ukrainian dorian",
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
APP_ICON_ICO_PATH = PROJECT_ROOT_PATH / "assets" / "app_icon.ico"
MANUAL_PATH = PROJECT_ROOT_PATH / "docs" / "manual.html"
MEMO_MARKER = "<!-- TAB_ANALYZER_MEMO_V1 -->"
MMDX_MARKER = "TAB_ANALYZER_MMDX_V1"
MMDX_MANIFEST_NAME = "manifest.json"
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)\n]+)\)")
HTML_IMAGE_PATTERN = re.compile(r"(<img\b[^>]*\bsrc=[\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)
SAFE_ASSET_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def _measure_note_text(text: str | None) -> str:
    return (text or "").strip()


def _memo_path_for_tab(path: Path) -> Path:
    return path.with_name(f"memo_{path.name}.mmdx")


def _legacy_memo_path_for_tab(path: Path) -> Path:
    return path.with_name(f"memo_{path.name}.md")


def _memo_autosave_path(path: Path) -> Path:
    return path.with_name(f".memo_{path.name}.autosave.mmdx")


def _serialize_legacy_memos(source_path: Path | None, memos: dict[int, str]) -> str:
    source = source_path.name if source_path is not None else ""
    lines = [
        "# Tab Analyzer Memo",
        "",
        MEMO_MARKER,
        f"source: {source}",
        f"saved_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for number in sorted(memos):
        text = _measure_note_text(memos[number])
        if not text:
            continue
        lines.extend([f"## M{number}", "", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_memos(markdown: str) -> dict[int, str]:
    memos: dict[int, str] = {}
    current: int | None = None
    buffer: list[str] = []
    heading = re.compile(r"^##\s+M(\d+)\b")

    def flush() -> None:
        if current is None:
            return
        text = "\n".join(buffer).strip()
        if text:
            memos[current] = text

    for line in markdown.splitlines():
        match = heading.match(line.strip())
        if match:
            flush()
            current = int(match.group(1))
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    flush()
    return memos


def _write_memo_package(path: Path, source_path: Path | None, memos: dict[int, str], base_dirs: tuple[Path, ...] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Path] = {}
    manifest = {
        "format": MMDX_MARKER,
        "source": source_path.name if source_path is not None else "",
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MMDX_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for number in sorted(memos):
            text = _measure_note_text(memos[number])
            if not text:
                continue
            rewritten = _rewrite_memo_image_references(text, number, base_dirs, assets)
            archive.writestr(f"M{number}.md", rewritten.rstrip() + "\n")
        for archive_name, source in sorted(assets.items()):
            archive.write(source, archive_name)


def _read_memo_package(path: Path, extract_dir: Path | None = None) -> dict[int, str]:
    if path.suffix.lower() != ".mmdx":
        return _parse_memos(path.read_text(encoding="utf-8"))

    memos: dict[int, str] = {}
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir() or not _safe_zip_member(info.filename):
                continue
            member_path = PurePosixPath(info.filename.replace("\\", "/"))
            match = re.fullmatch(r"M(\d+)\.md", member_path.name)
            if match and len(member_path.parts) == 1:
                memos[int(match.group(1))] = archive.read(info).decode("utf-8").strip()
            if extract_dir is not None:
                target = extract_dir.joinpath(*member_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
    return {number: text for number, text in memos.items() if _measure_note_text(text)}


def _safe_zip_member(name: str) -> bool:
    member_path = PurePosixPath(name.replace("\\", "/"))
    return not member_path.is_absolute() and ".." not in member_path.parts


def _rewrite_memo_image_references(text: str, measure_number: int, base_dirs: tuple[Path, ...], assets: dict[str, Path]) -> str:
    def markdown_replacer(match: re.Match[str]) -> str:
        raw_target = match.group(1)
        target = _image_target_from_markdown(raw_target)
        replacement = _memo_asset_reference(target, measure_number, base_dirs, assets)
        if replacement == target:
            return match.group(0)
        return match.group(0).replace(target, replacement, 1)

    def html_replacer(match: re.Match[str]) -> str:
        target = match.group(2)
        replacement = _memo_asset_reference(target, measure_number, base_dirs, assets)
        return f"{match.group(1)}{replacement}{match.group(3)}"

    text = MARKDOWN_IMAGE_PATTERN.sub(markdown_replacer, text)
    return HTML_IMAGE_PATTERN.sub(html_replacer, text)


def _image_target_from_markdown(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.strip("\"'")


def _memo_asset_reference(target: str, measure_number: int, base_dirs: tuple[Path, ...], assets: dict[str, Path]) -> str:
    source = _resolve_memo_asset(target, base_dirs)
    if source is None:
        return target
    archive_name = _unique_memo_asset_name(measure_number, source, assets)
    assets[archive_name] = source
    return archive_name


def _resolve_memo_asset(target: str, base_dirs: tuple[Path, ...]) -> Path | None:
    if _is_external_asset_reference(target):
        return None
    cleaned = unquote(target).strip().strip("\"'")
    if not cleaned:
        return None
    candidate = Path(cleaned)
    candidates = [candidate] if candidate.is_absolute() else [base / cleaned for base in base_dirs if base is not None]
    for item in candidates:
        try:
            resolved = item.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _is_external_asset_reference(target: str) -> bool:
    value = target.strip().lower()
    if not value or value.startswith("#"):
        return True
    if re.match(r"^[a-z]:[\\/]", value):
        return False
    return re.match(r"^[a-z][a-z0-9+.-]*:", value) is not None


def _unique_memo_asset_name(measure_number: int, source: Path, assets: dict[str, Path]) -> str:
    safe_name = SAFE_ASSET_PATTERN.sub("_", source.name).strip("._") or "image"
    stem = Path(safe_name).stem or "image"
    suffix = Path(safe_name).suffix
    candidate = f"M{measure_number}_{stem}{suffix}"
    counter = 2
    while candidate in assets and assets[candidate] != source:
        candidate = f"M{measure_number}_{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _render_markdown_preview(markdown_text: str) -> str | None:
    try:
        from markdown_editor.editor import MarkdownDocument
    except Exception:  # noqa: BLE001 - Markdown-Editor is optional at runtime until requirements are installed.
        return None
    try:
        document = MarkdownDocument()
        document.text = markdown_text
        return str(document.getHtml())
    except Exception:  # noqa: BLE001 - fallback to Qt's built-in Markdown renderer.
        return None


def _icon_button(icon: QIcon, tooltip: str, size: int = 30) -> QPushButton:
    button = QPushButton()
    button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setFixedSize(size, size)
    button.setIconSize(QSize(size - 10, size - 10))
    return button


def _player_icon(kind: str, color: str = "#111827") -> QIcon:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if kind == "play":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(12, 8),
                    QPointF(12, 24),
                    QPointF(24, 16),
                ]
            )
        )
    elif kind == "stop":
        painter.drawRect(QRect(10, 10, 12, 12))
    elif kind == "record":
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(QPointF(16, 16), 7, 7)
    elif kind == "metronome":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), 2))
        painter.drawLine(10, 25, 16, 7)
        painter.drawLine(22, 25, 16, 7)
        painter.drawLine(10, 25, 22, 25)
        painter.drawLine(16, 10, 20, 22)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(20, 22), 2.5, 2.5)
    elif kind == "speaker":
        painter.drawRect(QRect(7, 13, 5, 7))
        painter.drawPolygon(QPolygonF([QPointF(12, 13), QPointF(19, 8), QPointF(19, 25), QPointF(12, 20)]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), 2))
        painter.drawArc(QRect(18, 11, 8, 10), -45 * 16, 90 * 16)
    painter.end()
    return QIcon(pixmap)


def _delete_recording_icon() -> QIcon:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#4b5563"), 2))
    painter.setBrush(QColor("#f3f4f6"))
    eraser = QPolygonF(
        [
            QPointF(8, 21),
            QPointF(18, 11),
            QPointF(25, 18),
            QPointF(15, 28),
        ]
    )
    painter.drawPolygon(eraser)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRect(QRect(12, 23, 12, 4))
    painter.setPen(QPen(QColor("#dc2626"), 2))
    painter.drawLine(21, 6, 28, 13)
    painter.drawLine(28, 6, 21, 13)
    painter.end()
    return QIcon(pixmap)


def _post_it_icon_rect(origin_x: int, origin_y: int, size: int) -> QRect:
    return QRect(origin_x, origin_y, size, size)


def _draw_post_it_icon(painter: QPainter, rect: QRect, has_memo: bool) -> None:
    fill = QColor("#ef4444") if has_memo else QColor("#ffffff")
    border = QColor("#991b1b") if has_memo else QColor("#c7ccd6")
    fold = QColor("#fecaca") if has_memo else QColor("#eef2f7")
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(border, 1.1))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 2, 2)
    path = QPainterPath()
    path.moveTo(rect.right() - rect.width() * 0.36, rect.top())
    path.lineTo(rect.right(), rect.top())
    path.lineTo(rect.right(), rect.top() + rect.height() * 0.36)
    path.closeSubpath()
    painter.setBrush(fold)
    painter.drawPath(path)
    painter.restore()


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
        window_title: str = "분석 중",
        title_prefix: str = "분석 중",
        initial_detail: str = "파일을 준비하는 중입니다.",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setModal(True)
        self.setFixedSize(340, 132)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._title_prefix = title_prefix
        self.title_label = QLabel(f"{self._title_prefix}... 0%")
        self.detail_label = QLabel(initial_detail)
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
            self.detail_label.setText(detail)
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
                self.progress.emit(10, "파일 정보를 읽는 중입니다.")
                tracks = list_tracks(self.path)
                self.progress.emit(30, "기타 트랙을 찾는 중입니다.")
                selected_track = default_track_index(self.path)
                self.progress.emit(40, "타브와 음표를 분석하는 중입니다.")
                song = load_gp_file(self.path, track_index=selected_track)
                self.progress.emit(90, "분석 결과를 정리하는 중입니다.")
                self.finished.emit(("file", self.path, tracks, selected_track, song))
                return

            track_index = int(self.track_index or 0)
            self.progress.emit(10, "선택한 트랙을 준비하는 중입니다.")
            self.progress.emit(30, "타브와 음표를 분석하는 중입니다.")
            song = load_gp_file(self.path, track_index=track_index)
            self.progress.emit(90, "분석 결과를 정리하는 중입니다.")
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
                self.progress.emit(15, "Songsterr에서 곡을 검색하는 중입니다.")
                results = search_tabs(self.query)
                self.progress.emit(90, "검색 결과를 정리하는 중입니다.")
                self.finished.emit(("search", self.query, results))
                return

            if self.result is None:
                raise SongsterrError("다운로드할 Songsterr 곡이 선택되지 않았습니다.")
            self.progress.emit(15, "Songsterr에서 Guitar Pro 파일을 요청하는 중입니다.")
            path = download_guitar_pro(
                self.result,
                SONGSTERR_DOWNLOAD_DIR,
                cookie=self.cookie,
            )
            self.progress.emit(90, "다운로드 파일을 준비하는 중입니다.")
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
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a Guitar Pro file")

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
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#ffffff"))
                painter.drawRoundedRect(text_rect, 3, 3)
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
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open a Guitar Pro file")

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

        self._draw_note_relationships(painter, note_positions)

        seen_beats: set[int] = set()
        for x, _y, _note, beat in note_positions:
            beat_key = id(beat)
            if beat_key in seen_beats:
                continue
            seen_beats.add(beat_key)
            self._draw_beat_technique_symbols(painter, beat, x, rect.top(), tab_top)

        painter.setFont(note_font)
        for x, y, note, _beat in note_positions:
            text = tab_note_text(note)
            width = note_metrics.horizontalAdvance(text) + 8
            text_rect = QRect(x - width // 2, y - note_metrics.height() // 2, width, note_metrics.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#ffffff"))
            painter.drawRoundedRect(text_rect, 3, 3)
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
        positions: list[tuple[int, int, object, BeatData]] = []
        note_pad = max(10, int(14 * self.zoom))
        effective_width = max(1, tab_width - (note_pad * 2))
        for beat in measure.beats:
            if not beat.notes:
                continue
            ratio = min(1.0, max(0.0, beat.start_in_measure / measure.length_ticks))
            x = tab_left + note_pad + int(ratio * effective_width)
            for note in beat.notes:
                y = tab_top + ((note.string - 1) * string_gap)
                positions.append((x, y, note, beat))
        return positions

    def _draw_note_relationships(self, painter: QPainter, positions: list[tuple[int, int, object, BeatData]]) -> None:
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
                    self._draw_slide_connection(painter, left_x, left_y, right_x, right_y, left_note.fret, right_note.fret)
                if "tie" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "hammer_on" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "pull_off" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
            if ordered:
                last_x, last_y, last_note, _last_beat = ordered[-1]
                if "slide" in set(last_note.techniques):
                    self._draw_slide_out(painter, last_x, last_y)
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
        start_x = left_x + int(6 * self.zoom)
        end_x = right_x - int(6 * self.zoom)
        if end_x <= start_x:
            return
        base_y = min(left_y, right_y) - int(8 * self.zoom)
        height = max(int(5 * self.zoom), min(int(12 * self.zoom), (end_x - start_x) // 5))
        path = QPainterPath(QPointF(start_x, base_y))
        path.quadTo(QPointF((start_x + end_x) / 2, base_y - height), QPointF(end_x, base_y))
        pen = painter.pen()
        pen.setWidth(max(1, int(1.6 * self.zoom)))
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
        start_x = left_x + int(9 * self.zoom)
        end_x = right_x - int(9 * self.zoom)
        if end_x <= start_x:
            return
        offset = int(5 * self.zoom)
        if right_fret >= left_fret:
            painter.drawLine(start_x, left_y + offset, end_x, right_y - offset)
        else:
            painter.drawLine(start_x, left_y - offset, end_x, right_y + offset)

    def _draw_slide_out(self, painter: QPainter, x: int, y: int) -> None:
        painter.drawLine(x + int(9 * self.zoom), y + int(5 * self.zoom), x + int(24 * self.zoom), y - int(8 * self.zoom))

    def _draw_beat_technique_symbols(
        self,
        painter: QPainter,
        beat: BeatData,
        x: int,
        row_top: int,
        tab_top: int,
    ) -> None:
        techniques = self._beat_techniques(beat)
        if not techniques:
            return

        symbol_y = max(row_top + int(18 * self.zoom), tab_top - int(28 * self.zoom))
        slot = max(15, int(17 * self.zoom))
        limited = techniques[:5]
        start_x = x - ((len(limited) - 1) * slot) // 2
        for index, technique in enumerate(limited):
            bend_semitones = self._beat_bend_semitones(beat) if technique in {"bend", "release_bend"} else None
            self._draw_technique_symbol(painter, technique, start_x + (index * slot), symbol_y, bend_semitones)

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

    def _draw_technique_symbol(
        self,
        painter: QPainter,
        technique: str,
        x: int,
        y: int,
        bend_semitones: float | None = None,
    ) -> None:
        painter.save()
        color = QColor("#2f3746")
        accent = QColor("#805a13")
        pen_width = max(1, int(1.35 * self.zoom))
        painter.setPen(QPen(color, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if technique == "bend":
            self._draw_bend_symbol(painter, x, y, release=False, semitones=bend_semitones)
        elif technique == "release_bend":
            self._draw_bend_symbol(painter, x, y, release=True, semitones=bend_semitones)
        elif technique == "vibrato":
            self._draw_wavy_symbol(painter, x - int(8 * self.zoom), y, int(17 * self.zoom), int(4 * self.zoom))
        elif technique == "staccato":
            radius = max(2, int(2.2 * self.zoom))
            painter.setBrush(color)
            painter.drawEllipse(QPointF(x, y), radius, radius)
        elif technique == "accent":
            span = int(7 * self.zoom)
            painter.drawLine(x - span, y - span // 2, x + span, y)
            painter.drawLine(x - span, y + span // 2, x + span, y)
        elif technique == "harmonic":
            self._draw_text_symbol(painter, "N.H.", x, y)
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
        scale = self.zoom
        pen = QPen(painter.pen().color(), max(1, int(1.3 * scale)))
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        start = QPointF(x - int(11 * scale), y + int(8 * scale))
        peak = QPointF(x + int(5 * scale), y - int(15 * scale))
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(x - int(1 * scale), y + int(8 * scale)),
            QPointF(x + int(5 * scale), y - int(2 * scale)),
            peak,
        )
        painter.drawPath(path)
        self._draw_bend_arrow_triangle(painter, peak, up=True)

        if release:
            end = QPointF(x + int(21 * scale), y + int(5 * scale))
            release_path = QPainterPath(peak)
            release_path.cubicTo(
                QPointF(x + int(14 * scale), y - int(15 * scale)),
                QPointF(x + int(21 * scale), y - int(8 * scale)),
                end,
            )
            painter.drawPath(release_path)
            self._draw_bend_arrow_triangle(painter, end, up=False)

        label = self._bend_amount_label(semitones)
        if label:
            font = QFont("Segoe UI", max(5, int(6 * scale)), QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            label_x = int(peak.x()) - metrics.horizontalAdvance(label) // 2
            label_y = int(peak.y()) - metrics.height() - int(3 * scale)
            painter.drawText(
                QRect(label_x, label_y, metrics.horizontalAdvance(label) + 2, metrics.height()),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _draw_bend_arrow_triangle(self, painter: QPainter, tip: QPointF, up: bool) -> None:
        size = max(4, int(4.5 * self.zoom))
        half = max(3, int(4 * self.zoom))
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
        steps = 4
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
        span = int(8 * self.zoom)
        offset = int(4 * self.zoom)
        for index in range(3):
            yy = y - offset + (index * offset)
            painter.drawLine(x - span // 2, yy + offset // 2, x + span // 2, yy - offset // 2)

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
        line_y = y + int(6 * self.zoom)
        painter.drawLine(rect.right() + int(3 * self.zoom), line_y, rect.right() + int(28 * self.zoom), line_y)

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
        self.bpm = max(40, min(250, int(bpm)))
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
            try:
                self.recorder.recorderStateChanged.connect(lambda state: self._on_recorder_state_changed(state))
            except TypeError:
                pass
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
            self.statusChanged.emit("녹음 기능 없음")
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
            self.statusChanged.emit(f"녹음 중: {self.last_recording.name}")
        except Exception as exc:  # noqa: BLE001 - multimedia backend errors should be visible.
            self.statusChanged.emit(f"녹음 실패: {exc}")

    def stop_recording(self) -> None:
        if not self.available or self.recorder is None or not self.recording:
            return
        self.recorder.stop()
        self.recording = False
        self.recordingChanged.emit(False)
        if self.last_recording is not None:
            self.statusChanged.emit(f"녹음 저장: {self.last_recording.name}")
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
            self.statusChanged.emit("재생할 녹음 없음")
            return
        if not path.exists():
            self.statusChanged.emit(f"녹음 파일 없음: {path.name}")
            return
        self.last_recording = path
        self.playback_file = path
        source = QUrl.fromLocalFile(str(path))
        if self.player.source() != source:
            self.player.setSource(source)
        self.player.setPosition(max(0, int(start_position)))
        self.player.play()
        self.statusChanged.emit(f"녹음 재생: {path.name}")

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
                self.statusChanged.emit(f"녹음 저장: {self.last_recording.name}")
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
        self.title_label.setText(f"M{measure_number} 메모" if measure_number is not None else "M-")
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
        self.delete_button.setToolTip("녹음 파일 삭제")
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

        self.player = TabMidiPlayer()
        self.practice_metronome = StandaloneMetronome()
        self.recorder = RecordingController()
        self.score = TabScoreWidget()
        self.score_scroll = QScrollArea()
        self.recording_tab = QWidget()
        self.play_button = _icon_button(_player_icon("play"), "재생")
        self.stop_button = _icon_button(_player_icon("stop"), "정지")
        self.repeat_check = QCheckBox("선택 반복")
        self.metronome_check = QCheckBox("메트로놈")
        self.repeat_start_spin = QSpinBox()
        self.repeat_end_spin = QSpinBox()
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_label = QLabel("100%")
        self.record_metronome_check = QCheckBox("녹음 클릭")
        self.metronome_button = _icon_button(_player_icon("metronome"), "메트로놈 F9")
        self.record_button = _icon_button(_player_icon("record"), "녹음 F10")
        self.record_stop_button = _icon_button(_player_icon("stop"), "녹음 종료 F11")
        self.record_play_button = _icon_button(_player_icon("play"), "녹음 재생 F12")
        self.record_playback_slider = QSlider(Qt.Orientation.Horizontal)
        self.recording_list = QListWidget()
        self.delete_all_recordings_button = QPushButton("모든 녹음 삭제하기")
        self.record_input_combo = QComboBox()
        self.record_bpm_spin = QSpinBox()
        self.record_beats_spin = QSpinBox()
        self.shortcut_label = QLabel("F9 메트로놈 · F10 녹음 · F11 종료 · F12 재생")
        self.record_status_label = QLabel()
        self.midi_status_label = QLabel()
        self._syncing_record_slider = False

        self._build_ui()
        self.score.selectionChanged.connect(self._on_score_selection_changed)
        self.score.zoomWheelRequested.connect(self.zoomWheelRequested.emit)
        self.play_button.clicked.connect(self._play)
        self.stop_button.clicked.connect(self._stop)
        self.repeat_check.toggled.connect(self._on_repeat_toggled)
        self.metronome_check.toggled.connect(self._on_tab_metronome_changed)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.repeat_start_spin.valueChanged.connect(self._on_repeat_range_changed)
        self.repeat_end_spin.valueChanged.connect(self._on_repeat_range_changed)
        self.player.positionChanged.connect(self._on_playback_position_changed)
        self.player.playingChanged.connect(self._on_playing_changed)
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
        self._install_recording_shortcuts()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.repeat_check)
        controls.addWidget(QLabel("시작"))
        self.repeat_start_spin.setRange(1, 1)
        self.repeat_start_spin.setKeyboardTracking(False)
        controls.addWidget(self.repeat_start_spin)
        controls.addWidget(QLabel("끝"))
        self.repeat_end_spin.setRange(1, 1)
        self.repeat_end_spin.setKeyboardTracking(False)
        controls.addWidget(self.repeat_end_spin)
        controls.addWidget(self.metronome_check)
        controls.addSpacing(8)
        controls.addWidget(QLabel("속도"))
        self.speed_slider.setRange(50, 200)
        self.speed_slider.setValue(100)
        self.speed_slider.setFixedWidth(130)
        controls.addWidget(self.speed_slider)
        controls.addWidget(self.speed_label)
        controls.addStretch(1)
        self.midi_status_label.setText("MIDI OK" if self.player.is_midi_available else "MIDI 출력 없음")
        self.midi_status_label.setStyleSheet("color: #596579;")
        controls.addWidget(self.midi_status_label)
        layout.addLayout(controls)
        self._build_recording_tab()

        self.score_scroll.setWidgetResizable(True)
        self.score_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.score_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.score_scroll.setWidget(self.score)
        layout.addWidget(self.score_scroll, 1)

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
        options.addWidget(QLabel("입력"))
        self.record_input_combo.setMinimumWidth(180)
        options.addWidget(self.record_input_combo, 1)
        options.addWidget(QLabel("BPM"))
        self.record_bpm_spin.setRange(40, 250)
        self.record_bpm_spin.setValue(120)
        self.record_bpm_spin.setFixedWidth(88)
        options.addWidget(self.record_bpm_spin)
        options.addWidget(QLabel("박자"))
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

    def set_song(self, song: SongData | None) -> None:
        self._stop()
        self.song = song
        self.score.set_song(song)
        count = len(song.track.measures) if song is not None else 1
        self.repeat_start_spin.setRange(1, max(1, count))
        self.repeat_end_spin.setRange(1, max(1, count))
        self.set_selected_measure_range(0, 0, notify=False)
        self.midi_status_label.setText(
            f"MIDI OK · {song.tempo} BPM" if song is not None and self.player.is_midi_available else "MIDI 출력 없음"
        )
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
        self.practice_metronome.close()
        self.recorder.close()

    def _refresh_audio_inputs(self) -> None:
        self.record_input_combo.clear()
        if not self.recorder.available:
            self.record_input_combo.addItem("녹음 기능 없음", None)
            self.record_input_combo.setEnabled(False)
            self.record_status_label.setText("QtMultimedia 없음")
            return
        devices = self.recorder.audio_inputs()
        if not devices:
            self.record_input_combo.addItem("입력 장치 없음", None)
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

    def _toggle_practice_metronome(self) -> None:
        self._on_record_metronome_changed()
        self.practice_metronome.toggle()

    def _on_record_metronome_changed(self) -> None:
        self.practice_metronome.set_bpm(self.record_bpm_spin.value())
        self.practice_metronome.set_beats_per_bar(self.record_beats_spin.value())

    def _start_recording(self) -> None:
        device = self.record_input_combo.currentData()
        if device is None:
            self.record_status_label.setText("입력 장치 없음")
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
            self.record_status_label.setText(f"녹음 저장+클릭: {self.recorder.last_recording.name}")
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
            self.record_status_label.setText(f"녹음 삭제: {target.name}")
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
            "모든 녹음 삭제",
            f"녹음 파일 {len(files)}개를 모두 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        deleted = sum(1 for path in files if self._delete_recording_file(path))
        self.record_status_label.setText(f"녹음 {deleted}개 삭제")
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
            QMessageBox.warning(self, "녹음 삭제 실패", f"{path.name}\n\n{exc}")
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
        self.record_play_button.setToolTip("녹음 재생 F12")

    def _on_recording_saved(self, path: object) -> None:
        if isinstance(path, Path):
            self.recorder.last_recording = path
        self._refresh_recording_files()

    def _on_recording_playback_changed(self, playing: bool) -> None:
        self.record_play_button.setIcon(_player_icon("play", "#2563eb" if playing else "#111827"))
        self.record_play_button.setToolTip("녹음 재생 중단 F12" if playing else "녹음 재생 F12")

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

    def _on_practice_metronome_changed(self, ticking: bool) -> None:
        self.metronome_button.setStyleSheet("background: #fee2e2;" if ticking else "")

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

    def _on_score_selection_changed(self, start: int, end: int) -> None:
        was_playing = self.player.playing
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
        if self.player.playing:
            self._set_repeat_checked(True)
            self._restart_playback_for_repeat_mode(True)

    def _on_repeat_toggled(self, enabled: bool) -> None:
        if self._syncing_repeat_toggle or self.song is None:
            return
        if self.player.playing:
            self._restart_playback_for_repeat_mode(enabled)

    def _play(self) -> None:
        if self.player.playing:
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
        if not self.player.is_midi_available and not self._midi_warning_shown:
            QMessageBox.warning(
                self,
                "MIDI output unavailable",
                f"MIDI 장치를 열 수 없어 커서만 이동합니다.\n\n{self.player.midi_error}",
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
        tick = int(self.player.current_tick)
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
        self.score.set_playback_tick(None)

    def _on_speed_changed(self, value: int) -> None:
        self.speed_label.setText(f"{value}%")
        self.player.set_speed_percent(value)

    def _on_playback_position_changed(self, tick: int) -> None:
        self.score.set_playback_tick(tick)
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
        if target_top < visible_top:
            scroll_bar.setValue(target_top)
        elif target_bottom > visible_bottom:
            scroll_bar.setValue(target_bottom - viewport_height)

    def _on_playing_changed(self, playing: bool) -> None:
        self.play_button.setIcon(_player_icon("play", "#2563eb" if playing else "#111827"))
        self.play_button.setToolTip("정지" if playing else "재생")
        self.play_button.setStyleSheet("background: #dbeafe;" if playing else "")


class FretboardWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.measure: MeasureData | None = None
        self.segment: SegmentData | None = None
        self.candidate: Candidate | None = None
        self.kind = "scale"
        self.selected_scale_block_index: int | None = None
        self._scale_block_button_hits: list[tuple[QRect, int]] = []
        self.setFixedHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.measure = None
        self.segment = None
        self.candidate = None
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Fretboard")
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
        return min(blocks, key=lambda block: (block.start_fret, block.first_order, block.index)).index

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

        label = "스케일보기"
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
            return f"{self.song.title} - {self.song.track.name}" if self.song else "Fretboard"
        measure_text = f"M{self.measure.number}" if self.measure else ""
        if self.measure is not None and self.segment is not None:
            start_percent = round((self.segment.start_in_measure / self.measure.length_ticks) * 100)
            end_percent = round((self.segment.end_in_measure / self.measure.length_ticks) * 100)
            measure_text = f"{measure_text} {start_percent}-{end_percent}%"
        kind_text = "Scale" if self.kind == "scale" else "Chord"
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
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Scale view")

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

        label = "스케일보기"
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
            self._draw_empty(painter, "파일을 열면 곡의 스케일 블럭을 표시합니다.")
            return
        if self.preferred_scale is None or not self.usages:
            self._draw_empty(painter, "표시할 곡의 스케일 블럭이 없습니다.")
            return
        self._draw_fretboard(painter)

    def _draw_empty(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    def _draw_fretboard(self, painter: QPainter) -> None:
        if self.song is None or self.preferred_scale is None:
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        usages = self._visible_usages()
        if not usages:
            self._draw_empty(painter, "표시할 곡의 스케일 블럭이 없습니다.")
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
            return "곡의 스케일뷰"
        name = candidate_display_name(self.preferred_scale, self.song.track.prefer_flats)
        total = sum(usage.selected_count for usage in self.usages)
        return f"최선호 스케일: {name} · 선택 마디 {total}개"

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

        label = "스케일보기"
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
            self._draw_empty(painter, "파일을 열면 코드 포지션을 표시합니다.")
            return
        if self.candidate is None:
            self._draw_empty(painter, "마디의 코드 칩을 누르면 잡을 위치가 표시됩니다.")
            return
        if not self.positions:
            self._draw_empty(painter, "현재 제약 안에서 표시할 코드 포지션을 찾지 못했습니다.")
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
        painter.drawText(self.rect().adjusted(18, 18, -18, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

    def _draw_message(self, painter: QPainter, y: int, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRect(18, y, self.width() - 36, 120),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            text,
        )

    def _draw_category_header(self, painter: QPainter, y: int, category: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf5"))
        painter.drawRoundedRect(rect, 6, 6)
        count = len([position for position in self._visible_positions() if category in position.categories])
        count_text = f"  {count}개" if count else ""
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{category}{count_text}")

    def _draw_category_message(self, painter: QPainter, y: int, text: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 34)
        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#657083"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, text)

    def _draw_title(self, painter: QPainter) -> None:
        if self.song is None or self.candidate is None:
            return
        measure_text = f"M{self.measure.number}  " if self.measure is not None else ""
        title = f"{measure_text}{candidate_display_name(self.candidate, self.song.track.prefer_flats)} 코드 포지션"
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
            f" · {position.label}"
        )
        painter.drawText(
            rect.adjusted(10, 7, -10, -rect.height() + 41),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            title,
        )

        fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
        missing = self._missing_text(position)
        barre = f" · 바레 {position.barre_fret}프렛" if position.barre_fret is not None else ""
        range_start, range_end = self._display_fret_range(position)
        meta = (
            f"손가락 {position.finger_count}개"
            f"{' + 뮤트 ' + str(position.muted_finger_count) + '개' if position.muted_finger_count else ''}"
            f"{barre} · {range_start}-{range_end}프렛 · {fret_text} · 생략음 {missing}"
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
        for fret in range(range_start, range_end + 1):
            x = int(board.left() + (fret - range_start + 0.5) * fret_gap)
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
        x = int(board.left() + (position.barre_fret - range_start + 0.5) * fret_gap)
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
            if fret == 0:
                x = int(board.left())
            else:
                x = int(board.left() + (fret - range_start + 0.5) * fret_gap)
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
            parts.append(f"root가 {self.root_string_filter}번줄에 있는")
        if self.category_filter is not None:
            parts.append(f"{self.category_filter} 카테고리의")
        if parts:
            return " ".join(parts) + " 코드 포지션이 없습니다."
        return "표시할 코드 포지션이 없습니다."

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
        return ", ".join(missing) if missing else "없음"


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
        self.tab_playback_panel = TabPlaybackPanel()
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
        self._preserving_playback_selection = False
        self._load_thread: QThread | None = None
        self._load_worker: _LoadWorker | None = None
        self._load_progress_dialog: AnalysisProgressDialog | None = None
        self._songsterr_thread: QThread | None = None
        self._songsterr_worker: _SongsterrWorker | None = None
        self._songsterr_progress_dialog: AnalysisProgressDialog | None = None

        self._build_ui()
        self.tab_canvas.selectionChanged.connect(self._on_selection_changed)
        self.tab_canvas.memoClicked.connect(self._open_memo_for_measure)
        self.tab_playback_panel.selectionChanged.connect(self._on_tab_block_selection_changed)
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
        help_menu = self.menuBar().addMenu("Help")

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("Open", self)
        open_action.triggered.connect(self._open_file_dialog)
        file_menu.addAction(open_action)
        toolbar.addAction(open_action)
        songsterr_action = QAction("Songsterr에서 타브검색", self)
        songsterr_action.triggered.connect(self._search_songsterr)
        file_menu.addAction(songsterr_action)
        toolbar.addAction(songsterr_action)
        songsterr_login_action = QAction("Songsterr 로그인", self)
        songsterr_login_action.triggered.connect(self._login_songsterr)
        file_menu.addAction(songsterr_login_action)
        toolbar.addAction(songsterr_login_action)
        file_menu.addSeparator()
        memo_save_action = QAction("메모 저장", self)
        memo_save_action.setShortcut(QKeySequence("Ctrl+S"))
        memo_save_action.triggered.connect(self._save_memo)
        file_menu.addAction(memo_save_action)
        memo_save_as_action = QAction("메모 다른이름으로 저장", self)
        memo_save_as_action.triggered.connect(self._save_memo_as)
        file_menu.addAction(memo_save_as_action)
        memo_load_action = QAction("메모 불러오기", self)
        memo_load_action.setShortcut(QKeySequence("Ctrl+L"))
        memo_load_action.triggered.connect(self._load_memo_from_dialog)
        file_menu.addAction(memo_load_action)
        help_action = QAction("매뉴얼", self)
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
        self.analysis_tab_index = self.top_tabs.addTab(self.analysis_scroll, "분석 마디")
        self.tab_playback_tab_index = self.top_tabs.addTab(self.tab_playback_panel, "타브 플레이어")
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
        scale_filter_layout.addWidget(QLabel("종류"))
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
        song_scale_filter_layout.addWidget(QLabel("표시 개수"))
        song_scale_filter_layout.addWidget(self.song_scale_count_spin, 0)
        song_scale_filter_layout.addStretch(1)
        song_scale_usage_layout = QVBoxLayout(self.song_scale_usage_panel)
        song_scale_usage_layout.setContentsMargins(0, 0, 0, 0)
        song_scale_usage_layout.setSpacing(0)
        song_scale_usage_layout.addLayout(song_scale_filter_layout)
        song_scale_usage_layout.addWidget(self.song_scale_usage_widget, 1)
        self.measure_tabs.addTab(self.fretboard, "지판뷰")
        self.measure_tabs.addTab(self.scale_position_panel, "스케일뷰")
        self.measure_tabs.addTab(self.song_scale_usage_panel, "곡의 스케일뷰")
        self.measure_tabs.addTab(self.theory_browser, "마디설명")
        self.measure_tabs.addTab(self.memo_editor, "메모")
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
        chord_filter_layout.addWidget(QLabel("Root 줄"))
        chord_filter_layout.addWidget(self.root_string_combo, 1)
        chord_filter_layout.addWidget(QLabel("종류"))
        chord_filter_layout.addWidget(self.category_combo, 1)
        chord_panel_layout = QVBoxLayout(self.chord_positions_panel)
        chord_panel_layout.setContentsMargins(0, 0, 0, 0)
        chord_panel_layout.setSpacing(0)
        chord_panel_layout.addLayout(chord_filter_layout)
        chord_panel_layout.addWidget(self.chord_positions_scroll)
        self.right_tabs.addTab(self.song_browser, "곡 분석")
        self.right_tabs.addTab(self.chord_positions_panel, "코드 포지션")
        self.right_tabs.addTab(self.tab_playback_panel.recording_tab, "녹음")
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

    def _load_selected_track(self) -> None:
        if self.current_file is None:
            return
        track_index = self.track_combo.currentData()
        if track_index is None:
            track_index = 0
        self._start_load_worker(self.current_file, int(track_index), include_tracks=False)

    def _start_load_worker(self, path: Path, track_index: int | None, include_tracks: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            QMessageBox.information(self, "분석 중", "이미 다른 타브 파일을 분석하는 중입니다.")
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
        dialog.set_progress(10, "분석을 시작하는 중입니다.")
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
            self._load_progress_dialog.set_progress(100, "완료되었습니다.")
        mode, path, tracks, selected_track, song = result
        if Path(path) != self.current_file:
            return
        if mode == "file" and tracks is not None:
            self._populate_track_combo(tracks, int(selected_track))
        self._finish_loaded_song(song)

    def _on_load_failed(self, message: str) -> None:
        self._close_load_progress()
        self._set_loading_enabled(True)
        QMessageBox.critical(self, "Load failed", message)

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
            QMessageBox.information(self, "Songsterr 처리 중", "이미 Songsterr 작업이 진행 중입니다.")
            return
        self._show_songsterr_progress("Songsterr에서 곡을 검색하는 중입니다." if mode == "search" else "Songsterr에서 파일을 받는 중입니다.")
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
            window_title="Songsterr 처리 중",
            title_prefix="Songsterr 처리 중",
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
            self._songsterr_progress_dialog.set_progress(100, "완료되었습니다.")
        self._close_songsterr_progress()
        mode, _request, payload = result
        if mode == "search":
            results = payload
            if not results:
                QMessageBox.information(self, "Songsterr", "해당 검색어로 찾은 타브가 없습니다.")
                self.statusBar().clearMessage()
                return
            selected = self._choose_songsterr_result(results)
            if selected is None:
                self.statusBar().clearMessage()
                return
            self.statusBar().showMessage(f"Songsterr export 중: {selected.artist} - {selected.title}")
            cookie = load_cookie_header() or os.environ.get("SONGSTERR_COOKIE")
            current_thread = self._songsterr_thread
            if current_thread is not None:
                current_thread.finished.connect(lambda: self._start_songsterr_worker("download", result=selected, cookie=cookie))
            else:
                self._start_songsterr_worker("download", result=selected, cookie=cookie)
            return

        path = payload
        self.statusBar().showMessage(f"Downloaded {path.name}")
        self.load_file(path)

    def _on_songsterr_failed(self, message: str) -> None:
        self._close_songsterr_progress()
        QMessageBox.warning(self, "Songsterr failed", message)
        self.statusBar().clearMessage()

    def _on_songsterr_auth_failed(self) -> None:
        self._close_songsterr_progress()
        QMessageBox.warning(
            self,
            "Songsterr export requires login",
            "Songsterr에서 타브는 찾았지만 Guitar Pro export는 로그인 또는 export 권한이 필요합니다.\n\n"
            "이 프로그램은 Songsterr의 공식 export API만 사용합니다. 이미 권한이 있는 계정이라면 "
            "상단의 Songsterr 로그인 버튼으로 먼저 로그인해 주세요.",
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
            f"Loaded {self.song.path.name} - {self.song.track.name} - {len(self.song.track.measures)} measures - tuning {self._current_tuning_name()}"
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
                QMessageBox.warning(self, "메모 불러오기 실패", f"{load_path.name}\n\n{exc}")
        self.memo_dirty = False
        self.memo_text_pending = False
        self.memo_icon_refresh_pending = False

        if self.memo_autosave_path.exists():
            memo_mtime = load_path.stat().st_mtime if load_path is not None else 0
            if self.memo_autosave_path.stat().st_mtime >= memo_mtime:
                result = QMessageBox.question(
                    self,
                    "자동저장 메모",
                    "이전에 자동저장 된 메모가 있습니다. 불러올까요?",
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
                        QMessageBox.warning(self, "자동저장 메모 불러오기 실패", str(exc))
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
            "메모 저장",
            "메모의 변경사항을 저장하시겠습니까?",
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
            self.statusBar().showMessage(f"Memo saved: {self.memo_path.name}")
            self._refresh_memo_icons()
            return True
        except OSError as exc:
            QMessageBox.warning(self, "메모 저장 실패", str(exc))
            return False

    def _save_memo_as(self) -> bool:
        self._sync_current_memo_from_editor(force=True)
        start = str(self.memo_path or (Path.cwd() / "memo.mmdx"))
        path, _ = QFileDialog.getSaveFileName(self, "메모 다른이름으로 저장", start, "Tab Analyzer Memo (*.mmdx);;All files (*.*)")
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
        path, _ = QFileDialog.getOpenFileName(self, "메모 불러오기", start, "Tab Analyzer Memo (*.mmdx);;Legacy Markdown (*.md);;All files (*.*)")
        if not path:
            return
        loaded_path = Path(path)
        try:
            self._clear_memo_asset_dir()
            self.memo_asset_dir = self._make_memo_asset_dir() if loaded_path.suffix.lower() == ".mmdx" else None
            self.measure_memos = _read_memo_package(loaded_path, self.memo_asset_dir)
        except (OSError, UnicodeError) as exc:
            QMessageBox.warning(self, "메모 불러오기 실패", str(exc))
            return
        except zipfile.BadZipFile as exc:
            QMessageBox.warning(self, "메모 불러오기 실패", str(exc))
            return
        self.memo_path = loaded_path if loaded_path.suffix.lower() == ".mmdx" else loaded_path.with_suffix(".mmdx")
        self.memo_dirty = False
        self.memo_text_pending = False
        self.memo_icon_refresh_pending = False
        self._refresh_memo_icons()
        self._sync_memo_editor()
        self.statusBar().showMessage(f"Memo loaded: {self.memo_path.name}")

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

    def _open_manual(self) -> None:
        self._ensure_manual_file()
        dialog = self.manual_dialog
        if dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Tab Analyzer Manual")
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
            browser.setSource(QUrl.fromLocalFile(str(MANUAL_PATH)))
        self.manual_dialog.show()
        self.manual_dialog.raise_()
        self.manual_dialog.activateWindow()

    def _ensure_manual_file(self) -> None:
        if MANUAL_PATH.exists():
            return
        MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANUAL_PATH.write_text(
            """<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>Tab Analyzer Manual</title></head>
<body><h1>Tab Analyzer Manual</h1><p>매뉴얼 파일을 준비 중입니다.</p></body>
</html>
""",
            encoding="utf-8",
        )

    def _open_about(self) -> None:
        QMessageBox.about(
            self,
            "About Tab Analyzer",
            f"Tab Analyzer\n\nVersion: {__version__}\nhttps://github.com/swirlpotato/TabAnalyzer",
        )

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
            "Open Guitar Pro file",
            start_dir,
            "Guitar Pro files (*.gp *.gp3 *.gp4 *.gp5 *.gpx);;All files (*.*)",
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
                "Songsterr login unavailable",
                "Songsterr 로그인을 열기 위해 PyQt6-WebEngine이 필요하지만 import에 실패했습니다.\n\n"
                f"현재 앱 실행 Python:\n{sys.executable}\n\n"
                f"이 Python에 설치하려면:\n{install_command}\n\n"
                f"{type(exc).__name__}:\n{exc}",
            )
            return

        try:
            dialog = QDialog(self)
            dialog.setWindowTitle("Songsterr 로그인")
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
                    popup.setWindowTitle("Songsterr 로그인")
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
                "Songsterr login unavailable",
                "PyQt6-WebEngine은 설치되어 있지만 브라우저 초기화에 실패했습니다.\n\n"
                f"현재 앱 실행 Python:\n{sys.executable}\n\n"
                f"{type(exc).__name__}:\n{exc}\n\n"
                f"{traceback.format_exc()}",
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
            ok_button.setText("로그인 완료")

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
            QMessageBox.warning(self, "Songsterr login", "Songsterr 쿠키를 찾지 못했습니다. 로그인 후 다시 눌러 주세요.")
            return

        cookie_header = "; ".join(f"{name}={value}" for name, value in sorted(cookies.items()))
        try:
            save_cookie_header(cookie_header)
        except SongsterrError as exc:
            shutil.rmtree(session_root, ignore_errors=True)
            QMessageBox.warning(self, "Songsterr login", str(exc))
            return

        shutil.rmtree(session_root, ignore_errors=True)
        self.statusBar().showMessage("Songsterr login cookie saved")
        QMessageBox.information(self, "Songsterr login", "Songsterr 로그인 정보가 저장됐습니다.")

    def _search_songsterr(self) -> None:
        default_query = self._default_songsterr_query()
        query, ok = QInputDialog.getText(
            self,
            "Songsterr에서 타브검색",
            "검색어",
            text=default_query,
        )
        if not ok:
            return
        query = " ".join(query.split())
        if not query:
            QMessageBox.information(self, "Songsterr", "검색어를 입력해 주세요.")
            return

        self.statusBar().showMessage(f"Songsterr 검색 중: {query}")
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
            "Songsterr 검색 결과",
            "열 타브 선택",
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
        else:
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
                f"Tuning: {self._current_tuning_name()} - global scale {self.song.global_scale.name if self.song.global_scale else '-'}"
            )

    def _on_top_tab_changed(self, index: int) -> None:
        if self.song is None or not self.song.track.measures:
            return

        if index == self.analysis_tab_index:
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
            self._set_toolbar_zoom_percent(self.tab_playback_panel.zoom_percent())
            measure_index = self.tab_playback_panel.current_measure_index()
            QTimer.singleShot(0, lambda item=measure_index: self.tab_playback_panel.scroll_measure_into_view(item))

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

    def _apply_selected_tuning(self) -> None:
        if self.source_song is None:
            return

        preset = self._selected_tuning_preset()
        try:
            song = self.source_song if preset is None else retune_song(self.source_song, preset.midi_high_to_low)
        except ValueError as exc:
            QMessageBox.warning(self, "Tuning mismatch", str(exc))
            self.tuning_combo.setCurrentIndex(0)
            song = self.source_song

        self.song = song
        self.tab_canvas.set_song(song)
        self.tab_playback_panel.set_song(song)
        self.fretboard.set_song(song)
        self.scale_position_widget.set_song(song)
        self.song_scale_usage_widget.set_song(song)
        self._populate_root_string_combo(len(song.track.string_pitches))

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
            return "From file"
        return "From file (" + " ".join(reversed(self.song.track.string_names)) + ")"

    def _populate_root_string_combo(self, string_count: int) -> None:
        current = self.root_string_combo.currentData()
        self.root_string_combo.blockSignals(True)
        self.root_string_combo.clear()
        self.root_string_combo.addItem("전체", None)
        for string_number in range(string_count, 0, -1):
            self.root_string_combo.addItem(f"{string_number}번줄", string_number)
        index = self.root_string_combo.findData(current)
        self.root_string_combo.setCurrentIndex(index if index >= 0 else 0)
        self.root_string_combo.blockSignals(False)
        selected = self.root_string_combo.currentData()
        self.chord_positions_widget.set_root_string_filter(int(selected) if selected is not None else None)

    def _populate_category_combo(self) -> None:
        current = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("전체", None)
        for category in CHORD_POSITION_CATEGORIES:
            self.category_combo.addItem(category, category)
        index = self.category_combo.findData(current)
        self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.blockSignals(False)
        selected = self.category_combo.currentData()
        self.chord_positions_widget.set_category_filter(str(selected) if selected is not None else None)

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
            self.scale_type_combo.addItem(display_name, name)
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
            self.statusBar().showMessage(f"M{measure.number}: no notes")
            return
        segment_text = ""
        if segment is not None:
            start_percent = round((segment.start_in_measure / measure.length_ticks) * 100)
            end_percent = round((segment.end_in_measure / measure.length_ticks) * 100)
            segment_text = f" {start_percent}-{end_percent}%"
        self.statusBar().showMessage(f"M{measure.number}{segment_text}: {kind} {candidate.name} ({candidate.score}/100)")

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
        theory_index = self.measure_tabs.indexOf(self.theory_browser)
        if theory_index >= 0:
            self.measure_tabs.setCurrentIndex(theory_index)
        if start == end:
            self.statusBar().showMessage(f"M{first_measure.number}: 타브 블럭 선택")
        else:
            self.statusBar().showMessage(f"M{first_measure.number}-M{measures[end].number}: 타브 블럭 선택")

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
            QMessageBox.information(self, "분석 중", "타브 파일 분석이 끝난 뒤 창을 닫아주세요.")
            event.ignore()
            return
        if self._songsterr_thread is not None and self._songsterr_thread.isRunning():
            QMessageBox.information(self, "Songsterr 처리 중", "Songsterr 작업이 끝난 뒤 창을 닫아주세요.")
            event.ignore()
            return
        if not self._maybe_save_memo_changes():
            event.ignore()
            return
        self.tab_playback_panel.shutdown()
        self._clear_memo_asset_dir()
        super().closeEvent(event)


def run_app(initial_file: str | Path | None = None) -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv if sys.argv else ["TabAnalyzer"])
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    window = TabAnalyzerWindow(initial_file=initial_file)
    window.show()
    return app.exec()
