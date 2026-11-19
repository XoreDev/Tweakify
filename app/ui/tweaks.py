"""Page scaffolding plus the tweak list: section cards made of dense, scannable rows."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.controller import LOADING_RUNTIME_MESSAGE
from app.domain.models import ActionKind, SafetyTier
from app.ui.theme import ICONS
from app.ui.widgets import (
    EmptyState,
    SegmentedControl,
    StatusChip,
    ToggleSwitch,
    button,
    clear_layout,
    configure_scroll_area,
    divider,
    label,
    set_dynamic,
    set_pointing_cursor,
)

CONTENT_MAX_WIDTH = 1180
RESTART_COPY = {"none": "", "explorer": "Explorer restart", "logoff": "Sign-out", "restart": "Restart"}
TIER_TONES = {"Safe": "safe", "Advanced": "advanced", "Experimental": "experimental"}


def centered(widget: QWidget, max_width: int = CONTENT_MAX_WIDTH) -> QWidget:
    """Wrap `widget` so it never grows past a readable line length on wide monitors."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.addStretch(1)
    widget.setMaximumWidth(max_width)
    row.addWidget(widget, 100)
    row.addStretch(1)
    return holder


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title_label = label(title, "pageTitle")
        self.subtitle_label = label(subtitle, "pageSubtitle", wrap=True)
        text.addWidget(self.title_label)
        text.addWidget(self.subtitle_label)
        layout.addLayout(text, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)


