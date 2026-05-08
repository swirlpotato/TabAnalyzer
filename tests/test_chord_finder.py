import unittest

from tab_analyzer.chord_finder import (
    CHORD_FINDER_TYPES,
    chord_match_role_label,
    find_chords_by_filter,
    find_chords_containing_pitch,
    find_chords_containing_pitches,
)


class ChordFinderTests(unittest.TestCase):
    def test_types_are_sorted_by_common_usage(self):
        suffixes = [chord_type.suffix for chord_type in CHORD_FINDER_TYPES[:5]]

        self.assertEqual(suffixes, ["", "m", "7", "maj7", "m7"])

    def test_types_stay_at_intermediate_guitar_level(self):
        suffixes = {chord_type.suffix for chord_type in CHORD_FINDER_TYPES}

        self.assertIn("9", suffixes)
        self.assertIn("m7b5", suffixes)
        self.assertNotIn("7b9", suffixes)
        self.assertNotIn("13#11", suffixes)
        self.assertNotIn("7alt", suffixes)

    def test_clicking_c_prioritizes_c_root_chords(self):
        matches = find_chords_containing_pitch(0)
        names = [match.candidate.name for match in matches[:5]]

        self.assertEqual(names, ["C", "Cm", "C7", "Cmaj7", "Cm7"])
        self.assertTrue(all(match.selected_interval == 0 for match in matches[:5]))

    def test_root_filter_only_returns_that_root(self):
        matches = find_chords_containing_pitch(0, root_pc=5)

        self.assertTrue(matches)
        self.assertTrue(all(match.candidate.root_pc == 5 for match in matches))

    def test_type_filter_only_returns_that_type(self):
        matches = find_chords_containing_pitch(0, chord_type_suffix="maj7")

        self.assertTrue(matches)
        self.assertTrue(all(match.chord_type.suffix == "maj7" for match in matches))

    def test_role_label_describes_selected_note_function(self):
        match = find_chords_containing_pitch(4, root_pc=0, chord_type_suffix="")[0]

        self.assertEqual(match.candidate.name, "C")
        self.assertEqual(chord_match_role_label(match), "3")

    def test_multiple_notes_must_all_belong_to_the_chord(self):
        matches = find_chords_containing_pitches((0, 4, 7))
        names = [match.candidate.name for match in matches[:5]]

        self.assertEqual(names[0], "C")
        self.assertNotIn("Cm", names)
        self.assertTrue(all({0, 4, 7}.issubset(set(match.candidate.pitch_classes)) for match in matches))

    def test_filter_only_lookup_returns_selected_root_and_type(self):
        matches = find_chords_by_filter(root_pc=0, chord_type_suffix="maj7")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].candidate.name, "Cmaj7")

    def test_filter_only_lookup_requires_at_least_one_filter(self):
        self.assertEqual(find_chords_by_filter(), ())


if __name__ == "__main__":
    unittest.main()
