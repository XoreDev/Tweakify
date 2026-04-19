from __future__ import annotations

import ctypes
from functools import partial
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
    Qt,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.controller import LOADING_RUNTIME_MESSAGE, MODULES
from app.domain.models import ActionKind
from app.copy import ADMIN_PRIVILEGE_NOTE
from app.ui.theme import build_app_stylesheet, resolve_theme_mode


NVIDIA_PROFILE_INSPECTOR_RELEASES_URL = "https://github.com/Orbmu2k/nvidiaProfileInspector/releases"


def set_pointing_cursor(widget) -> None:
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
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


def apply_windows_backdrop(window: QMainWindow, resolved_theme_mode: str) -> None:
    try:
        hwnd = int(window.winId())
        dark_mode = ctypes.c_int(1 if resolved_theme_mode == "dark" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        build = getattr(ctypes.windll.kernel32, "GetVersion", lambda: 0)() & 0xFFFF
        if build >= 22000:
            backdrop_type = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop_type), ctypes.sizeof(backdrop_type))
    except Exception:
        return


class WorkerSignals(QObject):
    finished = Signal(str, int, object)
    failed = Signal(str, int, str)


class BackgroundTask(QRunnable):
    def __init__(self, domain: str, sequence: int, fn) -> None:
        super().__init__()
        self.domain = domain
        self.sequence = sequence
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # pragma: no cover - exercised only on runtime failures
            self.signals.failed.emit(self.domain, self.sequence, str(exc))
            return
        self.signals.finished.emit(self.domain, self.sequence, result)


class RefreshCoordinator(QObject):
    result_ready = Signal(str, object)
    error = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self._sequences: dict[str, int] = {}

    def request(self, domain: str, fn) -> None:
        sequence = self._sequences.get(domain, 0) + 1
        self._sequences[domain] = sequence
        task = BackgroundTask(domain, sequence, fn)
        task.signals.finished.connect(self._handle_finished)
        task.signals.failed.connect(self._handle_failed)
        self.pool.start(task)

    def _handle_finished(self, domain: str, sequence: int, result: object) -> None:
        if self._sequences.get(domain) != sequence:
            return
        self.result_ready.emit(domain, result)

    def _handle_failed(self, domain: str, sequence: int, message: str) -> None:
        if self._sequences.get(domain) != sequence:
            return
        self.error.emit(domain, message)


class StatusChip(QLabel):
    def __init__(self, text: str = "", tone: str = "muted", object_name: str = "chipLabel") -> None:
        super().__init__(text)
        self.setObjectName(object_name)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class PersistedTabWidget(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self.requested_index = 0
        self.currentChanged.connect(self._remember_index)

    def setCurrentIndex(self, index: int) -> None:
        self.requested_index = index
        super().setCurrentIndex(index)

    def _remember_index(self, index: int) -> None:
        self.requested_index = index


class MetricCard(QFrame):
    def __init__(self, title: str, value: str, detail: str) -> None:
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("eyebrowLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setWordWrap(True)
        self.detail_label.setObjectName("captionLabel")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)


class ActionCard(QFrame):
    def __init__(self, action, decision, controller, on_change) -> None:
        super().__init__()
        self.action = action
        self.controller = controller
        self.on_change = on_change
        self.decision = decision
        self.is_maintenance = action.definition.kind == ActionKind.MAINTENANCE
        self.setObjectName("actionCard")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)

        title_column = QVBoxLayout()
        title_column.setSpacing(4)
        self.title_label = QLabel(action.definition.title)
        self.title_label.setObjectName("sectionTitle")
        self.summary_label = QLabel(action.definition.description)
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("captionLabel")
        title_column.addWidget(self.title_label)
        title_column.addWidget(self.summary_label)
        header.addLayout(title_column, 1)

        control_column = QVBoxLayout()
        control_column.setSpacing(8)
        control_column.setAlignment(Qt.AlignTop)
        self.current_state_chip = StatusChip(object_name="stateChip")
        self.changed_chip = StatusChip("Staged", tone="changed", object_name="changedChip")
        self.changed_chip.hide()
        self.toggle = QPushButton()
        self.toggle.setObjectName("actionButton" if self.is_maintenance else "pillSwitch")
        self.toggle.setCheckable(not self.is_maintenance)
        set_pointing_cursor(self.toggle)
        self.toggle.clicked.connect(self._handle_toggle)
        control_column.addWidget(self.current_state_chip, alignment=Qt.AlignRight)
        control_column.addWidget(self.changed_chip, alignment=Qt.AlignRight)
        control_column.addWidget(self.toggle, alignment=Qt.AlignRight)
        header.addLayout(control_column)
        layout.addLayout(header)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(StatusChip(self.action.definition.safety_tier.value, tone="safety"))
        chip_row.addWidget(StatusChip(self.action.definition.scope.value.title(), tone="muted"))
        chip_row.addWidget(StatusChip(self._restart_copy(), tone="muted"))
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        self.reason_label.setObjectName("captionLabel")
        layout.addWidget(self.reason_label)

        self.details_label = QLabel(
            f"What it changes: {action.definition.what_it_changes}\n"
            f"Why it may help: {action.definition.why_it_may_help}\n"
            f"Downside: {action.definition.downside}\n"
            f"Rollback: {action.definition.rollback}"
        )
        self.details_label.setWordWrap(True)
        self.details_label.setObjectName("detailLabel")
        layout.addWidget(self.details_label)
        self.refresh()

    def _restart_copy(self) -> str:
        mapping = {
            "none": "Live apply",
            "explorer": "Explorer refresh",
            "logoff": "Logoff required",
            "restart": "Restart required",
        }
        return mapping[self.action.definition.restart_requirement.value]

    def refresh(self) -> None:
        changed = self.controller.is_changed(self.action.definition.id)

        if self.controller.runtime_pending:
            self.current_state_chip.setText("Loading")
            self.current_state_chip.set_tone("muted")
            self.toggle.blockSignals(True)
            if not self.is_maintenance:
                self.toggle.setChecked(False)
                self.toggle.setProperty("checked", False)
            else:
                self.toggle.setProperty("staged", False)
            self.toggle.setText("Loading")
            self.toggle.style().unpolish(self.toggle)
            self.toggle.style().polish(self.toggle)
            self.toggle.blockSignals(False)
            self.toggle.setEnabled(False)
            self.changed_chip.setHidden(True)
            self.reason_label.setText(LOADING_RUNTIME_MESSAGE)
            return

        if self.is_maintenance:
            self.current_state_chip.setText("One-shot")
            self.current_state_chip.set_tone("muted")
            self.toggle.blockSignals(True)
            self.toggle.setProperty("staged", changed)
            self.toggle.setText("Added" if changed else "Add To Review")
            self.toggle.style().unpolish(self.toggle)
            self.toggle.style().polish(self.toggle)
            self.toggle.blockSignals(False)
            self.changed_chip.setText("Ready")
        else:
            live_state = self.controller.current_state(self.action.definition.id)
            target_state = self.controller.target_state(self.action.definition.id)
            self.current_state_chip.setText("On" if live_state else "Off")
            self.current_state_chip.set_tone("on" if live_state else "off")
            self.toggle.blockSignals(True)
            self.toggle.setChecked(target_state)
            self.toggle.setProperty("checked", target_state)
            self.toggle.setText("On" if target_state else "Off")
            self.toggle.style().unpolish(self.toggle)
            self.toggle.style().polish(self.toggle)
            self.toggle.blockSignals(False)
            self.changed_chip.setText("Staged")

        self.changed_chip.setHidden(not changed)

        if self.decision.allowed:
            self.toggle.setEnabled(True)
            guidance = list(self.decision.warnings)
            if not guidance:
                guidance.append(f"Applies at {self.action.definition.scope.value} scope.")
            self.reason_label.setText(" | ".join(guidance))
        else:
            self.toggle.setEnabled(False)
            self.reason_label.setText("Why not: " + " | ".join(self.decision.reasons))

    def _handle_toggle(self, checked: bool = False) -> None:
        if self.is_maintenance:
            self.controller.stage_action(self.action.definition.id, True)
        else:
            self.controller.stage_action(self.action.definition.id, checked)
        self.refresh()
        self.on_change()

    def set_target_state(self, state: bool) -> None:
        if not self.toggle.isEnabled():
            return
        self.controller.stage_action(self.action.definition.id, state)
        self.refresh()
        self.on_change()