class ScrollablePage(QFrame):
    """Header + scrolling body, centered to a max content width."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea()
        configure_scroll_area(self.scroll)
        content = QWidget()
        self.viewport_layout = QVBoxLayout(content)
        self.viewport_layout.setContentsMargins(32, 28, 28, 40)
        self.viewport_layout.setSpacing(20)
        self.header = PageHeader(title, subtitle)
        self.header_card = self.header
        self.title_label = self.header.title_label
        self.subtitle_label = self.header.subtitle_label
        self.viewport_layout.addWidget(self.header)
        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(16)
        self.viewport_layout.addLayout(self.body_layout)
        self.viewport_layout.addStretch(1)
        self.scroll.setWidget(centered(content))
        outer.addWidget(self.scroll, 1)


# ----------------------------------------------------------------- tweak row
class TweakRow(QFrame):
    """One tweak: title, plain-language description, current state, and a switch."""

    def __init__(self, action, decision, controller, on_change) -> None:
        super().__init__()
        self.action = action
        self.decision = decision
        self.controller = controller
        self.on_change = on_change
        self.is_maintenance = action.definition.kind == ActionKind.MAINTENANCE
        self._render_key: tuple | None = None
        self.setObjectName("tweakRow")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        definition = action.definition

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 18, 0)
        outer.setSpacing(0)
        self.staged_bar = QFrame()
        self.staged_bar.setObjectName("stagedBar")
        outer.addWidget(self.staged_bar)

        body = QVBoxLayout()
        body.setContentsMargins(15, 14, 0, 14)
        body.setSpacing(4)
        outer.addLayout(body, 1)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = label(definition.title, "rowTitle")
        top.addWidget(self.title_label)
        tier = definition.safety_tier.value
        if definition.safety_tier != SafetyTier.SAFE:
            top.addWidget(StatusChip(tier, tone=TIER_TONES.get(tier, "muted")))
        restart = RESTART_COPY.get(definition.restart_requirement.value, "")
        if restart:
            top.addWidget(StatusChip(restart, tone="muted"))
        top.addStretch(1)
        body.addLayout(top)

        self.summary_label = label(definition.description, "rowBody", wrap=True)
        body.addWidget(self.summary_label)

        self.reason_label = label("", "rowReason", wrap=True)
        body.addWidget(self.reason_label)
        meta = QHBoxLayout()
        meta.setSpacing(0)
        self.details_button = QPushButton(f"Details  {ICONS['chevron_down']}")
        self.details_button.setObjectName("detailsLink")
        self.details_button.setCheckable(True)
        set_pointing_cursor(self.details_button)
        self.details_button.toggled.connect(self._toggle_details)
        meta.addWidget(self.details_button)
        meta.addStretch(1)
        body.addLayout(meta)

        self.details_panel = QFrame()
        self.details_panel.setObjectName("detailsPanel")
        grid = QGridLayout(self.details_panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for index, (key, value) in enumerate(
            (
                ("WHAT IT CHANGES", definition.what_it_changes),
                ("WHY IT HELPS", definition.why_it_may_help),
                ("TRADE-OFF", definition.downside),
                ("ROLLBACK", definition.rollback),
            )
        ):
            cell = QVBoxLayout()
            cell.setSpacing(3)
            cell.addWidget(label(key, "detailKey"))
            cell.addWidget(label(value, "detailValue", wrap=True))
            grid.addLayout(cell, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.details_panel.setVisible(False)
        body.addSpacing(2)
        body.addWidget(self.details_panel)
        self.details_label = self.details_panel

        controls = QHBoxLayout()
        controls.setSpacing(12)
        controls.setContentsMargins(16, 14, 0, 0)
        controls.setAlignment(Qt.AlignTop)
        state_column = QVBoxLayout()
        state_column.setSpacing(2)
        state_column.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.current_state_chip = label("", "stateText")
        self.current_state_chip.setAlignment(Qt.AlignRight)
        self.changed_chip = label("", "stateText")
        self.changed_chip.setProperty("tone", "changed")
        self.changed_chip.setAlignment(Qt.AlignRight)
        self.changed_chip.hide()
        state_column.addWidget(self.current_state_chip)
        state_column.addWidget(self.changed_chip)
        controls.addLayout(state_column)
        if self.is_maintenance:
            self.toggle = QPushButton("Run")
            self.toggle.setObjectName("runButton")
            set_pointing_cursor(self.toggle)
            self.toggle.clicked.connect(lambda _checked=False: self._handle_toggle())
        else:
            self.toggle = ToggleSwitch()
            self.toggle.clicked.connect(self._handle_toggle)
        self.toggle.setAccessibleName(definition.title)
        controls.addWidget(self.toggle, 0, Qt.AlignTop)
        outer.addLayout(controls)
        self.refresh()

    # -- interaction
    def _toggle_details(self, expanded: bool) -> None:
        self.details_panel.setVisible(expanded)
        self.details_button.setText(f"{'Hide' if expanded else 'Details'}  {ICONS['chevron_up' if expanded else 'chevron_down']}")

    def _handle_toggle(self, checked: bool = False) -> None:
        action_id = self.action.definition.id
        if self.is_maintenance:
            # Run toggles the one-shot task in and out of the plan.
            self.controller.stage_action(action_id, not self.controller.is_changed(action_id))
        else:
            self.controller.stage_action(action_id, checked)
        self.refresh()
        self.on_change()

    def set_target_state(self, state: bool) -> None:
        if not self.toggle.isEnabled():
            return
        self.controller.stage_action(self.action.definition.id, state)
        self.refresh()
        self.on_change()

    def flash(self) -> None:
        set_dynamic(self, "flash", True)
        QTimer.singleShot(1400, lambda: set_dynamic(self, "flash", False))

    # -- state
    def matches(self, mode: str) -> bool:
        action_id = self.action.definition.id
        if mode == "recommended":
            return self.action.definition.safety_tier == SafetyTier.SAFE
        if mode == "active":
            return (not self.is_maintenance) and self.controller.current_state(action_id)
        if mode == "pending":
            return self.controller.is_changed(action_id)
        return True

    def refresh(self) -> None:
        action_id = self.action.definition.id
        pending = self.controller.runtime_pending
        changed = (not pending) and self.controller.is_changed(action_id)
        live = None if (pending or self.is_maintenance) else self.controller.current_state(action_id)
        target = None if (pending or self.is_maintenance) else self.controller.target_state(action_id)
        key = (pending, changed, live, target, self.decision.allowed, tuple(self.decision.reasons), tuple(self.decision.warnings))
        if key == self._render_key:
            return
        self._render_key = key

        set_dynamic(self, "staged", changed)
        set_dynamic(self.staged_bar, "active", changed)

        if pending:
            self.current_state_chip.setText("Scanning")
            set_dynamic(self.current_state_chip, "tone", "")
            self.changed_chip.hide()
            self.toggle.blockSignals(True)
            if not self.is_maintenance:
                self.toggle.setChecked(False)
                self.toggle.setText("Off")
            self.toggle.blockSignals(False)
            self.toggle.setEnabled(False)
            self.reason_label.setText(LOADING_RUNTIME_MESSAGE)
            self.reason_label.setVisible(True)
            set_dynamic(self.reason_label, "blocked", False)
            return

        if self.is_maintenance:
            self.current_state_chip.setText("One-time task")
            set_dynamic(self.current_state_chip, "tone", "")
            self.toggle.setText("Queued" if changed else "Run")
            set_dynamic(self.toggle, "staged", changed)
            self.changed_chip.setText("Runs on Apply")
        else:
            self.current_state_chip.setText("On" if live else "Off")
            set_dynamic(self.current_state_chip, "tone", "on" if live else "")
            self.toggle.blockSignals(True)
            self.toggle.setChecked(bool(target))
            self.toggle.setText("On" if target else "Off")
            self.toggle.blockSignals(False)
            self.changed_chip.setText(f"Pending → {'On' if target else 'Off'}")
        self.changed_chip.setVisible(changed)

        if self.decision.allowed:
            self.toggle.setEnabled(True)
            self.reason_label.setText("  ·  ".join(self.decision.warnings))
            self.reason_label.setVisible(bool(self.decision.warnings))
            set_dynamic(self.reason_label, "blocked", False)
        else:
            self.toggle.setEnabled(False)
            self.reason_label.setText("Unavailable: " + "  ·  ".join(self.decision.reasons))
            self.reason_label.setVisible(True)
            set_dynamic(self.reason_label, "blocked", True)


ActionCard = TweakRow  # 1.1 name, kept for callers and tests


class SectionGroup(QFrame):
    """A titled card holding tweak rows separated by hairlines."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("sectionGroup")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 0)
        self.title_label = label(title.upper(), "eyebrow")
        header.addWidget(self.title_label)
        header.addStretch(1)
        self.count_label = label("", "subtle")
        header.addWidget(self.count_label)
        layout.addLayout(header)
        if subtitle:
            layout.addWidget(label(subtitle, "muted", wrap=True))
        self.card = QFrame()
        self.card.setObjectName("card")
        self.cards_layout = QVBoxLayout(self.card)
        self.cards_layout.setContentsMargins(0, 2, 0, 2)
        self.cards_layout.setSpacing(0)
        layout.addWidget(self.card)
        self.rows: list[TweakRow] = []
        self._dividers: list[QFrame] = []

    def add_row(self, row: TweakRow) -> None:
        if self.rows:
            line = divider()
            self._dividers.append(line)
            self.cards_layout.addWidget(line)
        self.rows.append(row)
        self.cards_layout.addWidget(row)
        self.count_label.setText(f"{len(self.rows)}")

    def apply_visibility(self, predicate) -> int:
        visible = 0
        for index, row in enumerate(self.rows):
            show = predicate(row)
            row.setVisible(show)
            if index > 0:
                self._dividers[index - 1].setVisible(show and visible > 0)
            visible += int(show)
        self.setVisible(visible > 0)
        return visible


