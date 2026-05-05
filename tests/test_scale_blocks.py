import unittest
from collections import Counter

from tab_analyzer.analysis import Candidate
from tab_analyzer.scale_blocks import (
    dedupe_repeated_pitch_positions,
    generate_scale_position_blocks,
    infer_preferred_scale,
    infer_scale_blocks,
    infer_song_scale_block_usages,
    scale_block_spans,
)

from tests.helpers import A_MINOR_PENTATONIC, A_NATURAL_MINOR, C_MAJOR, STANDARD_TUNING, scale_fixture_song, tab_note


class ScaleBlockInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.song = scale_fixture_song()

    def test_short_repeated_phrase_uses_one_compact_block(self):
        measure = self.song.track.measures[0]
        scale = measure.analysis.scale_candidates[0]

        blocks = infer_scale_blocks(measure.notes, scale, self.song.track.string_pitches, self.song.track.fret_count)

        self.assertEqual([(block.start_fret, block.end_fret) for block in blocks], [(10, 14)])

    def test_repeated_root_jump_breaks_the_stepwise_phrase(self):
        measure = self.song.track.measures[0]
        scale = measure.analysis.scale_candidates[0]

        blocks = infer_scale_blocks(measure.notes, scale, self.song.track.string_pitches, self.song.track.fret_count)

        self.assertEqual(blocks[0].played_positions, ((1, 10), (1, 13), (2, 12)))

    def test_minor_pentatonic_prefers_low_lateral_shift_across_strings(self):
        measure = self.song.track.measures[0]

        blocks = infer_scale_blocks(measure.notes, A_MINOR_PENTATONIC, self.song.track.string_pitches, self.song.track.fret_count)
        spans = scale_block_spans(blocks, A_MINOR_PENTATONIC, self.song.track.string_pitches, self.song.track.fret_count)

        span_by_string = {span.string_index: (span.start_fret, span.end_fret) for span in spans}
        self.assertEqual(span_by_string[2], (9, 12))
        self.assertNotEqual(span_by_string[2], (12, 14))
        self.assertEqual(span_by_string[1], (10, 13))

    def test_pentatonic_uses_two_notes_per_string(self):
        measure = self.song.track.measures[0]

        blocks = infer_scale_blocks(measure.notes, A_MINOR_PENTATONIC, self.song.track.string_pitches, self.song.track.fret_count)
        spans = scale_block_spans(blocks, A_MINOR_PENTATONIC, self.song.track.string_pitches, self.song.track.fret_count)

        for span in spans:
            scale_frets = [
                fret
                for fret in range(span.start_fret, span.end_fret + 1)
                if (self.song.track.string_pitches[span.string_index] + fret) % 12 in A_MINOR_PENTATONIC.pitch_classes
            ]
            self.assertLessEqual(len(scale_frets), 2)

    def test_shifted_phrase_keeps_low_root_anchored_overlap_block(self):
        measure = self.song.track.measures[1]

        blocks = infer_scale_blocks(measure.notes, A_NATURAL_MINOR, self.song.track.string_pitches, self.song.track.fret_count)
        spans = scale_block_spans(blocks, A_NATURAL_MINOR, self.song.track.string_pitches, self.song.track.fret_count)
        rooted_blocks = [block for block in blocks if block.start_fret == 9 and block.end_fret == 13 and block.start_midi == 57]

        self.assertTrue(rooted_blocks)
        block_indexes = {block.index for block in rooted_blocks}
        self.assertIn((4, 12), {position for block in rooted_blocks for position in block.played_positions})
        self.assertIn(
            (3, 9, 12),
            {(span.string_index, span.start_fret, span.end_fret) for span in spans if span.block_index in block_indexes},
        )
        self.assertTrue(any(span.string_index == 5 for span in spans if span.block_index in block_indexes))

    def test_inferred_blocks_dedupe_identical_visual_blocks(self):
        notes = (
            tab_note(5, 12, 0),
            tab_note(4, 9, 480),
            tab_note(3, 9, 960),
            tab_note(2, 10, 1440),
            tab_note(5, 12, 1920),
            tab_note(4, 9, 2400),
        )

        blocks = infer_scale_blocks(notes, A_NATURAL_MINOR, self.song.track.string_pitches, self.song.track.fret_count)
        signatures = []
        for block in blocks:
            spans = scale_block_spans((block,), A_NATURAL_MINOR, self.song.track.string_pitches, self.song.track.fret_count)
            signatures.append(tuple(sorted((span.string_index, span.start_fret, span.end_fret) for span in spans)))

        self.assertEqual(len(signatures), len(set(signatures)))

    def test_generated_scale_positions_cover_fretboard_without_duplicate_shapes(self):
        blocks = generate_scale_position_blocks(C_MAJOR, self.song.track.string_pitches, 24)

        self.assertTrue(blocks)
        self.assertEqual(blocks[0].start_fret, 0)
        self.assertEqual(blocks[0].played_positions[0][0], len(self.song.track.string_pitches) - 1)
        self.assertTrue(all(block.end_fret <= 24 for block in blocks))
        signatures = []
        for block in blocks:
            spans = scale_block_spans((block,), C_MAJOR, self.song.track.string_pitches, 24)
            positions = {
                (span.string_index, fret)
                for span in spans
                for fret in range(span.start_fret, span.end_fret + 1)
                if (self.song.track.string_pitches[span.string_index] + fret) % 12 in C_MAJOR.pitch_classes
            }
            signatures.append(
                tuple(sorted(dedupe_repeated_pitch_positions(positions, self.song.track.string_pitches)))
            )
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_generated_scale_positions_use_per_string_fret_span(self):
        blocks = generate_scale_position_blocks(C_MAJOR, self.song.track.string_pitches, 24)
        span_maps = [
            {span.string_index: (span.start_fret, span.end_fret) for span in scale_block_spans((block,), C_MAJOR, self.song.track.string_pitches, 24)}
            for block in blocks
        ]

        self.assertTrue(any(span_map.get(2) == (7, 10) and span_map.get(1) == (8, 12) for span_map in span_maps))
        self.assertTrue(any(span_map.get(2) == (7, 10) and span_map.get(1) == (8, 10) for span_map in span_maps))

    def test_generated_pentatonic_positions_use_two_notes_per_string(self):
        blocks = generate_scale_position_blocks(A_MINOR_PENTATONIC, self.song.track.string_pitches, 24)
        spans = scale_block_spans(blocks, A_MINOR_PENTATONIC, self.song.track.string_pitches, 24)

        self.assertTrue(blocks)
        for span in spans:
            scale_frets = [
                fret
                for fret in range(span.start_fret, span.end_fret + 1)
                if (self.song.track.string_pitches[span.string_index] + fret) % 12 in A_MINOR_PENTATONIC.pitch_classes
            ]
            self.assertLessEqual(len(scale_frets), 2)

    def test_scale_position_dedupe_removes_repeated_exact_pitches(self):
        positions = {
            (1, 6),
            (1, 8),
            (2, 7),
            (2, 9),
            (2, 10),
        }

        deduped = set(dedupe_repeated_pitch_positions(positions, self.song.track.string_pitches))
        midis = [
            self.song.track.string_pitches[string_index] + fret
            for string_index, fret in deduped
        ]

        self.assertIn((2, 10), deduped)
        self.assertNotIn((1, 6), deduped)
        self.assertEqual(len(midis), len(set(midis)))

    def test_preferred_scale_is_most_common_top_measure_scale(self):
        expected_name, _count = Counter(
            measure.analysis.scale_candidates[0].name
            for measure in self.song.track.measures
            if measure.analysis.scale_candidates
        ).most_common(1)[0]

        preferred = infer_preferred_scale(self.song.track.measures)

        self.assertIsNotNone(preferred)
        self.assertEqual(preferred.name, expected_name)

    def test_song_scale_block_usages_rank_selected_blocks(self):
        preferred = infer_preferred_scale(self.song.track.measures)
        self.assertIsNotNone(preferred)

        usages = infer_song_scale_block_usages(
            self.song.track.measures,
            self.song.track.string_pitches,
            self.song.track.fret_count,
            preferred,
        )

        self.assertTrue(usages)
        self.assertEqual([usage.block.index for usage in usages], list(range(len(usages))))
        self.assertTrue(all(usage.candidate.name == preferred.name for usage in usages))
        self.assertTrue(all(usage.selected_count > 0 for usage in usages))
        self.assertEqual(
            [usage.selected_count for usage in usages],
            sorted((usage.selected_count for usage in usages), reverse=True),
        )
        self.assertLessEqual(
            sum(usage.selected_count for usage in usages),
            sum(
                1
                for measure in self.song.track.measures
                if measure.analysis.scale_candidates
                and preferred is not None
                and measure.analysis.scale_candidates[0].name == preferred.name
            ),
        )

    def test_generated_scale_positions_can_use_explicit_tuning_without_song_file(self):
        scale = Candidate("scale", "C major", 0, (0, 2, 4, 5, 7, 9, 11), 100, 0, 0, 0)

        blocks = generate_scale_position_blocks(scale, STANDARD_TUNING, 24)

        self.assertTrue(blocks)


if __name__ == "__main__":
    unittest.main()
