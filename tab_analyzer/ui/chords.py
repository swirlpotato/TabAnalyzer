"""Chord position and chord finder widgets."""

from __future__ import annotations

from .common import *

class ChordPositionsWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.measure: MeasureData | None = None
        self.candidate: Candidate | None = None
        self.positions: tuple[ChordPosition, ...] = ()
        self.root_string_filter: int | None = None
        self.category_filter: str | None = None
        self._content_height = 320
        self.setMinimumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def sizeHint(self) -> QSize:
        return QSize(380, max(300, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self.measure = None
        self.candidate = None
        self.positions = ()
        self._rebuild_layout()
        self.update()

    def set_selection(self, song: SongData | None, measure: MeasureData | None, candidate: Candidate | None) -> None:
        self.song = song
        self.measure = measure
        self.candidate = candidate if candidate is not None and candidate.kind == "chord" else None
        if self.song is not None and self.candidate is not None:
            self.positions = generate_chord_positions(
                self.candidate,
                self.song.track.string_pitches,
                self.song.track.fret_count,
                max_positions=MAX_CHORD_POSITIONS * len(CHORD_POSITION_CATEGORIES),
            )
        else:
            self.positions = ()
        self._rebuild_layout()
        self.update()

    def set_root_string_filter(self, string_number: int | None) -> None:
        self.root_string_filter = string_number
        self._rebuild_layout()
        self.update()

    def set_category_filter(self, category: str | None) -> None:
        self.category_filter = category
        self._rebuild_layout()
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._rebuild_layout()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))

        if self.song is None:
            self._draw_empty(painter, "Open a file to show chord positions.")
            return
        if self.candidate is None:
            self._draw_empty(painter, "Click a measure chord chip to show playable positions.")
            return
        if not self.positions:
            self._draw_empty(painter, "No chord positions were found within the current limits.")
            return

        self._draw_title(painter)
        visible_positions = self._visible_positions()
        if not visible_positions:
            self._draw_message(painter, 58, self._empty_filter_message())
            return

        y = 50
        card_height = self._card_height()
        next_index = 1
        triad_message = self._triad_message(visible_positions)
        if triad_message is not None:
            self._draw_category_header(painter, y, "Triad")
            y += 30
            self._draw_category_message(painter, y, triad_message)
            y += 42
        for category, positions in self._visible_groups(visible_positions):
            self._draw_category_header(painter, y, category)
            y += 30
            for position in positions:
                rect = QRect(10, y, max(260, self.width() - 20), card_height)
                self._draw_position_card(painter, rect, next_index, position)
                next_index += 1
                y += card_height + 10

    def _rebuild_layout(self) -> None:
        visible_positions = self._visible_positions()
        if not self.positions or not visible_positions:
            self._content_height = 320
        else:
            group_count = len(self._visible_groups(visible_positions))
            triad_message_count = 1 if self._triad_message(visible_positions) is not None else 0
            self._content_height = (
                60
                + len(visible_positions) * (self._card_height() + 10)
                + (group_count + triad_message_count) * 30
                + triad_message_count * 42
                + 16
            )
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _card_height(self) -> int:
        return 230

    def _draw_empty(self, painter: QPainter, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(self.rect().adjusted(18, 18, -18, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_message(self, painter: QPainter, y: int, text: str) -> None:
        painter.setPen(QColor("#657083"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(
            QRect(18, y, self.width() - 36, 120),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            tr(text),
        )

    def _draw_category_header(self, painter: QPainter, y: int, category: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf5"))
        painter.drawRoundedRect(rect, 6, 6)
        count = len([position for position in self._visible_positions() if category in position.categories])
        count_text = f"  {count}" if count else ""
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{tr(category)}{count_text}")

    def _draw_category_message(self, painter: QPainter, y: int, text: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 34)
        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#657083"))
        painter.drawText(rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_title(self, painter: QPainter) -> None:
        if self.song is None or self.candidate is None:
            return
        measure_text = f"M{self.measure.number}  " if self.measure is not None else ""
        title = f"{measure_text}{_trf('{name} Chord positions', name=candidate_display_name(self.candidate, self.song.track.prefer_flats))}"
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(14, 10, self.width() - 28, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

    def _draw_position_card(self, painter: QPainter, rect: QRect, index: int, position: ChordPosition) -> None:
        if self.song is None or self.candidate is None:
            return

        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)

        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        title = (
            f"{index}. "
            f"{chord_position_display_name(self.candidate, position, self.song.track.prefer_flats)}"
            f" - {tr(position.label)}"
        )
        painter.drawText(
            rect.adjusted(10, 7, -10, -rect.height() + 41),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            title,
        )

        fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
        missing = self._missing_text(position)
        barre = _trf(" - barre {fret} frets", fret=position.barre_fret) if position.barre_fret is not None else ""
        range_start, range_end = self._display_fret_range(position)
        meta = (
            _trf("Fingers {count}", count=position.finger_count)
            + (_trf(" + muted {count}", count=position.muted_finger_count) if position.muted_finger_count else "")
            + barre
            + _trf(" - {start}-{end} frets - {frets} - omitted {missing}", start=range_start, end=range_end, frets=fret_text, missing=missing)
        )
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#526071"))
        painter.drawText(rect.adjusted(10, 45, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, meta)

        board = rect.adjusted(54, 80, -18, -28)
        if board.width() <= 120 or board.height() <= 80:
            return
        self._draw_mini_fretboard(painter, board, position, range_start, range_end)

    def _draw_mini_fretboard(
        self,
        painter: QPainter,
        board: QRect,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return

        string_count = len(self.song.track.string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / MAX_FRET_SPAN

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(board.adjusted(-4, -8, 4, 8), 5, 5)

        self._draw_mini_barre(painter, board, fret_gap, string_gap, position, range_start, range_end)

        for fret_offset in range(MAX_FRET_SPAN + 1):
            x = int(board.left() + fret_offset * fret_gap)
            is_nut = range_start == 0 and fret_offset == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())

        painter.setFont(QFont("Segoe UI", 8))
        for fret in self._mini_visible_fret_labels(range_start, range_end):
            x = self._mini_fret_center_x(board, fret_gap, fret, range_start)
            painter.setPen(QColor("#697586"))
            painter.drawText(QRect(int(x - fret_gap / 2), board.bottom() + 12, int(fret_gap), 16), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, open_midi in enumerate(self.song.track.string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(board.left() - 48, y - 9, 28, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self.song.track.prefer_flats),
            )
            self._draw_open_or_mute(painter, board.left() - 13, y, position, string_index, range_start)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_position_notes(painter, board, fret_gap, string_gap, position, range_start, range_end)

    def _draw_open_or_mute(
        self,
        painter: QPainter,
        x: int,
        y: int,
        position: ChordPosition,
        string_index: int,
        range_start: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return
        fret = position.frets_high_to_low[string_index]
        if fret == MUTED:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.setPen(QColor("#9b1c1c"))
            painter.drawText(QRect(x - 7, y - 10, 14, 20), Qt.AlignmentFlag.AlignCenter, "x")
        elif fret == 0 and range_start != 0:
            interval = (self.song.track.string_pitches[string_index] - self.candidate.root_pc) % 12
            self._draw_note_marker(
                painter,
                x,
                y,
                "0",
                self._chord_position_degree_label(interval),
                False,
                13,
                is_root=interval == 0,
            )

    def _draw_mini_barre(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if position.barre_fret is None or not (range_start <= position.barre_fret <= range_end):
            return
        strings = [index for index, fret in enumerate(position.frets_high_to_low) if fret == position.barre_fret]
        if len(strings) < 2:
            return
        x = self._mini_fret_center_x(board, fret_gap, position.barre_fret, range_start)
        top = int(board.top() + min(strings) * string_gap) - 15
        bottom = int(board.top() + max(strings) * string_gap) + 15
        painter.setPen(QPen(QColor("#b45309"), 1.2))
        painter.setBrush(QColor(250, 204, 21, 150))
        painter.drawRoundedRect(QRect(x - 15, top, 30, bottom - top), 13, 13)

    def _draw_position_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if self.song is None or self.candidate is None:
            return

        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for string_index, fret in enumerate(position.frets_high_to_low):
            if fret < 0 or not (range_start <= fret <= range_end):
                continue
            x = self._mini_fret_center_x(board, fret_gap, fret, range_start)
            y = int(board.top() + string_index * string_gap)
            is_barre = position.barre_fret == fret
            interval = (self.song.track.string_pitches[string_index] + fret - self.candidate.root_pc) % 12
            degree = self._chord_position_degree_label(interval)
            self._draw_note_marker(
                painter,
                x,
                y,
                str(fret),
                degree,
                is_barre,
                15,
                fret_font,
                degree_font,
                is_root=interval == 0,
            )

    def _draw_note_marker(
        self,
        painter: QPainter,
        x: int,
        y: int,
        fret_text: str,
        degree: str,
        is_barre: bool,
        radius: int,
        fret_font: QFont | None = None,
        degree_font: QFont | None = None,
        is_root: bool = False,
    ) -> None:
        if is_root:
            fill = QColor("#dc2626")
            border = QColor("#991b1b")
        elif is_barre:
            fill = QColor("#fde68a")
            border = QColor("#b45309")
        else:
            fill = QColor("#16a34a")
            border = QColor("#0f6f34")
        painter.setPen(QPen(border, 2))
        painter.setBrush(fill)
        painter.drawEllipse(QPoint(x, y), radius, radius)

        text_color = QColor("#111827") if is_barre and not is_root else QColor("#ffffff")
        painter.setPen(text_color)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setFont(fret_font or QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, fret_text)
        painter.setFont(degree_font or QFont("Segoe UI", 5, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)

    def _chord_position_degree_label(self, interval: int) -> str:
        return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]

    def _mini_visible_fret_labels(self, range_start: int, range_end: int) -> range:
        if range_start == 0:
            return range(1, range_end + 2)
        return range(range_start, range_end + 1)

    def _mini_fret_center_x(self, board: QRect, fret_gap: float, fret: int, range_start: int) -> int:
        if fret == 0:
            return int(board.left())
        if range_start == 0:
            return int(board.left() + (fret - 0.5) * fret_gap)
        return int(board.left() + (fret - range_start + 0.5) * fret_gap)

    def _visible_positions(self) -> tuple[ChordPosition, ...]:
        return filter_chord_positions(
            self.positions,
            self.root_string_filter,
            self.category_filter,
            max_positions=MAX_CHORD_POSITIONS,
        )

    def _visible_groups(
        self,
        visible_positions: tuple[ChordPosition, ...],
    ) -> tuple[tuple[str, tuple[ChordPosition, ...]], ...]:
        if self.category_filter is not None:
            return ((self.category_filter, visible_positions),)
        return group_chord_positions_by_category(visible_positions)

    def _triad_message(self, visible_positions: tuple[ChordPosition, ...]) -> str | None:
        return None

    def _empty_filter_message(self) -> str:
        parts: list[str] = []
        if self.root_string_filter is not None:
            parts.append(_trf("root on string {number}", number=self.root_string_filter))
        if self.category_filter is not None:
            parts.append(_trf("{category} category", category=tr(self.category_filter)))
        if parts:
            return _trf("No {filters} chord positions were found.", filters=" ".join(parts))
        return tr("No chord positions to show.")

    def _display_fret_range(self, position: ChordPosition) -> tuple[int, int]:
        if position.fretted_count == 0:
            return 0, MAX_FRET_SPAN - 1
        if position.open_count and position.max_fret <= MAX_FRET_SPAN - 1:
            return 0, MAX_FRET_SPAN - 1
        start = max(1, position.min_fret)
        return start, start + MAX_FRET_SPAN - 1

    def _missing_text(self, position: ChordPosition) -> str:
        if self.candidate is None:
            return "-"
        missing = [self._chord_position_degree_label(interval) for interval in position.missing_intervals]
        return ", ".join(missing) if missing else tr("None")


class ChordFinderWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.song: SongData | None = None
        self.selected_positions: list[tuple[int, int]] = []
        self.root_filter: int | None = None
        self.type_filter: str | None = None
        self.matches: tuple[ChordMatch, ...] = ()
        self.entries: tuple[tuple[ChordMatch, ChordPosition], ...] = ()
        self.match_count = 0
        self._position_cache: dict[tuple[int, str, tuple[int, ...], tuple[int, ...], int], tuple[ChordPosition, ...]] = {}
        self._searching = False
        self._search_token = 0
        self._chord_search_thread: QThread | None = None
        self._chord_search_worker: _ChordFinderSearchWorker | None = None
        self._pending_search_params: _ChordFinderSearchParams | None = None
        self._note_hits: list[tuple[QRect, int, int]] = []
        self._content_height = 560
        self.fretboard_scroll = QScrollBar(Qt.Orientation.Horizontal, self)
        self.fretboard_scroll.valueChanged.connect(lambda _value: self.update())
        self.fretboard_scroll.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumWidth(320)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._rebuild_layout()

    def sizeHint(self) -> QSize:
        return QSize(380, max(420, self._content_height))

    def set_song(self, song: SongData | None) -> None:
        self.song = song
        self._position_cache = {}
        string_count = len(self._string_pitches())
        display_fret_count = self._display_fret_count()
        self.selected_positions = [
            (string_index, fret)
            for string_index, fret in self.selected_positions
            if 0 <= string_index < string_count and 0 <= fret <= display_fret_count
        ]
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def set_root_filter(self, root_pc: int | None, clear_selection: bool = False) -> None:
        self.root_filter = root_pc
        if clear_selection:
            self.selected_positions = []
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def set_type_filter(self, type_suffix: str | None, clear_selection: bool = False) -> None:
        self.type_filter = type_suffix
        if clear_selection:
            self.selected_positions = []
        self._rebuild_matches()
        self._rebuild_layout()
        self.update()

    def shutdown(self) -> None:
        self._pending_search_params = None
        self._search_token += 1
        if self._chord_search_thread is not None and self._chord_search_thread.isRunning():
            self._chord_search_thread.quit()
            self._chord_search_thread.wait(2000)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_fretboard_scrollbar()
        self._rebuild_layout()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        position = event.position().toPoint()
        for rect, string_index, fret in self._note_hits:
            if rect.contains(position):
                selected_position = (string_index, fret)
                if selected_position in self.selected_positions:
                    self.selected_positions.remove(selected_position)
                else:
                    self.selected_positions = [
                        (selected_string_index, selected_fret)
                        for selected_string_index, selected_fret in self.selected_positions
                        if selected_string_index != string_index
                    ]
                    self.selected_positions.append(selected_position)
                self._rebuild_matches()
                self._rebuild_layout()
                self.update()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5f7fb"))
        self._draw_title(painter)
        self._draw_fretboard(painter)
        self._draw_results(painter)

    def _rebuild_matches(self) -> None:
        params = self._search_params()
        self._search_token += 1
        self._pending_search_params = None
        if params is None:
            self._searching = False
            self.matches = ()
            self.entries = ()
            self.match_count = 0
            return

        self._searching = True
        self.matches = ()
        self.entries = ()
        self.match_count = 0
        if self._chord_search_thread is not None and self._chord_search_thread.isRunning():
            self._pending_search_params = params
            return
        self._start_chord_search(params)

    def _search_params(self) -> _ChordFinderSearchParams | None:
        if len(self.selected_positions) == 1:
            return None
        note_pcs = self._selected_note_pcs()
        if not note_pcs and (self.root_filter is None or self.type_filter is None):
            return None
        return _ChordFinderSearchParams(
            note_pcs=note_pcs,
            selected_positions=tuple(self.selected_positions),
            root_filter=self.root_filter,
            type_filter=self.type_filter,
            string_pitches=self._string_pitches(),
            fret_count=self._fret_count(),
        )

    def _start_chord_search(self, params: _ChordFinderSearchParams) -> None:
        token = self._search_token
        thread = QThread(self)
        worker = _ChordFinderSearchWorker(token, params)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_chord_search_finished)
        worker.failed.connect(self._on_chord_search_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self._on_chord_search_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._chord_search_thread = thread
        self._chord_search_worker = worker
        thread.start()

    def _on_chord_search_finished(self, token: int, result: object) -> None:
        if token != self._search_token or not isinstance(result, _ChordFinderSearchResult):
            return
        self._searching = False
        self.matches = result.matches
        self.entries = result.entries
        self.match_count = result.match_count
        self._rebuild_layout()
        self.update()

    def _on_chord_search_failed(self, token: int, message: str) -> None:
        if token != self._search_token:
            return
        self._searching = False
        self.matches = ()
        self.entries = ()
        self.match_count = 0
        self._rebuild_layout()
        self.update()

    def _on_chord_search_thread_finished(self) -> None:
        self._chord_search_thread = None
        self._chord_search_worker = None
        if self._pending_search_params is None:
            return
        params = self._pending_search_params
        self._pending_search_params = None
        self._search_token += 1
        self._start_chord_search(params)

    def _rebuild_layout(self) -> None:
        self._sync_fretboard_scrollbar()
        result_y = self._results_start_y()
        if not self.entries:
            self._content_height = max(460, result_y + 112)
        else:
            self._content_height = (
                result_y
                + 42
                + len(self.entries) * (self._card_height() + 10)
                + 18
            )
        self.setMinimumHeight(self._content_height)
        self.updateGeometry()

    def _card_height(self) -> int:
        return 230

    def _string_pitches(self) -> tuple[int, ...]:
        if self.song is not None:
            return self.song.track.string_pitches
        return DEFAULT_FINDER_STRING_PITCHES_HIGH_TO_LOW

    def _fret_count(self) -> int:
        if self.song is not None:
            return self.song.track.fret_count
        return DEFAULT_FINDER_FRET_COUNT

    def _display_fret_count(self) -> int:
        return min(MAX_DISPLAY_FRET, max(12, self._fret_count()))

    def _prefer_flats(self) -> bool | None:
        return self.song.track.prefer_flats if self.song is not None else None

    def _selected_note_pcs(self) -> tuple[int, ...]:
        pitches = self._string_pitches()
        seen: set[int] = set()
        note_pcs: list[int] = []
        for string_index, fret in self.selected_positions:
            if string_index < 0 or string_index >= len(pitches):
                continue
            pc = (pitches[string_index] + fret) % 12
            if pc in seen:
                continue
            seen.add(pc)
            note_pcs.append(pc)
        return tuple(note_pcs)

    def _selected_note_names(self) -> str:
        return " ".join(self._pitch_name(pc) for pc in self._selected_note_pcs())

    def _board_viewport_rect(self) -> QRect:
        string_count = max(1, len(self._string_pitches()))
        board_height = max(104, (string_count - 1) * 24)
        return QRect(56, 64, max(240, self.width() - 84), board_height)

    def _board_virtual_width(self, viewport_width: int) -> int:
        return max(viewport_width * 2, 600)

    def _sync_fretboard_scrollbar(self) -> None:
        viewport = self._board_viewport_rect()
        virtual_width = self._board_virtual_width(viewport.width())
        maximum = max(0, virtual_width - viewport.width())
        self.fretboard_scroll.setGeometry(QRect(viewport.left(), viewport.bottom() + 48, viewport.width(), 16))
        self.fretboard_scroll.setRange(0, maximum)
        self.fretboard_scroll.setPageStep(viewport.width())
        self.fretboard_scroll.setSingleStep(max(16, viewport.width() // 10))
        self.fretboard_scroll.setVisible(maximum > 0)

    def _board_metrics(self) -> tuple[QRect, QRect, int, float, float]:
        string_count = max(1, len(self._string_pitches()))
        viewport = self._board_viewport_rect()
        virtual_width = self._board_virtual_width(viewport.width())
        scroll_offset = min(self.fretboard_scroll.value(), max(0, virtual_width - viewport.width()))
        board = QRect(viewport.left() - scroll_offset, viewport.top(), virtual_width, viewport.height())
        fret_count = self._display_fret_count()
        fret_gap = board.width() / max(1, fret_count)
        string_gap = board.height() / max(1, string_count - 1)
        return viewport, board, fret_count, fret_gap, string_gap

    def _results_start_y(self) -> int:
        board = self._board_viewport_rect()
        return board.bottom() + 82

    def _draw_title(self, painter: QPainter) -> None:
        selected_notes = self._selected_note_names()
        title = _trf("{notes} containing chords", notes=selected_notes) if selected_notes else self._filter_title()
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(QRect(14, 10, self.width() - 28, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#657083"))
        painter.drawText(
            QRect(14, 34, self.width() - 28, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            _trf(
                "{strings} strings - {frets} frets - selected {selected}",
                strings=len(self._string_pitches()),
                frets=self._display_fret_count(),
                selected=len(self.selected_positions),
            ),
        )

    def _draw_fretboard(self, painter: QPainter) -> None:
        self._sync_fretboard_scrollbar()
        viewport, board, fret_count, fret_gap, string_gap = self._board_metrics()
        pitches = self._string_pitches()
        if viewport.width() <= 80 or viewport.height() <= 80 or not pitches:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(viewport.adjusted(-4, -8, 4, 8), 5, 5)

        for string_index, open_midi in enumerate(pitches):
            y = int(viewport.top() + string_index * string_gap)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(viewport.left() - 50, y - 9, 30, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self._prefer_flats()),
            )

        painter.save()
        painter.setClipRect(viewport.adjusted(-2, -8, 2, 66))

        for fret in range(fret_count + 1):
            x = int(board.left() + fret * fret_gap)
            is_nut = fret == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())
            if fret > 0:
                painter.setFont(QFont("Segoe UI", 8))
                painter.setPen(QColor("#697586"))
                painter.drawText(
                    QRect(int(x - fret_gap), board.bottom() + 12, int(fret_gap * 2), 16),
                    Qt.AlignmentFlag.AlignCenter,
                    str(fret),
                )

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, _open_midi in enumerate(pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_inlays(painter, board, fret_count, fret_gap)
        self._draw_position_dots_below_frets(painter, board, fret_count, fret_gap)
        self._build_note_hits(board, fret_count, fret_gap, string_gap)
        self._draw_selected_notes(painter, board, fret_gap, string_gap)
        painter.restore()

    def _build_note_hits(self, board: QRect, fret_count: int, fret_gap: float, string_gap: float) -> None:
        self._note_hits = []
        hit_radius = max(12, min(20, int(fret_gap * 0.55)))
        for string_index, _open_midi in enumerate(self._string_pitches()):
            y = int(board.top() + string_index * string_gap)
            for fret in range(fret_count + 1):
                x = self._fret_center_x(board, fret_gap, fret)
                self._note_hits.append((QRect(x - hit_radius, y - hit_radius, hit_radius * 2, hit_radius * 2), string_index, fret))

    def _draw_selected_notes(self, painter: QPainter, board: QRect, fret_gap: float, string_gap: float) -> None:
        pitches = self._string_pitches()
        for string_index, fret in self.selected_positions:
            if string_index >= len(pitches) or fret > self._display_fret_count():
                continue
            pc = (pitches[string_index] + fret) % 12
            x = self._fret_center_x(board, fret_gap, fret)
            y = int(board.top() + string_index * string_gap)
            self._draw_selected_note_marker(painter, x, y, self._pitch_name(pc), str(fret))

    def _draw_selected_note_marker(self, painter: QPainter, x: int, y: int, note_text: str, fret_text: str) -> None:
        radius = 15
        painter.setPen(QPen(QColor("#0f6f34"), 2))
        painter.setBrush(QColor("#16a34a"))
        painter.drawEllipse(QPoint(x, y), radius, radius)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setPen(QColor("#ffffff"))
        note_font_size = 7 if len(note_text) >= 2 else 8
        painter.setFont(QFont("Segoe UI", note_font_size, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, note_text)
        painter.setFont(QFont("Segoe UI", 6, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, fret_text)

    def _draw_results(self, painter: QPainter) -> None:
        y = self._results_start_y()
        selected_notes = self._selected_note_names()
        if self._searching:
            self._draw_message(painter, y, "Searching chords...")
            return
        if len(self.selected_positions) == 1:
            self._draw_message(painter, y, "Select two or more notes to find chords.")
            return
        if not selected_notes and (self.root_filter is None or self.type_filter is None):
            self._draw_message(painter, y, "No selected notes")
            return
        if not self.entries:
            self._draw_message(painter, y, "No chords match the filters.")
            return

        summary = (
            _trf("Selected notes {notes} - chords {count}", notes=selected_notes, count=self.match_count)
            if selected_notes
            else _trf("{filter} - chords {count}", filter=self._filter_title(), count=self.match_count)
        )
        if self.match_count > len(self.entries):
            summary += _trf(" - top {count} shown", count=len(self.entries))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf5"))
        header_rect = QRect(10, y, max(260, self.width() - 20), 24)
        painter.drawRoundedRect(header_rect, 6, 6)
        painter.setPen(QColor("#253044"))
        painter.drawText(header_rect.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, summary)
        y += 36

        card_height = self._card_height()
        for index, (match, position) in enumerate(self.entries, start=1):
            rect = QRect(10, y, max(260, self.width() - 20), card_height)
            self._draw_match_card(painter, rect, index, match, position)
            y += card_height + 10

    def _draw_message(self, painter: QPainter, y: int, text: str) -> None:
        rect = QRect(10, y, max(260, self.width() - 20), 72)
        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 10))
        painter.setPen(QColor("#657083"))
        painter.drawText(rect.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(text))

    def _draw_match_card(
        self,
        painter: QPainter,
        rect: QRect,
        index: int,
        match: ChordMatch,
        position: ChordPosition,
    ) -> None:
        prefer_flats = self._prefer_flats()
        chord_name = candidate_display_name(match.candidate, prefer_flats)
        root = pitch_class_name(match.candidate.root_pc, prefer_flats)
        notes = " ".join(pitch_class_name(pc, prefer_flats) for pc in match.candidate.pitch_classes)
        roles = self._selected_roles_text(match)
        meta = _trf("Root {root} - type {type}", root=root, type=match.chord_type.display_name)
        if roles:
            meta += _trf(" - selected notes {roles}", roles=roles)

        painter.setPen(QPen(QColor("#d6deea"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(rect, 7, 7)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.setPen(QColor("#253044"))
        painter.drawText(
            rect.adjusted(10, 7, -10, -rect.height() + 41),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            f"{index}. {chord_name}",
        )
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#526071"))
        painter.drawText(
            rect.adjusted(10, 45, -10, -rect.height() + 74),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            _trf("{meta} - notes {notes}", meta=meta, notes=notes),
        )

        range_start, range_end = self._display_fret_range(position)
        fret_text = " ".join("x" if fret == MUTED else str(fret) for fret in reversed(position.frets_high_to_low))
        missing = self._missing_text(position)
        barre = _trf(" - barre {fret} frets", fret=position.barre_fret) if position.barre_fret is not None else ""
        position_meta = (
            _trf("Fingers {count}", count=position.finger_count)
            + (_trf(" + muted {count}", count=position.muted_finger_count) if position.muted_finger_count else "")
            + barre
            + _trf(" - {start}-{end} frets - {frets} - omitted {missing}", start=range_start, end=range_end, frets=fret_text, missing=missing)
        )
        painter.setPen(QColor("#526071"))
        painter.drawText(rect.adjusted(10, 64, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, position_meta)

        board = rect.adjusted(54, 96, -18, -28)
        if board.width() <= 120 or board.height() <= 80:
            return
        self._draw_match_mini_fretboard(painter, board, match.candidate, position, range_start, range_end)

    def _positions_for_match(self, match: ChordMatch) -> tuple[ChordPosition, ...]:
        key = (
            match.candidate.root_pc,
            match.chord_type.suffix,
            match.candidate.intervals,
            self._string_pitches(),
            self._fret_count(),
        )
        if key not in self._position_cache:
            positions = generate_chord_positions(
                match.candidate,
                self._string_pitches(),
                self._fret_count(),
                max_positions=MAX_CHORD_POSITIONS * len(CHORD_POSITION_CATEGORIES),
            )
            self._position_cache[key] = tuple(
                position for position in positions if self._barre_open_strings_are_playable(position)
            )
        return self._position_cache[key]

    def _position_contains_selected_frets(self, position: ChordPosition) -> bool:
        for string_index, fret in self.selected_positions:
            if string_index < 0 or string_index >= len(position.frets_high_to_low):
                return False
            if position.frets_high_to_low[string_index] != fret:
                return False
        return True

    def _selected_fret_span_can_fit(self) -> bool:
        fretted = [fret for _string_index, fret in self.selected_positions if fret > 0]
        if not fretted:
            return True
        if 0 in [fret for _string_index, fret in self.selected_positions] and max(fretted) > MAX_FRET_SPAN - 1:
            return False
        return max(fretted) - min(fretted) <= MAX_FRET_SPAN - 1

    def _barre_open_strings_are_playable(self, position: ChordPosition) -> bool:
        if position.barre_fret is None:
            return True
        barre_strings = [
            string_index
            for string_index, fret in enumerate(position.frets_high_to_low)
            if fret == position.barre_fret
        ]
        if len(barre_strings) < 2:
            return True
        thinnest_barred_string = min(barre_strings)
        return all(
            fret != 0
            for string_index, fret in enumerate(position.frets_high_to_low)
            if string_index < thinnest_barred_string
        )

    def _match_key(self, match: ChordMatch) -> tuple[int, str, tuple[int, ...]]:
        return (match.candidate.root_pc, match.chord_type.suffix, match.candidate.intervals)

    def _selected_roles_text(self, match: ChordMatch) -> str:
        parts = [
            f"{self._pitch_name(note_pc)}={self._chord_position_degree_label(interval)}"
            for note_pc, interval in zip(match.selected_note_pcs, match.selected_intervals)
        ]
        return ", ".join(parts)

    def _filter_title(self) -> str:
        root = tr("All")
        if self.root_filter is not None:
            root = pitch_class_name(self.root_filter, self._prefer_flats())
        chord_type = tr("All")
        if self.type_filter is not None:
            for item in CHORD_FINDER_TYPES:
                if item.suffix == self.type_filter:
                    chord_type = item.display_name
                    break
        if self.root_filter is None and self.type_filter is None:
            return tr("Chord finder")
        return f"{root} {chord_type}".strip()

    def _pitch_name(self, pitch_class: int) -> str:
        return pitch_class_name(pitch_class, self._prefer_flats())

    def _fret_center_x(self, board: QRect, fret_gap: float, fret: int) -> int:
        if fret == 0:
            return int(board.left())
        return int(board.left() + (fret - 0.5) * fret_gap)

    def _draw_match_mini_fretboard(
        self,
        painter: QPainter,
        board: QRect,
        candidate: Candidate,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        string_pitches = self._string_pitches()
        string_count = len(string_pitches)
        string_gap = board.height() / max(1, string_count - 1)
        fret_gap = board.width() / MAX_FRET_SPAN

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fbfcff"))
        painter.drawRoundedRect(board.adjusted(-4, -8, 4, 8), 5, 5)

        self._draw_match_mini_barre(painter, board, fret_gap, string_gap, position, range_start, range_end)

        for fret_offset in range(MAX_FRET_SPAN + 1):
            x = int(board.left() + fret_offset * fret_gap)
            is_nut = range_start == 0 and fret_offset == 0
            painter.setPen(QPen(QColor("#5e6878") if is_nut else QColor("#c3cbd6"), 4 if is_nut else 1))
            painter.drawLine(x, board.top(), x, board.bottom())

        painter.setFont(QFont("Segoe UI", 8))
        for fret in self._match_visible_fret_labels(range_start, range_end):
            x = self._match_fret_center_x(board, fret_gap, fret, range_start)
            painter.setPen(QColor("#697586"))
            painter.drawText(QRect(int(x - fret_gap / 2), board.bottom() + 12, int(fret_gap), 16), Qt.AlignmentFlag.AlignCenter, str(fret))

        painter.setPen(QPen(QColor("#798393"), 1.2))
        for string_index, open_midi in enumerate(string_pitches):
            y = int(board.top() + string_index * string_gap)
            painter.drawLine(board.left(), y, board.right(), y)
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(
                QRect(board.left() - 48, y - 9, 28, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fretboard_string_label(open_midi, string_index, self._prefer_flats()),
            )
            self._draw_match_open_or_mute(painter, board.left() - 13, y, candidate, position, string_index, range_start)
            painter.setPen(QPen(QColor("#798393"), 1.2))

        self._draw_match_position_notes(painter, board, fret_gap, string_gap, candidate, position, range_start, range_end)

    def _draw_match_open_or_mute(
        self,
        painter: QPainter,
        x: int,
        y: int,
        candidate: Candidate,
        position: ChordPosition,
        string_index: int,
        range_start: int,
    ) -> None:
        fret = position.frets_high_to_low[string_index]
        if fret == MUTED:
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            painter.setPen(QColor("#9b1c1c"))
            painter.drawText(QRect(x - 7, y - 10, 14, 20), Qt.AlignmentFlag.AlignCenter, "x")
        elif fret == 0 and range_start != 0:
            interval = (self._string_pitches()[string_index] - candidate.root_pc) % 12
            self._draw_chord_position_marker(
                painter,
                x,
                y,
                "0",
                self._chord_position_degree_label(interval),
                False,
                13,
                is_root=interval == 0,
            )

    def _draw_match_mini_barre(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        if position.barre_fret is None or not (range_start <= position.barre_fret <= range_end):
            return
        strings = [index for index, fret in enumerate(position.frets_high_to_low) if fret == position.barre_fret]
        if len(strings) < 2:
            return
        x = self._match_fret_center_x(board, fret_gap, position.barre_fret, range_start)
        top = int(board.top() + min(strings) * string_gap) - 15
        bottom = int(board.top() + max(strings) * string_gap) + 15
        painter.setPen(QPen(QColor("#b45309"), 1.2))
        painter.setBrush(QColor(250, 204, 21, 150))
        painter.drawRoundedRect(QRect(x - 15, top, 30, bottom - top), 13, 13)

    def _draw_match_position_notes(
        self,
        painter: QPainter,
        board: QRect,
        fret_gap: float,
        string_gap: float,
        candidate: Candidate,
        position: ChordPosition,
        range_start: int,
        range_end: int,
    ) -> None:
        fret_font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        degree_font = QFont("Segoe UI", 6, QFont.Weight.DemiBold)
        for string_index, fret in enumerate(position.frets_high_to_low):
            if fret < 0 or not (range_start <= fret <= range_end):
                continue
            x = self._match_fret_center_x(board, fret_gap, fret, range_start)
            y = int(board.top() + string_index * string_gap)
            is_barre = position.barre_fret == fret
            interval = (self._string_pitches()[string_index] + fret - candidate.root_pc) % 12
            degree = self._chord_position_degree_label(interval)
            self._draw_chord_position_marker(
                painter,
                x,
                y,
                str(fret),
                degree,
                is_barre,
                15,
                fret_font,
                degree_font,
                is_root=interval == 0,
            )

    def _draw_chord_position_marker(
        self,
        painter: QPainter,
        x: int,
        y: int,
        fret_text: str,
        degree: str,
        is_barre: bool,
        radius: int,
        fret_font: QFont | None = None,
        degree_font: QFont | None = None,
        is_root: bool = False,
    ) -> None:
        if is_root:
            fill = QColor("#dc2626")
            border = QColor("#991b1b")
        elif is_barre:
            fill = QColor("#fde68a")
            border = QColor("#b45309")
        else:
            fill = QColor("#16a34a")
            border = QColor("#0f6f34")
        painter.setPen(QPen(border, 2))
        painter.setBrush(fill)
        painter.drawEllipse(QPoint(x, y), radius, radius)

        text_color = QColor("#111827") if is_barre and not is_root else QColor("#ffffff")
        painter.setPen(text_color)
        circle_rect = QRect(x - radius, y - radius, radius * 2, radius * 2)
        painter.setFont(fret_font or QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(circle_rect.adjusted(0, 1, 0, -radius + 2), Qt.AlignmentFlag.AlignCenter, fret_text)
        painter.setFont(degree_font or QFont("Segoe UI", 5, QFont.Weight.DemiBold))
        painter.drawText(circle_rect.adjusted(0, radius - 4, 0, -1), Qt.AlignmentFlag.AlignCenter, degree)

    def _chord_position_degree_label(self, interval: int) -> str:
        return "R" if interval % 12 == 0 else CHORD_DEGREE_LABELS[interval % 12]

    def _match_visible_fret_labels(self, range_start: int, range_end: int) -> range:
        if range_start == 0:
            return range(1, range_end + 2)
        return range(range_start, range_end + 1)

    def _match_fret_center_x(self, board: QRect, fret_gap: float, fret: int, range_start: int) -> int:
        if fret == 0:
            return int(board.left())
        if range_start == 0:
            return int(board.left() + (fret - 0.5) * fret_gap)
        return int(board.left() + (fret - range_start + 0.5) * fret_gap)

    def _display_fret_range(self, position: ChordPosition) -> tuple[int, int]:
        if position.fretted_count == 0:
            return 0, MAX_FRET_SPAN - 1
        if position.open_count and position.max_fret <= MAX_FRET_SPAN - 1:
            return 0, MAX_FRET_SPAN - 1
        start = max(1, position.min_fret)
        return start, start + MAX_FRET_SPAN - 1

    def _missing_text(self, position: ChordPosition) -> str:
        missing = [self._chord_position_degree_label(interval) for interval in position.missing_intervals]
        return ", ".join(missing) if missing else tr("None")

    def _draw_position_dots_below_frets(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#111827"))
        y = board.bottom() + 34
        for fret in (3, 5, 7, 9, 15):
            if fret > fret_count:
                continue
            x = self._fret_center_x(board, fret_gap, fret)
            painter.drawEllipse(QPoint(x, y), 4, 4)
        if fret_count >= 12:
            x = self._fret_center_x(board, fret_gap, 12)
            painter.drawEllipse(QPoint(x - 6, y), 4, 4)
            painter.drawEllipse(QPoint(x + 6, y), 4, 4)

    def _draw_inlays(self, painter: QPainter, board: QRect, fret_count: int, fret_gap: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e8ef"))
        center_y = board.center().y()
        for fret in (3, 5, 7, 9, 15):
            if fret > fret_count:
                continue
            x = int(board.left() + (fret - 0.5) * fret_gap)
            painter.drawEllipse(QPoint(x, center_y), 5, 5)
        if fret_count >= 12:
            x = int(board.left() + 11.5 * fret_gap)
            painter.drawEllipse(QPoint(x, center_y - 18), 5, 5)
            painter.drawEllipse(QPoint(x, center_y + 18), 5, 5)

