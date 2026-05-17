"""Background workers and progress dialogs for long-running UI tasks."""

from __future__ import annotations

from .common import *

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


class _YouTubeSyncWorker(QObject):
    captureStarted = pyqtSignal()
    finished = pyqtSignal(object)

    def __init__(
        self,
        song: SongData,
        start_tick: int,
        play_seconds: float,
        total_capture_seconds: float,
        current_offset_ms: int,
        speed_percent: int,
    ) -> None:
        super().__init__()
        self.song = song
        self.start_tick = int(start_tick)
        self.play_seconds = float(play_seconds)
        self.total_capture_seconds = float(total_capture_seconds)
        self.current_offset_ms = int(current_offset_ms)
        self.speed_percent = int(speed_percent)

    def run(self) -> None:
        try:
            samples, sample_rate, device = capture_system_audio(
                self.total_capture_seconds,
                started_callback=self.captureStarted.emit,
            )
            estimate = estimate_sync_offset(
                samples,
                sample_rate,
                self.song,
                self.start_tick,
                self.play_seconds,
                self.current_offset_ms,
                self.speed_percent,
                capture_device_name=device.display_name,
            )
            self.finished.emit(estimate)
        except YouTubeSyncError as exc:
            self.finished.emit(exc)
        except Exception as exc:  # noqa: BLE001 - audio backends can raise platform-specific errors.
            self.finished.emit(YouTubeSyncError(str(exc)))

