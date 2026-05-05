"""Scale fingering block inference from played tab notes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from .analysis import Candidate


DEFAULT_FRET_SPAN = 5
DEFAULT_MAX_NOTES_PER_STRING = 3


class TabLikeNote(Protocol):
    string: int
    fret: int
    midi: int
    start_tick: int
    start_in_measure: int


class AnalysisLike(Protocol):
    scale_candidates: tuple[Candidate, ...]


class MeasureLike(Protocol):
    number: int
    notes: tuple[TabLikeNote, ...]
    analysis: AnalysisLike


@dataclass(frozen=True)
class PlayedNote:
    order: int
    string: int
    fret: int
    midi: int
    start_tick: int
    start_in_measure: int


@dataclass(frozen=True)
class ScaleBlock:
    index: int
    start_fret: int
    end_fret: int
    start_midi: int | None
    end_midi: int | None
    first_order: int
    played_positions: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ScaleSpan:
    block_index: int
    string_index: int
    start_fret: int
    end_fret: int


@dataclass(frozen=True)
class ScaleBlockUsage:
    candidate: Candidate
    block: ScaleBlock
    selected_count: int
    note_count: int
    measure_numbers: tuple[int, ...]


@dataclass
class _ScaleBlockUsageAccumulator:
    candidate: Candidate
    block: ScaleBlock
    selected_count: int
    note_count: int
    measure_numbers: list[int]
    best_note_count: int


@dataclass(frozen=True)
class _StringSpanOption:
    string_index: int
    frets: tuple[int, ...]
    min_midi: int
    max_midi: int
    score: float

    @property
    def start_fret(self) -> int:
        return min(self.frets)

    @property
    def end_fret(self) -> int:
        return max(self.frets)

    @property
    def center_fret(self) -> float:
        return sum(self.frets) / len(self.frets)


def infer_preferred_scale(measures: Iterable[MeasureLike]) -> Candidate | None:
    """Return the most common first-ranked scale candidate across measures."""

    stats: dict[str, tuple[int, int, int, Candidate]] = {}
    for order, measure in enumerate(measures):
        candidate = _top_scale_candidate(measure)
        if candidate is None:
            continue
        count, total_score, first_order, first_candidate = stats.get(
            candidate.name,
            (0, 0, order, candidate),
        )
        stats[candidate.name] = (
            count + 1,
            total_score + candidate.score,
            first_order,
            first_candidate,
        )
    if not stats:
        return None
    return max(stats.values(), key=lambda item: (item[0], item[1], -item[2]))[3]


def infer_song_scale_block_usages(
    measures: Iterable[MeasureLike],
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    preferred_scale: Candidate | None = None,
) -> tuple[ScaleBlockUsage, ...]:
    """Select and rank the scale blocks most often used by preferred-scale measures."""

    measures = tuple(measures)
    preferred_scale = preferred_scale or infer_preferred_scale(measures)
    if preferred_scale is None:
        return ()

    max_notes_per_string = _effective_max_notes_per_string(
        preferred_scale,
        DEFAULT_MAX_NOTES_PER_STRING,
    )
    usage_by_signature: dict[tuple[tuple[int, int], ...], _ScaleBlockUsageAccumulator] = {}

    for measure in measures:
        candidate = _top_scale_candidate(measure)
        if candidate is None or candidate.name != preferred_scale.name:
            continue
        notes = tuple(note for note in measure.notes if 0 <= note.fret <= fret_count)
        if not notes:
            continue
        blocks = infer_scale_blocks(
            notes,
            candidate,
            string_pitches_high_to_low,
            fret_count,
        )
        if not blocks:
            continue

        block, note_count, signature = _best_measure_scale_block(
            notes,
            blocks,
            candidate,
            string_pitches_high_to_low,
            fret_count,
            max_notes_per_string,
        )
        if block is None or not signature:
            continue

        existing = usage_by_signature.get(signature)
        if existing is None:
            usage_by_signature[signature] = _ScaleBlockUsageAccumulator(
                candidate=preferred_scale,
                block=block,
                selected_count=1,
                note_count=note_count,
                measure_numbers=[measure.number],
                best_note_count=note_count,
            )
            continue

        existing.selected_count += 1
        existing.note_count += note_count
        existing.measure_numbers.append(measure.number)
        if (note_count, -block.start_fret, -block.end_fret) > (
            existing.best_note_count,
            -existing.block.start_fret,
            -existing.block.end_fret,
        ):
            existing.block = block
            existing.best_note_count = note_count

    ordered = sorted(
        usage_by_signature.values(),
        key=lambda usage: (
            -usage.selected_count,
            -usage.note_count,
            usage.block.start_fret,
            usage.block.end_fret,
            usage.measure_numbers[0],
        ),
    )
    return tuple(
        ScaleBlockUsage(
            candidate=usage.candidate,
            block=ScaleBlock(
                index=index,
                start_fret=usage.block.start_fret,
                end_fret=usage.block.end_fret,
                start_midi=usage.block.start_midi,
                end_midi=usage.block.end_midi,
                first_order=usage.block.first_order,
                played_positions=usage.block.played_positions,
            ),
            selected_count=usage.selected_count,
            note_count=usage.note_count,
            measure_numbers=tuple(usage.measure_numbers),
        )
        for index, usage in enumerate(ordered)
    )


def _top_scale_candidate(measure: MeasureLike) -> Candidate | None:
    candidates = measure.analysis.scale_candidates
    return candidates[0] if candidates else None


def _best_measure_scale_block(
    notes: tuple[TabLikeNote, ...],
    blocks: tuple[ScaleBlock, ...],
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    max_notes_per_string: int,
) -> tuple[ScaleBlock | None, int, tuple[tuple[int, int], ...]]:
    best: tuple[int, int, int, int, ScaleBlock, tuple[tuple[int, int], ...]] | None = None
    for block in blocks:
        positions = _scale_block_display_positions(
            block,
            candidate,
            string_pitches_high_to_low,
            fret_count,
            max_notes_per_string,
        )
        signature = _scale_display_signature(
            positions,
            string_pitches_high_to_low,
            max_notes_per_string,
        )
        if not signature:
            continue
        position_set = set(positions)
        note_count = sum(
            1
            for note in notes
            if (note.string - 1, note.fret) in position_set
        )
        if note_count == 0:
            note_count = sum(
                1
                for note in notes
                if (note.string - 1, note.fret) in block.played_positions
            )
        score = (
            note_count,
            len(block.played_positions),
            -block.first_order,
            -block.start_fret,
            block,
            signature,
        )
        if best is None or score[:4] > best[:4]:
            best = score
    if best is None:
        return None, 0, ()
    return best[4], best[0], best[5]


def _scale_block_display_positions(
    block: ScaleBlock,
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    max_notes_per_string: int,
) -> tuple[tuple[int, int], ...]:
    spans = scale_block_spans(
        (block,),
        candidate,
        string_pitches_high_to_low,
        fret_count,
        DEFAULT_FRET_SPAN,
        max_notes_per_string,
    )
    return _scale_positions_from_spans(
        spans,
        set(candidate.pitch_classes),
        string_pitches_high_to_low,
    )


def infer_scale_blocks(
    notes: Iterable[TabLikeNote],
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    fret_span: int = DEFAULT_FRET_SPAN,
    max_notes_per_string: int = DEFAULT_MAX_NOTES_PER_STRING,
) -> tuple[ScaleBlock, ...]:
    """Infer compact scale boxes from played-note order.

    The intent is to show the fingering area a player is actually using rather
    than every theoretical root-position box. Blocks are derived from the note
    sequence and then augmented with useful root-anchored alternatives.
    """

    played = _normalize_notes(notes, fret_count)
    if not played:
        return ()
    max_notes_per_string = _effective_max_notes_per_string(candidate, max_notes_per_string)

    groups = _phrase_groups(played, fret_span, max_notes_per_string)
    blocks: list[ScaleBlock] = []
    seen: set[tuple[int, int, int | None, int | None, tuple[tuple[int, int], ...]]] = set()
    string_count = len(string_pitches_high_to_low)

    for group in groups:
        windows = _windows_for_group(
            group,
            candidate,
            string_count,
            fret_count,
            fret_span,
        )
        for start_fret, start_midi in windows:
            end_fret = min(fret_count, start_fret + fret_span - 1)
            covered = tuple(note for note in group if start_fret <= note.fret <= end_fret)
            if not covered:
                continue

            start_midi = _start_boundary(covered, candidate, string_count, start_midi)
            end_midi = _end_boundary(covered, candidate, string_count)
            if start_midi is not None and end_midi is not None and end_midi < start_midi:
                end_midi = None

            positions = tuple(sorted({(note.string - 1, note.fret) for note in covered}))
            key = (start_fret, end_fret, start_midi, end_midi, positions)
            if key in seen:
                continue
            seen.add(key)
            blocks.append(
                ScaleBlock(
                    index=len(blocks),
                    start_fret=start_fret,
                    end_fret=end_fret,
                    start_midi=start_midi,
                    end_midi=end_midi,
                    first_order=min(note.order for note in covered),
                    played_positions=positions,
                )
            )

    if not blocks:
        blocks = _fallback_blocks(played, fret_count, fret_span)

    blocks.sort(key=lambda block: (block.first_order, block.start_fret, block.end_fret))
    blocks = _dedupe_visual_blocks(
        blocks,
        candidate,
        string_pitches_high_to_low,
        fret_count,
        fret_span,
        max_notes_per_string,
    )

    return tuple(
        ScaleBlock(
            index=index,
            start_fret=block.start_fret,
            end_fret=block.end_fret,
            start_midi=block.start_midi,
            end_midi=block.end_midi,
            first_order=block.first_order,
            played_positions=block.played_positions,
        )
        for index, block in enumerate(blocks)
    )


def generate_scale_position_blocks(
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    fret_span: int = DEFAULT_FRET_SPAN,
    max_notes_per_string: int = DEFAULT_MAX_NOTES_PER_STRING,
) -> tuple[ScaleBlock, ...]:
    """Generate practical theoretical scale boxes across the full fretboard."""

    max_notes_per_string = _effective_max_notes_per_string(candidate, max_notes_per_string)
    last_start = max(0, fret_count - fret_span + 1)
    blocks: list[ScaleBlock] = []
    seen: set[tuple[tuple[int, int], ...]] = set()
    scale_pcs = set(candidate.pitch_classes)

    for start_fret in range(last_start + 1):
        spans = _theoretical_scale_position_spans(
            start_fret,
            candidate,
            string_pitches_high_to_low,
            fret_count,
            fret_span,
            max_notes_per_string,
        )
        _append_generated_scale_position_block(
            blocks,
            seen,
            spans,
            scale_pcs,
            string_pitches_high_to_low,
            max_notes_per_string,
            start_fret,
        )
        if fret_span > 1 and _has_full_fret_span(spans, fret_span):
            compact_spans = _theoretical_scale_position_spans(
                start_fret,
                candidate,
                string_pitches_high_to_low,
                fret_count,
                fret_span - 1,
                max_notes_per_string,
            )
            _append_generated_scale_position_block(
                blocks,
                seen,
                compact_spans,
                scale_pcs,
                string_pitches_high_to_low,
                max_notes_per_string,
                start_fret,
            )

    blocks = _dedupe_visual_blocks(
        blocks,
        candidate,
        string_pitches_high_to_low,
        fret_count,
        fret_span,
        max_notes_per_string,
    )

    return tuple(
        ScaleBlock(
            index=index,
            start_fret=block.start_fret,
            end_fret=block.end_fret,
            start_midi=block.start_midi,
            end_midi=block.end_midi,
            first_order=block.first_order,
            played_positions=block.played_positions,
        )
        for index, block in enumerate(blocks)
    )


def _append_generated_scale_position_block(
    blocks: list[ScaleBlock],
    seen: set[tuple[tuple[int, int], ...]],
    spans: tuple[ScaleSpan, ...],
    scale_pcs: set[int],
    string_pitches_high_to_low: tuple[int, ...],
    max_notes_per_string: int,
    first_order: int,
) -> None:
    positions = _scale_positions_from_spans(spans, scale_pcs, string_pitches_high_to_low)
    signature = _scale_display_signature(positions, string_pitches_high_to_low, max_notes_per_string)
    if not signature or signature in seen:
        return
    seen.add(signature)
    frets = [fret for _string_index, fret in positions]
    blocks.append(
        ScaleBlock(
            index=len(blocks),
            start_fret=min(frets),
            end_fret=max(frets),
            start_midi=None,
            end_midi=None,
            first_order=first_order,
            played_positions=positions,
        )
    )


def _scale_positions_from_spans(
    spans: tuple[ScaleSpan, ...],
    scale_pcs: set[int],
    string_pitches_high_to_low: tuple[int, ...],
) -> tuple[tuple[int, int], ...]:
    positions: set[tuple[int, int]] = set()
    for span in spans:
        if not 0 <= span.string_index < len(string_pitches_high_to_low):
            continue
        open_midi = string_pitches_high_to_low[span.string_index]
        for fret in range(span.start_fret, span.end_fret + 1):
            if (open_midi + fret) % 12 in scale_pcs:
                positions.add((span.string_index, fret))
    return tuple(sorted(positions, key=lambda position: (-position[0], position[1])))


def _scale_display_signature(
    positions: tuple[tuple[int, int], ...],
    string_pitches_high_to_low: tuple[int, ...],
    max_notes_per_string: int,
) -> tuple[tuple[int, int], ...]:
    return dedupe_repeated_pitch_positions(
        positions,
        string_pitches_high_to_low,
        preferred_notes_per_string=max_notes_per_string,
    )


def _has_full_fret_span(spans: tuple[ScaleSpan, ...], fret_span: int) -> bool:
    return any(span.end_fret - span.start_fret + 1 >= fret_span for span in spans)


def _theoretical_scale_position_spans(
    start_fret: int,
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    fret_span: int,
    max_notes_per_string: int,
) -> tuple[ScaleSpan, ...]:
    block = ScaleBlock(
        index=0,
        start_fret=start_fret,
        end_fret=min(fret_count, start_fret + fret_span - 1),
        start_midi=None,
        end_midi=None,
        first_order=start_fret,
        played_positions=(),
    )
    scale_pcs = set(candidate.pitch_classes)
    options_by_string = [
        _string_span_options(
            string_index,
            open_midi,
            block,
            set(),
            scale_pcs,
            fret_count,
            fret_span,
            max_notes_per_string,
        )
        for string_index, open_midi in enumerate(string_pitches_high_to_low)
    ]
    return tuple(
        ScaleSpan(0, option.string_index, option.start_fret, option.end_fret)
        for option in _choose_low_movement_string_spans(options_by_string)
    )


def dedupe_repeated_pitch_positions(
    positions: Iterable[tuple[int, int]],
    string_pitches_high_to_low: tuple[int, ...],
    preferred_notes_per_string: int = DEFAULT_MAX_NOTES_PER_STRING,
) -> tuple[tuple[int, int], ...]:
    """Remove repeated exact pitches between neighboring strings in a scale shape."""

    frets_by_string: dict[int, list[int]] = {}
    for string_index, fret in positions:
        if 0 <= string_index < len(string_pitches_high_to_low):
            frets_by_string.setdefault(string_index, []).append(fret)

    selected = {
        string_index: sorted(set(frets))
        for string_index, frets in frets_by_string.items()
        if frets
    }
    low_to_high = [
        string_index
        for string_index in range(len(string_pitches_high_to_low) - 1, -1, -1)
        if string_index in selected
    ]
    for lower_string, higher_string in zip(low_to_high, low_to_high[1:]):
        while selected[lower_string] and selected[higher_string]:
            lower_max_midi = string_pitches_high_to_low[lower_string] + selected[lower_string][-1]
            higher_min_midi = string_pitches_high_to_low[higher_string] + selected[higher_string][0]
            if lower_max_midi < higher_min_midi:
                break
            lower_priority = _scale_string_note_priority(selected[lower_string], preferred_notes_per_string)
            higher_priority = _scale_string_note_priority(selected[higher_string], preferred_notes_per_string)
            if higher_priority > lower_priority and len(selected[lower_string]) > 1:
                selected[lower_string].pop()
            elif len(selected[higher_string]) > 1:
                selected[higher_string].pop(0)
            elif len(selected[lower_string]) > 1:
                selected[lower_string].pop()
            else:
                break

    return tuple(
        (string_index, fret)
        for string_index in sorted(selected)
        for fret in selected[string_index]
    )


def _scale_string_note_priority(frets: list[int], preferred_notes_per_string: int) -> tuple[bool, int]:
    return (len(frets) >= preferred_notes_per_string, len(frets))


def _dedupe_visual_blocks(
    blocks: list[ScaleBlock],
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    fret_span: int,
    max_notes_per_string: int,
) -> list[ScaleBlock]:
    unique: list[ScaleBlock] = []
    seen: dict[tuple[tuple[int, int], ...], int] = {}
    priorities: dict[tuple[tuple[int, int], ...], tuple[bool, int, int]] = {}
    for block in blocks:
        spans = scale_block_spans(
            (block,),
            candidate,
            string_pitches_high_to_low,
            fret_count,
            fret_span,
            max_notes_per_string,
        )
        positions = _scale_positions_from_spans(spans, set(candidate.pitch_classes), string_pitches_high_to_low)
        signature = _scale_display_signature(positions, string_pitches_high_to_low, max_notes_per_string)
        priority = (block.start_midi is not None, -block.first_order, len(block.played_positions))
        existing_index = seen.get(signature)
        if existing_index is not None:
            if priority > priorities[signature]:
                unique[existing_index] = block
                priorities[signature] = priority
            continue
        seen[signature] = len(unique)
        priorities[signature] = priority
        unique.append(block)
    return unique


def scale_block_spans(
    blocks: Iterable[ScaleBlock],
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    fret_span: int = DEFAULT_FRET_SPAN,
    max_notes_per_string: int = DEFAULT_MAX_NOTES_PER_STRING,
) -> tuple[ScaleSpan, ...]:
    """Return per-string fret spans to paint for inferred scale blocks."""

    max_notes_per_string = _effective_max_notes_per_string(candidate, max_notes_per_string)
    spans: list[ScaleSpan] = []
    scale_pcs = set(candidate.pitch_classes)
    for block in blocks:
        observed_by_string: dict[int, set[int]] = {}
        for string_index, fret in block.played_positions:
            observed_by_string.setdefault(string_index, set()).add(fret)

        options_by_string = [
            _string_span_options(
                string_index,
                open_midi,
                block,
                observed_by_string.get(string_index, set()),
                scale_pcs,
                fret_count,
                fret_span,
                max_notes_per_string,
            )
            for string_index, open_midi in enumerate(string_pitches_high_to_low)
        ]
        chosen_options = _choose_low_movement_string_spans(options_by_string)
        for option in chosen_options:
            spans.append(ScaleSpan(block.index, option.string_index, option.start_fret, option.end_fret))
    return tuple(spans)


def _effective_max_notes_per_string(candidate: Candidate, default: int) -> int:
    if "pentatonic" in candidate.name.lower():
        return min(default, 2)
    return default


def _normalize_notes(notes: Iterable[TabLikeNote], fret_count: int) -> tuple[PlayedNote, ...]:
    normalized: list[PlayedNote] = []
    for order, note in enumerate(notes):
        fret = int(note.fret)
        if fret < 0 or fret > fret_count:
            continue
        normalized.append(
            PlayedNote(
                order=order,
                string=int(note.string),
                fret=fret,
                midi=int(note.midi),
                start_tick=int(getattr(note, "start_tick", 0) or 0),
                start_in_measure=int(getattr(note, "start_in_measure", 0) or 0),
            )
        )
    return tuple(sorted(normalized, key=lambda note: (note.start_tick, note.start_in_measure, note.order)))


def _phrase_groups(
    notes: tuple[PlayedNote, ...],
    fret_span: int,
    max_notes_per_string: int,
) -> tuple[tuple[PlayedNote, ...], ...]:
    groups: list[tuple[PlayedNote, ...]] = []
    current: list[PlayedNote] = []
    for note in notes:
        candidate = current + [note]
        if not current or _fits_position(candidate, fret_span, max_notes_per_string):
            current = candidate
            continue

        groups.append(tuple(current))
        seed = [note]
        for previous in reversed(current):
            if _fits_position([previous] + seed, fret_span, max_notes_per_string):
                seed.insert(0, previous)
            else:
                break
        current = seed

    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _fits_position(notes: list[PlayedNote], fret_span: int, max_notes_per_string: int) -> bool:
    frets = [note.fret for note in notes]
    if max(frets) - min(frets) > fret_span - 1:
        return False
    frets_by_string: dict[int, set[int]] = {}
    for note in notes:
        frets_by_string.setdefault(note.string, set()).add(note.fret)
    if any(len(frets) > max_notes_per_string for frets in frets_by_string.values()):
        return False
    return _is_stepwise_enough(notes)


def _is_stepwise_enough(notes: list[PlayedNote]) -> bool:
    ordered = sorted(notes, key=lambda note: (note.start_tick, note.start_in_measure, note.order))
    for previous, current in zip(ordered, ordered[1:]):
        if previous.string == current.string and abs(current.fret - previous.fret) > 3:
            return False
    return True


def _windows_for_group(
    group: tuple[PlayedNote, ...],
    candidate: Candidate,
    string_count: int,
    fret_count: int,
    fret_span: int,
) -> tuple[tuple[int, int | None], ...]:
    min_fret = min(note.fret for note in group)
    max_fret = max(note.fret for note in group)
    last_start = max(0, fret_count - fret_span + 1)
    if max_fret - min_fret <= fret_span - 1:
        covering_start = min_fret
    else:
        covering_start = max_fret - fret_span + 1
    covering_start = max(0, min(covering_start, last_start))
    windows: list[tuple[int, int | None]] = [(min(covering_start, last_start), None)]

    positions = {(note.string, note.fret) for note in group}
    strings = {note.string for note in group}
    if len(positions) < 4 or len(strings) < 2:
        return tuple(windows)

    for note in group:
        if note.midi % 12 != candidate.root_pc:
            continue
        if note.string >= max(1, string_count - 1):
            starts = (note.fret - 3,)
        else:
            continue
        for start in starts:
            start = max(0, min(last_start, start))
            if start <= note.fret <= start + fret_span - 1:
                windows.append((start, note.midi))

    useful: list[tuple[int, int | None]] = []
    seen: set[tuple[int, int | None]] = set()
    for start, start_midi in windows:
        end = start + fret_span - 1
        covered_count = sum(1 for note in group if start <= note.fret <= end)
        if covered_count < 2 and len(group) > 1:
            continue
        key = (start, start_midi)
        if key not in seen:
            seen.add(key)
            useful.append(key)
    return tuple(useful)


def _start_boundary(
    notes: tuple[PlayedNote, ...],
    candidate: Candidate,
    string_count: int,
    current_start_midi: int | None,
) -> int | None:
    low_string_notes = [note for note in notes if note.string == string_count]
    if low_string_notes:
        lowest = min(low_string_notes, key=lambda note: note.midi)
        if lowest.midi % 12 != candidate.root_pc:
            return lowest.midi
    return current_start_midi


def _end_boundary(
    notes: tuple[PlayedNote, ...],
    candidate: Candidate,
    _string_count: int,
) -> int | None:
    high_string_notes = [note for note in notes if note.string == 1]
    if high_string_notes:
        highest = max(high_string_notes, key=lambda note: note.midi)
        if highest.midi % 12 != candidate.root_pc:
            return highest.midi
    return None


def _limit_string_frets(
    scale_frets: list[int],
    observed_frets: set[int],
    max_notes_per_string: int,
) -> tuple[int, ...]:
    if len(scale_frets) <= max_notes_per_string:
        return tuple(scale_frets)
    best: tuple[int, ...] = tuple(scale_frets[:max_notes_per_string])
    best_score: tuple[int, int, int] | None = None
    for index in range(0, len(scale_frets) - max_notes_per_string + 1):
        window = tuple(scale_frets[index:index + max_notes_per_string])
        covered = len(observed_frets & set(window))
        center = sum(window)
        observed_center = sum(observed_frets) if observed_frets else center
        score = (covered, -abs(center - observed_center), -index)
        if best_score is None or score > best_score:
            best = window
            best_score = score
    return best


def _string_span_options(
    string_index: int,
    open_midi: int,
    block: ScaleBlock,
    observed_frets: set[int],
    scale_pcs: set[int],
    fret_count: int,
    fret_span: int,
    max_notes_per_string: int,
) -> tuple[_StringSpanOption, ...]:
    options: list[_StringSpanOption] = []
    seen: set[tuple[int, ...]] = set()
    observed_scale_frets = {
        fret
        for fret in observed_frets
        if 0 <= fret <= fret_count and (open_midi + fret) % 12 in scale_pcs
    }
    block_center = _block_center_fret(block)

    for window_start in range(0, max(0, fret_count - fret_span + 1) + 1):
        window_end = min(fret_count, window_start + fret_span - 1)
        scale_frets = [
            fret
            for fret in range(window_start, window_end + 1)
            if (open_midi + fret) % 12 in scale_pcs
        ]
        if not scale_frets:
            continue

        if observed_scale_frets and not observed_scale_frets.issubset(set(scale_frets)):
            continue

        chosen = _limit_string_frets(scale_frets, observed_scale_frets, max_notes_per_string)
        if not chosen or chosen in seen:
            continue
        seen.add(chosen)

        covered = len(observed_scale_frets & set(chosen))
        option_center = sum(chosen) / len(chosen)
        observed_center = sum(observed_scale_frets) / len(observed_scale_frets) if observed_scale_frets else block_center
        score = (
            covered * 900
            + len(chosen) * 64
            - abs(option_center - observed_center) * 16
            - abs(option_center - block_center) * 4
        )
        options.append(
            _StringSpanOption(
                string_index=string_index,
                frets=chosen,
                min_midi=open_midi + min(chosen),
                max_midi=open_midi + max(chosen),
                score=score,
            )
        )

    options.sort(key=lambda option: (-option.score, abs(option.center_fret - block_center), option.start_fret))
    return tuple(options[:12])


def _choose_low_movement_string_spans(
    options_by_string: list[tuple[_StringSpanOption, ...]],
) -> tuple[_StringSpanOption, ...]:
    strict = _choose_low_movement_string_spans_with_order(options_by_string, require_pitch_order=True)
    if strict:
        return strict
    return _choose_low_movement_string_spans_with_order(options_by_string, require_pitch_order=False)


def _choose_low_movement_string_spans_with_order(
    options_by_string: list[tuple[_StringSpanOption, ...]],
    require_pitch_order: bool,
) -> tuple[_StringSpanOption, ...]:
    low_to_high = list(reversed(options_by_string))
    states: list[tuple[float, tuple[_StringSpanOption, ...]]] = [(0.0, ())]

    for options in low_to_high:
        if not options:
            return ()
        next_states: list[tuple[float, tuple[_StringSpanOption, ...]]] = []
        for score, path in states:
            previous = path[-1] if path else None
            for option in options:
                if require_pitch_order and previous is not None and previous.max_midi >= option.min_midi:
                    continue
                transition_penalty = 0.0
                if previous is not None:
                    transition_penalty = abs(option.center_fret - previous.center_fret) * 24
                next_states.append((score + option.score - transition_penalty, path + (option,)))
        if not next_states:
            return ()
        next_states.sort(key=lambda item: item[0], reverse=True)
        states = next_states[:32]

    best = max(states, key=lambda item: item[0])[1]
    return tuple(sorted(best, key=lambda option: option.string_index))


def _block_center_fret(block: ScaleBlock) -> float:
    frets = [fret for _string_index, fret in block.played_positions]
    if frets:
        return sum(frets) / len(frets)
    return (block.start_fret + block.end_fret) / 2


def _fallback_blocks(
    notes: tuple[PlayedNote, ...],
    fret_count: int,
    fret_span: int,
) -> list[ScaleBlock]:
    blocks: list[ScaleBlock] = []
    frets = sorted({note.fret for note in notes})
    index = 0
    while index < len(frets):
        start = frets[index]
        end = min(fret_count, start + fret_span - 1)
        covered = tuple(note for note in notes if start <= note.fret <= end)
        positions = tuple(sorted({(note.string - 1, note.fret) for note in covered}))
        blocks.append(
            ScaleBlock(
                index=len(blocks),
                start_fret=start,
                end_fret=end,
                start_midi=None,
                end_midi=None,
                first_order=min((note.order for note in covered), default=0),
                played_positions=positions,
            )
        )
        while index + 1 < len(frets) and frets[index + 1] <= end:
            index += 1
        index += 1
    return blocks
