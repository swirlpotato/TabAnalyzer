import unittest
from dataclasses import replace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tab_analyzer import midi_player
from tab_analyzer.midi_player import (
    DRUM_CHANNEL,
    METRONOME_ACCENT_NOTE,
    MIN_AUDIBLE_DRUM_MS,
    MIN_AUDIBLE_MUTED_NOTE_MS,
    MIN_AUDIBLE_NOTE_MS,
    NOTE_RELEASE_GAP_TICKS,
    POSITION_UPDATE_INTERVAL_MS,
    PlaybackEvent,
    TabMidiPlayer,
    advance_song_tick_by_milliseconds,
    _metronome_events,
    _note_events,
    song_seconds_between_ticks,
)
from tab_analyzer.gp_loader import TempoChange
from tests.helpers import beat, measure, song_with_measures, tab_note


class FakeMidiOutput:
    available = True
    error = ""

    def __init__(self):
        self.calls: list[tuple[str, int | None, int | None, int | None]] = []

    def note_on(self, note: int, velocity: int, channel: int = 0) -> None:
        self.calls.append(("on", note, velocity, channel))

    def note_off(self, note: int, channel: int = 0) -> None:
        self.calls.append(("off", note, None, channel))

    def all_notes_off(self) -> None:
        self.calls.append(("all_off", None, None, None))

    def close(self) -> None:
        self.calls.append(("close", None, None, None))


class MidiPlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_short_note_events_keep_duration_on_note_on(self):
        note = replace(tab_note(1, 12), duration_ticks=20)
        events = _note_events(note, 3840)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, "note_on")
        self.assertEqual(events[0].duration_ticks, 40)
        self.assertEqual(events[0].string, 1)

    def test_note_duration_is_capped_before_next_note_on_same_string(self):
        note = replace(tab_note(1, 12), duration_ticks=480)
        events = _note_events(note, 3840, next_string_tick=60)

        self.assertEqual(events[0].duration_ticks, 60 - NOTE_RELEASE_GAP_TICKS)

    def test_metronome_events_use_scheduled_note_duration(self):
        measure_data = measure(1, ())
        events = _metronome_events(measure_data)

        self.assertTrue(events)
        self.assertTrue(all(event.kind == "note_on" for event in events))
        self.assertEqual(events[0].note, METRONOME_ACCENT_NOTE)
        self.assertEqual(events[0].channel, DRUM_CHANNEL)
        self.assertEqual(events[0].duration_ticks, 80)

    def test_note_off_is_delayed_and_stale_offs_are_ignored(self):
        scheduled: list[tuple[int, object]] = []
        original_single_shot = midi_player._single_shot
        midi_player._single_shot = lambda milliseconds, callback: scheduled.append((milliseconds, callback))
        player = TabMidiPlayer()
        player.output.close()
        fake_output = FakeMidiOutput()
        player.output = fake_output
        player._ticks_per_ms = 100.0
        try:
            event = PlaybackEvent(0, "note_on", 60, 100, duration_ticks=1)

            player._send_event(event)
            first_generation = player._active_note_generations[(0, 60)]
            player._send_event(event)
            second_generation = player._active_note_generations[(0, 60)]

            self.assertEqual(
                fake_output.calls,
                [("on", 60, 100, 0), ("off", 60, None, 0), ("on", 60, 100, 0)],
            )
            self.assertEqual(scheduled[0][0], MIN_AUDIBLE_NOTE_MS)
            self.assertNotEqual(first_generation, second_generation)

            scheduled[0][1]()
            self.assertEqual(fake_output.calls[-1], ("on", 60, 100, 0))

            scheduled[1][1]()
            self.assertEqual(fake_output.calls[-1], ("off", 60, None, 0))
        finally:
            midi_player._single_shot = original_single_shot
            player.close()

    def test_next_note_on_same_string_stops_previous_pitch(self):
        scheduled: list[tuple[int, object]] = []
        original_single_shot = midi_player._single_shot
        midi_player._single_shot = lambda milliseconds, callback: scheduled.append((milliseconds, callback))
        player = TabMidiPlayer()
        player.output.close()
        fake_output = FakeMidiOutput()
        player.output = fake_output
        player._ticks_per_ms = 1.0
        try:
            player._send_event(PlaybackEvent(0, "note_on", 60, 100, duration_ticks=120, string=1))
            player._send_event(PlaybackEvent(60, "note_on", 62, 100, duration_ticks=120, string=1))

            self.assertEqual(
                fake_output.calls,
                [("on", 60, 100, 0), ("off", 60, None, 0), ("on", 62, 100, 0)],
            )
        finally:
            midi_player._single_shot = original_single_shot
            player.close()

    def test_minimum_audible_duration_depends_on_event_type(self):
        player = TabMidiPlayer()
        player.output.close()
        player.output = FakeMidiOutput()
        player._ticks_per_ms = 100.0
        try:
            self.assertEqual(
                player._event_duration_ms(PlaybackEvent(0, "note_on", 60, 100, duration_ticks=1)),
                MIN_AUDIBLE_NOTE_MS,
            )
            self.assertEqual(
                player._event_duration_ms(PlaybackEvent(0, "note_on", 60, 34, duration_ticks=1)),
                MIN_AUDIBLE_MUTED_NOTE_MS,
            )
            self.assertEqual(
                player._event_duration_ms(PlaybackEvent(0, "note_on", 76, 100, duration_ticks=1, channel=DRUM_CHANNEL)),
                MIN_AUDIBLE_DRUM_MS,
            )
        finally:
            player.close()

    def test_position_updates_are_throttled_independently_from_midi_ticks(self):
        class FakeClock:
            def __init__(self, values: list[int]) -> None:
                self.values = values

            def restart(self) -> int:
                return self.values.pop(0)

        player = TabMidiPlayer()
        player.output.close()
        player.output = FakeMidiOutput()
        song = song_with_measures((measure(1, (beat(0, (tab_note(1, 5, 0),)),)),))
        emitted: list[int] = []
        player.positionChanged.connect(emitted.append)
        player.song = song
        player.playing = True
        player.speed_percent = 100
        player.start_tick = 0
        player.end_tick = song.track.measures[0].start_tick + song.track.measures[0].length_ticks
        player.events = []
        player.clock = FakeClock([12, 12, POSITION_UPDATE_INTERVAL_MS - 24])
        try:
            player._tick()
            player._tick()
            self.assertEqual(emitted, [])

            player._tick()
            self.assertEqual(len(emitted), 1)
        finally:
            player.close()

    def test_tempo_map_advances_ticks_through_tempo_changes(self):
        song = song_with_measures(
            (measure(1, ()),),
            tempo=120,
            tempo_changes=(TempoChange(0, 120), TempoChange(960, 240)),
        )

        self.assertEqual(advance_song_tick_by_milliseconds(song, 0, 500), 960)
        self.assertEqual(advance_song_tick_by_milliseconds(song, 960, 250), 1920)
        self.assertEqual(advance_song_tick_by_milliseconds(song, 0, 750), 1920)
        self.assertAlmostEqual(song_seconds_between_ticks(song, 0, 1920), 0.75)


if __name__ == "__main__":
    unittest.main()