class SectionGroup(QFrame):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("sectionGroup")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QVBoxLayout()
        header.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        header.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setObjectName("captionLabel")
            header.addWidget(subtitle_label)
        layout.addLayout(header)

        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignTop)
        layout.addLayout(self.cards_layout)


class ScrollablePage(QFrame):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName("pagePanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        configure_scroll_area(self.scroll)
        viewport = QWidget()
        viewport.setObjectName("moduleViewport")
        self.viewport_layout = QVBoxLayout(viewport)
        self.viewport_layout.setSpacing(16)
        self.viewport_layout.setContentsMargins(0, 0, 0, 0)

        self.header_card = QFrame()
        self.header_card.setObjectName("heroPanel")
        header_layout = QVBoxLayout(self.header_card)
        header_layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleLabel")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("captionLabel")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label)
        self.viewport_layout.addWidget(self.header_card)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(14)
        self.viewport_layout.addLayout(self.body_layout)
        self.viewport_layout.addStretch(1)
        self.scroll.setWidget(viewport)
        outer.addWidget(self.scroll, 1)


class ModulePage(ScrollablePage):
    def __init__(self, module_id: str, title: str, subtitle: str) -> None:
        super().__init__(title, subtitle)
        self.module_id = module_id
        self.content_layout = self.body_layout

    def clear(self) -> None:
        clear_layout(self.content_layout)


class DashboardPage(ScrollablePage):
    def __init__(self, controller, request_refresh_callback) -> None:
        super().__init__(
            "Dashboard",
            "Verified diagnostics, staged tuning, and a persistent review rail without burying key controls.",
        )
        self.controller = controller
        self.request_refresh_callback = request_refresh_callback
        self.caption_label = self.subtitle_label

        self.summary_card = QFrame()
        self.summary_card.setObjectName("heroPanel")
        summary_layout = QVBoxLayout(self.summary_card)
        summary_layout.setSpacing(8)
        self.safety_label = QLabel()
        self.safety_label.setObjectName("sectionTitle")
        self.summary_caption = QLabel()
        self.summary_caption.setObjectName("captionLabel")
        self.summary_caption.setWordWrap(True)
        self.admin_notice_label = QLabel(ADMIN_PRIVILEGE_NOTE)
        self.admin_notice_label.setObjectName("captionLabel")
        self.admin_notice_label.setWordWrap(True)
        summary_layout.addWidget(self.safety_label)
        summary_layout.addWidget(self.summary_caption)
        summary_layout.addWidget(self.admin_notice_label)
        self.body_layout.addWidget(self.summary_card)

        quick_tools = QFrame()
        quick_tools.setObjectName("toolCard")
        quick_layout = QHBoxLayout(quick_tools)
        quick_layout.setSpacing(10)
        self.refresh_button = QPushButton("Refresh Diagnostics")
        self.refresh_button.setObjectName("ghostButton")
        self.restore_point_button = QPushButton("Create Restore Point")
        self.restore_point_button.setObjectName("ghostButton")
        self.task_manager_button = QPushButton("Open Task Manager")
        self.task_manager_button.setObjectName("ghostButton")
        for button in (self.refresh_button, self.restore_point_button, self.task_manager_button):
            set_pointing_cursor(button)
            quick_layout.addWidget(button)
        quick_layout.addStretch(1)
        self.body_layout.addWidget(quick_tools)

        metrics_container = QWidget()
        self.metrics_layout = QGridLayout(metrics_container)
        self.metrics_layout.setSpacing(12)
        self.body_layout.addWidget(metrics_container)

        self.blocked_card = QFrame()
        self.blocked_card.setObjectName("sectionGroup")
        blocked_layout = QVBoxLayout(self.blocked_card)
        blocked_title = QLabel("Current Blocks")
        blocked_title.setObjectName("sectionTitle")
        self.blocked_preview = QPlainTextEdit()
        self.blocked_preview.setReadOnly(True)
        self.blocked_preview.setFixedHeight(120)
        blocked_layout.addWidget(blocked_title)
        blocked_layout.addWidget(self.blocked_preview)
        self.body_layout.addWidget(self.blocked_card)

        self.history_title = QLabel("Recent Activity")
        self.history_title.setObjectName("sectionTitle")
        self.history_list = QListWidget()
        self.body_layout.addWidget(self.history_title)
        self.body_layout.addWidget(self.history_list)

        self.refresh_button.clicked.connect(self.request_refresh_callback)
        self.restore_point_button.clicked.connect(self._create_restore_point)
        self.task_manager_button.clicked.connect(self.controller.open_task_manager)

    def refresh(self, controller) -> None:
        self._refresh_metrics(controller)
        self.refresh_summary(controller)
        self.blocked_preview.setPlainText(controller.blocked_actions_text())
        self.history_list.clear()
        for transaction in controller.store.list_transactions()[:6]:
            QListWidgetItem(
                f"{transaction.created_at[:19]} | {', '.join(transaction.action_ids) or 'No actions'}",
                self.history_list,
            )

    def refresh_summary(self, controller) -> None:
        count = controller.total_staged_count()
        if controller.runtime_pending:
            self.safety_label.setText("Loading live runtime")
            self.summary_caption.setText(
                controller.machine_summary_text()
                + "\nLoading diagnostics, startup inventory, and compatibility in the background."
            )
            return
        self.safety_label.setText(f"{count} pending change(s)" if count else "No pending changes")
        self.summary_caption.setText(
            controller.machine_summary_text()
            + "\n"
            + (
                "Use the review panel to preview and apply the staged plan."
                if count
                else "Diagnostics are live. Stage actions from any module and review them here before you apply."
            )
        )

    def _refresh_metrics(self, controller) -> None:
        clear_layout(self.metrics_layout)
        for index, item in enumerate(controller.diagnostics.items):
            self.metrics_layout.addWidget(MetricCard(item.title, item.value, item.detail), index // 3, index % 3)

    def _create_restore_point(self) -> None:
        created = self.controller.create_restore_point()
        self.summary_caption.setText(
            self.summary_caption.text()
            + "\n"
            + ("Restore point request completed." if created else "Restore point request failed.")
        )


class StartupEntryCard(QFrame):
    def __init__(self, entry, controller, on_change) -> None:
        super().__init__()
        self.entry_id = entry.id
        self.controller = controller
        self.on_change = on_change
        self.setObjectName("actionCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        self.title_label = QLabel(entry.name)
        self.title_label.setObjectName("sectionTitle")
        self.meta_label = QLabel()
        self.meta_label.setObjectName("captionLabel")
        self.meta_label.setWordWrap(True)
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.meta_label)
        header.addLayout(text_column, 1)

        control_column = QVBoxLayout()
        control_column.setSpacing(8)
        control_column.setAlignment(Qt.AlignTop)
        self.current_state_chip = StatusChip(object_name="stateChip")
        self.changed_chip = StatusChip("Staged", tone="changed", object_name="changedChip")
        self.changed_chip.hide()
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setObjectName("pillSwitch")
        set_pointing_cursor(self.toggle)
        self.toggle.clicked.connect(self._handle_toggle)
        control_column.addWidget(self.current_state_chip, alignment=Qt.AlignRight)
        control_column.addWidget(self.changed_chip, alignment=Qt.AlignRight)
        control_column.addWidget(self.toggle, alignment=Qt.AlignRight)
        header.addLayout(control_column)
        layout.addLayout(header)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.source_chip = StatusChip(tone="muted")
        self.location_chip = StatusChip(tone="muted")
        self.duplicate_chip = StatusChip("Duplicate", tone="changed")
        self.duplicate_chip.hide()
        for chip in (self.source_chip, self.location_chip, self.duplicate_chip):
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        self.command_label = QLabel()
        self.command_label.setObjectName("detailLabel")
        self.command_label.setWordWrap(True)
        layout.addWidget(self.command_label)
        self.refresh()

    def refresh(self) -> None:
        entry = self.controller.startup_inventory_by_id[self.entry_id]
        current_enabled = self.controller.current_startup_entry_enabled(self.entry_id)
        target_enabled = self.controller.target_startup_entry_enabled(self.entry_id)
        changed = self.controller.is_startup_entry_changed(self.entry_id)

        self.current_state_chip.setText("On" if current_enabled else "Off")
        self.current_state_chip.set_tone("on" if current_enabled else "off")
        self.toggle.blockSignals(True)
        self.toggle.setChecked(target_enabled)
        self.toggle.setText("On" if target_enabled else "Off")
        self.toggle.setProperty("checked", target_enabled)
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)
        self.toggle.blockSignals(False)
        self.changed_chip.setHidden(not changed)

        self.source_chip.setText("Registry" if entry.source_kind == "registry" else "Startup Folder")
        self.location_chip.setText(entry.location)
        self.duplicate_chip.setHidden(not entry.duplicate)
        status_copy = ""
        if entry.status_source == "windows_disabled":
            status_copy = " | Disabled in Windows Startup Apps"
        elif entry.status_source == "tweakify_disabled":
            status_copy = " | Disabled by Tweakify"
        self.meta_label.setText(f"{entry.scope.title()} scope{status_copy}")
        self.command_label.setText(
            f"Command or path: {entry.command or entry.original_path or entry.file_path or 'Unavailable'}"
        )

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
        self.setObjectName("toolCard")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        title = QLabel("Startup Entries")
        title.setObjectName("sectionTitle")
        self.summary_label = QLabel()
        self.summary_label.setObjectName("captionLabel")
        self.summary_label.setWordWrap(True)
        self.duplicates_label = QLabel()
        self.duplicates_label.setObjectName("eyebrowLabel")
        self.duplicates_label.setWordWrap(True)
        self.duplicates_label.hide()
        self.entries_layout = QVBoxLayout()
        self.entries_layout.setSpacing(10)
        self.entries_layout.setAlignment(Qt.AlignTop)
        layout.addWidget(title)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.duplicates_label)
        layout.addLayout(self.entries_layout)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.entries_layout)
        self.entry_cards = {}
        inventory = self.controller.startup_inventory
        self.refresh_summary()
        if inventory["duplicates"]:
            self.duplicates_label.setText("Duplicates: " + ", ".join(inventory["duplicates"]))
            self.duplicates_label.show()
        else:
            self.duplicates_label.hide()
        for entry in inventory["items"]:
            card = StartupEntryCard(entry, self.controller, self.on_change)
            self.entry_cards[entry.id] = card
            self.entries_layout.addWidget(card)
        if not inventory["items"]:
            message = (
                "Startup inventory is loading in the background."
                if self.controller.runtime_pending
                else "No startup entries were detected in Run keys or Startup folders."
            )
            empty = QLabel(message)
            empty.setObjectName("captionLabel")
            empty.setWordWrap(True)
            self.entries_layout.addWidget(empty)

    def refresh_summary(self) -> None:
        inventory = self.controller.startup_inventory
        if self.controller.runtime_pending:
            self.summary_label.setText(
                "Startup entries are loading. Run keys and Startup folders are being scanned in the background."
            )
            return
        enabled_count = sum(1 for entry in inventory["items"] if entry.enabled)
        disabled_count = inventory["count"] - enabled_count
        self.summary_label.setText(
            f"{inventory['count']} startup entries detected | "
            f"{enabled_count} on | {disabled_count} off | "
            f"{len(inventory['duplicates'])} duplicate name(s)"
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


class StartupPage(QFrame):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self._saved_state: dict[str, int] = {
            "tab_index": 0,
            "tweaks_scroll": 0,
            "apps_scroll": 0,
        }
        self.setObjectName("pagePanel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        self.header_card = QFrame()
        self.header_card.setObjectName("heroPanel")
        header_layout = QVBoxLayout(self.header_card)
        header_layout.setSpacing(6)
        self.title_label = QLabel("Startup")
        self.title_label.setObjectName("titleLabel")
        self.subtitle_label = QLabel(
            "Startup inventory, duplicate detection, and safe login-time cleanup actions."
        )
        self.subtitle_label.setObjectName("captionLabel")
        self.subtitle_label.setWordWrap(True)
        header_layout.addWidget(self.title_label)
        header_layout.addWidget(self.subtitle_label)
        outer.addWidget(self.header_card)

        self.tabs = PersistedTabWidget()
        self.tabs.setObjectName("pageTabs")
        self.tabs.currentChanged.connect(self._apply_saved_state)
        self.tweaks_scroll = QScrollArea()
        self.tweaks_scroll.setObjectName("startupTweaksScroll")
        configure_scroll_area(self.tweaks_scroll)
        tweaks_view = QWidget()
        tweaks_view.setObjectName("moduleViewport")
        self.tweaks_layout = QVBoxLayout(tweaks_view)
        self.tweaks_layout.setSpacing(14)
        self.tweaks_layout.setContentsMargins(0, 0, 0, 0)
        self.tweaks_layout.setAlignment(Qt.AlignTop)
        self.tweaks_scroll.setWidget(tweaks_view)
        self.tweaks_scroll.verticalScrollBar().valueChanged.connect(self._remember_tweaks_scroll)

        self.apps_scroll = QScrollArea()
        self.apps_scroll.setObjectName("startupAppsScroll")
        configure_scroll_area(self.apps_scroll)
        apps_view = QWidget()
        apps_view.setObjectName("moduleViewport")
        self.apps_layout = QVBoxLayout(apps_view)
        self.apps_layout.setSpacing(12)
        self.apps_layout.setContentsMargins(0, 0, 0, 0)
        self.apps_layout.setAlignment(Qt.AlignTop)
        self.apps_scroll.setWidget(apps_view)
        self.apps_scroll.verticalScrollBar().valueChanged.connect(self._remember_apps_scroll)

        self.tabs.addTab(self.tweaks_scroll, "Startup Tweaks")
        self.tabs.addTab(self.apps_scroll, "Startup Apps")
        outer.addWidget(self.tabs, 1)

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
        QTimer.singleShot(0, lambda: QTimer.singleShot(0, self._apply_saved_state))

    def _apply_saved_state(self, _index: int | None = None) -> None:
        self.tweaks_scroll.verticalScrollBar().setValue(int(self._saved_state.get("tweaks_scroll", 0)))
        self.apps_scroll.verticalScrollBar().setValue(int(self._saved_state.get("apps_scroll", 0)))

    def _remember_tweaks_scroll(self, value: int) -> None:
        if value > 0:
            self._saved_state["tweaks_scroll"] = value

    def _remember_apps_scroll(self, value: int) -> None:
        if value > 0:
            self._saved_state["apps_scroll"] = value


class ReviewDrawer(QFrame):
    def __init__(self, controller, stage_refresh_callback, apply_callback) -> None:
        super().__init__()
        self.controller = controller
        self.stage_refresh_callback = stage_refresh_callback
        self.apply_callback = apply_callback
        self.result_message = ""
        self._apply_animation_frames = (
            "Applying staged changes.",
            "Applying staged changes..",
            "Applying staged changes...",
        )
        self._apply_animation_index = 0
        self._apply_animation_timer = QTimer(self)
        self._apply_animation_timer.setInterval(220)
        self._apply_animation_timer.timeout.connect(self._advance_apply_animation)
        self.setObjectName("reviewDrawer")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Review")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Staged changes live here. Nothing mutates the machine until Apply.")
        subtitle.setWordWrap(True)
        subtitle.setObjectName("captionLabel")
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("captionLabel")
        self.staged_list = QListWidget()
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.staged_list)
        layout.addWidget(self.plan_text, 1)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Preview")
        self.preview_button.setObjectName("ghostButton")
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("accentButton")
        self.clear_button = QPushButton("Discard")
        self.clear_button.setObjectName("ghostButton")
        for button in (self.preview_button, self.apply_button, self.clear_button):
            set_pointing_cursor(button)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.preview_button.clicked.connect(self.show_dry_run)
        self.apply_button.clicked.connect(self.apply)
        self.clear_button.clicked.connect(self.clear)
        self.refresh()

    def refresh(self) -> None:
        self.staged_list.clear()
        count = self.controller.total_staged_count()
        self.summary_label.setText(
            f"{count} pending change(s) staged for review." if count else "No pending changes."
        )
        if not count:
            self.plan_text.setPlainText(self.result_message or "Stage actions from any module to build a dry-run plan here.")

        for action_id, target_state in self.controller.staged_targets.items():
            action = self.controller.actions_by_id[action_id]
            if action.definition.kind == ActionKind.MAINTENANCE:
                label = f"{action.definition.title}: one-shot action staged"
            else:
                current_state = self.controller.current_state(action_id)
                label = (
                    f"{action.definition.title}: "
                    f"{'On' if current_state else 'Off'} -> {'On' if target_state else 'Off'}"
                )
            QListWidgetItem(label, self.staged_list)

        for entry_id, target_enabled in self.controller.staged_startup_entries.items():
            entry = self.controller.startup_inventory_by_id.get(entry_id)
            if entry is None:
                continue
            QListWidgetItem(
                f"Startup Entry {entry.name}: "
                f"{'On' if self.controller.current_startup_entry_enabled(entry_id) else 'Off'}"
                f" -> {'On' if target_enabled else 'Off'}",
                self.staged_list,
            )

        if count and self.controller.settings.auto_preview and not self._apply_animation_timer.isActive():
            self.result_message = ""
            self.plan_text.setPlainText(self.controller.preview_staged().dry_run_text)

    def show_dry_run(self) -> None:
        self.plan_text.setPlainText(self.controller.preview_staged().dry_run_text)

    def show_stage_result(self, message: str) -> None:
        self.result_message = message
        self.refresh()

    def apply(self) -> None:
        if not self.controller.total_staged_count():
            return
        if self.controller.settings.confirm_before_apply:
            answer = QMessageBox.question(
                self,
                "Apply staged changes",
                "Apply the staged plan now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self.set_busy(True)
        self._start_apply_animation()
        self.apply_callback()

    def clear(self) -> None:
        self.controller.clear_staging()
        self.result_message = "Pending changes discarded."
        self.plan_text.setPlainText(self.result_message)
        self.stage_refresh_callback()

    def show_apply_result(self, transaction) -> None:
        self._stop_apply_animation()
        self.set_busy(False)
        if transaction.requested_elevation:
            self.result_message = (
                "Machine-scope changes were serialized for the elevated helper. Re-run elevated to execute them."
            )
        else:
            self.result_message = "\n".join(result.message for result in transaction.results) or "Nothing applied."
        self.refresh()

    def show_error(self, message: str) -> None:
        self._stop_apply_animation()
        self.set_busy(False)
        self.result_message = f"Apply failed: {message}"
        self.plan_text.setPlainText(self.result_message)

    def set_busy(self, busy: bool) -> None:
        for button in (self.preview_button, self.apply_button, self.clear_button):
            button.setEnabled(not busy)

    def _start_apply_animation(self) -> None:
        self._apply_animation_index = 0
        self.result_message = self._apply_animation_frames[self._apply_animation_index]
        self.plan_text.setPlainText(self.result_message)
        if not self._apply_animation_timer.isActive():
            self._apply_animation_timer.start()

    def _advance_apply_animation(self) -> None:
        self._apply_animation_index = (self._apply_animation_index + 1) % len(self._apply_animation_frames)
        self.result_message = self._apply_animation_frames[self._apply_animation_index]
        self.plan_text.setPlainText(self.result_message)

    def _stop_apply_animation(self) -> None:
        if self._apply_animation_timer.isActive():
            self._apply_animation_timer.stop()


class PresetCardView(QFrame):
    def __init__(self, preset, controller, on_stage) -> None:
        super().__init__()
        self.preset_id = preset.id
        self.controller = controller
        self.on_stage = on_stage
        self.setObjectName("presetCard")

        row = QHBoxLayout(self)
        row.setSpacing(12)

        text_column = QVBoxLayout()
        self.title_label = QLabel(preset.title)
        self.title_label.setObjectName("sectionTitle")
        self.description_label = QLabel(preset.description)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("captionLabel")
        self.primary_label = QLabel()
        self.primary_label.setObjectName("metricValue")
        self.secondary_label = QLabel()
        self.secondary_label.setWordWrap(True)
        self.secondary_label.setObjectName("captionLabel")
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setObjectName("eyebrowLabel")
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.description_label)
        text_column.addWidget(self.primary_label)
        text_column.addWidget(self.secondary_label)
        text_column.addWidget(self.result_label)
        row.addLayout(text_column, 1)

        self.button = QPushButton()
        self.button.setObjectName("accentButton")
        set_pointing_cursor(self.button)
        self.button.clicked.connect(self._stage)
        row.addWidget(self.button)

    def refresh(self, stats, stage_result=None) -> None:
        self.primary_label.setText(f"Will add {stats.will_stage} change(s)")
        secondary_parts = [
            f"Already set {stats.already_at_target}",
            f"Blocked {stats.blocked}",
            f"Compatible {stats.compatible}/{stats.total}",
        ]
        self.secondary_label.setText(" | ".join(secondary_parts))

        messages: list[str] = []
        if stats.message:
            messages.append(stats.message)
        if stage_result is not None:
            messages.append(stage_result.message)
        deduped_messages = list(dict.fromkeys(message for message in messages if message))
        self.result_label.setText(" | ".join(deduped_messages))
        self.result_label.setHidden(not deduped_messages)

        if not stats.enabled:
            self.button.setText("Loading" if stats.message and "loading" in stats.message.lower() else "Capture Baseline First")
            self.button.setEnabled(False)
            return
        self.button.setEnabled(True)
        if stats.will_stage:
            self.button.setText(f"Add {stats.will_stage} To Review")
        else:
            self.button.setText("View Result")

    def _stage(self, _checked: bool = False) -> None:
        self.on_stage(self.preset_id)