class ModulePage(ScrollablePage):
    def __init__(self, module_id: str, title: str, subtitle: str, on_stage_recommended=None) -> None:
        super().__init__(title, subtitle)
        self.module_id = module_id
        self.filter_mode = "all"
        self.groups: list[SectionGroup] = []
        self.stats_label = label("", "subtle")
        self.header.subtitle_label.setText(subtitle)
        self.stage_recommended_button = button(
            "Enable recommended", "ghostButton", on_stage_recommended,
            tooltip="Stage every Safe tweak on this page that is still off. Nothing changes until you apply.",
        )
        self.header.actions.addWidget(self.stage_recommended_button)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self.filter = SegmentedControl(
            [("all", "All"), ("recommended", "Recommended"), ("active", "Active"), ("pending", "Pending")]
        )
        self.filter.changed.connect(self.set_filter)
        toolbar.addWidget(self.filter)
        toolbar.addStretch(1)
        toolbar.addWidget(self.stats_label)
        self.body_layout.addLayout(toolbar)
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(22)
        self.body_layout.addLayout(self.content_layout)
        self.empty_state = EmptyState(ICONS["filter"], "Nothing matches this filter", "Switch back to All to see every tweak on this page.")
        self.empty_state.hide()
        self.body_layout.addWidget(self.empty_state)

    def clear(self) -> None:
        self.groups = []
        clear_layout(self.content_layout)

    def set_filter(self, mode: str) -> None:
        self.filter_mode = mode
        self.apply_filter()

    def apply_filter(self) -> None:
        total = sum(group.apply_visibility(lambda row: row.matches(self.filter_mode)) for group in self.groups)
        self.empty_state.setVisible(bool(self.groups) and total == 0)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        rows = [row for group in self.groups for row in group.rows]
        if not rows:
            self.stats_label.setText("")
            return
        controller = rows[0].controller
        if controller.runtime_pending:
            self.stats_label.setText(f"{len(rows)} tweaks  ·  scanning")
            return
        active = sum(1 for row in rows if not row.is_maintenance and controller.current_state(row.action.definition.id))
        pending = sum(1 for row in rows if controller.is_changed(row.action.definition.id))
        self.filter.set_label("pending", f"Pending · {pending}" if pending else "Pending")
        self.stats_label.setText(f"{len(rows)} tweaks  ·  {active} active  ·  {pending} pending")


