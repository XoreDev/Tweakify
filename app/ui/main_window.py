"""Tweakify 1.2 application shell.

Layout: a slim navigation rail, a content column (top bar + pages), and a review
panel that slides in when changes are staged. Every slow controller call runs on
the thread pool (see app.ui.tasks); the GUI thread only renders.
"""

from __future__ import annotations

import ctypes
from functools import partial
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.controller import MODULES
from app.domain.models import ActionKind, SafetyTier
from app.ui.dashboard import DashboardPage
from app.ui.pages import (
    NVIDIA_CARD_NOTICE,
    NVIDIA_PROFILE_INSPECTOR_RELEASES_URL,
    CompatibilityPage,
    NvidiaDependencyCard,
    PresetsPage,
    RestorePage,
    SettingsPage,
)
from app.ui.palette import CommandPalette, PaletteEntry
from app.ui.review import ReviewDrawer
from app.ui.tasks import RefreshCoordinator
from app.ui.theme import BRAND_GLYPH, ICONS, NAV_ICONS, build_app_stylesheet, palette_for, resolve_theme_mode
from app.ui.tweaks import ActionCard, ModulePage, SectionGroup, StartupEntriesPanel, StartupPage, TweakRow
from app.ui.widgets import (
    EmptyState,
    Glyph,
    StatusChip,
    Toast,
    button,
    glyph_icon,
    icon_button,
    kbd,
    label,
    motion_enabled,
    set_active_palette,
    set_pointing_cursor,
)

__all__ = ["TweakifyMainWindow", "ActionCard", "NVIDIA_CARD_NOTICE", "glyph_icon"]

APP_VERSION = "1.2"
REVIEW_WIDTH = 372
MODULE_COPY = {
    "performance": ("Performance", "Power plans, device power management, memory, and file-system behavior."),
    "gaming": ("Gaming", "Scheduler priority, CPU power, MMCSS, and Game Bar settings for steadier frame times."),
    "network": ("Network", "TCP, adapter, DNS, and background-traffic settings for lower, steadier ping."),
    "privacy": ("Privacy", "Telemetry, ads, activity tracking, and Windows AI features such as Copilot and Recall."),
    "services": ("Services", "Background services and system features you may not need."),
    "cleanup": ("Cleanup", "Reclaim disk space and repair Windows. These run once when you apply."),
    "input_ui": ("Input + UI", "Mouse, keyboard, animations, and shell responsiveness."),
    "graphics": ("Graphics", "Windows graphics settings and NVIDIA driver profile tweaks."),
}
NAV_SECTIONS = {"dashboard": "OVERVIEW", "performance": "OPTIMIZE", "compatibility": "SYSTEM"}


