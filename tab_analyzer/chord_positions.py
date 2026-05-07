"""Generate practical guitar chord positions for analyzed chord candidates."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .analysis import Candidate, candidate_display_name, pitch_class_name
from .i18n import tr


RULE_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "chord_position_rules.json"
MAX_CHORD_POSITIONS = 40
MAX_FRET_SPAN = 4
MAX_DISPLAY_FRET = 15
MAX_FINGERS = 4
MUTED = -1
CHORD_POSITION_CATEGORIES = (
    "Triad",
    "CAGED system",
    "Open",
    "Barre/Movable",
    "Shell voicing",
    "Drop 2",
    "Drop 3",
    "Inversion/Slash",
    "Extended/Color",
    "Power/Sus",
    "Other",
)


@dataclass(frozen=True)
class ChordPosition:
    frets_high_to_low: tuple[int, ...]
    label: str
    finger_count: int
    muted_finger_count: int
    barre_fret: int | None
    min_fret: int
    max_fret: int
    present_intervals: tuple[int, ...]
    missing_intervals: tuple[int, ...]
    bass_interval: int
    root_string_numbers: tuple[int, ...]
    category: str
    categories: tuple[str, ...]

    @property
    def total_finger_cost(self) -> int:
        return self.finger_count + self.muted_finger_count

    @property
    def fretted_count(self) -> int:
        return sum(1 for fret in self.frets_high_to_low if fret > 0)

    @property
    def muted_count(self) -> int:
        return sum(1 for fret in self.frets_high_to_low if fret == MUTED)

    @property
    def open_count(self) -> int:
        return sum(1 for fret in self.frets_high_to_low if fret == 0)


def generate_chord_positions(
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    max_positions: int = MAX_CHORD_POSITIONS,
) -> tuple[ChordPosition, ...]:
    if not string_pitches_high_to_low:
        return ()

    chord_pcs = set(candidate.pitch_classes)
    core_intervals = _core_intervals(candidate)
    required_intervals = _required_intervals(candidate)
    shell_intervals = _shell_intervals(candidate)
    max_fret = min(fret_count, MAX_DISPLAY_FRET)
    positions: list[ChordPosition] = []
    seen: set[tuple[int, ...]] = set()

    for window_start in range(0, max(0, max_fret - MAX_FRET_SPAN + 2)):
        choices_by_string = [
            _string_choices(open_midi, chord_pcs, window_start, max_fret)
            for open_midi in string_pitches_high_to_low
        ]
        for frets in _product_choices(choices_by_string):
            if frets in seen:
                continue
            seen.add(frets)
            position = _evaluate_position(
                frets,
                candidate,
                string_pitches_high_to_low,
                core_intervals,
                required_intervals,
                shell_intervals,
            )
            if position is not None:
                positions.append(position)

    positions.sort(key=lambda position: _position_sort_key(position))
    positions = _dedupe_equivalent_positions(positions)
    return tuple(_limit_position_variety(positions, max_positions))


def chord_position_display_name(
    candidate: Candidate,
    position: ChordPosition,
    prefer_flats: bool | None,
) -> str:
    original_name = candidate_display_name(candidate, prefer_flats)
    if position.bass_interval == 0:
        return original_name

    bass_name = pitch_class_name((candidate.root_pc + position.bass_interval) % 12, prefer_flats)
    slash_name = f"{original_name}/{bass_name}"
    inversion_label = chord_position_inversion_label(candidate, position.bass_interval)
    if inversion_label is None:
        return slash_name
    return f"{slash_name} ({original_name}, {inversion_label})"


def chord_position_inversion_label(candidate: Candidate, bass_interval: int) -> str | None:
    if bass_interval == 0:
        return None
    inversion_order = _inversion_intervals(candidate)
    try:
        inversion_index = inversion_order.index(bass_interval)
    except ValueError:
        return None
    if inversion_index == 0:
        return None
    return tr("{ordinal} inversion").format(ordinal=_ordinal(inversion_index))


def filter_chord_positions_by_root_string(
    positions: Iterable[ChordPosition],
    root_string_number: int | None,
) -> tuple[ChordPosition, ...]:
    if root_string_number is None:
        return tuple(positions)
    return tuple(position for position in positions if root_string_number in position.root_string_numbers)


def filter_chord_positions_by_category(
    positions: Iterable[ChordPosition],
    category: str | None,
) -> tuple[ChordPosition, ...]:
    if category is None:
        return tuple(positions)
    return tuple(position for position in positions if category in position.categories)


def filter_chord_positions(
    positions: Iterable[ChordPosition],
    root_string_number: int | None,
    category: str | None,
    max_positions: int = MAX_CHORD_POSITIONS,
) -> tuple[ChordPosition, ...]:
    root_filtered = filter_chord_positions_by_root_string(positions, root_string_number)
    category_filtered = filter_chord_positions_by_category(root_filtered, category)
    return category_filtered[:max_positions]


def group_chord_positions_by_category(
    positions: Iterable[ChordPosition],
) -> tuple[tuple[str, tuple[ChordPosition, ...]], ...]:
    grouped = {category: [] for category in CHORD_POSITION_CATEGORIES}
    for position in positions:
        category = position.category if position.category in grouped else "Other"
        grouped[category].append(position)
    return tuple(
        (category, tuple(category_positions))
        for category, category_positions in grouped.items()
        if category_positions
    )


def render_chord_positions_html(
    song_title: str,
    track_name: str,
    measure_number: int | None,
    candidate: Candidate | None,
    string_pitches_high_to_low: tuple[int, ...],
    fret_count: int,
    prefer_flats: bool | None,
) -> str:
    if candidate is None:
        return _page(
            tr("Chord positions"),
            [
                tr("Click a measure chord name to show up to 20 playable chord positions in this tab."),
                tr("When a scale is selected, or nothing is selected, the song analysis tab remains the default."),
            ],
        )

    positions = generate_chord_positions(candidate, string_pitches_high_to_low, fret_count)
    chord_name = candidate_display_name(candidate, prefer_flats)
    title = (
        tr("M{measure}: {chord} chord positions").format(measure=measure_number, chord=chord_name)
        if measure_number is not None
        else tr("{chord} chord positions").format(chord=chord_name)
    )
    if not positions:
        return _page(
            title,
            [
                f"{html.escape(song_title)} / {html.escape(track_name)}",
                tr("No practical chord positions were found within the current limits. Try omitting extensions or choosing another chord candidate."),
            ],
        )

    diagrams = "\n".join(
        _position_card(index, position, candidate, string_pitches_high_to_low, prefer_flats)
        for index, position in enumerate(positions, start=1)
    )
    sources = _source_links()
    return f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; color: #253044; font-size: 13px; line-height: 1.45; }}
        h2 {{ font-size: 16px; margin: 0 0 8px 0; }}
        p {{ margin: 6px 0; }}
        a {{ color: #2468d8; text-decoration: none; }}
        .card {{ border: 1px solid #d6deea; border-radius: 7px; padding: 8px; margin: 8px 0; background: #ffffff; }}
        .meta {{ color: #526071; font-size: 12px; }}
        .diagram {{ margin: 8px auto 2px; border-collapse: collapse; background: #fbfcff; }}
        .diagram td {{ min-width: 34px; height: 29px; text-align: center; vertical-align: middle; }}
        .fret-head {{ border: 0; color: #697586; font-size: 10px; height: 16px; }}
        .string-label {{ border: 0; color: #4b5563; font-size: 11px; font-weight: 700; min-width: 24px; }}
        .status {{ border: 0; min-width: 20px; font-size: 12px; }}
        .fret-cell {{ border: 1px solid #c3cbd6; background: #f8fafc; }}
        .nut-cell {{ border-left: 4px solid #5e6878; }}
        .note-cell {{ background: #ecfdf5; }}
        .barre-cell {{ background: #fff7cc; }}
        .mark {{ display: inline-block; min-width: 25px; padding: 2px 3px; font-weight: 700; line-height: 1.0; color: #111827; background: #bbf7d0; border: 1px solid #22c55e; }}
        .barre-mark {{ background: #fde68a; border-color: #b45309; }}
        .degree {{ font-size: 9px; color: #253044; }}
        .mute {{ color: #9b1c1c; font-weight: 700; }}
        .open {{ color: #166534; font-weight: 700; }}
        hr {{ border: 0; border-top: 1px solid #d8dee8; margin: 10px 0 6px; }}
    </style>
    </head>
    <body>
        <h2>{html.escape(title)}</h2>
        <p class="meta">{html.escape(song_title)} / {html.escape(track_name)}</p>
        {diagrams}
        <hr>
        <p><b>{tr("Reference sources")}</b>: {" - ".join(sources)}</p>
    </body>
    </html>
    """


