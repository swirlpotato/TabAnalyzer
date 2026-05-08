"""Scale and chord estimation logic.

This module is intentionally independent from the UI and Guitar Pro parser so
the scoring rules can be tuned or replaced later without touching the app.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from typing import Iterable, Sequence


NOTE_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
SHARP_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NOTE_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

INTERVAL_NAMES = {
    0: "R",
    1: "b2",
    2: "2",
    3: "b3",
    4: "3",
    5: "4",
    6: "b5",
    7: "5",
    8: "b6",
    9: "6",
    10: "b7",
    11: "7",
}

SCALE_PATTERNS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("major", (0, 2, 4, 5, 7, 9, 11)),
    ("natural minor", (0, 2, 3, 5, 7, 8, 10)),
    ("dorian", (0, 2, 3, 5, 7, 9, 10)),
    ("phrygian", (0, 1, 3, 5, 7, 8, 10)),
    ("lydian", (0, 2, 4, 6, 7, 9, 11)),
    ("mixolydian", (0, 2, 4, 5, 7, 9, 10)),
    ("locrian", (0, 1, 3, 5, 6, 8, 10)),
    ("harmonic minor", (0, 2, 3, 5, 7, 8, 11)),
    ("melodic minor", (0, 2, 3, 5, 7, 9, 11)),
    ("phrygian dominant", (0, 1, 4, 5, 7, 8, 10)),
    ("major pentatonic", (0, 2, 4, 7, 9)),
    ("minor pentatonic", (0, 3, 5, 7, 10)),
    ("blues", (0, 3, 5, 6, 7, 10)),
    ("major blues", (0, 2, 3, 4, 7, 9)),
)

CHORD_PATTERNS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("major", "", (0, 4, 7)),
    ("minor", "m", (0, 3, 7)),
    ("power", "5", (0, 7)),
    ("sus2", "sus2", (0, 2, 7)),
    ("sus4", "sus4", (0, 5, 7)),
    ("diminished", "dim", (0, 3, 6)),
    ("augmented", "aug", (0, 4, 8)),
    ("add9", "add9", (0, 2, 4, 7)),
    ("minor add9", "madd9", (0, 2, 3, 7)),
    ("major 6", "6", (0, 4, 7, 9)),
    ("minor 6", "m6", (0, 3, 7, 9)),
    ("six nine", "6/9", (0, 2, 4, 7, 9)),
    ("major 7", "maj7", (0, 4, 7, 11)),
    ("dominant 7", "7", (0, 4, 7, 10)),
    ("minor 7", "m7", (0, 3, 7, 10)),
    ("half diminished", "m7b5", (0, 3, 6, 10)),
    ("diminished 7", "dim7", (0, 3, 6, 9)),
    ("suspended 7", "7sus4", (0, 5, 7, 10)),
    ("dominant 9", "9", (0, 2, 4, 7, 10)),
    ("minor 9", "m9", (0, 2, 3, 7, 10)),
    ("major 9", "maj9", (0, 2, 4, 7, 11)),
    ("suspended 9", "9sus4", (0, 2, 5, 7, 10)),
)


@dataclass(frozen=True)
class Candidate:
    """A scored scale or chord candidate."""

    kind: str
    name: str
    root_pc: int
    intervals: tuple[int, ...]
    score: int
    matched_notes: int
    total_notes: int
    outside_notes: int

    @property
    def root_name(self) -> str:
        return pitch_class_name(self.root_pc)

    @property
    def pitch_classes(self) -> tuple[int, ...]:
        return tuple((self.root_pc + interval) % 12 for interval in self.intervals)

    @property
    def label(self) -> str:
        return f"{self.name} {self.score}"


@dataclass(frozen=True)
class MeasureAnalysis:
    """Analysis result for one measure."""

    note_pitch_classes: tuple[int, ...]
    scale_candidates: tuple[Candidate, ...]
    chord_candidates: tuple[Candidate, ...]


def pitch_class_name(pc: int, prefer_flats: bool | None = None) -> str:
    names = NOTE_NAMES
    if prefer_flats is True:
        names = FLAT_NOTE_NAMES
    elif prefer_flats is False:
        names = SHARP_NOTE_NAMES
    return names[pc % 12]


def midi_note_name(midi_note: int, prefer_flats: bool | None = None) -> str:
    octave = (midi_note // 12) - 1
    return f"{pitch_class_name(midi_note % 12, prefer_flats)}{octave}"


def prefer_flats_from_pitch_classes(pitch_classes: Iterable[int]) -> bool | None:
    saw_flat = False
    saw_sharp = False
    for pc in pitch_classes:
        name = NOTE_NAMES[pc % 12]
        saw_flat = saw_flat or "b" in name
        saw_sharp = saw_sharp or "#" in name
    if saw_flat:
        return True
    if saw_sharp:
        return False
    return None


def candidate_display_name(candidate: Candidate, prefer_flats: bool | None = None) -> str:
    root = pitch_class_name(candidate.root_pc, prefer_flats)
    default_root = pitch_class_name(candidate.root_pc)
    if candidate.name.startswith(default_root):
        return f"{root}{candidate.name[len(default_root):]}"
    return candidate.name


def candidate_display_label(candidate: Candidate, prefer_flats: bool | None = None) -> str:
    return f"{candidate_display_name(candidate, prefer_flats)} {candidate.score}"


def midi_to_pitch_class(midi_note: int) -> int:
    return midi_note % 12


def interval_name(root_pc: int, note_pc: int) -> str:
    return INTERVAL_NAMES[(note_pc - root_pc) % 12]


def analyze_midi_notes(
    midi_notes: Iterable[int],
    top_n: int = 12,
    context: Candidate | None = None,
) -> MeasureAnalysis:
    pitch_classes = [midi_to_pitch_class(note) for note in midi_notes]
    return analyze_pitch_classes(pitch_classes, top_n=top_n, context=context)


def analyze_pitch_classes(
    pitch_classes: Iterable[int],
    top_n: int = 12,
    context: Candidate | None = None,
) -> MeasureAnalysis:
    normalized = tuple(pc % 12 for pc in pitch_classes)
    if not normalized:
        return MeasureAnalysis((), (), ())

    weights = Counter(normalized)
    scale_candidates = _rank_scale_candidates(weights, top_n=top_n, context=context)
    if context is not None and len(weights) <= 2:
        scale_candidates = _promote_context_scale(scale_candidates, context, top_n)
    chord_candidates = _rank_chord_candidates(weights, top_n=top_n, context=context)
    return MeasureAnalysis(
        note_pitch_classes=tuple(sorted(weights)),
        scale_candidates=tuple(scale_candidates),
        chord_candidates=tuple(chord_candidates),
    )


def _promote_context_scale(
    candidates: list[Candidate],
    context: Candidate,
    top_n: int,
) -> list[Candidate]:
    promoted: Candidate | None = None
    for candidate in candidates:
        if candidate.name == context.name:
            promoted = replace(candidate, score=max(candidate.score, candidates[0].score if candidates else context.score))
            break
    if promoted is None:
        promoted = Candidate(
            kind="scale",
            name=context.name,
            root_pc=context.root_pc,
            intervals=context.intervals,
            score=max(85, candidates[0].score if candidates else context.score),
            matched_notes=0,
            total_notes=0,
            outside_notes=0,
        )
    return [promoted] + [candidate for candidate in candidates if candidate.name != promoted.name][: max(0, top_n - 1)]


def _rank_scale_candidates(
    weights: Counter[int],
    top_n: int,
    context: Candidate | None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    total_weight = sum(weights.values())
    observed = set(weights)

    for root_pc in range(12):
        for scale_name, intervals in SCALE_PATTERNS:
            scale_pcs = {(root_pc + interval) % 12 for interval in intervals}
            inside_weight = sum(count for pc, count in weights.items() if pc in scale_pcs)
            outside_weight = total_weight - inside_weight
            matched_distinct = len(observed & scale_pcs)

            fit = inside_weight / total_weight
            specificity = matched_distinct / len(intervals)
            root_bonus = min(weights.get(root_pc, 0) / total_weight, 0.25)
            fifth_bonus = 0.05 if (root_pc + 7) % 12 in observed else 0.0
            penalty = min(outside_weight / total_weight, 0.5)

            score = round((fit * 72) + (specificity * 18) + (root_bonus * 28) + (fifth_bonus * 10) - (penalty * 20))
            score += _scale_context_adjustment(root_pc, intervals, weights, context)
            score = max(0, min(100, score))

            if score >= 45 or outside_weight == 0:
                candidates.append(
                    Candidate(
                        kind="scale",
                        name=f"{pitch_class_name(root_pc)} {scale_name}",
                        root_pc=root_pc,
                        intervals=tuple(intervals),
                        score=score,
                        matched_notes=inside_weight,
                        total_notes=total_weight,
                        outside_notes=outside_weight,
                    )
                )

    return _dedupe_and_sort(candidates, top_n)


def _rank_chord_candidates(
    weights: Counter[int],
    top_n: int,
    context: Candidate | None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    total_weight = sum(weights.values())
    observed = set(weights)

    for root_pc in range(12):
        for chord_name, suffix, intervals in CHORD_PATTERNS:
            chord_pcs = {(root_pc + interval) % 12 for interval in intervals}
            inside_weight = sum(count for pc, count in weights.items() if pc in chord_pcs)
            outside_weight = total_weight - inside_weight
            matched_distinct = len(observed & chord_pcs)

            fit = inside_weight / total_weight
            coverage = matched_distinct / len(intervals)
            root_bonus = min(weights.get(root_pc, 0) / total_weight, 0.25)
            third_bonus = _third_bonus(root_pc, observed, intervals)
            fifth_bonus = 0.06 if (root_pc + 7) % 12 in observed else 0.0
            penalty = min(outside_weight / total_weight, 0.6)
            extension_penalty = max(0, len(intervals) - 4) * 7

            score = round((fit * 58) + (coverage * 27) + (root_bonus * 30) + (third_bonus * 10) + (fifth_bonus * 10) - (penalty * 24) - extension_penalty)
            score += _chord_context_adjustment(root_pc, intervals, weights, context)
            score = max(0, min(100, score))

            if score >= 45 or outside_weight == 0:
                display_name = f"{pitch_class_name(root_pc)}{suffix}"
                candidates.append(
                    Candidate(
                        kind="chord",
                        name=display_name,
                        root_pc=root_pc,
                        intervals=tuple(intervals),
                        score=score,
                        matched_notes=inside_weight,
                        total_notes=total_weight,
                        outside_notes=outside_weight,
                    )
                )

    return _dedupe_and_sort(candidates, top_n)


def _third_bonus(root_pc: int, observed: set[int], intervals: Sequence[int]) -> float:
    major_third = (root_pc + 4) % 12
    minor_third = (root_pc + 3) % 12
    if 4 in intervals and major_third in observed:
        return 0.08
    if 3 in intervals and minor_third in observed:
        return 0.08
    if 2 in intervals or 5 in intervals:
        return 0.03
    return 0.0


def _scale_context_adjustment(
    root_pc: int,
    intervals: Sequence[int],
    weights: Counter[int],
    context: Candidate | None,
) -> int:
    if context is None:
        return 0

    scale_pcs = {(root_pc + interval) % 12 for interval in intervals}
    context_pcs = set(context.pitch_classes)
    total_weight = max(1, sum(weights.values()))
    observed_outside_context = sum(
        count for pc, count in weights.items() if pc not in context_pcs
    ) / total_weight

    overlap = len(scale_pcs & context_pcs) / len(scale_pcs)
    adjustment = round((overlap - 0.55) * 12)
    if scale_pcs == context_pcs:
        adjustment += 8
    elif scale_pcs.issubset(context_pcs):
        adjustment += 5
    if root_pc == context.root_pc:
        adjustment += 10

    outside_candidate_pcs = len(scale_pcs - context_pcs)
    if observed_outside_context <= 0.15:
        adjustment -= max(0, outside_candidate_pcs - 1) * 2
    else:
        adjustment -= round(observed_outside_context * 6)
    return adjustment


def _chord_context_adjustment(
    root_pc: int,
    intervals: Sequence[int],
    weights: Counter[int],
    context: Candidate | None,
) -> int:
    if context is None:
        return 0

    chord_pcs = {(root_pc + interval) % 12 for interval in intervals}
    context_pcs = set(context.pitch_classes)
    total_weight = max(1, sum(weights.values()))
    observed_outside_context = sum(
        count for pc, count in weights.items() if pc not in context_pcs
    ) / total_weight

    overlap = len(chord_pcs & context_pcs) / len(chord_pcs)
    adjustment = round((overlap - 0.45) * 10)
    if chord_pcs.issubset(context_pcs):
        adjustment += 8
    if root_pc in context_pcs:
        adjustment += 2
    if root_pc == context.root_pc:
        adjustment += 3

    outside_candidate_pcs = len(chord_pcs - context_pcs)
    if observed_outside_context <= 0.15:
        adjustment -= outside_candidate_pcs * 3
    else:
        adjustment -= round(observed_outside_context * 6)
    return adjustment


def _dedupe_and_sort(candidates: Iterable[Candidate], top_n: int) -> list[Candidate]:
    best_by_name: dict[str, Candidate] = {}
    for candidate in candidates:
        current = best_by_name.get(candidate.name)
        if current is None or candidate.score > current.score:
            best_by_name[candidate.name] = candidate
    return sorted(
        best_by_name.values(),
        key=lambda candidate: (
            candidate.score,
            -candidate.outside_notes,
            candidate.matched_notes,
            candidate.name,
        ),
        reverse=True,
    )[:top_n]
