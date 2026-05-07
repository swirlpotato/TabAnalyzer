"""Tablature reading explanations backed by local reference data."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from .analysis import candidate_display_name
from .gp_loader import BeatData, MeasureData, SegmentData, SongData, TabNote
from .i18n import tr


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tab_reading_knowledge.json"
TICKS_PER_QUARTER = 960

TECHNIQUE_ORDER = (
    "palm_mute",
    "let_ring",
    "hammer_on",
    "pull_off",
    "legato",
    "slide",
    "bend",
    "release_bend",
    "vibrato",
    "dead_note",
    "ghost_note",
    "staccato",
    "accent",
    "harmonic",
    "tapping",
    "trill",
    "tremolo_picking",
    "tie",
)


class TabReadingKnowledge:
    def __init__(self, data_path: Path = DATA_PATH) -> None:
        self.data = json.loads(data_path.read_text(encoding="utf-8"))
        self.techniques: dict[str, dict[str, str]] = self.data.get("techniques", {})

    def source_links(self) -> list[str]:
        links: list[str] = []
        for source in self.data.get("sources", []):
            title = html.escape(source["title"])
            url = html.escape(source["url"])
            links.append(f'<a href="{url}">{title}</a>')
        return links

    def explain_song_selection(self, song: SongData | None, start_index: int, end_index: int) -> tuple[str, list[str]]:
        if song is None:
            return (
                tr("Tab playing explanation"),
                [
                    tr("Open a Guitar Pro file and select measures in the tab player to see fingering and technique explanations here."),
                    html.escape(self.data.get("basics", {}).get("line_order", "")),
                ],
            )

        if not song.track.measures:
            return f"{html.escape(song.title)}: {tr('Tab playing explanation')}", [tr("No measures to select.")]

        start_index, end_index = _clamp_range(start_index, end_index, len(song.track.measures))
        rows = [(measure, measure) for measure in song.track.measures[start_index : end_index + 1]]
        title = self._selection_title(song, rows)
        return title, self._paragraphs(song, rows)

    def explain_area(
        self,
        song: SongData | None,
        measure: MeasureData | None,
        segment: SegmentData | None,
    ) -> list[str]:
        if song is None or measure is None:
            return []
        area = segment if segment is not None else measure
        return self._paragraphs(song, [(measure, area)], compact=True)

    def technique_label(self, technique_id: str) -> str:
        return self.techniques.get(technique_id, {}).get("label", technique_id.replace("_", " "))

    def technique_symbol(self, technique_id: str) -> str:
        return self.techniques.get(technique_id, {}).get("symbol", "")

    def _selection_title(self, song: SongData, rows: list[tuple[MeasureData, MeasureData | SegmentData]]) -> str:
        first = rows[0][0].number
        last = rows[-1][0].number
        if first == last:
            return f"M{first} {tr('Tab playing explanation')}"
        return f"M{first}-M{last} {tr('Tab playing explanation')}"

    def _paragraphs(
        self,
        song: SongData,
        rows: list[tuple[MeasureData, MeasureData | SegmentData]],
        compact: bool = False,
    ) -> list[str]:
        areas = [area for _measure, area in rows]
        notes = [note for area in areas for note in area.notes]
        beats = [beat for area in areas for beat in area.beats if beat.notes]
        basics = self.data.get("basics", {})
        paragraphs: list[str] = []

        if not notes:
            return [f"<b>{tr('How to play')}</b>: {tr('This selection has no fretted numbers to play.')}"]

        if not compact:
            paragraphs.append(f"<b>{tr('Tab reading basics')}</b>: {html.escape(basics.get('line_order', ''))}")
            paragraphs.append(f"<b>{tr('Reading order')}</b>: {html.escape(basics.get('left_to_right', ''))}")

        paragraphs.append(self._range_summary(song, rows, notes, beats))
        paragraphs.append(self._rhythm_summary(rows, beats))

        chord_text = self._chord_and_line_summary(beats)
        if chord_text:
            paragraphs.append(chord_text)

        technique_text = self._technique_summary(notes)
        if technique_text:
            paragraphs.append(technique_text)
        elif not compact:
            paragraphs.append(
                f"<b>{tr('Technique marks')}</b>: "
                + tr("This selection has few separate technique marks. Fret the numbers accurately first, then match the rhythm and string changes.")
            )

        preview = self._sequence_preview(rows)
        if preview:
            paragraphs.append(preview)

        harmony = self._harmony_hint(song, rows)
        if harmony:
            paragraphs.append(harmony)

        if not compact:
            paragraphs.append(f"<b>{tr('Practice tip')}</b>: {html.escape(basics.get('position', ''))}")
        return paragraphs

    def _range_summary(
        self,
        song: SongData,
        rows: list[tuple[MeasureData, MeasureData | SegmentData]],
        notes: list[TabNote],
        beats: list[BeatData],
    ) -> str:
        measure_count = len({measure.number for measure, _area in rows})
        string_numbers = sorted({note.string for note in notes})
        fretted = [note.fret for note in notes if not note.is_muted and note.fret > 0]
        open_count = sum(1 for note in notes if not note.is_muted and note.fret == 0)
        muted_count = sum(1 for note in notes if note.is_muted)
        string_text = ", ".join(tr("string {number}").format(number=number) for number in string_numbers)
        fret_text = tr("mostly open strings")
        if fretted:
            low, high = min(fretted), max(fretted)
            fret_text = tr("{low}-{high} frets").format(low=low, high=high)
            if high - low <= 4:
                fret_text += tr(" in one position")
            else:
                fret_text += tr(" span, shift needed")
        extras = []
        if open_count:
            extras.append(tr("open {count}").format(count=open_count))
        if muted_count:
            extras.append(tr("muted {count}").format(count=muted_count))
        extra_text = f" ({', '.join(extras)})" if extras else ""
        tempo = f"{song.tempo} BPM"
        return f"<b>{tr('Selection')}</b>: " + tr(
            "{measure_count} measures, {event_count} playing events, {note_count} notes. "
            "Strings used: {strings}, frets: {frets}{extra}. "
            "Base tempo is {tempo}, and the player speed slider scales it proportionally."
        ).format(
            measure_count=measure_count,
            event_count=len(beats),
            note_count=len(notes),
            strings=html.escape(string_text),
            frets=html.escape(fret_text),
            extra=html.escape(extra_text),
            tempo=tempo,
        )

    def _rhythm_summary(self, rows: list[tuple[MeasureData, MeasureData | SegmentData]], beats: list[BeatData]) -> str:
        durations = Counter(_duration_name(beat.duration_ticks) for beat in beats)
        duration_text = ", ".join(f"{html.escape(name)} x{count}" for name, count in durations.most_common())
        time_signatures = sorted({measure.time_signature for measure, _area in rows})
        return f"<b>{tr('Rhythm')}</b>: " + tr(
            "The time signature is {time_signature}, and the main durations are {durations}. {rhythm}"
        ).format(
            time_signature=html.escape(", ".join(time_signatures)),
            durations=duration_text,
            rhythm=html.escape(self.data.get("basics", {}).get("rhythm", "")),
        )

    def _chord_and_line_summary(self, beats: list[BeatData]) -> str:
        chord_beats = [beat for beat in beats if len(beat.notes) >= 2]
        single_beats = [beat for beat in beats if len(beat.notes) == 1]
        if not chord_beats and not single_beats:
            return ""
        parts: list[str] = []
        if chord_beats:
            max_stack = max(len(beat.notes) for beat in chord_beats)
            parts.append(
                tr(
                    "Stacked notes occur {count} times, with up to {max_stack} notes played together. "
                    "Play stacked numbers at the same time, like chords or double-stops."
                ).format(count=len(chord_beats), max_stack=max_stack)
            )
        if single_beats:
            parts.append(tr("Single-note events occur {count} times. Check string changes slowly first.").format(count=len(single_beats)))
        return f"<b>{tr('Block character')}</b>: " + " ".join(parts)

    def _technique_summary(self, notes: list[TabNote]) -> str:
        counts: Counter[str] = Counter()
        for note in notes:
            counts.update(note.techniques)
        if not counts:
            return ""

        details: list[str] = []
        for technique_id in _sorted_techniques(counts):
            info = self.techniques.get(technique_id, {})
            label = html.escape(info.get("label", technique_id.replace("_", " ")))
            play = html.escape(info.get("play", info.get("summary", "")))
            symbol = info.get("symbol", "")
            symbol_text = f" ({html.escape(symbol)})" if symbol else ""
            details.append(f"{label}{symbol_text} x{counts[technique_id]}: {play}")
        return f"<b>{tr('Technique marks')}</b>: " + " / ".join(details)

    def _sequence_preview(self, rows: list[tuple[MeasureData, MeasureData | SegmentData]]) -> str:
        items: list[str] = []
        for measure, area in rows:
            for beat in area.beats:
                if not beat.notes:
                    continue
                note_text = " + ".join(_note_text(note) for note in sorted(beat.notes, key=lambda item: -item.string))
                items.append(f"M{measure.number} {_beat_label(measure, beat)} {note_text}")
                if len(items) >= 10:
                    break
            if len(items) >= 10:
                break
        if not items:
            return ""
        suffix = ""
        total = sum(1 for _measure, area in rows for beat in area.beats if beat.notes)
        if total > len(items):
            suffix = tr(" plus {count} more").format(count=total - len(items))
        return f"<b>{tr('Opening order')}</b>: " + " / ".join(html.escape(item) for item in items) + html.escape(suffix)

    def _harmony_hint(self, song: SongData, rows: list[tuple[MeasureData, MeasureData | SegmentData]]) -> str:
        labels: list[str] = []
        for measure, area in rows[:4]:
            scale = area.analysis.scale_candidates[0] if area.analysis.scale_candidates else None
            chord = area.analysis.chord_candidates[0] if area.analysis.chord_candidates else None
            if scale is None and chord is None:
                continue
            scale_text = candidate_display_name(scale, song.track.prefer_flats) if scale else "-"
            chord_text = candidate_display_name(chord, song.track.prefer_flats) if chord else "-"
            labels.append(tr("M{measure}: scale {scale}, chord {chord}").format(measure=measure.number, scale=scale_text, chord=chord_text))
        if not labels:
            return ""
        return f"<b>{tr('Analysis link')}</b>: " + " / ".join(html.escape(label) for label in labels)


def _clamp_range(start_index: int, end_index: int, measure_count: int) -> tuple[int, int]:
    if measure_count <= 0:
        return 0, 0
    start = max(0, min(start_index, measure_count - 1))
    end = max(0, min(end_index, measure_count - 1))
    if end < start:
        start, end = end, start
    return start, end


def _sorted_techniques(counts: Counter[str]) -> list[str]:
    order = {technique_id: index for index, technique_id in enumerate(TECHNIQUE_ORDER)}
    return sorted(counts, key=lambda item: (order.get(item, 999), item))


def _duration_name(ticks: int) -> str:
    values = {
        3840: "whole note",
        2880: "dotted half note",
        1920: "half note",
        1440: "dotted quarter note",
        960: "quarter note",
        720: "dotted eighth note",
        480: "eighth note",
        360: "dotted sixteenth note",
        320: "eighth-note triplet",
        240: "sixteenth note",
        160: "sixteenth-note triplet",
        120: "thirty-second note",
    }
    if ticks in values:
        return tr(values[ticks])
    beats = ticks / TICKS_PER_QUARTER
    return tr("{beats:.2f} beats").format(beats=beats)


def _beat_label(measure: MeasureData, beat: BeatData) -> str:
    numerator = _time_signature_numerator(measure.time_signature)
    ticks_per_beat = measure.length_ticks / max(1, numerator)
    beat_position = (beat.start_in_measure / ticks_per_beat) + 1
    if abs(beat_position - round(beat_position)) < 0.02:
        return tr("beat {number}").format(number=int(round(beat_position)))
    return tr("beat {number:.2f}").format(number=beat_position)


def _time_signature_numerator(time_signature: str) -> int:
    try:
        return max(1, int(time_signature.split("/", 1)[0]))
    except (ValueError, IndexError):
        return 4


def _note_text(note: TabNote) -> str:
    if note.is_muted:
        fret = "x"
    elif note.fret == 0:
        fret = "0"
    else:
        fret = str(note.fret)
    techniques = _short_technique_suffix(note.techniques)
    return tr("string {string} {fret}{techniques}").format(string=note.string, fret=fret, techniques=techniques)


def _short_technique_suffix(techniques: Iterable[str]) -> str:
    labels = {
        "hammer_on": "h",
        "pull_off": "p",
        "slide": "s",
        "bend": "b",
        "release_bend": "r",
        "vibrato": "~",
        "palm_mute": "PM",
        "let_ring": "LR",
        "dead_note": "x",
        "ghost_note": "ghost",
        "staccato": ".",
        "accent": ">",
        "harmonic": "harm",
        "tapping": "T",
        "trill": "tr",
        "tremolo_picking": "trem",
        "tie": "tie",
    }
    parts = [labels[item] for item in techniques if item in labels and item != "dead_note"]
    return f" ({', '.join(parts)})" if parts else ""
