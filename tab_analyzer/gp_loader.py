"""Guitar Pro file loading and normalization."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable
import zipfile
import xml.etree.ElementTree as ET

from .analysis import (
    Candidate,
    MeasureAnalysis,
    analyze_midi_notes,
    midi_note_name,
    pitch_class_name,
    prefer_flats_from_pitch_classes,
)


@dataclass(frozen=True)
class TabNote:
    string: int
    fret: int
    midi: int
    start_tick: int
    start_in_measure: int
    duration_ticks: int
    velocity: int
    techniques: tuple[str, ...] = ()
    bend_semitones: float | None = None

    @property
    def pitch_name(self) -> str:
        return pitch_class_name(self.midi % 12)

    @property
    def is_muted(self) -> bool:
        return "dead_note" in self.techniques


@dataclass(frozen=True)
class BeatData:
    start_tick: int
    start_in_measure: int
    duration_ticks: int
    notes: tuple[TabNote, ...]
    tuplet: tuple[int, int] | None = None


@dataclass(frozen=True)
class SegmentData:
    index: int
    start_in_measure: int
    end_in_measure: int
    beats: tuple[BeatData, ...]
    analysis: MeasureAnalysis

    @property
    def notes(self) -> tuple[TabNote, ...]:
        return tuple(note for beat in self.beats for note in beat.notes)


@dataclass(frozen=True)
class MeasureData:
    number: int
    start_tick: int
    length_ticks: int
    time_signature: str
    beats: tuple[BeatData, ...]
    segments: tuple[SegmentData, ...]
    analysis: MeasureAnalysis

    @property
    def notes(self) -> tuple[TabNote, ...]:
        return tuple(note for beat in self.beats for note in beat.notes)


@dataclass(frozen=True)
class TrackData:
    name: str
    number: int
    fret_count: int
    string_pitches: tuple[int, ...]
    measures: tuple[MeasureData, ...]
    prefer_flats: bool | None = None

    @property
    def string_names(self) -> tuple[str, ...]:
        return tuple(_midi_name(midi, self.prefer_flats) for midi in self.string_pitches)


@dataclass(frozen=True)
class TrackInfo:
    index: int
    name: str
    string_count: int
    tuning: tuple[int, ...]
    is_guitar: bool
    is_electric_guitar: bool
    is_bass: bool
    is_percussion: bool

    @property
    def display_name(self) -> str:
        prefer_flats = _prefer_flats_for_tuning(self.tuning)
        tuning_text = " ".join(_midi_name(midi, prefer_flats) for midi in reversed(self.tuning)) if self.tuning else "-"
        return f"{self.index + 1}. {self.name} ({self.string_count} strings, {tuning_text})"


@dataclass(frozen=True)
class SongData:
    title: str
    artist: str
    album: str
    path: Path
    global_analysis: MeasureAnalysis
    track: TrackData
    tempo: int = 120

    @property
    def global_scale(self) -> Candidate | None:
        return self.global_analysis.scale_candidates[0] if self.global_analysis.scale_candidates else None


def load_gp_file(path: str | Path, track_index: int | None = None) -> SongData:
    """Load a Guitar Pro file and return normalized tab data."""

    file_path = Path(path)
    if _is_gpif_file(file_path):
        return _load_gpif_file(file_path, track_index)

    try:
        import guitarpro
    except ImportError as exc:
        raise RuntimeError("PyGuitarPro is required. Install with: pip install PyGuitarPro") from exc

    song = guitarpro.parse(str(file_path))
    track = _select_track(song.tracks, track_index)
    string_pitch_by_number = {string.number: string.value for string in track.strings}
    string_pitches = tuple(string.value for string in sorted(track.strings, key=lambda item: item.number))
    prefer_flats = _prefer_flats_for_tuning(string_pitches)

    initial_measures = tuple(
        _convert_measure(measure, string_pitch_by_number)
        for measure in track.measures
    )
    global_analysis = _infer_global_analysis(initial_measures)
    measures = _reanalyze_with_context(initial_measures, global_analysis.scale_candidates[0] if global_analysis.scale_candidates else None)
    measures = _apply_scale_tie_breakers(measures)

    return SongData(
        title=song.title or file_path.stem,
        artist=getattr(song, "artist", "") or "",
        album=getattr(song, "album", "") or "",
        path=file_path,
        global_analysis=global_analysis,
        track=TrackData(
            name=track.name or f"Track {track.number}",
            number=track.number,
            fret_count=max(12, int(getattr(track, "fretCount", 24) or 24)),
            string_pitches=string_pitches,
            measures=measures,
            prefer_flats=prefer_flats,
        ),
        tempo=max(20, int(getattr(song, "tempo", 120) or 120)),
    )


def list_tracks(path: str | Path) -> tuple[TrackInfo, ...]:
    file_path = Path(path)
    if _is_gpif_file(file_path):
        return _list_gpif_tracks(file_path)

    try:
        import guitarpro
    except ImportError as exc:
        raise RuntimeError("PyGuitarPro is required. Install with: pip install PyGuitarPro") from exc

    song = guitarpro.parse(str(file_path))
    infos: list[TrackInfo] = []
    for index, track in enumerate(song.tracks):
        string_pitches = tuple(string.value for string in sorted(getattr(track, "strings", []), key=lambda item: item.number))
        high_to_low = tuple(string_pitches)
        name = track.name or f"Track {index + 1}"
        lowered = name.lower()
        is_percussion = bool(getattr(track, "isPercussionTrack", False))
        is_bass = "bass" in lowered or len(high_to_low) == 4
        is_guitar = bool(high_to_low) and not is_percussion and not is_bass
        infos.append(
            TrackInfo(
                index=index,
                name=name,
                string_count=len(high_to_low),
                tuning=high_to_low,
                is_guitar=is_guitar,
                is_electric_guitar=is_guitar,
                is_bass=is_bass,
                is_percussion=is_percussion,
            )
        )
    return tuple(infos)


def default_track_index(path: str | Path) -> int:
    tracks = list_tracks(path)
    if not tracks:
        return 0
    for track in tracks:
        if track.is_electric_guitar:
            return track.index
    for track in tracks:
        if track.is_guitar:
            return track.index
    for track in tracks:
        if track.string_count:
            return track.index
    return tracks[0].index


def _is_gpif_file(path: Path) -> bool:
    if not path.exists() or not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            return "Content/score.gpif" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _load_gpif_file(path: Path, track_index: int | None = None) -> SongData:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Content/score.gpif"))

    score = root.find("Score")
    tracks = root.find("Tracks")
    if tracks is None:
        raise ValueError("The GPIF file does not contain tracks.")

    track_elements = tracks.findall("Track")
    if not track_elements:
        raise ValueError("The GPIF file does not contain tracks.")

    track_position, track = _select_gpif_track(track_elements, track_index)
    string_pitches_low_to_high = _gpif_track_tuning(track)
    if not string_pitches_low_to_high:
        raise ValueError("The selected GPIF track does not contain a tuning.")

    string_pitches = tuple(reversed(string_pitches_low_to_high))
    prefer_flats = _prefer_flats_for_tuning(string_pitches)
    measures = _convert_gpif_measures(root, track_position, string_pitches)
    tempo = _gpif_initial_tempo(root)
    global_analysis = _infer_global_analysis(measures)
    measures = _reanalyze_with_context(measures, global_analysis.scale_candidates[0] if global_analysis.scale_candidates else None)
    measures = _apply_scale_tie_breakers(measures)

    return SongData(
        title=_clean_gpif_text(score.findtext("Title") if score is not None else "") or path.stem,
        artist=_clean_gpif_text(score.findtext("Artist") if score is not None else ""),
        album=_clean_gpif_text(score.findtext("Album") if score is not None else ""),
        path=path,
        global_analysis=global_analysis,
        track=TrackData(
            name=_clean_gpif_text(track.findtext("Name")) or f"Track {track_position + 1}",
            number=track_position + 1,
            fret_count=_gpif_track_fret_count(track),
            string_pitches=string_pitches,
            measures=measures,
            prefer_flats=prefer_flats,
        ),
        tempo=tempo,
    )


def _select_gpif_track(
    tracks: list[ET.Element],
    track_index: int | None,
) -> tuple[int, ET.Element]:
    if track_index is not None:
        if track_index < 0 or track_index >= len(tracks):
            raise IndexError(f"Track index {track_index} is out of range.")
        return track_index, tracks[track_index]

    scored: list[tuple[int, int, ET.Element]] = []
    for position, track in enumerate(tracks):
        name = _clean_gpif_text(track.findtext("Name")).lower()
        icon = (track.findtext("IconId") or "").strip()
        pitches = _gpif_track_tuning(track)
        score = 0
        if "guitar" in name:
            score += 50
        if "bass" in name:
            score += 25
        if icon in {"3", "24"}:
            score += 25
        if len(pitches) == 6:
            score += 15
        if len(pitches) == 4:
            score += 5
        if "drum" in name or icon == "18":
            score -= 100
        scored.append((score, -position, track))

    best_score, negative_position, best_track = max(scored, key=lambda item: item[:2])
    if best_score <= 0:
        return 0, tracks[0]
    return -negative_position, best_track


def _list_gpif_tracks(path: Path) -> tuple[TrackInfo, ...]:
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("Content/score.gpif"))

    tracks = root.find("Tracks")
    if tracks is None:
        return ()

    infos: list[TrackInfo] = []
    for index, track in enumerate(tracks.findall("Track")):
        name = _clean_gpif_text(track.findtext("Name")) or f"Track {index + 1}"
        lowered = name.lower()
        icon = (track.findtext("IconId") or "").strip()
        low_to_high = _gpif_track_tuning(track)
        high_to_low = tuple(reversed(low_to_high))
        is_percussion = "drum" in lowered or icon == "18"
        is_bass = "bass" in lowered or icon == "5" or len(high_to_low) == 4
        is_guitar = bool(high_to_low) and not is_percussion and not is_bass and ("guitar" in lowered or icon in {"3", "24"})
        is_electric = is_guitar and (
            icon in {"3", "24"}
            or "electric" in lowered
            or "red special" in lowered
            or "distortion" in lowered
            or "lead guitar" in lowered
            or "rhythm guitar" in lowered
        )
        infos.append(
            TrackInfo(
                index=index,
                name=name,
                string_count=len(high_to_low),
                tuning=high_to_low,
                is_guitar=is_guitar,
                is_electric_guitar=is_electric,
                is_bass=is_bass,
                is_percussion=is_percussion,
            )
        )
    return tuple(infos)


def _convert_gpif_measures(
    root: ET.Element,
    track_position: int,
    string_pitches_high_to_low: tuple[int, ...],
) -> tuple[MeasureData, ...]:
    master_bars = root.find("MasterBars")
    if master_bars is None:
        return ()

    bars = _gpif_index(root, "Bars", "Bar")
    voices = _gpif_index(root, "Voices", "Voice")
    beats = _gpif_index(root, "Beats", "Beat")
    notes = _gpif_index(root, "Notes", "Note")
    rhythms = _gpif_index(root, "Rhythms", "Rhythm")

    measures: list[MeasureData] = []
    absolute_start = 0
    for number, master_bar in enumerate(master_bars.findall("MasterBar"), start=1):
        time_signature = _clean_gpif_text(master_bar.findtext("Time")) or "4/4"
        length_ticks = _gpif_measure_length_ticks(time_signature)
        bar_ids = _int_list(master_bar.findtext("Bars"))
        bar_id = bar_ids[track_position] if track_position < len(bar_ids) else -1
        bar = bars.get(bar_id)

        measure_beats: list[BeatData] = []
        if bar is not None:
            voice_ids = [voice_id for voice_id in _int_list(bar.findtext("Voices")) if voice_id >= 0]
            for voice_id in voice_ids:
                voice = voices.get(voice_id)
                if voice is None:
                    continue
                start_in_measure = 0
                previous_note_by_string: dict[int, TabNote] = {}
                for beat_id in _int_list(voice.findtext("Beats")):
                    beat = beats.get(beat_id)
                    if beat is None:
                        continue
                    duration_ticks, tuplet = _gpif_beat_rhythm(beat, rhythms)
                    beat_notes = _gpif_beat_notes(
                        beat,
                        notes,
                        string_pitches_high_to_low,
                        absolute_start + start_in_measure,
                        start_in_measure,
                        duration_ticks,
                        previous_note_by_string,
                    )
                    measure_beats.append(
                        BeatData(
                            start_tick=absolute_start + start_in_measure,
                            start_in_measure=start_in_measure,
                            duration_ticks=duration_ticks,
                            notes=beat_notes,
                            tuplet=tuplet,
                        )
                    )
                    for note in beat_notes:
                        previous_note_by_string[note.string] = note
                    start_in_measure += duration_ticks

        measure_beats.sort(key=lambda item: (item.start_in_measure, item.start_tick))
        midi_notes = [note.midi for beat in measure_beats for note in beat.notes]
        segments = _build_segments(tuple(measure_beats), length_ticks, time_signature)
        measures.append(
            MeasureData(
                number=number,
                start_tick=absolute_start,
                length_ticks=length_ticks,
                time_signature=time_signature,
                beats=tuple(measure_beats),
                segments=segments,
                analysis=analyze_midi_notes(midi_notes),
            )
        )
        absolute_start += length_ticks

    return tuple(measures)


def _gpif_beat_notes(
    beat: ET.Element,
    notes: dict[int, ET.Element],
    string_pitches_high_to_low: tuple[int, ...],
    start_tick: int,
    start_in_measure: int,
    duration_ticks: int,
    previous_note_by_string: dict[int, TabNote] | None = None,
) -> tuple[TabNote, ...]:
    note_ids = _int_list(beat.findtext("Notes"))
    converted: list[TabNote] = []
    string_count = len(string_pitches_high_to_low)
    for note_id in note_ids:
        note = notes.get(note_id)
        if note is None:
            continue
        fret = _gpif_property_int(note, "Fret", "Fret")
        gpif_string = _gpif_property_int(note, "String", "String")
        if fret is None or gpif_string is None:
            continue
        string_number = string_count - gpif_string
        if string_number < 1 or string_number > string_count:
            continue
        midi = _gpif_property_int(note, "Midi", "Number")
        if midi is None:
            midi = string_pitches_high_to_low[string_number - 1] + fret
        converted.append(
            TabNote(
                string=string_number,
                fret=fret,
                midi=midi,
                start_tick=start_tick,
                start_in_measure=start_in_measure,
                duration_ticks=duration_ticks,
                velocity=0,
                techniques=_gpif_note_techniques(note, previous_note_by_string.get(string_number) if previous_note_by_string else None),
                bend_semitones=_gpif_note_bend_semitones(note),
            )
        )
    return tuple(converted)


def _gpif_beat_rhythm(beat: ET.Element, rhythms: dict[int, ET.Element]) -> tuple[int, tuple[int, int] | None]:
    rhythm_ref = beat.find("Rhythm")
    rhythm = rhythms.get(int(rhythm_ref.attrib.get("ref", "-1"))) if rhythm_ref is not None else None
    if rhythm is None:
        return 960, None

    value = _clean_gpif_text(rhythm.findtext("NoteValue")).lower()
    duration = {
        "whole": 3840,
        "half": 1920,
        "quarter": 960,
        "eighth": 480,
        "16th": 240,
        "32nd": 120,
        "64th": 60,
        "128th": 30,
    }.get(value, 960)

    dot = rhythm.find("AugmentationDot")
    if dot is not None:
        count = int(dot.attrib.get("count", "1"))
        addition = duration
        for _ in range(count):
            addition //= 2
            duration += addition

    tuplet = rhythm.find("PrimaryTuplet")
    tuplet_ratio = None
    if tuplet is not None:
        num = int(tuplet.attrib.get("num", "1"))
        den = int(tuplet.attrib.get("den", "1"))
        tuplet_ratio = _normalized_tuplet(num, den)
        if num:
            duration = round(duration * den / num)

    return max(1, duration), tuplet_ratio


def _normalized_tuplet(num: object, den: object) -> tuple[int, int] | None:
    try:
        numerator = int(num)
        denominator = int(den)
    except (TypeError, ValueError):
        return None
    if numerator <= 1 or denominator <= 0 or numerator == denominator:
        return None
    return numerator, denominator


def _gpif_measure_length_ticks(time_signature: str) -> int:
    try:
        numerator_text, denominator_text = time_signature.split("/", 1)
        numerator = int(numerator_text)
        denominator = int(denominator_text)
    except ValueError:
        numerator = 4
        denominator = 4
    return max(1, round(numerator * 3840 / denominator))


def _gpif_track_tuning(track: ET.Element) -> tuple[int, ...]:
    pitches = track.find(".//Property[@name='Tuning']/Pitches")
    return tuple(_int_list(pitches.text if pitches is not None else ""))


def _gpif_track_fret_count(track: ET.Element) -> int:
    fret_count = track.find(".//Property[@name='FretCount']/Number")
    if fret_count is not None and fret_count.text:
        return max(12, int(fret_count.text.strip()))
    return 24


def _gpif_initial_tempo(root: ET.Element) -> int:
    for automation in root.findall(".//MasterTrack/Automations/Automation"):
        if _clean_gpif_text(automation.findtext("Type")).lower() != "tempo":
            continue
        value = _int_list(automation.findtext("Value"))
        if value:
            return max(20, min(300, value[0]))
    return 120


def _gpif_property_int(note: ET.Element, name: str, child: str) -> int | None:
    element = note.find(f"Properties/Property[@name='{name}']/{child}")
    if element is None or element.text is None:
        return None
    return int(element.text.strip())


def _gpif_note_techniques(note: ET.Element, previous_note: TabNote | None) -> tuple[str, ...]:
    techniques: list[str] = []
    if _gpif_property_exists(note, "Muted"):
        techniques.append("dead_note")
    if _gpif_property_exists(note, "Ghost", "GhostNote"):
        techniques.append("ghost_note")
    if _gpif_property_exists(note, "PalmMute", "PalmMuted"):
        techniques.append("palm_mute")
    if note.find("LetRing") is not None or _gpif_property_exists(note, "LetRing"):
        techniques.append("let_ring")
    if note.find("Vibrato") is not None or _gpif_property_exists(note, "Vibrato"):
        techniques.append("vibrato")
    if note.find("Tie") is not None:
        tie = note.find("Tie")
        if tie is not None and tie.attrib.get("destination", "false").lower() == "true":
            techniques.append("tie")
    if _gpif_property_exists(note, "HopoDestination"):
        techniques.append(_gpif_legato_technique(note, previous_note))
    if _gpif_property_exists(note, "Slide"):
        techniques.append("slide")
    if _gpif_property_exists(note, "Bended"):
        origin = _gpif_property_float(note, "BendOriginValue")
        destination = _gpif_property_float(note, "BendDestinationValue")
        middle = _gpif_property_float(note, "BendMiddleValue")
        if (origin is not None and destination is not None and destination < origin) or (
            middle is not None and destination is not None and middle > destination
        ):
            techniques.append("release_bend")
        techniques.append("bend")
    if _gpif_property_exists(note, "Tapped"):
        techniques.append("tapping")
    if _gpif_property_exists(note, "Trill"):
        techniques.append("trill")
    if _gpif_property_exists(note, "Harmonic", "NaturalHarmonic", "ArtificialHarmonic", "PinchHarmonic"):
        techniques.append("harmonic")
    if _gpif_property_exists(note, "Staccato"):
        techniques.append("staccato")
    if _gpif_property_exists(note, "Accent", "Accentuated"):
        techniques.append("accent")
    return _unique_techniques(techniques)


def _gpif_note_bend_semitones(note: ET.Element) -> float | None:
    if not _gpif_property_exists(note, "Bended"):
        return None
    origin = _gpif_property_float(note, "BendOriginValue") or 0.0
    values = [
        value
        for value in (
            _gpif_property_float(note, "BendDestinationValue"),
            _gpif_property_float(note, "BendMiddleValue"),
        )
        if value is not None
    ]
    if not values:
        return None
    return _normalize_bend_semitones(max(abs(value - origin) for value in values))


def _gpif_legato_technique(note: ET.Element, previous_note: TabNote | None) -> str:
    if previous_note is None:
        return "legato"
    fret = _gpif_property_int(note, "Fret", "Fret")
    if fret is None:
        return "legato"
    if fret > previous_note.fret:
        return "hammer_on"
    if fret < previous_note.fret:
        return "pull_off"
    return "legato"


def _gpif_property_exists(note: ET.Element, *names: str) -> bool:
    return any(note.find(f"Properties/Property[@name='{name}']") is not None for name in names)


def _gpif_property_float(note: ET.Element, name: str) -> float | None:
    element = note.find(f"Properties/Property[@name='{name}']/Float")
    if element is None or element.text is None:
        return None
    try:
        return float(element.text.strip())
    except ValueError:
        return None


def _gpif_index(root: ET.Element, section: str, tag: str) -> dict[int, ET.Element]:
    parent = root.find(section)
    if parent is None:
        return {}
    return {
        int(element.attrib["id"]): element
        for element in parent.findall(tag)
        if "id" in element.attrib
    }


def _clean_gpif_text(text: str | None) -> str:
    return " ".join((text or "").split())


def _enum_name(value: object) -> str:
    return str(getattr(value, "name", "") or value or "")


def _unique_techniques(techniques: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for technique in techniques:
        if not technique or technique in seen:
            continue
        seen.add(technique)
        ordered.append(technique)
    return tuple(ordered)


def _int_list(text: str | None) -> list[int]:
    values: list[int] = []
    for item in (text or "").split():
        try:
            values.append(int(item))
        except ValueError:
            continue
    return values
    global_analysis = _infer_global_analysis(initial_measures)
    measures = _reanalyze_with_context(initial_measures, global_analysis.scale_candidates[0] if global_analysis.scale_candidates else None)
    measures = _apply_scale_tie_breakers(measures)

    return SongData(
        title=song.title or file_path.stem,
        artist=getattr(song, "artist", "") or "",
        album=getattr(song, "album", "") or "",
        path=file_path,
        global_analysis=global_analysis,
        track=TrackData(
            name=track.name or f"Track {track.number}",
            number=track.number,
            fret_count=max(12, int(getattr(track, "fretCount", 24) or 24)),
            string_pitches=string_pitches,
            measures=measures,
        ),
    )


def retune_song(song: SongData, string_pitches_high_to_low: tuple[int, ...]) -> SongData:
    """Return a copy of a song analyzed with a replacement tuning."""

    if len(string_pitches_high_to_low) != len(song.track.string_pitches):
        raise ValueError(
            f"Tuning has {len(string_pitches_high_to_low)} strings, "
            f"but the track has {len(song.track.string_pitches)} strings."
        )

    open_pitch_by_string = {
        string_number: pitch
        for string_number, pitch in enumerate(string_pitches_high_to_low, start=1)
    }
    initial_measures = tuple(
        _retune_measure_notes(measure, open_pitch_by_string)
        for measure in song.track.measures
    )
    global_analysis = _infer_global_analysis(initial_measures)
    measures = _reanalyze_with_context(
        initial_measures,
        global_analysis.scale_candidates[0] if global_analysis.scale_candidates else None,
    )
    measures = _apply_scale_tie_breakers(measures)

    return replace(
        song,
        global_analysis=global_analysis,
        track=replace(
            song.track,
            string_pitches=string_pitches_high_to_low,
            measures=measures,
            prefer_flats=_prefer_flats_for_tuning(string_pitches_high_to_low),
        ),
    )
def summarize_song(song: SongData, max_measures: int = 12) -> str:
    """Create a compact text summary for command-line verification."""

    lines = [
        f"Title: {song.title}",
        f"Track: {song.track.name} ({len(song.track.measures)} measures)",
        f"Tuning: {' '.join(song.track.string_names)}",
        f"Global scale: {_candidate_text(song.global_analysis.scale_candidates[:3])}",
        "",
    ]
    for measure in song.track.measures[:max_measures]:
        scale = _candidate_text(measure.analysis.scale_candidates)
        chord = _candidate_text(measure.analysis.chord_candidates)
        lines.append(f"M{measure.number:>3}: scale={scale} | chord={chord}")
        changes = _segment_text(measure)
        if changes:
            lines.append(f"      changes: {changes}")
    return "\n".join(lines)


def _select_track(tracks: Iterable[object], track_index: int | None) -> object:
    track_list = list(tracks)
    if not track_list:
        raise ValueError("The file does not contain any tracks.")
    if track_index is not None:
        if track_index < 0 or track_index >= len(track_list):
            raise IndexError(f"Track index {track_index} is out of range.")
        return track_list[track_index]

    for track in track_list:
        if not getattr(track, "isPercussionTrack", False) and getattr(track, "strings", None):
            return track
    return track_list[0]


def _pyguitarpro_note_techniques(note: object, previous_note: object | None, beat: object) -> tuple[str, ...]:
    techniques: list[str] = []
    effect = getattr(note, "effect", None)
    note_type = _enum_name(getattr(note, "type", None))
    if note_type == "dead":
        techniques.append("dead_note")
    if note_type == "tie":
        techniques.append("tie")

    if effect is not None:
        if bool(getattr(effect, "palmMute", False)):
            techniques.append("palm_mute")
        if bool(getattr(effect, "letRing", False)):
            techniques.append("let_ring")
        if bool(getattr(effect, "ghostNote", False)):
            techniques.append("ghost_note")
        if bool(getattr(effect, "staccato", False)):
            techniques.append("staccato")
        if bool(getattr(effect, "accentuatedNote", False)) or bool(getattr(effect, "heavyAccentuatedNote", False)):
            techniques.append("accent")
        if bool(getattr(effect, "vibrato", False)):
            techniques.append("vibrato")
        if getattr(effect, "harmonic", None) is not None:
            techniques.append("harmonic")
        if getattr(effect, "tremoloPicking", None) is not None:
            techniques.append("tremolo_picking")
        if getattr(effect, "trill", None) is not None:
            techniques.append("trill")
        if bool(getattr(effect, "hammer", False)):
            techniques.append(_legato_technique(note, previous_note))
        for slide in getattr(effect, "slides", []) or []:
            if _enum_name(slide) != "none":
                techniques.append("slide")
                break
        bend = getattr(effect, "bend", None)
        if bend is not None:
            bend_type = _enum_name(getattr(bend, "type", None))
            if "release" in bend_type or bend_type in {"bendRelease", "bendReleaseBend", "prebendRelease"}:
                techniques.append("release_bend")
            if bend_type != "none":
                techniques.append("bend")

    beat_effect = getattr(beat, "effect", None)
    if beat_effect is not None:
        if bool(getattr(beat_effect, "vibrato", False)):
            techniques.append("vibrato")
        if _enum_name(getattr(beat_effect, "slapEffect", None)) == "tapping":
            techniques.append("tapping")

    return _unique_techniques(techniques)


def _pyguitarpro_note_bend_semitones(note: object) -> float | None:
    effect = getattr(note, "effect", None)
    bend = getattr(effect, "bend", None) if effect is not None else None
    if bend is None or _enum_name(getattr(bend, "type", None)) == "none":
        return None
    values = [float(getattr(bend, "value", 0) or 0)]
    values.extend(float(getattr(point, "value", 0) or 0) for point in (getattr(bend, "points", []) or []))
    amount = max(abs(value) for value in values)
    return _normalize_bend_semitones(amount)


def _normalize_bend_semitones(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    if value > 12:
        value = value / 100
    return round(value * 4) / 4


def _legato_technique(note: object, previous_note: object | None) -> str:
    if previous_note is None:
        return "legato"
    current_fret = int(getattr(note, "value", 0) or 0)
    previous_fret = int(getattr(previous_note, "value", 0) or 0)
    if current_fret > previous_fret:
        return "hammer_on"
    if current_fret < previous_fret:
        return "pull_off"
    return "legato"


def _convert_measure(measure: object, string_pitch_by_number: dict[int, int]) -> MeasureData:
    beats: list[BeatData] = []
    midi_notes: list[int] = []

    for voice in getattr(measure, "voices", []):
        previous_note_by_string: dict[int, object] = {}
        for beat in getattr(voice, "beats", []):
            notes: list[TabNote] = []
            duration = getattr(beat, "duration", None)
            duration_ticks = int(getattr(duration, "time", 0) or 0)
            tuplet = _pyguitarpro_tuplet(duration)
            for note in getattr(beat, "notes", []):
                string_number = int(getattr(note, "string", 0) or 0)
                fret = int(getattr(note, "value", 0) or 0)
                open_pitch = string_pitch_by_number.get(string_number)
                if open_pitch is None:
                    continue

                midi = open_pitch + fret
                tab_note = TabNote(
                    string=string_number,
                    fret=fret,
                    midi=midi,
                    start_tick=int(getattr(beat, "start", 0) or 0),
                    start_in_measure=int(getattr(beat, "startInMeasure", 0) or 0),
                    duration_ticks=duration_ticks,
                    velocity=int(getattr(note, "velocity", 0) or 0),
                    techniques=_pyguitarpro_note_techniques(
                        note,
                        previous_note_by_string.get(string_number),
                        beat,
                    ),
                    bend_semitones=_pyguitarpro_note_bend_semitones(note),
                )
                notes.append(tab_note)
                midi_notes.append(midi)
            for note in getattr(beat, "notes", []):
                string_number = int(getattr(note, "string", 0) or 0)
                if string_number:
                    previous_note_by_string[string_number] = note

            beats.append(
                BeatData(
                    start_tick=int(getattr(beat, "start", 0) or 0),
                    start_in_measure=int(getattr(beat, "startInMeasure", 0) or 0),
                    duration_ticks=duration_ticks,
                    notes=tuple(notes),
                    tuplet=tuplet,
                )
            )

    measure_number = int(getattr(measure, "number", getattr(getattr(measure, "header", None), "number", 0)) or 0)
    length_ticks = int(getattr(measure, "length", getattr(getattr(measure, "header", None), "length", 3840)) or 3840)
    time_signature = getattr(measure, "timeSignature", None)
    length_ticks = max(1, length_ticks)
    segments = _build_segments(tuple(beats), length_ticks, time_signature)
    return MeasureData(
        number=measure_number,
        start_tick=int(getattr(measure, "start", 0) or 0),
        length_ticks=length_ticks,
        time_signature=_time_signature_text(time_signature),
        beats=tuple(beats),
        segments=segments,
        analysis=analyze_midi_notes(midi_notes),
    )


def _pyguitarpro_tuplet(duration: object | None) -> tuple[int, int] | None:
    tuplet = getattr(duration, "tuplet", None)
    return _normalized_tuplet(getattr(tuplet, "enters", 1), getattr(tuplet, "times", 1))


def _infer_global_analysis(measures: tuple[MeasureData, ...]) -> MeasureAnalysis:
    all_midi_notes = [note.midi for measure in measures for note in measure.notes]
    if not all_midi_notes:
        return analyze_midi_notes(())

    aggregate = analyze_midi_notes(all_midi_notes, top_n=12)
    tonic_root = _infer_tonic_root(measures)
    weighted: Counter[str] = Counter()
    candidates: dict[str, Candidate] = {}

    for measure in measures:
        if not measure.notes:
            continue
        for rank, scale in enumerate(measure.analysis.scale_candidates[:12]):
            weight = len(measure.notes) * max(1, scale.score) / (rank + 1)
            if tonic_root is not None and scale.root_pc == tonic_root:
                weight *= 2.4
            if _scale_family(scale.name) == "harmonic minor":
                weight *= 1.25
            weighted[scale.name] += weight
            current = candidates.get(scale.name)
            if current is None or scale.score > current.score:
                candidates[scale.name] = scale

    for rank, scale in enumerate(aggregate.scale_candidates):
        weight = max(1, scale.score) * 8 / (rank + 1)
        if tonic_root is not None and scale.root_pc == tonic_root:
            weight *= 2.8
        weighted[scale.name] += weight
        candidates.setdefault(scale.name, scale)

    if not weighted:
        return aggregate

    top_weight = max(weighted.values())
    scale_candidates = []
    for name, weight in weighted.most_common(12):
        candidate = candidates[name]
        confidence = round(min(100, max(candidate.score, 50 + (weight / top_weight) * 50)))
        scale_candidates.append(replace(candidate, score=confidence))

    return MeasureAnalysis(
        note_pitch_classes=aggregate.note_pitch_classes,
        scale_candidates=tuple(scale_candidates),
        chord_candidates=aggregate.chord_candidates,
    )


def _infer_tonic_root(measures: tuple[MeasureData, ...]) -> int | None:
    roots: Counter[int] = Counter()
    first_root: int | None = None
    last_root: int | None = None
    for measure in measures:
        if not measure.notes or not measure.analysis.chord_candidates:
            continue
        chord = measure.analysis.chord_candidates[0]
        roots[chord.root_pc] += len(measure.notes) * max(1, chord.score)
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


def _reanalyze_with_context(
    measures: tuple[MeasureData, ...],
    context: Candidate | None,
) -> tuple[MeasureData, ...]:
    if context is None:
        return measures
    return tuple(_reanalyze_measure(measure, context) for measure in measures)


def _reanalyze_measure(measure: MeasureData, context: Candidate) -> MeasureData:
    midi_notes = [note.midi for note in measure.notes]
    measure_analysis = analyze_midi_notes(midi_notes, context=context)
    measure_scale = measure_analysis.scale_candidates[0] if measure_analysis.scale_candidates else context
    segments = tuple(
        _reanalyze_segment(
            segment,
            context=context,
            measure_scale=measure_scale,
        )
        for segment in measure.segments
    )
    segments = _merge_compatible_scale_segments(segments, context, measure_scale)
    return replace(
        measure,
        analysis=measure_analysis,
        segments=segments,
    )


def _reanalyze_segment(
    segment: SegmentData,
    context: Candidate,
    measure_scale: Candidate | None,
) -> SegmentData:
    midi_notes = [note.midi for note in segment.notes]
    analysis = analyze_midi_notes(midi_notes, context=context)
    if measure_scale is not None:
        analysis = _prefer_measure_scale_when_compatible(analysis, measure_scale)

    return SegmentData(
        index=segment.index,
        start_in_measure=segment.start_in_measure,
        end_in_measure=segment.end_in_measure,
        beats=segment.beats,
        analysis=analysis,
    )


def _prefer_measure_scale_when_compatible(
    analysis: MeasureAnalysis,
    measure_scale: Candidate,
) -> MeasureAnalysis:
    if not analysis.scale_candidates:
        return analysis
    if any(pc not in set(measure_scale.pitch_classes) for pc in analysis.note_pitch_classes):
        return analysis

    existing = {candidate.name: candidate for candidate in analysis.scale_candidates}
    compatible = existing.get(measure_scale.name)
    if compatible is None:
        compatible = replace(
            measure_scale,
            score=max(analysis.scale_candidates[0].score, min(100, measure_scale.score)),
            matched_notes=sum(1 for pc in analysis.note_pitch_classes if pc in set(measure_scale.pitch_classes)),
            total_notes=len(analysis.note_pitch_classes),
            outside_notes=0,
        )

    promoted = replace(compatible, score=max(compatible.score, analysis.scale_candidates[0].score))
    reordered = [promoted]
    for candidate in analysis.scale_candidates:
        if candidate.name != promoted.name:
            reordered.append(candidate)
    return replace(analysis, scale_candidates=tuple(reordered))


def _merge_compatible_scale_segments(
    segments: tuple[SegmentData, ...],
    context: Candidate,
    measure_scale: Candidate | None,
) -> tuple[SegmentData, ...]:
    if len(segments) <= 1:
        return segments

    merged: list[SegmentData] = []
    for segment in segments:
        if merged and _segments_share_scale(merged[-1], segment):
            previous = merged[-1]
            combined_beats = previous.beats + segment.beats
            combined = SegmentData(
                index=previous.index,
                start_in_measure=previous.start_in_measure,
                end_in_measure=segment.end_in_measure,
                beats=combined_beats,
                analysis=analyze_midi_notes([note.midi for beat in combined_beats for note in beat.notes], context=context),
            )
            if measure_scale is not None:
                combined = replace(
                    combined,
                    analysis=_prefer_measure_scale_when_compatible(combined.analysis, measure_scale),
                )
            merged[-1] = combined
        else:
            merged.append(replace(segment, index=len(merged)))

    return tuple(replace(segment, index=index) for index, segment in enumerate(merged))


def _segments_share_scale(left: SegmentData, right: SegmentData) -> bool:
    if not left.analysis.scale_candidates or not right.analysis.scale_candidates:
        return False
    return left.analysis.scale_candidates[0].name == right.analysis.scale_candidates[0].name


def _retune_measure_notes(
    measure: MeasureData,
    open_pitch_by_string: dict[int, int],
) -> MeasureData:
    beats = tuple(_retune_beat_notes(beat, open_pitch_by_string) for beat in measure.beats)
    segments = tuple(
        SegmentData(
            index=segment.index,
            start_in_measure=segment.start_in_measure,
            end_in_measure=segment.end_in_measure,
            beats=tuple(_retune_beat_notes(beat, open_pitch_by_string) for beat in segment.beats),
            analysis=segment.analysis,
        )
        for segment in measure.segments
    )
    retuned = replace(measure, beats=beats, segments=segments)
    return replace(
        retuned,
        analysis=analyze_midi_notes([note.midi for note in retuned.notes]),
        segments=tuple(
            replace(
                segment,
                analysis=analyze_midi_notes([note.midi for note in segment.notes]),
            )
            for segment in retuned.segments
        ),
    )


def _retune_beat_notes(
    beat: BeatData,
    open_pitch_by_string: dict[int, int],
) -> BeatData:
    notes = tuple(
        replace(note, midi=open_pitch_by_string[note.string] + note.fret)
        for note in beat.notes
        if note.string in open_pitch_by_string
    )
    return replace(beat, notes=notes)


def _apply_scale_tie_breakers(measures: tuple[MeasureData, ...]) -> tuple[MeasureData, ...]:
    popularity = _scale_rank_popularity(measures)
    adjusted: list[MeasureData] = []

    for measure in measures:
        current_measure_popularity = _scale_rank_popularity((measure,))
        analysis = _analysis_with_scale_tie_order(
            measure.analysis,
            popularity,
            current_measure_popularity,
        )
        measure_scale = analysis.scale_candidates[0] if analysis.scale_candidates else None
        segments = tuple(
            replace(
                segment,
                analysis=_prefer_measure_scale_when_compatible(
                    _analysis_with_scale_tie_order(
                        segment.analysis,
                        popularity,
                        current_measure_popularity,
                    ),
                    measure_scale,
                ),
            )
            for segment in measure.segments
        )
        if measure_scale is not None:
            segments = _merge_compatible_scale_segments(segments, measure_scale, measure_scale)
        adjusted.append(replace(measure, analysis=analysis, segments=segments))

    return tuple(adjusted)


def _scale_rank_popularity(measures: tuple[MeasureData, ...]) -> Counter[str]:
    popularity: Counter[str] = Counter()
    for measure in measures:
        for rank, candidate in enumerate(measure.analysis.scale_candidates[:12]):
            popularity[candidate.name] += max(1, 12 - rank)
    return popularity


def _analysis_with_scale_tie_order(
    analysis: MeasureAnalysis,
    popularity: Counter[str],
    current_measure_popularity: Counter[str],
) -> MeasureAnalysis:
    if len(analysis.scale_candidates) <= 1:
        return analysis

    sorted_scales = tuple(
        sorted(
            analysis.scale_candidates,
            key=lambda candidate: (
                -candidate.score,
                -(popularity[candidate.name] - current_measure_popularity[candidate.name]),
                candidate.outside_notes,
                -candidate.matched_notes,
                candidate.name,
            ),
        )
    )
    return replace(analysis, scale_candidates=sorted_scales)


def _scale_family(scale_name: str) -> str:
    lowered = scale_name.lower()
    harmonic_minor_families = (
        "altered diminished",
        "locrian natural 6",
        "ionian augmented",
        "phrygian dominant",
        "harmonic minor",
        "dorian #4",
        "lydian #2",
    )
    for family in harmonic_minor_families:
        if family in lowered:
            return "harmonic minor"
    if "minor pentatonic" in lowered or "blues" in lowered:
        return "minor pentatonic"
    if "major pentatonic" in lowered:
        return "major pentatonic"
    if "minor" in lowered or "dorian" in lowered or "phrygian" in lowered or "locrian" in lowered:
        return "minor"
    return "major"


def _build_segments(
    beats: tuple[BeatData, ...],
    length_ticks: int,
    time_signature: object | None,
) -> tuple[SegmentData, ...]:
    note_beats = tuple(beat for beat in beats if beat.notes)
    if not note_beats:
        return ()

    region_count = _segment_region_count(time_signature)
    raw_segments: list[SegmentData] = []
    for index in range(region_count):
        start = round((length_ticks * index) / region_count)
        end = round((length_ticks * (index + 1)) / region_count)
        if index == region_count - 1:
            end = length_ticks
        region_beats = tuple(
            beat
            for beat in note_beats
            if start <= beat.start_in_measure < end or (index == region_count - 1 and beat.start_in_measure == length_ticks)
        )
        if not region_beats:
            continue

        midi_notes = [note.midi for beat in region_beats for note in beat.notes]
        raw_segments.append(
            SegmentData(
                index=len(raw_segments),
                start_in_measure=start,
                end_in_measure=max(start + 1, end),
                beats=region_beats,
                analysis=analyze_midi_notes(midi_notes),
            )
        )

    return _merge_equivalent_segments(raw_segments)


def _segment_region_count(time_signature: object | None) -> int:
    if time_signature is None:
        return 4
    if isinstance(time_signature, str):
        try:
            return max(1, min(12, int(time_signature.split("/", 1)[0])))
        except ValueError:
            return 4
    numerator = int(getattr(time_signature, "numerator", 4) or 4)
    return max(1, min(12, numerator))


def _merge_equivalent_segments(segments: list[SegmentData]) -> tuple[SegmentData, ...]:
    merged: list[SegmentData] = []
    for segment in segments:
        if merged and _segment_signature(merged[-1]) == _segment_signature(segment):
            previous = merged[-1]
            combined_beats = previous.beats + segment.beats
            midi_notes = [note.midi for beat in combined_beats for note in beat.notes]
            merged[-1] = SegmentData(
                index=previous.index,
                start_in_measure=previous.start_in_measure,
                end_in_measure=segment.end_in_measure,
                beats=combined_beats,
                analysis=analyze_midi_notes(midi_notes),
            )
        else:
            merged.append(
                SegmentData(
                    index=len(merged),
                    start_in_measure=segment.start_in_measure,
                    end_in_measure=segment.end_in_measure,
                    beats=segment.beats,
                    analysis=segment.analysis,
                )
            )
    return tuple(merged)


def _segment_signature(segment: SegmentData) -> tuple[str, str]:
    scale = segment.analysis.scale_candidates[0].name if segment.analysis.scale_candidates else ""
    chord = segment.analysis.chord_candidates[0].name if segment.analysis.chord_candidates else ""
    return scale, chord


def _time_signature_text(time_signature: object | None) -> str:
    if time_signature is None:
        return "4/4"
    numerator = getattr(time_signature, "numerator", 4)
    denominator = getattr(getattr(time_signature, "denominator", None), "value", 4)
    return f"{numerator}/{denominator}"


def _midi_name(midi: int, prefer_flats: bool | None = None) -> str:
    return midi_note_name(midi, prefer_flats)


def _prefer_flats_for_tuning(tuning: Iterable[int]) -> bool | None:
    return prefer_flats_from_pitch_classes(midi % 12 for midi in tuning)


def _candidate_text(candidates: tuple[object, ...]) -> str:
    if not candidates:
        return "-"
    return ", ".join(getattr(candidate, "label", str(candidate)) for candidate in candidates[:3])


def _segment_text(measure: MeasureData) -> str:
    if len(measure.segments) <= 1:
        return ""
    parts: list[str] = []
    for segment in measure.segments:
        scale = _candidate_text(segment.analysis.scale_candidates[:1])
        chord = _candidate_text(segment.analysis.chord_candidates[:1])
        start_percent = round((segment.start_in_measure / measure.length_ticks) * 100)
        end_percent = round((segment.end_in_measure / measure.length_ticks) * 100)
        parts.append(f"{start_percent}-{end_percent}% S={scale} C={chord}")
    return " > ".join(parts)
