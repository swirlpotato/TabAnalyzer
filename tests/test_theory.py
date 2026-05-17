import unittest
from dataclasses import replace
from unittest.mock import patch

from tab_analyzer.analysis import Candidate
from tab_analyzer.i18n import tr
from tab_analyzer.theory import TheoryExplainer

from tests.helpers import beat, measure, song_with_measures, tab_note, theory_fixture_song


class TheoryExplainerTests(unittest.TestCase):
    def test_empty_state_returns_html(self):
        html = TheoryExplainer().explain_selection(None, None, None, "scale", None)
        self.assertIn("<html>", html)

    def test_sample_selection_mentions_measure_and_scale(self):
        song = theory_fixture_song()
        measure = song.track.measures[0]
        segment = measure.segments[0]
        candidate = segment.analysis.scale_candidates[0]

        html = TheoryExplainer().explain_selection(song, measure, candidate, "scale", segment)

        self.assertIn("M9", html)
        self.assertIn(candidate.name, html)
        self.assertIn("C major / C", html)
        self.assertIn("<html>", html)

    def test_song_explanation_mentions_global_progression(self):
        song = theory_fixture_song()

        html = TheoryExplainer().explain_song(song)

        self.assertIn("Theory Fixture", html)
        self.assertIn("C major", html)
        self.assertIn("Am", html)
        self.assertIn("<html>", html)

    def test_song_explanation_mentions_guitar_requirements(self):
        seven_string_tuning = (64, 59, 55, 50, 45, 40, 35)
        song = song_with_measures(
            (
                measure(
                    1,
                    (
                        beat(0, (tab_note(1, 20, 0, seven_string_tuning),)),
                        beat(480, (replace(tab_note(7, 5, 480, seven_string_tuning), techniques=("tremolo_bar",)),)),
                    ),
                ),
            ),
            tuning=seven_string_tuning,
        )

        with patch("locale.getlocale", return_value=("English_United States", "1252")):
            html = TheoryExplainer().explain_song(song)

        self.assertIn("Required guitar conditions", html)
        self.assertIn("21-fret guitar can play it", html)
        self.assertIn("7-string guitar", html)
        self.assertIn("6-string guitar", html)
        self.assertIn("tremolo arm", html)

    def test_tab_selection_explanation_mentions_playing_details(self):
        song = theory_fixture_song()

        html = TheoryExplainer().explain_tab_selection(song, 0, 1)

        self.assertIn(tr("Tab playing explanation"), html)
        self.assertIn(tr("Selection"), html)
        self.assertIn(tr("Opening order"), html)
        self.assertIn("<html>", html)

    def test_scale_confidence_collapses_equivalent_modes(self):
        candidates = (
            Candidate("scale", "A natural minor", 9, (0, 2, 3, 5, 7, 8, 10), 100, 7, 7, 0),
            Candidate("scale", "G mixolydian", 7, (0, 2, 4, 5, 7, 9, 10), 100, 7, 7, 0),
            Candidate("scale", "A minor pentatonic", 9, (0, 3, 5, 7, 10), 96, 5, 5, 0),
        )

        unique = TheoryExplainer()._unique_scale_candidates(candidates)
        names = [candidate.name for candidate in unique[:3]]

        self.assertEqual(names[0], "A natural minor")
        self.assertNotIn("G mixolydian", names)


if __name__ == "__main__":
    unittest.main()
