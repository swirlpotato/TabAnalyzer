import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tab_analyzer.ui import TabAnalyzerWindow
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


if __name__ == "__main__":
    unittest.main()
