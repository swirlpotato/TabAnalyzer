import unittest

from tab_analyzer.analysis import Candidate, MeasureAnalysis, analyze_pitch_classes
from tab_analyzer.gp_loader import MeasureData, _apply_scale_tie_breakers, _merge_compatible_scale_segments, _reanalyze_with_context

from tests.helpers import A_DORIAN, A_NATURAL_MINOR, beat, measure, segment, tab_note


class AnalysisTests(unittest.TestCase):
    def test_minor_pentatonic_phrase_prefers_matching_scale(self):
        # A minor pentatonic: A C D E G
        analysis = analyze_pitch_classes([9, 0, 2, 4, 7, 9, 0])
        names = [candidate.name for candidate in analysis.scale_candidates[:3]]
        self.assertIn("A minor pentatonic", names)

    def test_major_triad_prefers_major_chord(self):
        # C E G
        analysis = analyze_pitch_classes([0, 4, 7, 0])
        self.assertEqual(analysis.chord_candidates[0].name, "C")

    def test_intermediate_guitar_scales_are_available(self):
        cases = {
            "C mixolydian": [0, 2, 4, 5, 7, 9, 10],
            "C harmonic minor": [0, 2, 3, 5, 7, 8, 11],
            "C melodic minor": [0, 2, 3, 5, 7, 9, 11],
            "C phrygian dominant": [0, 1, 4, 5, 7, 8, 10],
            "C major pentatonic": [0, 2, 4, 7, 9],
            "C minor pentatonic": [0, 3, 5, 7, 10],
            "C blues": [0, 3, 5, 6, 7, 10],
        }

        for expected_name, pitch_classes in cases.items():
            with self.subTest(expected_name=expected_name):
                analysis = analyze_pitch_classes(pitch_classes, top_n=12)
                names = [candidate.name for candidate in analysis.scale_candidates[:12]]
                self.assertIn(expected_name, names)

    def test_advanced_scale_names_are_not_ranked(self):
        analysis = analyze_pitch_classes([0, 1, 3, 4, 6, 8, 10], top_n=12)
        names = [candidate.name for candidate in analysis.scale_candidates[:12]]

        self.assertNotIn("C altered", names)
        self.assertNotIn("C diminished half-whole", names)
        self.assertNotIn("C double harmonic", names)

    def test_intermediate_chords_are_available(self):
        cases = {
            "Cmaj9": [0, 4, 7, 11, 2],
            "C6/9": [0, 4, 7, 9, 2],
            "C9sus4": [0, 5, 7, 10, 2],
            "Cm7b5": [0, 3, 6, 10],
            "Cdim7": [0, 3, 6, 9],
            "C7sus4": [0, 5, 7, 10],
        }

        for expected_name, pitch_classes in cases.items():
            with self.subTest(expected_name=expected_name):
                analysis = analyze_pitch_classes(pitch_classes, top_n=12)
                names = [candidate.name for candidate in analysis.chord_candidates[:12]]
                self.assertIn(expected_name, names)

    def test_advanced_chord_names_are_not_ranked(self):
        analysis = analyze_pitch_classes([0, 4, 7, 10, 1, 8], top_n=12)
        names = [candidate.name for candidate in analysis.chord_candidates[:12]]

        self.assertNotIn("C7b9", names)
        self.assertNotIn("C13#11", names)
        self.assertNotIn("C7b9b13", names)

    def test_global_context_biases_short_measure_scale(self):
        context = Candidate(
            kind="scale",
            name="F harmonic minor",
            root_pc=5,
            intervals=(0, 2, 3, 5, 7, 8, 11),
            score=100,
            matched_notes=7,
            total_notes=7,
            outside_notes=0,
        )
        analysis = analyze_pitch_classes([5, 0], context=context)
        names = [candidate.name for candidate in analysis.scale_candidates[:3]]
        self.assertIn("F harmonic minor", names)

    def test_equal_scale_scores_use_other_measure_rank_popularity(self):
        scale_a = Candidate("scale", "A natural minor", 9, (0, 2, 3, 5, 7, 8, 10), 90, 4, 4, 0)
        scale_b = Candidate("scale", "F harmonic minor", 5, (0, 2, 3, 5, 7, 8, 11), 90, 4, 4, 0)
        measure = _measure(1, (scale_a, scale_b))
        other_measure = _measure(2, (scale_b, scale_a))

        adjusted = _apply_scale_tie_breakers((measure, other_measure))

        self.assertEqual(adjusted[0].analysis.scale_candidates[0].name, "F harmonic minor")

    def test_segment_keeps_measure_scale_when_compatible(self):
        first = beat(0, (tab_note(5, 0, 0),))
        second = beat(960, (tab_note(2, 0, 960),))
        raw_segment = segment(0, 0, 3840, (first, second), A_DORIAN)
        raw_measure = measure(1, (first, second), segments=(raw_segment,))

        adjusted = _reanalyze_with_context((raw_measure,), A_DORIAN)[0]

        self.assertEqual(adjusted.analysis.scale_candidates[0].name, "A dorian")
        self.assertEqual(len(adjusted.segments), 1)
        self.assertEqual(adjusted.segments[0].analysis.scale_candidates[0].name, "A dorian")

    def test_matching_scale_segments_are_merged(self):
        first = beat(0, (tab_note(5, 0, 0),))
        second = beat(1920, (tab_note(2, 1, 1920),))
        left = segment(0, 0, 1920, (first,), A_NATURAL_MINOR)
        right = segment(1, 1920, 3840, (second,), A_NATURAL_MINOR)

        merged = _merge_compatible_scale_segments((left, right), A_NATURAL_MINOR, A_NATURAL_MINOR)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].analysis.scale_candidates[0].name, "A natural minor")
        self.assertEqual(merged[0].start_in_measure, 0)
        self.assertEqual(merged[0].end_in_measure, 3840)


if __name__ == "__main__":
    unittest.main()


def _measure(number, scales):
    return MeasureData(
        number=number,
        start_tick=0,
        length_ticks=3840,
        time_signature="4/4",
        beats=(),
        segments=(),
        analysis=MeasureAnalysis((), scales, ()),
    )
