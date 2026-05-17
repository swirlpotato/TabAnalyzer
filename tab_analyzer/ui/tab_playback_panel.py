"""Tab playback controls and recording list UI."""

from __future__ import annotations

from .common import *
from .playback_core import RecordingController, StandaloneMetronome, YouTubeTabPlayer
from .score import TabScoreWidget
from .workers import AnalysisProgressDialog, _YouTubeSyncWorker

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
        self.youtube_sync_find_button = QPushButton("Auto Sync")
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
        self._youtube_sync_thread: QThread | None = None
        self._youtube_sync_worker: _YouTubeSyncWorker | None = None
        self._youtube_sync_progress_dialog: AnalysisProgressDialog | None = None
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
        self.youtube_sync_down_button.clicked.connect(lambda: self._adjust_youtube_sync(-SYNC_STEP_MS))
        self.youtube_sync_up_button.clicked.connect(lambda: self._adjust_youtube_sync(SYNC_STEP_MS))
        self.youtube_sync_spin.valueChanged.connect(self._on_youtube_sync_changed)
        self.youtube_sync_find_button.clicked.connect(self._start_youtube_sync_search)
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
        self.youtube_sync_spin.setSingleStep(SYNC_STEP_MS)
        self.youtube_sync_spin.setSuffix(" ms")
        self.youtube_sync_spin.setKeyboardTracking(False)
        self.youtube_sync_spin.setFixedWidth(88)
        self.youtube_sync_find_button.setFixedWidth(76)
        self.youtube_sync_find_button.setToolTip("Analyze YouTube audio and suggest the closest sync offset")
        controls.addWidget(self.youtube_sync_down_button)
        controls.addWidget(self.youtube_sync_spin)
        controls.addWidget(self.youtube_sync_up_button)
        controls.addWidget(self.youtube_sync_find_button)
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
        self._close_youtube_sync_progress()
        if self._youtube_sync_thread is not None and self._youtube_sync_thread.isRunning():
            self._youtube_sync_thread.quit()
            self._youtube_sync_thread.wait(15000)
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
            offset_ms = round_sync_milliseconds(float(sync.get("offset_seconds", 0.0)) * 1000) if isinstance(sync, dict) else 0
        except (TypeError, ValueError):
            offset_ms = 0
        self._syncing_youtube_sync_spin = True
        self.youtube_sync_spin.setValue(max(self.youtube_sync_spin.minimum(), min(self.youtube_sync_spin.maximum(), offset_ms)))
        self._syncing_youtube_sync_spin = False
        self.youtube_player.set_offset_milliseconds(self.youtube_sync_spin.value())
        self._update_youtube_sync_controls()

    def _update_youtube_sync_controls(self) -> None:
        enabled = bool(self.song is not None and self.youtube_player.video_id and self.youtube_player.available)
        finding = self._youtube_sync_thread is not None and self._youtube_sync_thread.isRunning()
        for widget in (self.youtube_sync_spin, self.youtube_sync_down_button, self.youtube_sync_up_button):
            widget.setEnabled(enabled)
        self.youtube_sync_find_button.setEnabled(enabled and not finding)

    def _round_to_sync_step(self, value: int) -> int:
        return round_sync_milliseconds(value)

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

    def _start_youtube_sync_search(self) -> None:
        if self.song is None or not self.song.track.measures:
            return
        if self._youtube_sync_thread is not None and self._youtube_sync_thread.isRunning():
            QMessageBox.information(self, tr("Auto Sync"), tr("A YouTube sync search is already running."))
            return
        if not self.youtube_player.playback_available or not self.youtube_player.video_id:
            QMessageBox.warning(
                self,
                tr("YouTube unavailable"),
                tr("YouTube playback information is unavailable, so MIDI playback will be used."),
            )
            return

        start, end, play_seconds = self._youtube_sync_probe_range()
        start_tick = self.song.track.measures[start].start_tick
        total_capture_seconds = AUTO_SYNC_PRE_ROLL_SECONDS + play_seconds + AUTO_SYNC_SEARCH_RADIUS_SECONDS
        speed_percent = self.speed_slider.value()

        self._stop()
        self.youtube_radio.setChecked(True)
        self.youtube_sync_find_button.setText("Finding...")
        self.youtube_sync_find_button.setEnabled(False)
        self.youtube_status_label.setText(tr("Finding YouTube sync..."))
        self._show_youtube_sync_progress("Preparing audio capture.")

        thread = QThread(self)
        worker = _YouTubeSyncWorker(
            self.song,
            start_tick,
            play_seconds,
            total_capture_seconds,
            self.youtube_sync_spin.value(),
            speed_percent,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.captureStarted.connect(self._on_youtube_sync_capture_started)
        worker.captureStarted.connect(
            lambda s=start, e=end: QTimer.singleShot(
                int(AUTO_SYNC_PRE_ROLL_SECONDS * 1000),
                lambda: self._start_playback(s, e, repeat=False, play_from=s),
            )
        )
        worker.finished.connect(self._on_youtube_sync_search_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_youtube_sync_thread_finished)
        self._youtube_sync_thread = thread
        self._youtube_sync_worker = worker
        thread.start()

    def _show_youtube_sync_progress(self, detail: str) -> None:
        self._close_youtube_sync_progress()
        dialog = AnalysisProgressDialog(
            self,
            window_title="Auto Sync",
            title_prefix="Auto Sync",
            initial_detail=detail,
        )
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.set_progress(10, detail)
        self._youtube_sync_progress_dialog = dialog
        dialog.show()

    def _on_youtube_sync_capture_started(self) -> None:
        if self._youtube_sync_progress_dialog is not None:
            self._youtube_sync_progress_dialog.set_progress(25, "Capturing YouTube audio. Please wait.")

    def _close_youtube_sync_progress(self) -> None:
        if self._youtube_sync_progress_dialog is None:
            return
        self._youtube_sync_progress_dialog.close()
        self._youtube_sync_progress_dialog.deleteLater()
        self._youtube_sync_progress_dialog = None

    def _youtube_sync_probe_range(self) -> tuple[int, int, float]:
        if self.song is None or not self.song.track.measures:
            return 0, 0, AUTO_SYNC_MIN_PLAY_SECONDS
        measures = self.song.track.measures
        speed_percent = self.speed_slider.value()
        start = max(0, min(self.selected_start, len(measures) - 1))
        selected_end = max(start, min(self.selected_end, len(measures) - 1))
        start_tick = measures[start].start_tick
        selected_end_tick = measures[selected_end].start_tick + measures[selected_end].length_ticks
        selected_seconds = song_seconds_for_ticks(self.song, selected_end_tick - start_tick, speed_percent)

        if selected_end > start and selected_seconds >= AUTO_SYNC_MIN_PLAY_SECONDS:
            play_seconds = min(AUTO_SYNC_MAX_PLAY_SECONDS, selected_seconds)
        else:
            play_seconds = AUTO_SYNC_TARGET_PLAY_SECONDS

        target_ticks = ticks_for_song_seconds(self.song, play_seconds + AUTO_SYNC_SEARCH_RADIUS_SECONDS, speed_percent)
        target_end_tick = start_tick + target_ticks
        end = start
        for index in range(start, len(measures)):
            end = index
            measure_end = measures[index].start_tick + measures[index].length_ticks
            if measure_end >= target_end_tick:
                break
        play_seconds = max(AUTO_SYNC_MIN_PLAY_SECONDS, min(AUTO_SYNC_MAX_PLAY_SECONDS, play_seconds))
        return start, end, play_seconds

    def _on_youtube_sync_search_finished(self, result: object) -> None:
        self._stop()
        if self._youtube_sync_progress_dialog is not None:
            self._youtube_sync_progress_dialog.set_progress(100, "Done.")
        self._close_youtube_sync_progress()
        self.youtube_sync_find_button.setText("Auto Sync")
        self._update_youtube_status()
        if isinstance(result, Exception):
            QMessageBox.warning(self, tr("Auto Sync"), str(result))
            return
        if not isinstance(result, SyncEstimate):
            QMessageBox.warning(self, tr("Auto Sync"), tr("Automatic sync analysis failed."))
            return

        confidence_percent = round(result.confidence * 100)
        device_line = f"\n{tr('Captured from')}: {result.capture_device_name}" if result.capture_device_name else ""
        if abs(result.delta_ms) < SYNC_STEP_MS:
            QMessageBox.information(
                self,
                tr("Auto Sync"),
                tr("Sync looks close enough.")
                + f"\n{tr('Current Sync')}: {result.current_offset_ms} ms"
                + f"\n{tr('Confidence')}: {confidence_percent}%"
                + device_line,
            )
            return

        message = (
            tr("The tab and YouTube audio look out of sync.")
            + f"\n{tr('Current Sync')}: {result.current_offset_ms} ms"
            + f"\n{tr('Suggested Sync')}: {result.suggested_offset_ms} ms"
            + f"\n{tr('Estimated difference')}: {result.delta_ms:+d} ms"
            + f"\n{tr('Confidence')}: {confidence_percent}%"
            + device_line
            + "\n\n"
            + tr("Apply the suggested sync value?")
        )
        answer = QMessageBox.question(
            self,
            tr("Auto Sync"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.youtube_sync_spin.setValue(result.suggested_offset_ms)

    def _on_youtube_sync_thread_finished(self) -> None:
        self._youtube_sync_thread = None
        self._youtube_sync_worker = None
        self._close_youtube_sync_progress()
        self.youtube_sync_find_button.setText("Auto Sync")
        self._update_youtube_sync_controls()

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
        measure_changed = False
        if self.song is not None and self.song.track.measures:
            measure_index = self._measure_index_for_tick(tick)
            if measure_index != self._playback_measure_index:
                self._playback_measure_index = measure_index
                measure_changed = True
                self.playbackMeasureChanged.emit(measure_index)
        if measure_changed:
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

