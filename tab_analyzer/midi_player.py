"""Small MIDI playback helper for Guitar Pro tab data."""

from __future__ import annotations

import ctypes
import sys
from bisect import bisect_right
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QElapsedTimer, Qt, QTimer, pyqtSignal

from .gp_loader import MeasureData, SongData, TabNote, TempoChange


TICKS_PER_QUARTER = 960
GUITAR_CHANNEL = 0
DRUM_CHANNEL = 9
GUITAR_PROGRAM = 29
METRONOME_ACCENT_NOTE = 76
METRONOME_TICK_NOTE = 77
MIN_AUDIBLE_NOTE_MS = 32
MIN_AUDIBLE_MUTED_NOTE_MS = 22
MIN_AUDIBLE_DRUM_MS = 18
POSITION_UPDATE_INTERVAL_MS = 33
NOTE_RELEASE_GAP_TICKS = 12


@dataclass(frozen=True)
class PlaybackEvent:
    tick: int
    kind: str
    note: int
    velocity: int
    duration_ticks: int = 0
    channel: int = GUITAR_CHANNEL
    string: int = 0


class MidiOutput:
    def __init__(self) -> None:
        self._handle = ctypes.c_void_p()
        self.available = False
        self.error = ""
        self._winmm = None
        if sys.platform.startswith("win"):
            self._open_windows_midi()
        else:
            self.error = "The built-in MIDI output currently uses Windows winmm devices."

    def close(self) -> None:
        self.all_notes_off()
        if self._winmm is not None and self._handle.value:
            self._winmm.midiOutClose(self._handle)
            self._handle = ctypes.c_void_p()
        self.available = False

    def note_on(self, note: int, velocity: int, channel: int = GUITAR_CHANNEL) -> None:
        if self.available:
            self._short_message(0x90 | (channel & 0x0F), note, velocity)

    def note_off(self, note: int, channel: int = GUITAR_CHANNEL) -> None:
        if self.available:
            self._short_message(0x80 | (channel & 0x0F), note, 0)

    def all_notes_off(self) -> None:
        if not self.available:
            return
        for channel in range(16):
            self._short_message(0xB0 | channel, 123, 0)

    def _open_windows_midi(self) -> None:
        try:
            self._winmm = ctypes.WinDLL("winmm")
            result = self._winmm.midiOutOpen(ctypes.byref(self._handle), ctypes.c_uint(-1), 0, 0, 0)
        except OSError as exc:
            self.error = str(exc)
            return
        if result != 0:
            self.error = f"midiOutOpen failed: {result}"
            return
        self.available = True
        self._short_message(0xC0 | GUITAR_CHANNEL, GUITAR_PROGRAM, 0)

    def _short_message(self, status: int, data1: int, data2: int) -> None:
        if self._winmm is None or not self._handle.value:
            return
        message = (status & 0xFF) | ((data1 & 0x7F) << 8) | ((data2 & 0x7F) << 16)
        self._winmm.midiOutShortMsg(self._handle, ctypes.c_uint(message))


