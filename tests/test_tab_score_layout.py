import os
import unittest
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import QApplication

from tab_analyzer.i18n import tr
from tab_analyzer.scale_blocks import ScaleBlock
from tab_analyzer.ui import ABOUT_URL, ChordFinderWidget, FretboardWidget, TabPlaybackPanel, TabScoreWidget, _MeasureLayout
from tab_analyzer.ui import _about_html, _open_external_url
from tab_analyzer.ui import _ChordFinderSearchParams, _chord_finder_search_results
from tab_analyzer.ui import YOUTUBE_VIEW_HEIGHT, YOUTUBE_VIEW_PIP_MARGIN, YOUTUBE_VIEW_WIDTH
from tests.helpers import C_MAJOR, STANDARD_TUNING, beat, measure, song_with_measures, tab_note


class FakeMetronome:
    def __init__(self) -> None:
        self.bpm = None
        self.beats_per_bar = None
        self.ticking = False
        self.started = 0
        self.stopped = 0
        self.closed = 0

    def set_bpm(self, bpm: int) -> None:
        self.bpm = bpm

    def set_beats_per_bar(self, beats: int) -> None:
        self.beats_per_bar = beats

    def start(self) -> None:
        self.ticking = True
        self.started += 1

    def stop(self) -> None:
        self.ticking = False
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1


class FakeWebPage:
    def runJavaScript(self, _script: str) -> None:
        return


class FakePipView:
    def __init__(self) -> None:
        self.geometry = None
        self.raised = False
        self.visible = None
        self._page = FakeWebPage()

    def setGeometry(self, x: int, y: int, width: int, height: int) -> None:
        self.geometry = (x, y, width, height)

    def raise_(self) -> None:
        self.raised = True

    def setVisible(self, visible: bool) -> None:
        self.visible = visible

    def page(self) -> FakeWebPage:
        return self._page


class AboutDialogTests(unittest.TestCase):
    def test_about_html_turns_project_url_into_link(self):
        rendered = _about_html("1.2.3", ABOUT_URL)

        self.assertIn("1.2.3", rendered)
        self.assertIn(f'href="{ABOUT_URL}"', rendered)
        self.assertIn(f">{ABOUT_URL}</a>", rendered)

    def test_open_external_url_uses_qdesktopservices(self):
        with patch("tab_analyzer.ui.QDesktopServices.openUrl", return_value=True) as open_url:
            self.assertTrue(_open_external_url(ABOUT_URL))

        target = open_url.call_args.args[0]
        self.assertEqual(target.toString(), ABOUT_URL)


class FakeTechniquePainter:
    def __init__(self) -> None:
        self._pen = QPen(QColor("#111111"), 1)
        self.path_pen_widths: list[float] = []

    def save(self) -> None:
        return

    def restore(self) -> None:
        return

    def pen(self):
        return self._pen

    def setPen(self, pen) -> None:
        if isinstance(pen, QPen):
            self._pen = pen

    def setBrush(self, _brush) -> None:
        return

    def drawPath(self, _path) -> None:
        self.path_pen_widths.append(self._pen.widthF())


class TabScoreLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sequential_notes_keep_spacing_across_strings(self):
        measure_data = measure(
            14,
            (
                beat(0, (tab_note(4, 11, 0), tab_note(5, 9, 0))),
                beat(960, (tab_note(1, 13, 960),)),
                beat(1200, (tab_note(1, 14, 1200),)),
                beat(1440, (tab_note(1, 13, 1440),)),
                beat(1680, (tab_note(2, 15, 1680),)),
                beat(1920, (tab_note(2, 14, 1920),)),
            ),
        )
        widget = TabScoreWidget()
        positions = widget._note_positions(measure_data, 54, 475, 100, 13)

        by_start = {
            (beat_data.start_in_measure, note.string, note.fret): x
            for x, _y, note, beat_data in positions
        }

        self.assertGreaterEqual(
            by_start[(1680, 2, 15)] - by_start[(1440, 1, 13)],
            24,
        )

    def test_chord_notes_stay_aligned(self):
        measure_data = measure(
            1,
            (
                beat(0, (tab_note(4, 11, 0), tab_note(5, 9, 0))),
                beat(960, (tab_note(1, 13, 960),)),
            ),
        )
        widget = TabScoreWidget()
        positions = widget._note_positions(measure_data, 54, 475, 100, 13)
        chord_x = {
            note.string: x
            for x, _y, note, beat_data in positions
            if beat_data.start_in_measure == 0
        }

        self.assertEqual(chord_x[4], chord_x[5])

    def test_tied_same_notes_hide_repeated_tab_numbers(self):
        first_note = tab_note(5, 5, 0)
        new_note = tab_note(4, 7, 960)
        tied_note = replace(tab_note(5, 5, 960), techniques=("tie",))
        measure_data = measure(
            79,
            (
                beat(0, (first_note,)),
                beat(960, (new_note, tied_note)),
            ),
        )
        widget = TabScoreWidget()

        hidden_note_ids = widget._hidden_tied_note_ids(measure_data)

        self.assertEqual(widget._tab_note_text(first_note, hidden_note_ids), "5")
        self.assertEqual(widget._tab_note_text(new_note, hidden_note_ids), "7")
        self.assertEqual(widget._tab_note_text(tied_note, hidden_note_ids), "")

    def test_rhythm_notation_counts_beams_from_duration(self):
        widget = TabScoreWidget()

        self.assertEqual(widget._rhythm_beam_count(960), 0)
        self.assertEqual(widget._rhythm_beam_count(480), 1)
        self.assertEqual(widget._rhythm_beam_count(240), 2)
        self.assertEqual(widget._rhythm_beam_count(120), 3)

    def test_triplet_duration_gets_tuplet_label(self):
        widget = TabScoreWidget()

        self.assertEqual(widget._tuplet_label_for_duration(320), "3")
        self.assertEqual(widget._tuplet_label_for_duration(160), "3")
        self.assertIsNone(widget._tuplet_label_for_duration(240))

    def test_tuplet_groups_include_start_and_end_positions(self):
        widget = TabScoreWidget()
        beats = [
            replace(beat(0, (tab_note(1, 12, 0),)), duration_ticks=320),
            replace(beat(320, (tab_note(1, 14, 320),)), duration_ticks=320),
            replace(beat(640, (tab_note(1, 15, 640),)), duration_ticks=320),
            beat(960, (tab_note(2, 15, 960),)),
        ]

        groups = widget._tuplet_groups([(100, beats[0]), (140, beats[1]), (180, beats[2]), (240, beats[3])])

        self.assertEqual(groups, [("3", 100, 180)])

    def test_tuplet_groups_omit_connected_adjacent_triplets(self):
        widget = TabScoreWidget()
        beats = [
            replace(beat(index * 320, (tab_note(1, 12 + index, index * 320),)), duration_ticks=320)
            for index in range(6)
        ]

        groups = widget._tuplet_groups([(100 + (index * 40), beat_data) for index, beat_data in enumerate(beats)])

        self.assertEqual(groups, [("3", 100, 180), ("3", 220, 300)])

    def test_tuplet_groups_keep_single_sextuplet_group(self):
        widget = TabScoreWidget()
        beats = [
            replace(beat(index * 80, (tab_note(1, 12 + index, index * 80),)), duration_ticks=80, tuplet=(6, 4))
            for index in range(6)
        ]

        groups = widget._tuplet_groups([(100 + (index * 20), beat_data) for index, beat_data in enumerate(beats)])

        self.assertEqual(groups, [("6", 100, 200)])

    def test_tuplet_groups_keep_connected_sextuplet_run_from_songsterr_fixture(self):
        widget = TabScoreWidget()
        beats = [
            replace(beat(index * 80, (tab_note(1, 12 + index, index * 80),)), duration_ticks=80, tuplet=(6, 4))
            for index in range(12)
        ]

        groups = widget._tuplet_groups([(100 + (index * 20), beat_data) for index, beat_data in enumerate(beats)])

        self.assertEqual(groups, [("6", 100, 200), ("6", 220, 320)])

    def test_rhythm_beam_runs_split_on_four_four_quarter_boundaries(self):
        widget = TabScoreWidget()
        beats = [
            replace(beat(0, (tab_note(1, 8, 0),)), duration_ticks=240),
            replace(beat(240, (tab_note(1, 12, 240),)), duration_ticks=120),
            replace(beat(360, (tab_note(1, 8, 360),)), duration_ticks=120),
            replace(beat(480, (tab_note(2, 10, 480),)), duration_ticks=240),
            replace(beat(720, (tab_note(3, 9, 720),)), duration_ticks=240),
            replace(beat(960, (tab_note(2, 12, 960),)), duration_ticks=240),
            replace(beat(1200, (tab_note(2, 10, 1200),)), duration_ticks=240),
            replace(beat(1440, (tab_note(3, 9, 1440),)), duration_ticks=240),
            replace(beat(1680, (tab_note(4, 10, 1680),)), duration_ticks=240),
            *[
                replace(beat(1920 + (index * 160), (tab_note(1, 12 + index, 1920 + (index * 160)),)), duration_ticks=160, tuplet=(6, 4))
                for index in range(12)
            ],
        ]
        measure_data = measure(226, tuple(beats))

        runs = widget._rhythm_beam_runs([(100 + index * 20, beat_data) for index, beat_data in enumerate(beats)], measure_data)
        starts_by_run = [[beat_data.start_in_measure for _x, beat_data in run] for run in runs]

        self.assertEqual(
            starts_by_run,
            [
                [0, 240, 360, 480, 720],
                [960, 1200, 1440, 1680],
                [1920, 2080, 2240, 2400, 2560, 2720],
                [2880, 3040, 3200, 3360, 3520, 3680],
            ],
        )

    def test_diminuendo_span_draws_dim_label(self):
        widget = TabScoreWidget()
        dim_note_a = replace(tab_note(1, 12, 0), techniques=("diminuendo",))
        dim_note_b = replace(tab_note(1, 10, 480), techniques=("diminuendo",))
        dim_beat_a = beat(0, (dim_note_a,))
        dim_beat_b = beat(480, (dim_note_b,))
        calls: list[tuple[str, int, int]] = []
        widget._draw_dashed_span_text = lambda _painter, label, start_x, end_x, _y, _color: calls.append((label, start_x, end_x))
        image = QImage(220, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        try:
            widget._draw_technique_spans(painter, [(60, dim_beat_a), (120, dim_beat_b)], 20, 60)
        finally:
            painter.end()

        self.assertEqual(calls, [("dim.", 60, 142)])

    def test_tab_playback_panel_installs_space_toggle_shortcut(self):
        panel = TabPlaybackPanel()
        try:
            shortcuts = {shortcut.key().toString(): shortcut.context() for shortcut in panel.findChildren(QShortcut)}

            self.assertEqual(shortcuts.get("Space"), Qt.ShortcutContext.WidgetWithChildrenShortcut)
        finally:
            panel.shutdown()

    def test_tab_playback_panel_has_no_separate_stop_button(self):
        panel = TabPlaybackPanel()
        try:
            self.assertFalse(hasattr(panel, "stop_button"))
        finally:
            panel.shutdown()

    def test_tab_playback_panel_shows_youtube_before_midi(self):
        panel = TabPlaybackPanel()
        try:
            controls = panel.layout().itemAt(0).layout()

            self.assertIs(controls.itemAt(1).widget(), panel.youtube_radio)
            self.assertIs(controls.itemAt(2).widget(), panel.midi_radio)
        finally:
            panel.shutdown()

    def test_youtube_view_is_positioned_as_score_pip(self):
        panel = TabPlaybackPanel()
        original_view = panel.youtube_player.view
        fake_view = FakePipView()
        try:
            if original_view is not None:
                original_view.hide()
            panel.youtube_player.view = fake_view
            panel.resize(900, 620)
            panel.show()
            self.app.processEvents()

            panel._position_youtube_view()

            viewport = panel.score_scroll.viewport()
            top_left = viewport.mapTo(panel, viewport.rect().topLeft())
            expected_x = top_left.x() + max(0, viewport.width() - YOUTUBE_VIEW_WIDTH - YOUTUBE_VIEW_PIP_MARGIN)
            expected_y = top_left.y() + max(0, viewport.height() - YOUTUBE_VIEW_HEIGHT - YOUTUBE_VIEW_PIP_MARGIN)
            self.assertEqual(fake_view.geometry, (expected_x, expected_y, YOUTUBE_VIEW_WIDTH, YOUTUBE_VIEW_HEIGHT))
            self.assertTrue(fake_view.raised)
        finally:
            panel.youtube_player.view = original_view
            panel.close()
            panel.shutdown()

    def test_playback_scroll_avoids_youtube_pip_when_possible(self):
        panel = TabPlaybackPanel()
        original_view = panel.youtube_player.view
        fake_view = FakePipView()
        try:
            if original_view is not None:
                original_view.hide()
            panel.youtube_player.view = fake_view
            panel.youtube_radio.setEnabled(True)
            panel.youtube_radio.setChecked(True)
            panel.resize(900, 700)
            panel.show()
            song = song_with_measures(
                tuple(
                    measure(index + 1, (beat(0, (tab_note(1, 5, 0),)),))
                    for index in range(80)
                )
            )
            panel.song = song
            panel.score.set_song(song)
            self.app.processEvents()

            viewport = panel.score_scroll.viewport()
            pip_top = max(0, viewport.height() - YOUTUBE_VIEW_HEIGHT - YOUTUBE_VIEW_PIP_MARGIN)
            padding = int(24 * panel.score.zoom)
            layout = _MeasureLayout(0, QRect(viewport.width() - 180, 760, 160, 80))

            panel._scroll_score_layout_into_view(layout)

            expected_minimum = layout.rect.bottom() + padding - pip_top
            self.assertGreaterEqual(panel.score_scroll.verticalScrollBar().value(), expected_minimum)
        finally:
            panel.youtube_player.view = original_view
            panel.close()
            panel.shutdown()

    def test_fretboard_auto_selects_scale_block_with_most_played_notes(self):
        widget = FretboardWidget()
        measure_data = measure(
            1,
            (
                beat(0, (tab_note(2, 10, 0),)),
                beat(480, (tab_note(3, 9, 480),)),
                beat(960, (tab_note(4, 9, 960),)),
                beat(1440, (tab_note(1, 15, 1440),)),
            ),
        )
        widget.measure = measure_data
        blocks = (
            ScaleBlock(0, 14, 16, None, None, 0, ((0, 15),)),
            ScaleBlock(1, 9, 13, None, None, 1, ((1, 10), (2, 9), (3, 9))),
        )

        self.assertEqual(widget._active_scale_block_index(blocks), 1)

    def test_manual_scale_block_selection_still_wins(self):
        widget = FretboardWidget()
        widget.measure = measure(1, (beat(0, (tab_note(2, 10, 0),)),))
        widget.selected_scale_block_index = 0
        blocks = (
            ScaleBlock(0, 14, 16, None, None, 0, ((0, 15),)),
            ScaleBlock(1, 9, 13, None, None, 1, ((1, 10), (2, 9), (3, 9))),
        )

        self.assertEqual(widget._active_scale_block_index(blocks), 0)

    def test_fretboard_tracks_current_playback_notes(self):
        widget = FretboardWidget()
        measure_data = measure(
            1,
            (
                beat(0, (tab_note(1, 5, 0),)),
                beat(480, (tab_note(2, 7, 480),)),
            ),
            scales=(C_MAJOR,),
        )
        widget.set_song(song_with_measures((measure_data,)))
        widget.set_selection(measure_data, C_MAJOR, "scale")

        widget.set_playback_tick(100)
        self.assertEqual([note.fret for note in widget._current_playback_notes()], [5])

        widget.set_playback_tick(600)
        self.assertEqual([note.fret for note in widget._current_playback_notes()], [7])

        widget.set_playback_tick(None)
        self.assertEqual(widget._current_playback_notes(), ())

    def test_bend_symbol_uses_half_size_arrow_shape(self):
        widget = TabScoreWidget()
        widget.zoom = 1.0
        image = QImage(140, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        tips: list[tuple[QPointF, float | None]] = []
        widget._draw_bend_arrow_triangle = lambda _painter, tip, up, scale=None: tips.append((tip, scale))
        try:
            widget._draw_bend_symbol(painter, 20, 60, release=False, semitones=1)
        finally:
            painter.end()

        self.assertEqual(len(tips), 1)
        self.assertLessEqual(tips[0][0].x() - 20, 19)
        self.assertEqual(tips[0][1], 0.5)

    def test_vibrato_symbol_uses_bold_pen(self):
        widget = TabScoreWidget()
        widget.zoom = 1.0
        painter = FakeTechniquePainter()

        widget._draw_technique_symbol(painter, "vibrato", 40, 40)

        self.assertTrue(painter.path_pen_widths)
        self.assertGreaterEqual(painter.path_pen_widths[-1], 2.0)

    def test_chord_finder_ignores_single_selected_note(self):
        result = _chord_finder_search_results(
            _ChordFinderSearchParams(
                note_pcs=(0,),
                selected_positions=((0, 0),),
                root_filter=None,
                type_filter=None,
                string_pitches=STANDARD_TUNING,
                fret_count=24,
            )
        )

        self.assertEqual(result.entries, ())

    def test_chord_finder_searches_after_two_selected_notes(self):
        result = _chord_finder_search_results(
            _ChordFinderSearchParams(
                note_pcs=(0, 4),
                selected_positions=((1, 1), (0, 0)),
                root_filter=0,
                type_filter=None,
                string_pitches=STANDARD_TUNING,
                fret_count=24,
            )
        )

        self.assertTrue(result.entries)
        self.assertTrue(all({0, 4}.issubset(set(match.candidate.pitch_classes)) for match, _position in result.entries))

    def test_chord_finder_widget_starts_background_search(self):
        widget = ChordFinderWidget()
        started: list[_ChordFinderSearchParams] = []
        widget._start_chord_search = lambda params: started.append(params)  # type: ignore[method-assign]
        widget.selected_positions = [(1, 1), (0, 0)]

        widget._rebuild_matches()

        self.assertTrue(widget._searching)
        self.assertEqual(len(started), 1)

    def test_chord_finder_widget_does_not_search_single_note(self):
        widget = ChordFinderWidget()
        started: list[_ChordFinderSearchParams] = []
        widget._start_chord_search = lambda params: started.append(params)  # type: ignore[method-assign]
        widget.selected_positions = [(1, 1)]

        widget._rebuild_matches()

        self.assertFalse(widget._searching)
        self.assertEqual(started, [])

    def test_chord_finder_open_position_has_no_zero_fret_cell(self):
        widget = ChordFinderWidget()
        board = QRect(100, 20, 80, 40)
        fret_gap = board.width() / 4

        self.assertEqual(list(widget._match_visible_fret_labels(0, 3)), [1, 2, 3, 4])
        self.assertEqual(widget._match_fret_center_x(board, fret_gap, 0, 0), 100)
        self.assertEqual(widget._match_fret_center_x(board, fret_gap, 1, 0), 110)

    def test_tab_playback_defaults_to_youtube_when_available(self):
        panel = TabPlaybackPanel()
        try:
            panel.youtube_player.available = True
            panel.youtube_player._load_video = lambda _video_id, _status_message="": None
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))

            with patch(
                "tab_analyzer.ui.load_details_file",
                return_value={"youtube": {"default_video_id": "abc123", "sync": {}}},
            ):
                panel.set_song(song)

            self.assertTrue(panel.youtube_radio.isEnabled())
            self.assertTrue(panel.youtube_radio.isChecked())
            self.assertFalse(panel.midi_radio.isChecked())
        finally:
            panel.shutdown()

    def test_tab_playback_uses_midi_when_youtube_is_missing(self):
        panel = TabPlaybackPanel()
        try:
            panel.youtube_player.available = True
            panel.youtube_player._load_video = lambda _video_id, _status_message="": None
            song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            with patch(
                "tab_analyzer.ui.load_details_file",
                return_value={"youtube": {"default_video_id": "abc123", "sync": {}}},
            ):
                panel.set_song(song)
            self.assertTrue(panel.youtube_radio.isChecked())

            with patch("tab_analyzer.ui.load_details_file", return_value={}):
                panel.set_song(song)

            self.assertFalse(panel.youtube_radio.isEnabled())
            self.assertTrue(panel.midi_radio.isChecked())
        finally:
            panel.shutdown()

    def test_youtube_embed_error_switches_to_next_video_candidate(self):
        panel = TabPlaybackPanel()
        loaded: list[str] = []
        try:
            panel.youtube_player.available = True
            panel.youtube_player.playback_available = True
            panel.youtube_player.video_id = "bad"
            panel.youtube_player._loaded_video_id = "bad"
            panel.youtube_player._video_candidates = ["bad", "good"]
            panel.youtube_player._load_video = lambda video_id, _status_message="": loaded.append(video_id) or False

            panel.youtube_player._handle_youtube_error("150")

            self.assertEqual(panel.youtube_player.video_id, "good")
            self.assertEqual(loaded, ["good"])
            self.assertTrue(panel.youtube_player.playback_available)
            self.assertTrue(panel.youtube_radio.isEnabled())
            self.assertEqual(panel.youtube_status_label.text(), tr("YouTube OK - {video_id}").format(video_id="good"))
        finally:
            panel.shutdown()

    def test_youtube_embed_error_disables_youtube_when_no_candidates_remain(self):
        panel = TabPlaybackPanel()
        try:
            panel.youtube_player.available = True
            panel.youtube_player.playback_available = True
            panel.youtube_player.video_id = "bad"
            panel.youtube_player._loaded_video_id = "bad"
            panel.youtube_player._video_candidates = ["bad"]
            panel.youtube_radio.setEnabled(True)
            panel.youtube_radio.setChecked(True)

            panel.youtube_player._handle_youtube_error("150")

            self.assertFalse(panel.youtube_player.playback_available)
            self.assertFalse(panel.youtube_radio.isEnabled())
            self.assertTrue(panel.midi_radio.isChecked())
            self.assertEqual(panel.youtube_status_label.text(), tr("YouTube unavailable"))
        finally:
            panel.shutdown()

    def test_youtube_ready_promotes_successful_video_in_details_file(self):
        panel = TabPlaybackPanel()
        try:
            panel.song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            panel.details = {
                "youtube": {
                    "default_video_id": "bad",
                    "videos": [
                        {"video_id": "bad", "url": "https://www.youtube.com/watch?v=bad"},
                        {"video_id": "good", "url": "https://www.youtube.com/watch?v=good"},
                    ],
                }
            }

            with patch("tab_analyzer.ui.save_details_file") as save_details:
                panel._on_youtube_video_ready("good")

            self.assertEqual(panel.details["youtube"]["default_video_id"], "good")
            self.assertEqual([video["video_id"] for video in panel.details["youtube"]["videos"]], ["good", "bad"])
            save_details.assert_called_once_with(panel.song.path, panel.details)
        finally:
            panel.shutdown()

    def test_youtube_sync_control_updates_player_and_details_file(self):
        panel = TabPlaybackPanel()
        offsets: list[int] = []
        try:
            panel.song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
            panel.details = {"youtube": {"default_video_id": "abc123", "sync": {"offset_seconds": 0.0}}}
            panel.youtube_player.set_offset_milliseconds = offsets.append  # type: ignore[method-assign]

            with patch("tab_analyzer.ui.save_details_file") as save_details:
                panel.youtube_sync_spin.setValue(125)

            self.assertEqual(offsets[-1], 100)
            self.assertEqual(panel.details["youtube"]["sync"]["offset_seconds"], 0.1)
            save_details.assert_called_once_with(panel.song.path, panel.details)
        finally:
            panel.shutdown()

    def test_speed_buttons_adjust_and_reset_speed(self):
        panel = TabPlaybackPanel()
        try:
            panel.speed_slider.setValue(100)

            panel.speed_up_button.click()
            self.assertEqual(panel.speed_slider.value(), 101)

            panel.speed_down_button.click()
            self.assertEqual(panel.speed_slider.value(), 100)

            panel.speed_slider.setValue(137)
            panel.speed_reset_button.click()
            self.assertEqual(panel.speed_slider.value(), 100)
        finally:
            panel.shutdown()

    def test_tab_playback_emits_measure_changes_during_playback(self):
        panel = TabPlaybackPanel()
        try:
            song = song_with_measures(
                (
                    measure(1, (beat(0, (tab_note(1, 5, 0),)),)),
                    measure(2, (beat(0, (tab_note(1, 7, 0),)),)),
                )
            )
            panel.song = song
            panel.score.set_song(song)
            changed: list[int] = []
            ticks: list[object] = []
            scrolled: list[int] = []
            panel.playbackMeasureChanged.connect(changed.append)
            panel.playbackTickChanged.connect(ticks.append)
            panel._scroll_playback_measure_into_view = scrolled.append

            panel._on_playback_position_changed(song.track.measures[0].start_tick)
            panel._on_playback_position_changed(song.track.measures[0].start_tick + 480)
            panel._on_playback_position_changed(song.track.measures[1].start_tick)

            self.assertEqual(changed, [0, 1])
            self.assertEqual(ticks, [song.track.measures[0].start_tick, song.track.measures[0].start_tick + 480, song.track.measures[1].start_tick])
            self.assertEqual(scrolled, [song.track.measures[0].start_tick, song.track.measures[1].start_tick])
        finally:
            panel.shutdown()

    def test_youtube_metronome_starts_with_youtube_playback(self):
        panel = TabPlaybackPanel()
        fake = FakeMetronome()
        try:
            panel.tab_metronome.close()
            panel.tab_metronome = fake
            panel.song = replace(
                song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),)),
                tempo=90,
            )
            panel.youtube_radio.setEnabled(True)
            panel.youtube_radio.setChecked(True)
            panel.youtube_player.playing = True
            panel.speed_slider.setValue(150)

            panel.metronome_check.setChecked(True)

            self.assertTrue(fake.ticking)
            self.assertEqual(fake.started, 1)
            self.assertEqual(fake.bpm, 135)
            self.assertEqual(fake.beats_per_bar, 4)
        finally:
            panel.shutdown()

    def test_youtube_metronome_tracks_speed_and_stops_with_youtube(self):
        panel = TabPlaybackPanel()
        fake = FakeMetronome()
        try:
            panel.tab_metronome.close()
            panel.tab_metronome = fake
            panel.song = replace(
                song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),)),
                tempo=90,
            )
            panel.youtube_radio.setEnabled(True)
            panel.youtube_radio.setChecked(True)
            panel.youtube_player.playing = True
            panel.metronome_check.setChecked(True)

            panel.speed_slider.setValue(50)
            self.assertEqual(fake.bpm, 45)
            self.assertEqual(fake.started, 1)

            panel.youtube_player.playing = False
            panel._on_playing_changed(False)
            self.assertFalse(fake.ticking)
            self.assertGreaterEqual(fake.stopped, 1)
        finally:
            panel.shutdown()

    def test_slide_relationships_do_not_connect_to_next_note(self):
        widget = TabScoreWidget()
        first_note = replace(tab_note(1, 5, 0), techniques=("slide",))
        second_note = tab_note(1, 7, 480)
        first_beat = beat(0, (first_note,))
        second_beat = beat(480, (second_note,))
        calls: list[str] = []
        widget._draw_slide_connection = lambda *_args, **_kwargs: calls.append("connect")
        widget._draw_slide_out = lambda *_args, **_kwargs: calls.append("out")
        image = QImage(220, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        font = QFont("Consolas", 11, QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        try:
            widget._draw_note_relationships(
                painter,
                [(60, 40, first_note, first_beat), (140, 40, second_note, second_beat)],
                metrics,
            )
        finally:
            painter.end()

        self.assertEqual(calls, [])

    def test_slide_symbol_is_drawn_before_slide_destination(self):
        widget = TabScoreWidget()
        first_note = replace(tab_note(1, 10, 0), techniques=("slide",))
        second_note = tab_note(1, 20, 480)
        first_beat = beat(0, (first_note,))
        second_beat = beat(480, (second_note,))
        image = QImage(220, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        font = QFont("Consolas", 11, QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        calls: list[tuple[int, int]] = []
        widget._draw_slide_mark = lambda _painter, x, y: calls.append((x, y))
        try:
            widget._draw_note_relationships(
                painter,
                [(60, 40, first_note, first_beat), (140, 40, second_note, second_beat)],
                metrics,
            )
        finally:
            painter.end()

        self.assertEqual(len(calls), 1)
        self.assertGreater(calls[0][0], 60)
        self.assertLess(calls[0][0], 140)

    def test_legato_run_draws_one_continuous_slur(self):
        widget = TabScoreWidget()
        first_note = tab_note(1, 8, 0)
        second_note = replace(tab_note(1, 12, 240), techniques=("hammer_on",))
        third_note = replace(tab_note(1, 8, 360), techniques=("pull_off",))
        first_beat = beat(0, (first_note,))
        second_beat = beat(240, (second_note,))
        third_beat = beat(360, (third_note,))
        image = QImage(240, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        font = QFont("Consolas", 11, QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        calls: list[tuple[int, int, int, int]] = []
        widget._draw_slur_connection = lambda _painter, left_x, left_y, right_x, right_y, _label: calls.append((left_x, left_y, right_x, right_y))
        try:
            widget._draw_note_relationships(
                painter,
                [(60, 40, first_note, first_beat), (110, 40, second_note, second_beat), (160, 40, third_note, third_beat)],
                metrics,
            )
        finally:
            painter.end()

        self.assertEqual(calls, [(60, 40, 160, 40)])

    def test_slide_source_note_does_not_draw_own_symbol(self):
        widget = TabScoreWidget()
        note = replace(tab_note(1, 10, 0), techniques=("slide",))
        image = QImage(220, 80, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        font = QFont("Consolas", 11, QFont.Weight.DemiBold)
        metrics = QFontMetrics(font)
        calls: list[tuple[int, int]] = []
        widget._draw_slide_mark = lambda _painter, x, y: calls.append((x, y))
        try:
            widget._draw_note_technique_symbols(painter, note, 100, 40, metrics)
        finally:
            painter.end()

        self.assertEqual(calls, [])

    def test_palm_mute_spans_consecutive_beats(self):
        muted_a = replace(tab_note(6, 0, 0), techniques=("palm_mute",))
        muted_b = replace(tab_note(6, 2, 480), techniques=("palm_mute",))
        open_note = tab_note(6, 3, 960)
        measure_data = measure(
            1,
            (
                beat(0, (muted_a,)),
                beat(480, (muted_b,)),
                beat(960, (open_note,)),
            ),
        )
        widget = TabScoreWidget()
        positions = widget._note_positions(measure_data, 54, 475, 100, 13)
        spans = widget._technique_spans(widget._beat_positions(positions), "palm_mute")

        self.assertEqual(len(spans), 1)
        self.assertLess(spans[0][0], spans[0][1])


if __name__ == "__main__":
    unittest.main()