def _string_choices(
    open_midi: int,
    chord_pcs: set[int],
    window_start: int,
    fret_count: int,
) -> tuple[int, ...]:
    choices: list[int] = [MUTED]
    if window_start == 0 and open_midi % 12 in chord_pcs:
        choices.append(0)
    for fret in range(max(1, window_start), min(fret_count, window_start + MAX_FRET_SPAN - 1) + 1):
        if (open_midi + fret) % 12 in chord_pcs:
            choices.append(fret)
    return tuple(choices)


def _product_choices(choices_by_string: list[tuple[int, ...]]) -> Iterable[tuple[int, ...]]:
    if not choices_by_string:
        yield ()
        return
    first, *rest = choices_by_string
    for choice in first:
        for tail in _product_choices(rest):
            yield (choice,) + tail


def _evaluate_position(
    frets: tuple[int, ...],
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    core_intervals: set[int],
    required_intervals: set[int],
    shell_intervals: set[int],
) -> ChordPosition | None:
    sounding = [(index, fret) for index, fret in enumerate(frets) if fret >= 0]
    if len(sounding) < _minimum_sounding_strings(core_intervals):
        return None

    fretted = [fret for _index, fret in sounding if fret > 0]
    if fretted and max(fretted) - min(fretted) > MAX_FRET_SPAN - 1:
        return None
    if fretted and min(fretted) > 4 and any(fret == 0 for _index, fret in sounding):
        return None

    present_intervals = {
        ((string_pitches_high_to_low[index] + fret) % 12 - candidate.root_pc) % 12
        for index, fret in sounding
    }
    if 0 not in present_intervals:
        return None
    if not required_intervals.issubset(present_intervals):
        return None
    if _requires_altered_tension(candidate) and not ({1, 3, 6, 8} & present_intervals):
        return None

    label = _position_label(present_intervals, core_intervals, shell_intervals, len(sounding))
    if label is None:
        return None

    muted_finger_count = _inner_muted_string_count(frets)
    barre_fret = _barre_fret(frets)
    finger_count = _finger_count(frets, barre_fret)
    if finger_count + muted_finger_count > MAX_FINGERS:
        return None

    bass_index, bass_fret = min(
        sounding,
        key=lambda item: string_pitches_high_to_low[item[0]] + item[1],
    )
    bass_interval = ((string_pitches_high_to_low[bass_index] + bass_fret) % 12 - candidate.root_pc) % 12
    min_fret = min(fretted) if fretted else 0
    max_fret = max(fretted) if fretted else 0
    missing = tuple(interval for interval in candidate.intervals if interval not in present_intervals)
    root_string_numbers = tuple(
        index + 1
        for index, fret in sounding
        if ((string_pitches_high_to_low[index] + fret) % 12 - candidate.root_pc) % 12 == 0
    )
    categories = _position_categories(
        candidate,
        frets,
        present_intervals,
        core_intervals,
        shell_intervals,
        barre_fret,
        bass_interval,
    )
    category = _primary_position_category(categories)
    return ChordPosition(
        frets_high_to_low=frets,
        label=label,
        finger_count=finger_count,
        muted_finger_count=muted_finger_count,
        barre_fret=barre_fret,
        min_fret=min_fret,
        max_fret=max_fret,
        present_intervals=tuple(sorted(present_intervals)),
        missing_intervals=missing,
        bass_interval=bass_interval,
        root_string_numbers=root_string_numbers,
        category=category,
        categories=categories,
    )


