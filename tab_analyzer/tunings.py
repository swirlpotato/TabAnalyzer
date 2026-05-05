"""Common guitar tuning presets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "tunings.json"

NOTE_TO_PC = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}


@dataclass(frozen=True)
class TuningPreset:
    id: str
    name: str
    notes_low_to_high: tuple[str, ...]
    description: str

    @property
    def display_name(self) -> str:
        return f"{self.name} ({' '.join(self.notes_low_to_high)})"

    @property
    def midi_low_to_high(self) -> tuple[int, ...]:
        return tuple(note_name_to_midi(note) for note in self.notes_low_to_high)

    @property
    def midi_high_to_low(self) -> tuple[int, ...]:
        return tuple(reversed(self.midi_low_to_high))


def load_tuning_presets(path: Path = DATA_PATH) -> tuple[TuningPreset, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        TuningPreset(
            id=item["id"],
            name=item["name"],
            notes_low_to_high=tuple(item["notes_low_to_high"]),
            description=item.get("description", ""),
        )
        for item in data["presets"]
    )


def note_name_to_midi(note_name: str) -> int:
    match = re.fullmatch(r"([A-Ga-g])([#bB]?)(-?\d+)", note_name.strip())
    if not match:
        raise ValueError(f"Invalid note name: {note_name}")

    letter, accidental, octave_text = match.groups()
    key = (letter + accidental).upper()
    pitch_class = NOTE_TO_PC[key]
    octave = int(octave_text)
    return (octave + 1) * 12 + pitch_class
