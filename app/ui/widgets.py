"""Reusable UI primitives for the Obsidian design system.

Custom-painted widgets (toggle, score ring, sparkline) can't be styled with QSS, so
they read colors from the active palette, which the main window updates on every
theme or accent change.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import DISPLAY_FONT, ICON_FONTS, ThemePalette, palette_for

_ACTIVE = {"palette": palette_for("dark"), "motion": True}


def set_active_palette(palette: ThemePalette, motion: bool = True) -> None:
    _ACTIVE["palette"] = palette
    _ACTIVE["motion"] = motion


def active_palette() -> ThemePalette:
    return _ACTIVE["palette"]  # type: ignore[return-value]


def motion_enabled() -> bool:
    return bool(_ACTIVE["motion"])


def _display_family() -> str:
    return DISPLAY_FONT.split(",")[0].strip().strip('"')


# ----------------------------------------------------------------- helpers
def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_dynamic(widget: QWidget, name: str, value) -> None:
    """Set a QSS dynamic property and repolish only when it actually changed."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


def set_pointing_cursor(widget: QWidget) -> None:
    widget.setCursor(Qt.PointingHandCursor)


def configure_scroll_area(scroll: QScrollArea) -> None:
    scroll.setWidgetResizable(True)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif child is not None:
            clear_layout(child)


def glyph_icon(glyph: str, color: str, size: int = 18) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    font = QFont(ICON_FONTS[0])
    font.setFamilies(list(ICON_FONTS))
    font.setPixelSize(int(size * 1.5))
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