def _core_intervals(candidate: Candidate) -> set[int]:
    intervals = set(candidate.intervals)
    if "quartal" in candidate.name.lower():
        return {0, 5, 10} & intervals or {0, 5}
    if intervals == {0, 7}:
        return {0, 7}
    if 2 in intervals and 4 not in intervals and 3 not in intervals:
        return {0, 2, 7} & intervals
    if 5 in intervals and 4 not in intervals and 3 not in intervals:
        return {0, 5, 7} & intervals
    third = 4 if 4 in intervals else 3 if 3 in intervals else None
    fifth = 7 if 7 in intervals else 6 if 6 in intervals else 8 if 8 in intervals else None
    core = {0}
    if third is not None:
        core.add(third)
    if fifth is not None:
        core.add(fifth)
    return core


def _required_intervals(candidate: Candidate) -> set[int]:
    intervals = set(candidate.intervals)
    suffix = _candidate_suffix(candidate)
    required = {0}

    if "quartal" in suffix:
        return ({0, 5, 10} & intervals) or ({0, 5} & intervals) or {0}
    if intervals == {0, 7} or suffix == "5":
        return {0, 7}

    if 5 in intervals and 4 not in intervals and 3 not in intervals:
        required.add(5)
    elif 2 in intervals and 4 not in intervals and 3 not in intervals:
        required.add(2)
    else:
        third = 4 if 4 in intervals else 3 if 3 in intervals else None
        if third is not None:
            required.add(third)

    seventh = _seventh_interval(intervals)
    if seventh is not None:
        required.add(seventh)

    if _is_simple_chord_suffix(suffix):
        fifth = _fifth_interval(intervals)
        if fifth is not None:
            required.add(fifth)

    if "b5" in suffix and 6 in intervals:
        required.add(6)
    if "#5" in suffix and 8 in intervals:
        required.add(8)

    if "b9" in suffix and 1 in intervals:
        required.add(1)
    if "#9" in suffix and 3 in intervals:
        required.add(3)
    if _has_natural_extension(suffix, "9") and 2 in intervals:
        required.add(2)

    if "#11" in suffix and 6 in intervals:
        required.add(6)
    elif _has_natural_extension(suffix, "11") and 5 in intervals:
        required.add(5)
        if 2 in intervals:
            required.add(2)

    if "b13" in suffix and 8 in intervals:
        required.add(8)
    elif _has_natural_extension(suffix, "13") and 9 in intervals:
        required.add(9)

    if _has_sixth_suffix(suffix) and 9 in intervals:
        required.add(9)

    return required & intervals


