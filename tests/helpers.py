from __future__ import annotations

from pathlib import Path
import zipfile

from tab_analyzer.analysis import Candidate, MeasureAnalysis, analyze_midi_notes, prefer_flats_from_pitch_classes
from tab_analyzer.gp_loader import BeatData, MeasureData, SegmentData, SongData, TabNote, TrackData


STANDARD_TUNING = (64, 59, 55, 50, 45, 40)
FLAT_TUNING = (63, 58, 54, 49, 44, 39)

A_NATURAL_MINOR = Candidate("scale", "A natural minor", 9, (0, 2, 3, 5, 7, 8, 10), 100, 7, 7, 0)
A_DORIAN = Candidate("scale", "A dorian", 9, (0, 2, 3, 5, 7, 9, 10), 100, 7, 7, 0)
A_MINOR_PENTATONIC = Candidate("scale", "A minor pentatonic", 9, (0, 3, 5, 7, 10), 100, 5, 5, 0)
C_MAJOR = Candidate("scale", "C major", 0, (0, 2, 4, 5, 7, 9, 11), 100, 7, 7, 0)
C_CHORD = Candidate("chord", "C", 0, (0, 4, 7), 100, 3, 3, 0)
AM_CHORD = Candidate("chord", "Am", 9, (0, 3, 7), 100, 3, 3, 0)


def tab_note(string: int, fret: int, start_in_measure: int = 0, tuning: tuple[int, ...] = STANDARD_TUNING) -> TabNote:
    return TabNote(
        string=string,
        fret=fret,
        midi=tuning[string - 1] + fret,
        start_tick=start_in_measure,
        start_in_measure=start_in_measure,
        duration_ticks=480,
        velocity=100,
    )


def beat(start_in_measure: int, notes: tuple[TabNote, ...]) -> BeatData:
    return BeatData(
        start_tick=start_in_measure,
        start_in_measure=start_in_measure,
        duration_ticks=480,
        notes=notes,
    )


def measure(
    number: int,
    beats: tuple[BeatData, ...],
    scales: tuple[Candidate, ...] | None = None,
    chords: tuple[Candidate, ...] | None = None,
    segments: tuple[SegmentData, ...] = (),
) -> MeasureData:
    notes = tuple(note for item in beats for note in item.notes)
    analysis = analyze_midi_notes([note.midi for note in notes])
    if scales is not None or chords is not None:
        analysis = MeasureAnalysis(
            tuple(sorted({note.midi % 12 for note in notes})),
            scales if scales is not None else analysis.scale_candidates,
            chords if chords is not None else analysis.chord_candidates,
        )
    return MeasureData(
        number=number,
        start_tick=(number - 1) * 3840,
        length_ticks=3840,
        time_signature="4/4",
        beats=beats,
        segments=segments,
        analysis=analysis,
    )


def segment(index: int, start: int, end: int, beats: tuple[BeatData, ...], scale: Candidate, chord: Candidate | None = None) -> SegmentData:
    notes = tuple(note for item in beats for note in item.notes)
    return SegmentData(
        index=index,
        start_in_measure=start,
        end_in_measure=end,
        beats=beats,
        analysis=MeasureAnalysis(
            tuple(sorted({note.midi % 12 for note in notes})),
            (scale,),
            (chord,) if chord is not None else (),
        ),
    )


def song_with_measures(
    measures: tuple[MeasureData, ...],
    tuning: tuple[int, ...] = STANDARD_TUNING,
    title: str = "Synthetic Song",
) -> SongData:
    midi_notes = [note.midi for measure_data in measures for note in measure_data.notes]
    return SongData(
        title=title,
        artist="Test Artist",
        album="",
        path=Path("synthetic.gp"),
        global_analysis=analyze_midi_notes(midi_notes),
        track=TrackData(
            name="Lead Guitar",
            number=1,
            fret_count=24,
            string_pitches=tuning,
            measures=measures,
            prefer_flats=prefer_flats_from_pitch_classes(midi % 12 for midi in tuning),
        ),
    )


def scale_fixture_song() -> SongData:
    phrase = (
        beat(0, (tab_note(2, 10, 0),)),
        beat(480, (tab_note(2, 13, 480),)),
        beat(960, (tab_note(3, 12, 960),)),
    )
    shifted = (
        beat(0, (tab_note(5, 12, 0),)),
        beat(480, (tab_note(4, 9, 480),)),
        beat(960, (tab_note(3, 9, 960),)),
        beat(1440, (tab_note(2, 10, 1440),)),
    )
    return song_with_measures(
        (
            measure(1, phrase, scales=(A_MINOR_PENTATONIC, A_NATURAL_MINOR)),
            measure(2, shifted, scales=(A_NATURAL_MINOR, A_MINOR_PENTATONIC)),
            measure(3, shifted, scales=(A_NATURAL_MINOR, A_MINOR_PENTATONIC)),
            measure(4, phrase, scales=(A_MINOR_PENTATONIC, A_NATURAL_MINOR)),
        )
    )


