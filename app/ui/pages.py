"""Presets, Compatibility, Restore, and Settings pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import ACCENT_LABELS, ACCENTS, ICONS, palette_for
from app.ui.tweaks import ScrollablePage
from app.ui.widgets import (
    EmptyState,
    Glyph,
    StatusChip,
    ToggleSwitch,
    button,
    card,
    clear_layout,
    divider,
    label,
    set_pointing_cursor,
)

NVIDIA_PROFILE_INSPECTOR_RELEASES_URL = "https://github.com/Orbmu2k/nvidiaProfileInspector/releases"
NVIDIA_CARD_NOTICE = (
    "NVIDIA Profile Inspector powers Tweakify's NVIDIA driver tweaks (power mode, V-Sync, low latency, "
    "refresh rate, texture filtering). They are written to the global driver profile and can be rolled back."
)
PRESET_GLYPHS = {
    "baseline_restore": ICONS["restore_point"],
    "gaming": ICONS["game"],
    "low_latency": ICONS["bolt"],
    "balanced": ICONS["check"],
    "privacy_minimal": ICONS["shield"],
    "debloat_lite": ICONS["broom"],
    "creator_workstation": ICONS["cpu"],
}


# ----------------------------------------------------------------- presets
class PresetCardView(QFrame):
    def __init__(self, preset, controller, on_stage) -> None:
        super().__init__()
        self.preset_id = preset.id
        self.controller = controller
        self.on_stage = on_stage
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        icon = Glyph(PRESET_GLYPHS.get(preset.id, ICONS["sparkle"]), tone="accent", size_pt=15)
        icon.setFixedSize(36, 36)
        top.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title_label = label(preset.title, "h2")
        self.primary_label = label("", "accentText")
        titles.addWidget(self.title_label)
        titles.addWidget(self.primary_label)
        top.addLayout(titles, 1)
        layout.addLayout(top)
        self.description_label = label(preset.description, "muted", wrap=True)
        layout.addWidget(self.description_label)
        self.secondary_label = label("", "subtle", wrap=True)
        layout.addWidget(self.secondary_label)
        self.result_label = label("", "subtle", wrap=True)
        layout.addWidget(self.result_label)
        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.button = button("", "primaryButton", self._stage)
        row.addWidget(self.button)
        layout.addLayout(row)

    def refresh(self, stats, stage_result=None) -> None:
        self.primary_label.setText(f"Will add {stats.will_stage} change(s)")
        self.secondary_label.setText(
            f"{stats.already_at_target} already set  ·  {stats.blocked} unavailable  ·  "
            f"{stats.compatible}/{stats.total} compatible"
        )
        messages = list(dict.fromkeys(m for m in (stats.message, getattr(stage_result, "message", "")) if m))
        self.result_label.setText("  ·  ".join(messages))
        self.result_label.setHidden(not messages)
        if not stats.enabled:
            self.button.setText("Scanning" if stats.message and "loading" in stats.message.lower() else "Capture a baseline first")
            self.button.setEnabled(False)
            return
        self.button.setEnabled(True)
        self.button.setText(f"Add {stats.will_stage} to review" if stats.will_stage else "Show result")

    def _stage(self) -> None:
        self.on_stage(self.preset_id)


class PresetsPage(ScrollablePage):
    def __init__(self, controller, refresh_callback) -> None:
        super().__init__("Presets", "Curated bundles of tweaks for a goal. Each one only stages changes; you review before applying.")
        self.controller = controller
        self.refresh_callback = refresh_callback
        self.last_stage_result: dict[str, object] = {}
        self.card_views: dict[str, PresetCardView] = {}
        container = QWidget()
        self.cards_layout = QGridLayout(container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(14)
        self.body_layout.addWidget(container)

    def refresh(self) -> None:
        presets = list(self.controller.presets)
        if [card.preset_id for card in self.card_views.values()] != [preset.id for preset in presets]:
            clear_layout(self.cards_layout)
            self.card_views = {}
            for index, preset in enumerate(presets):
                view = PresetCardView(preset, self.controller, self._stage)
                self.card_views[preset.id] = view
                self.cards_layout.addWidget(view, index // 2, index % 2)
            self.cards_layout.setColumnStretch(0, 1)
            self.cards_layout.setColumnStretch(1, 1)
        for preset in presets:
            self.card_views[preset.id].refresh(self.controller.preset_stats(preset.id), self.last_stage_result.get(preset.id))

    def _stage(self, preset_id: str) -> None:
        result = self.controller.stage_preset(preset_id)
        self.last_stage_result[preset_id] = result
        self.refresh()
        self.refresh_callback(result)


# ----------------------------------------------------------------- compatibility
class CompatibilityPage(ScrollablePage):
    def __init__(self) -> None:
        super().__init__("Compatibility", "Tweaks this PC can't run right now, and exactly why.")
        self.overview = label("", "muted", wrap=True)
        self.body_layout.addWidget(self.overview)
        self.list_card = QFrame()
        self.list_card.setObjectName("card")
        self.list_layout = QVBoxLayout(self.list_card)
        self.list_layout.setContentsMargins(0, 2, 0, 2)
        self.list_layout.setSpacing(0)
        self.body_layout.addWidget(self.list_card)
        # Plain-text mirror of the list (copyable, and used by tests and the CLI wording).
        self.blocked_list = QPlainTextEdit()
        self.blocked_list.setReadOnly(True)
        self.blocked_list.hide()

    def refresh(self, controller) -> None:
        self.blocked_list.setPlainText(controller.blocked_actions_text())
        clear_layout(self.list_layout)
        if controller.runtime_pending:
            self.overview.setText("Checking dependencies, Windows build, and hardware capabilities...")
            self.list_layout.addWidget(EmptyState(ICONS["clock"], "Scanning", "Compatibility appears once the scan finishes."))
            return
        blocked = [
            (action, controller.compatibility_by_action[action.definition.id])
            for action in controller.actions
            if not controller.compatibility_by_action[action.definition.id].allowed
        ]
        self.overview.setText(
            f"{len(controller.actions) - len(blocked)} of {len(controller.actions)} tweaks can run on this PC."
        )
        if not blocked:
            self.list_layout.addWidget(EmptyState(ICONS["check"], "Everything is available", "No dependency, build, or hardware blocks."))
            return
        for index, (action, decision) in enumerate(blocked):
            if index:
                self.list_layout.addWidget(divider())
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(18, 12, 18, 12)
            layout.setSpacing(12)
            icon = Glyph(ICONS["lock"], tone="warning", size_pt=10)
            icon.setFixedWidth(18)
            layout.addWidget(icon, 0, Qt.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(label(action.definition.title, "rowTitle"))
            text.addWidget(label("; ".join(decision.reasons), "rowBody", wrap=True))
            layout.addLayout(text, 1)
            layout.addWidget(StatusChip(action.definition.module_id.replace("_", " ").title(), tone="muted"), 0, Qt.AlignTop)
            self.list_layout.addWidget(row)


# ----------------------------------------------------------------- restore
class RestorePage(ScrollablePage):
    def __init__(self, controller, refresh_callback) -> None:
        super().__init__("Restore", "Every apply is snapshotted. Roll back any of them, or capture a fresh baseline.")
        self.controller = controller
        self.refresh_callback = refresh_callback
        self.baseline_button = button("Capture baseline", "ghostButton")
        self.restore_point_button = button("Create restore point", "ghostButton")
        self.rollback_button = button("Roll back selected", "primaryButton")
        for widget in (self.baseline_button, self.restore_point_button, self.rollback_button):
            self.header.actions.addWidget(widget)
        split = QHBoxLayout()
        split.setSpacing(14)
        list_card, list_layout = card(margins=(10, 12, 10, 12), spacing=6)
        list_layout.addWidget(label("  SNAPSHOTS", "eyebrow"))
        self.snapshot_list = QListWidget()
        self.snapshot_list.setMinimumHeight(420)
        list_layout.addWidget(self.snapshot_list)
        split.addWidget(list_card, 2)
        details_card, details_layout = card()
        details_layout.addWidget(label("Details", "h2"))
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        details_layout.addWidget(self.details, 1)
        split.addWidget(details_card, 3)
        self.body_layout.addLayout(split)
        self.baseline_button.clicked.connect(self.capture_baseline)
        self.restore_point_button.clicked.connect(self._create_restore_point)
        self.rollback_button.clicked.connect(self.rollback_selected)
        self.snapshot_list.currentRowChanged.connect(self._show_details)

    def refresh(self) -> None:
        snapshots = self.controller.store.list_snapshots()
        self.snapshot_list.clear()
        for snapshot in snapshots:
            tag = "  ·  baseline" if snapshot.is_baseline else ""
            QListWidgetItem(f"{snapshot.label}{tag}\n{snapshot.created_at[:19].replace('T', '  ')}", self.snapshot_list)
        self.rollback_button.setEnabled(bool(snapshots))
        if snapshots:
            self.snapshot_list.setCurrentRow(0)
            self._show_details(0)
        else:
            self.details.setPlainText("No snapshots yet. Tweakify records one every time you apply a plan.")

    def capture_baseline(self) -> None:
        self.controller.capture_new_baseline()
        self.refresh_callback()

    def _create_restore_point(self) -> None:
        created = self.controller.create_restore_point()
        self.details.setPlainText("Restore point created." if created else "Restore point request failed.")

    def rollback_selected(self) -> None:
        row = self.snapshot_list.currentRow()
        snapshots = self.controller.store.list_snapshots()
        if 0 <= row < len(snapshots):
            self.controller.rollback_snapshot(snapshots[row].snapshot_id)
            self.refresh_callback()

    def _show_details(self, row: int) -> None:
        snapshots = self.controller.store.list_snapshots()
        if row < 0 or row >= len(snapshots):
            self.details.setPlainText("")
            return
        snapshot = snapshots[row]
        lines = [f"{snapshot.label}", f"{snapshot.created_at[:19].replace('T', ' ')}  ·  {snapshot.machine_name}", ""]
        for entry in snapshot.action_entries:
            name = entry.action_id
            action = self.controller.actions_by_id.get(entry.action_id)
            if action is not None:
                name = action.definition.title
            if entry.notes.startswith("Startup entry::"):
                name = "Startup: " + entry.notes.split("::", 1)[1]
            lines.append(f"{'ON ' if entry.target_state else 'OFF'}  {name}")
        self.details.setPlainText("\n".join(lines))


# ----------------------------------------------------------------- settings
class NvidiaDependencyCard(QFrame):
    def __init__(self, title: str, on_download, on_open_releases, on_choose_existing, on_rescan) -> None:
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label(title, "h3"))
        top.addStretch(1)
        self.status_chip = StatusChip("Checking", tone="muted")
        top.addWidget(self.status_chip)
        layout.addLayout(top)
        self.path_label = label("", "mono", wrap=True)
        self.legacy_label = label("", "muted", wrap=True)
        self.notice_label = label(NVIDIA_CARD_NOTICE, "subtle", wrap=True)
        for widget in (self.path_label, self.legacy_label, self.notice_label):
            layout.addWidget(widget)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.download_button = button("Download latest", "primaryButton", on_download)
        self.open_releases_button = button("Releases", "ghostButton", on_open_releases)
        self.choose_button = button("Choose file", "ghostButton", on_choose_existing)
        self.rescan_button = button("Rescan", "quietButton", on_rescan)
        for widget in (self.download_button, self.open_releases_button, self.choose_button, self.rescan_button):
            row.addWidget(widget)
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self, detected_path: str | None, profile_path: str | None, helper_message: str = "") -> None:
        if profile_path:
            self.status_chip.setText("Ready")
            self.status_chip.set_tone("safe")
            self.path_label.setText(profile_path)
        else:
            self.status_chip.setText("Not installed")
            self.status_chip.set_tone("muted")
            self.path_label.setText("nvidiaProfileInspector.exe was not found.")
        self.legacy_label.setText(
            "NVIDIA driver tweaks are available on the Graphics page."
            if profile_path
            else "NVIDIA driver tweaks stay locked until Profile Inspector is downloaded or selected."
        )
        self.notice_label.setText((helper_message + "\n" if helper_message else "") + NVIDIA_CARD_NOTICE)

    def set_busy(self, busy: bool) -> None:
        for widget in (self.download_button, self.open_releases_button, self.choose_button, self.rescan_button):
            widget.setEnabled(not busy)


class SettingsPage(ScrollablePage):
    def __init__(self, controller, on_setting_change, on_download_profile_inspector, on_open_nvidia_page, on_choose_nvidia_copy, on_rescan_nvidia) -> None:
        super().__init__("Settings", "Appearance, behavior, safety, and integrations.")
        self.controller = controller
        self.on_setting_change = on_setting_change
        self.group_cards: dict[str, QFrame] = {}
        self.controls: dict[str, QWidget] = {}
        self.debounce_timers: dict[str, QTimer] = {}
        self.accent_buttons: dict[str, QPushButton] = {}
        self.nvidia_dependency_card: NvidiaDependencyCard | None = None
        self.groups_layout = QVBoxLayout()
        self.groups_layout.setSpacing(22)
        self.body_layout.addLayout(self.groups_layout)

        appearance = self._group("Appearance", "How Tweakify looks.")
        self._add_theme_combo(appearance, "Theme", "Follow Windows, or force light or dark.", "theme_mode")
        self._add_accent_picker(appearance, "Accent color", "Used for primary actions, selection, and live data.")
        self._add_toggle(appearance, "Compact mode", "Tighter rows and padding.", "compact_mode")
        self._add_toggle(appearance, "Reduced motion", "Turn off animated switches, gauges, and fades.", "reduced_motion")
        self._add_double_spin(appearance, "Text size", "Scale all text.", "font_scale", 0.90, 1.25, 0.05)

        behavior = self._group("Behavior", "How staging and applying work.")
        self._add_toggle(behavior, "Open review when staging", "Slide the review panel in when you stage a change.", "auto_open_review_drawer")
        self._add_toggle(behavior, "Keep review panel open", "Pin the review panel even when nothing is staged.", "review_tray_open")
        self._add_toggle(behavior, "Live plan preview", "Keep the dry-run plan updated as you stage.", "auto_preview")
        self._add_toggle(behavior, "Confirm before apply", "Ask once more before changing the system.", "confirm_before_apply")
        self._add_toggle(behavior, "Restore point before Advanced changes", "Create a Windows restore point first.", "auto_restore_point_advanced")
        self._add_toggle(behavior, "Capture a baseline automatically", "Record the original state on first launch.", "auto_capture_baseline")

        diagnostics = self._group("Diagnostics", "How often Tweakify reads the system.")
        self._add_toggle(diagnostics, "Scan on launch", "Read live diagnostics every time the app opens.", "diagnostics_refresh_on_launch")
        self._add_toggle(diagnostics, "Background rescans", "Rescan periodically while the app is open.", "diagnostics_background_poll")
        self._add_spin(diagnostics, "Rescan interval", "Seconds between background rescans.", "diagnostics_refresh_interval_seconds", 30, 3600, 30)
        self._add_spin(diagnostics, "Keep cached diagnostics", "Days to keep the last scan.", "diagnostics_cache_retention_days", 1, 30, 1)

        games = self._group("Games", "Executables that get High CPU and I/O priority from Gaming > Game Profiles.")
        self._add_line_edit(games, "Game executables", "Comma-separated, e.g. cs2.exe, FortniteClient-Win64-Shipping.exe", "game_executables")

        safety = self._group("Safety", "Show riskier tweaks only when you want them.")
        self._add_toggle(safety, "Show Advanced tweaks", "Tweaks with real trade-offs.", "show_advanced")
        self._add_toggle(safety, "Show Experimental tweaks", "Tweaks that can break things on some hardware.", "show_experimental")
        self._add_toggle(safety, "Stricter confirmation", "Extra confirmation for Experimental changes.", "strict_confirmation")

        integrations = self._group("Integrations", "Optional third-party tools.")
        self._add_line_edit(integrations, "Legacy nvidiaInspector.exe", "Only needed for old setups.", "nvidia_inspector_path")
        self.nvidia_dependency_card = NvidiaDependencyCard(
            "NVIDIA Profile Inspector", on_download_profile_inspector, on_open_nvidia_page, on_choose_nvidia_copy, on_rescan_nvidia
        )
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(18, 4, 18, 16)
        holder_layout.addWidget(self.nvidia_dependency_card)
        integrations.addWidget(holder)
        self.refresh()

    # -- building blocks
    def _group(self, title: str, subtitle: str) -> QVBoxLayout:
        section = QVBoxLayout()
        section.setSpacing(8)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.setContentsMargins(4, 0, 4, 0)
        head.addWidget(label(title.upper(), "eyebrow"))
        head.addWidget(label(subtitle, "subtle", wrap=True))
        section.addLayout(head)
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        rows = QVBoxLayout(frame)
        rows.setContentsMargins(0, 2, 0, 2)
        rows.setSpacing(0)
        section.addWidget(frame)
        self.groups_layout.addLayout(section)
        self.group_cards[title] = frame
        return rows

    def _row(self, rows: QVBoxLayout, title: str, description: str, control: QWidget) -> None:
        if rows.count():
            rows.addWidget(divider())
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, "rowTitle"))
        if description:
            text.addWidget(label(description, "rowBody", wrap=True))
        layout.addLayout(text, 1)
        layout.addWidget(control, 0, Qt.AlignVCenter)
        rows.addWidget(row)

    def _add_toggle(self, rows, title: str, description: str, name: str) -> None:
        control = ToggleSwitch()
        control.setAccessibleName(title)
        control.clicked.connect(lambda checked, setting=name: self.on_setting_change(setting, checked))
        self.controls[name] = control
        self._row(rows, title, description, control)

    def _add_spin(self, rows, title, description, name, minimum, maximum, step) -> None:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        control.setFixedWidth(110)
        self._debounce(control, name, lambda widget=control: widget.value())
        self._row(rows, title, description, control)

    def _add_double_spin(self, rows, title, description, name, minimum, maximum, step) -> None:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setSingleStep(step)
        control.setDecimals(2)
        control.setFixedWidth(110)
        self._debounce(control, name, lambda widget=control: float(widget.value()))
        self._row(rows, title, description, control)

    def _debounce(self, control, name: str, read) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self.on_setting_change(name, read()))
        control.valueChanged.connect(lambda _value: timer.start(180))
        control.editingFinished.connect(lambda: (timer.stop(), self.on_setting_change(name, read())))
        self.debounce_timers[name] = timer
        self.controls[name] = control

    def _add_line_edit(self, rows, title, description, name) -> None:
        control = QLineEdit()
        control.setMinimumWidth(320)
        control.editingFinished.connect(lambda setting=name, widget=control: self.on_setting_change(setting, widget.text().strip()))
        self.controls[name] = control
        self._row(rows, title, description, control)

    def _add_theme_combo(self, rows, title, description, name) -> None:
        control = QComboBox()
        for text, value in (("System", "system"), ("Dark", "dark"), ("Light", "light")):
            control.addItem(text, value)
        control.setFixedWidth(150)
        set_pointing_cursor(control)
        control.currentIndexChanged.connect(lambda _i, widget=control, setting=name: self.on_setting_change(setting, widget.currentData()))
        self.controls[name] = control
        self._row(rows, title, description, control)

    def _add_accent_picker(self, rows, title, description) -> None:
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for key in ACCENTS:
            swatch = QPushButton()
            swatch.setObjectName("swatch")
            swatch.setCheckable(True)
            swatch.setToolTip(ACCENT_LABELS[key])
            swatch.setAccessibleName(f"{ACCENT_LABELS[key]} accent")
            set_pointing_cursor(swatch)
            swatch.clicked.connect(lambda _checked=False, value=key: self.on_setting_change("accent_color", value))
            self.accent_buttons[key] = swatch
            layout.addWidget(swatch)
        self.controls["accent_color"] = holder
        self._row(rows, title, description, holder)

    def _paint_swatches(self) -> None:
        mode = getattr(self.window(), "resolved_theme_mode", "dark")
        current = self.controller.settings.accent_color
        for key, swatch in self.accent_buttons.items():
            color = palette_for(mode, key).accent
            ring = palette_for(mode, key).text if key == current else "transparent"
            swatch.setChecked(key == current)
            swatch.setStyleSheet(f"QPushButton#swatch {{ background: {color}; border: 2px solid {ring}; }}")

    def refresh(self) -> None:
        settings = self.controller.settings
        for name, control in self.controls.items():
            if name == "accent_color":
                continue
            value = getattr(settings, name)
            control.blockSignals(True)
            if isinstance(control, ToggleSwitch):
                control.setChecked(bool(value))
                control.setText("On" if value else "Off")
            elif isinstance(control, QSpinBox):
                control.setValue(int(value))
            elif isinstance(control, QDoubleSpinBox):
                control.setValue(float(value))
            elif isinstance(control, QLineEdit):
                if not control.hasFocus():
                    control.setText(str(value))
            elif isinstance(control, QComboBox):
                index = control.findData(value)
                control.setCurrentIndex(index if index >= 0 else 0)
            control.blockSignals(False)
        self._paint_swatches()
        if self.nvidia_dependency_card is not None:
            self.nvidia_dependency_card.refresh(
                self.controller.machine_context.nvidia_inspector_path,
                self.controller.settings.nvidia_profile_inspector_path or None,
            )
