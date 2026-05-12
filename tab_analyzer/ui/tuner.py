"""Realtime chromatic and polyphonic guitar tuner widgets."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys
import time
from typing import Iterable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

try:  # QtMultimedia may be missing on trimmed Python installations.
    from PyQt6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
except Exception:  # noqa: BLE001 - the dialog reports this to the user.
    QAudioFormat = None
    QAudioSource = None
    QMediaDevices = None

try:  # NumPy keeps realtime analysis responsive; pure Python fallbacks remain below.
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

from ..i18n import tr
from ..tunings import TuningPreset, load_tuning_presets


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
STANDARD_GUITAR_STRINGS = (
    ("E2", 40),
    ("A2", 45),
    ("D3", 50),
    ("G3", 55),
    ("B3", 59),
    ("E4", 64),
)


@dataclass(frozen=True)
class PitchReading:
    frequency: float
    note_name: str
    midi_number: int
    cents: float
    clarity: float
    level: float


@dataclass(frozen=True)
class StringReading:
    name: str
    target_frequency: float
    cents: float | None
    level: float
    active: bool
    held: bool = False


@dataclass(frozen=True)
class _PolyCandidate:
    name: str
    target_frequency: float
    cents: float | None
    peak_frequency: float | None
    peak_power: float
    normalized_power: float
    prominence: float
    active: bool


POLY_DISPLAY_HOLD_SECONDS = 1.45
POLY_DISPLAY_SMOOTHING = 0.32
POLY_DISPLAY_FAST_SMOOTHING = 0.62
POLY_DISPLAY_FAST_JUMP_CENTS = 18.0
POLY_FUNDAMENTAL_SCAN_CENTS = 80.0
POLY_MIN_NORMALIZED_POWER = 0.010
POLY_MIN_PROMINENCE = 4.5
POLY_HARMONIC_SUPPRESSION_CENTS = 18.0
POLY_HARMONIC_POWER_RATIO = 0.28


def midi_to_frequency(midi_number: float, reference_a4: float = 440.0) -> float:
    return float(reference_a4) * (2.0 ** ((float(midi_number) - 69.0) / 12.0))


def frequency_to_midi(frequency: float, reference_a4: float = 440.0) -> float:
    if frequency <= 0:
        raise ValueError("frequency must be positive")
    return 69.0 + (12.0 * math.log2(float(frequency) / float(reference_a4)))


def note_name_for_midi(midi_number: int) -> str:
    return f"{NOTE_NAMES[midi_number % 12]}{(midi_number // 12) - 1}"


def pitch_reading_from_frequency(frequency: float, reference_a4: float = 440.0, *, clarity: float = 1.0, level: float = 0.0) -> PitchReading:
    midi_float = frequency_to_midi(frequency, reference_a4)
    midi_number = int(round(midi_float))
    target = midi_to_frequency(midi_number, reference_a4)
    cents = 1200.0 * math.log2(float(frequency) / target)
    return PitchReading(frequency, note_name_for_midi(midi_number), midi_number, cents, max(0.0, min(1.0, clarity)), max(0.0, level))


def string_reading_from_pitch(
    reading: PitchReading,
    targets: Iterable[tuple[str, int]],
    reference_a4: float = 440.0,
    selected_target: tuple[str, int] | None = None,
) -> StringReading | None:
    target_strings = tuple(targets)
    if selected_target is None:
        if not target_strings:
            return None
        selected_target = min(
            target_strings,
            key=lambda item: abs(math.log2(reading.frequency / midi_to_frequency(item[1], reference_a4))),
        )
    name, midi_number = selected_target
    target_frequency = midi_to_frequency(midi_number, reference_a4)
    cents = 1200.0 * math.log2(reading.frequency / target_frequency)
    return StringReading(name, target_frequency, cents, reading.level, True)


def estimate_single_string_reading(
    samples: Iterable[float],
    sample_rate: int,
    reference_a4: float = 440.0,
    *,
    targets: Iterable[tuple[str, int]] = STANDARD_GUITAR_STRINGS,
    selected_target: tuple[str, int] | None = None,
) -> StringReading | None:
    target_strings = tuple(targets)
    if not target_strings:
        return None
    readings = estimate_polyphonic_strings(samples, sample_rate, reference_a4, target_strings)
    if selected_target is not None:
        for target, reading in zip(target_strings, readings):
            if target == selected_target:
                return reading if reading.active and reading.cents is not None else None
        return None

    active_readings = tuple(reading for reading in readings if reading.active and reading.cents is not None)
    if not active_readings:
        return None
    return max(active_readings, key=lambda reading: (reading.level, -abs(reading.cents or 0.0)))


def estimate_monophonic_pitch(
    samples: Iterable[float],
    sample_rate: int,
    reference_a4: float = 440.0,
    *,
    min_frequency: float = 55.0,
    max_frequency: float = 1200.0,
) -> PitchReading | None:
    if np is not None:
        return _estimate_monophonic_pitch_numpy(samples, sample_rate, reference_a4, min_frequency, max_frequency)
    window = _prepare_window(samples)
    count = len(window)
    if count < 1024 or sample_rate <= 0:
        return None
    level = _rms(window)
    if level < 0.006:
        return None

    tau_min = max(2, int(sample_rate / max_frequency))
    tau_max = min(count - 2, int(sample_rate / min_frequency))
    if tau_max <= tau_min:
        return None

    differences = [0.0] * (tau_max + 1)
    for tau in range(1, tau_max + 1):
        total = 0.0
        limit = count - tau
        for index in range(limit):
            delta = window[index] - window[index + tau]
            total += delta * delta
        differences[tau] = total

    normalized = [1.0] * (tau_max + 1)
    running = 0.0
    best_tau = 0
    best_value = 1.0
    for tau in range(1, tau_max + 1):
        running += differences[tau]
        if tau < tau_min or running <= 0:
            continue
        value = differences[tau] * tau / running
        normalized[tau] = value
        if value < best_value:
            best_value = value
            best_tau = tau

    threshold = 0.14
    selected_tau = 0
    for tau in range(tau_min, tau_max):
        if normalized[tau] < threshold and normalized[tau] <= normalized[tau + 1]:
            selected_tau = tau
            break
    if selected_tau == 0:
        if best_tau == 0 or best_value > 0.28:
            return None
        selected_tau = best_tau

    refined_tau = _parabolic_refined_index(normalized, selected_tau)
    if refined_tau <= 0:
        return None
    frequency = sample_rate / refined_tau
    if frequency < min_frequency or frequency > max_frequency:
        return None
    clarity = 1.0 - min(1.0, normalized[selected_tau])
    return pitch_reading_from_frequency(frequency, reference_a4, clarity=clarity, level=level)


def estimate_polyphonic_strings(
    samples: Iterable[float],
    sample_rate: int,
    reference_a4: float = 440.0,
    targets: Iterable[tuple[str, int]] = STANDARD_GUITAR_STRINGS,
) -> tuple[StringReading, ...]:
    target_strings = tuple(targets)
    if np is not None:
        return _estimate_polyphonic_strings_numpy(samples, sample_rate, reference_a4, target_strings)
    window = _prepare_window(samples)
    level = _rms(window)
    if len(window) < 1024 or sample_rate <= 0 or level < 0.004:
        return tuple(
            StringReading(name, midi_to_frequency(midi_number, reference_a4), None, 0.0, False)
            for name, midi_number in target_strings
        )

    readings: list[StringReading] = []
    for name, midi_number in target_strings:
        target_frequency = midi_to_frequency(midi_number, reference_a4)
        best_cents = 0.0
        best_power = 0.0
        for cents in range(-60, 61, 3):
            candidate_frequency = target_frequency * (2.0 ** (cents / 1200.0))
            power = 0.0
            for harmonic, weight in ((1, 1.0), (2, 0.55), (3, 0.35), (4, 0.22)):
                harmonic_frequency = candidate_frequency * harmonic
                if harmonic_frequency < sample_rate * 0.45:
                    power += _goertzel_power(window, sample_rate, harmonic_frequency) * weight
            if power > best_power:
                best_power = power
                best_cents = float(cents)

        normalized_power = best_power / max(level * level, 1e-9)
        active = best_power > 0.000015 and normalized_power > 0.010
        if active:
            best_cents = _refine_polyphonic_cents(window, sample_rate, target_frequency, best_cents)
        readings.append(StringReading(name, target_frequency, best_cents if active else None, normalized_power, active))
    return tuple(readings)


def smooth_polyphonic_readings(
    readings: Iterable[StringReading],
    previous: dict[str, tuple[StringReading, float]],
    now: float,
    *,
    hold_seconds: float = POLY_DISPLAY_HOLD_SECONDS,
    smoothing: float = POLY_DISPLAY_SMOOTHING,
    fast_smoothing: float = POLY_DISPLAY_FAST_SMOOTHING,
    fast_jump_cents: float = POLY_DISPLAY_FAST_JUMP_CENTS,
) -> tuple[tuple[StringReading, ...], dict[str, tuple[StringReading, float]]]:
    displayed: list[StringReading] = []
    updated: dict[str, tuple[StringReading, float]] = {}
    for reading in readings:
        previous_item = previous.get(reading.name)
        previous_reading = previous_item[0] if previous_item is not None else None
        previous_seen = previous_item[1] if previous_item is not None else None
        if reading.active and reading.cents is not None:
            cents = reading.cents
            if previous_reading is not None and previous_reading.cents is not None:
                delta = cents - previous_reading.cents
                alpha = fast_smoothing if abs(delta) >= fast_jump_cents else smoothing
                cents = previous_reading.cents + (delta * alpha)
            smoothed = StringReading(reading.name, reading.target_frequency, cents, reading.level, True)
            displayed.append(smoothed)
            updated[reading.name] = (smoothed, now)
            continue

        if previous_reading is not None and previous_reading.cents is not None and previous_seen is not None:
            if now - previous_seen <= hold_seconds:
                held = StringReading(
                    reading.name,
                    reading.target_frequency,
                    previous_reading.cents,
                    previous_reading.level,
                    False,
                    True,
                )
                displayed.append(held)
                updated[reading.name] = (previous_reading, previous_seen)
                continue

        displayed.append(StringReading(reading.name, reading.target_frequency, None, 0.0, False))
    return tuple(displayed), updated


def _estimate_monophonic_pitch_numpy(
    samples: Iterable[float],
    sample_rate: int,
    reference_a4: float,
    min_frequency: float,
    max_frequency: float,
) -> PitchReading | None:
    values = np.asarray(list(samples), dtype=np.float64)
    count = int(values.size)
    if count < 1024 or sample_rate <= 0:
        return None
    values = values - float(np.mean(values))
    if count > 1:
        values = values * np.hanning(count)
    level = float(np.sqrt(np.mean(values * values)))
    if level < 0.006:
        return None

    tau_min = max(2, int(sample_rate / max_frequency))
    tau_max = min(count - 2, int(sample_rate / min_frequency))
    if tau_max <= tau_min:
        return None

    fft_size = 1 << ((count * 2 - 1).bit_length())
    spectrum = np.fft.rfft(values, fft_size)
    autocorrelation = np.fft.irfft(spectrum * np.conjugate(spectrum), fft_size)[: tau_max + 1]
    squared = values * values
    cumulative_squared = np.concatenate(([0.0], np.cumsum(squared)))

    taus = np.arange(1, tau_max + 1, dtype=np.int64)
    differences = (
        cumulative_squared[count - taus]
        + (cumulative_squared[count] - cumulative_squared[taus])
        - (2.0 * autocorrelation[taus])
    )
    differences = np.maximum(differences, 0.0)
    running = np.cumsum(differences)
    normalized = np.ones(tau_max + 1, dtype=np.float64)
    valid = running > 0
    normalized_values = np.ones_like(differences)
    normalized_values[valid] = differences[valid] * taus[valid] / running[valid]
    normalized[1:] = normalized_values

    search = normalized[tau_min : tau_max + 1]
    if search.size == 0:
        return None
    best_relative = int(np.argmin(search))
    best_tau = tau_min + best_relative
    best_value = float(normalized[best_tau])

    threshold = 0.14
    selected_tau = 0
    for tau in range(tau_min, tau_max):
        if normalized[tau] < threshold and normalized[tau] <= normalized[tau + 1]:
            selected_tau = tau
            break
    if selected_tau == 0:
        if best_value > 0.28:
            return None
        selected_tau = best_tau

    refined_tau = _parabolic_refined_index(normalized.tolist(), selected_tau)
    if refined_tau <= 0:
        return None
    frequency = sample_rate / refined_tau
    if frequency < min_frequency or frequency > max_frequency:
        return None
    clarity = 1.0 - min(1.0, float(normalized[selected_tau]))
    return pitch_reading_from_frequency(frequency, reference_a4, clarity=clarity, level=level)


def _estimate_polyphonic_strings_numpy(
    samples: Iterable[float],
    sample_rate: int,
    reference_a4: float,
    target_strings: tuple[tuple[str, int], ...],
) -> tuple[StringReading, ...]:
    values = np.asarray(list(samples), dtype=np.float64)
    count = int(values.size)
    if count < 1024 or sample_rate <= 0:
        return tuple(
            StringReading(name, midi_to_frequency(midi_number, reference_a4), None, 0.0, False)
            for name, midi_number in target_strings
        )
    values = values - float(np.mean(values))
    if count > 1:
        values = values * np.hanning(count)
    level = float(np.sqrt(np.mean(values * values)))
    if level < 0.004:
        return tuple(
            StringReading(name, midi_to_frequency(midi_number, reference_a4), None, 0.0, False)
            for name, midi_number in target_strings
        )

    fft_size = max(65536, 1 << ((count * 8 - 1).bit_length()))
    spectrum = np.fft.rfft(values, fft_size)
    powers = (np.abs(spectrum) ** 2) / max(1, count * count)
    frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)

    candidates: list[_PolyCandidate] = []
    for name, midi_number in target_strings:
        target_frequency = midi_to_frequency(midi_number, reference_a4)
        peak = _filtered_fft_peak(
            frequencies,
            powers,
            target_frequency,
            scan_cents=POLY_FUNDAMENTAL_SCAN_CENTS,
        )
        if peak is None:
            candidates.append(_PolyCandidate(name, target_frequency, None, None, 0.0, 0.0, 0.0, False))
            continue
        peak_frequency, peak_power, prominence = peak
        if peak_frequency <= 0.0 or not math.isfinite(peak_frequency):
            candidates.append(_PolyCandidate(name, target_frequency, None, None, peak_power, 0.0, prominence, False))
            continue
        cents = 1200.0 * math.log2(peak_frequency / target_frequency)
        normalized_power = peak_power / max(level * level, 1e-9)
        active = (
            abs(cents) <= POLY_FUNDAMENTAL_SCAN_CENTS
            and normalized_power >= POLY_MIN_NORMALIZED_POWER
            and prominence >= POLY_MIN_PROMINENCE
        )
        candidates.append(
            _PolyCandidate(
                name,
                target_frequency,
                cents if active else None,
                peak_frequency,
                peak_power,
                normalized_power,
                prominence,
                active,
            )
        )

    candidates = _suppress_lower_string_harmonic_candidates(candidates)
    return tuple(
        StringReading(candidate.name, candidate.target_frequency, candidate.cents, candidate.normalized_power, candidate.active)
        for candidate in candidates
    )


def _filtered_fft_peak(
    frequencies,
    powers,
    target_frequency: float,
    *,
    scan_cents: float,
) -> tuple[float, float, float] | None:
    low = target_frequency * (2.0 ** (-scan_cents / 1200.0))
    high = target_frequency * (2.0 ** (scan_cents / 1200.0))
    indexes = np.flatnonzero((frequencies >= low) & (frequencies <= high))
    if indexes.size == 0:
        return None
    peak_index = int(indexes[int(np.argmax(powers[indexes]))])
    peak_frequency = _refine_fft_peak_frequency(frequencies, powers, peak_index)
    if peak_frequency <= 0.0 or not math.isfinite(peak_frequency):
        peak_frequency = float(frequencies[peak_index])
    if peak_frequency <= 0.0 or not math.isfinite(peak_frequency):
        return None
    peak_power = float(powers[peak_index])

    wide_low = target_frequency * (2.0 ** (-500.0 / 1200.0))
    wide_high = target_frequency * (2.0 ** (500.0 / 1200.0))
    noise_indexes = np.flatnonzero(
        (frequencies >= wide_low)
        & (frequencies <= wide_high)
        & ((frequencies < low) | (frequencies > high))
    )
    if noise_indexes.size == 0:
        noise_indexes = indexes
    noise_floor = float(np.median(powers[noise_indexes])) if noise_indexes.size else 0.0
    prominence = peak_power / max(noise_floor, 1e-15)
    return peak_frequency, peak_power, prominence


def _refine_fft_peak_frequency(frequencies, powers, index: int) -> float:
    if index <= 0 or index >= len(powers) - 1:
        return float(frequencies[index])
    left = math.log(max(float(powers[index - 1]), 1e-30))
    center = math.log(max(float(powers[index]), 1e-30))
    right = math.log(max(float(powers[index + 1]), 1e-30))
    denominator = left - (2.0 * center) + right
    if abs(denominator) < 1e-12:
        return float(frequencies[index])
    offset = 0.5 * (left - right) / denominator
    if not math.isfinite(offset) or abs(offset) > 1.0:
        return float(frequencies[index])
    offset = max(-0.5, min(0.5, offset))
    bin_width = float(frequencies[1] - frequencies[0]) if len(frequencies) > 1 else 0.0
    return float(frequencies[index]) + (offset * bin_width)


def _suppress_lower_string_harmonic_candidates(candidates: list[_PolyCandidate]) -> list[_PolyCandidate]:
    updated = list(candidates)
    for index, candidate in enumerate(candidates):
        if not candidate.active or candidate.peak_frequency is None:
            continue
        suppress = False
        for lower in candidates[:index]:
            if not lower.active or lower.peak_frequency is None or lower.peak_power <= 0:
                continue
            ratio = candidate.peak_frequency / lower.peak_frequency
            harmonic = round(ratio)
            if harmonic < 2 or harmonic > 6:
                continue
            harmonic_cents = 1200.0 * math.log2(ratio / harmonic)
            if abs(harmonic_cents) > POLY_HARMONIC_SUPPRESSION_CENTS:
                continue
            power_ratio = candidate.peak_power / lower.peak_power
            if power_ratio < POLY_HARMONIC_POWER_RATIO:
                suppress = True
                break
        if suppress:
            updated[index] = _PolyCandidate(
                candidate.name,
                candidate.target_frequency,
                None,
                candidate.peak_frequency,
                candidate.peak_power,
                candidate.normalized_power,
                candidate.prominence,
                False,
            )
    return updated


def _prepare_window(samples: Iterable[float]) -> list[float]:
    values = [float(sample) for sample in samples]
    count = len(values)
    if count == 0:
        return []
    mean = sum(values) / count
    if count == 1:
        return [values[0] - mean]
    return [
        (sample - mean) * (0.5 - (0.5 * math.cos((2.0 * math.pi * index) / (count - 1))))
        for index, sample in enumerate(values)
    ]


def _rms(samples: Iterable[float]) -> float:
    values = list(samples)
    if not values:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in values) / len(values))


def _parabolic_refined_index(values: list[float], index: int) -> float:
    if index <= 0 or index >= len(values) - 1:
        return float(index)
    left = values[index - 1]
    center = values[index]
    right = values[index + 1]
    denominator = left - (2.0 * center) + right
    if abs(denominator) < 1e-12:
        return float(index)
    return float(index) + (0.5 * (left - right) / denominator)


def _goertzel_power(samples: list[float], sample_rate: int, frequency: float) -> float:
    omega = (2.0 * math.pi * frequency) / sample_rate
    coefficient = 2.0 * math.cos(omega)
    previous = 0.0
    previous2 = 0.0
    for sample in samples:
        current = sample + (coefficient * previous) - previous2
        previous2 = previous
        previous = current
    power = (previous2 * previous2) + (previous * previous) - (coefficient * previous * previous2)
    return max(0.0, power / max(1, len(samples) * len(samples)))


def _refine_polyphonic_cents(samples: list[float], sample_rate: int, target_frequency: float, center_cents: float) -> float:
    best_cents = center_cents
    best_power = -1.0
    start = int(round(center_cents - 3.0))
    end = int(round(center_cents + 3.0))
    for cents in range(start, end + 1):
        candidate_frequency = target_frequency * (2.0 ** (cents / 1200.0))
        power = 0.0
        for harmonic, weight in ((1, 1.0), (2, 0.55), (3, 0.35), (4, 0.22)):
            harmonic_frequency = candidate_frequency * harmonic
            if harmonic_frequency < sample_rate * 0.45:
                power += _goertzel_power(samples, sample_rate, harmonic_frequency) * weight
        if power > best_power:
            best_power = power
            best_cents = float(cents)
    return best_cents


def _decode_audio_samples(raw: bytes, audio_format) -> list[float]:
    if not raw or audio_format is None or QAudioFormat is None:
        return []
    channel_count = max(1, int(audio_format.channelCount()))
    sample_format = audio_format.sampleFormat()
    if sample_format == QAudioFormat.SampleFormat.Int16:
        values = array("h")
        values.frombytes(raw[: len(raw) - (len(raw) % 2)])
        if sys.byteorder != "little":
            values.byteswap()
        return _collapse_channels(values, channel_count, 32768.0)
    if sample_format == QAudioFormat.SampleFormat.Int32:
        values = array("i")
        values.frombytes(raw[: len(raw) - (len(raw) % 4)])
        if sys.byteorder != "little":
            values.byteswap()
        return _collapse_channels(values, channel_count, 2147483648.0)
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        return _collapse_channels((value - 128 for value in raw), channel_count, 128.0)
    if sample_format == QAudioFormat.SampleFormat.Float:
        values = array("f")
        values.frombytes(raw[: len(raw) - (len(raw) % 4)])
        if sys.byteorder != "little":
            values.byteswap()
        return _collapse_channels(values, channel_count, 1.0)
    return []


def _collapse_channels(values: Iterable[float], channel_count: int, scale: float) -> list[float]:
    normalized = [float(value) / scale for value in values]
    if channel_count <= 1:
        return normalized
    frames: list[float] = []
    usable_count = len(normalized) - (len(normalized) % channel_count)
    for index in range(0, usable_count, channel_count):
        frames.append(sum(normalized[index : index + channel_count]) / channel_count)
    return frames


def _format_cents(cents: float | None) -> str:
    if cents is None:
        return "--"
    return f"{cents:+.1f}"


def _intonation_label(cents: float | None) -> str:
    if cents is None:
        return tr("Quiet")
    if abs(cents) <= 3.0:
        return tr("In tune")
    return tr("Flat") if cents < 0 else tr("Sharp")


class TunerMeterWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cents: float | None = None
        self.setMinimumHeight(46)

    def set_cents(self, cents: float | None) -> None:
        self.cents = None if cents is None else max(-50.0, min(50.0, float(cents)))
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        center_x = rect.center().x()
        center_y = rect.center().y()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f5f7fb"))
        painter.drawRoundedRect(rect, 6, 6)

        tuned_width = max(4, int(rect.width() * 0.06))
        painter.setBrush(QColor("#dff6e7"))
        painter.drawRoundedRect(center_x - tuned_width // 2, rect.top() + 4, tuned_width, rect.height() - 8, 4, 4)

        painter.setPen(QPen(QColor("#ccd3df"), 1))
        for cents in range(-50, 51, 10):
            x = self._x_for_cents(rect, float(cents))
            height = 14 if cents % 20 == 0 else 9
            painter.drawLine(x, center_y - height // 2, x, center_y + height // 2)

        painter.setPen(QPen(QColor("#16a34a"), 2))
        painter.drawLine(center_x, rect.top() + 5, center_x, rect.bottom() - 5)

        if self.cents is not None:
            needle_color = QColor("#16a34a") if abs(self.cents) <= 3.0 else QColor("#dc2626")
            x = self._x_for_cents(rect, self.cents)
            painter.setPen(QPen(needle_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(x, rect.top() + 4, x, rect.bottom() - 4)

    def _x_for_cents(self, rect, cents: float) -> int:
        ratio = (max(-50.0, min(50.0, cents)) + 50.0) / 100.0
        return int(rect.left() + (ratio * rect.width()))


class StringTunerRow(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name_label = QLabel(name)
        self.name_label.setMinimumWidth(38)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_label = QLabel()
        self.target_label.setMinimumWidth(84)
        self.meter = TunerMeterWidget()
        self.meter.setMinimumHeight(34)
        self.cents_label = QLabel("--")
        self.cents_label.setMinimumWidth(64)
        self.status_label = QLabel(tr("Quiet"))
        self.status_label.setMinimumWidth(78)

        font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        self.name_label.setFont(font)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)
        layout.addWidget(self.name_label)
        layout.addWidget(self.target_label)
        layout.addWidget(self.meter, 1)
        layout.addWidget(self.cents_label)
        layout.addWidget(self.status_label)

    def set_reading(self, reading: StringReading) -> None:
        self.target_label.setText(f"{reading.target_frequency:.1f} Hz")
        self.meter.set_cents(reading.cents)
        self.cents_label.setText(_format_cents(reading.cents))
        self.status_label.setText(tr("Last signal") if reading.held else _intonation_label(reading.cents))


class ChromaticTunerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Chromatic tuner"))
        self.resize(720, 560)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self.tuning_presets = load_tuning_presets()
        self.device_combo = QComboBox()
        self.refresh_button = QPushButton(tr("Refresh"))
        self.start_button = QPushButton(tr("Start"))
        self.single_radio = QRadioButton(tr("Single string"))
        self.poly_radio = QRadioButton(tr("All strings"))
        self.single_radio.setChecked(True)
        self.reference_spin = QDoubleSpinBox()
        self.reference_spin.setRange(430.0, 450.0)
        self.reference_spin.setDecimals(1)
        self.reference_spin.setSingleStep(0.1)
        self.reference_spin.setValue(440.0)

        self.note_label = QLabel("--")
        self.note_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note_label.setFont(QFont("Segoe UI", 54, QFont.Weight.Bold))
        self.frequency_label = QLabel("-- Hz")
        self.frequency_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cents_label = QLabel("--")
        self.cents_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label = QLabel(tr("Ready"))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #596579;")
        self.single_meter = TunerMeterWidget()
        self.single_meter.setMinimumHeight(72)

        self.tuning_label = QLabel(tr("Tuning"))
        self.tuning_combo = QComboBox()
        self.tuning_combo.setMinimumWidth(260)
        self._populate_tuning_combo()
        self.single_target_label = QLabel(tr("Target string"))
        self.single_target_combo = QComboBox()
        self.single_target_combo.setMinimumWidth(190)
        self._populate_single_target_combo()
        self.poly_container = QWidget()
        self.string_rows: list[StringTunerRow] = []
        self.poly_layout = QVBoxLayout(self.poly_container)
        self.poly_layout.setContentsMargins(0, 0, 0, 0)
        self.poly_layout.setSpacing(2)
        self._rebuild_string_rows()

        controls = QHBoxLayout()
        controls.addWidget(QLabel(tr("Input device")))
        controls.addWidget(self.device_combo, 1)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.start_button)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel(tr("Tuning mode")))
        mode_layout.addWidget(self.single_radio)
        mode_layout.addWidget(self.poly_radio)
        mode_layout.addStretch(1)
        mode_layout.addWidget(QLabel(tr("Reference A4")))
        mode_layout.addWidget(self.reference_spin)

        poly_tuning_layout = QHBoxLayout()
        poly_tuning_layout.addWidget(self.tuning_label)
        poly_tuning_layout.addWidget(self.tuning_combo, 1)
        poly_tuning_layout.addWidget(self.single_target_label)
        poly_tuning_layout.addWidget(self.single_target_combo, 0)

        single_layout = QVBoxLayout()
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(4)
        single_layout.addWidget(self.note_label)
        single_layout.addWidget(self.frequency_label)
        single_layout.addWidget(self.single_meter)
        single_layout.addWidget(self.cents_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(controls)
        layout.addLayout(mode_layout)
        layout.addLayout(poly_tuning_layout)
        layout.addLayout(single_layout)
        layout.addWidget(self.poly_container)
        layout.addWidget(self.status_label)

        self._audio_source = None
        self._audio_device = None
        self._audio_format = None
        self._audio_io = None
        self._samples: list[float] = []
        self._max_samples = 48000
        self._analysis_size = 8192
        self._running = False
        self._poly_display_state: dict[str, tuple[StringReading, float]] = {}

        self._analysis_timer = QTimer(self)
        self._analysis_timer.setInterval(180)
        self._analysis_timer.timeout.connect(self._analyze)

        self.refresh_button.clicked.connect(self._refresh_devices)
        self.start_button.clicked.connect(self._toggle_audio)
        self.single_radio.toggled.connect(self._sync_mode_visibility)
        self.poly_radio.toggled.connect(self._sync_mode_visibility)
        self.device_combo.currentIndexChanged.connect(self._restart_if_running)
        self.reference_spin.valueChanged.connect(self._on_reference_changed)
        self.tuning_combo.currentIndexChanged.connect(self._on_tuning_changed)
        self.single_target_combo.currentIndexChanged.connect(lambda _index: self._analyze())

        self._refresh_devices()
        self._sync_mode_visibility()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_audio()
        super().closeEvent(event)

    def _refresh_devices(self) -> None:
        self.device_combo.clear()
        if QMediaDevices is None or QAudioSource is None or QAudioFormat is None:
            self.device_combo.addItem(tr("Audio input unavailable"), None)
            self.device_combo.setEnabled(False)
            self.start_button.setEnabled(False)
            self.status_label.setText(tr("Audio input unavailable."))
            return
        devices = QMediaDevices.audioInputs()
        if not devices:
            self.device_combo.addItem(tr("No input device"), None)
            self.device_combo.setEnabled(False)
            self.start_button.setEnabled(False)
            self.status_label.setText(tr("No input device"))
            return
        for device in devices:
            self.device_combo.addItem(device.description(), device)
        self.device_combo.setEnabled(True)
        self.start_button.setEnabled(True)
        self.status_label.setText(tr("Ready"))

    def _populate_tuning_combo(self) -> None:
        self.tuning_combo.clear()
        for preset in self.tuning_presets:
            self.tuning_combo.addItem(preset.display_name, preset)

    def _selected_tuning_preset(self) -> TuningPreset | None:
        preset = self.tuning_combo.currentData()
        return preset if isinstance(preset, TuningPreset) else None

    def _poly_targets(self) -> tuple[tuple[str, int], ...]:
        preset = self._selected_tuning_preset()
        if preset is None:
            return STANDARD_GUITAR_STRINGS
        return tuple(zip(preset.notes_low_to_high, preset.midi_low_to_high))

    def _display_targets(self) -> tuple[tuple[str, int], ...]:
        return tuple(reversed(self._poly_targets()))

    def _populate_single_target_combo(self) -> None:
        current = self.single_target_combo.currentData()
        self.single_target_combo.blockSignals(True)
        self.single_target_combo.clear()
        self.single_target_combo.addItem(tr("Auto string"), None)
        for name, midi_number in self._display_targets():
            self.single_target_combo.addItem(f"{name} ({midi_to_frequency(midi_number, self.reference_spin.value()):.1f} Hz)", (name, midi_number))
        if current is not None:
            index = self.single_target_combo.findData(current)
            self.single_target_combo.setCurrentIndex(index if index >= 0 else 0)
        self.single_target_combo.blockSignals(False)

    def _selected_single_target(self) -> tuple[str, int] | None:
        target = self.single_target_combo.currentData()
        if isinstance(target, tuple) and len(target) == 2:
            name, midi_number = target
            if isinstance(name, str) and isinstance(midi_number, int):
                return name, midi_number
        return None

    def _rebuild_string_rows(self) -> None:
        for row in self.string_rows:
            self.poly_layout.removeWidget(row)
            row.deleteLater()
        self.string_rows = [StringTunerRow(name) for name, _midi in self._display_targets()]
        for row in self.string_rows:
            self.poly_layout.addWidget(row)

    def _reset_poly_display_state(self) -> None:
        self._poly_display_state = {}

    def _on_tuning_changed(self, _index: int | None = None) -> None:
        self._reset_poly_display_state()
        self._populate_single_target_combo()
        self._rebuild_string_rows()
        self._set_quiet_poly_readings()
        self._analyze()

    def _on_reference_changed(self, _value: float) -> None:
        self._reset_poly_display_state()
        self._populate_single_target_combo()
        self._analyze()

    def _sync_mode_visibility(self) -> None:
        is_poly = self.poly_radio.isChecked()
        self.single_target_label.setVisible(not is_poly)
        self.single_target_combo.setVisible(not is_poly)
        self.poly_container.setVisible(is_poly)
        self.note_label.setVisible(not is_poly)
        self.frequency_label.setVisible(not is_poly)
        self.cents_label.setVisible(not is_poly)
        self.single_meter.setVisible(not is_poly)
        self._analyze()

    def _set_quiet_poly_readings(self) -> None:
        self._reset_poly_display_state()
        readings = tuple(
            StringReading(name, midi_to_frequency(midi_number, self.reference_spin.value()), None, 0.0, False)
            for name, midi_number in self._display_targets()
        )
        for row, reading in zip(self.string_rows, readings):
            row.set_reading(reading)

    def _toggle_audio(self) -> None:
        if self._running:
            self._stop_audio()
        else:
            self._start_audio()

    def _restart_if_running(self) -> None:
        if not self._running:
            return
        self._stop_audio()
        self._start_audio()

    def _start_audio(self) -> None:
        if QAudioFormat is None or QAudioSource is None:
            self.status_label.setText(tr("Audio input unavailable."))
            return
        device = self.device_combo.currentData()
        if device is None:
            QMessageBox.warning(self, tr("Chromatic tuner"), tr("Select an input device."))
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            audio_format = device.preferredFormat()

        self._samples = []
        self._audio_device = device
        self._audio_format = audio_format
        self._audio_source = QAudioSource(device, audio_format, self)
        self._audio_source.setBufferSize(8192)
        self._audio_io = self._audio_source.start()
        if self._audio_io is None:
            self._audio_source.deleteLater()
            self._audio_source = None
            self.status_label.setText(tr("The selected input device could not be started."))
            return
        self._audio_io.readyRead.connect(self._read_audio)
        self._running = True
        self.start_button.setText(tr("Stop"))
        self.status_label.setText(tr("Listening..."))
        self._analysis_timer.start()

    def _stop_audio(self) -> None:
        self._analysis_timer.stop()
        if self._audio_source is not None:
            self._audio_source.stop()
            self._audio_source.deleteLater()
        self._audio_source = None
        self._audio_io = None
        self._running = False
        self.start_button.setText(tr("Start"))
        self.status_label.setText(tr("Ready"))

    def _read_audio(self) -> None:
        if self._audio_io is None:
            return
        raw = bytes(self._audio_io.readAll())
        decoded = _decode_audio_samples(raw, self._audio_format)
        if not decoded:
            return
        self._samples.extend(decoded)
        if len(self._samples) > self._max_samples:
            self._samples = self._samples[-self._max_samples :]

    def _analyze(self) -> None:
        if len(self._samples) < 2048:
            if self.poly_radio.isChecked():
                self._set_quiet_poly_readings()
            return
        window = self._samples[-self._analysis_size :]
        reference = self.reference_spin.value()
        sample_rate = int(self._audio_format.sampleRate()) if self._audio_format is not None else 48000
        if self.poly_radio.isChecked():
            readings = estimate_polyphonic_strings(
                window,
                sample_rate,
                reference,
                self._poly_targets(),
            )
            readings, self._poly_display_state = smooth_polyphonic_readings(
                readings,
                self._poly_display_state,
                time.monotonic(),
            )
            reading_by_name = {reading.name: reading for reading in readings}
            display_readings = tuple(
                reading_by_name.get(
                    name,
                    StringReading(name, midi_to_frequency(midi_number, reference), None, 0.0, False),
                )
                for name, midi_number in self._display_targets()
            )
            for row, reading in zip(self.string_rows, display_readings):
                row.set_reading(reading)
            active_count = sum(1 for reading in display_readings if reading.active)
            held_count = sum(1 for reading in display_readings if reading.held)
            if active_count:
                self.status_label.setText(tr("Listening..."))
            elif held_count:
                self.status_label.setText(tr("Last signal"))
            else:
                self.status_label.setText(tr("Quiet"))
            return

        target_reading = estimate_single_string_reading(
            window,
            sample_rate,
            reference,
            targets=self._poly_targets(),
            selected_target=self._selected_single_target(),
        )
        if target_reading is None or target_reading.cents is None:
            self.note_label.setText("--")
            self.frequency_label.setText("-- Hz")
            self.cents_label.setText("--")
            self.single_meter.set_cents(None)
            self.status_label.setText(tr("Quiet") if self._running else tr("Ready"))
            return
        detected_frequency = target_reading.target_frequency * (2.0 ** (target_reading.cents / 1200.0))
        self.note_label.setText(target_reading.name)
        self.frequency_label.setText(f"{detected_frequency:.1f} Hz / {target_reading.target_frequency:.1f} Hz")
        self.cents_label.setText(f"{_format_cents(target_reading.cents)} cents - {_intonation_label(target_reading.cents)}")
        self.single_meter.set_cents(target_reading.cents)
        self.status_label.setText(_intonation_label(target_reading.cents))
