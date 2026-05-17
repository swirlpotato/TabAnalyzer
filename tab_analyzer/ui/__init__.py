"""PyQt6 user interface for the tab analyzer."""

from __future__ import annotations

import sys
import types

from .common import *
from .workers import AnalysisProgressDialog, _LoadWorker, _SongsterrWorker, _YouTubeSyncWorker
from .score import TabCanvas, TabScoreWidget
from .playback_core import RecordingController, StandaloneMetronome, YouTubeTabPlayer
from .songsterr_panel import SongsterrPagePanel
from .tab_playback_panel import MemoEditorWidget, RecordingListRow, TabPlaybackPanel
from .fretboard import FretboardWidget, ScalePositionWidget, SongScaleUsageWidget
from .chords import ChordFinderWidget, ChordPositionsWidget
from .main_window import TabAnalyzerWindow, run_app

_PATCHABLE_MODULE_NAMES = (
    "tab_analyzer.ui.common",
    "tab_analyzer.ui.workers",
    "tab_analyzer.ui.score",
    "tab_analyzer.ui.playback_core",
    "tab_analyzer.ui.songsterr_panel",
    "tab_analyzer.ui.tab_playback_panel",
    "tab_analyzer.ui.fretboard",
    "tab_analyzer.ui.chords",
    "tab_analyzer.ui.main_window",
)


class _UiModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module_name in _PATCHABLE_MODULE_NAMES:
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _UiModule

__all__ = [name for name in globals() if name == "__version__" or not (name.startswith("__") and name.endswith("__"))]
