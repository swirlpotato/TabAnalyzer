"""Fretboard and scale visualization widgets."""

from __future__ import annotations

from .common import *

class FretboardWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.measure: MeasureData | None = None
        self.segment: SegmentData | None = None
        self.candidate: Candidate | None = None
        self.kind = "scale"
        self.playback_tick: int | None = None
        self.selected_scale_block_index: int | None = None
        self._scale_block_button_hits: list[tuple[QRect, int]] = []
        self.setFixedHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.measure = None
        self.segment = None
        self.candidate = None
        self.playback_tick = None
        self.selected_scale_block_index = None
        self._scale_block_button_hits = []
        self.update()

    def set_selection(
        self,
        measure: MeasureData | None,
        candidate: Candidate | None,
        kind: str,
        segment: SegmentData | None = None,
    ) -> None:
        self.measure = measure
        self.segment = segment
        self.candidate = candidate
        self.kind = kind
        self.selected_scale_block_index = None
        self.update()

    def set_playback_tick(self, tick: object) -> None:
        self.playback_tick = int(tick) if tick is not None else None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, block_index in self._scale_block_button_hits:
            if rect.contains(position):
                self.selected_scale_block_index = block_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._draw_fretboard(painter)

    def _draw_fretboard(self, painter: QPainter) -> None:
        self._scale_block_button_hits = []
        if self.song is None:
            painter.setPen(QColor("#657083"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Fretboard"))
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        scale_blocks = self._current_scale_blocks(fret_count)
        show_scale_buttons = self.kind == "scale" and len(scale_blocks) > 1
        left = 56
        right = 28
        top = 44
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        title = self._selection_title()
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(16, 10, self.width() - 32, 24), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        self._draw_scale_blocks(painter, board, fret_count, fret_gap, scale_blocks)

        painter.setPen(QPen(QColor("#9aa6b7"), 1))
        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_candidate_notes(painter, board, fret_count, fret_gap, string_gap)
        self._draw_measure_fingering(painter, board, fret_count, fret_gap, string_gap)
        self._draw_current_playback_notes(painter, board, fret_count, fret_gap, string_gap)
        self._draw_scale_block_buttons(painter, board, scale_blocks)

    def _draw_scale_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.kind != "scale" or self.measure is None or self.candidate is None or self.song is None:
            return

        if not blocks:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        active_block_index = self._active_scale_block_index(blocks)
        visible_blocks = blocks
        if len(blocks) > 1 and active_block_index is not None:
            visible_blocks = tuple(block for block in blocks if block.index == active_block_index)
        spans = scale_block_spans(
            visible_blocks,
            self.candidate,
            self.song.track.string_pitches,
            fret_count,
        )
        if not spans:
            return

        row_height = max(14, min(30, int(string_gap * 0.58)))
        block_color = QColor(250, 204, 21, 165)

        painter.setPen(Qt.PenStyle.NoPen)
        for span in spans:
            painter.setBrush(block_color)
            painter.drawRoundedRect(
                self._scale_span_rect(board, fret_gap, string_gap, span.string_index, span.start_fret, span.end_fret, row_height),
                5,
                5,
            )

    def _current_scale_blocks(self, fret_count: int) -> tuple[ScaleBlock, ...]:
        if self.kind != "scale" or self.measure is None or self.candidate is None or self.song is None:
            return ()
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        notes = tuple(note for note in notes if 0 <= note.fret <= fret_count)
        if not notes:
            return ()
        return infer_scale_blocks(
            notes,
            self.candidate,
            self.song.track.string_pitches,
            fret_count,
        )

    def _active_scale_block_index(self, blocks: tuple[ScaleBlock, ...]) -> int | None:
        if not blocks:
            return None
        block_indexes = {block.index for block in blocks}
        if self.selected_scale_block_index in block_indexes:
            return self.selected_scale_block_index
        return max(
            blocks,
            key=lambda block: (
                self._scale_block_played_note_count(block),
                len(block.played_positions),
                -block.first_order,
                -block.start_fret,
                -block.index,
            ),
        ).index

    def _scale_block_played_note_count(self, block: ScaleBlock) -> int:
        if self.measure is None:
            return len(block.played_positions)
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        positions = set(block.played_positions)
        return sum(1 for note in notes if (int(note.string) - 1, int(note.fret)) in positions)

    def _draw_scale_block_buttons(
        self,
        painter: QPainter,
        board: QRect,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        self._scale_block_button_hits = []
        if self.kind != "scale" or len(blocks) <= 1:
            return

        active_block_index = self._active_scale_block_index(blocks)
        ordered = sorted(blocks, key=lambda block: (block.start_fret, block.end_fret, block.first_order, block.index))
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        for display_number, block in enumerate(ordered, start=1):
            text = f"{display_number}: {block.start_fret}-{block.end_fret}"
            width = max(54, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = block.index == active_block_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._scale_block_button_hits.append((rect, block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _scale_block_overlap_rects(
        self,
        spans: tuple[ScaleSpan, ...],
        board: QRect,
        fret_gap: float,
        string_gap: float,
        row_height: int,
    ) -> list[QRect]:
        overlap_rects: list[QRect] = []
        for left_index, left_span in enumerate(spans):
            for right_span in spans[left_index + 1:]:
                if left_span.block_index == right_span.block_index or left_span.string_index != right_span.string_index:
                    continue
                overlap_start = max(left_span.start_fret, right_span.start_fret)
                overlap_end = min(left_span.end_fret, right_span.end_fret)
                if overlap_start > overlap_end:
                    continue
                overlap_rects.append(
                    self._scale_span_rect(
                        board,
                        fret_gap,
                        string_gap,
                        left_span.string_index,
                        overlap_start,
                        overlap_end,
                        row_height,
                    )
                )
        return overlap_rects

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)

    def _draw_candidate_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.candidate is None or self.song is None:
            return

        pcs = set(self.candidate.pitch_classes)
        color = QColor("#f9a8d4") if self.kind == "scale" else QColor("#2468d8")
        root_color = QColor("#be185d") if self.kind == "scale" else QColor("#174ea6")
        missing_chord_root = self.kind == "chord" and not self._root_is_played()

        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for fret in range(fret_count + 1):
                pc = (open_midi + fret) % 12
                if pc not in pcs:
                    continue
                x = int(board.left() + (fret * fret_gap if fret == 0 else (fret - 0.5) * fret_gap))
                is_root = pc == self.candidate.root_pc
                dot_color = root_color if is_root else color
                text_color = QColor("#ffffff") if is_root or self.kind != "scale" else QColor("#3b1426")
                if is_root and missing_chord_root:
                    dot_color = QColor("#174ea6")
                    text_color = QColor("#ffffff")
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(dot_color)
                radius = 12 if is_root else 10
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(text_color)
                label = self._fretboard_degree_label((pc - self.candidate.root_pc) % 12, pc)
                painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, label)

    def _draw_measure_fingering(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.measure is None or self.song is None:
            return

        notes = self.segment.notes if self.segment is not None else self.measure.notes
        played_by_position: dict[tuple[int, int], object] = {}
        for note in notes:
            played_by_position.setdefault((note.string, note.fret), note)
        if not played_by_position:
            return

        candidate_pcs = set(self.candidate.pitch_classes) if self.candidate is not None else set()
        inside_fill = QColor("#16a34a")
        inside_border = QColor("#0f6f34")
        outside_fill = QColor("#f9a8d4")
        outside_border = QColor("#be185d")
        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for (string_number, fret), note in sorted(played_by_position.items()):
            if fret < 0 or fret > fret_count:
                continue
            string_index = string_number - 1
            if string_index < 0 or string_index >= len(self.song.track.string_pitches):
                continue

            inside_candidate = self.candidate is None or (note.midi % 12) in candidate_pcs
            x = int(board.left() + (fret * fret_gap if fret == 0 else (fret - 0.5) * fret_gap))
            y = int(board.top() + string_index * string_gap)
            show_degree = self.candidate is not None and self.kind in {"scale", "chord"}
            radius = 15 if show_degree else 13
            interval = (note.midi - self.candidate.root_pc) % 12 if show_degree else 0
            is_scale_root = show_degree and self.kind == "scale" and interval == 0
            is_chord_root = show_degree and self.kind == "chord" and interval == 0
            if is_chord_root:
                fill = QColor("#dc2626")
                border = QColor("#991b1b")
            elif is_scale_root:
                fill = QColor("#dc2626")
                border = QColor("#991b1b")
            else:
                fill = inside_fill if inside_candidate else outside_fill
                border = inside_border if inside_candidate else outside_border
            painter.setPen(QPen(border, 2))
            painter.setBrush(fill)
            painter.drawEllipse(QPoint(x, y), radius, radius)
            painter.setPen(QColor("#111827") if not inside_candidate and not is_scale_root and not is_chord_root else QColor("#ffffff"))
            circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
            if show_degree:
                painter.setFont(fret_font)
                painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, str(fret))
                painter.setFont(degree_font)
                degree = self._fretboard_degree_label(interval, note.midi % 12)
                painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)
            else:
                painter.setFont(fret_font)
                painter.drawText(circle_rect, Qt.AlignmentFlag.AlignCenter, str(fret))

    def _current_playback_notes(self) -> tuple[object, ...]:
        if self.measure is None or self.playback_tick is None:
            return ()
        measure_start = self.measure.start_tick
        measure_end = self.measure.start_tick + self.measure.length_ticks
        if not (measure_start <= self.playback_tick < measure_end):
            return ()
        return tuple(
            note
            for note in self.measure.notes
            if note.start_tick <= self.playback_tick < note.start_tick + max(1, note.duration_ticks)
        )

    def _draw_current_playback_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
    ) -> None:
        if self.song is None:
            return
        notes = self._current_playback_notes()
        if not notes:
            return

        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        for note in notes:
            if note.fret < 0 or note.fret > fret_count:
                continue
            string_index = int(note.string) - 1
            if string_index < 0 or string_index >= len(self.song.track.string_pitches):
                continue
            x = self._fret_center_x(board, fret_gap, int(note.fret))
            y = int(board.top() + string_index * string_gap)
            radius = 20
            painter.setPen(QPen(QColor("#f5d0fe"), 3))
            painter.setBrush(QColor("#7e22ce"))
            painter.drawEllipse(QPoint(x, y), radius, radius)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, str(note.fret))

    def _root_is_played(self) -> bool:
        if self.kind != "chord" or self.candidate is None or self.measure is None:
            return False
        notes = self.segment.notes if self.segment is not None else self.measure.notes
        return any(note.midi % 12 == self.candidate.root_pc for note in notes)

    def _fretboard_degree_label(self, interval: int, note_pc: int) -> str:
        if self.kind == "chord":
            return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]
        if self.candidate is None:
            return ""
        return interval_name(self.candidate.root_pc, note_pc)

    def _selection_title(self) -> str:
        if self.candidate is None:
            return f"{self.song.title} - {self.song.track.name}" if self.song else tr("Fretboard")
        measure_text = f"M{self.measure.number}" if self.measure else ""
        if self.measure is not None and self.segment is not None:
            start_percent = round((self.segment.start_in_measure / self.measure.length_ticks) * 100)
            end_percent = round((self.segment.end_in_measure / self.measure.length_ticks) * 100)
            measure_text = f"{measure_text} {start_percent}-{end_percent}%"
        kind_text = tr("Scale") if self.kind == "scale" else tr("Chord")
        prefer_flats = self.song.track.prefer_flats if self.song is not None else None
        notes = " ".join(pitch_class_name(pc, prefer_flats) for pc in self.candidate.pitch_classes)
        name = candidate_display_name(self.candidate, prefer_flats)
        return f"{measure_text}  {kind_text}: {name} ({self.candidate.score})  {notes}"


class ScalePositionWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.root_pc = 0
        self.scale_name = SCALE_POSITION_PATTERNS[0][0]
        self.scale_intervals = SCALE_POSITION_PATTERNS[0][1]
        self.selected_scale_block_index: int | None = None
        self._scale_block_button_hits: list[tuple[QRect, int]] = []
        self.setMinimumHeight(244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(960, 260)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_scale_block_index = None
        self._scale_block_button_hits = []
        self.update()

    def set_scale(self, root_pc: int, scale_name: str) -> None:
        self.root_pc = root_pc % 12
        self.scale_name = scale_name
        self.scale_intervals = SCALE_POSITION_PATTERN_BY_NAME.get(scale_name, self.scale_intervals)
        self.selected_scale_block_index = None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, block_index in self._scale_block_button_hits:
            if rect.contains(position):
                self.selected_scale_block_index = block_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._scale_block_button_hits = []
        if self.song is None:
            self._draw_empty(painter)
            return
        self._draw_fretboard(painter)

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Scale view"))

    def _draw_fretboard(self, painter: QPainter) -> None:
        if self.song is None:
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        scale_blocks = self._scale_blocks(fret_count)
        left = 56
        right = 28
        top = 42
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            QRect(16, 10, self.width() - 32, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title(),
        )

        self._draw_scale_blocks(painter, board, fret_count, fret_gap, scale_blocks)

        painter.setPen(QPen(QColor("#9aa6b7"), 1))
        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_scale_notes(painter, board, fret_count, fret_gap, string_gap, scale_blocks)
        self._draw_scale_block_buttons(painter, board, scale_blocks)

    def _title(self) -> str:
        prefer_flats = self.song.track.prefer_flats if self.song is not None else None
        root = SCALE_POSITION_ROOT_LABELS.get(self.root_pc, pitch_class_name(self.root_pc, prefer_flats))
        scale = SCALE_POSITION_DISPLAY_NAMES.get(self.scale_name, self.scale_name)
        notes = " ".join(
            pitch_class_name((self.root_pc + interval) % 12, prefer_flats)
            for interval in self.scale_intervals
        )
        return f"{root} {scale}   {notes}"

    def _draw_scale_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.song is None:
            return

        pitch_classes = {(self.root_pc + interval) % 12 for interval in self.scale_intervals}
        active_block_index = self._active_scale_block_index(blocks)
        active_blocks = tuple(block for block in blocks if block.index == active_block_index)
        inactive_blocks = tuple(block for block in blocks if block.index != active_block_index)
        candidate = self._candidate()

        inactive_positions = self._scale_note_positions(
            inactive_blocks,
            candidate,
            pitch_classes,
            fret_count,
        )
        active_positions = self._scale_note_positions(
            active_blocks,
            candidate,
            pitch_classes,
            fret_count,
        )
        if not active_positions and not inactive_positions:
            active_positions = {
                (string_index, fret)
                for string_index, open_midi in enumerate(self.song.track.string_pitches)
                for fret in range(fret_count + 1)
                if (open_midi + fret) % 12 in pitch_classes
            }

        self._draw_scale_note_positions(
            painter,
            board,
            fret_gap,
            string_gap,
            inactive_positions - active_positions,
            root_color=QColor("#174ea6"),
            note_color=QColor("#bfdbfe"),
            root_text_color=QColor("#ffffff"),
            note_text_color=QColor("#17345d"),
            root_radius=10,
            note_radius=8,
        )
        self._draw_scale_note_positions(
            painter,
            board,
            fret_gap,
            string_gap,
            active_positions,
            root_color=QColor("#8f1d18"),
            note_color=QColor("#cb3a31"),
            root_text_color=QColor("#ffffff"),
            note_text_color=QColor("#ffffff"),
            root_radius=11,
            note_radius=9,
        )

    def _scale_note_positions(
        self,
        blocks: tuple[ScaleBlock, ...],
        candidate: Candidate,
        pitch_classes: set[int],
        fret_count: int,
    ) -> set[tuple[int, int]]:
        if self.song is None or not blocks:
            return set()

        positions: set[tuple[int, int]] = set()
        positions_by_block: dict[int, set[tuple[int, int]]] = {}
        for span in scale_block_spans(
            blocks,
            candidate,
            self.song.track.string_pitches,
            fret_count,
        ):
            open_midi = self.song.track.string_pitches[span.string_index]
            for fret in range(span.start_fret, span.end_fret + 1):
                if (open_midi + fret) % 12 in pitch_classes:
                    positions_by_block.setdefault(span.block_index, set()).add((span.string_index, fret))

        for block_positions in positions_by_block.values():
            preferred_notes = 2 if "pentatonic" in self.scale_name.lower() else 3
            positions.update(
                dedupe_repeated_pitch_positions(
                    block_positions,
                    self.song.track.string_pitches,
                    preferred_notes_per_string=preferred_notes,
                )
            )
        return positions

    def _draw_scale_note_positions(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        positions: set[tuple[int, int]],
        root_color: QColor,
        note_color: QColor,
        root_text_color: QColor,
        note_text_color: QColor,
        root_radius: int,
        note_radius: int,
    ) -> None:
        if self.song is None or not positions:
            return

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for _position_string, fret in sorted(position for position in positions if position[0] == string_index):
                pc = (open_midi + fret) % 12
                x = self._fret_center_x(board, fret_gap, fret)
                is_root = pc == self.root_pc
                radius = root_radius if is_root else note_radius
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(root_color if is_root else note_color)
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(root_text_color if is_root else note_text_color)
                painter.drawText(
                    QRect(x - radius, y - radius, radius * 2, radius * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    interval_name(self.root_pc, pc),
                )

    def _candidate(self) -> Candidate:
        root = SCALE_POSITION_ROOT_LABELS.get(self.root_pc, pitch_class_name(self.root_pc))
        return Candidate(
            kind="scale",
            name=f"{root} {self.scale_name}",
            root_pc=self.root_pc,
            intervals=self.scale_intervals,
            score=100,
            matched_notes=0,
            total_notes=0,
            outside_notes=0,
        )

    def _scale_blocks(self, fret_count: int) -> tuple[ScaleBlock, ...]:
        if self.song is None:
            return ()
        return generate_scale_position_blocks(
            self._candidate(),
            self.song.track.string_pitches,
            fret_count,
        )

    def _visible_scale_blocks(self, blocks: tuple[ScaleBlock, ...]) -> tuple[ScaleBlock, ...]:
        if not blocks:
            return ()
        active_block_index = self._active_scale_block_index(blocks)
        if active_block_index is None:
            return ()
        return tuple(block for block in blocks if block.index == active_block_index)

    def _active_scale_block_index(self, blocks: tuple[ScaleBlock, ...]) -> int | None:
        if not blocks:
            return None
        block_indexes = {block.index for block in blocks}
        if self.selected_scale_block_index in block_indexes:
            return self.selected_scale_block_index
        return min(blocks, key=lambda block: (block.start_fret, block.end_fret, block.index)).index

    def _draw_scale_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        if self.song is None or not blocks:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        positions = self._scale_note_positions(
            self._visible_scale_blocks(blocks),
            self._candidate(),
            {(self.root_pc + interval) % 12 for interval in self.scale_intervals},
            fret_count,
        )
        if not positions:
            return

        frets_by_string: dict[int, list[int]] = {}
        for string_index, fret in positions:
            frets_by_string.setdefault(string_index, []).append(fret)

        row_height = max(14, min(30, int(string_gap * 0.58)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(250, 204, 21, 165))
        for string_index, frets in sorted(frets_by_string.items()):
            painter.drawRoundedRect(
                self._scale_span_rect(board, fret_gap, string_gap, string_index, min(frets), max(frets), row_height),
                5,
                5,
            )

    def _draw_scale_block_buttons(
        self,
        painter: QPainter,
        board: QRect,
        blocks: tuple[ScaleBlock, ...],
    ) -> None:
        self._scale_block_button_hits = []
        if len(blocks) <= 1:
            return

        active_block_index = self._active_scale_block_index(blocks)
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        ordered = sorted(blocks, key=lambda block: (block.start_fret, block.end_fret, block.index))
        for display_number, block in enumerate(ordered, start=1):
            text = f"{display_number}: {block.start_fret}-{block.end_fret}"
            width = max(54, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = block.index == active_block_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._scale_block_button_hits.append((rect, block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)


class SongScaleUsageWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.preferred_scale: Candidate | None = None
        self.usages: tuple[ScaleBlockUsage, ...] = ()
        self.visible_count = 5
        self.selected_usage_index: int | None = None
        self._usage_button_hits: list[tuple[QRect, int]] = []
        self.setMinimumHeight(244)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(960, 260)

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.selected_usage_index = None
        self._usage_button_hits = []
        self.preferred_scale = None
        self.usages = ()
        if song is not None:
            self.preferred_scale = infer_preferred_scale(song.track.measures)
            self.usages = infer_song_scale_block_usages(
                song.track.measures,
                song.track.string_pitches,
                song.track.fret_count,
                self.preferred_scale,
            )
        self.update()

    def set_visible_count(self, count: int) -> None:
        self.visible_count = max(1, count)
        if self.selected_usage_index not in {usage.block.index for usage in self._visible_usages()}:
            self.selected_usage_index = None
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, usage_index in self._usage_button_hits:
            if rect.contains(position):
                self.selected_usage_index = usage_index
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#fbfcff"))
        self._usage_button_hits = []
        if self.song is None:
            self._draw_empty(painter, tr("Open a file to show song scale blocks."))
            return
        if self.preferred_scale is None or not self.usages:
            self._draw_empty(painter, tr("No song scale blocks to show."))
            return
        self._draw_fretboard(painter)

    def _draw_empty(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_fretboard(self, painter: QPainter) -> None:
        if self.song is None or self.preferred_scale is None:
            return

        fret_count = min(24, max(12, self.song.track.fret_count))
        usages = self._visible_usages()
        if not usages:
            self._draw_empty(painter, tr("No song scale blocks to show."))
            return

        left = 56
        right = 28
        top = 42
        bottom = 104
        board = self.rect().adjusted(left, top, -right, -bottom)
        if board.width() <= 80 or board.height() <= 80:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / fret_count

        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            QRect(16, 10, self.width() - 32, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._title(),
        )

        self._draw_usage_blocks(painter, board, fret_count, fret_gap, string_gap, usages)

        for fret in range(fret_count + 1):
            x = int(board.left() + (fret * fret_gap))
            pen_width = 4 if fret == 0 else 1
            painter.setPen(QPen(QColor("#5e6878") if fret == 0 else QColor("#c3cbd6"), pen_width))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 10, int(fret_gap * 2), 18),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(0, y - 10, 34, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(midi, string_index, self.song.track.prefer_flats),
            )
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._draw_usage_notes(painter, board, fret_count, fret_gap, string_gap, usages)
        self._draw_usage_buttons(painter, board, usages)

    def _title(self) -> str:
        if self.song is None or self.preferred_scale is None:
            return tr("Song scale view")
        name = candidate_display_name(self.preferred_scale, self.song.track.prefer_flats)
        total = sum(usage.selected_count for usage in self.usages)
        return _trf("Best scale: {name} - selected measures {count}", name=name, count=total)

    def _visible_usages(self) -> tuple[ScaleBlockUsage, ...]:
        return self.usages[: self.visible_count]

    def _active_usage_index(self, usages: tuple[ScaleBlockUsage, ...]) -> int | None:
        if not usages:
            return None
        usage_indexes = {usage.block.index for usage in usages}
        if self.selected_usage_index in usage_indexes:
            return self.selected_usage_index
        return usages[0].block.index

    def _draw_usage_blocks(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        active_usage_index = self._active_usage_index(usages)
        row_height = max(14, min(30, int(string_gap * 0.58)))
        painter.setPen(Qt.PenStyle.NoPen)
        ordered_usages = tuple(usage for usage in usages if usage.block.index != active_usage_index)
        ordered_usages += tuple(usage for usage in usages if usage.block.index == active_usage_index)
        for usage in ordered_usages:
            color = QColor(239, 68, 68, 130) if usage.block.index == active_usage_index else QColor(250, 204, 21, 165)
            self._draw_usage_block_spans(
                painter,
                board,
                fret_count,
                fret_gap,
                string_gap,
                row_height,
                usage,
                color,
            )

    def _draw_usage_block_spans(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        row_height: int,
        usage: ScaleBlockUsage,
        color: QColor,
    ) -> None:
        if self.song is None:
            return
        spans = scale_block_spans(
            (usage.block,),
            usage.candidate,
            self.song.track.string_pitches,
            fret_count,
        )
        painter.setBrush(color)
        for span in spans:
            painter.drawRoundedRect(
                self._scale_span_rect(
                    board,
                    fret_gap,
                    string_gap,
                    span.string_index,
                    span.start_fret,
                    span.end_fret,
                    row_height,
                ),
                5,
                5,
            )

    def _draw_usage_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_count: int,
        fret_gap: float,
        string_gap: float,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        if self.song is None or self.preferred_scale is None:
            return
        positions: set[tuple[int, int]] = set()
        pitch_classes = set(self.preferred_scale.pitch_classes)
        preferred_notes = 2 if "pentatonic" in self.preferred_scale.name.lower() else 3
        for usage in usages:
            block_positions: set[tuple[int, int]] = set()
            for span in scale_block_spans((usage.block,), usage.candidate, self.song.track.string_pitches, fret_count):
                open_midi = self.song.track.string_pitches[span.string_index]
                for fret in range(span.start_fret, span.end_fret + 1):
                    if (open_midi + fret) % 12 in pitch_classes:
                        block_positions.add((span.string_index, fret))
            positions.update(
                dedupe_repeated_pitch_positions(
                    block_positions,
                    self.song.track.string_pitches,
                    preferred_notes_per_string=preferred_notes,
                )
            )
        if not positions:
            return

        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            for _position_string, fret in sorted(position for position in positions if position[0] == string_index):
                pc = (open_midi + fret) % 12
                x = self._fret_center_x(board, fret_gap, fret)
                is_root = pc == self.preferred_scale.root_pc
                radius = 11 if is_root else 9
                painter.setPen(QPen(QColor("#ffffff"), 1))
                painter.setBrush(QColor("#8f1d18") if is_root else QColor("#cb3a31"))
                painter.drawEllipse(QPoint(x, y), radius, radius)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    QRect(x - radius, y - radius, radius * 2, radius * 2),
                    Qt.AlignmentFlag.AlignCenter,
                    interval_name(self.preferred_scale.root_pc, pc),
                )

    def _draw_usage_buttons(
        self,
        painter: QPainter,
        board: QRect,
        usages: tuple[ScaleBlockUsage, ...],
    ) -> None:
        self._usage_button_hits = []
        if not usages:
            return

        active_usage_index = self._active_usage_index(usages)
        font = QFont("Segoe UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        x = board.left()
        y = board.bottom() + 48
        button_height = metrics.height() + 8
        gap = 6

        label = tr("Scale view")
        label_width = metrics.horizontalAdvance(label) + 4
        painter.setPen(QColor("#4b5563"))
        painter.drawText(QRect(x, y, label_width, button_height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        x += label_width + gap

        for display_number, usage in enumerate(usages, start=1):
            text = f"{display_number}: {usage.block.start_fret}-{usage.block.end_fret} ({usage.selected_count})"
            width = max(72, metrics.horizontalAdvance(text) + 18)
            if x + width > board.right() and x > board.left() + label_width + gap:
                x = board.left()
                y += button_height + 5
            rect = QRect(x, y, width, button_height)
            active = usage.block.index == active_usage_index
            painter.setPen(QPen(QColor("#4b5563") if active else QColor("#9ca3af"), 1.0))
            painter.setBrush(QColor("#d1d5db") if active else QColor("#f8fafc"))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor("#111827") if active else QColor("#4b5563"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            self._usage_button_hits.append((rect, usage.block.index))
            x += width + gap

    def _scale_span_rect(
        self,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        string_index: int,
        start_fret: int,
        end_fret: int,
        row_height: int,
    ) -> QRect:
        pad = max(8, min(18, int(fret_gap * 0.34)))
        y = int(board.top() + string_index * string_gap)
        left = self._fret_center_x(board, fret_gap, start_fret) - pad
        right = self._fret_center_x(board, fret_gap, end_fret) + pad
        return QRect(left, y - row_height // 2, max(1, right - left), row_height)

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        for fret in (12, 24):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15, 17, 19, 21):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)
        if fret_count >= 24:
            x = int(board.left() + 23.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)

