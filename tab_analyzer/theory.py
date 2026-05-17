"""Harmony explanation generation based on local theory data."""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .analysis import Candidate, analyze_pitch_classes, candidate_display_name, interval_name, pitch_class_name
from .gp_loader import MeasureData, SegmentData, SongData, TabNote
from .i18n import tr
from .tab_knowledge import TabReadingKnowledge


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "harmony_knowledge.json"

ROMAN_BY_SEMITONE = {
    0: "I",
    1: "bII",
    2: "II",
    3: "bIII",
    4: "III",
    5: "IV",
    6: "#IV",
    7: "V",
    8: "bVI",
    9: "VI",
    10: "bVII",
    11: "VII",
}


@dataclass(frozen=True)
class ChordRole:
    roman: str
    function_id: str
    function_label: str
    function_meaning: str
    chromatic: bool


@dataclass(frozen=True)
class SongEvent:
    measure_number: int
    start_percent: int
    end_percent: int
    scale: Candidate | None
    chord: Candidate | None
    role: ChordRole | None
    note_count: int


class TheoryExplainer:
    def __init__(self, data_path: Path = DATA_PATH) -> None:
        self.data = json.loads(data_path.read_text(encoding="utf-8"))
        self.tab_knowledge = TabReadingKnowledge()

    def explain_selection(
        self,
        song: SongData | None,
        measure: MeasureData | None,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None,
    ) -> str:
        if song is None:
            return self._page(
                tr("Harmony explanation"),
                [tr("Open a Guitar Pro file to explain the selected measure scale, chord, and functional movement.")],
            )
        if measure is None:
            return self._page(
                tr("Harmony explanation"),
                [
                    tr("{title} was loaded.").format(title=html.escape(song.title)),
                    tr("Click a measure or segment scale/chord label in the upper tab to show the analysis reasons here."),
                ],
            )

        area = segment if segment is not None else measure
        prefer_flats = song.track.prefer_flats
        active_scale = self._active_scale(area, candidate, kind)
        active_chord = self._active_chord(area, candidate, kind)
        title = self._title(measure, segment, active_scale, active_chord, prefer_flats)
        paragraphs: list[str] = []

        if active_scale is not None:
            paragraphs.extend(self._scale_explanation(area, active_scale, active_chord, prefer_flats))
        if active_chord is not None:
            paragraphs.extend(self._chord_explanation(area, active_chord, active_scale, prefer_flats))

        paragraphs.extend(self._progression_explanation(measure, segment, active_scale, prefer_flats))
        paragraphs.extend(self.tab_knowledge.explain_area(song, measure, segment))
        paragraphs.extend(self._uncertainty_note(area))
        return self._page(title, paragraphs, self._source_links())

    def explain_tab_selection(self, song: SongData | None, start_index: int, end_index: int) -> str:
        title, paragraphs = self.tab_knowledge.explain_song_selection(song, start_index, end_index)
        return self._page(title, paragraphs, self.tab_knowledge.source_links())

    def explain_song(self, song: SongData | None) -> str:
        if song is None:
            return self._page(
                tr("Whole-song progression"),
                [
                    tr("Open a file to summarize the song central scale, repeated progressions, harmonic rhythm, function distribution, and open/closed sections."),
                    tr("The right pane is the overview map, and the lower explanation pane zooms into the selected measure."),
                ],
            )

        raw_events = self._song_events(song, None)
        if not raw_events:
            return self._page(
                tr("{title}: Whole-song progression").format(title=song.title),
                [tr("There are not yet any measures with notes to analyze.")],
                self._source_links(),
            )

        global_scale = song.global_scale or self._infer_global_scale(song, raw_events)
        prefer_flats = song.track.prefer_flats
        events = self._song_events(song, global_scale)
        paragraphs: list[str] = []
        paragraphs.extend(self._song_guitar_requirements(song))
        paragraphs.extend(self._song_overview(song, events, global_scale, prefer_flats))
        paragraphs.extend(self._song_scale_distribution(events, global_scale, prefer_flats))
        paragraphs.extend(self._song_chord_palette(events, prefer_flats))
        paragraphs.extend(self._song_harmonic_rhythm(song, events))
        paragraphs.extend(self._song_function_distribution(events))
        paragraphs.extend(self._song_chromatic_features(events, global_scale, prefer_flats))
        paragraphs.extend(self._song_progression_schemas(events))
        paragraphs.extend(self._song_root_motion(events))
        paragraphs.extend(self._song_repeated_patterns(events, prefer_flats))
        paragraphs.extend(self._song_section_closure(song, events, prefer_flats))
        paragraphs.extend(self._song_timeline(song, events, prefer_flats))
        return self._page(tr("{title}: Whole-song progression").format(title=song.title), paragraphs, self._source_links())

    def _song_events(self, song: SongData, global_scale: Candidate | None) -> list[SongEvent]:
        events: list[SongEvent] = []
        for measure in song.track.measures:
            areas: tuple[SegmentData | MeasureData, ...] = measure.segments if measure.segments else (measure,)
            for area in areas:
                if not area.notes:
                    continue
                scale = area.analysis.scale_candidates[0] if area.analysis.scale_candidates else None
                chord = area.analysis.chord_candidates[0] if area.analysis.chord_candidates else None
                role_scale = global_scale or scale
                role = self._chord_role(chord, role_scale) if chord is not None and role_scale is not None else None
                if isinstance(area, SegmentData):
                    start = round((area.start_in_measure / measure.length_ticks) * 100)
                    end = round((area.end_in_measure / measure.length_ticks) * 100)
                else:
                    start = 0
                    end = 100
                events.append(
                    SongEvent(
                        measure_number=measure.number,
                        start_percent=start,
                        end_percent=end,
                        scale=scale,
                        chord=chord,
                        role=role,
                        note_count=len(area.notes),
                    )
                )
        return events

    def _infer_global_scale(self, song: SongData, events: list[SongEvent]) -> Candidate | None:
        tonic_root = self._infer_tonic_root(song)
        weighted: Counter[str] = Counter()
        candidates: dict[str, Candidate] = {}
        for measure in song.track.measures:
            if not measure.notes:
                continue
            for rank, scale in enumerate(measure.analysis.scale_candidates[:12]):
                weight = len(measure.notes) * max(1, scale.score) / (rank + 1)
                if scale.root_pc == tonic_root:
                    weight *= 2.4
                if self._scale_family(scale.name) == "harmonic minor":
                    weight *= 1.25
                weighted[scale.name] += weight
                current = candidates.get(scale.name)
                if current is None or scale.score > current.score:
                    candidates[scale.name] = scale

        all_pitch_classes = [note.midi % 12 for measure in song.track.measures for note in measure.notes]
        if all_pitch_classes:
            aggregate = analyze_pitch_classes(all_pitch_classes, top_n=12)
            for rank, scale in enumerate(aggregate.scale_candidates):
                weight = max(1, scale.score) * 8 / (rank + 1)
                if scale.root_pc == tonic_root:
                    weight *= 2.8
                weighted[scale.name] += weight
                candidates.setdefault(scale.name, scale)

        if not weighted:
            return None
        return candidates[weighted.most_common(1)[0][0]]

    def _infer_tonic_root(self, song: SongData) -> int | None:
        roots: Counter[int] = Counter()
        first_root: int | None = None
        last_root: int | None = None
        for measure in song.track.measures:
            if not measure.notes or not measure.analysis.chord_candidates:
                continue
            chord = measure.analysis.chord_candidates[0]
            weight = max(1, len(measure.notes)) * max(1, chord.score)
            roots[chord.root_pc] += weight
            if first_root is None:
                first_root = chord.root_pc
            last_root = chord.root_pc

        if first_root is not None:
            roots[first_root] += 600
        if last_root is not None:
            roots[last_root] += 250
        if not roots:
            return None
        return roots.most_common(1)[0][0]

    def _song_overview(
        self,
        song: SongData,
        events: list[SongEvent],
        global_scale: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        active_measures = len({event.measure_number for event in events})
        scale_text = candidate_display_name(global_scale, prefer_flats) if global_scale else tr("Undetermined")
        concepts = self.data.get("song_progression_concepts", {})
        overview = [
            f"<b>{tr('Main center')}</b>: "
            + tr("Across {measure_count} measures, {active_measures} measures contain notes. The most-supported central scale is <b>{scale}</b>.").format(
                measure_count=len(song.track.measures),
                active_measures=active_measures,
                scale=html.escape(scale_text),
            ),
            f"<b>{tr('Analysis view')}</b>: {html.escape(concepts.get('phrase_model', tr('The whole song is easier to understand through functional flow than isolated chords.')))}",
        ]
        if global_scale is not None:
            overview.append(self._scale_parent_explanation(global_scale, self._scale_family(global_scale.name), prefer_flats))
        return overview

    def _song_guitar_requirements(self, song: SongData) -> list[str]:
        tab_notes = [
            note
            for measure in song.track.measures
            for note in measure.notes
            if note.fret >= 0
        ]
        notes = [note for note in tab_notes if not note.is_muted] or tab_notes
        if not notes:
            return []

        max_fret = max(note.fret for note in notes)
        fret_capacity = self._required_fret_capacity(max_fret)
        details = [self._fret_requirement_text(max_fret, fret_capacity)]
        string_detail = self._string_requirement_text(song, notes, fret_capacity)
        if string_detail:
            details.append(string_detail)
        details.append(self._arm_requirement_text(notes))
        return [f"<b>{tr('Required guitar conditions')}</b>: " + " ".join(html.escape(detail) for detail in details)]

    def _required_fret_capacity(self, max_fret: int) -> int:
        for fret_capacity in (21, 22, 24):
            if max_fret <= fret_capacity:
                return fret_capacity
        return max_fret

    def _fret_requirement_text(self, max_fret: int, fret_capacity: int) -> str:
        if max_fret <= 0:
            return tr("Only open strings are used, so fret count does not limit the guitar choice.")
        if fret_capacity == 21:
            return tr("The highest fret used is fret {max_fret}, so a 21-fret guitar can play it.").format(max_fret=max_fret)
        if fret_capacity == 22:
            return tr("The highest fret used is fret {max_fret}, so a 22-fret guitar can play it.").format(max_fret=max_fret)
        if fret_capacity == 24:
            return tr("The highest fret used is fret {max_fret}, so a 24-fret guitar is needed.").format(max_fret=max_fret)
        return tr("The highest fret used is fret {max_fret}, so a guitar with more than 24 frets is needed.").format(max_fret=max_fret)

    def _string_requirement_text(self, song: SongData, notes: list[TabNote], fret_capacity: int) -> str:
        used_strings = [note.string for note in notes if note.string > 0]
        if not used_strings:
            return ""

        track_strings = len(song.track.string_pitches)
        max_used_string = max(used_strings)
        if max_used_string <= 6:
            if track_strings > 6:
                return tr("The tab is written for {track_strings} strings, but it only uses up to the 6th string, so a 6-string guitar can play it.").format(track_strings=track_strings)
            return tr("A 6-string guitar can play this because the used notes stay within the first 6 strings.")

        cover_fret = self._six_string_cover_fret(song, notes)
        if cover_fret is not None:
            if cover_fret > fret_capacity:
                return tr("The tab uses string {string_count}, so it is written for a {string_count}-string guitar, but the notes can be covered on a 6-string guitar if you allow up to fret {cover_fret}.").format(
                    string_count=max_used_string,
                    cover_fret=cover_fret,
                )
            return tr("The tab uses string {string_count}, so it is written for a {string_count}-string guitar, but the notes can be covered on a 6-string guitar.").format(
                string_count=max_used_string,
            )
        return tr("The tab uses string {string_count} with notes outside the 6-string range, so a {string_count}-string guitar is required.").format(
            string_count=max_used_string,
        )

    def _six_string_cover_fret(self, song: SongData, notes: list[TabNote]) -> int | None:
        six_string_pitches = song.track.string_pitches[:6]
        if len(six_string_pitches) < 6:
            return None

        cover_limit = max(24, song.track.fret_count)
        required_frets: list[int] = []
        for note in notes:
            if note.string <= 6:
                continue
            playable_frets = [
                note.midi - open_midi
                for open_midi in six_string_pitches
                if 0 <= note.midi - open_midi <= cover_limit
            ]
            if not playable_frets:
                return None
            required_frets.append(min(playable_frets))
        return max(required_frets) if required_frets else 0

    def _arm_requirement_text(self, notes: list[TabNote]) -> str:
        if any("tremolo_bar" in note.techniques for note in notes):
            return tr("Tremolo arm markings are used, so a guitar with a tremolo arm is recommended.")
        return tr("No tremolo arm markings were detected.")

    def _song_scale_distribution(
        self,
        events: list[SongEvent],
        global_scale: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        scales = [event.scale for event in events if event.scale is not None]
        if not scales:
            return []

        counts = Counter(candidate_display_name(scale, prefer_flats) for scale in scales)
        top = counts.most_common(5)
        top_text = ", ".join(f"{html.escape(name)} x{count}" for name, count in top)
        changes = 0
        previous_name = ""
        for scale in scales:
            name = scale.name
            if previous_name and name != previous_name:
                changes += 1
            previous_name = name

        global_text = ""
        if global_scale is not None:
            global_name = candidate_display_name(global_scale, prefer_flats)
            support = counts.get(global_name, 0)
            global_text = tr(" The global center {name} appears directly in {count} detected segments.").format(
                name=html.escape(global_name),
                count=support,
            )

        concept = self.data.get("song_progression_concepts", {}).get("scale_stability", "")
        return [
            f"<b>{tr('Scale distribution')}</b>: "
            + tr("{top}. The scale name changes about {changes} times.{global_text} {concept}").format(
                top=top_text,
                changes=changes,
                global_text=global_text,
                concept=html.escape(concept),
            )
        ]

    def _song_chord_palette(self, events: list[SongEvent], prefer_flats: bool | None) -> list[str]:
        chords = [event.chord for event in events if event.chord is not None]
        if not chords:
            return []

        counts = Counter(candidate_display_name(chord, prefer_flats) for chord in chords)
        top_text = ", ".join(f"{html.escape(name)} x{count}" for name, count in counts.most_common(6))
        family_counts: Counter[str] = Counter(self._chord_family(chord) for chord in chords)
        family_labels = {
            "major": tr("major"),
            "minor": tr("minor"),
            "dominant": tr("dominant"),
            "altered_dominant": tr("altered dominant"),
            "suspended": tr("sus"),
            "diminished": tr("diminished"),
            "augmented": tr("augmented"),
            "extended": tr("extended"),
            "added_tone": tr("add"),
            "quartal": tr("quartal"),
            "power": tr("power"),
        }
        family_text = ", ".join(
            f"{family_labels.get(family, family)} x{count}"
            for family, count in family_counts.most_common()
        )
        guide_concept = self._concept("guide_tones")
        return [
            f"<b>{tr('Chord palette')}</b>: "
            + tr("Frequent candidates are {top}. By character, {families} appears. {concept}").format(
                top=top_text,
                families=html.escape(family_text),
                concept=html.escape(guide_concept),
            )
        ]

    def _song_harmonic_rhythm(self, song: SongData, events: list[SongEvent]) -> list[str]:
        active_measures = max(1, len({event.measure_number for event in events}))
        changes_per_measure = len(events) / active_measures
        if changes_per_measure < 1.25:
            density = tr("Harmony mostly stays stable within each measure.")
        elif changes_per_measure < 2.25:
            density = tr("This is medium density where chords/scales sometimes change within a measure.")
        else:
            density = tr("This is a fast harmonic rhythm with frequent changes within a measure.")
        concept = self.data.get("song_progression_concepts", {}).get("harmonic_rhythm", "")
        return [
            f"<b>{tr('Harmonic rhythm')}</b>: "
            + tr("Measures with notes average {changes:.2f} harmonic segments. {density} {concept}").format(
                changes=changes_per_measure,
                density=html.escape(density),
                concept=html.escape(concept),
            )
        ]

    def _song_function_distribution(self, events: list[SongEvent]) -> list[str]:
        role_counts: Counter[str] = Counter()
        labels: dict[str, str] = {}
        for event in events:
            if event.role is None:
                continue
            role_counts[event.role.function_id] += 1
            labels[event.role.function_id] = event.role.function_label
        if not role_counts:
            return [f"<b>{tr('Function distribution')}</b>: {tr('There are not enough chord/scale candidates to compute roman-numeral functions reliably.')}"]
        total = sum(role_counts.values())
        parts = [
            f"{html.escape(labels[key])} x{count}({round(count / total * 100)}%)"
            for key, count in role_counts.most_common()
        ]
        dominant_note = ""
        if role_counts.get("modal_color", 0) >= max(role_counts.values()) * 0.6:
            dominant_note = tr(" If modal/color functions dominate, riffs, common tones, and repeated patterns may hold the song together more than traditional cadences.")
        return [f"<b>{tr('Function distribution')}</b>: " + ", ".join(parts) + html.escape(dominant_note)]

    def _song_chromatic_features(
        self,
        events: list[SongEvent],
        global_scale: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        if global_scale is None:
            return []

        chromatic_events = [event for event in events if event.role is not None and event.role.chromatic]
        secondary_labels: list[str] = []
        tritone_count = 0
        for event in events:
            if event.chord is None:
                continue
            target = self._secondary_dominant_target(event.chord, global_scale)
            if target is not None:
                target_pc, target_roman = target
                chord_name = candidate_display_name(event.chord, prefer_flats)
                target_name = pitch_class_name(target_pc, prefer_flats)
                secondary_labels.append(f"M{event.measure_number} {chord_name}-> {target_name}({target_roman})")
            if self._is_tritone_substitution(event.chord, global_scale):
                tritone_count += 1

        mixture_count = sum(
            1
            for event in events
            if event.role is not None and event.role.function_id in {"modal_color", "chromatic"}
        )

        details: list[str] = []
        if chromatic_events:
            details.append(tr("out-of-scale root/function candidates x{count}").format(count=len(chromatic_events)))
        if secondary_labels:
            details.append(tr("secondary dominant candidates {items}").format(items=", ".join(html.escape(label) for label in secondary_labels[:6])))
        if tritone_count:
            details.append(tr("tritone substitution candidates x{count}").format(count=tritone_count))
        if mixture_count:
            details.append(tr("modal/chromatic color candidates x{count}").format(count=mixture_count))
        if not details:
            details.append(tr("Most chords are explained within the central scale"))

        concepts = " ".join(
            self._concept(key)
            for key in ("secondary_dominant", "modal_mixture", "tritone_substitution")
            if self._concept(key)
        )
        return [f"<b>{tr('Chromatic/borrowed signs')}</b>: " + " / ".join(details) + " " + html.escape(concepts)]

    def _song_progression_schemas(self, events: list[SongEvent]) -> list[str]:
        roles = [event.role for event in events if event.role is not None]
        if len(roles) < 2:
            return []

        dominant_to_tonic = 0
        predominant_dominant_tonic = 0
        turnaround_like = 0
        for previous, current in zip(roles, roles[1:]):
            if previous.function_id == "dominant" and current.function_id == "tonic":
                dominant_to_tonic += 1
        for first, second, third in zip(roles, roles[1:], roles[2:]):
            if (
                first.function_id == "predominant"
                and second.function_id == "dominant"
                and third.function_id in {"tonic", "tonic_prolongation"}
            ):
                predominant_dominant_tonic += 1
        for window in zip(roles, roles[1:], roles[2:], roles[3:]):
            ids = [role.function_id for role in window]
            if ids[-2:] == ["predominant", "dominant"] and ids[0] in {"tonic", "tonic_prolongation", "dominant"}:
                turnaround_like += 1

        parts = [
            tr("dominant-to-tonic resolutions x{count}").format(count=dominant_to_tonic),
            tr("predominant-dominant-tonic flows x{count}").format(count=predominant_dominant_tonic),
            tr("turnaround-like flows x{count}").format(count=turnaround_like),
        ]
        concept = self.data.get("song_progression_concepts", {}).get("jazz_turnaround", "")
        return [f"<b>{tr('Progression grammar')}</b>: " + ", ".join(parts) + ". " + html.escape(concept)]

    def _song_root_motion(self, events: list[SongEvent]) -> list[str]:
        roots = [event.chord.root_pc for event in events if event.chord is not None]
        if len(roots) < 2:
            return []
        motion_counts: Counter[str] = Counter()
        for previous, current in zip(roots, roots[1:]):
            motion = (current - previous) % 12
            if motion == 0:
                motion_counts["same"] += 1
            elif motion in {5, 7}:
                motion_counts["fifth"] += 1
            elif motion in {1, 2, 10, 11}:
                motion_counts["step"] += 1
            elif motion in {3, 4, 8, 9}:
                motion_counts["third"] += 1
            else:
                motion_counts["tritone"] += 1

        total = sum(motion_counts.values())
        concept = self.data.get("song_progression_concepts", {}).get("circle_of_fifths", "")
        parts = [
            tr("same root x{count}").format(count=motion_counts["same"]),
            tr("fourth/fifth relationships x{count}").format(count=motion_counts["fifth"]),
            tr("stepwise motion x{count}").format(count=motion_counts["step"]),
            tr("third relationships x{count}").format(count=motion_counts["third"]),
        ]
        strongest = motion_counts.most_common(1)[0][0]
        comment = ""
        if strongest == "same":
            comment = tr(" The root stays for a long time, so it may sound riff-centered or like a pedal point.")
        elif strongest == "fifth":
            comment = tr(" Many fourth/fifth relationships make circle-of-fifths pull important.")
        elif strongest == "step":
            comment = tr(" Frequent stepwise root motion can make the progression feel like a melodic bass line.")
        return [f"<b>{tr('Root motion')}</b>: {', '.join(parts)} / {tr('total')} {total}. {html.escape(comment)} {html.escape(concept)}"]

    def _song_repeated_patterns(self, events: list[SongEvent], prefer_flats: bool | None) -> list[str]:
        chord_names = [
            candidate_display_name(event.chord, prefer_flats)
            for event in events
            if event.chord is not None
        ]
        if len(chord_names) < 4:
            return []
        best_pattern: tuple[str, ...] = ()
        best_count = 1
        for size in (4, 3, 2):
            counts = Counter(tuple(chord_names[index:index + size]) for index in range(len(chord_names) - size + 1))
            pattern, count = counts.most_common(1)[0]
            if count >= 2:
                best_pattern = pattern
                best_count = count
                break
        if not best_pattern:
            return [f"<b>{tr('Repeated pattern')}</b>: {tr('Rather than an identical short chord loop, this looks like riff/scale material being varied and continued.')}"]
        riff_concept = self.data.get("song_progression_concepts", {}).get("riff_based_harmony", "")
        return [
            f"<b>{tr('Repeated pattern')}</b>: "
            + tr("{pattern} pattern appears at least {count} times. {concept}").format(
                pattern=" -> ".join(html.escape(name) for name in best_pattern),
                count=best_count,
                concept=html.escape(riff_concept),
            )
        ]

    def _song_section_closure(self, song: SongData, events: list[SongEvent], prefer_flats: bool | None) -> list[str]:
        by_measure: dict[int, SongEvent] = {}
        for event in events:
            by_measure[event.measure_number] = event
        sections: list[str] = []
        measure_numbers = [measure.number for measure in song.track.measures]
        if not measure_numbers:
            return []
        first = measure_numbers[0]
        last = measure_numbers[-1]
        start = first
        while start <= last:
            end = min(last, start + 7)
            section_events = [by_measure[number] for number in range(start, end + 1) if number in by_measure]
            if section_events:
                final = section_events[-1]
                if final.role is None:
                    closure = tr("pending judgment")
                elif final.role.function_id == "tonic":
                    closure = tr("closed section")
                else:
                    closure = tr("open section")
                final_chord = candidate_display_name(final.chord, prefer_flats) if final.chord else "-"
                final_role = final.role.function_label if final.role else "-"
                sections.append(f"M{start}-{end}: {closure}({final_chord}, {final_role})")
            start += 8

        concept = self.data.get("song_progression_concepts", {}).get("open_closed_sections", "")
        return [f"<b>{tr('8-measure open/closed sections')}</b>: " + " / ".join(html.escape(item) for item in sections) + f"<br>{html.escape(concept)}"]

    def _song_timeline(self, song: SongData, events: list[SongEvent], prefer_flats: bool | None) -> list[str]:
        by_measure: dict[int, list[SongEvent]] = {}
        for event in events:
            by_measure.setdefault(event.measure_number, []).append(event)
        chunks: list[str] = []
        measures = song.track.measures
        for index in range(0, len(measures), 8):
            chunk = measures[index:index + 8]
            labels: list[str] = []
            for measure in chunk:
                measure_events = by_measure.get(measure.number, [])
                if not measure_events:
                    continue
                chord_labels = []
                for event in measure_events[:3]:
                    chord = candidate_display_name(event.chord, prefer_flats) if event.chord else "-"
                    roman = f" {event.role.roman}" if event.role else ""
                    scale = candidate_display_name(event.scale, prefer_flats) if event.scale else "-"
                    chord_labels.append(f"{chord}{roman}/{scale}")
                if len(measure_events) > 3:
                    chord_labels.append("...")
                labels.append(f"M{measure.number}:{'/'.join(chord_labels)}")
            if labels:
                chunks.append(" - ".join(html.escape(label) for label in labels))
        if not chunks:
            return []
        return [f"<b>{tr('Progression map')}</b><br>" + "<br>".join(chunks)]

    def _active_scale(self, area: SegmentData | MeasureData, candidate: Candidate | None, kind: str) -> Candidate | None:
        if candidate is not None and kind == "scale":
            return candidate
        return area.analysis.scale_candidates[0] if area.analysis.scale_candidates else None

    def _active_chord(self, area: SegmentData | MeasureData, candidate: Candidate | None, kind: str) -> Candidate | None:
        if candidate is not None and kind == "chord":
            return candidate
        return area.analysis.chord_candidates[0] if area.analysis.chord_candidates else None

    def _title(
        self,
        measure: MeasureData,
        segment: SegmentData | None,
        scale: Candidate | None,
        chord: Candidate | None,
        prefer_flats: bool | None,
    ) -> str:
        location = f"M{measure.number}"
        if segment is not None:
            start = round((segment.start_in_measure / measure.length_ticks) * 100)
            end = round((segment.end_in_measure / measure.length_ticks) * 100)
            location = f"{location} {start}-{end}%"

        scale_text = candidate_display_name(scale, prefer_flats) if scale else tr("No scale")
        chord_text = candidate_display_name(chord, prefer_flats) if chord else tr("No chord")
        return f"{location}: {scale_text} / {chord_text}"

    def _scale_explanation(
        self,
        area: SegmentData | MeasureData,
        scale: Candidate,
        chord: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        family = self._scale_family(scale.name)
        family_data = self.data["scale_families"].get(family, {})
        scale_name = candidate_display_name(scale, prefer_flats)
        note_names = ", ".join(pitch_class_name(pc, prefer_flats) for pc in scale.pitch_classes)
        degree_names = ", ".join(
            f"{interval_name(scale.root_pc, (scale.root_pc + interval) % 12)}={pitch_class_name((scale.root_pc + interval) % 12, prefer_flats)}"
            for interval in scale.intervals
        )
        observed = sorted({note.midi % 12 for note in area.notes})
        observed_names = ", ".join(pitch_class_name(pc, prefer_flats) for pc in observed) if observed else "-"
        outside = [pc for pc in observed if pc not in set(scale.pitch_classes)]
        outside_text = ""
        if outside:
            outside_text = tr(
                " However, {notes} is outside the candidate scale, so check whether it is a passing tone, neighbor tone, bend/slide ornament, or brief modulation. {concept}"
            ).format(
                notes=", ".join(pitch_class_name(pc, prefer_flats) for pc in outside),
                concept=self._concept("non_chord_tones"),
            )

        chord_scale_text = ""
        if chord is not None:
            chord_name = candidate_display_name(chord, prefer_flats)
            chord_pcs = set(chord.pitch_classes)
            scale_pcs = set(scale.pitch_classes)
            inside_chord = chord_pcs & scale_pcs
            outside_chord = chord_pcs - scale_pcs
            inside_text = ", ".join(pitch_class_name(pc, prefer_flats) for pc in sorted(inside_chord))
            if outside_chord:
                outside_chord_text = ", ".join(pitch_class_name(pc, prefer_flats) for pc in sorted(outside_chord))
                chord_scale_text = (
                    f"<b>{tr('Chord-scale relationship')}</b>: "
                    + tr("In {chord}, {inside} is inside the scale, while {outside} is outside-scale color. {concept}").format(
                        chord=html.escape(chord_name),
                        inside=html.escape(inside_text),
                        outside=html.escape(outside_chord_text),
                        concept=html.escape(self._concept("chord_scale")),
                    )
                )
            else:
                chord_scale_text = (
                    f"<b>{tr('Chord-scale relationship')}</b>: "
                    + tr("All notes of {chord} fit inside {scale}. So the chord tones and scale candidate strongly support each other. {concept}").format(
                        chord=html.escape(chord_name),
                        scale=html.escape(scale_name),
                        concept=html.escape(self._concept("chord_scale")),
                    )
                )

        color_degrees = [
            interval_name(scale.root_pc, (scale.root_pc + interval) % 12)
            for interval in scale.intervals
            if interval not in {0, 3, 4, 7, 10, 11}
        ]
        color_text = ""
        if color_degrees:
            color_text = tr(" In particular, color tones such as {degrees} show how this leaves the basic major/minor frame.").format(
                degrees="/".join(color_degrees)
            )

        return [
            f"<b>{tr('Scale evidence')}</b>: "
            + tr("The observed notes are {observed}, and {scale} contains {matched}/{total} notes for a score of {score}/100.{outside}").format(
                observed=html.escape(observed_names),
                scale=html.escape(scale_name),
                matched=scale.matched_notes,
                total=scale.total_notes,
                score=scale.score,
                outside=html.escape(outside_text),
            ),
            f"<b>{tr('{scale} notes').format(scale=html.escape(scale_name))}</b>: {html.escape(note_names)}.",
            f"<b>{tr('Degree map')}</b>: {html.escape(degree_names)}.",
            self._candidate_confidence(area.analysis.scale_candidates, "Scale", prefer_flats),
            chord_scale_text,
            self._scale_parent_explanation(scale, family, prefer_flats),
            f"<b>{tr('Color')}</b>: {html.escape(family_data.get('mood', tr('This scale is the best fit for the current note set.')))} {html.escape(family_data.get('focus', tr('Check the root and main chord-tone positions together.')))}{html.escape(color_text)}",
            f"<b>{tr('Practice point')}</b>: {html.escape(family_data.get('practice_hint', tr('Listen for the root, third, and fifth first, then decide whether the remaining notes are tension or ornament.')))}",
        ]

    def _chord_explanation(
        self,
        area: SegmentData | MeasureData,
        chord: Candidate,
        scale: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        chord_name = candidate_display_name(chord, prefer_flats)
        chord_notes = ", ".join(
            f"{pitch_class_name(pc, prefer_flats)}({self._chord_interval_label(chord, (pc - chord.root_pc) % 12)})"
            for pc in chord.pitch_classes
        )
        family = self._chord_family(chord)
        family_data = self.data.get("chord_families", {}).get(family, {})
        guide_tones = self._guide_tone_text(chord, prefer_flats)
        tensions = self._chord_tension_text(chord, prefer_flats)
        parts = [
            f"<b>{tr('Chord evidence')}</b>: "
            + tr("{chord} explains {matched}/{total} notes using chord tones {notes} for a score of {score}/100.").format(
                chord=html.escape(chord_name),
                matched=chord.matched_notes,
                total=chord.total_notes,
                notes=html.escape(chord_notes),
                score=chord.score,
            ),
            self._candidate_confidence(area.analysis.chord_candidates, "Chord", prefer_flats),
            f"<b>{tr('Chord character')}</b>: {html.escape(family_data.get('color', tr('This chord best explains the current note set.')))} {html.escape(family_data.get('listen', tr('Check the root, third, and seventh first.')))}",
        ]
        if guide_tones:
            parts.append(f"<b>{tr('Guide tones')}</b>: {html.escape(guide_tones)} {html.escape(self._concept('guide_tones'))}")
        if tensions:
            parts.append(f"<b>{tr('Extensions/alterations')}</b>: {html.escape(tensions)}")

        if scale is None:
            parts.append(f"<b>{tr('Function interpretation')}</b>: {tr('No scale candidate is available for comparison, so roman numeral and function were not fixed.')}")
            return parts

        role = self._chord_role(chord, scale)
        scale_name = candidate_display_name(scale, prefer_flats)
        parts.append(
            f"<b>{tr('Function interpretation')}</b>: "
            + tr("Relative to {scale}, {chord} is roughly <b>{roman}</b>, and can be heard as {function} function. {meaning}").format(
                scale=html.escape(scale_name),
                chord=html.escape(chord_name),
                roman=html.escape(role.roman),
                function=html.escape(role.function_label),
                meaning=html.escape(role.function_meaning),
            )
        )
        if role.chromatic:
            parts.append(tr("This chord sits slightly outside the current scale diatonic chords, so it may sound like a borrowed chord or momentary color chord."))
        chromatic_detail = self._chromatic_chord_detail(chord, scale, prefer_flats)
        if chromatic_detail:
            parts.append(chromatic_detail)
        return parts

    def _progression_explanation(
        self,
        measure: MeasureData,
        selected_segment: SegmentData | None,
        active_scale: Candidate | None,
        prefer_flats: bool | None,
    ) -> list[str]:
        if len(measure.segments) <= 1:
            return [f"<b>{tr('Within-measure movement')}</b>: {tr('Only one clear scale/chord change was detected inside this measure.')}"]

        rows: list[tuple[SegmentData, Candidate | None, Candidate | None, ChordRole | None]] = []
        for segment in measure.segments:
            scale = segment.analysis.scale_candidates[0] if segment.analysis.scale_candidates else active_scale
            chord = segment.analysis.chord_candidates[0] if segment.analysis.chord_candidates else None
            role = self._chord_role(chord, scale) if chord is not None and scale is not None else None
            rows.append((segment, scale, chord, role))

        labels: list[str] = []
        for segment, scale, chord, role in rows:
            start = round((segment.start_in_measure / measure.length_ticks) * 100)
            end = round((segment.end_in_measure / measure.length_ticks) * 100)
            scale_name = candidate_display_name(scale, prefer_flats) if scale else "-"
            chord_name = candidate_display_name(chord, prefer_flats) if chord else "-"
            roman = f" {role.roman}" if role else ""
            labels.append(f"{start}-{end}% {chord_name}{roman} / {scale_name}")

        paragraphs = [f"<b>{tr('Within-measure movement')}</b>: " + " -> ".join(html.escape(label) for label in labels)]

        transitions: list[str] = []
        for previous, current in zip(rows, rows[1:]):
            prev_role = previous[3]
            curr_role = current[3]
            if prev_role is None or curr_role is None:
                continue
            idea = self._progression_idea(prev_role.function_id, curr_role.function_id)
            if idea:
                transitions.append(idea)
            elif previous[2] is not None and current[2] is not None:
                root_motion = (current[2].root_pc - previous[2].root_pc) % 12
                if root_motion in {5, 7}:
                    transitions.append(tr("The root moves by fourth/fifth relationship, so the direction between chords sounds fairly strong."))

        if transitions:
            paragraphs.append(f"<b>{tr('Why it sounds like a progression')}</b>: " + " ".join(html.escape(text) for text in transitions[:3]))

        details = self._segment_transition_details(rows, prefer_flats)
        if details:
            paragraphs.append(f"<b>{tr('Segment connection detail')}</b>: " + " / ".join(html.escape(detail) for detail in details[:5]))

        if selected_segment is not None:
            paragraphs.append(tr("Only the selected change segment is narrowed to green fingering dots on the lower fretboard. Click another segment to update the explanation and fingering dots together."))

        return paragraphs

    def _segment_transition_details(
        self,
        rows: list[tuple[SegmentData, Candidate | None, Candidate | None, ChordRole | None]],
        prefer_flats: bool | None,
    ) -> list[str]:
        details: list[str] = []
        measure_length = max((row[0].end_in_measure for row in rows), default=1)
        for previous, current in zip(rows, rows[1:]):
            previous_segment, previous_scale, previous_chord, previous_role = previous
            current_segment, current_scale, current_chord, current_role = current
            start = round((current_segment.start_in_measure / measure_length) * 100) if measure_length else 0
            parts: list[str] = [tr("{start}% point").format(start=start)]
            if previous_chord is not None and current_chord is not None:
                motion = self._root_motion_label(previous_chord.root_pc, current_chord.root_pc)
                common = len(set(previous_chord.pitch_classes) & set(current_chord.pitch_classes))
                parts.append(tr("root {motion}, common chord tones {count}").format(motion=motion, count=common))
            if previous_scale is not None and current_scale is not None and previous_scale.name != current_scale.name:
                prev_family = self._scale_family(previous_scale.name)
                curr_family = self._scale_family(current_scale.name)
                parts.append(
                    tr("scale changes from {previous} to {current} ({previous_family}->{current_family})").format(
                        previous=candidate_display_name(previous_scale, prefer_flats),
                        current=candidate_display_name(current_scale, prefer_flats),
                        previous_family=tr(prev_family),
                        current_family=tr(curr_family),
                    )
                )
            if previous_role is not None and current_role is not None:
                parts.append(tr("function {previous}->{current}").format(previous=previous_role.function_label, current=current_role.function_label))
            details.append(", ".join(parts))
        return details

    def _candidate_confidence(
        self,
        candidates: tuple[Candidate, ...],
        label: str,
        prefer_flats: bool | None,
    ) -> str:
        if label == "Scale":
            candidates = self._unique_scale_candidates(candidates)
        if not candidates:
            return ""
        first = candidates[0]
        if len(candidates) == 1:
            return (
                f"<b>{tr('{label} candidate comparison').format(label=tr(label))}</b>: "
                + tr("The displayed candidate is {candidate} {score}/100 only.").format(
                    candidate=html.escape(candidate_display_name(first, prefer_flats)),
                    score=first.score,
                )
            )

        second = candidates[1]
        gap = first.score - second.score
        if gap <= 4:
            reading = tr("The scores are almost tied, so compare surrounding measures and the global center scale.")
        elif gap <= 10:
            reading = tr("The top candidate leads, but other interpretations are still plausible.")
        else:
            reading = tr("The top candidate is relatively clear.")
        return (
            f"<b>{tr('{label} candidate comparison').format(label=tr(label))}</b>: "
            + tr("top {first} {first_score}/100, second {second} {second_score}/100, gap {gap} points. {reading} {concept}").format(
                first=html.escape(candidate_display_name(first, prefer_flats)),
                first_score=first.score,
                second=html.escape(candidate_display_name(second, prefer_flats)),
                second_score=second.score,
                gap=gap,
                reading=html.escape(reading),
                concept=html.escape(self._concept("candidate_confidence")),
            )
        )

    def _unique_scale_candidates(self, candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
        unique: list[Candidate] = []
        seen_pitch_sets: set[tuple[int, ...]] = set()
        for candidate in candidates:
            key = tuple(sorted(candidate.pitch_classes))
            if key in seen_pitch_sets:
                continue
            seen_pitch_sets.add(key)
            unique.append(candidate)
        return tuple(unique)

    def _chord_family(self, chord: Candidate) -> str:
        name = chord.name.lower()
        intervals = set(chord.intervals)
        if chord.intervals == (0, 7) or name.endswith("5"):
            return "power"
        if "quartal" in name:
            return "quartal"
        if {0, 3, 6}.issubset(intervals):
            return "diminished"
        if {0, 4, 8}.issubset(intervals):
            return "augmented"
        if self._is_dominant_chord(chord) and any(token in name for token in ("alt", "b9", "#9", "b5", "#5", "b13", "#11")):
            return "altered_dominant"
        if "sus" in name:
            return "suspended"
        if self._is_dominant_chord(chord):
            return "dominant"
        if "add" in name:
            return "added_tone"
        if any(token in name for token in ("9", "11", "13", "6/9")):
            return "extended"
        if {0, 3, 7}.issubset(intervals) or ("m" in name and "maj" not in name and "dim" not in name):
            return "minor"
        return "major"

    def _is_dominant_chord(self, chord: Candidate) -> bool:
        intervals = set(chord.intervals)
        return 4 in intervals and 10 in intervals

    def _chord_interval_label(self, chord: Candidate, interval: int) -> str:
        intervals = set(chord.intervals)
        if interval == 0:
            return "R"
        if interval == 1:
            return "b9"
        if interval == 2:
            return "9"
        if interval == 3 and 4 in intervals:
            return "#9"
        if interval == 3:
            return "b3"
        if interval == 4:
            return "3"
        if interval == 5:
            return "11/sus4"
        if interval == 6 and 7 in intervals:
            return "#11"
        if interval == 6:
            return "b5"
        if interval == 7:
            return "5"
        if interval == 8 and 7 in intervals:
            return "b13"
        if interval == 8:
            return "#5"
        if interval == 9:
            return "13"
        if interval == 10:
            return "b7"
        if interval == 11:
            return "7"
        return interval_name(chord.root_pc, (chord.root_pc + interval) % 12)

    def _guide_tone_text(self, chord: Candidate, prefer_flats: bool | None) -> str:
        labels: list[str] = []
        for interval in (3, 4, 10, 11):
            if interval in chord.intervals:
                pc = (chord.root_pc + interval) % 12
                labels.append(f"{self._chord_interval_label(chord, interval)}={pitch_class_name(pc, prefer_flats)}")
        return ", ".join(labels)

    def _chord_tension_text(self, chord: Candidate, prefer_flats: bool | None) -> str:
        tension_intervals = [interval for interval in chord.intervals if interval in {1, 2, 5, 6, 8, 9}]
        if not tension_intervals:
            return ""
        labels = [
            f"{self._chord_interval_label(chord, interval)}={pitch_class_name((chord.root_pc + interval) % 12, prefer_flats)}"
            for interval in tension_intervals
        ]
        concept = self._concept("altered_dominant") if self._chord_family(chord) == "altered_dominant" else ""
        return ", ".join(labels) + (f". {concept}" if concept else "")

    def _chromatic_chord_detail(
        self,
        chord: Candidate,
        scale: Candidate,
        prefer_flats: bool | None,
    ) -> str:
        target = self._secondary_dominant_target(chord, scale)
        if target is not None:
            target_pc, target_roman = target
            chord_name = candidate_display_name(chord, prefer_flats)
            target_name = pitch_class_name(target_pc, prefer_flats)
            return (
                f"<b>{tr('Chromatic interpretation')}</b>: "
                + tr("{chord} can resolve to {target}({roman}) as a secondary dominant. {concept}").format(
                    chord=html.escape(chord_name),
                    target=html.escape(target_name),
                    roman=html.escape(target_roman),
                    concept=html.escape(self._concept("secondary_dominant")),
                )
            )
        if self._is_tritone_substitution(chord, scale):
            return f"<b>{tr('Chromatic interpretation')}</b>: {tr('A bII7-family dominant may be a tritone substitution for V7.')} " + html.escape(self._concept("tritone_substitution"))
        if chord.root_pc not in set(scale.pitch_classes):
            return f"<b>{tr('Chromatic interpretation')}</b>: {tr('The root itself is outside the current scale, so check for borrowed harmony, implied modulation, or riff-centered color.')} " + html.escape(self._concept("modal_mixture"))
        return ""

    def _secondary_dominant_target(self, chord: Candidate, scale: Candidate) -> tuple[int, str] | None:
        if not self._is_dominant_chord(chord):
            return None
        target_pc = (chord.root_pc + 5) % 12
        if target_pc == scale.root_pc or target_pc not in set(scale.pitch_classes):
            return None
        target_roman = ROMAN_BY_SEMITONE[(target_pc - scale.root_pc) % 12]
        return target_pc, target_roman

    def _is_tritone_substitution(self, chord: Candidate, scale: Candidate) -> bool:
        return self._is_dominant_chord(chord) and (chord.root_pc - scale.root_pc) % 12 == 1

    def _root_motion_label(self, previous_root: int, current_root: int) -> str:
        motion = (current_root - previous_root) % 12
        if motion == 0:
            return tr("same root")
        if motion == 5:
            return tr("up a perfect fourth")
        if motion == 7:
            return tr("up a perfect fifth")
        if motion in {1, 2}:
            return tr("step up")
        if motion in {10, 11}:
            return tr("step down")
        if motion in {3, 4}:
            return tr("third up")
        if motion in {8, 9}:
            return tr("third down")
        if motion == 6:
            return tr("tritone")
        return tr("{count} semitone motion").format(count=motion)

    def _concept(self, key: str) -> str:
        return tr(self.data.get("analysis_concepts", {}).get(key, ""))

    def _uncertainty_note(self, area: SegmentData | MeasureData) -> list[str]:
        note_count = len(area.notes)
        if note_count == 0:
            return [tr("This is a rest segment with no notes to analyze.")]
        if note_count <= 2:
            return [f"<b>{tr('Note')}</b>: {tr('With only one or two notes, several scales/chords can receive the same score. Check surrounding measures too.')}"]
        return []

    def _chord_role(self, chord: Candidate, scale: Candidate) -> ChordRole:
        roman = self._roman_numeral(chord, scale)
        family = self._tonality_family(scale.name)
        simple = roman.replace("13", "").replace("11", "").replace("9", "").replace("7", "")
        function_id = self.data["roman_function_map"].get(family, {}).get(simple)
        chromatic = False
        if function_id is None:
            function_id = "modal_color"
            chromatic = chord.root_pc not in set(scale.pitch_classes)
        function_data = self.data["functions"].get(function_id, self.data["functions"]["modal_color"])
        return ChordRole(
            roman=roman,
            function_id=function_id,
            function_label=function_data["label"],
            function_meaning=function_data["meaning"],
            chromatic=chromatic,
        )

    def _roman_numeral(self, chord: Candidate, scale: Candidate) -> str:
        diff = (chord.root_pc - scale.root_pc) % 12
        base = ROMAN_BY_SEMITONE[diff]
        quality = self._chord_quality(chord)
        accidental = ""
        while base.startswith(("b", "#")):
            accidental += base[0]
            base = base[1:]

        if quality == "minor":
            base = base.lower()
        elif quality == "diminished":
            base = base.lower() + "°"
        elif quality == "augmented":
            base = base + "+"

        extension = self._roman_extension(chord.name)
        return accidental + base + extension

    def _chord_quality(self, chord: Candidate) -> str:
        intervals = set(chord.intervals)
        name = chord.name
        if {0, 3, 6}.issubset(intervals):
            return "diminished"
        if {0, 4, 8}.issubset(intervals):
            return "augmented"
        if {0, 3, 7}.issubset(intervals) or ("m" in name and "maj" not in name and "dim" not in name):
            return "minor"
        return "major"

    def _roman_extension(self, chord_name: str) -> str:
        if "13" in chord_name:
            return "13"
        if "11" in chord_name:
            return "11"
        if "9" in chord_name:
            return "9"
        if "7" in chord_name:
            return "7"
        return ""

    def _scale_family(self, scale_name: str) -> str:
        lowered = scale_name.lower()
        for family in sorted(self.data["scale_families"], key=len, reverse=True):
            if family in lowered:
                return family
        return "major"

    def _tonality_family(self, scale_name: str) -> str:
        family = self._scale_family(scale_name)
        if family in {
            "major",
            "major pentatonic",
            "major blues",
            "lydian",
            "mixolydian",
            "lydian dominant",
            "lydian augmented",
            "mixolydian b6",
            "ionian augmented",
            "lydian #2",
            "harmonic major",
            "double harmonic",
            "whole tone",
            "neapolitan major",
            "persian",
            "prometheus",
            "major locrian",
        }:
            return "major"
        return "minor"

    def _progression_idea(self, previous_function: str, current_function: str) -> str:
        for idea in self.data["progression_ideas"]:
            if idea["from"] == previous_function and idea["to"] == current_function:
                return tr(idea["explanation"])
        return ""

    def _scale_parent_explanation(self, scale: Candidate, family: str, prefer_flats: bool | None) -> str:
        parent = self._harmonic_minor_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>{tr('Parent scale')}</b>: "
                + tr(
                    "{scale} shares material with <b>{parent} harmonic minor</b>, so it is a harmonic-minor-family mode. "
                    "So the segment name may appear as a mode while the whole-song explanation may look harmonic-minor based."
                ).format(
                    scale=html.escape(candidate_display_name(scale, prefer_flats)),
                    parent=html.escape(pitch_class_name(parent, prefer_flats)),
                )
            )
        parent = self._melodic_minor_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>{tr('Parent scale')}</b>: "
                + tr(
                    "{scale} is a <b>{parent} melodic minor</b> family mode. "
                    "Even if this mode name fits a single chord, parent scale and voice leading may explain surrounding motion more naturally."
                ).format(
                    scale=html.escape(candidate_display_name(scale, prefer_flats)),
                    parent=html.escape(pitch_class_name(parent, prefer_flats)),
                )
            )
        parent = self._double_harmonic_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>{tr('Parent scale')}</b>: "
                + tr(
                    "{scale} shares material with the <b>{parent} double harmonic</b> family. "
                    "The semitone tensions between b2/major 3rd and b6/major 7th are central to this family."
                ).format(
                    scale=html.escape(candidate_display_name(scale, prefer_flats)),
                    parent=html.escape(pitch_class_name(parent, prefer_flats)),
                )
            )
        if family == "phrygian":
            return (
                f"<b>{tr('Key difference')}</b>: "
                + tr(
                    "Regular Phrygian is a minor mode with b3, while Phrygian dominant is the fifth mode of harmonic minor with a major 3rd. "
                    "That one scale degree strongly changes the dominant function and neoclassical color."
                )
            )
        return ""

    def _harmonic_minor_parent(self, root_pc: int, family: str) -> int | None:
        offsets = {
            "harmonic minor": 0,
            "locrian natural 6": 2,
            "ionian augmented": 3,
            "dorian #4": 5,
            "ukrainian dorian": 5,
            "phrygian dominant": 7,
            "lydian #2": 8,
            "altered diminished": 11,
        }
        offset = offsets.get(family)
        if offset is None:
            return None
        return (root_pc - offset) % 12

    def _melodic_minor_parent(self, root_pc: int, family: str) -> int | None:
        offsets = {
            "melodic minor": 0,
            "dorian b2": 2,
            "lydian augmented": 3,
            "lydian dominant": 5,
            "mixolydian b6": 7,
            "locrian #2": 9,
            "altered": 11,
        }
        offset = offsets.get(family)
        if offset is None:
            return None
        return (root_pc - offset) % 12

    def _double_harmonic_parent(self, root_pc: int, family: str) -> int | None:
        offsets = {
            "double harmonic": 0,
            "hungarian minor": 5,
        }
        offset = offsets.get(family)
        if offset is None:
            return None
        return (root_pc - offset) % 12

    def _source_links(self) -> list[str]:
        links = []
        for source in self.data.get("sources", []):
            title = html.escape(source["title"])
            url = html.escape(source["url"])
            links.append(f'<a href="{url}">{title}</a>')
        return links

    def _page(self, title: str, paragraphs: list[str], sources: list[str] | None = None) -> str:
        body = "\n".join(f"<p>{paragraph}</p>" for paragraph in paragraphs if paragraph)
        source_html = ""
        if sources:
            source_html = f"<hr><p><b>{tr('Reference sources')}</b>: " + " - ".join(sources) + "</p>"
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