def _candidate_suffix(candidate: Candidate) -> str:
    name = candidate.name.strip()
    root = pitch_class_name(candidate.root_pc)
    suffix = name[len(root):] if name.startswith(root) else name
    return suffix.lower().replace("♯", "#").replace("♭", "b").replace("Δ", "maj")


def _seventh_interval(intervals: set[int]) -> int | None:
    if 10 in intervals:
        return 10
    if 11 in intervals:
        return 11
    if 9 in intervals and 10 not in intervals and 11 not in intervals and 2 not in intervals:
        return 9
    return None


def _fifth_interval(intervals: set[int]) -> int | None:
    if 7 in intervals:
        return 7
    if 6 in intervals:
        return 6
    if 8 in intervals:
        return 8
    return None


def _is_simple_chord_suffix(suffix: str) -> bool:
    simple_suffixes = {
        "",
        "m",
        "min",
        "minor",
        "dim",
        "aug",
        "+",
        "sus",
        "sus2",
        "sus4",
    }
    return suffix in simple_suffixes


def _has_natural_extension(suffix: str, extension: str) -> bool:
    token_start = suffix.find(extension)
    while token_start != -1:
        prefix = suffix[token_start - 1] if token_start > 0 else ""
        if prefix not in {"b", "#"}:
            return True
        token_start = suffix.find(extension, token_start + len(extension))
    return False


def _has_sixth_suffix(suffix: str) -> bool:
    return suffix in {"6", "m6", "min6"} or suffix.endswith("6/9")


def _requires_altered_tension(candidate: Candidate) -> bool:
    return "alt" in _candidate_suffix(candidate)