class PresetsPage(ScrollablePage):
    def __init__(self, controller, refresh_callback) -> None:
        super().__init__(
            "Presets",
            "Safe-heavy presets pack in high-value public actions so one preset feels worth using, while still respecting compatibility and safety boundaries.",
        )
        self.controller = controller
        self.refresh_callback = refresh_callback
        self.last_stage_result: dict[str, object] = {}
        self.card_views: dict[str, PresetCardView] = {}
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(12)
        self.body_layout.addLayout(self.cards_layout)

    def refresh(self) -> None:
        clear_layout(self.cards_layout)
        self.card_views = {}
        for preset in self.controller.presets:
            stats = self.controller.preset_stats(preset.id)
            stage_result = self.last_stage_result.get(preset.id)
            card = PresetCardView(preset, self.controller, self._stage)
            card.refresh(stats, stage_result)
            self.card_views[preset.id] = card
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)

    def _stage(self, preset_id: str) -> None:
        result = self.controller.stage_preset(preset_id)
        self.last_stage_result[preset_id] = result
        self.refresh()
        self.refresh_callback(result)


class CompatibilityPage(ScrollablePage):
    def __init__(self) -> None:
        super().__init__(
            "Compatibility",
            "Only real dependency, build, and capability blocks are listed here.",
        )
        self.overview = QLabel()
        self.overview.setWordWrap(True)
        self.overview.setObjectName("captionLabel")
        self.blocked_list = QPlainTextEdit()
        self.blocked_list.setReadOnly(True)
        self.body_layout.addWidget(self.overview)
        self.body_layout.addWidget(self.blocked_list)

    def refresh(self, controller) -> None:
        self.overview.setText(
            controller.machine_summary_text()
            + "\nOnly real dependency, build, and capability blocks are listed here."
        )
        self.blocked_list.setPlainText(controller.blocked_actions_text())


