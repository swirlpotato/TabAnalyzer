import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tab_analyzer.gp_loader import _pyguitarpro_note_techniques, default_track_index, list_tracks, load_gp_file

from tests.helpers import write_gpif_fixture


class GpifLoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.fixture_path = write_gpif_fixture(Path(self.temp_dir.name) / "fixture.gp")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_songsterr_gp_file_loads_gpif_score(self):
        song = load_gp_file(self.fixture_path)

        self.assertEqual(song.title, "Fixture Song")
        self.assertIn("Lead Guitar", song.track.name)
        self.assertEqual(song.tempo, 90)
        self.assertEqual(len(song.track.measures), 1)
        self.assertEqual(song.track.string_names, ("E4", "B3", "G3", "D3", "A2", "E2"))
        self.assertTrue(any(measure.notes for measure in song.track.measures))

    def test_songsterr_gp_tracks_are_listed_and_default_to_first_electric_guitar(self):
        tracks = list_tracks(self.fixture_path)

        self.assertGreater(len(tracks), 1)
        self.assertEqual(default_track_index(self.fixture_path), 2)
        self.assertIn("Lead Guitar", tracks[2].name)
        self.assertTrue(tracks[2].is_electric_guitar)

    def test_songsterr_gp_can_load_selected_track(self):
        song = load_gp_file(self.fixture_path, track_index=7)

        self.assertIn("Rhythm Guitar", song.track.name)

    def test_songsterr_gp_reads_gpif_note_techniques(self):
        song = load_gp_file(self.fixture_path, track_index=7)
        techniques = {technique for note in song.track.measures[0].notes for technique in note.techniques}

        self.assertIn("slide", techniques)
        self.assertIn("let_ring", techniques)
        self.assertIn("bend", techniques)
        self.assertIn("tremolo_bar", techniques)

    def test_songsterr_gp_reads_gpif_bend_amount(self):
        song = load_gp_file(self.fixture_path, track_index=7)
        bent_notes = [note for note in song.track.measures[0].notes if "bend" in note.techniques]

        self.assertEqual(len(bent_notes), 1)
        self.assertEqual(bent_notes[0].bend_semitones, 1)

    def test_pyguitarpro_beat_tremolo_bar_marks_arm_usage(self):
        note = SimpleNamespace(type=None, effect=SimpleNamespace())
        beat = SimpleNamespace(effect=SimpleNamespace(tremoloBar=SimpleNamespace(type=SimpleNamespace(name="dip"))))

        self.assertIn("tremolo_bar", _pyguitarpro_note_techniques(note, None, beat))


if __name__ == "__main__":
    unittest.main()
