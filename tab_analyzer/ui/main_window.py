"""Main Tab Analyzer window and application entry point."""

from __future__ import annotations

from .common import *
from .chords import ChordFinderWidget, ChordPositionsWidget
from .fretboard import FretboardWidget, ScalePositionWidget, SongScaleUsageWidget
from .score import TabCanvas
from .songsterr_panel import SongsterrPagePanel
from .tab_playback_panel import MemoEditorWidget, TabPlaybackPanel
from .workers import AnalysisProgressDialog, _LoadWorker, _SongsterrWorker

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
        self.songsterr_panel.selectionChanged.connect(self._on_tab_block_selection_changed)
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
        self._restore_selected_measure_from_details(self.song)
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
            self._sync_songsterr_to_measure(self.tab_playback_panel.current_measure_index())

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
        self.songsterr_panel.set_measure_count(
            len(song.track.measures) if song is not None else 0,
            self.tab_playback_panel.selected_measure_range(),
        )
        self._update_songsterr_tab(song)
        self.fretboard.set_song(song)
        self.scale_position_widget.set_song(song)
        self.song_scale_usage_widget.set_song(song)
        self.chord_finder_widget.set_song(song)
        self._populate_root_string_combo(len(song.track.string_pitches) if song is not None else 6)
        self._restore_selected_measure_from_details(song)

    def _restore_selected_measure_from_details(self, song: SongData | None) -> None:
        if song is None or not song.track.measures:
            return
        details = self.tab_playback_panel.details if isinstance(self.tab_playback_panel.details, dict) else load_details_file(song.path)
        saved = selected_measure_range_from_details(details, tuple(measure.number for measure in song.track.measures))
        if saved is None:
            return
        start, end = self._clamped_measure_range(saved[0], saved[1])
        self._apply_selected_measure_range(start, end, update_context=True)
        self._sync_songsterr_to_measure(start)
        QTimer.singleShot(0, lambda item=start: self._scroll_current_top_tab_to_measure(item))

    def _apply_selected_measure_range(self, start: int, end: int, update_context: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            return
        start, end = self._clamped_measure_range(start, end)
        self.tab_canvas.set_selected_measure_index(start, emit=False)
        self.tab_playback_panel.set_selected_measure_range(start, end, notify=False)
        self.songsterr_panel.set_selected_measure_range(start, end, notify=False)
        self._set_current_memo_measure_index(start)
        if not update_context:
            return
        measure = self.song.track.measures[start]
        candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
        self.fretboard.set_selection(measure, candidate, "scale", None)
        self.theory_browser.setHtml(self.theory_explainer.explain_tab_selection(self.song, start, end))

    def _save_selected_measure_range(self, start: int, end: int) -> None:
        if self.song is None or not self.song.track.measures:
            return
        song_path = Path(self.song.path)
        details_path = details_path_for_gp(song_path)
        if not song_path.exists() and not details_path.exists():
            return
        start, end = self._clamped_measure_range(start, end)
        measures = self.song.track.measures
        details = self.tab_playback_panel.details if isinstance(self.tab_playback_panel.details, dict) else load_details_file(song_path)
        if update_selected_measure_range(details, start, end, measures[start].number, measures[end].number):
            save_details_file(song_path, details)
        self.tab_playback_panel.details = details

    def _sync_songsterr_to_measure(self, measure_index: int) -> None:
        if self.song is None or not self.song.track.measures or self.songsterr_tab_index < 0:
            return
        measure_index, _end = self._clamped_measure_range(measure_index, measure_index)
        self.songsterr_panel.set_selected_measure_index(measure_index)

    def _scroll_current_top_tab_to_measure(self, measure_index: int) -> None:
        if self.top_tabs.currentIndex() == self.analysis_tab_index:
            self._scroll_analysis_measure_into_view(measure_index)
        elif self.top_tabs.currentIndex() == self.tab_playback_tab_index:
            self.tab_playback_panel.scroll_measure_into_view(measure_index)

    def _clamped_measure_range(self, start: int, end: int) -> tuple[int, int]:
        if self.song is None or not self.song.track.measures:
            return 0, 0
        count = len(self.song.track.measures)
        start = max(0, min(start, count - 1))
        end = max(0, min(end, count - 1))
        if end < start:
            start, end = end, start
        return start, end

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
        self.songsterr_panel.set_measure_count(0)

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
                self.songsterr_panel.set_selected_measure_range(index, index, notify=False)
            self._set_current_memo_measure_index(index)
            self._save_selected_measure_range(index, index)
            self._sync_songsterr_to_measure(index)
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
        self.tab_playback_panel.set_selected_measure_range(start, end, notify=False)
        self.songsterr_panel.set_selected_measure_range(start, end, notify=False)
        self._set_current_memo_measure_index(start)
        self._save_selected_measure_range(start, end)
        self._sync_songsterr_to_measure(start)
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

    def _sync_selection_from_songsterr_measure(self, measure_index: int) -> MeasureData | None:
        if self.song is None or not self.song.track.measures:
            return None
        measure_index, _end = self._clamped_measure_range(measure_index, measure_index)
        if self.songsterr_panel.repeat_enabled():
            measure = self._select_fretboard_scale_measure(measure_index)
            self._set_current_memo_measure_index(measure_index)
            self.theory_browser.setHtml(self.theory_explainer.explain_tab_selection(self.song, measure_index, measure_index))
            return measure
        self._apply_selected_measure_range(measure_index, measure_index, update_context=True)
        self._save_selected_measure_range(measure_index, measure_index)
        return self.song.track.measures[measure_index]

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
        preserve_selected_range = self.songsterr_panel.repeat_enabled()
        if bool(state.get("shouldPlay")) and state.get("source") == "time":
            tick_from_time = self._songsterr_playback_tick_from_state(state)
            if tick_from_time is not None:
                measure_index = self._measure_index_for_playback_tick(tick_from_time)
                measure = measures[measure_index]
                selection_mismatch = (
                    not preserve_selected_range
                    and self.tab_playback_panel.current_measure_index() != measure_index
                )
                if (
                    self._songsterr_playback_measure_index != measure_index
                    or self.fretboard.measure is not measure
                    or selection_mismatch
                ):
                    self._songsterr_playback_measure_index = measure_index
                    self._sync_selection_from_songsterr_measure(measure_index)
                self._set_songsterr_playback_tick(tick_from_time, state)
                return

        measure_index = max(0, min(measure_index, len(measures) - 1))
        measure = measures[measure_index]
        selection_mismatch = (
            not preserve_selected_range
            and self.tab_playback_panel.current_measure_index() != measure_index
        )
        if (
            self._songsterr_playback_measure_index != measure_index
            or self.fretboard.measure is not measure
            or selection_mismatch
        ):
            self._songsterr_playback_measure_index = measure_index
            self._sync_selection_from_songsterr_measure(measure_index)

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
        tick = int(
            round(
                song_tick_for_seconds(
                    self.song,
                    self._songsterr_playback_base_tick,
                    max(0, elapsed_ms) / 1000.0,
                    self._songsterr_playback_speed_percent,
                )
            )
        )
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
        tick = int(round(song_tick_for_seconds(self.song, 0, milliseconds / 1000.0)))
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
