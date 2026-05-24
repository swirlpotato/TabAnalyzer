import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tab_analyzer.songsterr import load_details_file, save_details_file
from tab_analyzer.ui import SongsterrPagePanel, TabAnalyzerWindow
from tests.helpers import beat, measure, song_with_measures, tab_note


class TabPlaybackSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tab_player_measure_click_shows_scale_on_fretboard(self):
        window = TabAnalyzerWindow()
        try:
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            window.song = song
            window.tab_canvas.set_song(song)
            window.tab_playback_panel.set_song(song)
            window.fretboard.set_song(song)
            window.measure_tabs.setCurrentWidget(window.theory_browser)

            window._on_tab_block_selection_changed(0, 0)

            self.assertIs(window.measure_tabs.currentWidget(), window.fretboard)
            self.assertIs(window.fretboard.measure, song.track.measures[0])
            self.assertEqual(window.fretboard.kind, "scale")
            self.assertEqual(window.fretboard.candidate, song.track.measures[0].analysis.scale_candidates[0])
        finally:
            window.close()

    def test_playback_measure_change_updates_fretboard_scale(self):
        window = TabAnalyzerWindow()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            window.song = song
            window.tab_canvas.set_song(song)
            window.tab_playback_panel.set_song(song)
            window.fretboard.set_song(song)

            window._on_tab_playback_measure_changed(1)

            self.assertIs(window.fretboard.measure, song.track.measures[1])
            self.assertEqual(window.fretboard.kind, "scale")
            self.assertEqual(window.fretboard.candidate, song.track.measures[1].analysis.scale_candidates[0])
        finally:
            window.close()

    def test_saved_selected_measure_restores_when_song_loads(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                gp_path = Path(temp_dir) / "Song.gp"
                gp_path.write_bytes(b"")
                song = replace(
                    song_with_measures(
                        (
                            measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                            measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                        )
                    ),
                    path=gp_path,
                )
                save_details_file(
                    gp_path,
                    {
                        "selection": {
                            "start_measure_index": 1,
                            "end_measure_index": 1,
                            "start_measure_number": 2,
                            "end_measure_number": 2,
                        },
                    },
                )

                window._set_current_song(song)

                self.assertEqual(window.tab_playback_panel.current_measure_index(), 1)
                self.assertEqual(window.tab_canvas.selected_measure_index, 1)
                self.assertIs(window.fretboard.measure, song.track.measures[1])
                self.assertEqual(window.current_memo_measure_index, 1)
        finally:
            window.close()

    def test_tab_selection_saves_details_and_pushes_songsterr(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                gp_path = Path(temp_dir) / "Song.gp"
                gp_path.write_bytes(b"")
                song = replace(
                    song_with_measures(
                        (
                            measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                            measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                        )
                    ),
                    path=gp_path,
                )
                save_details_file(
                    gp_path,
                    {
                        "source": "songsterr",
                        "songsterr": {
                            "song_id": 270,
                            "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                        },
                    },
                )
                pushed: list[int] = []
                window.songsterr_panel.set_selected_measure_index = lambda index: pushed.append(index)

                window._set_current_song(song)
                window._on_tab_block_selection_changed(1, 1)

                self.assertEqual(load_details_file(gp_path)["selection"]["start_measure_number"], 2)
                self.assertEqual(window.tab_canvas.selected_measure_index, 1)
                self.assertEqual(pushed[-1], 1)
        finally:
            window.close()

    def test_songsterr_measure_selection_requires_confirmed_selection(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            panel = SongsterrPagePanel()
        try:
            panel._pending_measure_index = 2
            panel._on_measure_selection_applied({"available": True, "selected": False})

            self.assertEqual(panel._pending_measure_index, 2)
            self.assertEqual(panel._measure_selection_attempts, 1)

            panel._on_measure_selection_applied({"available": True, "selected": True})

            self.assertIsNone(panel._pending_measure_index)
            self.assertEqual(panel._measure_selection_attempts, 0)
        finally:
            panel.close()

    def test_songsterr_measure_selection_uses_songsterr_dispatch_api(self):
        script = SongsterrPagePanel._SELECT_MEASURE_SCRIPT

        self.assertIn("store.dispatch(name, payload)", script)
        self.assertIn('dispatchAction("commands/editor:position"', script)
        self.assertIn('dispatchAction("editorUI/toBeat"', script)
        self.assertIn('dispatchAction("cursor/move"', script)

    def test_songsterr_repeat_range_updates_tab_player_selection(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                gp_path = Path(temp_dir) / "Song.gp"
                gp_path.write_bytes(b"")
                song = replace(
                    song_with_measures(
                        (
                            measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                            measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                        )
                    ),
                    path=gp_path,
                )
                save_details_file(
                    gp_path,
                    {
                        "source": "songsterr",
                        "songsterr": {
                            "song_id": 270,
                            "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                        },
                    },
                )

                window._set_current_song(song)
                window.songsterr_panel.set_selected_measure_range(0, 1, notify=True)

                self.assertEqual(window.tab_playback_panel.selected_measure_range(), (0, 1))
                self.assertEqual(window.songsterr_panel.selected_measure_range(), (0, 1))
                self.assertEqual(load_details_file(gp_path)["selection"]["end_measure_number"], 2)
        finally:
            window.close()

    def test_songsterr_repeat_restart_triggers_at_range_end(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            panel = SongsterrPagePanel()
        try:
            calls: list[bool] = []
            panel.set_measure_count(4, (1, 2))
            panel.repeat_check.setChecked(True)
            panel._seek_to_repeat_start = lambda: calls.append(True)

            panel._maybe_restart_repeat(2, 0.5, True)
            self.assertEqual(calls, [])

            panel._maybe_restart_repeat(2, 0.99, True)
            self.assertEqual(calls, [True])
        finally:
            panel.close()

    def test_songsterr_repeat_preserves_range_during_playback_sync(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            window.top_tabs.setCurrentWidget(window.songsterr_panel)
            window.songsterr_panel.set_selected_measure_range(0, 1, notify=True)
            window.songsterr_panel.repeat_check.setChecked(True)

            window._on_songsterr_playback_position_changed(
                {"measureIndex": 1, "ratio": 0.5, "shouldPlay": True}
            )

            self.assertEqual(window.tab_playback_panel.selected_measure_range(), (0, 1))
            self.assertEqual(window.songsterr_panel.selected_measure_range(), (0, 1))
            self.assertIs(window.fretboard.measure, song.track.measures[1])
        finally:
            window.close()

    def test_songsterr_details_add_top_songsterr_tab(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }

            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)

            index = window.top_tabs.indexOf(window.songsterr_panel)
            self.assertGreaterEqual(index, 0)
            self.assertEqual(window.top_tabs.tabText(index), "Songsterr")
            self.assertEqual(window.songsterr_panel.current_url(), details["songsterr"]["url"])
        finally:
            window.close()

    def test_songsterr_tab_is_removed_for_non_songsterr_files(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            self.assertGreaterEqual(window.top_tabs.indexOf(window.songsterr_panel), 0)

            with patch("tab_analyzer.ui.load_details_file", return_value={}):
                window._set_current_song(song)

            self.assertEqual(window.top_tabs.indexOf(window.songsterr_panel), -1)
            self.assertEqual(window.songsterr_tab_index, -1)
            self.assertEqual(window.songsterr_panel.current_url(), "")
        finally:
            window.close()

    def test_songsterr_playback_position_updates_fretboard_scale_and_tick(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            window.top_tabs.setCurrentWidget(window.songsterr_panel)

            window._on_songsterr_playback_position_changed(
                {"measureIndex": 1, "ratio": 0.5, "shouldPlay": True}
            )

            self.assertIs(window.fretboard.measure, song.track.measures[1])
            self.assertEqual(window.fretboard.kind, "scale")
            self.assertEqual(window.fretboard.candidate, song.track.measures[1].analysis.scale_candidates[0])
            self.assertEqual(window.fretboard.playback_tick, song.track.measures[1].start_tick + 1920)
        finally:
            window.close()

    def test_songsterr_paused_position_selects_measure_without_playback_tick(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            window.top_tabs.setCurrentWidget(window.songsterr_panel)
            window.fretboard.set_playback_tick(1234)

            window._on_songsterr_playback_position_changed(
                {"measureIndex": 0, "ratio": 0.25, "shouldPlay": False}
            )

            self.assertIs(window.fretboard.measure, song.track.measures[0])
            self.assertEqual(window.tab_playback_panel.current_measure_index(), 0)
            self.assertEqual(window.tab_canvas.selected_measure_index, 0)
            self.assertIsNone(window.fretboard.playback_tick)
        finally:
            window.close()

    def test_songsterr_playback_time_overrides_stale_measure_state(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            window.top_tabs.setCurrentWidget(window.songsterr_panel)

            window._on_songsterr_playback_position_changed(
                {"measureIndex": 0, "ratio": 0.0, "cursorMs": 2100, "shouldPlay": True, "source": "time"}
            )

            self.assertIs(window.fretboard.measure, song.track.measures[1])
            self.assertEqual(window.fretboard.playback_tick, song.track.measures[1].start_tick + 192)
        finally:
            window.close()

    def test_songsterr_playback_tick_interpolates_between_web_polls(self):
        with patch("tab_analyzer.ui.SongsterrPagePanel._load_web_engine", return_value=False):
            window = TabAnalyzerWindow()
        try:
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            details = {
                "source": "songsterr",
                "songsterr": {
                    "song_id": 270,
                    "url": "https://www.songsterr.com/a/wsa/queen-bohemian-rhapsody-tab-s270",
                },
            }
            with patch("tab_analyzer.ui.load_details_file", return_value=details):
                window._set_current_song(song)
            window.top_tabs.setCurrentWidget(window.songsterr_panel)

            window._on_songsterr_playback_position_changed(
                {"measureIndex": 0, "ratio": 0.0, "shouldPlay": True, "speed": 150, "source": "layout"}
            )

            self.assertEqual(window.fretboard.playback_tick, song.track.measures[0].start_tick)
            self.assertEqual(window._songsterr_interpolated_playback_tick(50), song.track.measures[0].start_tick + 144)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