def _inversion_intervals(candidate: Candidate) -> tuple[int, ...]:
    intervals = set(candidate.intervals)
    suffix = _candidate_suffix(candidate)
    ordered: list[int] = [0]

    def append(interval: int | None) -> None:
        if interval is not None and interval in intervals and interval not in ordered:
            ordered.append(interval)

    if "sus2" in suffix and 2 in intervals and 4 not in intervals and 3 not in intervals:
        append(2)
    elif "sus" in suffix and 5 in intervals and 4 not in intervals and 3 not in intervals:
        append(5)
    elif 4 in intervals:
        append(4)
    elif 3 in intervals:
        append(3)

    append(_fifth_interval(intervals))
    append(_seventh_interval(intervals))
    append(_extension_interval(suffix, "9", intervals))
    append(_extension_interval(suffix, "11", intervals))
    append(_extension_interval(suffix, "13", intervals))

    for interval in candidate.intervals:
        append(interval)
    return tuple(ordered)


def _extension_interval(suffix: str, extension: str, intervals: set[int]) -> int | None:
    if extension == "9":
        if "b9" in suffix:
            return 1
        if "#9" in suffix:
            return 3
        if _has_natural_extension(suffix, "9"):
            return 2
    if extension == "11":
        if "#11" in suffix:
            return 6
        if _has_natural_extension(suffix, "11"):
            return 5
    if extension == "13":
        if "b13" in suffix:
            return 8
        if _has_natural_extension(suffix, "13") or _has_sixth_suffix(suffix):
            return 9
    return None


def _ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _shell_intervals(candidate: Candidate) -> set[int]:
    intervals = set(candidate.intervals)
    third = 4 if 4 in intervals else 3 if 3 in intervals else None
    seventh = 10 if 10 in intervals else 11 if 11 in intervals else None
    if third is None or seventh is None:
        return set()
    return {0, third, seventh}


def _minimum_sounding_strings(core_intervals: set[int]) -> int:
    return 2 if core_intervals <= {0, 7} else min(3, len(core_intervals))


def _position_label(
    present_intervals: set[int],
    core_intervals: set[int],
    shell_intervals: set[int],
    sounding_count: int,
) -> str | None:
    if present_intervals <= core_intervals:
        if len(present_intervals) == 3 and sounding_count == 3:
            return "Triad/Core"
        return "Core"
    if shell_intervals and shell_intervals.issubset(present_intervals):
        if present_intervals <= shell_intervals:
            return "Shell"
        return "Shell + Color"
    if len(present_intervals - core_intervals) <= 2:
        return "Color"
    return "Fuller"


def _position_categories(
    candidate: Candidate,
    frets: tuple[int, ...],
    present_intervals: set[int],
    core_intervals: set[int],
    shell_intervals: set[int],
    barre_fret: int | None,
    bass_interval: int,
) -> tuple[str, ...]:
    sounding_indexes = [index for index, fret in enumerate(frets) if fret >= 0]
    open_count = sum(1 for fret in frets if fret == 0)
    categories: list[str] = []

    if _is_triad_category(candidate, present_intervals, len(sounding_indexes)):
        categories.append("Triad")
    if _is_caged_category(candidate, frets):
        categories.append("CAGED system")
    if open_count and _is_first_position(frets):
        categories.append("Open")
    if shell_intervals and present_intervals <= shell_intervals:
        categories.append("Shell voicing")
    if _is_drop2_category(frets, sounding_indexes, present_intervals):
        categories.append("Drop 2")
    if _is_drop3_category(frets, sounding_indexes, present_intervals):
        categories.append("Drop 3")
    if barre_fret is not None:
        categories.append("Barre/Movable")
    if bass_interval != 0:
        categories.append("Inversion/Slash")
    if _is_power_or_sus_category(candidate, present_intervals):
        categories.append("Power/Sus")
    if present_intervals - core_intervals:
        categories.append("Extended/Color")
    if not categories:
        categories.append("Other")
    return tuple(dict.fromkeys(categories))


def _primary_position_category(categories: tuple[str, ...]) -> str:
    for category in CHORD_POSITION_CATEGORIES:
        if category in categories:
            return category
    return "Other"


def _is_triad_category(candidate: Candidate, present_intervals: set[int], sounding_count: int) -> bool:
    triad = _triad_intervals(candidate)
    return triad is not None and present_intervals == triad and sounding_count == 3


def _triad_intervals(candidate: Candidate) -> set[int] | None:
    intervals = set(candidate.intervals)
    third = 4 if 4 in intervals else 3 if 3 in intervals else None
    fifth = _fifth_interval(intervals)
    if third is None or fifth is None:
        return None
    return {0, third, fifth}


