from __future__ import annotations

from PyQt6.QtCore import QPointF, QRect, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QPushButton


def _icon_button(icon: QIcon, tooltip: str, size: int = 30) -> QPushButton:
    button = QPushButton()
    button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setFixedSize(size, size)
    button.setIconSize(QSize(size - 10, size - 10))
    return button


def _player_icon(kind: str, color: str = "#111827") -> QIcon:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    if kind == "play":
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(12, 8),
                    QPointF(12, 24),
                    QPointF(24, 16),
                ]
            )
        )
    elif kind == "stop":
        painter.drawRect(QRect(10, 10, 12, 12))
    elif kind == "record":
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(QPointF(16, 16), 7, 7)
    elif kind == "metronome":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), 2))
        painter.drawLine(10, 25, 16, 7)
        painter.drawLine(22, 25, 16, 7)
        painter.drawLine(10, 25, 22, 25)
        painter.drawLine(16, 10, 20, 22)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(20, 22), 2.5, 2.5)
    elif kind == "speaker":
        painter.drawRect(QRect(7, 13, 5, 7))
        painter.drawPolygon(QPolygonF([QPointF(12, 13), QPointF(19, 8), QPointF(19, 25), QPointF(12, 20)]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(color), 2))
        painter.drawArc(QRect(18, 11, 8, 10), -45 * 16, 90 * 16)
    painter.end()
    return QIcon(pixmap)


def _delete_recording_icon() -> QIcon:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#4b5563"), 2))
    painter.setBrush(QColor("#f3f4f6"))
    eraser = QPolygonF(
        [
            QPointF(8, 21),
            QPointF(18, 11),
            QPointF(25, 18),
            QPointF(15, 28),
        ]
    )
    painter.drawPolygon(eraser)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRect(QRect(12, 23, 12, 4))
    painter.setPen(QPen(QColor("#dc2626"), 2))
    painter.drawLine(21, 6, 28, 13)
    painter.drawLine(28, 6, 21, 13)
    painter.end()
    return QIcon(pixmap)


def _post_it_icon_rect(origin_x: int, origin_y: int, size: int) -> QRect:
    return QRect(origin_x, origin_y, size, size)


def _draw_post_it_icon(painter: QPainter, rect: QRect, has_memo: bool) -> None:
    fill = QColor("#ef4444") if has_memo else QColor("#ffffff")
    border = QColor("#991b1b") if has_memo else QColor("#c7ccd6")
    fold = QColor("#fecaca") if has_memo else QColor("#eef2f7")
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(border, 1.1))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 2, 2)
    path = QPainterPath()
    path.moveTo(rect.right() - rect.width() * 0.36, rect.top())
    path.lineTo(rect.right(), rect.top())
    path.lineTo(rect.right(), rect.top() + rect.height() * 0.36)
    path.closeSubpath()
    painter.setBrush(fold)
    painter.drawPath(path)
    painter.restore()
