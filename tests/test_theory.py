import unittest

from tab_analyzer.analysis import Candidate
from tab_analyzer.theory import TheoryExplainer

from tests.helpers import theory_fixture_song


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

    def test_tab_selection_explanation_mentions_playing_details(self):
        song = theory_fixture_song()

        html = TheoryExplainer().explain_tab_selection(song, 0, 1)

        self.assertIn("타브 연주 설명", html)
        self.assertIn("선택 범위", html)
        self.assertIn("앞부분 순서", html)
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
