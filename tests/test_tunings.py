import unittest

from tab_analyzer.gp_loader import retune_song
from tab_analyzer.tunings import load_tuning_presets, note_name_to_midi

from tests.helpers import FLAT_TUNING, scale_fixture_song, song_with_measures


class TuningTests(unittest.TestCase):
    def test_common_tuning_presets_have_ten_entries(self):
        presets = load_tuning_presets()
        self.assertEqual(len(presets), 10)
        self.assertEqual(presets[0].id, "standard")
        self.assertEqual(presets[0].midi_high_to_low, (64, 59, 55, 50, 45, 40))

    def test_note_name_to_midi_supports_flats_and_sharps(self):
        self.assertEqual(note_name_to_midi("Eb2"), 39)
        self.assertEqual(note_name_to_midi("F#3"), 54)

    def test_retune_song_updates_open_string_pitches(self):
        song = scale_fixture_song()
        drop_d = next(preset for preset in load_tuning_presets() if preset.id == "drop_d")

        retuned = retune_song(song, drop_d.midi_high_to_low)

        self.assertEqual(retuned.track.string_pitches, drop_d.midi_high_to_low)
        self.assertEqual(retuned.track.string_names, ("E4", "B3", "G3", "D3", "A2", "D2"))

    def test_loaded_tuning_spelling_is_consistent_for_flat_tunings(self):
        song = song_with_measures((), tuning=FLAT_TUNING)

        self.assertEqual(song.track.string_names, ("Eb4", "Bb3", "Gb3", "Db3", "Ab2", "Eb2"))
        self.assertTrue(song.track.prefer_flats)


if __name__ == "__main__":
    unittest.main()