def theory_fixture_song() -> SongData:
    first_beats = (
        beat(0, (tab_note(5, 3, 0), tab_note(4, 2, 0), tab_note(3, 0, 0))),
        beat(960, (tab_note(2, 1, 960),)),
    )
    second_beats = (
        beat(0, (tab_note(5, 0, 0), tab_note(4, 2, 0), tab_note(3, 2, 0))),
        beat(960, (tab_note(2, 1, 960),)),
    )
    first_segment = segment(0, 0, 3840, first_beats, C_MAJOR, C_CHORD)
    second_segment = segment(0, 0, 3840, second_beats, C_MAJOR, AM_CHORD)
    return song_with_measures(
        (
            measure(9, first_beats, scales=(C_MAJOR,), chords=(C_CHORD,), segments=(first_segment,)),
            measure(10, second_beats, scales=(C_MAJOR,), chords=(AM_CHORD,), segments=(second_segment,)),
        ),
        title="Theory Fixture",
    )


def write_gpif_fixture(path: Path) -> Path:
    bars = " ".join(str(index) for index in range(8))
    empty_bars = "\n".join(f'<Bar id="{index}"><Voices>-1</Voices></Bar>' for index in range(8) if index not in {2, 7})
    gpif = f"""<?xml version="1.0" encoding="utf-8"?>
<GPIF>
  <Score><Title>Fixture Song</Title><Artist>Fixture Artist</Artist><Album></Album></Score>
  <Tracks>
    <Track><Name>Vocals</Name><IconId>1</IconId><Properties><Property name="Tuning"><Pitches></Pitches></Property></Properties></Track>
    <Track><Name>Bass</Name><IconId>5</IconId><Properties><Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property><Property name="FretCount"><Number>20</Number></Property></Properties></Track>
    <Track><Name>Lead Guitar</Name><IconId>3</IconId><Properties><Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property><Property name="FretCount"><Number>24</Number></Property></Properties></Track>
    <Track><Name>Piano</Name><IconId>1</IconId><Properties><Property name="Tuning"><Pitches></Pitches></Property></Properties></Track>
    <Track><Name>Strings</Name><IconId>1</IconId><Properties><Property name="Tuning"><Pitches></Pitches></Property></Properties></Track>
    <Track><Name>Acoustic Guitar</Name><IconId>24</IconId><Properties><Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property><Property name="FretCount"><Number>24</Number></Property></Properties></Track>
    <Track><Name>Drums</Name><IconId>18</IconId><Properties><Property name="Tuning"><Pitches></Pitches></Property></Properties></Track>
    <Track><Name>Rhythm Guitar</Name><IconId>24</IconId><Properties><Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property><Property name="FretCount"><Number>24</Number></Property></Properties></Track>
  </Tracks>
  <MasterTrack>
    <Automations>
      <Automation>
        <Type>Tempo</Type>
        <Bar>0</Bar>
        <Position>0</Position>
        <Value>90 2</Value>
      </Automation>
    </Automations>
  </MasterTrack>
  <MasterBars><MasterBar><Time>4/4</Time><Bars>{bars}</Bars></MasterBar></MasterBars>
  <Bars>
    {empty_bars}
    <Bar id="2"><Voices>2</Voices></Bar>
    <Bar id="7"><Voices>7</Voices></Bar>
  </Bars>
  <Voices>
    <Voice id="2"><Beats>2</Beats></Voice>
    <Voice id="7"><Beats>7</Beats></Voice>
  </Voices>
  <Beats>
    <Beat id="2"><Notes>20 21 22</Notes><Rhythm ref="1"/></Beat>
    <Beat id="7"><Notes>70 71 72</Notes><Rhythm ref="1"/><Properties><Property name="TremoloBar"/></Properties></Beat>
  </Beats>
  <Rhythms><Rhythm id="1"><NoteValue>quarter</NoteValue></Rhythm></Rhythms>
  <Notes>
    <Note id="20"><Properties><Property name="String"><String>0</String></Property><Property name="Fret"><Fret>3</Fret></Property></Properties></Note>
    <Note id="21"><Properties><Property name="String"><String>1</String></Property><Property name="Fret"><Fret>2</Fret></Property></Properties></Note>
    <Note id="22"><Properties><Property name="String"><String>2</String></Property><Property name="Fret"><Fret>0</Fret></Property></Properties></Note>
    <Note id="70"><Properties><Property name="String"><String>0</String></Property><Property name="Fret"><Fret>5</Fret></Property><Property name="Slide"><Flags>4</Flags></Property></Properties></Note>
    <Note id="71"><Properties><Property name="String"><String>1</String></Property><Property name="Fret"><Fret>4</Fret></Property></Properties><LetRing/></Note>
    <Note id="72"><Properties><Property name="String"><String>2</String></Property><Property name="Fret"><Fret>2</Fret></Property><Property name="Bended"/><Property name="BendOriginValue"><Float>0</Float></Property><Property name="BendDestinationValue"><Float>1</Float></Property></Properties></Note>
  </Notes>
</GPIF>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Content/score.gpif", gpif)
    return path