def _is_caged_category(
    candidate: Candidate,
    frets: tuple[int, ...],
) -> bool:
    return _matches_caged_template(candidate, frets)


def _matches_caged_template(candidate: Candidate, frets: tuple[int, ...]) -> bool:
    triad = _triad_intervals(candidate)
    if triad == {0, 4, 7}:
        templates = _major_caged_templates_for_root(candidate.root_pc)
    elif triad == {0, 3, 7}:
        templates = _minor_caged_templates_for_root(candidate.root_pc)
    else:
        return False
    return frets in templates


def _major_caged_templates_for_root(root_pc: int) -> set[tuple[int, ...]]:
    c_major_templates = (
        (0, 1, 0, 2, 3, MUTED),
        (3, 5, 5, 5, 3, MUTED),
        (8, 5, 5, 5, 7, 8),
        (8, 8, 9, 10, 10, 8),
        (12, 13, 12, 10, MUTED, MUTED),
    )
    return _transpose_caged_templates(c_major_templates, root_pc)


def _minor_caged_templates_for_root(root_pc: int) -> set[tuple[int, ...]]:
    c_minor_templates = (
        (3, 4, 5, 5, 3, MUTED),
        (8, 8, 8, 10, 10, 8),
        (11, 13, 12, 10, MUTED, MUTED),
    )
    return _transpose_caged_templates(c_minor_templates, root_pc)


def _transpose_caged_templates(
    templates: tuple[tuple[int, ...], ...],
    root_pc: int,
) -> set[tuple[int, ...]]:
    transposed: set[tuple[int, ...]] = set()
    for template in templates:
        for octave in range(-2, 3):
            shift = root_pc + (12 * octave)
            frets = tuple(MUTED if fret == MUTED else fret + shift for fret in template)
            if all(fret == MUTED or fret >= 0 for fret in frets):
                transposed.add(frets)
    return transposed


def _is_first_position(frets: tuple[int, ...]) -> bool:
    fretted = [fret for fret in frets if fret > 0]
    return not fretted or max(fretted) <= 4


def _is_drop2_category(
    frets: tuple[int, ...],
    sounding_indexes: list[int],
    present_intervals: set[int],
) -> bool:
    return (
        len(sounding_indexes) == 4
        and _uses_adjacent_strings(sounding_indexes)
        and all(frets[index] > 0 for index in sounding_indexes)
        and len(present_intervals) >= 4
    )


def _is_drop3_category(
    frets: tuple[int, ...],
    sounding_indexes: list[int],
    present_intervals: set[int],
) -> bool:
    return (
        len(sounding_indexes) == 4
        and _string_span_gap_count(sounding_indexes) == 1
        and all(frets[index] > 0 for index in sounding_indexes)
        and len(present_intervals) >= 4
    )


def _uses_adjacent_strings(sounding_indexes: list[int]) -> bool:
    return bool(sounding_indexes) and max(sounding_indexes) - min(sounding_indexes) + 1 == len(sounding_indexes)


def _string_span_gap_count(sounding_indexes: list[int]) -> int:
    if not sounding_indexes:
        return 0
    return max(sounding_indexes) - min(sounding_indexes) + 1 - len(sounding_indexes)


def _is_power_or_sus_category(candidate: Candidate, present_intervals: set[int]) -> bool:
    intervals = set(candidate.intervals)
    if intervals <= {0, 7} or present_intervals <= {0, 7}:
        return True
    has_third = bool(present_intervals & {3, 4})
    has_sus = bool(present_intervals & {2, 5})
    return not has_third and has_sus


def _inner_muted_string_count(frets: tuple[int, ...]) -> int:
    sounding_indexes = [index for index, fret in enumerate(frets) if fret >= 0]
    if len(sounding_indexes) < 2:
        return 0
    left = min(sounding_indexes)
    right = max(sounding_indexes)
    return sum(1 for index in range(left, right + 1) if frets[index] == MUTED)


