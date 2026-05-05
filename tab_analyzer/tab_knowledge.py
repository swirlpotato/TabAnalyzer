"""Tablature reading explanations backed by local reference data."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from .analysis import candidate_display_name
from .gp_loader import BeatData, MeasureData, SegmentData, SongData, TabNote


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
                "타브 연주 설명",
                [
                    "Guitar Pro 파일을 열고 타브 플레이어에서 마디를 선택하면, 이곳에 운지와 주법 설명이 표시됩니다.",
                    html.escape(self.data.get("basics", {}).get("line_order", "")),
                ],
            )

        if not song.track.measures:
            return f"{html.escape(song.title)}: 타브 연주 설명", ["선택할 마디가 없습니다."]

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
            return f"M{first} 타브 연주 설명"
        return f"M{first}-M{last} 타브 연주 설명"

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
            return ["<b>연주 방법</b>: 이 선택 범위에는 실제로 연주할 프렛 숫자가 없습니다."]

        if not compact:
            paragraphs.append(f"<b>타브 읽기 기준</b>: {html.escape(basics.get('line_order', ''))}")
            paragraphs.append(f"<b>읽는 순서</b>: {html.escape(basics.get('left_to_right', ''))}")

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
                "<b>주법 표식</b>: 선택 범위에는 별도 주법 표식이 거의 없습니다. 숫자를 정확히 누르고 리듬과 줄 이동을 먼저 맞추면 됩니다."
            )

        preview = self._sequence_preview(rows)
        if preview:
            paragraphs.append(preview)

        harmony = self._harmony_hint(song, rows)
        if harmony:
            paragraphs.append(harmony)

        if not compact:
            paragraphs.append(f"<b>연습 팁</b>: {html.escape(basics.get('position', ''))}")
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
        string_text = ", ".join(f"{number}번줄" for number in string_numbers)
        fret_text = "오픈 스트링 중심"
        if fretted:
            low, high = min(fretted), max(fretted)
            fret_text = f"{low}-{high}프렛"
            if high - low <= 4:
                fret_text += " 안의 한 포지션"
            else:
                fret_text += f" 범위라 중간 이동이 필요"
        extras = []
        if open_count:
            extras.append(f"오픈 {open_count}개")
        if muted_count:
            extras.append(f"뮤트 {muted_count}개")
        extra_text = f" ({', '.join(extras)})" if extras else ""
        tempo = f"{song.tempo} BPM"
        return (
            f"<b>선택 범위</b>: {measure_count}마디, 연주 이벤트 {len(beats)}개, 음 {len(notes)}개입니다. "
            f"사용 줄은 {html.escape(string_text)}, 프렛은 {html.escape(fret_text)}{html.escape(extra_text)}입니다. "
            f"기본 템포는 {tempo}이고 플레이어의 속도 슬라이더가 이 값을 비율로 조절합니다."
        )

    def _rhythm_summary(self, rows: list[tuple[MeasureData, MeasureData | SegmentData]], beats: list[BeatData]) -> str:
        durations = Counter(_duration_name(beat.duration_ticks) for beat in beats)
        duration_text = ", ".join(f"{html.escape(name)} {count}개" for name, count in durations.most_common())
        time_signatures = sorted({measure.time_signature for measure, _area in rows})
        return (
            f"<b>리듬</b>: 박자표는 {html.escape(', '.join(time_signatures))}이고, "
            f"주요 길이는 {duration_text}입니다. {html.escape(self.data.get('basics', {}).get('rhythm', ''))}"
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
                f"세로로 겹친 음이 {len(chord_beats)}번 나오며, 최대 {max_stack}개 음을 한 번에 잡습니다. "
                "겹친 숫자는 코드나 더블스톱처럼 같은 타이밍에 치세요."
            )
        if single_beats:
            parts.append(f"한 음씩 진행하는 이벤트는 {len(single_beats)}번입니다. 줄 이동을 먼저 느리게 확인하세요.")
        return "<b>블럭 성격</b>: " + " ".join(parts)

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
            details.append(f"{label}{symbol_text} {counts[technique_id]}개: {play}")
        return "<b>주법 표식</b>: " + " / ".join(details)

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
            suffix = f" 외 {total - len(items)}개"
        return "<b>앞부분 순서</b>: " + " / ".join(html.escape(item) for item in items) + html.escape(suffix)

    def _harmony_hint(self, song: SongData, rows: list[tuple[MeasureData, MeasureData | SegmentData]]) -> str:
        labels: list[str] = []
        for measure, area in rows[:4]:
            scale = area.analysis.scale_candidates[0] if area.analysis.scale_candidates else None
            chord = area.analysis.chord_candidates[0] if area.analysis.chord_candidates else None
            if scale is None and chord is None:
                continue
            scale_text = candidate_display_name(scale, song.track.prefer_flats) if scale else "-"
            chord_text = candidate_display_name(chord, song.track.prefer_flats) if chord else "-"
            labels.append(f"M{measure.number}: 스케일 {scale_text}, 코드 {chord_text}")
        if not labels:
            return ""
        return "<b>분석과 연결</b>: " + " / ".join(html.escape(label) for label in labels)


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
        3840: "온음표",
        2880: "점2분음표",
        1920: "2분음표",
        1440: "점4분음표",
        960: "4분음표",
        720: "점8분음표",
        480: "8분음표",
        360: "점16분음표",
        320: "8분 셋잇단",
        240: "16분음표",
        160: "16분 셋잇단",
        120: "32분음표",
    }
    if ticks in values:
        return values[ticks]
    beats = ticks / TICKS_PER_QUARTER
    return f"{beats:.2f}박"


def _beat_label(measure: MeasureData, beat: BeatData) -> str:
    numerator = _time_signature_numerator(measure.time_signature)
    ticks_per_beat = measure.length_ticks / max(1, numerator)
    beat_position = (beat.start_in_measure / ticks_per_beat) + 1
    if abs(beat_position - round(beat_position)) < 0.02:
        return f"{int(round(beat_position))}박"
    return f"{beat_position:.2f}박"


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
    return f"{note.string}번줄 {fret}{techniques}"


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