class RestorePage(ScrollablePage):
    def __init__(self, controller, refresh_callback) -> None:
        super().__init__(
            "Restore",
            "Capture baselines, request a Windows restore point, or roll back a recorded transaction.",
        )
        self.controller = controller
        self.refresh_callback = refresh_callback

        button_row = QHBoxLayout()
        self.baseline_button = QPushButton("Capture Baseline")
        self.baseline_button.setObjectName("ghostButton")
        self.restore_point_button = QPushButton("Create Restore Point")
        self.restore_point_button.setObjectName("ghostButton")
        self.rollback_button = QPushButton("Rollback Selected")
        self.rollback_button.setObjectName("accentButton")
        for button in (self.baseline_button, self.restore_point_button, self.rollback_button):
            set_pointing_cursor(button)
            button_row.addWidget(button)
        self.body_layout.addLayout(button_row)

        self.snapshot_list = QListWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.body_layout.addWidget(self.snapshot_list)
        self.body_layout.addWidget(self.details)

        self.baseline_button.clicked.connect(self.capture_baseline)
        self.restore_point_button.clicked.connect(self._create_restore_point)
        self.rollback_button.clicked.connect(self.rollback_selected)
        self.snapshot_list.currentRowChanged.connect(self._show_details)

    def refresh(self) -> None:
        snapshots = self.controller.store.list_snapshots()
        self.snapshot_list.clear()
        for snapshot in snapshots:
            label = f"{snapshot.created_at[:19]} | {snapshot.label}"
            if snapshot.is_baseline:
                label += " [baseline]"
            QListWidgetItem(label, self.snapshot_list)
        if snapshots:
            self.snapshot_list.setCurrentRow(0)
            self._show_details(0)
        else:
            self.details.setPlainText("No snapshots recorded yet.")

    def capture_baseline(self) -> None:
        self.controller.capture_new_baseline()
        self.refresh_callback()

    def _create_restore_point(self) -> None:
        created = self.controller.create_restore_point()
        self.details.setPlainText("Restore point request completed." if created else "Restore point request failed.")

    def rollback_selected(self) -> None:
        row = self.snapshot_list.currentRow()
        snapshots = self.controller.store.list_snapshots()
        if row < 0 or row >= len(snapshots):
            return
        self.controller.rollback_snapshot(snapshots[row].snapshot_id)
        self.refresh_callback()

    def _show_details(self, row: int) -> None:
        snapshots = self.controller.store.list_snapshots()
        if row < 0 or row >= len(snapshots):
            self.details.setPlainText("")
            return
        snapshot = snapshots[row]
        lines = [
            f"Snapshot: {snapshot.snapshot_id}",
            f"Label: {snapshot.label}",
            f"Machine: {snapshot.machine_name}",
            "",
        ]
        for entry in snapshot.action_entries:
            label = entry.action_id
            if entry.notes.startswith("Startup entry::"):
                label = "Startup Entry: " + entry.notes.split("::", 1)[1]
            lines.append(f"- {label} -> {'On' if entry.target_state else 'Off'}")
        self.details.setPlainText("\n".join(lines))


