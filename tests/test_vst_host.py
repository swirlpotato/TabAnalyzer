import tempfile
import sys
import unittest
from pathlib import Path

import numpy as np

from tab_analyzer.ui.vst_host import (
    VstPluginInfo,
    _audio_to_float_stream,
    _audio_to_int16_bytes,
    _format_description,
    _int16_bytes_to_audio,
    plugin_info_from_path,
    scan_vst_plugins,
)


class VstHostTests(unittest.TestCase):
    def test_scan_vst_plugins_finds_vst2_files_and_vst3_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vst3 = root / "Amp Rack.vst3"
            vst3.mkdir()
            vst2 = root / "Classic Delay.dll"
            vst2.write_bytes(b"not a real plugin")
            (root / "notes.txt").write_text("ignore me", encoding="utf-8")

            plugins = scan_vst_plugins((root,))

        self.assertEqual(
            [(plugin.name, plugin.plugin_format) for plugin in plugins],
            [("Amp Rack", "VST3"), ("Classic Delay", "VST2")],
        )

    def test_plugin_info_from_path_rejects_non_vst_files(self):
        self.assertEqual(plugin_info_from_path(Path("effect.vst3")), VstPluginInfo("effect", Path("effect.vst3"), "VST3"))
        self.assertEqual(plugin_info_from_path(Path("effect.dll")), VstPluginInfo("effect", Path("effect.dll"), "VST2"))
        self.assertIsNone(plugin_info_from_path(Path("effect.txt")))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows VST3 bundles use this inner binary layout")
    def test_plugin_info_from_windows_vst3_bundle_uses_inner_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "TONEX.vst3"
            binary = bundle / "Contents" / "x86_64-win" / "TONEX.vst3"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"not a real plugin")

            info = plugin_info_from_path(bundle)

        self.assertEqual(info, VstPluginInfo("TONEX", binary, "VST3"))

    def test_int16_audio_round_trip_preserves_shape(self):
        frames = np.array(
            [
                [0, 32767],
                [-32768, 0],
                [8192, -8192],
            ],
            dtype="<i2",
        )
        audio = _int16_bytes_to_audio(frames.tobytes(), 2)
        self.assertEqual(audio.shape, (2, 3))

        raw = _audio_to_int16_bytes(audio, 2, 3)
        self.assertEqual(len(raw), frames.nbytes)

    def test_float_stream_output_matches_stream_layout(self):
        audio = np.array([[0.0, 0.5], [1.0, -1.0]], dtype=np.float32)
        stream = _audio_to_float_stream(audio, 2, 4)
        self.assertEqual(stream.shape, (4, 2))
        self.assertTrue(np.allclose(stream[:2], audio.T))
        self.assertTrue(np.allclose(stream[2:], 0.0))

    def test_route_description_supports_sounddevice_settings(self):
        self.assertEqual(_format_description((44100, 2, 128, "ASIO")), "44100 Hz, 2 ch, 128 frames, ASIO")


if __name__ == "__main__":
    unittest.main()
