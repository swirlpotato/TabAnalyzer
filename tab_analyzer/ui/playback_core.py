"""Core audio, recording, metronome, and YouTube playback controllers."""

from __future__ import annotations

from .common import *

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
        self._run_js("if (typeof pauseVideo === 'function') { pauseVideo(); }")
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
            self._seek_current_tick_for_sync()

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

    def _seek_current_tick_for_sync(self) -> None:
        self._run_or_queue_js(
            f"playAt({self._tick_to_seconds(self.current_tick):.3f}, {self.speed_percent / 100.0:.3f});",
            defer=self._loading_video,
        )
        if self.clock.isValid():
            self.clock.restart()

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

