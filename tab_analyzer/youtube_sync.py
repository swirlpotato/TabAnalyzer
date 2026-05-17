"""Helpers for estimating YouTube-to-tab sync from captured audio."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Callable, Iterable

from .gp_loader import SongData
from .midi_player import TICKS_PER_QUARTER

try:
    import numpy as np
except Exception:  # noqa: BLE001 - callers report a graceful unavailable state.
    np = None


SYNC_STEP_MS = 100
AUTO_SYNC_PRE_ROLL_SECONDS = 0.45
AUTO_SYNC_TARGET_PLAY_SECONDS = 8.0
AUTO_SYNC_MIN_PLAY_SECONDS = 4.0
AUTO_SYNC_MAX_PLAY_SECONDS = 12.0
AUTO_SYNC_SEARCH_RADIUS_SECONDS = 8.0
AUTO_SYNC_MIN_ONSETS = 4
AUTO_SYNC_MIN_CONFIDENCE = 0.16


class YouTubeSyncError(RuntimeError):
    """Raised when automatic YouTube sync cannot produce a useful estimate."""


@dataclass(frozen=True)
class AudioCaptureDevice:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    default_sample_rate: int

    @property
    def display_name(self) -> str:
        return f"{self.name} [{self.host_api}]"


@dataclass(frozen=True)
class SyncEstimate:
    current_offset_ms: int
    suggested_offset_ms: int
    delta_ms: int
    confidence: float
    onset_count: int
    capture_device_name: str = ""


@dataclass(frozen=True)
class _TabOnset:
    seconds: float
    weight: float


def round_sync_milliseconds(value: int | float, step_ms: int = SYNC_STEP_MS) -> int:
    """Round a millisecond value to the nearest sync UI step."""

    step = max(1, int(step_ms))
    sign = -1 if float(value) < 0 else 1
    rounded = ((abs(int(round(float(value)))) + (step // 2)) // step) * step
    return sign * rounded


def song_seconds_for_ticks(song: SongData, ticks: int | float, speed_percent: int = 100) -> float:
    speed = max(0.01, float(speed_percent) / 100.0)
    return (float(ticks) / TICKS_PER_QUARTER) * (60.0 / max(1, song.tempo)) / speed


def ticks_for_song_seconds(song: SongData, seconds: float, speed_percent: int = 100) -> int:
    speed = max(0.01, float(speed_percent) / 100.0)
    return int(round(float(seconds) * speed * max(1, song.tempo) * TICKS_PER_QUARTER / 60.0))


def expected_tab_onsets(
    song: SongData,
    start_tick: int,
    play_seconds: float,
    speed_percent: int = 100,
    *,
    pre_roll_seconds: float = AUTO_SYNC_PRE_ROLL_SECONDS,
) -> tuple[float, ...]:
    return tuple(
        onset.seconds
        for onset in _expected_tab_onsets_with_weights(
            song,
            start_tick,
            play_seconds,
            speed_percent,
            pre_roll_seconds=pre_roll_seconds,
        )
    )


def estimate_sync_offset(
    samples: object,
    sample_rate: int,
    song: SongData,
    start_tick: int,
    play_seconds: float,
    current_offset_ms: int,
    speed_percent: int = 100,
    *,
    pre_roll_seconds: float = AUTO_SYNC_PRE_ROLL_SECONDS,
    capture_device_name: str = "",
) -> SyncEstimate:
    """Estimate the offset correction from captured YouTube audio.

    A positive delta means the captured audio attacks arrived later than the tab
    expects, so the saved YouTube offset should be increased by that amount.
    """

    onsets = _expected_tab_onsets_with_weights(
        song,
        start_tick,
        play_seconds,
        speed_percent,
        pre_roll_seconds=pre_roll_seconds,
    )
    if len(onsets) < AUTO_SYNC_MIN_ONSETS:
        raise YouTubeSyncError("Select a range with several clear note attacks, then try Auto Sync again.")

    delta_ms, confidence = estimate_delta_from_onsets(samples, sample_rate, onsets)
    if confidence < AUTO_SYNC_MIN_CONFIDENCE:
        raise YouTubeSyncError(
            "The captured audio did not match the tab strongly enough. Try a louder section with clear note attacks."
        )

    delta_ms = round_sync_milliseconds(delta_ms)
    suggested = round_sync_milliseconds(int(current_offset_ms) + delta_ms)
    return SyncEstimate(
        current_offset_ms=round_sync_milliseconds(current_offset_ms),
        suggested_offset_ms=suggested,
        delta_ms=suggested - round_sync_milliseconds(current_offset_ms),
        confidence=max(0.0, min(1.0, float(confidence))),
        onset_count=len(onsets),
        capture_device_name=capture_device_name,
    )


def estimate_delta_from_onsets(
    samples: object,
    sample_rate: int,
    onsets: Iterable[float],
    *,
    search_radius_seconds: float = AUTO_SYNC_SEARCH_RADIUS_SECONDS,
    hop_seconds: float = 0.01,
) -> tuple[int, float]:
    """Return ``(delta_ms, confidence)`` by correlating audio and tab onset envelopes."""

    if np is None:
        raise YouTubeSyncError("NumPy is required for automatic sync analysis.")
    audio = _audio_onset_envelope(samples, sample_rate, hop_seconds=hop_seconds)
    if audio.size < 16:
        raise YouTubeSyncError("Not enough audio was captured for sync analysis.")
    if float(np.sqrt(np.mean(np.square(_mono_samples(samples))))) < 0.002:
        raise YouTubeSyncError("No YouTube audio was captured. Use a loopback or stereo-mix input and try again.")

    tab = _tab_onset_envelope(tuple(onsets), audio.size, hop_seconds)
    if not np.any(tab > 0):
        raise YouTubeSyncError("The selected tab range does not contain enough note attacks.")

    audio = _normalize_envelope(audio)
    tab = _normalize_envelope(tab)
    max_lag = max(1, int(round(search_radius_seconds / hop_seconds)))
    best_lag = 0
    best_score = -1.0

    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            audio_slice = audio[lag:]
            tab_slice = tab[: audio_slice.size]
        else:
            tab_slice = tab[-lag:]
            audio_slice = audio[: tab_slice.size]
        if audio_slice.size < 16 or tab_slice.size < 16:
            continue
        denominator = float(np.linalg.norm(audio_slice) * np.linalg.norm(tab_slice))
        if denominator <= 0.0:
            continue
        score = float(np.dot(audio_slice, tab_slice) / denominator)
        if score > best_score:
            best_score = score
            best_lag = lag

    return int(round(best_lag * hop_seconds * 1000.0)), max(0.0, best_score)


def best_system_audio_capture_device() -> AudioCaptureDevice | None:
    devices = system_audio_capture_devices()
    if not devices:
        return None
    preferred = [device for device in devices if _is_loopback_like(device.name)]
    return (preferred or devices)[0]


def system_audio_capture_devices() -> tuple[AudioCaptureDevice, ...]:
    sd = _sounddevice_module()
    if sd is None:
        return ()
    try:
        hostapis = sd.query_hostapis()
        raw_devices = sd.query_devices()
    except Exception:  # noqa: BLE001 - device backends can fail while probing.
        return ()

    devices: list[AudioCaptureDevice] = []
    for index, raw_device in enumerate(raw_devices):
        raw = dict(raw_device)
        try:
            max_inputs = int(raw["max_input_channels"])
        except Exception:  # noqa: BLE001
            continue
        if max_inputs <= 0:
            continue
        try:
            host_api = str(hostapis[int(raw["hostapi"])]["name"])
        except Exception:  # noqa: BLE001
            host_api = ""
        devices.append(
            AudioCaptureDevice(
                index=int(raw.get("index", index)),
                name=str(raw.get("name") or f"Input {index}"),
                host_api=host_api,
                max_input_channels=max_inputs,
                default_sample_rate=int(float(raw.get("default_samplerate") or 48000)),
            )
        )

    def priority(device: AudioCaptureDevice) -> tuple[int, int, str]:
        name = device.name.lower()
        if _is_loopback_like(name):
            first = 0
        elif "wasapi" in device.host_api.lower():
            first = 1
        else:
            first = 2
        host_priority = {"windows wasapi": 0, "mme": 1, "windows directsound": 2}.get(device.host_api.lower(), 5)
        return first, host_priority, device.name.lower()

    return tuple(sorted(devices, key=priority))


def capture_system_audio(
    seconds: float,
    device: AudioCaptureDevice | None = None,
    *,
    started_callback: Callable[[], None] | None = None,
) -> tuple[object, int, AudioCaptureDevice]:
    sd = _sounddevice_module()
    if sd is None or np is None:
        raise YouTubeSyncError("Automatic sync requires sounddevice and NumPy.")
    device = device or best_system_audio_capture_device()
    if device is None:
        raise YouTubeSyncError("No system-audio input was found. Enable a loopback or stereo-mix input and try again.")

    sample_rate = max(8000, int(device.default_sample_rate or 48000))
    channels = max(1, min(2, int(device.max_input_channels)))
    frames = max(1, int(math.ceil(float(seconds) * sample_rate)))
    try:
        recording = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=channels,
            dtype="float32",
            device=device.index,
            blocking=False,
        )
        if started_callback is not None:
            started_callback()
        sd.wait()
    except Exception as exc:  # noqa: BLE001 - show a concise device-specific failure.
        raise YouTubeSyncError(f"Could not capture system audio from {device.display_name}: {exc}") from exc
    return np.asarray(recording, dtype=np.float32).copy(), sample_rate, device


def _sounddevice_module():
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001
        return None
    return sd


def _expected_tab_onsets_with_weights(
    song: SongData,
    start_tick: int,
    play_seconds: float,
    speed_percent: int,
    *,
    pre_roll_seconds: float,
) -> tuple[_TabOnset, ...]:
    end_tick = int(start_tick) + ticks_for_song_seconds(song, play_seconds, speed_percent)
    seconds_per_tick = song_seconds_for_ticks(song, 1, speed_percent)
    by_tick: dict[int, float] = {}
    for measure in song.track.measures:
        measure_start = measure.start_tick
        measure_end = measure.start_tick + measure.length_ticks
        if measure_end < start_tick:
            continue
        if measure_start > end_tick:
            break
        for beat in measure.beats:
            if not beat.notes:
                continue
            tick = measure.start_tick + beat.start_in_measure
            if start_tick <= tick <= end_tick:
                by_tick[tick] = by_tick.get(tick, 0.0) + math.sqrt(len(beat.notes))
    return tuple(
        _TabOnset(pre_roll_seconds + ((tick - int(start_tick)) * seconds_per_tick), weight)
        for tick, weight in sorted(by_tick.items())
    )


def _mono_samples(samples: object):
    if np is None:
        raise YouTubeSyncError("NumPy is required for automatic sync analysis.")
    values = np.asarray(samples, dtype=np.float32)
    if values.size == 0:
        return np.zeros(0, dtype=np.float32)
    if values.ndim == 1:
        mono = values
    elif values.shape[0] <= 8 and values.shape[1] > values.shape[0]:
        mono = np.mean(values, axis=0)
    else:
        mono = np.mean(values, axis=1)
    mono = np.nan_to_num(mono, copy=False)
    return np.asarray(mono, dtype=np.float32)


def _audio_onset_envelope(samples: object, sample_rate: int, *, hop_seconds: float):
    mono = _mono_samples(samples)
    if mono.size < 512 or sample_rate <= 0:
        return np.zeros(0, dtype=np.float32)
    mono = mono - float(np.mean(mono))
    hop = max(1, int(round(sample_rate * hop_seconds)))
    frame = max(hop * 2, int(round(sample_rate * 0.046)))
    if mono.size < frame:
        return np.zeros(0, dtype=np.float32)
    energies: list[float] = []
    for start in range(0, mono.size - frame + 1, hop):
        chunk = mono[start : start + frame]
        energies.append(float(np.sqrt(np.mean(np.square(chunk)))))
    rms = np.asarray(energies, dtype=np.float32)
    if rms.size < 2:
        return rms
    baseline = _moving_average(rms, 17)
    novelty = np.maximum(0.0, rms - baseline)
    diff = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    envelope = (novelty * 0.65) + (diff * 0.35)
    return _moving_average(envelope, 5)


def _tab_onset_envelope(onsets: tuple[_TabOnset, ...], frame_count: int, hop_seconds: float):
    envelope = np.zeros(frame_count, dtype=np.float32)
    for onset in onsets:
        index = int(round(onset.seconds / hop_seconds))
        if 0 <= index < frame_count:
            envelope[index] += float(onset.weight)
    if not np.any(envelope > 0):
        return envelope
    kernel = np.asarray([0.18, 0.42, 0.75, 1.0, 0.75, 0.42, 0.18], dtype=np.float32)
    return np.convolve(envelope, kernel, mode="same")


def _normalize_envelope(envelope):
    values = np.asarray(envelope, dtype=np.float32)
    if values.size == 0:
        return values
    values = values - float(np.mean(values))
    std = float(np.std(values))
    if std <= 1e-8:
        return np.zeros_like(values)
    return values / std


def _moving_average(values, width: int):
    width = max(1, int(width))
    if width <= 1 or values.size < width:
        return np.asarray(values, dtype=np.float32)
    kernel = np.ones(width, dtype=np.float32) / float(width)
    return np.convolve(values, kernel, mode="same").astype(np.float32)


def _is_loopback_like(name: str) -> bool:
    lower = str(name or "").lower()
    return any(token in lower for token in ("loopback", "stereo mix", "what u hear", "스테레오 믹스"))


def estimate_with_device_name(estimate: SyncEstimate, device_name: str) -> SyncEstimate:
    return replace(estimate, capture_device_name=device_name)