def apply_windows_backdrop(window: QMainWindow, resolved_theme_mode: str) -> None:
    try:
        hwnd = int(window.winId())
        dark_mode = ctypes.c_int(1 if resolved_theme_mode == "dark" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
        # Square-ish corners and a caption color that matches the window background.
        palette = palette_for(resolved_theme_mode)
        color = palette.window.lstrip("#")
        colorref = ctypes.c_int(int(color[4:6] + color[2:4] + color[0:2], 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), ctypes.sizeof(colorref))
    except Exception:
        return


class TweakifyMainWindow(QMainWindow):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.sidebar_buttons: list[QPushButton] = []
        self.action_cards: dict[str, TweakRow] = {}
        self.module_pages: dict[str, ModulePage] = {}
        self.section_groups: list[SectionGroup] = []
        self.startup_entries_panel: StartupEntriesPanel | None = None
        self.graphics_nvidia_card: NvidiaDependencyCard | None = None
        self.nvidia_helper_message = ""
        self.resolved_theme_mode = "dark"
        self._startup_runtime_requested = False
        self._baseline_capture_requested = False
        self._review_open = False
        self._built_signature: tuple | None = None
        self._live_sampler = None
        self.refresh_coordinator = RefreshCoordinator()
        self.refresh_coordinator.result_ready.connect(self._handle_background_result)
        self.refresh_coordinator.error.connect(self._handle_background_error)

        self.setWindowTitle("Tweakify")
        self.setMinimumSize(QSize(1180, 720))
        self.resize(1600, 960)

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.sidebar_panel = self._build_sidebar()
        root_layout.addWidget(self.sidebar_panel)

        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_top_bar())
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack, 1)
        root_layout.addWidget(self.content, 1)

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
            module_id: ModulePage(module_id, title, subtitle, partial(self._stage_module_recommended, module_id))
            for module_id, (title, subtitle) in MODULE_COPY.items()
        }
        page_map = {
            "dashboard": self.dashboard_page,
            "presets": self.presets_page,
            "startup": self.startup_page,
            "compatibility": self.compatibility_page,
            "restore": self.restore_page,
            "settings": self.settings_page,
            **self.module_pages,
        }
        for module_id, _label in MODULES:
            self.stack.addWidget(page_map[module_id])

        self.review_drawer = ReviewDrawer(controller, self.refresh_staging, self.request_apply_staged, self._close_review)
        self.review_tray = self.review_drawer
        root_layout.addWidget(self.review_drawer)
        self.setCentralWidget(root)

        self.toast = Toast(self.content)
        self.command_palette = CommandPalette(root, self._palette_entries)

        self.dashboard_page.stage_fixes_callback = self._after_recommended_fixes
        self.dashboard_page.latency_button.clicked.connect(self.request_latency_test)
        self.dashboard_page.restore_point_button.clicked.connect(self.request_restore_point)
        self.dashboard_page.free_ram_button.clicked.connect(self.request_free_memory)
        for widget, handler in (
            (self.restore_page.restore_point_button, self.request_restore_point),
            (self.restore_page.rollback_button, self.request_rollback_selected),
            (self.restore_page.baseline_button, self.request_capture_baseline),
        ):
            widget.clicked.disconnect()
            widget.clicked.connect(handler)

        for sequence in ("Ctrl+K", "Ctrl+F"):
            QShortcut(QKeySequence(sequence), self, activated=self.command_palette.open)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.review_drawer.apply)
        for index in range(min(9, len(MODULES))):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self, activated=partial(self._set_page, index))

        self.live_timer = QTimer(self)
        self.live_timer.setInterval(1000)
        self.live_timer.timeout.connect(self._sample_live)

        self._apply_runtime_settings()
        self._populate_module_pages()
        self._refresh_current_surfaces()
        self.show()

    # ------------------------------------------------------------------ shell
    def _build_sidebar(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("sidebar")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(2)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.setContentsMargins(6, 0, 0, 0)
        self.brand_mark = QPushButton(BRAND_GLYPH)
        self.brand_mark.setObjectName("iconButton")
        self.brand_mark.setFixedSize(34, 34)
        self.brand_mark.setFocusPolicy(Qt.NoFocus)
        brand.addWidget(self.brand_mark)
        brand.addWidget(label("Tweakify", "brandName"))
        brand.addWidget(label(APP_VERSION, "versionTag"), 0, Qt.AlignVCenter)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(10)
        for index, (module_id, text) in enumerate(MODULES):
            if module_id in NAV_SECTIONS:
                layout.addWidget(label(NAV_SECTIONS[module_id], "navSection"))
            nav = QPushButton(text)
            nav.setObjectName("navButton")
            nav.setCheckable(True)
            nav.setProperty("module_id", module_id)
            nav.setIconSize(QSize(17, 17))
            nav.setToolTip(f"{text}  (Ctrl+{index + 1})" if index < 9 else text)
            set_pointing_cursor(nav)
            nav.clicked.connect(partial(self._set_page, index))
            nav.setChecked(index == 0)
            self.sidebar_buttons.append(nav)
            layout.addWidget(nav)
        self._nav_labels = [text for _module_id, text in MODULES]
        layout.addStretch(1)

        footer = QFrame()
        footer.setObjectName("sidebarFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 8, 10)
        footer_layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.elevation_label = label("", "h3")
        self.sidebar_subtitle = label("Performance toolkit", "subtle")
        text.addWidget(self.elevation_label)
        text.addWidget(self.sidebar_subtitle)
        footer_layout.addLayout(text, 1)
        self.theme_button = icon_button(ICONS["moon"], "Switch light / dark", self._toggle_theme)
        footer_layout.addWidget(self.theme_button)
        layout.addWidget(footer)
        panel.setFixedWidth(236)
        return panel

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(60)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(32, 0, 20, 0)
        layout.setSpacing(12)
        self.search_launcher = QPushButton(f"{ICONS['search']}   Search tweaks, pages, and commands")
        self.search_launcher.setObjectName("searchLauncher")
        self.search_launcher.setMinimumWidth(360)
        self.search_launcher.setMaximumWidth(520)
        set_pointing_cursor(self.search_launcher)
        self.search_launcher.clicked.connect(lambda _checked=False: self.command_palette.open())
        launcher_row = QHBoxLayout(self.search_launcher)
        launcher_row.setContentsMargins(0, 0, 10, 0)
        launcher_row.addStretch(1)
        launcher_row.addWidget(kbd("Ctrl K"))
        layout.addWidget(self.search_launcher, 1)
        layout.addStretch(1)
        self.live_readout = label("", "liveReadout")
        layout.addWidget(self.live_readout)
        self.admin_chip = StatusChip("", tone="muted")
        layout.addWidget(self.admin_chip)
        self.review_launcher = QPushButton("Review")
        self.review_launcher.setObjectName("reviewLauncher")
        set_pointing_cursor(self.review_launcher)
        self.review_launcher.clicked.connect(lambda _checked=False: self._toggle_review())
        layout.addWidget(self.review_launcher)
        return bar

    def _apply_runtime_settings(self) -> None:
        settings = self.controller.settings
        self.resolved_theme_mode = resolve_theme_mode(settings.theme_mode, self.controller.platform.system_theme_mode())
        palette = palette_for(self.resolved_theme_mode, settings.accent_color)
        set_active_palette(palette, motion=not settings.reduced_motion)
        self.setStyleSheet(
            build_app_stylesheet(
                resolved_theme_mode=self.resolved_theme_mode,
                accent_intensity=settings.accent_intensity,
                compact_mode=settings.compact_mode,
                accent=settings.accent_color,
            )
        )
        font = self.font()
        font.setPointSizeF(10.0 * float(settings.font_scale))
        self.setFont(font)
        self.sidebar_panel.setFixedWidth(212 if settings.compact_mode else 236)
        for nav in self.sidebar_buttons:
            glyph = NAV_ICONS.get(str(nav.property("module_id")), "")
            if glyph:
                nav.setIcon(glyph_icon(glyph, palette.text_muted))
        self.brand_mark.setStyleSheet(
            f"QPushButton#iconButton {{ background: {palette.accent}; color: {palette.accent_text}; border-radius: 9px; font-size: 13pt; }}"
        )
        self.theme_button.setText(ICONS["sun"] if self.resolved_theme_mode == "dark" else ICONS["moon"])
        self.review_drawer.setFixedWidth(REVIEW_WIDTH - (24 if settings.compact_mode else 0))
        self._update_review_drawer_badge()
        apply_windows_backdrop(self, self.resolved_theme_mode)
        self.update()

    def _toggle_theme(self) -> None:
        self._handle_setting_change("theme_mode", "light" if self.resolved_theme_mode == "dark" else "dark")

    # ------------------------------------------------------------------ review panel
    def _toggle_review(self) -> None:
        if self.review_drawer.isVisible() and not self.controller.settings.review_tray_open:
            self._review_open = False
        else:
            self._review_open = True
        self._update_review_drawer_badge()

    def _close_review(self) -> None:
        self._review_open = False
        if self.controller.settings.review_tray_open:
            self._handle_setting_change("review_tray_open", False)
            return
        self._update_review_drawer_badge()

    def _update_review_drawer_badge(self) -> None:
        count = self.controller.total_staged_count()
        pinned = bool(self.controller.settings.review_tray_open)
        self.review_drawer.setVisible(pinned or self._review_open)
        self.review_launcher.setText(f"Review  ·  {count}" if count else "Review")
        if self.review_launcher.property("pending") != bool(count):
            self.review_launcher.setProperty("pending", bool(count))
            self.review_launcher.style().unpolish(self.review_launcher)
            self.review_launcher.style().polish(self.review_launcher)

    # ------------------------------------------------------------------ navigation
    def _set_page(self, index: int, _checked: bool = False) -> None:
        if index < 0 or index >= self.stack.count():
            return
        previous = self.stack.currentIndex()
        self.stack.setCurrentIndex(index)
        for button_index, nav in enumerate(self.sidebar_buttons):
            nav.setChecked(button_index == index)
        if index != previous and motion_enabled() and self.isVisible():
            page = self.stack.currentWidget()
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", page)
            fade.setDuration(150)
            fade.setStartValue(0.35)
            fade.setEndValue(1.0)
            fade.finished.connect(lambda p=page: p.setGraphicsEffect(None))
            fade.start(QPropertyAnimation.DeleteWhenStopped)
        self._sync_live_timer()

    def _module_index(self, module_id: str) -> int:
        return next(index for index, (mid, _label) in enumerate(MODULES) if mid == module_id)

    def reveal_action(self, action_id: str) -> None:
        row = self.action_cards.get(action_id)
        if row is None:
            return
        module_id = row.action.definition.module_id
        self._set_page(self._module_index(module_id))
        page = self.module_pages.get(module_id)
        if page is not None:
            if page.filter_mode != "all":
                page.filter.set_value("all")
                page.set_filter("all")
            QTimer.singleShot(0, lambda: page.scroll.ensureWidgetVisible(row, 0, 120))
        elif module_id == "startup":
            self.startup_page.tabs.setCurrentIndex(StartupPage.TWEAKS_TAB)
            QTimer.singleShot(0, lambda: self.startup_page.tweaks_scroll.ensureWidgetVisible(row, 0, 120))
        row.flash()

    def _palette_entries(self) -> list[PaletteEntry]:
        entries = [
            PaletteEntry("command", "Optimize now", "Stage every recommended Safe fix", ICONS["bolt"], self.dashboard_page._stage_recommended_fixes, "fix health recommended"),
            PaletteEntry("command", "Apply staged changes", "Open the review panel", ICONS["play"], self._open_review_and_apply, "apply run"),
            PaletteEntry("command", "Rescan system", "Re-read diagnostics and tweak states", ICONS["refresh"], self.request_runtime_refresh, "refresh scan"),
            PaletteEntry("command", "Free memory", "Empty the standby list", ICONS["memory"], self.request_free_memory, "ram standby"),
            PaletteEntry("command", "Create restore point", "Windows System Restore", ICONS["restore_point"], self.request_restore_point, "backup"),
            PaletteEntry("command", "Ping test", "Cloudflare, Google, Quad9", ICONS["ping"], self.request_latency_test, "latency network"),
            PaletteEntry("command", "Switch light / dark theme", "Appearance", ICONS["sun"], self._toggle_theme, "theme mode"),
        ]
        for index, (module_id, text) in enumerate(MODULES):
            entries.append(PaletteEntry("page", text, "Page", NAV_ICONS.get(module_id, ICONS["chevron_right"]), partial(self._set_page, index), module_id))
        for action_id, row in self.action_cards.items():
            definition = row.action.definition
            state = "one-time task" if row.is_maintenance else ("on" if self.controller.current_state(action_id) else "off")
            if self.controller.runtime_pending:
                state = "scanning"
            module_label = dict(MODULES).get(definition.module_id, definition.module_id)
            entries.append(
                PaletteEntry(
                    "tweak", definition.title, f"{module_label}  ·  {state}", NAV_ICONS.get(definition.module_id, ICONS["chevron_right"]),
                    partial(self.reveal_action, action_id), " ".join((definition.description, definition.public_group, action_id)),
                )
            )
        return entries

    def _open_review_and_apply(self) -> None:
        self._review_open = True
        self._update_review_drawer_badge()
        self.review_drawer.apply()

    # ------------------------------------------------------------------ live monitor
    def _sync_live_timer(self) -> None:
        should_run = self.isVisible() and not self.isMinimized()
        if should_run and not self.live_timer.isActive():
            if self._live_sampler is None:
                factory = getattr(self.controller.platform, "create_live_sampler", None)
                self._live_sampler = factory() if factory else None
            if self._live_sampler is not None:
                self.live_timer.start()
        elif not should_run and self.live_timer.isActive():
            self.live_timer.stop()
        self.dashboard_page.set_live_paused(not self.live_timer.isActive())

    def _sample_live(self) -> None:
        if self._live_sampler is None:
            return
        try:
            sample = self._live_sampler.sample()
        except Exception:
            self.live_timer.stop()
            return
        parts = []
        if sample.cpu_percent is not None:
            parts.append(f"CPU {sample.cpu_percent:.0f}%")
        if sample.memory_percent is not None:
            parts.append(f"RAM {sample.memory_percent:.0f}%")
        if sample.gpu_percent is not None:
            parts.append(f"GPU {sample.gpu_percent:.0f}%")
        self.live_readout.setText("   ".join(parts))
        # The tiles keep history even off-screen, but only repaint when visible.
        self.dashboard_page.update_live(sample)

    # ------------------------------------------------------------------ pages
    def _build_signature(self) -> tuple:
        modules = ["startup", *self.module_pages]
        return (
            self.controller.runtime_pending,
            tuple((module_id, tuple(id(action) for action in self.controller.visible_actions(module_id))) for module_id in modules),
            tuple(entry.id for entry in self.controller.startup_inventory["items"]),
        )

    def _populate_module_pages(self) -> None:
        signature = self._build_signature()
        if signature == self._built_signature:
            # Same rows as last time: update them in place instead of rebuilding ~120 widgets.
            self._refresh_action_cards()
            if self.startup_entries_panel is not None:
                self.startup_entries_panel.refresh_staged_state()
            for page in self.module_pages.values():
                page.apply_filter()
            return
        self._built_signature = signature
        self.action_cards = {}
        self.section_groups = []
        self.graphics_nvidia_card = None

        self.startup_page.clear_apps()
        self.startup_page.clear_tweaks()
        self.startup_entries_panel = StartupEntriesPanel(self.controller, self.refresh_staging)
        self.startup_page.apps_layout.addWidget(self.startup_entries_panel)
        sections = self.controller.module_sections("startup")
        if not sections:
            self.startup_page.tweaks_layout.addWidget(
                EmptyState(ICONS["filter"], "No startup tweaks visible", "Turn on Advanced tweaks in Settings to see more.")
            )
        for section_title, actions in sections:
            self.startup_page.tweaks_layout.addWidget(self._build_group(section_title, actions))

        for module_id, page in self.module_pages.items():
            page.clear()
            if module_id == "graphics":
                self.graphics_nvidia_card = self._build_nvidia_card("NVIDIA Profile Inspector")
                page.content_layout.addWidget(self.graphics_nvidia_card)
            sections = self.controller.module_sections(module_id)
            if not sections:
                page.content_layout.addWidget(
                    EmptyState(ICONS["filter"], "No tweaks visible", "Turn on Advanced or Experimental tweaks in Settings to see more.")
                )
            for section_title, actions in sections:
                group = self._build_group(section_title, actions)
                page.groups.append(group)
                page.content_layout.addWidget(group)
            page.apply_filter()

    def _build_group(self, title: str, actions) -> SectionGroup:
        group = SectionGroup(title)
        for action in actions:
            row = TweakRow(
                action=action,
                decision=self.controller.compatibility_by_action[action.definition.id],
                controller=self.controller,
                on_change=self.refresh_staging,
            )
            self.action_cards[action.definition.id] = row
            group.add_row(row)
        self.section_groups.append(group)
        return group

    def _refresh_action_cards(self) -> None:
        for action_id, row in self.action_cards.items():
            row.decision = self.controller.compatibility_by_action[action_id]
            row.refresh()

    def _refresh_current_surfaces(self) -> None:
        context = self.controller.machine_context
        self.elevation_label.setText("Administrator" if context.is_admin else "Standard user")
        self.admin_chip.setText(f"{ICONS['shield']}  Elevated" if context.is_admin else "Not elevated")
        self.admin_chip.set_tone("positive" if context.is_admin else "muted")
        self.admin_chip.setStyleSheet('font-family: "Segoe UI Variable Text", "Segoe Fluent Icons", "Segoe MDL2 Assets";')
        self.dashboard_page.refresh(self.controller)
        self.presets_page.refresh()
        self.compatibility_page.refresh(self.controller)
        self.restore_page.refresh()
        self.settings_page.refresh()
        self.review_drawer.refresh()
        for page in self.module_pages.values():
            page.refresh_stats()
        self._update_review_drawer_badge()

    def _capture_startup_page_state(self) -> dict[str, int] | None:
        return self.startup_page.capture_state()

    def _restore_startup_page_state(self, state: dict[str, int] | None) -> None:
        self.startup_page.restore_state(state)

    def _stage_module_recommended(self, module_id: str) -> None:
        added = 0
        for action in self.controller.visible_actions(module_id):
            definition = action.definition
            if definition.safety_tier != SafetyTier.SAFE or definition.kind != ActionKind.SETTING:
                continue
            if not self.controller.compatibility_by_action[definition.id].allowed:
                continue
            if self.controller.current_state(definition.id) or self.controller.target_state(definition.id):
                continue
            self.controller.stage_action(definition.id, True)
            added += 1
        self.refresh_staging()
        self.toast.show_message(
            f"Staged {added} recommended tweak(s)" if added else "Every recommended tweak here is already on",
            ICONS["check"] if added else ICONS["info"],
        )

    def _after_recommended_fixes(self, added: int = 0) -> None:
        self.refresh_staging()
        self.toast.show_message(
            f"Added {added} recommended fix(es) to review" if added else "Nothing new to fix",
            ICONS["bolt"] if added else ICONS["info"],
        )

    # ------------------------------------------------------------------ NVIDIA
    def _build_nvidia_card(self, title: str) -> NvidiaDependencyCard:
        card = NvidiaDependencyCard(
            title, self._download_profile_inspector, self._open_nvidia_download_page, self._choose_nvidia_copy, self._rescan_nvidia_dependency
        )
        card.refresh(
            self.controller.machine_context.nvidia_inspector_path,
            self.controller.settings.nvidia_profile_inspector_path or None,
            self.nvidia_helper_message,
        )
        return card

    def _open_nvidia_download_page(self) -> None:
        self.controller.platform.open_external_url(NVIDIA_PROFILE_INSPECTOR_RELEASES_URL)

    def _choose_nvidia_copy(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(self, "Select nvidiaProfileInspector.exe", str(Path.home()), "Executable (nvidiaProfileInspector.exe)")
        if path:
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
        for card in (self.settings_page.nvidia_dependency_card, self.graphics_nvidia_card):
            if card is not None:
                card.refresh(
                    self.controller.machine_context.nvidia_inspector_path,
                    self.controller.settings.nvidia_profile_inspector_path or None,
                    self.nvidia_helper_message,
                )

    def _set_nvidia_cards_busy(self, busy: bool) -> None:
        for card in (self.settings_page.nvidia_dependency_card, self.graphics_nvidia_card):
            if card is not None:
                card.set_busy(busy)

    # ------------------------------------------------------------------ background work
    def request_runtime_refresh(self, force_live_diagnostics: bool = True) -> None:
        self._startup_runtime_requested = True
        self.dashboard_page.refresh_button.setEnabled(False)
        self.dashboard_page.refresh_button.setText("Scanning...")
        self.refresh_coordinator.request(
            "runtime", lambda: self.controller.build_runtime_snapshot(force_live_diagnostics=force_live_diagnostics)
        )

    def request_apply_staged(self) -> None:
        self.refresh_coordinator.request("apply", self.controller.apply_staged)

    def request_latency_test(self) -> None:
        self.dashboard_page.latency_label.setText("Pinging...")
        self.dashboard_page.latency_button.setEnabled(False)
        self.refresh_coordinator.request("latency", self.controller.run_latency_test)

    def request_restore_point(self) -> None:
        self.dashboard_page.restore_point_button.set_caption("Creating...")
        self.restore_page.details.setPlainText("Creating a Windows restore point in the background...")
        self.refresh_coordinator.request("restore_point", self.controller.create_restore_point)

    def request_free_memory(self) -> None:
        self.dashboard_page.free_ram_button.set_caption("Freeing...")
        self.refresh_coordinator.request("free_memory", self.controller.platform.purge_standby_list)

    def request_capture_baseline(self) -> None:
        self.restore_page.details.setPlainText("Capturing a new baseline in the background...")
        self.refresh_coordinator.request("baseline_manual", self.controller.capture_new_baseline)

    def request_rollback_selected(self) -> None:
        row = self.restore_page.snapshot_list.currentRow()
        snapshots = self.controller.store.list_snapshots()
        if row < 0 or row >= len(snapshots):
            return
        snapshot = snapshots[row]
        answer = QMessageBox.question(
            self, "Roll back snapshot",
            f"Restore {len(snapshot.action_entries)} setting(s) from '{snapshot.label}' ({snapshot.created_at[:19]})?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.restore_page.details.setPlainText("Rolling back in the background...")
        self.refresh_coordinator.request("rollback", lambda: self.controller.rollback_snapshot(snapshot.snapshot_id))

    def _handle_background_result(self, domain: str, result: object) -> None:
        if domain == "runtime":
            self.dashboard_page.refresh_button.setEnabled(True)
            self.dashboard_page.refresh_button.setText("Rescan")
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
            failed = len(getattr(result, "failed_results", []))
            if getattr(result, "requested_elevation", False):
                self.toast.show_message("Handed off to the elevated helper", ICONS["shield"])
            elif failed:
                self.toast.show_message(f"{failed} change(s) failed. See the plan for details", ICONS["warning"], "warning", 4200)
            else:
                self.toast.show_message(f"Applied {len(getattr(result, 'results', []))} change(s)", ICONS["check"], "positive")
            return
        if domain == "profile_inspector_download":
            self._set_nvidia_cards_busy(False)
            self.nvidia_helper_message = result.message  # type: ignore[attr-defined]
            self.controller.refresh_integrations_only()
            self._refresh_integration_surfaces()
            return
        if domain == "latency":
            self.dashboard_page.latency_button.setEnabled(True)
            values = [ms for ms in result.values() if ms is not None]  # type: ignore[union-attr]
            self.dashboard_page.latency_label.setText(
                f"Best {min(values):.0f} ms  ·  avg {sum(values) / len(values):.0f} ms" if values else "No reply"
            )
            parts = [f"{host} {'timeout' if ms is None else f'{ms:.0f} ms'}" for host, ms in result.items()]  # type: ignore[union-attr]
            self.dashboard_page.latency_button.setToolTip("\n".join(parts))
            return
        if domain == "restore_point":
            ok = bool(result)
            self.dashboard_page.restore_point_button.set_caption("Created just now" if ok else "Failed. Is System Protection on?")
            message = "Windows restore point created." if ok else (
                "Windows could not create a restore point. Check that System Protection is on for the system drive."
            )
            self.restore_page.details.setPlainText(message)
            self.toast.show_message("Restore point created" if ok else "Restore point failed", ICONS["check"] if ok else ICONS["warning"], "positive" if ok else "warning")
            return
        if domain == "free_memory":
            ok = bool(result)
            self.dashboard_page.free_ram_button.set_caption("Standby list emptied" if ok else "Needs administrator rights")
            self.toast.show_message("Standby memory freed" if ok else "Run Tweakify as administrator to free memory", ICONS["memory"], "positive" if ok else "warning")
            return
        if domain == "baseline_manual":
            self.restore_page.refresh()
            self.presets_page.refresh()
            self.toast.show_message("Baseline captured", ICONS["check"], "positive")
            return
        if domain == "rollback":
            failed = result.failed_results  # type: ignore[attr-defined]
            startup_state = self._capture_startup_page_state()
            self._populate_module_pages()
            self._refresh_current_surfaces()
            self._restore_startup_page_state(startup_state)
            self.restore_page.details.setPlainText(
                "\n".join(
                    [f"Rolled back {len(result.results) - len(failed)} item(s)" + (f", {len(failed)} failed." if failed else ".")]  # type: ignore[attr-defined]
                    + [item.message for item in result.results]  # type: ignore[attr-defined]
                )
            )
            self.toast.show_message("Rollback finished", ICONS["restore_point"], "warning" if failed else "positive")

    def _handle_background_error(self, domain: str, message: str) -> None:
        if domain == "runtime":
            self.dashboard_page.refresh_button.setEnabled(True)
            self.dashboard_page.refresh_button.setText("Rescan")
            self.dashboard_page.summary_caption.setText(f"Background scan failed: {message}")
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
            return
        if domain == "latency":
            self.dashboard_page.latency_button.setEnabled(True)
            self.dashboard_page.latency_label.setText("Ping failed")
            return
        if domain == "free_memory":
            self.dashboard_page.free_ram_button.set_caption("Failed")
            return
        if domain in {"restore_point", "rollback", "baseline_manual"}:
            self.restore_page.details.setPlainText(f"{domain.replace('_', ' ').title()} failed: {message}")

    # ------------------------------------------------------------------ settings + staging
    def _handle_setting_change(self, name: str, value) -> None:
        self.controller.update_setting(name, value)
        appearance = {"theme_mode", "accent_color", "accent_intensity", "compact_mode", "reduced_motion", "font_scale"}
        behavior = {
            "auto_preview", "confirm_before_apply", "auto_capture_baseline", "auto_restore_point_advanced",
            "review_tray_open", "auto_open_review_drawer",
            "diagnostics_refresh_on_launch", "diagnostics_refresh_interval_seconds",
            "diagnostics_background_poll", "diagnostics_cache_retention_days",
        }
        if name == "game_executables":
            self._populate_module_pages()
            self.compatibility_page.refresh(self.controller)
            self.refresh_staging()
            return
        if name in appearance:
            self._apply_runtime_settings()
            self._refresh_action_cards()
            self.settings_page.refresh()
            return
        if name in behavior:
            self.settings_page.refresh()
            self.review_drawer.refresh()
            self.dashboard_page.refresh_summary(self.controller)
            self._update_review_drawer_badge()
            return
        if name in {"show_advanced", "show_experimental", "strict_confirmation"}:
            startup_state = self._capture_startup_page_state()
            self.controller.refresh_visibility_only()
            self._populate_module_pages()
            self.presets_page.refresh()
            self.compatibility_page.refresh(self.controller)
            self.settings_page.refresh()
            self.refresh_staging()
            self._restore_startup_page_state(startup_state)
            return
        if name in {"nvidia_inspector_path", "nvidia_profile_inspector_path"}:
            self.controller.refresh_integrations_only()
            self._refresh_integration_surfaces()
            self._update_review_drawer_badge()

    def refresh_staging(self, stage_result=None, startup_entry_id: str | None = None) -> None:
        startup_state = self._capture_startup_page_state()
        self._refresh_action_cards()
        if self.startup_entries_panel is not None:
            if startup_entry_id is not None:
                self.startup_entries_panel.refresh_entry(startup_entry_id)
            else:
                self.startup_entries_panel.refresh_staged_state()
        current = self.stack.currentWidget()
        for page in self.module_pages.values():
            if page is current and page.filter_mode == "pending":
                page.apply_filter()
            else:
                page.refresh_stats()
        self.presets_page.refresh()
        self.dashboard_page.refresh_summary(self.controller)
        count = self.controller.total_staged_count()
        if stage_result is not None and not count:
            self.review_drawer.show_stage_result(stage_result.message)
        elif self.controller.last_stage_notice:
            self.review_drawer.refresh()
            self.review_drawer.summary_label.setText(self.review_drawer.summary_label.text() + " " + self.controller.last_stage_notice)
        else:
            self.review_drawer.refresh()
        if count and self.controller.settings.auto_open_review_drawer:
            self._review_open = True
        elif not count:
            self._review_open = False
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

    # ------------------------------------------------------------------ Qt hooks
    def resizeEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().resizeEvent(event)
        self.toast.reposition()
        if self.command_palette.isVisible():
            self.command_palette.setGeometry(self.centralWidget().rect())

    def showEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().showEvent(event)
        apply_windows_backdrop(self, self.resolved_theme_mode)
        self._sync_live_timer()
        if self.controller.runtime_pending and not self._startup_runtime_requested:
            QTimer.singleShot(
                0, lambda: self.request_runtime_refresh(force_live_diagnostics=self.controller.settings.diagnostics_refresh_on_launch)
            )

    def hideEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().hideEvent(event)
        self._sync_live_timer()

    def changeEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self._sync_live_timer()

    def closeEvent(self, event) -> None:  # pragma: no cover - Qt runtime hook
        self.live_timer.stop()
        if self.refresh_coordinator.is_busy("apply") or self.refresh_coordinator.is_busy("rollback"):
            self.setWindowTitle("Tweakify - finishing changes...")
            self.refresh_coordinator.wait_for_idle(60000)
        if self._live_sampler is not None:
            try:
                self._live_sampler.close()
            except Exception:
                pass
        super().closeEvent(event)

    def nativeEvent(self, eventType, message):  # pragma: no cover - platform runtime hook
        try:
            from ctypes import wintypes

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt_x", wintypes.LONG), ("pt_y", wintypes.LONG),
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