def _barre_fret(frets: tuple[int, ...]) -> int | None:
    fretted = [fret for fret in frets if fret > 0]
    if not fretted:
        return None
    lowest = min(fretted)
    barre_indexes = [index for index, fret in enumerate(frets) if fret == lowest]
    if len(barre_indexes) < 2:
        return None
    left = min(barre_indexes)
    right = max(barre_indexes)
    for index in range(left, right + 1):
        if frets[index] in {MUTED, 0}:
            return None
    return lowest


def _finger_count(frets: tuple[int, ...], barre_fret: int | None) -> int:
    fretted = [fret for fret in frets if fret > 0]
    if not fretted:
        return 0
    if barre_fret is None:
        return len(fretted)
    return 1 + sum(1 for fret in fretted if fret != barre_fret)


def _position_sort_key(position: ChordPosition) -> tuple[int, int, int, int, int, int, tuple[int, ...]]:
    label_order = {
        "Triad/Core": 0,
        "Core": 1,
        "Shell": 2,
        "Shell + Color": 3,
        "Color": 4,
        "Fuller": 5,
    }.get(position.label, 6)
    start = position.min_fret
    span = position.max_fret - position.min_fret if position.max_fret else 0
    return (
        label_order,
        position.total_finger_cost,
        position.fretted_count,
        position.muted_finger_count,
        position.muted_count,
        start,
        span,
        position.frets_high_to_low,
    )


def _dedupe_equivalent_positions(positions: list[ChordPosition]) -> list[ChordPosition]:
    unique: list[ChordPosition] = []
    seen: set[tuple[int | None, tuple[tuple[int, int], ...]]] = set()
    for position in positions:
        signature = _position_visual_signature(position)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(position)
    return unique


def _position_visual_signature(position: ChordPosition) -> tuple[int | None, tuple[tuple[int, int], ...]]:
    sounding_positions = tuple(
        (string_index, fret)
        for string_index, fret in enumerate(position.frets_high_to_low)
        if fret >= 0
    )
    return position.barre_fret, sounding_positions


def _limit_position_variety(positions: list[ChordPosition], max_positions: int) -> list[ChordPosition]:
    if len(positions) <= max_positions:
        return positions

    has_non_triad = any(position.label != "Triad/Core" for position in positions)
    primary: list[ChordPosition] = []
    skipped: list[ChordPosition] = []
    label_counts: dict[str, int] = {}
    caps = {
        "Triad/Core": 8 if has_non_triad else max_positions,
        "Core": 8,
        "Shell": 8,
        "Shell + Color": 8,
        "Color": 8,
        "Fuller": 8,
    }
    for position in positions:
        count = label_counts.get(position.label, 0)
        if count < caps.get(position.label, max_positions):
            primary.append(position)
            label_counts[position.label] = count + 1
        else:
            skipped.append(position)
        if len(primary) >= max_positions:
            break

    if len(primary) < max_positions:
        for position in skipped:
            primary.append(position)
            if len(primary) >= max_positions:
                break
    return primary[:max_positions]


def _position_card(
    index: int,
    position: ChordPosition,
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    prefer_flats: bool | None,
) -> str:
    fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
    missing = ", ".join(_interval_label(interval) for interval in position.missing_intervals) or tr("None")
    barre = tr(", barre {fret} fret").format(fret=position.barre_fret) if position.barre_fret is not None else ""
    range_start, range_end = _display_fret_range(position)
    meta = tr(
        "{label} - fingers {finger_count}{muted}{barre} - range {start}-{end} frets - low-to-high strings: {frets} - omitted notes: {missing}"
    ).format(
        label=tr(position.label),
        finger_count=position.finger_count,
        muted=tr(" + muted {count}").format(count=position.muted_finger_count) if position.muted_finger_count else "",
        barre=barre,
        start=range_start,
        end=range_end,
        frets=html.escape(fret_text),
        missing=html.escape(missing),
    )
    return f"""
    <div class="card">
        <b>{index}. {html.escape(chord_position_display_name(candidate, position, prefer_flats))}</b>
        <div class="meta">{meta}</div>
        {_diagram_table(position, candidate, string_pitches_high_to_low, prefer_flats)}
    </div>
    """


def _display_fret_range(position: ChordPosition) -> tuple[int, int]:
    if position.fretted_count == 0:
        return 0, MAX_FRET_SPAN - 1
    if position.open_count and position.max_fret <= MAX_FRET_SPAN - 1:
        return 0, MAX_FRET_SPAN - 1
    start = max(1, position.min_fret)
    return start, start + MAX_FRET_SPAN - 1


