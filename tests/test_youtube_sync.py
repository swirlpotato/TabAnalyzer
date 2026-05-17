import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

import tab_analyzer.ui.tab_playback_panel as tab_playback_panel
from tab_analyzer.youtube_sync import (
    AUTO_SYNC_PRE_ROLL_SECONDS,
    AUTO_SYNC_SEARCH_RADIUS_SECONDS,
    expected_tab_onsets,
    estimate_sync_offset,
    round_sync_milliseconds,
)
from tab_analyzer.ui import TabPlaybackPanel
from tests.helpers import beat, measure, song_with_measures, tab_note


class YouTubeSyncAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rounds_sync_values_to_100_ms(self):
        self.assertEqual(round_sync_milliseconds(49), 0)
        self.assertEqual(round_sync_milliseconds(50), 100)
        self.assertEqual(round_sync_milliseconds(-149), -100)
        self.assertEqual(round_sync_milliseconds(-150), -200)

    def test_sync_estimate_handles_large_audio_onset_shift(self):
        song = song_with_measures(
            (
                measure(
                    1,
                    (
                        beat(0, (tab_note(1, 0, 0),)),
                        beat(480, (tab_note(2, 0, 480),)),
                        beat(960, (tab_note(3, 0, 960),)),
                        beat(1440, (tab_note(4, 0, 1440),)),
                        beat(1920, (tab_note(5, 0, 1920),)),
                        beat(2400, (tab_note(6, 0, 2400),)),
                        beat(2880, (tab_note(1, 3, 2880),)),
                        beat(3360, (tab_note(2, 3, 3360),)),
                    ),
                ),
            )
        )
        sample_rate = 48000
        play_seconds = 4.0
        shift_seconds = 4.0
        duration_seconds = AUTO_SYNC_PRE_ROLL_SECONDS + play_seconds + AUTO_SYNC_SEARCH_RADIUS_SECONDS
        samples = np.zeros(int(sample_rate * duration_seconds), dtype=np.float32)
        for onset in expected_tab_onsets(song, 0, play_seconds):
            center = int((onset + shift_seconds) * sample_rate)
            for index in range(max(0, center - 120), min(samples.size, center + 360)):
                distance = index - center
                envelope = math.exp(-(distance / 95.0) ** 2)
                samples[index] += 0.8 * envelope * math.sin((2 * math.pi * 440.0 * index) / sample_rate)

        estimate = estimate_sync_offset(samples, sample_rate, song, 0, play_seconds, 0)

        self.assertEqual(estimate.suggested_offset_ms, 4000)
        self.assertGreaterEqual(estimate.confidence, 0.16)

    def test_tab_playback_probe_plays_extra_audio_for_large_positive_offsets(self):
        with patch("tab_analyzer.ui.YouTubeTabPlayer._load_web_engine", return_value=None):
            panel = TabPlaybackPanel()
        try:
            song = song_with_measures(
                tuple(
                    measure(index, (beat(0, (tab_note(1, index % 5, 0),)),))
                    for index in range(1, 13)
                )
            )
            panel.set_song(song)
            panel.set_selected_measure_range(0, 0)

            start, end, play_seconds = panel._youtube_sync_probe_range()

            self.assertEqual(start, 0)
            self.assertGreater(end, 3)
            self.assertAlmostEqual(play_seconds, 8.0)
        finally:
            panel.shutdown()
            panel.close()

    def test_tab_playback_sync_ui_uses_100_ms_steps(self):
        with patch("tab_analyzer.ui.YouTubeTabPlayer._load_web_engine", return_value=None):
            panel = TabPlaybackPanel()
        try:
            self.assertEqual(panel.youtube_sync_spin.singleStep(), 100)
            panel.youtube_sync_spin.setValue(125)
            self.assertEqual(panel.youtube_sync_spin.value(), 100)
            panel._adjust_youtube_sync(100)
            self.assertEqual(panel.youtube_sync_spin.value(), 200)
        finally:
            panel.shutdown()
            panel.close()

    def test_auto_sync_progress_dialog_is_application_modal(self):
        with patch("tab_analyzer.ui.YouTubeTabPlayer._load_web_engine", return_value=None):
            panel = TabPlaybackPanel()
        try:
            panel._show_youtube_sync_progress("Preparing audio capture.")

            self.assertIsNotNone(panel._youtube_sync_progress_dialog)
            assert panel._youtube_sync_progress_dialog is not None
            self.assertEqual(
                panel._youtube_sync_progress_dialog.windowModality(),
                Qt.WindowModality.ApplicationModal,
            )
            self.assertTrue(panel._youtube_sync_progress_dialog.isModal())

            panel._on_youtube_sync_capture_started()
            self.assertEqual(panel._youtube_sync_progress_dialog.progress_bar.value(), 25)
            self.assertEqual(panel._youtube_sync_progress_dialog.detail_label.text(), "Capturing YouTube audio. Please wait.")
        finally:
            panel.shutdown()
            panel.close()

    def test_tab_playback_panel_imports_youtube_sync_worker(self):
        self.assertIs(tab_playback_panel._YouTubeSyncWorker, __import__("tab_analyzer.ui.workers", fromlist=["_YouTubeSyncWorker"])._YouTubeSyncWorker)


if __name__ == "__main__":
    unittest.main()
