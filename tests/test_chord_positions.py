import unittest

from tab_analyzer.analysis import Candidate
from tab_analyzer.chord_positions import (
    chord_position_display_name,
    filter_chord_positions,
    filter_chord_positions_by_category,
    filter_chord_positions_by_root_string,
    generate_chord_positions,
    group_chord_positions_by_category,
    render_chord_positions_html,
)
from tab_analyzer.i18n import tr


STANDARD_TUNING_HIGH_TO_LOW = (64, 59, 55, 50, 45, 40)


class ChordPositionTests(unittest.TestCase):
    def test_positions_obey_physical_limits(self):
        chord = Candidate("chord", "C13#11", 0, (0, 2, 4, 6, 7, 9, 10), 90, 7, 7, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertLessEqual(len(positions), 40)
        self.assertTrue(positions)
        for position in positions:
            fretted = [fret for fret in position.frets_high_to_low if fret > 0]
            if fretted:
                self.assertLessEqual(max(fretted) - min(fretted), 3)
                self.assertLess(max(fretted), 16)
            self.assertLessEqual(position.total_finger_cost, 4)

    def test_positions_do_not_include_frets_16_or_higher(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=440)

        self.assertTrue(positions)
        self.assertTrue(
            all(fret < 16 for position in positions for fret in position.frets_high_to_low if fret > 0)
        )

    def test_triad_positions_are_sorted_first(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertEqual(positions[0].label, "Triad/Core")
        self.assertEqual(sum(1 for fret in positions[0].frets_high_to_low if fret >= 0), 3)
        self.assertIn(0, positions[0].present_intervals)
        self.assertIn(4, positions[0].present_intervals)
        self.assertIn(7, positions[0].present_intervals)

    def test_triad_category_uses_exactly_three_sounding_strings(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=440)
        triad_positions = filter_chord_positions_by_category(positions, "Triad")
        c_shape = next(position for position in positions if position.frets_high_to_low == (0, 1, 0, 2, 3, -1))

        self.assertTrue(triad_positions)
        self.assertTrue(
            all(sum(1 for fret in position.frets_high_to_low if fret >= 0) == 3 for position in triad_positions)
        )
        self.assertNotIn("Triad", c_shape.categories)
        self.assertEqual(c_shape.label, "Core")

    def test_extended_chords_include_non_triad_voicings(self):
        chord = Candidate("chord", "C13#11", 0, (0, 2, 4, 6, 7, 9, 10), 90, 7, 7, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertTrue(any(position.label != "Triad/Core" for position in positions))

    def test_seventh_chords_keep_the_seventh(self):
        chord = Candidate("chord", "C7", 0, (0, 4, 7, 10), 96, 4, 4, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertTrue(positions)
        self.assertTrue(all(10 in position.present_intervals for position in positions))

    def test_ninth_chords_keep_the_seventh_and_ninth(self):
        chord = Candidate("chord", "C9", 0, (0, 2, 4, 7, 10), 96, 5, 5, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertTrue(positions)
        self.assertTrue(all(10 in position.present_intervals for position in positions))
        self.assertTrue(all(2 in position.present_intervals for position in positions))

    def test_add_chords_keep_the_added_tone(self):
        chord = Candidate("chord", "Cadd9", 0, (0, 2, 4, 7), 96, 4, 4, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertTrue(positions)
        self.assertTrue(all(2 in position.present_intervals for position in positions))

    def test_eleventh_chords_keep_the_ninth_and_eleventh(self):
        chord = Candidate("chord", "C11", 0, (0, 2, 4, 5, 7, 10), 96, 6, 6, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        self.assertTrue(positions)
        self.assertTrue(all(2 in position.present_intervals for position in positions))
        self.assertTrue(all(5 in position.present_intervals for position in positions))

    def test_visible_duplicate_fingerings_are_removed(self):
        chord = Candidate("chord", "Emadd9", 4, (0, 2, 3, 7), 98, 4, 4, 0)

        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)
        signatures = [
            (
                position.barre_fret,
                tuple((index, fret) for index, fret in enumerate(position.frets_high_to_low) if fret >= 0),
            )
            for position in positions
        ]

        self.assertEqual(len(signatures), len(set(signatures)))

    def test_triad_inversions_are_named_as_slash_chords(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)
        names_by_bass = {
            position.bass_interval: chord_position_display_name(chord, position, None)
            for position in positions
        }

        self.assertEqual(names_by_bass[4], f"C/E (C, {tr('{ordinal} inversion').format(ordinal='1st')})")
        self.assertEqual(names_by_bass[7], f"C/G (C, {tr('{ordinal} inversion').format(ordinal='2nd')})")

    def test_seventh_inversion_is_named(self):
        chord = Candidate("chord", "C7", 0, (0, 4, 7, 10), 96, 4, 4, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)
        names_by_bass = {
            position.bass_interval: chord_position_display_name(chord, position, None)
            for position in positions
        }

        self.assertEqual(names_by_bass[10], f"C7/Bb (C7, {tr('{ordinal} inversion').format(ordinal='3rd')})")

    def test_root_string_filter_keeps_positions_with_root_on_that_string(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=200)

        filtered = filter_chord_positions_by_root_string(positions, 6)

        self.assertTrue(filtered)
        self.assertTrue(all(6 in position.root_string_numbers for position in filtered))
        self.assertTrue(any(len(position.root_string_numbers) > 1 for position in filtered))

    def test_positions_are_grouped_by_category(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        grouped = dict(group_chord_positions_by_category(positions))

        self.assertIn("Triad", grouped)

    def test_category_filter_returns_only_that_category(self):
        chord = Candidate("chord", "C7", 0, (0, 4, 7, 10), 96, 4, 4, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=200)

        shell_positions = filter_chord_positions_by_category(positions, "Shell voicing")

        self.assertTrue(shell_positions)
        self.assertTrue(all("Shell voicing" in position.categories for position in shell_positions))

    def test_combined_filter_limits_results_after_category_filtering(self):
        chord = Candidate("chord", "C7", 0, (0, 4, 7, 10), 96, 4, 4, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=200)

        filtered = filter_chord_positions(positions, None, "Shell voicing", max_positions=2)

        self.assertEqual(len(filtered), 2)
        self.assertTrue(all("Shell voicing" in position.categories for position in filtered))

    def test_caged_filter_includes_c_a_g_e_d_shapes_for_c_major(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24, max_positions=440)

        caged_positions = filter_chord_positions(positions, None, "CAGED system", max_positions=40)
        caged_frets = {position.frets_high_to_low for position in caged_positions}

        self.assertLessEqual(len(caged_positions), 40)
        self.assertIn((0, 1, 0, 2, 3, -1), caged_frets)
        self.assertIn((3, 5, 5, 5, 3, -1), caged_frets)
        self.assertIn((8, 5, 5, 5, 7, 8), caged_frets)
        self.assertIn((8, 8, 9, 10, 10, 8), caged_frets)
        self.assertIn((12, 13, 12, 10, -1, -1), caged_frets)

    def test_extended_required_tones_remove_triad_category(self):
        chord = Candidate("chord", "C9", 0, (0, 2, 4, 7, 10), 96, 5, 5, 0)
        positions = generate_chord_positions(chord, STANDARD_TUNING_HIGH_TO_LOW, 24)

        categories = {category for position in positions for category in position.categories}

        self.assertNotIn("Triad", categories)

    def test_html_mentions_rules_and_sources(self):
        chord = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)

        html = render_chord_positions_html("Song", "Guitar", 1, chord, STANDARD_TUNING_HIGH_TO_LOW, 24, None)

        self.assertIn(tr("M{measure}: {chord} chord positions").format(measure=1, chord="C"), html)
        self.assertIn('<table class="diagram">', html)
        self.assertIn(tr("Reference sources"), html)
        self.assertNotIn("<svg", html)


if __name__ == "__main__":
    unittest.main()
