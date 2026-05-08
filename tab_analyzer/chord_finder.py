"""Chord lookup helpers for the interactive chord finder tab."""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import CHORD_PATTERNS, Candidate, pitch_class_name


COMMON_CHORD_TYPE_SUFFIX_ORDER = (
    "",
    "m",
    "7",
    "maj7",
    "m7",
    "sus4",
    "sus2",
    "add9",
    "madd9",
    "5",
    "6",
    "m6",
    "6/9",
    "9",
    "m9",
    "maj9",
    "7sus4",
    "9sus4",
    "dim",
    "aug",
    "m7b5",
    "dim7",
)

CHORD_TYPE_DISPLAY_NAMES = {
    "": "Major",
    "m": "Minor",
    "7": "7",
    "maj7": "maj7",
    "m7": "m7",
    "sus4": "sus4",
    "sus2": "sus2",
    "add9": "add9",
    "5": "Power 5",
    "dim": "dim",
    "aug": "aug",
}

CHORD_INTERVAL_ROLE_LABELS = {
    0: "Root",
    1: "b9",
    2: "9",
    3: "b3",
    4: "3",
    5: "11",
    6: "b5/#11",
    7: "5",
    8: "b13/#5",
    9: "6/13",
    10: "b7",
    11: "7",
}

CHORD_INTERVAL_ROLE_PRIORITY = {
    0: 0,
    4: 1,
    3: 1,
    7: 2,
    10: 3,
    11: 3,
    2: 4,
    9: 4,
    5: 5,
    6: 6,
    8: 6,
    1: 7,
}


@dataclass(frozen=True)
class ChordType:
    name: str
    suffix: str
    intervals: tuple[int, ...]
    display_name: str
    usage_rank: int


@dataclass(frozen=True)
class ChordMatch:
    candidate: Candidate
    chord_type: ChordType
    selected_intervals: tuple[int, ...]
    selected_note_pcs: tuple[int, ...]
    role_rank: int

    @property
    def selected_interval(self) -> int:
        return self.selected_intervals[0] if self.selected_intervals else 0

    @property
    def selected_note_pc(self) -> int:
        return self.selected_note_pcs[0] if self.selected_note_pcs else self.candidate.root_pc


def common_chord_types() -> tuple[ChordType, ...]:
    pattern_by_suffix = {suffix: (name, intervals) for name, suffix, intervals in CHORD_PATTERNS}
    ordered: list[ChordType] = []
    seen: set[str] = set()

    for rank, suffix in enumerate(COMMON_CHORD_TYPE_SUFFIX_ORDER):
        pattern = pattern_by_suffix.get(suffix)
        if pattern is None:
            continue
        name, intervals = pattern
        ordered.append(
            ChordType(
                name=name,
                suffix=suffix,
                intervals=tuple(intervals),
                display_name=chord_type_display_name(suffix),
                usage_rank=rank,
            )
        )
        seen.add(suffix)

    next_rank = len(ordered)
    for name, suffix, intervals in CHORD_PATTERNS:
        if suffix in seen:
            continue
        ordered.append(
            ChordType(
                name=name,
                suffix=suffix,
                intervals=tuple(intervals),
                display_name=chord_type_display_name(suffix),
                usage_rank=next_rank,
            )
        )
        seen.add(suffix)
        next_rank += 1

    return tuple(ordered)

def chord_type_display_name(suffix: str) -> str:
    return CHORD_TYPE_DISPLAY_NAMES.get(suffix, suffix or "Major")


CHORD_FINDER_TYPES = common_chord_types()


def chord_match_role_label(match: ChordMatch) -> str:
    return CHORD_INTERVAL_ROLE_LABELS[match.selected_interval % 12]


def find_chords_containing_pitch(
    note_pc: int,
    root_pc: int | None = None,
    chord_type_suffix: str | None = None,
) -> tuple[ChordMatch, ...]:
    return find_chords_containing_pitches((note_pc,), root_pc, chord_type_suffix)


def find_chords_containing_pitches(
    note_pcs: tuple[int, ...],
    root_pc: int | None = None,
    chord_type_suffix: str | None = None,
) -> tuple[ChordMatch, ...]:
    normalized_note_pcs = _unique_pitch_classes(note_pcs)
    if not normalized_note_pcs:
        return ()

    matches: list[ChordMatch] = []
    root_range = (root_pc % 12,) if root_pc is not None else range(12)

    for candidate_root in root_range:
        for chord_type in CHORD_FINDER_TYPES:
            if chord_type_suffix is not None and chord_type.suffix != chord_type_suffix:
                continue
            selected_intervals = tuple((note_pc - candidate_root) % 12 for note_pc in normalized_note_pcs)
            if any(selected_interval not in chord_type.intervals for selected_interval in selected_intervals):
                continue
            role_rank = sum(CHORD_INTERVAL_ROLE_PRIORITY.get(selected_interval, 9) for selected_interval in selected_intervals)
            candidate = Candidate(
                kind="chord",
                name=f"{pitch_class_name(candidate_root)}{chord_type.suffix}",
                root_pc=candidate_root,
                intervals=chord_type.intervals,
                score=max(1, 100 - chord_type.usage_rank - role_rank * 3 - max(0, len(chord_type.intervals) - len(normalized_note_pcs))),
                matched_notes=len(normalized_note_pcs),
                total_notes=len(chord_type.intervals),
                outside_notes=0,
            )
            matches.append(
                ChordMatch(
                    candidate=candidate,
                    chord_type=chord_type,
                    selected_intervals=selected_intervals,
                    selected_note_pcs=normalized_note_pcs,
                    role_rank=role_rank,
                )
            )

    return tuple(sorted(matches, key=_chord_match_sort_key))


def find_chords_by_filter(
    root_pc: int | None = None,
    chord_type_suffix: str | None = None,
) -> tuple[ChordMatch, ...]:
    if root_pc is None and chord_type_suffix is None:
        return ()

    matches: list[ChordMatch] = []
    root_range = (root_pc % 12,) if root_pc is not None else range(12)
    for candidate_root in root_range:
        for chord_type in CHORD_FINDER_TYPES:
            if chord_type_suffix is not None and chord_type.suffix != chord_type_suffix:
                continue
            candidate = Candidate(
                kind="chord",
                name=f"{pitch_class_name(candidate_root)}{chord_type.suffix}",
                root_pc=candidate_root,
                intervals=chord_type.intervals,
                score=max(1, 100 - chord_type.usage_rank),
                matched_notes=0,
                total_notes=len(chord_type.intervals),
                outside_notes=0,
            )
            matches.append(
                ChordMatch(
                    candidate=candidate,
                    chord_type=chord_type,
                    selected_intervals=(),
                    selected_note_pcs=(),
                    role_rank=0,
                )
            )

    return tuple(sorted(matches, key=_chord_match_sort_key))


def _chord_match_sort_key(match: ChordMatch) -> tuple[int, int, int, int, int]:
    return (
        match.role_rank,
        match.chord_type.usage_rank,
        len(match.chord_type.intervals),
        match.candidate.root_pc,
        match.selected_interval,
    )


def _unique_pitch_classes(note_pcs: tuple[int, ...]) -> tuple[int, ...]:
    unique: list[int] = []
    seen: set[int] = set()
    for note_pc in note_pcs:
        normalized = note_pc % 12
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return tuple(unique)
