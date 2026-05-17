"""Tab score painting widgets."""

from __future__ import annotations

from .common import *

class TabCanvas(QWidget):
    selectionChanged = pyqtSignal(object, object, str, object)
    memoClicked = pyqtSignal(int)
    zoomWheelRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.zoom = 1.0
        self.selected_measure_index: int | None = None
        self.selected_segment: SegmentData | None = None
        self.selected_candidate: Candidate | None = None
        self.selected_kind = "scale"
        self._measure_layouts: list[_MeasureLayout] = []
        self._candidate_hits: list[_CandidateHit] = []
        self._memo_icon_hits: list[_MemoIconHit] = []
        self._memo_measure_numbers: set[int] = set()
        self._content_height = 320
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(960, max(320, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_measure_index = None
        self.selected_segment = None
        self.selected_candidate = None
        self._rebuild_layout()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.65, min(2.4, zoom))
        self._rebuild_layout()
        self.update()

    def set_memo_measure_numbers(self, measure_numbers: set[int]) -> None:
        self._memo_measure_numbers = set(measure_numbers)
        self.update()

    def set_selected_measure_index(self, measure_index: int, emit: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            return
        measure_index = max(0, min(measure_index, len(self.song.track.measures) - 1))
        measure = self.song.track.measures[measure_index]
        candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
        self.selected_measure_index = measure_index
        self.selected_candidate = candidate
        self.selected_kind = "scale"
        self.selected_segment = None
        if emit:
            self.selectionChanged.emit(measure, candidate, "scale", None)
        self.update()

    def layout_for_measure(self, measure_index: int) -> _MeasureLayout | None:
        for layout in self._measure_layouts:
            if layout.index == measure_index:
                return layout
        return None

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None:
            return
        position = event.position().toPoint()

        for hit in reversed(self._memo_icon_hits):
            if hit.rect.contains(position):
                measure = self.song.track.measures[hit.measure_index]
                candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
                self._select(hit.measure_index, candidate, "scale", None)
                self.memoClicked.emit(hit.measure_index)
                return

        for hit in reversed(self._candidate_hits):
            if hit.rect.contains(position):
                self._select(hit.measure_index, hit.candidate, hit.kind, hit.segment)
                return

        for layout in self._measure_layouts:
            if layout.rect.contains(position):
                measure = self.song.track.measures[layout.index]
                candidate = measure.analysis.scale_candidates[0] if measure.analysis.scale_candidates else None
                self._select(layout.index, candidate, "scale", None)
                return

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoomWheelRequested.emit(10 if delta > 0 else -10)
                event.accept()
                return
        super().wheelEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))
        self._candidate_hits = []
        self._memo_icon_hits = []

        if self.song is None:
            self._draw_empty(painter)
            return

        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            self._draw_measure(painter, layout, measure)

    def _select(
        self,
        measure_index: int,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None,
    ) -> None:
        if self.song is None:
            return
        self.selected_measure_index = measure_index
        self.selected_candidate = candidate
        self.selected_kind = kind
        self.selected_segment = segment
        self.selectionChanged.emit(self.song.track.measures[measure_index], candidate, kind, segment)
        self.update()

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Open a Guitar Pro file"))

    def _draw_measure(self, painter: QPainter, layout: _MeasureLayout, measure: MeasureData) -> None:
        rect = layout.rect
        selected = layout.index == self.selected_measure_index
        background = QColor("#ffffff") if not selected else QColor("#edf4ff")
        border = QColor("#c7d1df") if not selected else QColor("#3d7edb")

        painter.setPen(QPen(border, 1.4 if selected else 1.0))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        title_font = QFont("Segoe UI", max(8, int(9 * self.zoom)))
        painter.setFont(title_font)
        painter.setPen(QColor("#2e3a4f"))
        title = f"M{measure.number}  {measure.time_signature}"
        painter.drawText(rect.adjusted(8, 4, -8, 0), Qt.AlignmentFlag.AlignLeft, title)
        self._draw_memo_icon(painter, rect, layout.index, measure)

        self._draw_tab_lines(painter, rect, measure)
        self._draw_segment_changes(painter, rect, layout.index, measure)
        self._draw_analysis_chips(painter, rect, layout.index, measure)

    def _draw_memo_icon(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        font = QFont("Segoe UI", max(8, int(9 * self.zoom)))
        metrics = QFontMetrics(font)
        title = f"M{measure.number}  {measure.time_signature}"
        size = max(12, int(14 * self.zoom))
        x = rect.left() + 12 + metrics.horizontalAdvance(title)
        y = rect.top() + max(4, int(5 * self.zoom))
        icon_rect = _post_it_icon_rect(x, y, size)
        _draw_post_it_icon(painter, icon_rect, measure.number in self._memo_measure_numbers)
        self._memo_icon_hits.append(_MemoIconHit(icon_rect.adjusted(-3, -3, 3, 3), measure_index))

    def _draw_tab_lines(self, painter: QPainter, rect: QRect, measure: MeasureData) -> None:
        if self.song is None:
            return

        left_pad = int(34 * self.zoom)
        right_pad = int(10 * self.zoom)
        tab_top = rect.top() + int(30 * self.zoom)
        string_gap = max(8, int(10 * self.zoom))
        line_width = max(1, int(1.2 * self.zoom))
        tab_left = rect.left() + left_pad
        tab_right = rect.right() - right_pad
        note_pad = max(8, int(12 * self.zoom))
        tab_width = max(40, tab_right - tab_left - (note_pad * 2))

        painter.setPen(QPen(QColor("#96a1b2"), line_width))
        label_font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(label_font)
        string_names = self.song.track.string_names
        for string_index, name in enumerate(string_names):
            y = tab_top + (string_index * string_gap)
            painter.drawLine(tab_left, y, tab_right, y)
            painter.setPen(QColor("#6b7280"))
            painter.drawText(rect.left() + 8, y + 4, name[:-1] if len(name) > 1 else name)
            painter.setPen(QPen(QColor("#96a1b2"), line_width))

        painter.setPen(QPen(QColor("#7d8797"), line_width))
        painter.drawLine(tab_left, tab_top, tab_left, tab_top + (len(string_names) - 1) * string_gap)
        painter.drawLine(tab_right, tab_top, tab_right, tab_top + (len(string_names) - 1) * string_gap)

        note_font = QFont("Consolas", max(8, int(9 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(note_font)
        metrics = QFontMetrics(note_font)
        for beat in measure.beats:
            if not beat.notes:
                continue
            beat_ratio = min(1.0, max(0.0, beat.start_in_measure / measure.length_ticks))
            x = tab_left + note_pad + int(beat_ratio * tab_width)
            for note in beat.notes:
                y = tab_top + ((note.string - 1) * string_gap)
                text = tab_note_text(note)
                text_rect = QRect(
                    x - metrics.horizontalAdvance(text) // 2 - 3,
                    y - metrics.height() // 2,
                    metrics.horizontalAdvance(text) + 6,
                    metrics.height(),
                )
                painter.setPen(QColor("#111827"))
                painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_analysis_chips(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(font)
        metrics = QFontMetrics(font)

        y = rect.top() + int(126 * self.zoom)
        if self.zoom < 0.9:
            y = rect.top() + int(114 * self.zoom)

        scale_color = QColor("#cb3a31")
        chord_color = QColor("#2468d8")
        next_y = self._draw_chip_row(
            painter,
            rect.left() + 8,
            y,
            rect.width() - 16,
            "S",
            measure.analysis.scale_candidates,
            scale_color,
            metrics,
            measure_index,
            "scale",
            None,
        )
        self._draw_chip_row(
            painter,
            rect.left() + 8,
            next_y + 3,
            rect.width() - 16,
            "C",
            measure.analysis.chord_candidates,
            chord_color,
            metrics,
            measure_index,
            "chord",
            None,
        )

    def _draw_chip_row(
        self,
        painter: QPainter,
        x: int,
        y: int,
        width: int,
        prefix: str,
        candidates: tuple[Candidate, ...],
        color: QColor,
        metrics: QFontMetrics,
        measure_index: int,
        kind: str,
        segment: SegmentData | None,
    ) -> int:
        painter.setPen(QColor("#5f6b7c"))
        chip_height = metrics.height() + 4
        line_step = chip_height + 4
        prefix_rect = QRect(x, y, 18, chip_height)
        painter.drawText(prefix_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, prefix)
        row_x = x + 20
        cursor_x = row_x
        cursor_y = y
        max_x = x + width
        row_width = max(42, max_x - row_x)

        if not candidates:
            painter.drawText(QRect(cursor_x, y, width - 20, chip_height), Qt.AlignmentFlag.AlignVCenter, "-")
            return y + line_step

        for candidate in self._display_candidates(candidates, kind):
            label = self._candidate_label(candidate)
            chip_width = min(max(metrics.horizontalAdvance(label) + 12, 42), row_width)
            if cursor_x > row_x and cursor_x + chip_width > max_x:
                cursor_x = row_x
                cursor_y += line_step
            if cursor_x + chip_width > max_x:
                chip_width = max(42, max_x - cursor_x)
            chip_rect = QRect(cursor_x, cursor_y, chip_width, chip_height)
            painter.setPen(QPen(color, 1))
            fill = QColor(color)
            fill.setAlpha(24)
            painter.setBrush(fill)
            painter.drawRoundedRect(chip_rect, 5, 5)
            painter.setPen(color)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            visible_label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, chip_width - 10)
            painter.drawText(chip_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignCenter, visible_label)
            self._candidate_hits.append(_CandidateHit(chip_rect, measure_index, candidate, kind, segment))
            cursor_x += chip_width + 4
        return cursor_y + line_step

    def _draw_segment_changes(self, painter: QPainter, rect: QRect, measure_index: int, measure: MeasureData) -> None:
        if len(measure.segments) <= 1:
            return

        tab_left, tab_right = self._tab_x_bounds(rect)
        tab_width = max(40, tab_right - tab_left)
        row_height = max(12, int(15 * self.zoom))
        gap = max(2, int(3 * self.zoom))
        scale_y = rect.top() + int(86 * self.zoom)
        chord_y = scale_y + row_height + gap
        scale_color = QColor("#cb3a31")
        chord_color = QColor("#2468d8")
        marker_color = QColor("#2f3746")
        font = QFont("Segoe UI", max(6, int(7 * self.zoom)))
        painter.setFont(font)
        metrics = QFontMetrics(font)

        previous_scale = ""
        previous_chord = ""
        for segment in measure.segments:
            x1 = tab_left + int((segment.start_in_measure / measure.length_ticks) * tab_width)
            x2 = tab_left + int((segment.end_in_measure / measure.length_ticks) * tab_width)
            segment_width = max(8, x2 - x1)
            scale = segment.analysis.scale_candidates[0] if segment.analysis.scale_candidates else None
            chord = segment.analysis.chord_candidates[0] if segment.analysis.chord_candidates else None
            scale_name = scale.name if scale else ""
            chord_name = chord.name if chord else ""

            if segment.index > 0 and (scale_name != previous_scale or chord_name != previous_chord):
                painter.setPen(QPen(marker_color, 1.2))
                painter.drawLine(x1, scale_y - 3, x1, chord_y + row_height + 2)

            if scale is not None:
                self._draw_segment_chip(
                    painter,
                    QRect(x1, scale_y, segment_width, row_height),
                    scale,
                    scale_color,
                    metrics,
                    measure_index,
                    "scale",
                    segment,
                )
            if chord is not None:
                self._draw_segment_chip(
                    painter,
                    QRect(x1, chord_y, segment_width, row_height),
                    chord,
                    chord_color,
                    metrics,
                    measure_index,
                    "chord",
                    segment,
                )

            previous_scale = scale_name
            previous_chord = chord_name

    def _draw_segment_chip(
        self,
        painter: QPainter,
        chip_rect: QRect,
        candidate: Candidate,
        color: QColor,
        metrics: QFontMetrics,
        measure_index: int,
        kind: str,
        segment: SegmentData,
    ) -> None:
        if chip_rect.width() < 8:
            return

        fill = QColor(color)
        fill.setAlpha(20)
        painter.setPen(QPen(color, 0.8))
        painter.setBrush(fill)
        painter.drawRoundedRect(chip_rect, 4, 4)

        if chip_rect.width() >= 28:
            painter.setPen(color)
            label = self._short_candidate_label(candidate)
            visible_label = metrics.elidedText(label, Qt.TextElideMode.ElideRight, chip_rect.width() - 4)
            painter.drawText(chip_rect.adjusted(2, 0, -2, 0), Qt.AlignmentFlag.AlignCenter, visible_label)

        self._candidate_hits.append(_CandidateHit(chip_rect, measure_index, candidate, kind, segment))

    def _short_candidate_label(self, candidate: Candidate) -> str:
        name = candidate_display_name(candidate, self._prefer_flats())
        name = name.replace("natural minor", "min")
        name = name.replace("harmonic minor", "hmin")
        name = name.replace("phrygian dominant", "phr dom")
        name = name.replace("locrian natural 6", "loc n6")
        name = name.replace("ionian augmented", "ion aug")
        name = name.replace("dorian #4", "dor #4")
        name = name.replace("lydian #2", "lyd #2")
        name = name.replace("altered diminished", "alt dim")
        name = name.replace("melodic minor", "mmin")
        name = name.replace("major pentatonic", "maj p")
        name = name.replace("minor pentatonic", "min p")
        return f"{name} {candidate.score}"

    def _candidate_label(self, candidate: Candidate) -> str:
        return candidate_display_label(candidate, self._prefer_flats())

    def _display_candidates(self, candidates: tuple[Candidate, ...], kind: str) -> tuple[Candidate, ...]:
        if kind != "scale":
            return candidates[:MAX_DISPLAY_CANDIDATES]

        display: list[Candidate] = []
        seen_pitch_sets: set[tuple[int, ...]] = set()
        for candidate in candidates:
            key = tuple(sorted(candidate.pitch_classes))
            if key in seen_pitch_sets:
                continue
            seen_pitch_sets.add(key)
            display.append(candidate)
            if len(display) >= MAX_DISPLAY_CANDIDATES:
                break
        return tuple(display)

    def _prefer_flats(self) -> bool | None:
        return self.song.track.prefer_flats if self.song is not None else None

    def _tab_x_bounds(self, rect: QRect) -> tuple[int, int]:
        left_pad = int(34 * self.zoom)
        right_pad = int(10 * self.zoom)
        return rect.left() + left_pad, rect.right() - right_pad

    def _rebuild_layout(self) -> None:
        self._measure_layouts = []
        if self.song is None:
            self._content_height = 320
            self.setMinimumHeight(self._content_height)
            return

        width = max(360, self.width())
        margin = int(12 * self.zoom)
        x = margin
        y = margin
        max_width = width - (margin * 2)
        chip_metrics = QFontMetrics(QFont("Segoe UI", max(7, int(8 * self.zoom))))
        row_height = 0

        for index, measure in enumerate(self.song.track.measures):
            note_slots = max(1, sum(1 for beat in measure.beats if beat.notes))
            change_slots = max(1, len(measure.segments) * 2)
            desired_width = int(max(172 * self.zoom, 58 * self.zoom + max(note_slots, change_slots) * 35 * self.zoom))
            measure_width = min(max_width, desired_width)
            measure_height = self._measure_row_height(measure, measure_width, chip_metrics)
            if x > margin and x + measure_width > width - margin:
                x = margin
                y += row_height + margin
                row_height = 0
            self._measure_layouts.append(_MeasureLayout(index, QRect(x, y, measure_width, measure_height)))
            row_height = max(row_height, measure_height)
            x += measure_width + margin

        self._content_height = max(320, y + row_height + margin)
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _measure_row_height(self, measure: MeasureData, measure_width: int, metrics: QFontMetrics) -> int:
        chip_width = measure_width - 16
        scale_lines = self._chip_line_count(measure.analysis.scale_candidates, chip_width, metrics, "scale")
        chord_lines = self._chip_line_count(measure.analysis.chord_candidates, chip_width, metrics, "chord")
        extra_lines = max(0, scale_lines + chord_lines - 2)
        return int(190 * self.zoom) + extra_lines * (metrics.height() + 8)

    def _chip_line_count(
        self,
        candidates: tuple[Candidate, ...],
        width: int,
        metrics: QFontMetrics,
        kind: str,
    ) -> int:
        display_candidates = self._display_candidates(candidates, kind)
        if not display_candidates:
            return 1
        row_width = max(42, width - 20)
        lines = 1
        cursor_width = 0
        for candidate in display_candidates:
            label = self._candidate_label(candidate)
            chip_width = min(max(metrics.horizontalAdvance(label) + 12, 42), row_width)
            if cursor_width > 0 and cursor_width + chip_width > row_width:
                lines += 1
                cursor_width = 0
            cursor_width += chip_width + 4
        return lines


class TabScoreWidget(QWidget):
    selectionChanged = pyqtSignal(int, int)
    zoomWheelRequested = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.zoom = 1.0
        self.selected_start = 0
        self.selected_end = 0
        self.playback_tick: int | None = None
        self._measure_layouts: list[_MeasureLayout] = []
        self._content_size = QSize(960, 260)
        self._drag_anchor: int | None = None
        self._dragging = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return self._content_size

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_start = 0
        self.selected_end = 0
        self.playback_tick = None
        self._rebuild_layout()
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(0.6, min(2.2, zoom))
        self._rebuild_layout()
        self.update()

    def set_selected_range(self, start: int, end: int, emit: bool = False) -> None:
        if self.song is None or not self.song.track.measures:
            self.selected_start = 0
            self.selected_end = 0
            self.update()
            return
        count = len(self.song.track.measures)
        start = max(0, min(start, count - 1))
        end = max(0, min(end, count - 1))
        if end < start:
            start, end = end, start
        changed = (start, end) != (self.selected_start, self.selected_end)
        self.selected_start = start
        self.selected_end = end
        if changed:
            self.update()
            if emit:
                self.selectionChanged.emit(start, end)

    def set_playback_tick(self, tick: int | None) -> None:
        self.playback_tick = tick
        self.update()

    def layout_for_tick(self, tick: int) -> _MeasureLayout | None:
        if self.song is None or not self._measure_layouts:
            return None
        last_layout: _MeasureLayout | None = None
        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            measure_start = measure.start_tick
            measure_end = measure.start_tick + measure.length_ticks
            if measure_start <= tick < measure_end:
                return layout
            last_layout = layout
        return last_layout if tick >= self.song.track.measures[-1].start_tick else None

    def layout_for_measure(self, measure_index: int) -> _MeasureLayout | None:
        for layout in self._measure_layouts:
            if layout.index == measure_index:
                return layout
        return None

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None:
            return
        position = event.position().toPoint()
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._measure_index_at(position)
            if index is not None:
                self._drag_anchor = index
                self._dragging = True
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.set_selected_range(self.selected_start, index, emit=True)
                else:
                    self.set_selected_range(index, index, emit=True)
                return

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self.song is None or not self._dragging or self._drag_anchor is None:
            return
        index = self._measure_index_at(event.position().toPoint())
        if index is None:
            return
        self.set_selected_range(self._drag_anchor, index, emit=True)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_anchor = None
            return

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoomWheelRequested.emit(10 if delta > 0 else -10)
                event.accept()
                return
        super().wheelEvent(event)

    def _measure_index_at(self, position: QPoint) -> int | None:
        for layout in self._measure_layouts:
            if layout.rect.contains(position):
                return layout.index
        return None

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfaf6"))
        if self.song is None:
            self._draw_empty(painter)
            return
        self._draw_systems(painter)
        for layout in self._measure_layouts:
            measure = self.song.track.measures[layout.index]
            self._draw_measure(painter, layout, measure)

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Open a Guitar Pro file"))

    def _draw_measure(self, painter: QPainter, layout: _MeasureLayout, measure: MeasureData) -> None:
        if self.song is None:
            return
        rect = layout.rect
        selected = self.selected_start <= layout.index <= self.selected_end
        tab_left, tab_right, tab_top, string_gap = self._tab_geometry(rect)
        string_count = len(self.song.track.string_names)
        tab_bottom = tab_top + ((string_count - 1) * string_gap)

        if selected:
            highlight = QColor("#ffd46f")
            highlight.setAlpha(85)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(highlight)
            painter.drawRect(QRect(tab_left + 1, rect.top() + int(19 * self.zoom), max(1, tab_right - tab_left - 1), tab_bottom - rect.top() + int(22 * self.zoom)))

        title_font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor("#445065"))
        title = f"{measure.number}"
        painter.drawText(QRect(tab_left + 4, rect.top() + 2, max(24, rect.width() - 8), int(17 * self.zoom)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        bar_pen = QPen(QColor("#424b59"), max(1, int(1.2 * self.zoom)))
        painter.setPen(bar_pen)
        if self._is_row_start(layout):
            painter.drawLine(tab_left, tab_top, tab_left, tab_bottom)
        painter.drawLine(tab_right, tab_top, tab_right, tab_bottom)

        self._draw_notes(painter, rect, measure, tab_left, tab_right, tab_top, string_gap)
        self._draw_playback_cursor(painter, layout, measure, tab_left, tab_right, tab_top, string_gap)

    def _draw_systems(self, painter: QPainter) -> None:
        if self.song is None:
            return

        line_pen = QPen(QColor("#7e8796"), max(1, int(1.05 * self.zoom)))
        label_font = QFont("Segoe UI", max(7, int(8 * self.zoom)))
        painter.setFont(label_font)
        rows = self._row_groups()
        for row in rows:
            first = row[0]
            last = row[-1]
            tab_left, _right, tab_top, string_gap = self._tab_geometry(first.rect)
            tab_right = self._tab_geometry(last.rect)[1]
            label_x = max(2, tab_left - int(38 * self.zoom))
            for string_index, name in enumerate(self.song.track.string_names):
                y = tab_top + (string_index * string_gap)
                painter.setPen(QColor("#5e6775"))
                painter.drawText(QRect(label_x, y - 8, int(30 * self.zoom), 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name[:-1] if len(name) > 1 else name)
                painter.setPen(line_pen)
                painter.drawLine(tab_left, y, tab_right, y)

    def _draw_notes(
        self,
        painter: QPainter,
        rect: QRect,
        measure: MeasureData,
        tab_left: int,
        tab_right: int,
        tab_top: int,
        string_gap: int,
    ) -> None:
        tab_width = max(1, tab_right - tab_left)
        note_font = QFont("Consolas", max(9, int(11 * self.zoom)), QFont.Weight.DemiBold)
        note_metrics = QFontMetrics(note_font)
        note_positions = self._note_positions(measure, tab_left, tab_width, tab_top, string_gap)
        beat_positions = self._beat_positions(note_positions)

        self._draw_rhythm_notation(painter, measure, beat_positions, tab_top, string_gap)
        self._draw_technique_spans(painter, beat_positions, rect.top(), tab_top)
        self._draw_note_relationships(painter, note_positions, note_metrics)

        for x, y, note, _beat in note_positions:
            self._draw_note_technique_symbols(painter, note, x, y, note_metrics)

        painter.setFont(note_font)
        for x, y, note, _beat in note_positions:
            text = tab_note_text(note)
            width = note_metrics.horizontalAdvance(text) + 8
            text_rect = QRect(x - width // 2, y - note_metrics.height() // 2, width, note_metrics.height())
            painter.setPen(QColor("#171923"))
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def _note_positions(
        self,
        measure: MeasureData,
        tab_left: int,
        tab_width: int,
        tab_top: int,
        string_gap: int,
    ) -> list[tuple[int, int, object, BeatData]]:
        note_pad = max(10, int(14 * self.zoom))
        effective_width = max(1, tab_width - (note_pad * 2))
        note_font = QFont("Consolas", max(9, int(11 * self.zoom)), QFont.Weight.DemiBold)
        note_metrics = QFontMetrics(note_font)
        min_gap = max(4, int(6 * self.zoom))
        beat_items: list[tuple[int, BeatData, tuple[object, ...], int]] = []
        for beat in measure.beats:
            if not beat.notes:
                continue
            ratio = min(1.0, max(0.0, beat.start_in_measure / measure.length_ticks))
            x = tab_left + note_pad + int(ratio * effective_width)
            half_width = max(
                1,
                max((note_metrics.horizontalAdvance(tab_note_text(note)) + 8) // 2 for note in beat.notes),
            )
            beat_items.append((x, beat, tuple(beat.notes), half_width))

        adjusted_by_beat = self._spread_close_beat_positions(
            beat_items,
            tab_left + note_pad,
            tab_left + note_pad + effective_width,
            min_gap,
        )

        positions: list[tuple[int, int, object, BeatData]] = []
        for raw_x, beat, notes, _half_width in beat_items:
            x = adjusted_by_beat.get(id(beat), raw_x)
            for note in beat.notes:
                y = tab_top + ((note.string - 1) * string_gap)
                positions.append((x, y, note, beat))
        return positions

    def _spread_close_beat_positions(
        self,
        beat_items: list[tuple[int, BeatData, tuple[object, ...], int]],
        min_x: int,
        max_x: int,
        min_gap: int,
    ) -> dict[int, int]:
        if not beat_items:
            return {}

        ordered = sorted(beat_items, key=lambda item: (item[1].start_in_measure, item[0]))
        half_widths = [half_width for _x, _beat, _notes, half_width in ordered]
        total_text_width = sum(half_width * 2 for half_width in half_widths)
        available_width = max(1, max_x - min_x)
        local_gap = min_gap
        if len(ordered) > 1 and total_text_width + (min_gap * (len(ordered) - 1)) > available_width:
            local_gap = max(0, (available_width - total_text_width) // (len(ordered) - 1))

        adjusted: list[tuple[BeatData, int, int]] = []
        previous_right: int | None = None
        for item, half_width in zip(ordered, half_widths):
            raw_x, beat, _notes, _half_width = item
            target_x = max(min_x + half_width, raw_x)
            if previous_right is not None:
                target_x = max(target_x, previous_right + local_gap + half_width)
            adjusted.append((beat, target_x, half_width))
            previous_right = target_x + half_width

        overflow = adjusted[-1][1] + adjusted[-1][2] - max_x
        if overflow > 0:
            adjusted = [(beat, x - overflow, half_width) for beat, x, half_width in adjusted]

        adjusted_by_beat: dict[int, int] = {}
        previous_right = None
        for beat, x, half_width in adjusted:
            target_x = max(min_x + half_width, x)
            if previous_right is not None:
                target_x = max(target_x, previous_right + local_gap + half_width)
            adjusted_by_beat[id(beat)] = target_x
            previous_right = target_x + half_width
        return adjusted_by_beat

    def _beat_positions(self, positions: list[tuple[int, int, object, BeatData]]) -> list[tuple[int, BeatData]]:
        seen: set[int] = set()
        beat_positions: list[tuple[int, BeatData]] = []
        for x, _y, _note, beat in positions:
            key = id(beat)
            if key in seen:
                continue
            seen.add(key)
            beat_positions.append((x, beat))
        return sorted(beat_positions, key=lambda item: (item[1].start_in_measure, item[0]))

    def _draw_rhythm_notation(
        self,
        painter: QPainter,
        measure: MeasureData,
        beat_positions: list[tuple[int, BeatData]],
        tab_top: int,
        string_gap: int,
    ) -> None:
        if not beat_positions or self.song is None:
            return

        string_count = len(self.song.track.string_names)
        tab_bottom = tab_top + ((string_count - 1) * string_gap)
        stem_top = tab_bottom + int(8 * self.zoom)
        stem_bottom = tab_bottom + int(28 * self.zoom)
        beam_gap = max(3, int(4 * self.zoom))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rhythm_pen = QPen(QColor("#535353"), max(1, int(1.05 * self.zoom)))
        rhythm_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(rhythm_pen)
        painter.setBrush(QColor("#535353"))

        for x, beat in beat_positions:
            if beat.duration_ticks >= 3840:
                painter.drawEllipse(QPointF(x, stem_top + int(4 * self.zoom)), max(3, int(4 * self.zoom)), max(2, int(2.5 * self.zoom)))
                continue
            painter.drawLine(x, stem_top, x, stem_bottom)
            if beat.duration_ticks >= 1920:
                painter.drawEllipse(QPointF(x, stem_top + int(3 * self.zoom)), max(3, int(4 * self.zoom)), max(2, int(2.5 * self.zoom)))

        self._draw_rhythm_beams(painter, beat_positions, stem_bottom, beam_gap)
        self._draw_tuplet_labels(painter, beat_positions, stem_bottom)
        painter.restore()

    def _draw_rhythm_beams(
        self,
        painter: QPainter,
        beat_positions: list[tuple[int, BeatData]],
        stem_bottom: int,
        beam_gap: int,
    ) -> None:
        runs = self._rhythm_beam_runs(beat_positions)
        beam_height = max(2, int(3 * self.zoom))
        for run in runs:
            if len(run) == 1:
                x, beat = run[0]
                for level in range(self._rhythm_beam_count(beat.duration_ticks)):
                    y = stem_bottom - (level * beam_gap)
                    painter.drawRect(QRect(x, y - beam_height // 2, int(10 * self.zoom), beam_height))
                continue

            min_count = min(self._rhythm_beam_count(beat.duration_ticks) for _x, beat in run)
            start_x = run[0][0]
            end_x = run[-1][0]
            for level in range(min_count):
                y = stem_bottom - (level * beam_gap)
                painter.drawRect(QRect(start_x, y - beam_height // 2, max(1, end_x - start_x), beam_height))
            for x, beat in run:
                extra = self._rhythm_beam_count(beat.duration_ticks) - min_count
                for level in range(extra):
                    y = stem_bottom - ((min_count + level) * beam_gap)
                    painter.drawRect(QRect(x, y - beam_height // 2, int(10 * self.zoom), beam_height))

    def _rhythm_beam_runs(self, beat_positions: list[tuple[int, BeatData]]) -> list[list[tuple[int, BeatData]]]:
        runs: list[list[tuple[int, BeatData]]] = []
        current: list[tuple[int, BeatData]] = []
        expected_next: int | None = None
        for item in beat_positions:
            _x, beat = item
            if self._rhythm_beam_count(beat.duration_ticks) <= 0:
                if current:
                    runs.append(current)
                    current = []
                expected_next = beat.start_in_measure + beat.duration_ticks
                continue
            if current and expected_next is not None and abs(beat.start_in_measure - expected_next) > 1:
                runs.append(current)
                current = []
            current.append(item)
            expected_next = beat.start_in_measure + beat.duration_ticks
        if current:
            runs.append(current)
        return runs

    def _draw_tuplet_labels(self, painter: QPainter, beat_positions: list[tuple[int, BeatData]], stem_bottom: int) -> None:
        groups = self._tuplet_groups(beat_positions)
        if not groups:
            return
        color = QColor("#2f3746")
        bracket_pen = QPen(color, max(1, int(1.35 * self.zoom)))
        bracket_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(bracket_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        bracket_y = stem_bottom + int(10 * self.zoom)
        hook_top = stem_bottom + int(2 * self.zoom)
        overhang = max(3, int(4 * self.zoom))
        label_gap = max(3, int(4 * self.zoom))
        for label, start_x, end_x in groups:
            if end_x <= start_x:
                continue
            bracket_start = start_x - overhang
            bracket_end = end_x + overhang
            rect = QRect(
                int((start_x + end_x) / 2) - metrics.horizontalAdvance(label) // 2 - 4,
                bracket_y - metrics.height() // 2,
                metrics.horizontalAdvance(label) + 8,
                metrics.height(),
            )

            painter.setPen(bracket_pen)
            painter.drawLine(bracket_start, bracket_y, max(bracket_start, rect.left() - label_gap), bracket_y)
            painter.drawLine(min(bracket_end, rect.right() + label_gap), bracket_y, bracket_end, bracket_y)
            painter.drawLine(bracket_start, hook_top, bracket_start, bracket_y)
            painter.drawLine(bracket_end, hook_top, bracket_end, bracket_y)
            painter.drawLine(bracket_start, hook_top, bracket_start + overhang, hook_top)
            painter.drawLine(bracket_end - overhang, hook_top, bracket_end, hook_top)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#fff5d8"))
            painter.drawRoundedRect(rect.adjusted(-1, 0, 1, 0), 2, 2)
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _tuplet_groups(self, beat_positions: list[tuple[int, BeatData]]) -> list[tuple[str, int, int]]:
        groups: list[tuple[str, int, int]] = []
        index = 0
        while index < len(beat_positions):
            _x, beat = beat_positions[index]
            tuplet_info = self._tuplet_info_for_beat(beat)
            if tuplet_info is None:
                index += 1
                continue
            label, target_count = tuplet_info
            start_index = index
            expected_next = beat.start_in_measure + beat.duration_ticks
            index += 1
            while index < len(beat_positions):
                _next_x, next_beat = beat_positions[index]
                next_tuplet_info = self._tuplet_info_for_beat(next_beat)
                if next_tuplet_info is None or next_tuplet_info[0] != label:
                    break
                if abs(next_beat.start_in_measure - expected_next) > 1:
                    break
                expected_next = next_beat.start_in_measure + next_beat.duration_ticks
                index += 1
            run_count = index - start_index
            if run_count >= target_count * 2:
                continue
            for group_start in range(start_index, index, target_count):
                group_end = min(group_start + target_count, index) - 1
                if group_end > group_start:
                    groups.append((label, beat_positions[group_start][0], beat_positions[group_end][0]))
        return groups

    def _tuplet_info_for_beat(self, beat: BeatData) -> tuple[str, int] | None:
        if beat.tuplet is not None:
            numerator, _denominator = beat.tuplet
            if numerator > 1:
                return str(numerator), numerator
        label = self._tuplet_label_for_duration(beat.duration_ticks)
        if label is None:
            return None
        return label, int(label)

    def _tuplet_label_for_duration(self, duration_ticks: int) -> str | None:
        standard = {30, 60, 120, 240, 480, 960, 1920, 3840}
        for label, numerator, denominator in (("3", 3, 2), ("5", 5, 4), ("6", 6, 4), ("7", 7, 4)):
            base = duration_ticks * numerator / denominator
            if any(abs(base - value) <= 1 for value in standard):
                return label
        return None

    def _rhythm_beam_count(self, duration_ticks: int) -> int:
        if duration_ticks <= 60:
            return 4
        if duration_ticks <= 120:
            return 3
        if duration_ticks <= 240:
            return 2
        if duration_ticks <= 480:
            return 1
        return 0

    def _draw_technique_spans(
        self,
        painter: QPainter,
        beat_positions: list[tuple[int, BeatData]],
        row_top: int,
        tab_top: int,
    ) -> None:
        specs = (("palm_mute", "PM"), ("let_ring", "let ring"))
        base_y = max(row_top + int(16 * self.zoom), tab_top - int(18 * self.zoom))
        drawn_lane = 0
        for technique, label in specs:
            spans = self._technique_spans(beat_positions, technique)
            if not spans:
                continue
            y = base_y - int(drawn_lane * 12 * self.zoom)
            for start_x, end_x in spans:
                self._draw_dashed_span_text(painter, label, start_x, end_x, y, QColor("#666666"))
            drawn_lane += 1

    def _technique_spans(self, beat_positions: list[tuple[int, BeatData]], technique: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        start_x: int | None = None
        end_x: int | None = None
        expected_next: int | None = None
        for x, beat in beat_positions:
            has_technique = any(technique in getattr(note, "techniques", ()) for note in beat.notes)
            is_contiguous = expected_next is None or abs(beat.start_in_measure - expected_next) <= 1
            if has_technique and (start_x is None or is_contiguous):
                if start_x is None:
                    start_x = x
                end_x = x + int(22 * self.zoom)
            else:
                if start_x is not None and end_x is not None:
                    spans.append((start_x, end_x))
                start_x = x if has_technique else None
                end_x = x + int(22 * self.zoom) if has_technique else None
            expected_next = beat.start_in_measure + beat.duration_ticks
        if start_x is not None and end_x is not None:
            spans.append((start_x, end_x))
        return spans

    def _draw_note_relationships(
        self,
        painter: QPainter,
        positions: list[tuple[int, int, object, BeatData]],
        note_metrics: QFontMetrics,
    ) -> None:
        by_string: dict[int, list[tuple[int, int, object, BeatData]]] = {}
        for position in positions:
            _x, _y, note, _beat = position
            by_string.setdefault(note.string, []).append(position)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        relation_pen = QPen(QColor("#202633"), max(1, int(1.25 * self.zoom)))
        relation_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(relation_pen)

        for string_positions in by_string.values():
            ordered = sorted(string_positions, key=lambda item: (item[3].start_in_measure, item[0]))
            for left, right in zip(ordered, ordered[1:]):
                left_x, left_y, left_note, _left_beat = left
                right_x, right_y, right_note, _right_beat = right
                if right_x <= left_x:
                    continue
                left_techniques = set(left_note.techniques)
                right_techniques = set(right_note.techniques)

                if "slide" in left_techniques:
                    self._draw_slide_mark_before_note(painter, right_note, right_x, right_y, note_metrics)
                if "tie" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "hammer_on" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
                elif "pull_off" in right_techniques:
                    self._draw_slur_connection(painter, left_x, left_y, right_x, right_y, "")
        painter.restore()

    def _draw_slur_connection(
        self,
        painter: QPainter,
        left_x: int,
        left_y: int,
        right_x: int,
        right_y: int,
        label: str,
    ) -> None:
        start_x = left_x + int(5 * self.zoom)
        end_x = right_x - int(5 * self.zoom)
        if end_x <= start_x:
            return
        base_y = min(left_y, right_y) - int(5 * self.zoom)
        height = max(int(4 * self.zoom), min(int(7 * self.zoom), (end_x - start_x) // 7))
        path = QPainterPath(QPointF(start_x, base_y))
        path.quadTo(QPointF((start_x + end_x) / 2, base_y - height), QPointF(end_x, base_y))
        pen = painter.pen()
        pen.setWidth(max(1, int(1.35 * self.zoom)))
        painter.setPen(pen)
        painter.drawPath(path)
        if label:
            font = QFont("Segoe UI", max(6, int(7 * self.zoom)), QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            label_rect = QRect(
                int((start_x + end_x) / 2) - metrics.horizontalAdvance(label) // 2,
                base_y - height - metrics.height() + 2,
                metrics.horizontalAdvance(label) + 2,
                metrics.height(),
            )
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _draw_slide_connection(
        self,
        painter: QPainter,
        left_x: int,
        left_y: int,
        right_x: int,
        right_y: int,
        left_fret: int,
        right_fret: int,
    ) -> None:
        start_x = left_x + int(8 * self.zoom)
        end_x = right_x - int(8 * self.zoom)
        if end_x <= start_x:
            return
        offset = int(4 * self.zoom)
        if right_fret >= left_fret:
            painter.drawLine(start_x, left_y + offset, end_x, right_y - offset)
        else:
            painter.drawLine(start_x, left_y - offset, end_x, right_y + offset)

    def _draw_slide_out(self, painter: QPainter, x: int, y: int) -> None:
        painter.drawLine(x + int(8 * self.zoom), y + int(4 * self.zoom), x + int(22 * self.zoom), y - int(7 * self.zoom))

    def _draw_beat_technique_symbols(
        self,
        painter: QPainter,
        beat: BeatData,
        x: int,
        row_top: int,
        tab_top: int,
    ) -> None:
        techniques = self._beat_techniques(beat)
        techniques = [technique for technique in techniques if technique in {"palm_mute", "let_ring"}]
        if not techniques:
            return

        symbol_y = max(row_top + int(16 * self.zoom), tab_top - int(18 * self.zoom))
        slot = max(42, int(54 * self.zoom))
        limited = techniques[:5]
        start_x = x - ((len(limited) - 1) * slot) // 2
        for index, technique in enumerate(limited):
            self._draw_technique_symbol(painter, technique, start_x + (index * slot), symbol_y)

    def _beat_techniques(self, beat: BeatData) -> list[str]:
        priority = {
            "palm_mute": 0,
            "let_ring": 1,
            "bend": 2,
            "release_bend": 3,
            "vibrato": 9,
            "staccato": 10,
            "accent": 11,
            "harmonic": 12,
            "tapping": 13,
            "trill": 14,
            "tremolo_picking": 15,
        }
        found: set[str] = set()
        for note in beat.notes:
            found.update(note.techniques)
        found.discard("dead_note")
        found.discard("ghost_note")
        found.difference_update({"slide", "hammer_on", "pull_off", "legato", "tie"})
        if "release_bend" in found:
            found.discard("bend")
        return sorted(found, key=lambda item: (priority.get(item, 99), item))

    def _beat_bend_semitones(self, beat: BeatData) -> float | None:
        values = [note.bend_semitones for note in beat.notes if note.bend_semitones is not None]
        return max(values) if values else None

    def _draw_note_technique_symbols(
        self,
        painter: QPainter,
        note: object,
        x: int,
        y: int,
        note_metrics: QFontMetrics,
    ) -> None:
        techniques = set(getattr(note, "techniques", ()))
        visible = {
            "accent",
            "bend",
            "harmonic",
            "release_bend",
            "staccato",
            "tapping",
            "tremolo_picking",
            "trill",
            "vibrato",
        }
        if not techniques.intersection(visible):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#161616")
        gray = QColor("#535353")
        pen = QPen(color, max(1, int(1.15 * self.zoom)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        text_width = note_metrics.horizontalAdvance(tab_note_text(note)) + int(6 * self.zoom)
        text_half = max(5, text_width // 2)
        lane = 0

        def next_above_y() -> int:
            nonlocal lane
            symbol_y = y - int((17 + (lane * 11)) * self.zoom)
            lane += 1
            return symbol_y

        if "harmonic" in techniques:
            self._draw_harmonic_symbol(painter, x - text_half - int(5 * self.zoom), y)

        if "bend" in techniques or "release_bend" in techniques:
            self._draw_bend_symbol(
                painter,
                x + text_half + int(3 * self.zoom),
                y,
                release="release_bend" in techniques,
                semitones=getattr(note, "bend_semitones", None),
            )

        if "tapping" in techniques:
            self._draw_tapping_symbol(painter, x, next_above_y())
        if "trill" in techniques:
            self._draw_trill_symbol(painter, x, next_above_y())
        if "vibrato" in techniques:
            vibrato_pen = QPen(gray, max(2, int(2.4 * self.zoom)))
            vibrato_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            vibrato_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(vibrato_pen)
            self._draw_wavy_symbol(
                painter,
                x + text_half + int(3 * self.zoom),
                next_above_y(),
                int(24 * self.zoom),
                max(1, int(1.8 * self.zoom)),
            )
            painter.setPen(pen)
        if "accent" in techniques:
            self._draw_accent_symbol(painter, x, next_above_y())
        if "staccato" in techniques:
            self._draw_staccato_symbol(painter, x, next_above_y())
        if "tremolo_picking" in techniques:
            self._draw_tremolo_symbol(painter, x + text_half + int(6 * self.zoom), y + int(14 * self.zoom))

        painter.restore()

    def _draw_slide_mark_before_note(
        self,
        painter: QPainter,
        note: object,
        x: int,
        y: int,
        note_metrics: QFontMetrics,
    ) -> None:
        text_width = note_metrics.horizontalAdvance(tab_note_text(note)) + int(6 * self.zoom)
        text_half = max(5, text_width // 2)
        self._draw_slide_mark(painter, x - text_half - int(5 * self.zoom), y)

    def _draw_slide_mark(self, painter: QPainter, x: int, y: int) -> None:
        length = max(8, int(10 * self.zoom))
        height = max(8, int(11 * self.zoom))
        painter.drawLine(x - length, y + height // 2, x, y - height // 2)

    def _draw_technique_symbol(
        self,
        painter: QPainter,
        technique: str,
        x: int,
        y: int,
        bend_semitones: float | None = None,
    ) -> None:
        painter.save()
        color = QColor("#161616")
        accent = QColor("#666666")
        pen_width = max(1, int(1.1 * self.zoom))
        painter.setPen(QPen(color, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if technique == "bend":
            self._draw_bend_symbol(painter, x, y, release=False, semitones=bend_semitones)
        elif technique == "release_bend":
            self._draw_bend_symbol(painter, x, y, release=True, semitones=bend_semitones)
        elif technique == "vibrato":
            vibrato_pen = QPen(accent, max(2, int(2.4 * self.zoom)))
            vibrato_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            vibrato_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(vibrato_pen)
            self._draw_wavy_symbol(painter, x - int(8 * self.zoom), y, int(22 * self.zoom), max(1, int(1.8 * self.zoom)))
        elif technique == "staccato":
            self._draw_staccato_symbol(painter, x, y)
        elif technique == "accent":
            self._draw_accent_symbol(painter, x, y)
        elif technique == "harmonic":
            self._draw_harmonic_symbol(painter, x, y)
        elif technique == "tapping":
            self._draw_tapping_symbol(painter, x, y)
        elif technique == "trill":
            self._draw_trill_symbol(painter, x, y)
        elif technique == "tremolo_picking":
            self._draw_tremolo_symbol(painter, x, y)
        elif technique == "palm_mute":
            self._draw_dashed_text_symbol(painter, "P.M.", x, y, accent)
        elif technique == "let_ring":
            self._draw_dashed_text_symbol(painter, "let ring", x, y, accent)
        painter.restore()

    def _draw_bend_symbol(
        self,
        painter: QPainter,
        x: int,
        y: int,
        release: bool,
        semitones: float | None = None,
    ) -> None:
        scale = self.zoom * 0.5
        pen = QPen(painter.pen().color(), max(1, int(1.15 * scale)))
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        start = QPointF(x, y - int(2 * scale))
        peak = QPointF(x + int(37 * scale), y - int(43 * scale))
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(x + int(20 * scale), y - int(2 * scale)),
            QPointF(x + int(37 * scale), y - int(18 * scale)),
            peak,
        )
        painter.drawPath(path)
        self._draw_bend_arrow_triangle(painter, peak, up=True, scale=scale)

        if release:
            end = QPointF(x + int(72 * scale), y - int(16 * scale))
            release_path = QPainterPath(peak)
            release_path.cubicTo(
                QPointF(x + int(59 * scale), y - int(43 * scale)),
                QPointF(x + int(72 * scale), y - int(33 * scale)),
                end,
            )
            painter.drawPath(release_path)
            self._draw_bend_arrow_triangle(painter, end, up=False, scale=scale)

        label = self._bend_amount_label(semitones)
        if label:
            font = QFont("Segoe UI", max(5, int(6 * scale)), QFont.Weight.DemiBold)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            label_x = int(peak.x()) - metrics.horizontalAdvance(label) // 2
            label_y = int(peak.y()) - metrics.height() - int(2 * scale)
            painter.drawText(
                QRect(label_x, label_y, metrics.horizontalAdvance(label) + 2, metrics.height()),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )

    def _draw_bend_arrow_triangle(self, painter: QPainter, tip: QPointF, up: bool, scale: float | None = None) -> None:
        scale = self.zoom if scale is None else scale
        size = max(2, int(4.1 * scale))
        half = max(2, int(4 * scale))
        path = QPainterPath(tip)
        if up:
            path.lineTo(QPointF(tip.x() - half, tip.y() + size))
            path.lineTo(QPointF(tip.x() + half, tip.y() + size))
        else:
            path.lineTo(QPointF(tip.x() - half, tip.y() - size))
            path.lineTo(QPointF(tip.x() + half, tip.y() - size))
        path.closeSubpath()
        color = painter.pen().color()
        old_brush = painter.brush()
        old_pen = painter.pen()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _draw_harmonic_symbol(self, painter: QPainter, x: int, y: int) -> None:
        size = max(4, int(4.2 * self.zoom))
        path = QPainterPath(QPointF(x, y - size))
        path.lineTo(QPointF(x + size, y))
        path.lineTo(QPointF(x, y + size))
        path.lineTo(QPointF(x - size, y))
        path.closeSubpath()
        old_pen = painter.pen()
        old_brush = painter.brush()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b0b2b6"))
        painter.drawPath(path)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _draw_accent_symbol(self, painter: QPainter, x: int, y: int) -> None:
        span = max(5, int(6 * self.zoom))
        rise = max(2, int(3 * self.zoom))
        old_pen = painter.pen()
        accent_pen = QPen(QColor("#161616"), max(1, int(1.15 * self.zoom)))
        accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        accent_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(accent_pen)
        painter.drawLine(x - span, y - rise, x + span, y)
        painter.drawLine(x - span, y + rise, x + span, y)
        painter.setPen(old_pen)

    def _draw_staccato_symbol(self, painter: QPainter, x: int, y: int) -> None:
        radius = max(2, int(2.4 * self.zoom))
        old_brush = painter.brush()
        old_pen = painter.pen()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#161616"))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.setPen(old_pen)
        painter.setBrush(old_brush)

    def _bend_amount_label(self, semitones: float | None) -> str:
        if semitones is None or semitones <= 0:
            return ""
        fraction = Fraction(semitones / 2).limit_denominator(4)
        whole = fraction.numerator // fraction.denominator
        remainder = fraction - whole
        if remainder == 0:
            return str(whole)
        text = f"{remainder.numerator}/{remainder.denominator}"
        return f"{whole} {text}" if whole else text

    def _draw_wavy_symbol(self, painter: QPainter, x: int, y: int, width: int, amplitude: int) -> None:
        path = QPainterPath(QPointF(x, y))
        steps = max(6, int(width / max(3, int(3.5 * self.zoom))))
        segment = width / steps
        for index in range(steps):
            start_x = x + (index * segment)
            mid_x = start_x + segment / 2
            end_x = start_x + segment
            direction = -1 if index % 2 == 0 else 1
            path.quadTo(QPointF(mid_x, y + (direction * amplitude)), QPointF(end_x, y))
        painter.drawPath(path)

    def _draw_text_symbol(self, painter: QPainter, text: str, x: int, y: int) -> QRect:
        font = QFont("Segoe UI", max(7, int(8 * self.zoom)), QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        rect = QRect(
            x - metrics.horizontalAdvance(text) // 2,
            y - metrics.height() // 2,
            metrics.horizontalAdvance(text) + 2,
            metrics.height(),
        )
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        return rect

    def _draw_tapping_symbol(self, painter: QPainter, x: int, y: int) -> None:
        font = QFont("Segoe UI", max(8, int(9 * self.zoom)), QFont.Weight.Bold)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = "T"
        painter.drawText(
            QRect(
                x - metrics.horizontalAdvance(text) // 2,
                y - metrics.height() // 2,
                metrics.horizontalAdvance(text) + 2,
                metrics.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    def _draw_tremolo_symbol(self, painter: QPainter, x: int, y: int) -> None:
        old_pen = painter.pen()
        tremolo_pen = QPen(QColor("#a5a7ab"), max(1, int(1.05 * self.zoom)))
        tremolo_pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        painter.setPen(tremolo_pen)
        span = max(8, int(10 * self.zoom))
        offset = max(3, int(4 * self.zoom))
        for index in range(3):
            yy = y - offset + (index * offset)
            painter.drawLine(x - span // 2, yy + offset // 2, x + span // 2, yy - offset // 2)
        painter.setPen(old_pen)

    def _draw_trill_symbol(self, painter: QPainter, x: int, y: int) -> None:
        rect = self._draw_text_symbol(painter, "tr", x - int(5 * self.zoom), y)
        self._draw_wavy_symbol(
            painter,
            rect.right() + int(2 * self.zoom),
            y,
            int(19 * self.zoom),
            int(3 * self.zoom),
        )

    def _draw_dashed_text_symbol(self, painter: QPainter, text: str, x: int, y: int, color: QColor) -> None:
        painter.setPen(QPen(color, max(1, int(1.2 * self.zoom))))
        rect = self._draw_text_symbol(painter, text, x, y)
        dash_pen = QPen(color, max(1, int(1 * self.zoom)))
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(dash_pen)
        line_y = y + int(5 * self.zoom)
        painter.drawLine(rect.right() + int(3 * self.zoom), line_y, rect.right() + int(46 * self.zoom), line_y)

    def _draw_dashed_span_text(self, painter: QPainter, text: str, start_x: int, end_x: int, y: int, color: QColor) -> None:
        painter.save()
        painter.setPen(QPen(color, max(1, int(1.05 * self.zoom))))
        rect = self._draw_text_symbol(painter, text, start_x, y)
        dash_pen = QPen(color, max(1, int(1 * self.zoom)))
        dash_pen.setStyle(Qt.PenStyle.DashLine)
        dash_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(dash_pen)
        line_y = y + int(5 * self.zoom)
        line_start = rect.right() + int(4 * self.zoom)
        line_end = max(line_start + int(12 * self.zoom), end_x)
        painter.drawLine(line_start, line_y, line_end, line_y)
        painter.restore()

    def _draw_playback_cursor(
        self,
        painter: QPainter,
        layout: _MeasureLayout,
        measure: MeasureData,
        tab_left: int,
        tab_right: int,
        tab_top: int,
        string_gap: int,
    ) -> None:
        if self.playback_tick is None:
            return
        measure_start = measure.start_tick
        measure_end = measure.start_tick + measure.length_ticks
        if self.playback_tick < measure_start or self.playback_tick > measure_end:
            return
        ratio = (self.playback_tick - measure_start) / max(1, measure.length_ticks)
        x = tab_left + int(max(0.0, min(1.0, ratio)) * max(1, tab_right - tab_left))
        painter.setPen(QPen(QColor("#d92727"), max(2, int(2 * self.zoom))))
        painter.drawLine(x, tab_top - int(18 * self.zoom), x, tab_top + ((len(self.song.track.string_names) - 1) * string_gap) + int(12 * self.zoom) if self.song else layout.rect.bottom())

    def _tab_geometry(self, rect: QRect) -> tuple[int, int, int, int]:
        top = rect.top() + int(54 * self.zoom)
        string_gap = max(10, int(13 * self.zoom))
        return rect.left(), rect.right(), top, string_gap

    def _rebuild_layout(self) -> None:
        self._measure_layouts = []
        if self.song is None:
            self._content_size = QSize(max(360, self.width()), 260)
            self.setMinimumWidth(0)
            self.setMinimumHeight(self._content_size.height())
            self.updateGeometry()
            return

        margin = int(12 * self.zoom)
        label_width = int(42 * self.zoom)
        system_gap = int(24 * self.zoom)
        available_width = max(260, self.width() - (margin * 2))
        system_left = margin + label_width
        system_right = margin + available_width
        system_width = max(160, system_right - system_left)
        x = system_left
        y = margin
        string_count = max(1, len(self.song.track.string_pitches))
        row_height = int((88 + (string_count * 15)) * self.zoom)
        for index, measure in enumerate(self.song.track.measures):
            note_slots = max(2, sum(1 for beat in measure.beats if beat.notes))
            width = int(max(118 * self.zoom, 34 * self.zoom + note_slots * 34 * self.zoom))
            width = min(width, system_width)
            if x > system_left and x + width > system_right:
                x = system_left
                y += row_height + system_gap
            self._measure_layouts.append(_MeasureLayout(index, QRect(x, y, width, row_height)))
            x += width
        self._content_size = QSize(max(360, self.width()), max(240, y + row_height + margin))
        self.setMinimumWidth(0)
        self.setMinimumHeight(self._content_size.height())
        self.updateGeometry()

    def _row_groups(self) -> list[list[_MeasureLayout]]:
        rows: list[list[_MeasureLayout]] = []
        for layout in self._measure_layouts:
            if not rows or rows[-1][0].rect.top() != layout.rect.top():
                rows.append([layout])
            else:
                rows[-1].append(layout)
        return rows

    def _is_row_start(self, layout: _MeasureLayout) -> bool:
        return not any(
            other.index < layout.index and other.rect.top() == layout.rect.top()
            for other in self._measure_layouts
        )