# ----------------------------------------------------------------- startup
class StartupEntryCard(QFrame):
    def __init__(self, entry, controller, on_change) -> None:
        super().__init__()
        self.entry_id = entry.id
        self.controller = controller
        self.on_change = on_change
        self.setObjectName("tweakRow")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 18, 0)
        outer.setSpacing(0)
        self.staged_bar = QFrame()
        self.staged_bar.setObjectName("stagedBar")
        outer.addWidget(self.staged_bar)
        body = QVBoxLayout()
        body.setContentsMargins(15, 12, 0, 12)
        body.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = label(entry.name, "rowTitle")
        top.addWidget(self.title_label)
        self.source_chip = StatusChip(tone="muted")
        self.location_chip = StatusChip(tone="muted")
        self.duplicate_chip = StatusChip("Duplicate", tone="changed")
        self.duplicate_chip.hide()
        for chip in (self.source_chip, self.location_chip, self.duplicate_chip):
            top.addWidget(chip)
        top.addStretch(1)
        body.addLayout(top)
        self.meta_label = label("", "rowBody", wrap=True)
        self.command_label = label("", "mono", wrap=True)
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.addWidget(self.meta_label)
        body.addWidget(self.command_label)
        outer.addLayout(body, 1)
        controls = QHBoxLayout()
        controls.setContentsMargins(16, 12, 0, 0)
        controls.setSpacing(12)
        controls.setAlignment(Qt.AlignTop)
        state = QVBoxLayout()
        state.setSpacing(2)
        self.current_state_chip = label("", "stateText")
        self.current_state_chip.setAlignment(Qt.AlignRight)
        self.changed_chip = label("", "stateText")
        self.changed_chip.setProperty("tone", "changed")
        self.changed_chip.hide()
        state.addWidget(self.current_state_chip)
        state.addWidget(self.changed_chip)
        controls.addLayout(state)
        self.toggle = ToggleSwitch()
        self.toggle.setAccessibleName(entry.name)
        self.toggle.clicked.connect(self._handle_toggle)
        controls.addWidget(self.toggle, 0, Qt.AlignTop)
        outer.addLayout(controls)
        self.refresh()

    def refresh(self) -> None:
        entry = self.controller.startup_inventory_by_id[self.entry_id]
        current = self.controller.current_startup_entry_enabled(self.entry_id)
        target = self.controller.target_startup_entry_enabled(self.entry_id)
        changed = self.controller.is_startup_entry_changed(self.entry_id)
        self.current_state_chip.setText("On" if current else "Off")
        set_dynamic(self.current_state_chip, "tone", "on" if current else "")
        self.toggle.blockSignals(True)
        self.toggle.setChecked(target)
        self.toggle.setText("On" if target else "Off")
        self.toggle.blockSignals(False)
        self.changed_chip.setText(f"Pending → {'On' if target else 'Off'}")
        self.changed_chip.setVisible(changed)
        set_dynamic(self, "staged", changed)
        set_dynamic(self.staged_bar, "active", changed)
        self.source_chip.setText("Registry" if entry.source_kind == "registry" else "Startup folder")
        self.location_chip.setText(entry.location)
        self.duplicate_chip.setHidden(not entry.duplicate)
        status = ""
        if entry.status_source == "windows_disabled":
            status = "  ·  Disabled in Windows Startup Apps"
        elif entry.status_source == "tweakify_disabled":
            status = "  ·  Disabled by Tweakify"
        self.meta_label.setText(f"{entry.scope.title()} scope{status}")
        self.command_label.setText(entry.command or entry.original_path or entry.file_path or "Command unavailable")

    def _handle_toggle(self, checked: bool) -> None:
        self.controller.stage_startup_entry(self.entry_id, checked)
        self.refresh()
        self.on_change(startup_entry_id=self.entry_id)

    def set_target_state(self, state: bool) -> None:
        self.controller.stage_startup_entry(self.entry_id, state)
        self.refresh()
        self.on_change(startup_entry_id=self.entry_id)


