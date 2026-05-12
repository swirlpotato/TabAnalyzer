import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from tab_analyzer.tunings import note_name_to_midi
from tab_analyzer.ui.tuner import (
    ChromaticTunerDialog,
    PitchReading,
    StringReading,
    estimate_monophonic_pitch,
    estimate_polyphonic_strings,
    estimate_single_string_reading,
    string_reading_from_pitch,
    smooth_polyphonic_readings,
    _refine_fft_peak_frequency,
)


class TunerAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_monophonic_pitch_detects_a4(self):
        sample_rate = 48000
        samples = [0.4 * math.sin((2 * math.pi * 440.0 * index) / sample_rate) for index in range(8192)]

        reading = estimate_monophonic_pitch(samples, sample_rate)

        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.note_name, "A4")
        self.assertAlmostEqual(reading.frequency, 440.0, delta=0.5)
        self.assertAlmostEqual(reading.cents, 0.0, delta=2.0)

    def test_polyphonic_pitch_detects_standard_open_strings(self):
        sample_rate = 48000
        frequencies = (82.4069, 110.0, 146.8324, 195.9977, 246.9417, 329.6276)
        samples = [
            sum(0.12 * math.sin((2 * math.pi * frequency * index) / sample_rate) for frequency in frequencies)
            for index in range(8192)
        ]

        readings = estimate_polyphonic_strings(samples, sample_rate)

        self.assertEqual([reading.name for reading in readings], ["E2", "A2", "D3", "G3", "B3", "E4"])
        self.assertTrue(all(reading.active for reading in readings))
        for reading in readings:
            self.assertIsNotNone(reading.cents)
            self.assertLessEqual(abs(reading.cents or 0.0), 3.0)

    def test_polyphonic_pitch_filters_lower_string_harmonics(self):
        sample_rate = 48000
        partials = (
            (82.4069, 0.35),
            (82.4069 * 2, 0.15),
            (82.4069 * 3, 0.12),
            (110.0, 0.35),
            (110.0 * 2, 0.15),
            (110.0 * 3, 0.12),
        )
        samples = [
            sum(amplitude * math.sin((2 * math.pi * frequency * index) / sample_rate) for frequency, amplitude in partials)
            for index in range(8192)
        ]

        readings = estimate_polyphonic_strings(samples, sample_rate)

        active = {reading.name for reading in readings if reading.active}
        self.assertEqual(active, {"E2", "A2"})

    def test_polyphonic_pitch_uses_selected_tuning_targets(self):
        sample_rate = 48000
        notes = ("D2", "A2", "D3", "G3", "B3", "E4")
        targets = tuple((note, note_name_to_midi(note)) for note in notes)
        frequencies = (73.4162, 110.0, 146.8324, 195.9977, 246.9417, 329.6276)
        samples = [
            sum(0.12 * math.sin((2 * math.pi * frequency * index) / sample_rate) for frequency in frequencies)
            for index in range(8192)
        ]

        readings = estimate_polyphonic_strings(samples, sample_rate, targets=targets)

        self.assertEqual([reading.name for reading in readings], list(notes))
        self.assertTrue(all(reading.active for reading in readings))
        for reading in readings:
            self.assertIsNotNone(reading.cents)
            self.assertLessEqual(abs(reading.cents or 0.0), 3.0)

    def test_single_string_reading_uses_selected_target(self):
        pitch = PitchReading(108.9, "A2", 45, -17.0, 0.9, 0.2)
        targets = (("E2", note_name_to_midi("E2")), ("A2", note_name_to_midi("A2")))

        reading = string_reading_from_pitch(pitch, targets, selected_target=targets[1])

        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.name, "A2")
        self.assertLess(reading.cents or 0.0, 0.0)

    def test_single_string_reading_auto_uses_nearest_tuning_target(self):
        pitch = PitchReading(73.4, "D2", 38, 0.0, 0.9, 0.2)
        targets = (("D2", note_name_to_midi("D2")), ("A2", note_name_to_midi("A2")))

        reading = string_reading_from_pitch(pitch, targets)

        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.name, "D2")
        self.assertAlmostEqual(reading.cents or 0.0, 0.0, delta=1.0)

    def test_single_string_filter_uses_selected_target_fundamental(self):
        sample_rate = 48000
        targets = (("E2", note_name_to_midi("E2")), ("A2", note_name_to_midi("A2")), ("D3", note_name_to_midi("D3")))
        samples = [
            (0.18 * math.sin((2 * math.pi * 110.0 * index) / sample_rate))
            + (0.10 * math.sin((2 * math.pi * 220.0 * index) / sample_rate))
            + (0.04 * math.sin((2 * math.pi * 146.8324 * index) / sample_rate))
            for index in range(8192)
        ]

        reading = estimate_single_string_reading(samples, sample_rate, targets=targets, selected_target=targets[1])

        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.name, "A2")
        self.assertAlmostEqual(reading.cents or 0.0, 0.0, delta=3.0)

    def test_single_string_filter_handles_selected_e4(self):
        sample_rate = 48000
        targets = (
            ("E2", note_name_to_midi("E2")),
            ("A2", note_name_to_midi("A2")),
            ("D3", note_name_to_midi("D3")),
            ("G3", note_name_to_midi("G3")),
            ("B3", note_name_to_midi("B3")),
            ("E4", note_name_to_midi("E4")),
        )
        samples = [
            (0.18 * math.sin((2 * math.pi * 329.6276 * index) / sample_rate))
            + (0.04 * math.sin((2 * math.pi * 659.2552 * index) / sample_rate))
            for index in range(8192)
        ]

        reading = estimate_single_string_reading(samples, sample_rate, targets=targets, selected_target=targets[-1])

        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(reading.name, "E4")
        self.assertAlmostEqual(reading.cents or 0.0, 0.0, delta=3.0)

    def test_single_string_filter_ignores_other_selected_target_when_fundamental_is_missing(self):
        sample_rate = 48000
        targets = (("E2", note_name_to_midi("E2")), ("A2", note_name_to_midi("A2")), ("E4", note_name_to_midi("E4")))
        samples = [
            (0.22 * math.sin((2 * math.pi * 329.6276 * index) / sample_rate))
            + (0.10 * math.sin((2 * math.pi * 220.0 * index) / sample_rate))
            for index in range(8192)
        ]

        reading = estimate_single_string_reading(samples, sample_rate, targets=targets, selected_target=targets[1])

        self.assertIsNone(reading)

    def test_fft_peak_refinement_keeps_pathological_offset_in_range(self):
        frequencies = [100.0, 101.0, 102.0]
        powers = [math.exp(1.0), math.exp(0.5000000001), math.exp(0.0000000004)]

        frequency = _refine_fft_peak_frequency(frequencies, powers, 1)

        self.assertEqual(frequency, 101.0)

    def test_tuner_dialog_displays_strings_high_to_low(self):
        dialog = ChromaticTunerDialog()
        try:
            self.assertEqual([row.name_label.text() for row in dialog.string_rows], ["E4", "B3", "G3", "D3", "A2", "E2"])
            combo_names = [
                dialog.single_target_combo.itemData(index)[0]
                for index in range(1, dialog.single_target_combo.count())
            ]
            self.assertEqual(combo_names, ["E4", "B3", "G3", "D3", "A2", "E2"])
        finally:
            dialog.close()

    def test_polyphonic_display_smooths_active_readings(self):
        previous = {"E2": (StringReading("E2", 82.4, 20.0, 0.2, True), 0.0)}
        readings = (StringReading("E2", 82.4, 10.0, 0.3, True),)

        displayed, updated = smooth_polyphonic_readings(readings, previous, 0.2, smoothing=0.3)

        self.assertAlmostEqual(displayed[0].cents or 0.0, 17.0, delta=0.01)
        self.assertTrue(displayed[0].active)
        self.assertFalse(displayed[0].held)
        self.assertEqual(updated["E2"][0], displayed[0])

    def test_polyphonic_display_holds_recent_lost_signal(self):
        previous = {"E2": (StringReading("E2", 82.4, -6.0, 0.2, True), 1.0)}
        readings = (StringReading("E2", 82.4, None, 0.0, False),)

        displayed, updated = smooth_polyphonic_readings(readings, previous, 1.8, hold_seconds=1.2)

        self.assertEqual(displayed[0].cents, -6.0)
        self.assertFalse(displayed[0].active)
        self.assertTrue(displayed[0].held)
        self.assertEqual(updated["E2"][1], 1.0)

    def test_polyphonic_display_expires_old_lost_signal(self):
        previous = {"E2": (StringReading("E2", 82.4, -6.0, 0.2, True), 1.0)}
        readings = (StringReading("E2", 82.4, None, 0.0, False),)

        displayed, updated = smooth_polyphonic_readings(readings, previous, 3.0, hold_seconds=1.2)

        self.assertIsNone(displayed[0].cents)
        self.assertFalse(displayed[0].active)
        self.assertFalse(displayed[0].held)
        self.assertEqual(updated, {})


if __name__ == "__main__":
    unittest.main()