def _diagram_table(
    position: ChordPosition,
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    prefer_flats: bool | None,
) -> str:
    string_count = len(string_pitches_high_to_low)
    if string_count == 0:
        return ""

    display_indices = tuple(range(string_count))
    range_start, range_end = _display_fret_range(position)
    fret_headers = "".join(
        f'<td class="fret-head">{fret}</td>'
        for fret in range(range_start, range_end + 1)
    )

    rows: list[str] = [
        f'<tr><td class="string-label"></td><td class="status"></td>{fret_headers}</tr>',
    ]
    for string_index in display_indices:
        string_name = html.escape(pitch_class_name(string_pitches_high_to_low[string_index] % 12, prefer_flats))
        status = _string_status_cell(position.frets_high_to_low[string_index])
        cells = [
            _fret_cell(position, candidate, string_pitches_high_to_low, string_index, fret, range_start)
            for fret in range(range_start, range_end + 1)
        ]
        rows.append(f'<tr><td class="string-label">{string_name}</td>{status}{"".join(cells)}</tr>')

    return f'<table class="diagram">{"".join(rows)}</table>'


def _string_status_cell(fret: int) -> str:
    if fret == MUTED:
        return '<td class="status mute">x</td>'
    if fret == 0:
        return '<td class="status open">o</td>'
    return '<td class="status"></td>'


def _fret_cell(
    position: ChordPosition,
    candidate: Candidate,
    string_pitches_high_to_low: tuple[int, ...],
    string_index: int,
    fret: int,
    range_start: int,
) -> str:
    selected_fret = position.frets_high_to_low[string_index]
    nut_class = " nut-cell" if range_start == 0 and fret == 0 else ""
    if selected_fret != fret or selected_fret < 0:
        return f'<td class="fret-cell{nut_class}"></td>'
    interval = ((string_pitches_high_to_low[string_index] + fret) % 12 - candidate.root_pc) % 12
    cell_css = "barre-cell" if position.barre_fret == fret else "note-cell"
    mark_css = "barre-mark" if position.barre_fret == fret else ""
    return (
        f'<td class="fret-cell {cell_css}{nut_class}"><div class="mark {mark_css}">{fret}</div>'
        f'<div class="degree">{html.escape(_interval_label(interval))}</div></td>'
    )


def _interval_label(interval: int) -> str:
    labels = {
        0: "R",
        1: "b9",
        2: "9",
        3: "b3/#9",
        4: "3",
        5: "11",
        6: "b5/#11",
        7: "5",
        8: "b13/#5",
        9: "13",
        10: "b7",
        11: "7",
    }
    return labels[interval % 12]


def _load_rule_data() -> dict:
    try:
        return json.loads(RULE_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": (), "rules": ()}


def _rule_summary() -> str:
    data = _load_rule_data()
    rules = data.get("rules", ())
    if not rules:
        return tr("Positions within a four-fret span, one note per string, and four fingers are prioritized.")
    return "<br>".join(html.escape(rule) for rule in rules)


def _source_links() -> list[str]:
    links = []
    for source in _load_rule_data().get("sources", ()):
        title = html.escape(source.get("title", tr("source")))
        url = html.escape(source.get("url", ""))
        if url:
            links.append(f'<a href="{url}">{title}</a>')
    return links


def _page(title: str, paragraphs: list[str]) -> str:
    body = "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs if paragraph)
    sources = " - ".join(_source_links())
    source_html = f"<hr><p><b>{tr('Reference sources')}</b>: {sources}</p>" if sources else ""
    return f"""
    <html>
    <head>
    <style>
        body {{ font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; color: #253044; font-size: 13px; line-height: 1.45; }}
        h2 {{ font-size: 16px; margin: 0 0 8px 0; }}
        p {{ margin: 6px 0; }}
        a {{ color: #2468d8; text-decoration: none; }}
        hr {{ border: 0; border-top: 1px solid #d8dee8; margin: 10px 0 6px; }}
    </style>
    </head>
    <body>
        <h2>{html.escape(title)}</h2>
        {body}
        {source_html}
    </body>
    </html>
    """