class StartupEntriesPanel(QFrame):
    def __init__(self, controller, on_change) -> None:
        super().__init__()
        self.controller = controller
        self.on_change = on_change
        self.entry_cards: dict[str, StartupEntryCard] = {}
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.summary_label = label("", "muted", wrap=True)
        header.addWidget(self.summary_label, 1)
        self.disable_all_button = button(
            "Disable all", "ghostButton", self._stage_disable_all,
            tooltip="Stage every enabled startup entry off. Nothing changes until Apply.",
        )
        header.addWidget(self.disable_all_button)
        layout.addLayout(header)
        self.duplicates_label = label("", "accentText", wrap=True)
        self.duplicates_label.hide()
        layout.addWidget(self.duplicates_label)
        self.list_card = QFrame()
        self.list_card.setObjectName("card")
        self.entries_layout = QVBoxLayout(self.list_card)
        self.entries_layout.setContentsMargins(0, 2, 0, 2)
        self.entries_layout.setSpacing(0)
        layout.addWidget(self.list_card)
        self.refresh()

    def _stage_disable_all(self) -> None:
        self.controller.stage_disable_all_startup()
        self.refresh_staged_state()
        self.on_change()

    def refresh(self) -> None:
        clear_layout(self.entries_layout)
        self.entry_cards = {}
        inventory = self.controller.startup_inventory
        self.refresh_summary()
        duplicates = inventory["duplicates"]
        self.duplicates_label.setText("Duplicate entries: " + ", ".join(duplicates))
        self.duplicates_label.setVisible(bool(duplicates))
        for index, entry in enumerate(inventory["items"]):
            if index:
                self.entries_layout.addWidget(divider())
            card = StartupEntryCard(entry, self.controller, self.on_change)
            self.entry_cards[entry.id] = card
            self.entries_layout.addWidget(card)
        if not inventory["items"]:
            message = (
                ("Scanning startup entries", "Run keys and Startup folders are being read in the background.")
                if self.controller.runtime_pending
                else ("No startup entries", "Nothing launches from Run keys or Startup folders.")
            )
            self.entries_layout.addWidget(EmptyState(ICONS["clock"], *message))

    def refresh_summary(self) -> None:
        inventory = self.controller.startup_inventory
        if self.controller.runtime_pending:
            self.summary_label.setText("Scanning Run keys and Startup folders...")
            return
        enabled = sum(1 for entry in inventory["items"] if entry.enabled)
        self.summary_label.setText(
            f"{inventory['count']} apps launch with Windows  ·  {enabled} on  ·  "
            f"{inventory['count'] - enabled} off  ·  {len(inventory['duplicates'])} duplicate(s)"
        )

    def refresh_staged_state(self) -> None:
        self.refresh_summary()
        for card in self.entry_cards.values():
            card.refresh()

    def refresh_entry(self, entry_id: str) -> None:
        self.refresh_summary()
        card = self.entry_cards.get(entry_id)
        if card is None:
            self.refresh()
            return
        card.refresh()