class NvidiaDependencyCard(QFrame):
    def __init__(self, title: str, on_download, on_open_releases, on_choose_existing, on_rescan) -> None:
        super().__init__()
        self.setObjectName("dependencyCard")
        self.on_download = on_download
        self.on_open_releases = on_open_releases
        self.on_choose_existing = on_choose_existing
        self.on_rescan = on_rescan
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.status_chip = StatusChip("Checking...", tone="muted")
        self.path_label = QLabel()
        self.path_label.setObjectName("captionLabel")
        self.path_label.setWordWrap(True)
        self.legacy_label = QLabel()
        self.legacy_label.setObjectName("captionLabel")
        self.legacy_label.setWordWrap(True)
        self.notice_label = QLabel(
            "Downloading NVIDIA Profile Inspector does not enable Tweakify's legacy NVIDIA tweak actions. Those still require nvidiaInspector.exe."
        )
        self.notice_label.setObjectName("detailLabel")
        self.notice_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(self.status_chip)
        layout.addWidget(self.path_label)
        layout.addWidget(self.legacy_label)
        layout.addWidget(self.notice_label)

        button_row = QHBoxLayout()
        self.download_button = QPushButton("Download Latest")
        self.download_button.setObjectName("ghostButton")
        self.open_releases_button = QPushButton("Open Releases")
        self.open_releases_button.setObjectName("ghostButton")
        self.choose_button = QPushButton("Choose Existing Copy")
        self.choose_button.setObjectName("ghostButton")
        self.rescan_button = QPushButton("Rescan")
        self.rescan_button.setObjectName("accentButton")
        for button in (self.download_button, self.open_releases_button, self.choose_button, self.rescan_button):
            set_pointing_cursor(button)
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self.download_button.clicked.connect(self.on_download)
        self.open_releases_button.clicked.connect(self.on_open_releases)
        self.choose_button.clicked.connect(self.on_choose_existing)
        self.rescan_button.clicked.connect(self.on_rescan)

    def refresh(self, detected_path: str | None, profile_path: str | None, helper_message: str = "") -> None:
        if profile_path:
            self.status_chip.setText("Profile Inspector Ready")
            self.status_chip.set_tone("safety")
            self.path_label.setText(profile_path)
        else:
            self.status_chip.setText("Profile Inspector Missing")
            self.status_chip.set_tone("muted")
            self.path_label.setText(
                "Download the current NVIDIA Profile Inspector release or choose an existing nvidiaProfileInspector.exe copy."
            )
        if detected_path:
            self.legacy_label.setText(f"Legacy NVIDIA tweak CLI ready: {detected_path}")
        else:
            self.legacy_label.setText("Legacy NVIDIA tweak actions remain blocked until nvidiaInspector.exe is installed or selected.")
        if helper_message:
            self.notice_label.setText(
                helper_message
                + "\n"
                + "Downloading NVIDIA Profile Inspector does not enable Tweakify's legacy NVIDIA tweak actions. Those still require nvidiaInspector.exe."
            )

    def set_busy(self, busy: bool) -> None:
        for button in (self.download_button, self.open_releases_button, self.choose_button, self.rescan_button):
            button.setEnabled(not busy)


