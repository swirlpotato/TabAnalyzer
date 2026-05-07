"""Small MIDI playback helper for Guitar Pro tab data."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QElapsedTimer, QTimer, pyqtSignal

from .gp_loader import MeasureData, SongData, TabNote


TICKS_PER_QUARTER = 960
GUITAR_CHANNEL = 0
DRUM_CHANNEL = 9
GUITAR_PROGRAM = 29
METRONOME_ACCENT_NOTE = 76
METRONOME_TICK_NOTE = 77
MIN_AUDIBLE_NOTE_MS = 32
MIN_AUDIBLE_MUTED_NOTE_MS = 22
MIN_AUDIBLE_DRUM_MS = 18


@dataclass(frozen=True)
class PlaybackEvent:
    tick: int
    kind: str
    note: int
    velocity: int
    duration_ticks: int = 0
    channel: int = GUITAR_CHANNEL


class MidiOutput:
    def __init__(self) -> None:
        self._handle = ctypes.c_void_p()
        self.available = False
        self.error = ""
        self._winmm = None
        if sys.platform.startswith("win"):
            self._open_windows_midi()
        else:
            self.error = "현재 내장 MIDI 출력은 Windows winmm 장치를 사용합니다."

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
        ticks_per_ms = (self.song.tempo * (self.speed_percent / 100.0) * TICKS_PER_QUARTER) / 60000.0
        self._ticks_per_ms = max(0.001, ticks_per_ms)
        self.current_tick += elapsed_ms * ticks_per_ms

        while self.event_index < len(self.events) and self.events[self.event_index].tick <= self.current_tick:
            self._send_event(self.events[self.event_index])
            self.event_index += 1

        if self.current_tick >= self.end_tick:
            if self.repeat:
                self._stop_active_notes()
                self.current_tick = float(self.start_tick)
                self.event_index = 0
                self.clock.restart()
                self.positionChanged.emit(self.start_tick)
                return
            self.positionChanged.emit(self.end_tick)
            self.stop()
            return

        self.positionChanged.emit(int(self.current_tick))

    def _send_event(self, event: PlaybackEvent) -> None:
        if event.kind == "note_on":
            self._start_note(event)
        elif event.kind == "note_off":
            self._stop_note((event.channel, event.note))

    def _start_note(self, event: PlaybackEvent) -> None:
        key = (event.channel, event.note)
        if key in self._active_note_generations:
            self.output.note_off(event.note, event.channel)
        self._note_generation += 1
        generation = self._note_generation
        self._active_note_generations[key] = generation
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
        self.output.note_off(note, channel)

    def _stop_active_notes(self) -> None:
        self._active_note_generations.clear()
        self.output.all_notes_off()

    def _event_duration_ms(self, event: PlaybackEvent) -> int:
        duration_ms = round(max(1, event.duration_ticks) / max(0.001, self._ticks_per_ms))
        return max(_minimum_audible_ms(event), duration_ms)


def _build_events(measures: tuple[MeasureData, ...], metronome: bool) -> list[PlaybackEvent]:
    events: list[PlaybackEvent] = []
    for measure in measures:
        measure_end = measure.start_tick + measure.length_ticks
        for beat in measure.beats:
            if not beat.notes:
                continue
            for note in beat.notes:
                events.extend(_note_events(note, measure_end))
        if metronome:
            events.extend(_metronome_events(measure))
    return sorted(events, key=lambda event: (event.tick, event.channel, event.note))


def _note_events(note: TabNote, measure_end_tick: int) -> list[PlaybackEvent]:
    if note.is_muted:
        velocity = 34
        duration = min(max(30, note.duration_ticks // 6), 120)
    else:
        velocity = max(1, min(127, note.velocity or 92))
        if "palm_mute" in note.techniques or "staccato" in note.techniques:
            duration = max(40, min(note.duration_ticks, round(note.duration_ticks * 0.45)))
        else:
            duration = max(40, round(note.duration_ticks * 0.9))
    off_tick = min(measure_end_tick, note.start_tick + duration)
    return [PlaybackEvent(note.start_tick, "note_on", note.midi, velocity, max(1, off_tick - note.start_tick))]


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