class PersistedTabWidget(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self.requested_index = 0
        self.currentChanged.connect(self._remember_index)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - Qt API
        self.requested_index = index
        super().setCurrentIndex(index)

    def _remember_index(self, index: int) -> None:
        self.requested_index = index


class StartupPage(QFrame):
    APPS_TAB = 0
    TWEAKS_TAB = 1

    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self._saved_state: dict[str, int] = {"tab_index": 0, "tweaks_scroll": 0, "apps_scroll": 0}
        self.setObjectName("page")
        # The tabs scroll individually, so the header + tabs column is centered as a
        # whole (the other pages center inside their single scroll area instead).
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        column = QWidget()
        column.setMaximumWidth(CONTENT_MAX_WIDTH + 60)
        root.addStretch(1)
        root.addWidget(column, 100)
        root.addStretch(1)
        outer = QVBoxLayout(column)
        outer.setContentsMargins(32, 28, 28, 0)
        outer.setSpacing(18)
        self.header_card = PageHeader("Startup", "Everything that launches with Windows, plus login-time tweaks.")
        self.title_label = self.header_card.title_label
        outer.addWidget(self.header_card)

        self.tabs = PersistedTabWidget()
        self.tabs.currentChanged.connect(self._apply_saved_state)
        self.apps_scroll, self.apps_layout = self._scroll("startupAppsScroll", self._remember_apps_scroll)
        self.tweaks_scroll, self.tweaks_layout = self._scroll("startupTweaksScroll", self._remember_tweaks_scroll)
        self.tabs.addTab(self.apps_scroll, "Startup Apps")
        self.tabs.addTab(self.tweaks_scroll, "Startup Tweaks")
        outer.addWidget(self.tabs, 1)
        self.column_layout = outer

    def _scroll(self, name: str, remember):
        scroll = QScrollArea()
        scroll.setObjectName(name)
        configure_scroll_area(scroll)
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 14, 4, 40)
        layout.setSpacing(20)
        layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(view)
        scroll.verticalScrollBar().valueChanged.connect(remember)
        return scroll, layout

    def clear_apps(self) -> None:
        clear_layout(self.apps_layout)

    def clear_tweaks(self) -> None:
        clear_layout(self.tweaks_layout)

    def capture_state(self) -> dict[str, int]:
        if self.tweaks_scroll.verticalScrollBar().value() > 0:
            self._saved_state["tweaks_scroll"] = self.tweaks_scroll.verticalScrollBar().value()
        if self.apps_scroll.verticalScrollBar().value() > 0:
            self._saved_state["apps_scroll"] = self.apps_scroll.verticalScrollBar().value()
        self._saved_state["tab_index"] = self.tabs.requested_index
        return dict(self._saved_state)

    def restore_state(self, state: dict[str, int] | None) -> None:
        if not state:
            return
        self._saved_state = dict(state)
        self.tabs.setCurrentIndex(int(state.get("tab_index", 0)))
        self._apply_saved_state()
        QTimer.singleShot(0, self._apply_saved_state)

    def _apply_saved_state(self, _index: int | None = None) -> None:
        self.tweaks_scroll.verticalScrollBar().setValue(int(self._saved_state.get("tweaks_scroll", 0)))
        self.apps_scroll.verticalScrollBar().setValue(int(self._saved_state.get("apps_scroll", 0)))

    def _remember_tweaks_scroll(self, value: int) -> None:
        if value > 0:
            self._saved_state["tweaks_scroll"] = value

    def _remember_apps_scroll(self, value: int) -> None:
        if value > 0:
            self._saved_state["apps_scroll"] = value