class TabMidiPlayer(QObject):
    positionChanged = pyqtSignal(int)
    playingChanged = pyqtSignal(bool)
    finished = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.output = MidiOutput()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(12)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.song: SongData | None = None
        self.events: list[PlaybackEvent] = []
        self.event_index = 0
        self.start_tick = 0
        self.end_tick = 0
        self.current_tick = 0.0
        self.speed_percent = 100
        self.repeat = False
        self.playing = False
        self.start_measure_index = 0
        self.end_measure_index = 0
        self.metronome = False
        self._ticks_per_ms = 1.0
        self._note_generation = 0
        self._active_note_generations: dict[tuple[int, int], int] = {}
        self._active_string_notes: dict[tuple[int, int], tuple[int, int]] = {}
        self._position_emit_elapsed_ms = 0

    @property
    def is_midi_available(self) -> bool:
        return self.output.available

    @property
    def midi_error(self) -> str:
        return self.output.error

    def start(
        self,
        song: SongData,
        start_measure_index: int,
        end_measure_index: int,
        *,
        repeat: bool,
        speed_percent: int,
        metronome: bool,
        play_from_measure_index: int | None = None,
        play_from_tick: int | None = None,
    ) -> None:
        if not song.track.measures:
            return
        self.stop(emit=False)
        start_measure_index, end_measure_index = _clamp_range(
            start_measure_index,
            end_measure_index,
            len(song.track.measures),
        )
        measures = song.track.measures[start_measure_index : end_measure_index + 1]
        self.song = song
        self.repeat = repeat
        self.speed_percent = speed_percent
        self.start_measure_index = start_measure_index
        self.end_measure_index = end_measure_index
        self.metronome = metronome
        self.start_tick = measures[0].start_tick
        self.end_tick = measures[-1].start_tick + measures[-1].length_ticks
        self.events = _build_events(measures, metronome)
        start_tick = self._play_from_tick(song, start_measure_index, end_measure_index, play_from_measure_index, play_from_tick)
        self.current_tick = float(start_tick)
        self.event_index = _event_index_at_or_after(self.events, start_tick)
        self._stop_active_notes()
        self._position_emit_elapsed_ms = 0
        self.clock.start()
        self.timer.start()
        self.playing = True
        self.playingChanged.emit(True)
        self.positionChanged.emit(start_tick)

    def stop(self, emit: bool = True) -> None:
        self.timer.stop()
        self._stop_active_notes()
        was_playing = self.playing
        self.playing = False
        self.event_index = 0
        if emit and was_playing:
            self.playingChanged.emit(False)
            self.finished.emit()

    def set_speed_percent(self, value: int) -> None:
        self.speed_percent = max(25, min(300, int(value)))

    def set_metronome_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.metronome == enabled:
            return
        self.metronome = enabled
        self.output.note_off(METRONOME_ACCENT_NOTE, DRUM_CHANNEL)
        self.output.note_off(METRONOME_TICK_NOTE, DRUM_CHANNEL)
        if self.song is None:
            return
        measures = self.song.track.measures[self.start_measure_index : self.end_measure_index + 1]
        self.events = _build_events(measures, self.metronome)
        self.event_index = _event_index_at_or_after(self.events, int(self.current_tick))

    def close(self) -> None:
        self.stop(emit=False)
        self.output.close()

    def _play_from_tick(
        self,
        song: SongData,
        start_measure_index: int,
        end_measure_index: int,
        play_from_measure_index: int | None,
        play_from_tick: int | None,
    ) -> int:
        if play_from_tick is not None:
            return max(self.start_tick, min(int(play_from_tick), self.end_tick))
        if play_from_measure_index is None:
            return self.start_tick
        play_from_measure_index = max(start_measure_index, min(play_from_measure_index, end_measure_index))
        return song.track.measures[play_from_measure_index].start_tick

    def _tick(self) -> None:
        if self.song is None or not self.playing:
            return
        elapsed_ms = max(0, self.clock.restart())
        self.current_tick = advance_song_tick_by_milliseconds(self.song, self.current_tick, elapsed_ms, self.speed_percent)
        self._ticks_per_ms = ticks_per_millisecond(self.song, self.current_tick, self.speed_percent)
        self._position_emit_elapsed_ms += elapsed_ms

        while self.event_index < len(self.events) and self.events[self.event_index].tick <= self.current_tick:
            self._send_event(self.events[self.event_index])
            self.event_index += 1

        if self.current_tick >= self.end_tick:
            if self.repeat:
                self._stop_active_notes()
                self.current_tick = float(self.start_tick)
                self.event_index = 0
                self._position_emit_elapsed_ms = 0
                self.clock.restart()
                self.positionChanged.emit(self.start_tick)
                return
            self.positionChanged.emit(self.end_tick)
            self.stop()
            return

        if self._position_emit_elapsed_ms >= POSITION_UPDATE_INTERVAL_MS:
            self._position_emit_elapsed_ms = 0
            self.positionChanged.emit(int(self.current_tick))

    def _send_event(self, event: PlaybackEvent) -> None:
        if event.kind == "note_on":
            self._start_note(event)
        elif event.kind == "note_off":
            self._stop_note((event.channel, event.note))

    def _start_note(self, event: PlaybackEvent) -> None:
        key = (event.channel, event.note)
        string_key = (event.channel, event.string) if event.string else None
        if string_key is not None:
            previous_key = self._active_string_notes.get(string_key)
            if previous_key is not None and previous_key != key:
                self._stop_note(previous_key)
        if key in self._active_note_generations:
            self.output.note_off(event.note, event.channel)
        self._note_generation += 1
        generation = self._note_generation
        self._active_note_generations[key] = generation
        if string_key is not None:
            self._active_string_notes[string_key] = key
        self.output.note_on(event.note, event.velocity, event.channel)
        _single_shot(self._event_duration_ms(event), lambda item=key, gen=generation: self._finish_note(item, gen))

    def _finish_note(self, key: tuple[int, int], generation: int) -> None:
        if self._active_note_generations.get(key) != generation:
            return
        self._stop_note(key)

    def _stop_note(self, key: tuple[int, int]) -> None:
        channel, note = key
        if key in self._active_note_generations:
            del self._active_note_generations[key]
        for string_key, note_key in tuple(self._active_string_notes.items()):
            if note_key == key:
                del self._active_string_notes[string_key]
        self.output.note_off(note, channel)

    def _stop_active_notes(self) -> None:
        self._active_note_generations.clear()
        self._active_string_notes.clear()
        self.output.all_notes_off()

    def _event_duration_ms(self, event: PlaybackEvent) -> int:
        if self.song is not None:
            duration_ms = round(milliseconds_for_song_ticks(self.song, event.tick, max(1, event.duration_ticks), self.speed_percent))
        else:
            duration_ms = round(max(1, event.duration_ticks) / max(0.001, self._ticks_per_ms))
        return max(_minimum_audible_ms(event), duration_ms)