class SettingsPage(ScrollablePage):
    def __init__(
        self,
        controller,
        on_setting_change,
        on_download_profile_inspector,
        on_open_nvidia_page,
        on_choose_nvidia_copy,
        on_rescan_nvidia,
    ) -> None:
        super().__init__(
            "Settings",
            "Appearance, behavior, diagnostics, integrations, and safety controls live here without blocking the app.",
        )
        self.controller = controller
        self.on_setting_change = on_setting_change
        self.group_cards: dict[str, QFrame] = {}
        self.controls: dict[str, QWidget] = {}
        self.debounce_timers: dict[str, QTimer] = {}
        self.nvidia_dependency_card: NvidiaDependencyCard | None = None
        self.groups_container = QWidget()
        self.groups_container.setObjectName("moduleViewport")
        self.groups_layout = QGridLayout(self.groups_container)
        self.groups_layout.setSpacing(14)
        self.groups_layout.setAlignment(Qt.AlignTop)
        self.body_layout.addWidget(self.groups_container)

        self._build_groups(
            on_download_profile_inspector,
            on_open_nvidia_page,
            on_choose_nvidia_copy,
            on_rescan_nvidia,
        )
        self.refresh()

    def _build_groups(
        self,
        on_download_profile_inspector,
        on_open_nvidia_page,
        on_choose_nvidia_copy,
        on_rescan_nvidia,
    ) -> None:
        appearance = self._create_group("Appearance", "Adjust the public shell theme and glass intensity.", 0, 0)
        self._add_theme_combo(appearance, "Theme mode", "theme_mode")
        self._add_double_spin(appearance, "Accent intensity", "accent_intensity", 0.20, 1.00, 0.05)
        self._add_checkbox(appearance, "Compact mode", "compact_mode")
        self._add_checkbox(appearance, "Reduced motion", "reduced_motion")
        self._add_double_spin(appearance, "Font scale", "font_scale", 0.90, 1.25, 0.05)

        behavior = self._create_group("Behavior", "Control review and apply behavior.", 0, 1)
        self._add_checkbox(behavior, "Auto-preview staged plan", "auto_preview")
        self._add_checkbox(behavior, "Confirm before apply", "confirm_before_apply")
        self._add_checkbox(behavior, "Auto-capture baseline", "auto_capture_baseline")
        self._add_checkbox(behavior, "Create restore point before Advanced apply", "auto_restore_point_advanced")
        self._add_checkbox(behavior, "Show review panel", "review_tray_open")

        diagnostics = self._create_group("Diagnostics", "Tune polling cadence and cached state retention.", 1, 0)
        self._add_checkbox(diagnostics, "Refresh on launch", "diagnostics_refresh_on_launch")
        self._add_checkbox(diagnostics, "Background polling", "diagnostics_background_poll")
        self._add_spin(diagnostics, "Refresh cadence (seconds)", "diagnostics_refresh_interval_seconds", 30, 3600, 30)
        self._add_spin(diagnostics, "Cache retention (days)", "diagnostics_cache_retention_days", 1, 30, 1)

        integrations = self._create_group("Integrations", "Configure optional dependency paths and helper tools.", 1, 1)
        self._add_line_edit(integrations, "Legacy nvidiaInspector.exe path", "nvidia_inspector_path")
        self.nvidia_dependency_card = NvidiaDependencyCard(
            "NVIDIA Profile Inspector",
            on_download_profile_inspector,
            on_open_nvidia_page,
            on_choose_nvidia_copy,
            on_rescan_nvidia,
        )
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self.nvidia_dependency_card)
        integrations.addRow(QLabel("Dependency helper"), container)

        safety = self._create_group("Safety", "Expose Advanced and Experimental controls deliberately.", 2, 0, 2)
        self._add_checkbox(safety, "Show Advanced actions", "show_advanced")
        self._add_checkbox(safety, "Show Experimental actions", "show_experimental")
        self._add_checkbox(safety, "Stricter confirmation", "strict_confirmation")

    def _create_group(self, title: str, subtitle: str, row: int, column: int, column_span: int = 1) -> QFormLayout:
        frame = QFrame()
        frame.setObjectName("settingsGroup")
        layout = QVBoxLayout(frame)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("captionLabel")
        subtitle_label.setWordWrap(True)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addLayout(form)
        self.groups_layout.addWidget(frame, row, column, 1, column_span)
        self.group_cards[title] = frame
        return form

    def _add_checkbox(self, layout: QFormLayout, label: str, setting_name: str) -> None:
        control = QPushButton()
        control.setCheckable(True)
        control.setObjectName("pillSwitch")
        set_pointing_cursor(control)
        control.clicked.connect(lambda checked, name=setting_name: self.on_setting_change(name, checked))
        self.controls[setting_name] = control
        layout.addRow(QLabel(label), control)

    def _add_spin(self, layout: QFormLayout, label: str, setting_name: str, minimum: int, maximum: int, step: int) -> None:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda name=setting_name, widget=control: self.on_setting_change(name, widget.value()))
        control.valueChanged.connect(lambda _value, current=timer: current.start(180))
        control.editingFinished.connect(lambda name=setting_name, widget=control, current=timer: self._flush_debounced(name, widget.value(), current))
        self.debounce_timers[setting_name] = timer
        self.controls[setting_name] = control
        layout.addRow(QLabel(label), control)

    def _add_double_spin(self, layout: QFormLayout, label: str, setting_name: str, minimum: float, maximum: float, step: float) -> None:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        control.setDecimals(2)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda name=setting_name, widget=control: self.on_setting_change(name, float(widget.value())))
        control.valueChanged.connect(lambda _value, current=timer: current.start(180))
        control.editingFinished.connect(lambda name=setting_name, widget=control, current=timer: self._flush_debounced(name, float(widget.value()), current))
        self.debounce_timers[setting_name] = timer
        self.controls[setting_name] = control
        layout.addRow(QLabel(label), control)

    def _add_line_edit(self, layout: QFormLayout, label: str, setting_name: str) -> None:
        control = QLineEdit()
        control.editingFinished.connect(lambda name=setting_name, widget=control: self.on_setting_change(name, widget.text().strip()))
        self.controls[setting_name] = control
        layout.addRow(QLabel(label), control)

    def _add_theme_combo(self, layout: QFormLayout, label: str, setting_name: str) -> None:
        control = QComboBox()
        control.addItem("System", "system")
        control.addItem("Light", "light")
        control.addItem("Dark", "dark")
        set_pointing_cursor(control)
        control.currentIndexChanged.connect(lambda _index, widget=control, name=setting_name: self.on_setting_change(name, widget.currentData()))
        self.controls[setting_name] = control
        layout.addRow(QLabel(label), control)

    def _flush_debounced(self, name: str, value, timer: QTimer) -> None:
        timer.stop()
        self.on_setting_change(name, value)

    def refresh(self) -> None:
        settings = self.controller.settings
        for name, control in self.controls.items():
            value = getattr(settings, name)
            control.blockSignals(True)
            if isinstance(control, QPushButton) and control.isCheckable():
                control.setChecked(bool(value))
                control.setProperty("checked", bool(value))
                control.setText("On" if value else "Off")
                control.style().unpolish(control)
                control.style().polish(control)
            elif isinstance(control, QSpinBox):
                control.setValue(int(value))
            elif isinstance(control, QDoubleSpinBox):
                control.setValue(float(value))
            elif isinstance(control, QLineEdit):
                control.setText(str(value))
            elif isinstance(control, QComboBox):
                index = control.findData(value)
                control.setCurrentIndex(index if index >= 0 else 0)
            control.blockSignals(False)
        if self.nvidia_dependency_card is not None:
            self.nvidia_dependency_card.refresh(
                self.controller.machine_context.nvidia_inspector_path,
                self.controller.settings.nvidia_profile_inspector_path or None,
            )


