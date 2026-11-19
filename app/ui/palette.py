"""Ctrl+K command palette: jump to any page or tweak, or run a command, from the keyboard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QSizePolicy, QVBoxLayout, QWidget

from app.ui.theme import ICONS
from app.ui.widgets import Glyph, active_palette, divider, glyph_icon, kbd, label


@dataclass
class PaletteEntry:
    kind: str  # "page" | "tweak" | "command"
    title: str
    subtitle: str
    glyph: str
    run: Callable[[], None]
    keywords: str = ""
    haystack: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.haystack = " ".join((self.title, self.subtitle, self.keywords, self.kind)).casefold()


def score(entry: PaletteEntry, terms: list[str]) -> int | None:
    if not terms:
        return {"command": 0, "page": 1, "tweak": 2}.get(entry.kind, 3)
    if not all(term in entry.haystack for term in terms):
        return None
    title = entry.title.casefold()
    first = terms[0]
    if title.startswith(first):
        return 0
    if any(word.startswith(first) for word in title.split()):
        return 1
    if first in title:
        return 2
    return 3


class CommandPalette(QFrame):
    MAX_RESULTS = 60

    def __init__(self, parent: QWidget, provider: Callable[[], list[PaletteEntry]]) -> None:
        super().__init__(parent)
        self.provider = provider
        self.entries: list[PaletteEntry] = []
        self.visible_entries: list[PaletteEntry] = []
        self.setObjectName("paletteScrim")
        self.hide()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 90, 0, 0)
        outer.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.card = QFrame()
        self.card.setObjectName("paletteCard")
        self.card.setFixedWidth(640)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(14, 4, 14, 12)
        card_layout.setSpacing(4)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        search_row.addWidget(Glyph(ICONS["search"], size_pt=12))
        self.input = QLineEdit()
        self.input.setObjectName("paletteInput")
        self.input.setPlaceholderText("Search tweaks, pages, and commands")
        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        search_row.addWidget(self.input, 1)
        search_row.addWidget(kbd("Esc"))
        card_layout.addLayout(search_row)
        card_layout.addWidget(divider())
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setIconSize(QSize(18, 18))
        self.list.setUniformItemSizes(True)
        self.list.setFixedHeight(400)
        self.list.itemActivated.connect(lambda _item: self._activate())
        self.list.itemClicked.connect(lambda _item: self._activate())
        card_layout.addWidget(self.list)
        self.hint = label("↑↓ to move  ·  Enter to open  ·  Esc to close", "subtle")
        card_layout.addWidget(self.hint)
        self.card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        outer.addWidget(self.card, 0, Qt.AlignHCenter | Qt.AlignTop)
        outer.addStretch(1)

    # -- show / hide
    def open(self) -> None:
        self.entries = self.provider()
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.input.clear()
        self._filter("")
        self.show()
        self.raise_()
        self.input.setFocus()

    def close_palette(self) -> None:
        self.hide()

    def mousePressEvent(self, event) -> None:  # pragma: no cover - UI path
        if not self.card.geometry().contains(event.position().toPoint()):
            self.close_palette()
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.close_palette()
                return True
            if key in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if key == Qt.Key_Down else -1)
                if self.list.count():
                    self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._activate()
                return True
        return super().eventFilter(watched, event)

    # -- results
    def _filter(self, text: str) -> None:
        terms = text.casefold().split()
        ranked = [(rank, index, entry) for index, entry in enumerate(self.entries) if (rank := score(entry, terms)) is not None]
        ranked.sort(key=lambda item: (item[0], item[1]))
        self.visible_entries = [entry for _rank, _index, entry in ranked[: self.MAX_RESULTS]]
        self.list.clear()
        palette = active_palette()
        for entry in self.visible_entries:
            item = QListWidgetItem(glyph_icon(entry.glyph, palette.accent if entry.kind == "command" else palette.text_muted), f"{entry.title}    —  {entry.subtitle}")
            item.setSizeHint(QSize(0, 38))
            self.list.addItem(item)
        self.list.setFixedHeight(max(1, min(len(self.visible_entries), 10)) * 38 + 8)
        if self.visible_entries:
            self.list.setCurrentRow(0)

    def _activate(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.visible_entries):
            entry = self.visible_entries[row]
            self.close_palette()
            entry.run()
