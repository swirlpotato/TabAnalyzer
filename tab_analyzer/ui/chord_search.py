from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QObject, pyqtSignal

from ..chord_finder import ChordMatch, find_chords_by_filter, find_chords_containing_pitches
from ..chord_positions import (
    CHORD_POSITION_CATEGORIES,
    ChordPosition,
    MAX_CHORD_POSITIONS,
    MAX_FRET_SPAN,
    generate_chord_positions,
)


MAX_CHORD_FINDER_RESULTS = 120


class _ChordFinderSearchParams(NamedTuple):
    note_pcs: tuple[int, ...]
    selected_positions: tuple[tuple[int, int], ...]
    root_filter: int | None
    type_filter: str | None
    string_pitches: tuple[int, ...]
    fret_count: int


class _ChordFinderSearchResult(NamedTuple):
    matches: tuple[ChordMatch, ...]
    entries: tuple[tuple[ChordMatch, ChordPosition], ...]
    match_count: int


def _chord_finder_search_results(params: _ChordFinderSearchParams) -> _ChordFinderSearchResult:
    note_pcs = params.note_pcs
    selected_positions = params.selected_positions
    if len(selected_positions) == 1:
        return _ChordFinderSearchResult((), (), 0)

    if note_pcs:
        matches = find_chords_containing_pitches(
            note_pcs,
            root_pc=params.root_filter,
            chord_type_suffix=params.type_filter,
        )
    elif params.root_filter is None or params.type_filter is None:
        matches = ()
    else:
        matches = find_chords_by_filter(
            root_pc=params.root_filter,
            chord_type_suffix=params.type_filter,
        )

    if not matches or (note_pcs and not _selected_fret_span_can_fit(selected_positions)):
        return _ChordFinderSearchResult((), (), 0)

    entries: list[tuple[ChordMatch, ChordPosition]] = []
    listed_matches: list[ChordMatch] = []
    position_cache: dict[tuple[int, str, tuple[int, ...]], tuple[ChordPosition, ...]] = {}
    positions_per_filter_chord = 20 if not note_pcs and params.root_filter is not None and params.type_filter is not None else 1

    for match in matches:
        positions = _positions_for_chord_finder_match(match, params, position_cache)
        if note_pcs:
            positions = tuple(position for position in positions if _position_contains_selected_frets(position, selected_positions))
        if not positions:
            continue
        for position in positions[:positions_per_filter_chord]:
            entries.append((match, position))
            listed_matches.append(match)
            if len(entries) >= MAX_CHORD_FINDER_RESULTS:
                break
        if len(entries) >= MAX_CHORD_FINDER_RESULTS:
            break

    return _ChordFinderSearchResult(tuple(listed_matches), tuple(entries), len(entries))


def _positions_for_chord_finder_match(
    match: ChordMatch,
    params: _ChordFinderSearchParams,
    position_cache: dict[tuple[int, str, tuple[int, ...]], tuple[ChordPosition, ...]],
) -> tuple[ChordPosition, ...]:
    key = (match.candidate.root_pc, match.chord_type.suffix, match.candidate.intervals)
    if key not in position_cache:
        positions = generate_chord_positions(
            match.candidate,
            params.string_pitches,
            params.fret_count,
            max_positions=MAX_CHORD_POSITIONS * len(CHORD_POSITION_CATEGORIES),
        )
        position_cache[key] = tuple(position for position in positions if _barre_open_strings_are_playable(position))
    return position_cache[key]


def _position_contains_selected_frets(position: ChordPosition, selected_positions: tuple[tuple[int, int], ...]) -> bool:
    for string_index, fret in selected_positions:
        if string_index < 0 or string_index >= len(position.frets_high_to_low):
            return False
        if position.frets_high_to_low[string_index] != fret:
            return False
    return True


def _selected_fret_span_can_fit(selected_positions: tuple[tuple[int, int], ...]) -> bool:
    fretted = [fret for _string_index, fret in selected_positions if fret > 0]
    if not fretted:
        return True
    if 0 in [fret for _string_index, fret in selected_positions] and max(fretted) > MAX_FRET_SPAN - 1:
        return False
    return max(fretted) - min(fretted) <= MAX_FRET_SPAN - 1


def _barre_open_strings_are_playable(position: ChordPosition) -> bool:
    if position.barre_fret is None:
        return True
    barre_strings = [
        string_index
        for string_index, fret in enumerate(position.frets_high_to_low)
        if fret == position.barre_fret
    ]
    if len(barre_strings) < 2:
        return True
    thinnest_barred_string = min(barre_strings)
    return all(
        fret != 0
        for string_index, fret in enumerate(position.frets_high_to_low)
        if string_index < thinnest_barred_string
    )


class _ChordFinderSearchWorker(QObject):
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)

    def __init__(self, token: int, params: _ChordFinderSearchParams) -> None:
        super().__init__()
        self.token = token
        self.params = params

    def run(self) -> None:
        try:
            self.finished.emit(self.token, _chord_finder_search_results(self.params))
        except Exception as exc:  # noqa: BLE001 - background errors should not take down the UI.
            self.failed.emit(self.token, str(exc))