class TweakifyMainWindow(QMainWindow):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.sidebar_buttons: list[QPushButton] = []
        self.action_cards: dict[str, ActionCard] = {}
        self.module_pages: dict[str, ModulePage] = {}
        self.refresh_coordinator = RefreshCoordinator()
        self.refresh_coordinator.result_ready.connect(self._handle_background_result)
        self.refresh_coordinator.error.connect(self._handle_background_error)
        self.startup_entries_panel: StartupEntriesPanel | None = None
        self.startup_page: StartupPage | None = None
        self.graphics_nvidia_card: NvidiaDependencyCard | None = None
        self.nvidia_helper_message = ""
        self.resolved_theme_mode = "dark"
        self._startup_runtime_requested = False
        self._baseline_capture_requested = False

        self.setWindowTitle("Tweakify")
        self.resize(1620, 980)

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        self.sidebar_panel = self._build_sidebar()
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentStack")

        self.dashboard_page = DashboardPage(controller, self.request_runtime_refresh)
        self.presets_page = PresetsPage(controller, self.refresh_staging)
        self.compatibility_page = CompatibilityPage()
        self.restore_page = RestorePage(controller, self.refresh_all)
        self.snapshots_page = self.restore_page
        self.startup_page = StartupPage(controller)
        self.settings_page = SettingsPage(
            controller,
            self._handle_setting_change,
            self._download_profile_inspector,
            self._open_nvidia_download_page,
            self._choose_nvidia_copy,
            self._rescan_nvidia_dependency,
        )

        self.module_pages = {
            "performance": ModulePage("performance", "Performance", "Power, CPU responsiveness, and latency-oriented system controls."),
            "network": ModulePage("network", "Network", "TCP, adapter, DNS, and background network controls with compatibility gating."),
            "services": ModulePage("services", "Services", "Background policy, telemetry, notification, and service-oriented controls."),
            "cleanup": ModulePage("cleanup", "Cleanup", "Storage recovery, maintenance actions, and shell cleanup tools."),
            "input_ui": ModulePage("input_ui", "Input + UI", "Pointer, keyboard, animations, shell polish, and interaction-focused controls."),
            "graphics": ModulePage("graphics", "Graphics", "Windows graphics settings plus optional NVIDIA hooks when the dependency exists."),
        }

        page_map = {
            "dashboard": self.dashboard_page,
            "presets": self.presets_page,
            "startup": self.startup_page,
            "performance": self.module_pages["performance"],
            "network": self.module_pages["network"],
            "services": self.module_pages["services"],
            "cleanup": self.module_pages["cleanup"],
            "input_ui": self.module_pages["input_ui"],
            "graphics": self.module_pages["graphics"],
            "compatibility": self.compatibility_page,
            "restore": self.restore_page,
            "settings": self.settings_page,
        }
        for module_id, _label in MODULES:
            self.stack.addWidget(page_map[module_id])

        self.review_drawer = ReviewDrawer(controller, self.refresh_staging, self.request_apply_staged)
        self.review_tray = self.review_drawer

        root_layout.addWidget(self.sidebar_panel)
        root_layout.addWidget(self.stack, 1)
        root_layout.addWidget(self.review_drawer)
        self.setCentralWidget(root)

        self._apply_runtime_settings()
        self._populate_module_pages()
        self._refresh_current_surfaces()
        self.show()

    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebarPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        brand = QLabel("Tweakify")
        brand.setObjectName("titleLabel")
        self.sidebar_subtitle = QLabel("Performance Toolkit")
        self.sidebar_subtitle.setObjectName("captionLabel")
        layout.addWidget(brand)
        layout.addWidget(self.sidebar_subtitle)

        for index, (_module_id, label) in enumerate(MODULES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("navButton")
            set_pointing_cursor(button)
            button.clicked.connect(partial(self._set_page, index))
            if index == 0:
                button.setChecked(True)
            self.sidebar_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)
        return panel

    def _apply_runtime_settings(self) -> None:
        self.resolved_theme_mode = resolve_theme_mode(
            self.controller.settings.theme_mode,
            self.controller.platform.system_theme_mode(),
        )
        self.setStyleSheet(
            build_app_stylesheet(
                resolved_theme_mode=self.resolved_theme_mode,
                accent_intensity=self.controller.settings.accent_intensity,
                compact_mode=self.controller.settings.compact_mode,
            )
        )
        font = self.font()
        font.setPointSizeF(10.5 * float(self.controller.settings.font_scale))
        self.setFont(font)
        self.sidebar_panel.setFixedWidth(232 if self.controller.settings.compact_mode else 258)
        self.review_drawer.setFixedWidth(380 if self.controller.settings.compact_mode else 408)
        self.review_drawer.setVisible(bool(self.controller.settings.review_tray_open))
        apply_windows_backdrop(self, self.resolved_theme_mode)

    def _build_nvidia_card(self, title: str) -> NvidiaDependencyCard:
        card = NvidiaDependencyCard(
            title,
            self._download_profile_inspector,
            self._open_nvidia_download_page,
            self._choose_nvidia_copy,
            self._rescan_nvidia_dependency,
        )
        card.refresh(
            self.controller.machine_context.nvidia_inspector_path,
            self.controller.settings.nvidia_profile_inspector_path or None,
            self.nvidia_helper_message,
        )
        return card

    def _populate_module_pages(self) -> None:
        self.action_cards = {}
        self.startup_entries_panel = None
        self.graphics_nvidia_card = None
        if self.startup_page is not None:
            self.startup_page.clear_apps()
            self.startup_page.clear_tweaks()
            self.startup_entries_panel = StartupEntriesPanel(self.controller, self.refresh_staging)
            self.startup_page.apps_layout.addWidget(self.startup_entries_panel)
            startup_sections = self.controller.module_sections("startup")
            if not startup_sections:
                empty = QFrame()
                empty.setObjectName("sectionGroup")
                empty.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
                empty_layout = QVBoxLayout(empty)
                message = QLabel("No startup tweaks are visible with the current safety filters.")
                message.setWordWrap(True)
                message.setObjectName("captionLabel")
                empty_layout.addWidget(message)
                self.startup_page.tweaks_layout.addWidget(empty)
            else:
                for section_title, actions in startup_sections:
                    group = SectionGroup(section_title)
                    for action in actions:
                        card = ActionCard(
                            action=action,
                            decision=self.controller.compatibility_by_action[action.definition.id],
                            controller=self.controller,
                            on_change=self.refresh_staging,
                        )
                        self.action_cards[action.definition.id] = card
                        group.cards_layout.addWidget(card)
                    self.startup_page.tweaks_layout.addWidget(group)
        for module_id, page in self.module_pages.items():
            page.clear()
            if module_id == "graphics":
                self.graphics_nvidia_card = self._build_nvidia_card("NVIDIA Profile Inspector")
                page.content_layout.addWidget(self.graphics_nvidia_card)

            sections = self.controller.module_sections(module_id)
            if not sections:
                empty = QFrame()
                empty.setObjectName("sectionGroup")
                empty_layout = QVBoxLayout(empty)
                message = QLabel("No actions are visible with the current safety filters.")
                message.setWordWrap(True)
                message.setObjectName("captionLabel")
                empty_layout.addWidget(message)
                page.content_layout.addWidget(empty)
                page.content_layout.addStretch(1)
                continue

            for section_title, actions in sections:
                group = SectionGroup(section_title)
                for action in actions:
                    card = ActionCard(
                        action=action,
                        decision=self.controller.compatibility_by_action[action.definition.id],
                        controller=self.controller,
                        on_change=self.refresh_staging,
                    )
                    self.action_cards[action.definition.id] = card
                    group.cards_layout.addWidget(card)
                page.content_layout.addWidget(group)
            page.content_layout.addStretch(1)

    def _refresh_action_cards(self) -> None:
        for action_id, card in self.action_cards.items():
            card.decision = self.controller.compatibility_by_action[action_id]
            card.refresh()

    def _refresh_current_surfaces(self) -> None:
        self.dashboard_page.refresh(self.controller)
        self.presets_page.refresh()
        self.compatibility_page.refresh(self.controller)
        self.restore_page.refresh()
        self.settings_page.refresh()
        self.review_drawer.refresh()
        self._update_review_drawer_badge()

    def _capture_startup_page_state(self) -> dict[str, int] | None:
        if self.startup_page is None:
            return None
        return self.startup_page.capture_state()

    def _restore_startup_page_state(self, state: dict[str, int] | None) -> None:
        if self.startup_page is None:
            return
        self.startup_page.restore_state(state)

    def _set_page(self, index: int, _checked: bool = False) -> None:
        self.stack.setCurrentIndex(index)
        for button_index, button in enumerate(self.sidebar_buttons):
            button.setChecked(button_index == index)

    def _update_review_drawer_badge(self) -> None:
        self.review_drawer.setVisible(bool(self.controller.settings.review_tray_open))

    def _open_nvidia_download_page(self) -> None:
        self.controller.platform.open_external_url(NVIDIA_PROFILE_INSPECTOR_RELEASES_URL)

    def _choose_nvidia_copy(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select nvidiaProfileInspector.exe",
            str(Path.home()),
            "Executable (nvidiaProfileInspector.exe)",
        )
        if not path:
            return
        self._handle_setting_change("nvidia_profile_inspector_path", path)

    def _download_profile_inspector(self) -> None:
        self.nvidia_helper_message = "Downloading NVIDIA Profile Inspector in the background..."
        self._set_nvidia_cards_busy(True)
        self._refresh_integration_surfaces()
        self.refresh_coordinator.request("profile_inspector_download", self.controller.download_nvidia_profile_inspector)

    def _rescan_nvidia_dependency(self) -> None:
        self.controller.refresh_integrations_only()
        self._refresh_integration_surfaces()

    def _refresh_integration_surfaces(self) -> None:
        self._refresh_action_cards()
        self.presets_page.refresh()
        self.compatibility_page.refresh(self.controller)
        self.settings_page.refresh()
        if self.settings_page.nvidia_dependency_card is not None:
            self.settings_page.nvidia_dependency_card.refresh(
                self.controller.machine_context.nvidia_inspector_path,
                self.controller.settings.nvidia_profile_inspector_path or None,
                self.nvidia_helper_message,
            )
        if self.graphics_nvidia_card is not None:
            self.graphics_nvidia_card.refresh(
                self.controller.machine_context.nvidia_inspector_path,
                self.controller.settings.nvidia_profile_inspector_path or None,
                self.nvidia_helper_message,
            )

    def _set_nvidia_cards_busy(self, busy: bool) -> None:
        if self.settings_page.nvidia_dependency_card is not None:
            self.settings_page.nvidia_dependency_card.set_busy(busy)
        if self.graphics_nvidia_card is not None:
            self.graphics_nvidia_card.set_busy(busy)

    def request_runtime_refresh(self, force_live_diagnostics: bool = True) -> None:
        self._startup_runtime_requested = True
        if self.controller.runtime_pending:
            self.dashboard_page.summary_caption.setText(
                "Loading diagnostics, startup inventory, and compatibility in the background..."
            )
        else:
            self.dashboard_page.summary_caption.setText("Refreshing diagnostics and compatibility in the background...")
        self.refresh_coordinator.request(
            "runtime",
            lambda: self.controller.build_runtime_snapshot(force_live_diagnostics=force_live_diagnostics),
        )

    def request_apply_staged(self) -> None:
        self.refresh_coordinator.request("apply", self.controller.apply_staged)

    def _handle_background_result(self, domain: str, result: object) -> None:
        if domain == "runtime":
            startup_state = self._capture_startup_page_state()
            self.controller.apply_runtime_snapshot(result)  # type: ignore[arg-type]
            self.controller.refresh_integrations_only()
            self._populate_module_pages()
            self._refresh_current_surfaces()
            self._restore_startup_page_state(startup_state)
            if (
                self.controller.settings.auto_capture_baseline
                and self.controller.store.latest_baseline() is None
                and not self._baseline_capture_requested
            ):
                self._baseline_capture_requested = True
                self.refresh_coordinator.request("baseline", self.controller.capture_initial_baseline_if_needed)
            return
        if domain == "baseline":
            self._baseline_capture_requested = False
            self.restore_page.refresh()
            self.presets_page.refresh()
            self.review_drawer.refresh()
            return
        if domain == "apply":
            startup_state = self._capture_startup_page_state()
            self.controller.refresh_integrations_only()
            self._populate_module_pages()
            self._refresh_current_surfaces()
            self.review_drawer.show_apply_result(result)
            self._restore_startup_page_state(startup_state)
            return
        if domain == "profile_inspector_download":
            self._set_nvidia_cards_busy(False)
            self.nvidia_helper_message = result.message
            self.controller.refresh_integrations_only()
            self._refresh_integration_surfaces()

    def _handle_background_error(self, domain: str, message: str) -> None:
        if domain == "runtime":
            self.dashboard_page.summary_caption.setText(f"Background refresh failed: {message}")
            return
        if domain == "baseline":
            self._baseline_capture_requested = False
            return
        if domain == "apply":
            self.review_drawer.show_error(message)
            return
        if domain == "profile_inspector_download":
            self._set_nvidia_cards_busy(False)
            self.nvidia_helper_message = f"Download failed: {message}"
            self._refresh_integration_surfaces()

    def _handle_setting_change(self, name: str, value) -> None:
        self.controller.update_setting(name, value)

        appearance_settings = {"theme_mode", "accent_intensity", "compact_mode", "reduced_motion", "font_scale"}
        diagnostics_settings = {
            "diagnostics_refresh_on_launch",
            "diagnostics_refresh_interval_seconds",
            "diagnostics_background_poll",
            "diagnostics_cache_retention_days",
        }
        behavior_settings = {
            "auto_preview",
            "confirm_before_apply",
            "auto_capture_baseline",
            "auto_restore_point_advanced",
            "review_tray_open",
        }
        safety_settings = {"show_advanced", "show_experimental", "strict_confirmation"}
        integration_settings = {"nvidia_inspector_path", "nvidia_profile_inspector_path"}

        if name in appearance_settings:
            self._apply_runtime_settings()
            self._refresh_action_cards()
            self.settings_page.refresh()
            self._update_review_drawer_badge()
            return

        if name in diagnostics_settings or name in behavior_settings:
            self.settings_page.refresh()
            self.review_drawer.refresh()
            self.dashboard_page.refresh_summary(self.controller)
            self._update_review_drawer_badge()
            return

        if name in safety_settings:
            startup_state = self._capture_startup_page_state()
            self.controller.refresh_visibility_only()
            self._populate_module_pages()
            self.presets_page.refresh()
            self.compatibility_page.refresh(self.controller)
            self.settings_page.refresh()
            self.refresh_staging()
            self._restore_startup_page_state(startup_state)
            return

        if name in integration_settings:
            self.controller.refresh_integrations_only()
            self._refresh_integration_surfaces()
            self._update_review_drawer_badge()
            return

    def refresh_staging(self, stage_result=None, startup_entry_id: str | None = None) -> None:
        startup_state = self._capture_startup_page_state()
        self._refresh_action_cards()
        if self.startup_entries_panel is not None:
            if startup_entry_id is not None:
                self.startup_entries_panel.refresh_entry(startup_entry_id)
            else:
                self.startup_entries_panel.refresh_staged_state()
        self.presets_page.refresh()
        self.dashboard_page.refresh_summary(self.controller)
        if stage_result is not None and not self.controller.total_staged_count():
            self.review_drawer.show_stage_result(stage_result.message)
        else:
            self.review_drawer.refresh()
        self._restore_startup_page_state(startup_state)
        self._update_review_drawer_badge()

    def refresh_all(self, background: bool = False) -> None:
        if background:
            self.request_runtime_refresh()
            return
        startup_state = self._capture_startup_page_state()
        self.controller.refresh_machine_context()
        self.controller.refresh_integrations_only()
        self.controller.refresh_action_states()
        self.controller.refresh_startup_inventory()
        self.controller.refresh_diagnostics()
        self.controller.refresh_presets()
        self._populate_module_pages()
        self._refresh_current_surfaces()
        self._restore_startup_page_state(startup_state)

    def showEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().showEvent(event)
        apply_windows_backdrop(self, self.resolved_theme_mode)
        if self.controller.runtime_pending and not self._startup_runtime_requested:
            QTimer.singleShot(
                0,
                lambda: self.request_runtime_refresh(
                    force_live_diagnostics=self.controller.settings.diagnostics_refresh_on_launch
                ),
            )

    def nativeEvent(self, eventType, message):  # pragma: no cover - platform runtime hook
        try:
            from ctypes import wintypes

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt_x", wintypes.LONG),
                    ("pt_y", wintypes.LONG),
                ]

            msg = MSG.from_address(int(message))
            if msg.message in {0x001A, 0x031A} and self.controller.settings.theme_mode == "system":
                previous = self.resolved_theme_mode
                self._apply_runtime_settings()
                if self.resolved_theme_mode != previous:
                    self.settings_page.refresh()
        except Exception:
            pass
        return super().nativeEvent(eventType, message)
