"""Realtime VST effect routing dialog."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from threading import Event
from typing import Iterable

os.environ.setdefault("SD_ENABLE_ASIO", "1")

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
)

try:  # QtMultimedia may be unavailable on trimmed Python installations.
    from PyQt6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices
except Exception:  # noqa: BLE001 - the dialog reports this to the user.
    QAudioFormat = None
    QAudioSink = None
    QAudioSource = None
    QMediaDevices = None

try:  # NumPy is already a core dependency, but keep the dialog graceful.
    import numpy as np
except Exception:  # noqa: BLE001
    np = None

from ..i18n import tr


VST3_SUFFIX = ".vst3"
VST2_SUFFIXES = frozenset({".dll", ".vst"})
PLUGIN_SUFFIXES = frozenset({VST3_SUFFIX, *VST2_SUFFIXES})
DEFAULT_SAMPLE_RATES = (48000, 44100)
DEFAULT_CHANNEL_COUNTS = (2, 1)
ROUTE_CHUNK_FRAMES = 512
LOW_LATENCY_BUFFER_FRAMES = (64, 128, 256, 512)


@dataclass(frozen=True)
class AudioDeviceInfo:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: int
    low_input_latency: float
    low_output_latency: float

    @property
    def display_name(self) -> str:
        latency = self.low_input_latency if self.max_input_channels else self.low_output_latency
        latency_text = f"{latency * 1000:.1f} ms" if latency > 0 else "low"
        return f"{self.name} [{self.host_api}, {latency_text}]"

    @property
    def is_asio(self) -> bool:
        return self.host_api.upper() == "ASIO"


@dataclass(frozen=True)
class VstPluginInfo:
    name: str
    path: Path
    plugin_format: str

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.plugin_format})"


def default_vst_search_roots() -> tuple[Path, ...]:
    """Return common platform VST search roots plus user-provided env paths."""

    roots: list[Path] = []
    for key in ("VST3_PATH", "VST2_PATH", "VST_PATH"):
        roots.extend(_split_env_paths(os.environ.get(key, "")))

    if sys.platform.startswith("win"):
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        common_program_files = os.environ.get("CommonProgramFiles", str(Path(program_files) / "Common Files"))
        common_program_files_x86 = os.environ.get("CommonProgramFiles(x86)", str(Path(program_files_x86) / "Common Files"))
        roots.extend(
            Path(path)
            for path in (
                Path(common_program_files) / "VST3",
                Path(common_program_files) / "VST2",
                Path(program_files) / "VSTPlugins",
                Path(program_files) / "Steinberg" / "VSTPlugins",
                Path(common_program_files_x86) / "VST3",
                Path(common_program_files_x86) / "VST2",
                Path(program_files_x86) / "VSTPlugins",
                Path(program_files_x86) / "Steinberg" / "VSTPlugins",
            )
        )
    elif sys.platform == "darwin":
        roots.extend(
            Path(path)
            for path in (
                "/Library/Audio/Plug-Ins/VST3",
                "/Library/Audio/Plug-Ins/VST",
                Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST3",
                Path.home() / "Library" / "Audio" / "Plug-Ins" / "VST",
            )
        )
    else:
        roots.extend(
            Path(path)
            for path in (
                Path.home() / ".vst3",
                Path.home() / ".vst",
                "/usr/lib/vst3",
                "/usr/lib/vst",
                "/usr/local/lib/vst3",
                "/usr/local/lib/vst",
            )
        )

    return _dedupe_paths(roots)


def scan_vst_plugins(roots: Iterable[Path]) -> list[VstPluginInfo]:
    """Find VST2 and VST3 plugin files/bundles below the given roots."""

    plugins: list[VstPluginInfo] = []
    seen: set[str] = set()
    stack = [Path(root) for root in roots if Path(root).exists()]

    while stack:
        current = stack.pop()
        try:
            suffix = current.suffix.lower()
            if current.is_file() and suffix in PLUGIN_SUFFIXES:
                _append_plugin(plugins, seen, current)
                continue
            if current.is_dir() and suffix == VST3_SUFFIX:
                _append_plugin(plugins, seen, current)
                continue
            if not current.is_dir():
                continue
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        path = Path(entry.path)
                        entry_suffix = path.suffix.lower()
                        if entry.is_dir(follow_symlinks=False):
                            if entry_suffix == VST3_SUFFIX:
                                _append_plugin(plugins, seen, path)
                            else:
                                stack.append(path)
                        elif entry.is_file(follow_symlinks=False) and entry_suffix in PLUGIN_SUFFIXES:
                            _append_plugin(plugins, seen, path)
                    except OSError:
                        continue
        except OSError:
            continue

    return sorted(plugins, key=lambda item: (item.name.lower(), item.plugin_format, str(item.path).lower()))


def plugin_info_from_path(path: Path) -> VstPluginInfo | None:
    path = _resolve_vst_load_path(path)
    suffix = path.suffix.lower()
    if suffix not in PLUGIN_SUFFIXES:
        return None
    return VstPluginInfo(path.stem, path, "VST3" if suffix == VST3_SUFFIX else "VST2")


def _resolve_vst_load_path(path: Path) -> Path:
    if not sys.platform.startswith("win") or path.suffix.lower() != VST3_SUFFIX:
        return path
    try:
        if not path.is_dir():
            return path
    except OSError:
        return path
    architecture = "x86_64-win" if sys.maxsize > 2**32 else "x86-win"
    exact_candidate = path / "Contents" / architecture / f"{path.stem}.vst3"
    if exact_candidate.exists():
        return exact_candidate
    for candidate in (path / "Contents").glob("*/*.vst3"):
        if candidate.is_file():
            return candidate
    return path


def _append_plugin(plugins: list[VstPluginInfo], seen: set[str], path: Path) -> None:
    info = plugin_info_from_path(path)
    if info is None:
        return
    key = str(path.resolve(strict=False)).lower()
    if key in seen:
        return
    seen.add(key)
    plugins.append(info)


def _split_env_paths(value: str) -> list[Path]:
    if not value:
        return []
    parts: list[str] = []
    for chunk in value.split(os.pathsep):
        parts.extend(item for item in chunk.split(";") if item)
    return [Path(part.strip().strip('"')) for part in parts if part.strip()]


def _dedupe_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(Path(path))
    return tuple(deduped)


def _format_description(audio_format) -> str:
    if isinstance(audio_format, tuple):
        sample_rate, channel_count, buffer_frames, driver_name = audio_format
        return f"{sample_rate} Hz, {channel_count} ch, {buffer_frames} frames, {driver_name}"
    if audio_format is None:
        return ""
    return f"{int(audio_format.sampleRate())} Hz, {int(audio_format.channelCount())} ch"


def _sounddevice_module():
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001 - UI reports unavailable state.
        return None
    return sd


def _sounddevice_audio_devices(input_side: bool) -> list[AudioDeviceInfo]:
    sd = _sounddevice_module()
    if sd is None:
        return []
    hostapis = sd.query_hostapis()
    devices: list[AudioDeviceInfo] = []
    for device in sd.query_devices():
        max_inputs = int(device["max_input_channels"])
        max_outputs = int(device["max_output_channels"])
        if input_side and max_inputs <= 0:
            continue
        if not input_side and max_outputs <= 0:
            continue
        host_api = str(hostapis[int(device["hostapi"])]["name"])
        devices.append(
            AudioDeviceInfo(
                index=int(device["index"]),
                name=str(device["name"]),
                host_api=host_api,
                max_input_channels=max_inputs,
                max_output_channels=max_outputs,
                default_sample_rate=int(device["default_samplerate"]),
                low_input_latency=float(device["default_low_input_latency"]),
                low_output_latency=float(device["default_low_output_latency"]),
            )
        )
    priority = {"ASIO": 0, "Windows WASAPI": 1, "Windows WDM-KS": 2, "Windows DirectSound": 3, "MME": 4}
    return sorted(devices, key=lambda item: (priority.get(item.host_api, 9), item.name.lower()))


def _sounddevice_route_settings(input_device: AudioDeviceInfo, output_device: AudioDeviceInfo, buffer_frames: int):
    sd = _sounddevice_module()
    if sd is None:
        return None
    channel_count = min(2, input_device.max_input_channels, output_device.max_output_channels)
    if channel_count <= 0:
        return None
    sample_rates = _unique_ints((input_device.default_sample_rate, output_device.default_sample_rate, 48000, 44100))
    for sample_rate in sample_rates:
        try:
            sd.check_input_settings(device=input_device.index, channels=channel_count, samplerate=sample_rate, dtype="float32")
            sd.check_output_settings(device=output_device.index, channels=channel_count, samplerate=sample_rate, dtype="float32")
        except Exception:  # noqa: BLE001 - try the next common sample rate.
            continue
        return sample_rate, channel_count, max(16, int(buffer_frames))
    return None


def _unique_ints(values: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        result.append(int(value))
    return tuple(result)


def _int16_bytes_to_audio(raw: bytes, channel_count: int):
    if np is None or not raw:
        return None
    values = np.frombuffer(raw, dtype="<i2")
    frame_count = values.size // channel_count
    if frame_count <= 0:
        return None
    values = values[: frame_count * channel_count].astype(np.float32) / 32768.0
    return values.reshape(frame_count, channel_count).T.copy()


def _audio_to_int16_bytes(audio, channel_count: int, frame_count: int) -> bytes:
    if np is None:
        return b""
    output = np.asarray(audio, dtype=np.float32)
    if output.ndim == 1:
        output = output.reshape(1, -1)
    if output.shape[0] != channel_count and output.shape[-1] == channel_count:
        output = output.T
    if output.shape[0] < channel_count:
        repeats = channel_count - output.shape[0]
        output = np.vstack([output, np.tile(output[-1:], (repeats, 1))])
    elif output.shape[0] > channel_count:
        output = output[:channel_count]
    if output.shape[1] < frame_count:
        output = np.pad(output, ((0, 0), (0, frame_count - output.shape[1])))
    elif output.shape[1] > frame_count:
        output = output[:, :frame_count]
    interleaved = np.clip(output.T, -1.0, 1.0)
    return (interleaved * 32767.0).astype("<i2").tobytes()


def _audio_to_float_stream(audio, channel_count: int, frame_count: int):
    if np is None:
        return None
    output = np.asarray(audio, dtype=np.float32)
    if output.ndim == 1:
        output = output.reshape(1, -1)
    if output.shape[0] != channel_count and output.shape[-1] == channel_count:
        output = output.T
    if output.shape[0] < channel_count:
        repeats = channel_count - output.shape[0]
        output = np.vstack([output, np.tile(output[-1:], (repeats, 1))])
    elif output.shape[0] > channel_count:
        output = output[:channel_count]
    if output.shape[1] < frame_count:
        output = np.pad(output, ((0, 0), (0, frame_count - output.shape[1])))
    elif output.shape[1] > frame_count:
        output = output[:, :frame_count]
    return np.clip(output.T, -1.0, 1.0)


def _compatible_audio_format(input_device, output_device):
    if QAudioFormat is None:
        return None
    for sample_rate in DEFAULT_SAMPLE_RATES:
        for channel_count in DEFAULT_CHANNEL_COUNTS:
            audio_format = QAudioFormat()
            audio_format.setSampleRate(sample_rate)
            audio_format.setChannelCount(channel_count)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            try:
                if input_device.isFormatSupported(audio_format) and output_device.isFormatSupported(audio_format):
                    return audio_format
            except Exception:  # noqa: BLE001 - device backends can fail while probing.
                continue
    return None


class _VstSearchWorker(QObject):
    finished = pyqtSignal(list, str)

    def __init__(self, roots: tuple[Path, ...]) -> None:
        super().__init__()
        self.roots = roots

    def run(self) -> None:
        try:
            self.finished.emit(scan_vst_plugins(self.roots), "")
        except Exception as exc:  # noqa: BLE001 - scanning should report, not crash.
            self.finished.emit([], str(exc))


class _AudioRouteWorker(QObject):
    started = pyqtSignal()
    stopped = pyqtSignal()
    statusChanged = pyqtSignal(str)

    def __init__(self, input_device, output_device, audio_format, processor) -> None:
        super().__init__()
        self.input_device = input_device
        self.output_device = output_device
        self.audio_format = audio_format
        self.processor = processor
        self.input_source = None
        self.output_sink = None
        self.input_io = None
        self.output_io = None
        self._pending_audio = bytearray()
        self._chunk_bytes = ROUTE_CHUNK_FRAMES * int(audio_format.channelCount()) * 2
        self._running = False

    def start(self) -> None:
        try:
            self.output_sink = QAudioSink(self.output_device, self.audio_format, self)
            self.output_sink.setBufferSize(self._chunk_bytes * 8)
            self.output_io = self.output_sink.start()
            self.input_source = QAudioSource(self.input_device, self.audio_format, self)
            self.input_source.setBufferSize(self._chunk_bytes * 4)
            self.input_io = self.input_source.start()
            if self.input_io is None or self.output_io is None:
                self.stop()
                self.statusChanged.emit(tr("The selected audio devices could not be started."))
                return
            self.input_io.readyRead.connect(self._process_available_audio)
            self._running = True
            self.started.emit()
        except Exception as exc:  # noqa: BLE001
            self.stop()
            self.statusChanged.emit(tr("VST routing failed: {error}").format(error=exc))

    def stop(self) -> None:
        if self.input_source is not None:
            self.input_source.stop()
            self.input_source.deleteLater()
        if self.output_sink is not None:
            self.output_sink.stop()
            self.output_sink.deleteLater()
        self.input_source = None
        self.output_sink = None
        self.input_io = None
        self.output_io = None
        self._pending_audio.clear()
        self._running = False
        self.stopped.emit()

    def _process_available_audio(self) -> None:
        if self.input_io is None or self.output_io is None or self.audio_format is None or self.processor is None:
            return
        raw = bytes(self.input_io.readAll())
        if not raw:
            return
        self._pending_audio.extend(raw)
        while len(self._pending_audio) >= self._chunk_bytes:
            chunk = bytes(self._pending_audio[: self._chunk_bytes])
            del self._pending_audio[: self._chunk_bytes]
            channel_count = int(self.audio_format.channelCount())
            audio = _int16_bytes_to_audio(chunk, channel_count)
            if audio is None:
                continue
            try:
                processed = self.processor.process(audio)
            except Exception as exc:  # noqa: BLE001
                self.stop()
                self.statusChanged.emit(tr("VST processing failed: {error}").format(error=exc))
                return
            output = _audio_to_int16_bytes(processed, channel_count, ROUTE_CHUNK_FRAMES)
            if output:
                self.output_io.write(output)


class _SoundDeviceRoute:
    def __init__(
        self,
        input_device: AudioDeviceInfo,
        output_device: AudioDeviceInfo,
        sample_rate: int,
        channel_count: int,
        buffer_frames: int,
        processor,
    ) -> None:
        sd = _sounddevice_module()
        if sd is None:
            raise RuntimeError(tr("Audio routing unavailable."))
        self.sd = sd
        self.input_device = input_device
        self.output_device = output_device
        self.sample_rate = sample_rate
        self.channel_count = channel_count
        self.buffer_frames = buffer_frames
        self.processor = processor
        self.stream = None
        self.last_status = ""

    @property
    def driver_name(self) -> str:
        if self.input_device.index == self.output_device.index:
            return self.input_device.host_api
        return f"{self.input_device.host_api}/{self.output_device.host_api}"

    def start(self) -> None:
        self.stream = self.sd.Stream(
            device=(self.input_device.index, self.output_device.index),
            samplerate=self.sample_rate,
            blocksize=self.buffer_frames,
            channels=(self.channel_count, self.channel_count),
            dtype="float32",
            latency="low",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _callback(self, indata, outdata, frames, _time, status) -> None:
        if status:
            self.last_status = str(status)
        try:
            audio = np.ascontiguousarray(indata.T, dtype=np.float32)
            processed = self.processor.process(audio, frames)
            output = _audio_to_float_stream(processed, self.channel_count, frames)
            if output is None:
                outdata.fill(0.0)
            else:
                outdata[:] = output
        except Exception as exc:  # noqa: BLE001 - PortAudio callbacks must not raise.
            self.last_status = str(exc)
            outdata.fill(0.0)


class VstRouteController(QObject):
    _stopWorkerRequested = pyqtSignal()
    runningChanged = pyqtSignal(bool)
    editorAvailableChanged = pyqtSignal(bool)
    statusChanged = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.audio_format = None
        self.processor = None
        self._route: _SoundDeviceRoute | None = None
        self.running = False

    @property
    def available(self) -> bool:
        return _sounddevice_module() is not None and np is not None

    def start(self, input_device: AudioDeviceInfo, output_device: AudioDeviceInfo, plugin_info: VstPluginInfo, buffer_frames: int) -> None:
        if not self.available:
            self.statusChanged.emit(tr("VST routing unavailable."))
            return
        if plugin_info.plugin_format == "VST2":
            self.statusChanged.emit(tr("VST2 plugins are listed, but realtime routing currently requires a VST3 effect."))
            return
        route_settings = _sounddevice_route_settings(input_device, output_device, buffer_frames)
        if route_settings is None:
            self.statusChanged.emit(tr("The selected audio devices do not share a supported format."))
            return
        sample_rate, channel_count, buffer_frames = route_settings
        try:
            processor = _load_vst3_processor(plugin_info, float(sample_rate), int(channel_count))
        except Exception as exc:  # noqa: BLE001 - plugin loaders raise backend-specific errors.
            self.statusChanged.emit(tr("The selected VST could not be loaded: {error}").format(error=exc))
            return
        try:
            self.stop()
            route = _SoundDeviceRoute(input_device, output_device, sample_rate, channel_count, buffer_frames, processor)
            route.start()
            self.processor = processor
            self._route = route
            self.audio_format = (sample_rate, channel_count, buffer_frames, route.driver_name)
            self.running = True
            self.runningChanged.emit(True)
            self.statusChanged.emit(
                tr("Running {plugin} through {format}.").format(
                    plugin=f"{plugin_info.name} ({processor.backend_name})",
                    format=_format_description(self.audio_format),
                )
            )
            self.editorAvailableChanged.emit(bool(getattr(processor, "has_editor", False)))
            if getattr(processor, "has_editor", False):
                self.open_editor()
        except Exception as exc:  # noqa: BLE001
            processor.close()
            self.stop()
            self.statusChanged.emit(tr("VST routing failed: {error}").format(error=exc))

    def open_editor(self) -> None:
        if self.processor is None:
            self.statusChanged.emit(tr("Start a VST before opening its UI."))
            return
        open_editor = getattr(self.processor, "open_editor", None)
        if not callable(open_editor):
            self.statusChanged.emit(tr("The selected backend cannot show this VST editor."))
            return
        try:
            self.statusChanged.emit(tr("VST editor opened."))
            opened = bool(open_editor())
        except Exception as exc:  # noqa: BLE001 - plugin editor launch failures should be visible.
            self.statusChanged.emit(tr("VST editor failed: {error}").format(error=exc))
            return
        if not opened:
            self.statusChanged.emit(tr("The selected backend cannot show this VST editor."))

    def stop(self) -> None:
        if self._route is not None:
            self._route.stop()
        if self.processor is not None:
            self.processor.close()
        self.editorAvailableChanged.emit(False)
        self.audio_format = None
        self.processor = None
        self._route = None
        was_running = self.running
        self.running = False
        if was_running:
            self.runningChanged.emit(False)
            self.statusChanged.emit(tr("Stopped"))

    def _start_audio_worker(self, input_device, output_device, audio_format, processor) -> None:
        return


class _MinihostProcessor:
    backend_name = "minihost"
    has_editor = False

    def __init__(self, path: Path, sample_rate: float, channel_count: int) -> None:
        import minihost

        self.plugin = minihost.Plugin(
            str(path),
            sample_rate=sample_rate,
            max_block_size=ROUTE_CHUNK_FRAMES,
            in_channels=channel_count,
            out_channels=channel_count,
        )
        self.channel_count = channel_count
        self._output = np.zeros((channel_count, ROUTE_CHUNK_FRAMES), dtype=np.float32)

    def process(self, audio, _buffer_frames: int | None = None):
        if audio.shape != self._output.shape:
            self._output = np.zeros(audio.shape, dtype=np.float32)
        else:
            self._output.fill(0.0)
        self.plugin.process(np.ascontiguousarray(audio, dtype=np.float32), self._output)
        return self._output

    def close(self) -> None:
        close = getattr(self.plugin, "close", None)
        if callable(close):
            close()


class _PedalboardProcessor:
    backend_name = "pedalboard"

    def __init__(self, path: Path, sample_rate: float, _channel_count: int) -> None:
        from pedalboard import load_plugin

        self.plugin = load_plugin(str(path), initialization_timeout=15.0)
        if not getattr(self.plugin, "is_effect", False):
            raise RuntimeError(tr("The selected VST is not an audio effect."))
        self.sample_rate = sample_rate
        self.has_editor = callable(getattr(self.plugin, "show_editor", None))
        self._editor_close_event: Event | None = None
        reset = getattr(self.plugin, "reset", None)
        if callable(reset):
            reset()

    def process(self, audio, buffer_frames: int | None = None):
        return self.plugin(
            audio,
            self.sample_rate,
            buffer_size=buffer_frames or ROUTE_CHUNK_FRAMES,
            reset=False,
        )

    def close(self) -> None:
        if self._editor_close_event is not None:
            self._editor_close_event.set()
        self._editor_close_event = None
        close = getattr(self.plugin, "close", None)
        if callable(close):
            close()

    def open_editor(self) -> bool:
        show_editor = getattr(self.plugin, "show_editor", None)
        if not callable(show_editor):
            return False
        self._editor_close_event = Event()
        show_editor(self._editor_close_event)
        self._editor_close_event = None
        return True


def _load_vst3_processor(plugin_info: VstPluginInfo, sample_rate: float, channel_count: int):
    errors: list[str] = []
    for processor_type in (_PedalboardProcessor, _MinihostProcessor):
        try:
            return processor_type(plugin_info.path, sample_rate, channel_count)
        except ModuleNotFoundError as exc:
            errors.append(f"{processor_type.backend_name}: {exc.name} is not installed")
        except Exception as exc:  # noqa: BLE001 - plugin hosts report backend-specific errors.
            errors.append(f"{processor_type.backend_name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    raise RuntimeError(tr("Install minihost or pedalboard to run VST3 effects."))


class VstHostDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("VST Effect Rack"))
        self.resize(760, 520)
        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        self.plugin_filter = QLineEdit()
        self.plugin_filter.setPlaceholderText(tr("Filter VST plugins"))
        self.plugin_list = QListWidget()
        self.refresh_devices_button = QPushButton(tr("Refresh devices"))
        self.scan_button = QPushButton(tr("Scan VSTs"))
        self.add_plugin_button = QPushButton(tr("Add VST file"))
        self.add_folder_button = QPushButton(tr("Add VST folder"))
        self.buffer_combo = QComboBox()
        for frames in LOW_LATENCY_BUFFER_FRAMES:
            self.buffer_combo.addItem(f"{frames} samples", frames)
        self.buffer_combo.setCurrentIndex(1)
        self.start_button = QPushButton(tr("Start"))
        self.stop_button = QPushButton(tr("Stop"))
        self.stop_button.setEnabled(False)
        self.editor_button = QPushButton(tr("Open VST UI"))
        self.editor_button.setEnabled(False)
        self.status_label = QLabel(tr("Ready"))
        self.vst2_check = QCheckBox(tr("Show VST2"))
        self.vst2_check.setChecked(True)

        self.plugins: list[VstPluginInfo] = []
        self._scan_thread: QThread | None = None
        self._scan_worker: _VstSearchWorker | None = None
        self._scan_progress: QProgressDialog | None = None
        self.router = VstRouteController(self)

        form = QGridLayout()
        form.setColumnStretch(1, 1)
        form.addWidget(QLabel(tr("Audio input")), 0, 0)
        form.addWidget(self.input_combo, 0, 1)
        form.addWidget(QLabel(tr("Audio output")), 1, 0)
        form.addWidget(self.output_combo, 1, 1)
        form.addWidget(self.refresh_devices_button, 0, 2, 2, 1)
        form.addWidget(QLabel(tr("Buffer size")), 2, 0)
        form.addWidget(self.buffer_combo, 2, 1)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.plugin_filter, 1)
        search_layout.addWidget(self.vst2_check)
        search_layout.addWidget(self.scan_button)
        search_layout.addWidget(self.add_plugin_button)
        search_layout.addWidget(self.add_folder_button)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.editor_button)
        button_layout.addWidget(self.stop_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(QLabel(tr("VST plugins")))
        layout.addLayout(search_layout)
        layout.addWidget(self.plugin_list, 1)
        layout.addLayout(button_layout)
        layout.addWidget(self.status_label)

        self.refresh_devices_button.clicked.connect(self._refresh_devices)
        self.scan_button.clicked.connect(self._scan_plugins)
        self.add_plugin_button.clicked.connect(self._add_plugin_file)
        self.add_folder_button.clicked.connect(self._add_plugin_folder)
        self.start_button.clicked.connect(self._start_route)
        self.editor_button.clicked.connect(self.router.open_editor)
        self.stop_button.clicked.connect(self.router.stop)
        self.plugin_filter.textChanged.connect(self._populate_plugin_list)
        self.vst2_check.toggled.connect(self._populate_plugin_list)
        self.router.runningChanged.connect(self._on_running_changed)
        self.router.editorAvailableChanged.connect(self.editor_button.setEnabled)
        self.router.statusChanged.connect(self.status_label.setText)

        self._refresh_devices()
        self._scan_plugins()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.router.stop()
        super().closeEvent(event)

    def _refresh_devices(self) -> None:
        self.input_combo.clear()
        self.output_combo.clear()
        if _sounddevice_module() is None:
            self.input_combo.addItem(tr("Audio routing unavailable"), None)
            self.output_combo.addItem(tr("Audio routing unavailable"), None)
            self.start_button.setEnabled(False)
            self.status_label.setText(tr("Audio routing unavailable."))
            return
        inputs = _sounddevice_audio_devices(True)
        outputs = _sounddevice_audio_devices(False)
        if not inputs:
            self.input_combo.addItem(tr("No input device"), None)
        else:
            for device in inputs:
                self.input_combo.addItem(device.display_name, device)
        if not outputs:
            self.output_combo.addItem(tr("No output device"), None)
        else:
            for device in outputs:
                self.output_combo.addItem(device.display_name, device)
        self.start_button.setEnabled(bool(inputs and outputs))
        has_asio = any(device.is_asio for device in (*inputs, *outputs))
        if inputs and outputs:
            self.status_label.setText(tr("ASIO ready") if has_asio else tr("Ready"))
        else:
            self.status_label.setText(tr("Select audio input and output devices."))

    def _scan_plugins(self) -> None:
        if self._scan_thread is not None:
            return
        self.status_label.setText(tr("Searching VST plugins..."))
        self._scan_progress = QProgressDialog(tr("Searching VST plugins..."), tr("Cancel"), 0, 0, self)
        self._scan_progress.setWindowTitle(tr("Searching"))
        self._scan_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._scan_progress.setMinimumDuration(0)
        self._scan_progress.show()
        self._scan_thread = QThread(self)
        self._scan_worker = _VstSearchWorker(default_vst_search_roots())
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_plugins_scanned)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.finished.connect(lambda: setattr(self, "_scan_thread", None))
        self._scan_thread.finished.connect(lambda: setattr(self, "_scan_worker", None))
        self._scan_thread.start()

    def _on_plugins_scanned(self, plugins: list[VstPluginInfo], error: str) -> None:
        if self._scan_progress is not None:
            self._scan_progress.close()
            self._scan_progress = None
        if error:
            self.status_label.setText(tr("VST search failed: {error}").format(error=error))
            return
        self.plugins = plugins
        self._populate_plugin_list()
        self.status_label.setText(
            tr("Found {count} VST plugins.").format(count=len(plugins))
            if plugins
            else tr("No VST plugins found. Use Add VST file.")
        )

    def _populate_plugin_list(self) -> None:
        selected_path = self._selected_plugin_path()
        self.plugin_list.clear()
        needle = self.plugin_filter.text().strip().lower()
        show_vst2 = self.vst2_check.isChecked()
        for plugin in self.plugins:
            if not show_vst2 and plugin.plugin_format == "VST2":
                continue
            searchable = f"{plugin.name} {plugin.path}".lower()
            if needle and needle not in searchable:
                continue
            item = QListWidgetItem(plugin.display_name)
            item.setToolTip(str(plugin.path))
            item.setData(Qt.ItemDataRole.UserRole, plugin)
            self.plugin_list.addItem(item)
            if selected_path is not None and plugin.path == selected_path:
                self.plugin_list.setCurrentItem(item)
        if self.plugin_list.currentRow() < 0 and self.plugin_list.count():
            self.plugin_list.setCurrentRow(0)

    def _add_plugin_file(self) -> None:
        path_text, _filter = QFileDialog.getOpenFileName(
            self,
            tr("Select VST plugin"),
            str(Path.home()),
            tr("VST plugins (*.vst3 *.dll *.vst);;All files (*)"),
        )
        if not path_text:
            return
        info = plugin_info_from_path(Path(path_text))
        if info is None:
            QMessageBox.warning(self, tr("VST Effect Rack"), tr("Select a VST2 or VST3 plugin file."))
            return
        self._add_plugin(info)
        self._populate_plugin_list()
        self.status_label.setText(tr("Added {plugin}.").format(plugin=info.name))

    def _add_plugin_folder(self) -> None:
        path_text = QFileDialog.getExistingDirectory(self, tr("Select VST folder"), str(Path.home()))
        if not path_text:
            return
        path = Path(path_text)
        info = plugin_info_from_path(path)
        if info is not None:
            self._add_plugin(info)
            added = 1
        else:
            plugins = scan_vst_plugins((path,))
            for plugin in plugins:
                self._add_plugin(plugin)
            added = len(plugins)
        self._populate_plugin_list()
        self.status_label.setText(
            tr("Added {count} VST plugins.").format(count=added)
            if added
            else tr("No VST plugins found in the selected folder.")
        )

    def _add_plugin(self, plugin: VstPluginInfo) -> None:
        key = str(plugin.path.resolve(strict=False)).lower()
        current = {str(item.path.resolve(strict=False)).lower() for item in self.plugins}
        if key not in current:
            self.plugins.append(plugin)
            self.plugins.sort(key=lambda item: (item.name.lower(), item.plugin_format, str(item.path).lower()))

    def _start_route(self) -> None:
        input_device = self.input_combo.currentData()
        output_device = self.output_combo.currentData()
        plugin = self._selected_plugin()
        if input_device is None or output_device is None:
            QMessageBox.warning(self, tr("VST Effect Rack"), tr("Select audio input and output devices."))
            return
        if plugin is None:
            QMessageBox.warning(self, tr("VST Effect Rack"), tr("Select a VST plugin."))
            return
        self.router.start(input_device, output_device, plugin, int(self.buffer_combo.currentData() or 128))

    def _selected_plugin(self) -> VstPluginInfo | None:
        item = self.plugin_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, VstPluginInfo) else None

    def _selected_plugin_path(self) -> Path | None:
        plugin = self._selected_plugin()
        return plugin.path if plugin is not None else None

    def _on_running_changed(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.input_combo.setEnabled(not running)
        self.output_combo.setEnabled(not running)
        self.plugin_list.setEnabled(not running)
        self.scan_button.setEnabled(not running)
        self.add_plugin_button.setEnabled(not running)
        self.add_folder_button.setEnabled(not running)
        if not running:
            self.editor_button.setEnabled(False)