def _build_events(measures: tuple[MeasureData, ...], metronome: bool) -> list[PlaybackEvent]:
    events: list[PlaybackEvent] = []
    scheduled_notes: list[tuple[TabNote, int]] = []
    for measure in measures:
        measure_end = measure.start_tick + measure.length_ticks
        for beat in measure.beats:
            if not beat.notes:
                continue
            for note in beat.notes:
                scheduled_notes.append((note, measure_end))
        if metronome:
            events.extend(_metronome_events(measure))
    scheduled_notes.sort(key=lambda item: (item[0].start_tick, item[0].string, item[0].midi))
    next_start_by_index: list[int | None] = [None] * len(scheduled_notes)
    next_start_by_string: dict[int, int] = {}
    for index in range(len(scheduled_notes) - 1, -1, -1):
        note, _measure_end = scheduled_notes[index]
        next_start_by_index[index] = next_start_by_string.get(note.string)
        next_start_by_string[note.string] = note.start_tick
    for index, (note, measure_end) in enumerate(scheduled_notes):
        events.extend(_note_events(note, measure_end, next_start_by_index[index]))
    return sorted(events, key=lambda event: (event.tick, event.channel, event.note))


def _note_events(note: TabNote, measure_end_tick: int, next_string_tick: int | None = None) -> list[PlaybackEvent]:
    if note.is_muted:
        velocity = 34
        duration = min(max(30, note.duration_ticks // 6), 120)
    else:
        velocity = max(1, min(127, note.velocity or 92))
        if "palm_mute" in note.techniques or "staccato" in note.techniques:
            duration = max(40, min(note.duration_ticks, round(note.duration_ticks * 0.45)))
        else:
            duration = max(40, round(note.duration_ticks * 0.9))
    max_end_tick = measure_end_tick
    if next_string_tick is not None and next_string_tick > note.start_tick:
        max_end_tick = min(max_end_tick, max(note.start_tick + 1, next_string_tick - NOTE_RELEASE_GAP_TICKS))
    off_tick = min(max_end_tick, note.start_tick + duration)
    return [PlaybackEvent(note.start_tick, "note_on", note.midi, velocity, max(1, off_tick - note.start_tick), string=note.string)]


def _metronome_events(measure: MeasureData) -> list[PlaybackEvent]:
    events: list[PlaybackEvent] = []
    numerator = _time_signature_numerator(measure.time_signature)
    step = max(1, round(measure.length_ticks / numerator))
    for index in range(numerator):
        tick = measure.start_tick + (index * step)
        note = METRONOME_ACCENT_NOTE if index == 0 else METRONOME_TICK_NOTE
        velocity = 108 if index == 0 else 76
        events.append(PlaybackEvent(tick, "note_on", note, velocity, duration_ticks=80, channel=DRUM_CHANNEL))
    return events


def _minimum_audible_ms(event: PlaybackEvent) -> int:
    if event.channel == DRUM_CHANNEL:
        return MIN_AUDIBLE_DRUM_MS
    if event.velocity <= 40:
        return MIN_AUDIBLE_MUTED_NOTE_MS
    return MIN_AUDIBLE_NOTE_MS


def _single_shot(milliseconds: int, callback) -> None:
    QTimer.singleShot(max(1, int(milliseconds)), callback)


def _time_signature_numerator(time_signature: str) -> int:
    try:
        return max(1, int(time_signature.split("/", 1)[0]))
    except (ValueError, IndexError):
        return 4


def _clamp_range(start_index: int, end_index: int, measure_count: int) -> tuple[int, int]:
    start = max(0, min(start_index, measure_count - 1))
    end = max(0, min(end_index, measure_count - 1))
    if end < start:
        start, end = end, start
    return start, end


def _event_index_at_or_after(events: list[PlaybackEvent], tick: int) -> int:
    for index, event in enumerate(events):
        if event.tick >= tick:
            return index
    return len(events)


def tempo_at_tick(song: SongData, tick: int | float) -> int:
    changes = _song_tempo_changes(song)
    return _tempo_at_tick_from_changes(changes, tick)


def ticks_per_millisecond(song: SongData, tick: int | float, speed_percent: int = 100) -> float:
    speed = max(0.01, float(speed_percent) / 100.0)
    return max(0.001, tempo_at_tick(song, tick) * speed * TICKS_PER_QUARTER / 60000.0)


def advance_song_tick_by_milliseconds(
    song: SongData,
    start_tick: int | float,
    milliseconds: int | float,
    speed_percent: int = 100,
) -> float:
    return song_tick_for_seconds(song, start_tick, float(milliseconds) / 1000.0, speed_percent)


def milliseconds_for_song_ticks(
    song: SongData,
    start_tick: int | float,
    ticks: int | float,
    speed_percent: int = 100,
) -> float:
    return song_seconds_between_ticks(song, start_tick, float(start_tick) + max(0.0, float(ticks)), speed_percent) * 1000.0


def song_seconds_between_ticks(
    song: SongData,
    start_tick: int | float,
    end_tick: int | float,
    speed_percent: int = 100,
) -> float:
    start = float(start_tick)
    end = float(end_tick)
    if end <= start:
        return 0.0
    speed = max(0.01, float(speed_percent) / 100.0)
    changes = _song_tempo_changes(song)
    change_ticks = [change.tick for change in changes]
    seconds = 0.0
    tick = start
    while tick < end:
        tempo = _tempo_at_tick_from_changes(changes, tick)
        ticks_per_second = max(0.001, tempo * speed * TICKS_PER_QUARTER / 60.0)
        change_index = bisect_right(change_ticks, tick)
        next_change_tick = change_ticks[change_index] if change_index < len(change_ticks) else end
        segment_end = min(end, max(tick, float(next_change_tick)))
        if segment_end <= tick:
            segment_end = end
        seconds += (segment_end - tick) / ticks_per_second
        tick = segment_end
    return seconds


def song_tick_for_seconds(
    song: SongData,
    start_tick: int | float,
    seconds: int | float,
    speed_percent: int = 100,
) -> float:
    remaining_seconds = max(0.0, float(seconds))
    tick = float(start_tick)
    if remaining_seconds <= 0:
        return tick
    speed = max(0.01, float(speed_percent) / 100.0)
    changes = _song_tempo_changes(song)
    change_ticks = [change.tick for change in changes]
    while remaining_seconds > 0:
        tempo = _tempo_at_tick_from_changes(changes, tick)
        ticks_per_second = max(0.001, tempo * speed * TICKS_PER_QUARTER / 60.0)
        change_index = bisect_right(change_ticks, tick)
        next_change_tick = change_ticks[change_index] if change_index < len(change_ticks) else None
        if next_change_tick is None:
            return tick + (remaining_seconds * ticks_per_second)
        ticks_until_change = max(0.0, float(next_change_tick) - tick)
        seconds_until_change = ticks_until_change / ticks_per_second
        if remaining_seconds <= seconds_until_change:
            return tick + (remaining_seconds * ticks_per_second)
        tick = float(next_change_tick)
        remaining_seconds -= seconds_until_change
    return tick


def _song_tempo_changes(song: SongData) -> tuple[TempoChange, ...]:
    raw_changes = tuple(getattr(song, "tempo_changes", ()) or ())
    by_tick: dict[int, int] = {}
    for change in raw_changes:
        tick = max(0, int(getattr(change, "tick", 0) or 0))
        bpm = max(1, int(getattr(change, "bpm", 0) or 0))
        by_tick[tick] = bpm
    if 0 not in by_tick:
        by_tick[0] = max(1, int(getattr(song, "tempo", 120) or 120))
    return tuple(TempoChange(tick, bpm) for tick, bpm in sorted(by_tick.items()))


def _tempo_at_tick_from_changes(changes: tuple[TempoChange, ...], tick: int | float) -> int:
    if not changes:
        return 120
    ticks = [change.tick for change in changes]
    index = max(0, bisect_right(ticks, float(tick)) - 1)
    return changes[index].bpm