def label(text: str = "", object_name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


def kbd(text: str) -> QLabel:
    """A keyboard-shortcut hint like `Ctrl K`."""
    widget = QLabel(text)
    widget.setObjectName("kbd")
    widget.setAlignment(Qt.AlignCenter)
    widget.setFixedHeight(20)
    widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return widget


def divider(vertical: bool = False) -> QFrame:
    line = QFrame()
    line.setObjectName("vdivider" if vertical else "divider")
    return line


def card(object_name: str = "card", margins: tuple[int, int, int, int] = (20, 18, 20, 18), spacing: int = 12):
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return frame, layout


def button(text: str, object_name: str = "ghostButton", on_click=None, tooltip: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(object_name)
    set_pointing_cursor(widget)
    if tooltip:
        widget.setToolTip(tooltip)
    if on_click is not None:
        widget.clicked.connect(lambda _checked=False: on_click())
    return widget


def icon_button(glyph: str, tooltip: str, on_click=None) -> QPushButton:
    widget = button(glyph, "iconButton", on_click, tooltip)
    widget.setAccessibleName(tooltip)
    widget.setFixedSize(34, 34)
    return widget


class Glyph(QLabel):
    def __init__(self, glyph: str, tone: str = "", size_pt: float | None = None) -> None:
        super().__init__(glyph)
        self.setObjectName("glyph")
        self.setAlignment(Qt.AlignCenter)
        if tone:
            self.setProperty("tone", tone)
        if size_pt is not None:
            self.setStyleSheet(f"font-size: {size_pt}pt;")

    def set_tone(self, tone: str) -> None:
        set_dynamic(self, "tone", tone)


class StatusChip(QLabel):
    def __init__(self, text: str = "", tone: str = "muted", object_name: str = "chip") -> None:
        super().__init__(text)
        self.setObjectName("chip")
        self.setProperty("role", object_name)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setProperty("tone", tone)

    def set_tone(self, tone: str) -> None:
        set_dynamic(self, "tone", tone)


# ----------------------------------------------------------------- toggle switch
class ToggleSwitch(QAbstractButton):
    """iOS/Fluent-style switch with an animated knob. `text()` mirrors On/Off for a11y."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(44, 24)
        self._offset = 0.0
        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # pragma: no cover - layout hint
        return QSize(44, 24)

    def _get_offset(self) -> float:
        return self._offset

    def _set_offset(self, value: float) -> None:
        self._offset = value
        self.update()

    offset = Property(float, _get_offset, _set_offset)

    def _animate(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not motion_enabled() or not self.isVisible():
            self._animation.stop()
            self._set_offset(target)
            return
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(target)
        self._animation.start()

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(checked)
        if self._animation.state() != QPropertyAnimation.Running:
            self._offset = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, _event) -> None:  # pragma: no cover - paint path
        p = active_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        enabled = self.isEnabled()
        on = QColor(p.accent)
        off = QColor(p.border_strong)
        track = QColor(
            int(off.red() + (on.red() - off.red()) * self._offset),
            int(off.green() + (on.green() - off.green()) * self._offset),
            int(off.blue() + (on.blue() - off.blue()) * self._offset),
        )
        if not enabled:
            track.setAlpha(90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.accent_soft_border), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), rect.height() / 2 + 1, rect.height() / 2 + 1)
        knob_d = rect.height() - 6
        x = 3 + (rect.width() - knob_d - 6) * self._offset
        knob = QColor(p.accent_text) if self._offset > 0.5 else QColor(p.text if p.mode == "dark" else "#FFFFFF")
        if not enabled:
            knob.setAlpha(140)
        painter.setPen(Qt.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(QRectF(x + 0.5, 3.5, knob_d, knob_d))
        painter.end()


# ----------------------------------------------------------------- score ring
class ScoreRing(QWidget):
    """Animated 0-100 gauge. The arc sweeps from the previous score to the new one."""

    def __init__(self, diameter: int = 148, stroke: int = 10) -> None:
        super().__init__()
        self.setFixedSize(diameter, diameter)
        self.stroke = stroke
        self.score: int | None = None
        self.color = QColor(active_palette().accent)
        self.caption = "HEALTH"
        self._shown = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(900)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._on_value)

    def _on_value(self, value) -> None:
        self._shown = float(value)
        self.update()

    def set_score(self, score: int | None, color: str, *_unused) -> None:
        self.score = score
        self.color = QColor(color)
        target = float(score or 0)
        if not motion_enabled():
            self._shown = target
            self.update()
            return
        self._animation.stop()
        self._animation.setStartValue(self._shown)
        self._animation.setEndValue(target)
        self._animation.start()

    def paintEvent(self, _event) -> None:  # pragma: no cover - paint path
        p = active_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        inset = self.stroke / 2 + 2
        rect = QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2)
        pen = QPen(QColor(p.border), self.stroke)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        if self.score is not None and self._shown > 0:
            pen.setColor(self.color)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * max(0.0, min(100.0, self._shown)) / 100))
        number = QFont(_display_family())
        number.setPixelSize(int(self.height() * 0.30))
        number.setWeight(QFont.Bold)
        painter.setFont(number)
        painter.setPen(QColor(p.text))
        number_rect = QRectF(0, self.height() * 0.24, self.width(), self.height() * 0.40)
        painter.drawText(number_rect, Qt.AlignCenter, "--" if self.score is None else str(int(round(self._shown))))
        caption = QFont(_display_family())
        caption.setPixelSize(max(9, int(self.height() * 0.075)))
        caption.setWeight(QFont.DemiBold)
        caption.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
        painter.setFont(caption)
        painter.setPen(QColor(p.text_subtle))
        painter.drawText(QRectF(0, self.height() * 0.60, self.width(), self.height() * 0.14), Qt.AlignCenter, self.caption)
        painter.end()


# ----------------------------------------------------------------- sparkline
class Sparkline(QWidget):
    """Rolling line chart with a soft fill. Values are 0-100 (percent)."""

    def __init__(self, capacity: int = 60, height: int = 44) -> None:
        super().__init__()
        self.values: deque[float] = deque(maxlen=capacity)
        self.capacity = capacity
        self.color: str | None = None
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(height)

    def push(self, value: float | None) -> None:
        if value is None:
            return
        self.values.append(max(0.0, min(100.0, float(value))))
        if self.isVisible():
            self.update()

    def paintEvent(self, _event) -> None:  # pragma: no cover - paint path
        p = active_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = self.width(), self.height()
        grid = QColor(p.border)
        grid.setAlpha(120)
        painter.setPen(QPen(grid, 1, Qt.DashLine))
        painter.drawLine(QPointF(0, height / 2), QPointF(width, height / 2))
        if len(self.values) < 2:
            painter.end()
            return
        step = width / max(1, self.capacity - 1)
        start_x = width - step * (len(self.values) - 1)
        points = [
            QPointF(start_x + index * step, 2 + (height - 4) * (1 - value / 100))
            for index, value in enumerate(self.values)
        ]
        line = QPainterPath(points[0])
        for point in points[1:]:
            line.lineTo(point)
        color = QColor(self.color or p.accent)
        fill = QPainterPath(line)
        fill.lineTo(points[-1].x(), height)
        fill.lineTo(points[0].x(), height)
        fill.closeSubpath()
        gradient = QLinearGradient(0, 0, 0, height)
        top = QColor(color)
        top.setAlpha(70)
        bottom = QColor(color)
        bottom.setAlpha(0)
        gradient.setColorAt(0, top)
        gradient.setColorAt(1, bottom)
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(color, 1.8))
        painter.drawPath(line)
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(points[-1], 2.6, 2.6)
        painter.end()


# ----------------------------------------------------------------- segmented control
class SegmentedControl(QFrame):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], current: str | None = None) -> None:
        super().__init__()
        self.setObjectName("segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in options:
            segment = QPushButton(text)
            segment.setObjectName("segment")
            segment.setCheckable(True)
            segment.setMinimumWidth(segment.fontMetrics().horizontalAdvance(text) + 34)
            set_pointing_cursor(segment)
            segment.clicked.connect(lambda _checked=False, value=key: self.set_value(value, emit=True))
            layout.addWidget(segment)
            self.buttons[key] = segment
        self.value = ""
        self.set_value(current or options[0][0])

    def set_value(self, value: str, emit: bool = False) -> None:
        self.value = value
        for key, segment in self.buttons.items():
            segment.setChecked(key == value)
        if emit:
            self.changed.emit(value)

    def set_label(self, key: str, text: str) -> None:
        if key in self.buttons and self.buttons[key].text() != text:
            self.buttons[key].setText(text)
            self.buttons[key].setMinimumWidth(self.buttons[key].fontMetrics().horizontalAdvance(text) + 34)


# ----------------------------------------------------------------- empty state
class EmptyState(QWidget):
    def __init__(self, glyph: str, title: str, body: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        icon = Glyph(glyph, size_pt=22)
        self.title_label = label(title, "h3")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.body_label = label(body, "muted", wrap=True)
        self.body_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)


# ----------------------------------------------------------------- toast
class Toast(QFrame):
    """A transient confirmation pinned to the bottom-right of its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 16, 10)
        layout.setSpacing(10)
        self.icon = Glyph("", tone="accent")
        self.text = label("", "", wrap=False)
        layout.addWidget(self.icon)
        layout.addWidget(self.text)
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.finished.connect(self._after_fade)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, glyph: str, tone: str = "accent", duration_ms: int = 2600) -> None:
        self.icon.setText(glyph)
        self.icon.set_tone(tone)
        self.text.setText(text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._fade.stop()
        if motion_enabled():
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._opacity.setOpacity(1.0)
        self._timer.start(duration_ms)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)

    def _fade_out(self) -> None:
        if not motion_enabled():
            self.hide()
            return
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self._opacity.opacity() < 0.05:
            self.hide()
