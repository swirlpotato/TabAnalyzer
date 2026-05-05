"""Harmony explanation generation based on local theory data."""

from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .analysis import Candidate, analyze_pitch_classes, candidate_display_name, interval_name, pitch_class_name
from .gp_loader import MeasureData, SegmentData, SongData
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
            return self._page("화성 설명", ["Guitar Pro 파일을 열면 선택한 마디의 스케일, 코드, 기능 진행을 설명합니다."])
        if measure is None:
            return self._page(
                "화성 설명",
                [
                    f"{html.escape(song.title)}을 불러왔습니다.",
                    "상단 탭의 마디 또는 구간별 스케일/코드 표시를 누르면 이곳에 분석 이유가 표시됩니다."
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
                "전체 곡 진행",
                [
                    "파일을 열면 곡 전체의 중심 스케일, 반복 진행, 화성 리듬, 기능 분포, 열린/닫힌 구간을 요약합니다.",
                    "오른쪽 창은 큰 지도이고, 아래 설명 창은 선택한 마디를 확대해서 보는 공간입니다.",
                ],
            )

        raw_events = self._song_events(song, None)
        if not raw_events:
            return self._page(
                f"{song.title}: 전체 곡 진행",
                ["분석할 음이 있는 마디가 아직 없습니다."],
                self._source_links(),
            )

        global_scale = song.global_scale or self._infer_global_scale(song, raw_events)
        prefer_flats = song.track.prefer_flats
        events = self._song_events(song, global_scale)
        paragraphs: list[str] = []
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
        return self._page(f"{song.title}: 전체 곡 진행", paragraphs, self._source_links())

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
        scale_text = candidate_display_name(global_scale, prefer_flats) if global_scale else "미확정"
        concepts = self.data.get("song_progression_concepts", {})
        overview = [
            f"<b>큰 중심</b>: 전체 {len(song.track.measures)}마디 중 음이 있는 마디는 {active_measures}마디입니다. 가장 많이 지지된 중심 스케일은 <b>{html.escape(scale_text)}</b>입니다.",
            f"<b>분석 관점</b>: {html.escape(concepts.get('phrase_model', '곡 전체는 개별 코드보다 기능 흐름으로 보면 이해하기 쉽습니다.'))}",
        ]
        if global_scale is not None:
            overview.append(self._scale_parent_explanation(global_scale, self._scale_family(global_scale.name), prefer_flats))
        return overview

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
        top_text = ", ".join(f"{html.escape(name)} {count}회" for name, count in top)
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
            global_text = f" 전체 중심으로 잡힌 {html.escape(global_name)}는 감지 구간 중 {support}회 직접 등장합니다."

        concept = self.data.get("song_progression_concepts", {}).get("scale_stability", "")
        return [
            f"<b>스케일 분포</b>: {top_text}. 스케일 이름이 바뀐 지점은 약 {changes}회입니다.{global_text} {html.escape(concept)}"
        ]

    def _song_chord_palette(self, events: list[SongEvent], prefer_flats: bool | None) -> list[str]:
        chords = [event.chord for event in events if event.chord is not None]
        if not chords:
            return []

        counts = Counter(candidate_display_name(chord, prefer_flats) for chord in chords)
        top_text = ", ".join(f"{html.escape(name)} {count}회" for name, count in counts.most_common(6))
        family_counts: Counter[str] = Counter(self._chord_family(chord) for chord in chords)
        family_labels = {
            "major": "major",
            "minor": "minor",
            "dominant": "dominant",
            "altered_dominant": "altered dominant",
            "suspended": "sus",
            "diminished": "diminished",
            "augmented": "augmented",
            "extended": "extended",
            "added_tone": "add",
            "quartal": "quartal",
            "power": "power",
        }
        family_text = ", ".join(
            f"{family_labels.get(family, family)} {count}회"
            for family, count in family_counts.most_common()
        )
        guide_concept = self._concept("guide_tones")
        return [
            f"<b>코드 팔레트</b>: 자주 나온 후보는 {top_text}입니다. 성격별로는 {html.escape(family_text)}가 보입니다. {html.escape(guide_concept)}"
        ]

    def _song_harmonic_rhythm(self, song: SongData, events: list[SongEvent]) -> list[str]:
        active_measures = max(1, len({event.measure_number for event in events}))
        changes_per_measure = len(events) / active_measures
        if changes_per_measure < 1.25:
            density = "대체로 한 마디 안에서 화성이 천천히 유지됩니다."
        elif changes_per_measure < 2.25:
            density = "한 마디 안에서 가끔 코드/스케일이 바뀌는 중간 밀도입니다."
        else:
            density = "한 마디 안에서도 변화가 자주 생기는 빠른 화성 리듬입니다."
        concept = self.data.get("song_progression_concepts", {}).get("harmonic_rhythm", "")
        return [
            f"<b>화성 리듬</b>: 음이 있는 마디 기준 평균 {changes_per_measure:.2f}개의 화성 구간이 감지됩니다. {html.escape(density)} {html.escape(concept)}"
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
            return ["<b>기능 분포</b>: 로마숫자 기능을 안정적으로 계산할 만큼 코드/스케일 후보가 충분하지 않습니다."]
        total = sum(role_counts.values())
        parts = [
            f"{html.escape(labels[key])} {count}회({round(count / total * 100)}%)"
            for key, count in role_counts.most_common()
        ]
        dominant_note = ""
        if role_counts.get("modal_color", 0) >= max(role_counts.values()) * 0.6:
            dominant_note = " 모달/색채 기능이 많으면 전통적인 종지보다 리프, 공통음, 반복 패턴이 곡의 접착제일 가능성이 큽니다."
        return ["<b>기능 분포</b>: " + ", ".join(parts) + html.escape(dominant_note)]

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
            details.append(f"스케일 밖 루트/기능 후보 {len(chromatic_events)}회")
        if secondary_labels:
            details.append("secondary dominant 후보 " + ", ".join(html.escape(label) for label in secondary_labels[:6]))
        if tritone_count:
            details.append(f"tritone substitution 후보 {tritone_count}회")
        if mixture_count:
            details.append(f"modal/chromatic color 후보 {mixture_count}회")
        if not details:
            details.append("대부분의 코드가 중심 스케일 내부에서 설명됩니다")

        concepts = " ".join(
            self._concept(key)
            for key in ("secondary_dominant", "modal_mixture", "tritone_substitution")
            if self._concept(key)
        )
        return ["<b>크로매틱/차용 징후</b>: " + " / ".join(details) + " " + html.escape(concepts)]

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
            f"dominant→tonic 해결 {dominant_to_tonic}회",
            f"predominant→dominant→tonic 흐름 {predominant_dominant_tonic}회",
            f"turnaround 유사 흐름 {turnaround_like}회",
        ]
        concept = self.data.get("song_progression_concepts", {}).get("jazz_turnaround", "")
        return ["<b>진행 문법</b>: " + ", ".join(parts) + ". " + html.escape(concept)]

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
            f"동일 루트 {motion_counts['same']}회",
            f"4도/5도 관계 {motion_counts['fifth']}회",
            f"순차 진행 {motion_counts['step']}회",
            f"3도 관계 {motion_counts['third']}회",
        ]
        strongest = motion_counts.most_common(1)[0][0]
        comment = ""
        if strongest == "same":
            comment = " 루트가 오래 유지되어 리프 중심 또는 페달 포인트처럼 들릴 수 있습니다."
        elif strongest == "fifth":
            comment = " 4도/5도 관계가 많아 5도권 진행의 자연스러운 끌림이 중요합니다."
        elif strongest == "step":
            comment = " 순차적인 루트 이동이 많아 선율적인 베이스 라인처럼 진행이 이어질 수 있습니다."
        return [f"<b>루트 움직임</b>: {', '.join(parts)} / 총 {total}회. {html.escape(comment)} {html.escape(concept)}"]

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
            return ["<b>반복 패턴</b>: 완전히 같은 짧은 코드 루프보다는 리프/스케일 재료가 변형되며 이어지는 형태로 보입니다."]
        riff_concept = self.data.get("song_progression_concepts", {}).get("riff_based_harmony", "")
        return [
            f"<b>반복 패턴</b>: {' → '.join(html.escape(name) for name in best_pattern)} 패턴이 {best_count}회 이상 나타납니다. {html.escape(riff_concept)}"
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
                    closure = "판단 보류"
                elif final.role.function_id == "tonic":
                    closure = "닫힌 구간"
                else:
                    closure = "열린 구간"
                final_chord = candidate_display_name(final.chord, prefer_flats) if final.chord else "-"
                final_role = final.role.function_label if final.role else "-"
                sections.append(f"M{start}-{end}: {closure}({final_chord}, {final_role})")
            start += 8

        concept = self.data.get("song_progression_concepts", {}).get("open_closed_sections", "")
        return ["<b>8마디 단위 열림/닫힘</b>: " + " / ".join(html.escape(item) for item in sections) + f"<br>{html.escape(concept)}"]

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
                chunks.append(" · ".join(html.escape(label) for label in labels))
        if not chunks:
            return []
        return ["<b>진행 지도</b><br>" + "<br>".join(chunks)]

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

        scale_text = candidate_display_name(scale, prefer_flats) if scale else "스케일 없음"
        chord_text = candidate_display_name(chord, prefer_flats) if chord else "코드 없음"
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
            outside_text = (
                " 다만 "
                + ", ".join(pitch_class_name(pc, prefer_flats) for pc in outside)
                + "은 후보 스케일 밖이라 passing tone, neighbor tone, bend/slide 장식음, 또는 순간 전조 가능성으로 확인해야 합니다. "
                + self._concept("non_chord_tones")
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
                    f"<b>코드-스케일 관계</b>: {html.escape(chord_name)} 구성음 중 {html.escape(inside_text)}는 스케일 안에 있고, "
                    f"{html.escape(outside_chord_text)}는 스케일 밖 색채입니다. {html.escape(self._concept('chord_scale'))}"
                )
            else:
                chord_scale_text = (
                    f"<b>코드-스케일 관계</b>: {html.escape(chord_name)} 구성음은 모두 {html.escape(scale_name)} 안에 들어갑니다. "
                    f"따라서 이 구간은 코드톤과 스케일 후보가 서로 강하게 지지합니다. {html.escape(self._concept('chord_scale'))}"
                )

        color_degrees = [
            interval_name(scale.root_pc, (scale.root_pc + interval) % 12)
            for interval in scale.intervals
            if interval not in {0, 3, 4, 7, 10, 11}
        ]
        color_text = ""
        if color_degrees:
            color_text = f" 특히 {'/'.join(color_degrees)} 같은 색채음이 장단조 기본 골격을 어떻게 벗어나는지 보면 구분이 쉽습니다."

        return [
            f"<b>스케일 근거</b>: 실제 나온 음은 {html.escape(observed_names)}이고, {html.escape(scale_name)} 후보는 {scale.matched_notes}/{scale.total_notes}개 음을 품어서 {scale.score}/100점으로 평가됐습니다.{html.escape(outside_text)}",
            f"<b>{html.escape(scale_name)}의 음</b>: {html.escape(note_names)}.",
            f"<b>도수 지도</b>: {html.escape(degree_names)}.",
            self._candidate_confidence(area.analysis.scale_candidates, "스케일", prefer_flats),
            chord_scale_text,
            self._scale_parent_explanation(scale, family, prefer_flats),
            f"<b>색채</b>: {html.escape(family_data.get('mood', '이 스케일은 현재 구간의 음 집합과 가장 잘 맞는 후보입니다.'))} {html.escape(family_data.get('focus', '루트와 주요 코드톤의 위치를 함께 확인해보세요.'))}{html.escape(color_text)}",
            f"<b>연습 포인트</b>: {html.escape(family_data.get('practice_hint', '루트, 3도, 5도를 먼저 듣고 나머지 음이 긴장인지 장식인지 나눠보세요.'))}",
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
            f"<b>코드 근거</b>: {html.escape(chord_name)} 후보는 구성음 {html.escape(chord_notes)}을 기준으로 {chord.matched_notes}/{chord.total_notes}개 음을 설명해 {chord.score}/100점입니다.",
            self._candidate_confidence(area.analysis.chord_candidates, "코드", prefer_flats),
            f"<b>코드 성격</b>: {html.escape(family_data.get('color', '이 코드는 현재 음 집합을 가장 잘 설명하는 후보입니다.'))} {html.escape(family_data.get('listen', '루트와 3도, 7도를 먼저 확인해보세요.'))}",
        ]
        if guide_tones:
            parts.append(f"<b>가이드톤</b>: {html.escape(guide_tones)} {html.escape(self._concept('guide_tones'))}")
        if tensions:
            parts.append(f"<b>확장/변화음</b>: {html.escape(tensions)}")

        if scale is None:
            parts.append("<b>기능 해석</b>: 비교할 스케일 후보가 없어 로마숫자와 기능을 확정하지 않았습니다.")
            return parts

        role = self._chord_role(chord, scale)
        scale_name = candidate_display_name(scale, prefer_flats)
        parts.append(
            f"<b>기능 해석</b>: {html.escape(scale_name)} 기준으로 {html.escape(chord_name)}는 대략 <b>{html.escape(role.roman)}</b>이며, "
            f"{html.escape(role.function_label)} 기능으로 볼 수 있습니다. {html.escape(role.function_meaning)}"
        )
        if role.chromatic:
            parts.append("이 코드는 현재 스케일의 다이어토닉 코드에서 살짝 벗어나므로, 차용화음이나 순간적인 색채 코드로 들릴 수 있습니다.")
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
            return ["<b>마디 내부 진행</b>: 이 마디 안에서는 뚜렷한 스케일/코드 변화가 하나만 감지됐습니다."]

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

        paragraphs = ["<b>마디 내부 진행</b>: " + " → ".join(html.escape(label) for label in labels)]

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
                    transitions.append("루트가 4도/5도 관계로 움직여 코드 사이의 방향감이 비교적 강하게 들립니다.")

        if transitions:
            paragraphs.append("<b>왜 진행처럼 들리나</b>: " + " ".join(html.escape(text) for text in transitions[:3]))

        details = self._segment_transition_details(rows, prefer_flats)
        if details:
            paragraphs.append("<b>구간 연결 디테일</b>: " + " / ".join(html.escape(detail) for detail in details[:5]))

        if selected_segment is not None:
            paragraphs.append("현재 선택한 변화 구간만 하단 지판에 녹색 운지점으로 좁혀 표시됩니다. 다른 구간을 누르면 설명과 운지점이 함께 바뀝니다.")

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
            parts: list[str] = [f"{start}% 지점"]
            if previous_chord is not None and current_chord is not None:
                motion = self._root_motion_label(previous_chord.root_pc, current_chord.root_pc)
                common = len(set(previous_chord.pitch_classes) & set(current_chord.pitch_classes))
                parts.append(f"루트 {motion}, 공통 코드톤 {common}개")
            if previous_scale is not None and current_scale is not None and previous_scale.name != current_scale.name:
                prev_family = self._scale_family(previous_scale.name)
                curr_family = self._scale_family(current_scale.name)
                parts.append(
                    f"스케일 {candidate_display_name(previous_scale, prefer_flats)}에서 {candidate_display_name(current_scale, prefer_flats)}로 변경({prev_family}->{curr_family})"
                )
            if previous_role is not None and current_role is not None:
                parts.append(f"기능 {previous_role.function_label}->{current_role.function_label}")
            details.append(", ".join(parts))
        return details

    def _candidate_confidence(
        self,
        candidates: tuple[Candidate, ...],
        label: str,
        prefer_flats: bool | None,
    ) -> str:
        if label == "스케일":
            candidates = self._unique_scale_candidates(candidates)
        if not candidates:
            return ""
        first = candidates[0]
        if len(candidates) == 1:
            return (
                f"<b>{label} 후보 비교</b>: 현재 표시된 후보는 "
                f"{html.escape(candidate_display_name(first, prefer_flats))} {first.score}/100점 하나입니다."
            )

        second = candidates[1]
        gap = first.score - second.score
        if gap <= 4:
            reading = "거의 동점이라 앞뒤 마디와 전체 중심 스케일을 함께 봐야 합니다."
        elif gap <= 10:
            reading = "1순위가 앞서지만 다른 해석도 충분히 가능한 구간입니다."
        else:
            reading = "1순위 후보가 비교적 분명합니다."
        return (
            f"<b>{label} 후보 비교</b>: 1순위 {html.escape(candidate_display_name(first, prefer_flats))} {first.score}/100점, "
            f"2순위 {html.escape(candidate_display_name(second, prefer_flats))} {second.score}/100점, 차이 {gap}점입니다. "
            f"{html.escape(reading)} {html.escape(self._concept('candidate_confidence'))}"
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
                f"<b>크로매틱 해석</b>: {html.escape(chord_name)}는 {html.escape(target_name)}({html.escape(target_roman)})로 "
                f"해결하려는 secondary dominant처럼 볼 수 있습니다. {html.escape(self._concept('secondary_dominant'))}"
            )
        if self._is_tritone_substitution(chord, scale):
            return "<b>크로매틱 해석</b>: bII7 계열 dominant라면 V7의 tritone substitution 가능성이 있습니다. " + html.escape(self._concept("tritone_substitution"))
        if chord.root_pc not in set(scale.pitch_classes):
            return "<b>크로매틱 해석</b>: 루트 자체가 현재 스케일 밖이므로 차용화음, 전조 암시, 또는 리프 중심 색채로 확인해야 합니다. " + html.escape(self._concept("modal_mixture"))
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
            return "동일 루트"
        if motion == 5:
            return "완전4도 상승"
        if motion == 7:
            return "완전5도 상승"
        if motion in {1, 2}:
            return "순차 상승"
        if motion in {10, 11}:
            return "순차 하강"
        if motion in {3, 4}:
            return "3도 상승"
        if motion in {8, 9}:
            return "3도 하강"
        if motion == 6:
            return "트라이톤"
        return f"{motion}반음 이동"

    def _concept(self, key: str) -> str:
        return self.data.get("analysis_concepts", {}).get(key, "")

    def _uncertainty_note(self, area: SegmentData | MeasureData) -> list[str]:
        note_count = len(area.notes)
        if note_count == 0:
            return ["분석할 음이 없는 쉼표 구간입니다."]
        if note_count <= 2:
            return ["<b>주의</b>: 음이 1-2개뿐이면 여러 스케일/코드가 같은 점수를 받을 수 있습니다. 앞뒤 마디까지 함께 보는 것이 좋습니다."]
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
                return idea["explanation"]
        return ""

    def _scale_parent_explanation(self, scale: Candidate, family: str, prefer_flats: bool | None) -> str:
        parent = self._harmonic_minor_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>모계 스케일</b>: {html.escape(candidate_display_name(scale, prefer_flats))}는 "
                f"<b>{html.escape(pitch_class_name(parent, prefer_flats))} harmonic minor</b>와 같은 음 재료를 공유하는 harmonic minor 계열 모드입니다. "
                "따라서 구간 이름은 모드로 보이고, 곡 전체 설명은 harmonic minor 기반으로 보일 수 있습니다."
            )
        parent = self._melodic_minor_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>모계 스케일</b>: {html.escape(candidate_display_name(scale, prefer_flats))}는 "
                f"<b>{html.escape(pitch_class_name(parent, prefer_flats))} melodic minor</b> 계열의 모드입니다. "
                "코드 하나에는 이 모드명이 잘 맞아도, 앞뒤 진행에서는 parent scale과 voice leading을 같이 보는 편이 더 자연스럽습니다."
            )
        parent = self._double_harmonic_parent(scale.root_pc, family)
        if parent is not None:
            return (
                f"<b>모계 스케일</b>: {html.escape(candidate_display_name(scale, prefer_flats))}는 "
                f"<b>{html.escape(pitch_class_name(parent, prefer_flats))} double harmonic</b> 계열과 같은 음 재료를 공유합니다. "
                "b2와 장3도, b6과 장7도가 만드는 반음 긴장이 이 계열의 핵심입니다."
            )
        if family == "phrygian":
            return (
                "<b>주의할 차이</b>: 일반 Phrygian은 b3를 가진 minor 모드이고, "
                "Phrygian dominant는 3도를 가진 harmonic minor의 5번째 모드입니다. "
                "이 3도 한 음 때문에 dominant 기능과 네오클래시컬 색채가 크게 달라집니다."
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
            source_html = "<hr><p><b>참고 데이터 출처</b>: " + " · ".join(sources) + "</p>"
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
