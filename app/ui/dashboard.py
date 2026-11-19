"""Dashboard: health hero, live system monitor, system facts, quick actions, activity."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.copy import ADMIN_PRIVILEGE_NOTE
from app.domain.health import format_bytes
from app.ui.theme import ICONS, palette_for, score_color
from app.ui.tweaks import ScrollablePage
from app.ui.widgets import (
    EmptyState,
    Glyph,
    ScoreRing,
    Sparkline,
    StatusChip,
    active_palette,
    button,
    card,
    clear_layout,
    divider,
    label,
    set_pointing_cursor,
)

SEVERITY = {
    "critical": (ICONS["error"], "danger"),
    "warning": (ICONS["warning"], "warning"),
    "info": (ICONS["info"], "accent"),
    "ok": (ICONS["check"], "positive"),
}
DIAGNOSTIC_TONES = {"good": "positive", "ok": "positive", "warning": "warning", "critical": "danger"}


def _ago(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        seconds = int((datetime.now(UTC) - moment).total_seconds())
    except (TypeError, ValueError):
        return iso[:16]
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


class LiveTile(QFrame):
    """One live metric: label, big number, unit, sparkline, and a detail line."""

    def __init__(self, title: str, glyph: str, unit: str = "%") -> None:
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(Glyph(glyph, size_pt=10))
        top.addWidget(label(title.upper(), "eyebrow"))
        top.addStretch(1)
        self.detail_label = label("", "subtle")
        top.addWidget(self.detail_label)
        layout.addLayout(top)
        value_row = QHBoxLayout()
        value_row.setSpacing(4)
        self.value_label = label("--", "metric")
        self.unit_label = label(unit, "metricUnit")
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        layout.addLayout(value_row)
        self.sparkline = Sparkline()
        layout.addWidget(self.sparkline)

    def set_value(self, value: float | None, detail: str = "") -> None:
        if value is None:
            self.value_label.setText("--")
            self.unit_label.setVisible(False)
            self.detail_label.setText(detail or "Unavailable")
            return
        self.unit_label.setVisible(True)
        self.value_label.setText(f"{value:.0f}")
        self.detail_label.setText(detail)
        palette = active_palette()
        self.sparkline.color = palette.danger if value >= 90 else (palette.warning if value >= 75 else None)
        self.sparkline.push(value)


class QuickAction(QPushButton):
    def __init__(self, glyph: str, title: str, caption: str) -> None:
        super().__init__()
        self.setObjectName("quickAction")
        set_pointing_cursor(self)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        icon = Glyph(glyph, tone="accent", size_pt=13)
        icon.setFixedWidth(22)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_label = label(title, "h3")
        self.caption_label = label(caption, "subtle")
        for widget in (self.title_label, self.caption_label):
            widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            text.addWidget(widget)
        layout.addLayout(text, 1)
        self.setAccessibleName(title)

    def set_caption(self, text: str) -> None:
        self.caption_label.setText(text)


class DashboardPage(ScrollablePage):
    def __init__(self, controller, request_refresh_callback) -> None:
        super().__init__("Dashboard", "Live health, what is holding this PC back, and one-click fixes you review first.")
        self.controller = controller
        self.request_refresh_callback = request_refresh_callback
        self.caption_label = self.subtitle_label
        self.stage_fixes_callback = None
        self.quick_callbacks: dict[str, object] = {}
        self.body_layout.setSpacing(18)

        # ------------------------------------------------ hero
        hero, hero_layout = card("heroCard", margins=(28, 26, 28, 26), spacing=0)
        hero_row = QHBoxLayout()
        hero_row.setSpacing(28)
        self.score_ring = ScoreRing(150, 11)
        hero_row.addWidget(self.score_ring, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(6)
        self.health_eyebrow = label("SYSTEM HEALTH", "eyebrow")
        self.health_score_label = label("Scanning", "display")
        self.health_summary_label = label("", "muted", wrap=True)
        self.summary_caption = label("", "subtle", wrap=True)
        text.addWidget(self.health_eyebrow)
        text.addWidget(self.health_score_label)
        text.addWidget(self.health_summary_label)
        text.addSpacing(10)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.stage_fixes_button = button(f"{ICONS['bolt']}  Optimize now", "primaryButton", self._stage_recommended_fixes)
        self.stage_fixes_button.setToolTip("Stage every recommended Safe fix. You review the plan before anything changes.")
        self.refresh_button = button("Rescan", "ghostButton", self.request_refresh_callback)
        actions.addWidget(self.stage_fixes_button)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        text.addLayout(actions)
        text.addSpacing(4)
        text.addWidget(self.summary_caption)
        hero_row.addLayout(text, 5)
        hero_row.addWidget(divider(vertical=True))
        findings_column = QVBoxLayout()
        findings_column.setSpacing(4)
        findings_column.addWidget(label("FINDINGS", "eyebrow"))
        self.findings_layout = QVBoxLayout()
        self.findings_layout.setSpacing(2)
        findings_column.addLayout(self.findings_layout)
        findings_column.addStretch(1)
        findings_holder = QWidget()
        findings_holder.setLayout(findings_column)
        findings_holder.setMinimumWidth(320)
        hero_row.addWidget(findings_holder, 6)
        hero_layout.addLayout(hero_row)
        self.health_card = hero
        self.body_layout.addWidget(hero)

        # ------------------------------------------------ live monitor
        live_header = QHBoxLayout()
        live_header.addWidget(label("LIVE", "eyebrow"))
        self.live_state = StatusChip("Monitoring", tone="positive")
        live_header.addWidget(self.live_state)
        live_header.addStretch(1)
        self.body_layout.addLayout(live_header)
        live_row = QHBoxLayout()
        live_row.setSpacing(14)
        self.cpu_tile = LiveTile("Processor", ICONS["cpu"])
        self.memory_tile = LiveTile("Memory", ICONS["memory"])
        self.gpu_tile = LiveTile("Graphics", ICONS["gpu"])
        self.disk_tile = LiveTile("Disk activity", ICONS["disk"])
        for tile in (self.cpu_tile, self.memory_tile, self.gpu_tile, self.disk_tile):
            live_row.addWidget(tile, 1)
        self.body_layout.addLayout(live_row)

        # ------------------------------------------------ system + actions
        grid = QHBoxLayout()
        grid.setSpacing(14)
        system_card, system_layout = card()
        head = QHBoxLayout()
        head.addWidget(label("System", "h2"))
        head.addStretch(1)
        self.machine_chip = StatusChip("", tone="muted")
        head.addWidget(self.machine_chip)
        system_layout.addLayout(head)
        metrics_container = QWidget()
        self.metrics_layout = QGridLayout(metrics_container)
        self.metrics_layout.setContentsMargins(0, 4, 0, 0)
        self.metrics_layout.setHorizontalSpacing(18)
        self.metrics_layout.setVerticalSpacing(12)
        system_layout.addWidget(metrics_container)
        system_layout.addStretch(1)
        self.admin_notice_label = label(ADMIN_PRIVILEGE_NOTE, "subtle", wrap=True)
        system_layout.addWidget(divider())
        system_layout.addWidget(self.admin_notice_label)
        grid.addWidget(system_card, 3)

        right = QVBoxLayout()
        right.setSpacing(14)
        actions_card, actions_layout = card()
        actions_layout.addWidget(label("Quick actions", "h2"))
        quick = QGridLayout()
        quick.setSpacing(10)
        self.free_ram_button = QuickAction(ICONS["memory"], "Free memory", "Empty the standby list")
        self.restore_point_button = QuickAction(ICONS["restore_point"], "Restore point", "Windows System Restore")
        self.latency_button = QuickAction(ICONS["ping"], "Ping test", "Three public DNS servers")
        self.task_manager_button = QuickAction(ICONS["task_manager"], "Task Manager", "See what is running")
        for index, widget in enumerate((self.free_ram_button, self.restore_point_button, self.latency_button, self.task_manager_button)):
            quick.addWidget(widget, index // 2, index % 2)
        actions_layout.addLayout(quick)
        self.latency_label = self.latency_button.caption_label
        right.addWidget(actions_card)

        activity_card, activity_layout = card()
        activity_layout.addWidget(label("Recent activity", "h2"))
        self.history_layout = QVBoxLayout()
        self.history_layout.setSpacing(8)
        activity_layout.addLayout(self.history_layout)
        activity_layout.addStretch(1)
        right.addWidget(activity_card, 1)
        grid.addLayout(right, 2)
        self.body_layout.addLayout(grid)

        self.task_manager_button.clicked.connect(lambda _checked=False: self.controller.open_task_manager())

    # ------------------------------------------------ refresh
    def refresh(self, controller) -> None:
        self._refresh_metrics(controller)
        self.refresh_summary(controller)
        self.refresh_health(controller)
        self._refresh_history(controller)

    def refresh_summary(self, controller) -> None:
        context = controller.machine_context
        self.machine_chip.setText(f"Windows build {context.windows_build}  ·  {context.edition}")
        if controller.runtime_pending:
            self.summary_caption.setText("Reading diagnostics, startup apps, and tweak states in the background...")
            return
        count = controller.total_staged_count()
        self.summary_caption.setText(
            f"{count} change(s) waiting in review." if count else "Nothing is staged. Every change is reviewed before it is applied."
        )

    def refresh_health(self, controller) -> None:
        clear_layout(self.findings_layout)
        palette = active_palette()
        if controller.runtime_pending:
            self.score_ring.set_score(None, palette.accent)
            self.health_score_label.setText("Scanning")
            self.health_summary_label.setText("Calculating your health score from live diagnostics.")
            self.stage_fixes_button.setEnabled(False)
            for _ in range(3):
                self.findings_layout.addWidget(self._finding_row(ICONS["clock"], "", "Scanning...", ""))
            return
        report = controller.health_report()
        self.score_ring.set_score(report.score, score_color(palette, report.score))
        self.health_score_label.setText(report.grade)
        self.health_summary_label.setText(report.summary)
        for finding in report.findings[:5]:
            glyph, tone = SEVERITY.get(finding.severity, (ICONS["info"], ""))
            self.findings_layout.addWidget(self._finding_row(glyph, tone, finding.title, finding.detail))
        fixes = controller.recommended_fix_ids()
        self.stage_fixes_button.setEnabled(bool(fixes))
        self.stage_fixes_button.setText(f"{ICONS['bolt']}  Optimize now" + (f"  ·  {len(fixes)}" if fixes else ""))

    def _finding_row(self, glyph: str, tone: str, title: str, detail: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(10)
        icon = Glyph(glyph, tone=tone, size_pt=10)
        icon.setFixedWidth(18)
        layout.addWidget(icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "h3", wrap=True))
        if detail:
            text.addWidget(label(detail, "subtle", wrap=True))
        layout.addLayout(text, 1)
        return row

    def _refresh_metrics(self, controller) -> None:
        clear_layout(self.metrics_layout)
        items = list(controller.diagnostics.items)
        if controller.cleanup_sizes:
            from app.domain.models import DiagnosticItem

            items.append(
                DiagnosticItem(
                    "recoverable_space", "Recoverable space", format_bytes(sum(controller.cleanup_sizes.values())),
                    "info", "Temp, update, crash-dump, thumbnail, and browser caches.",
                )
            )
        for column in range(2):
            self.metrics_layout.setColumnStretch(column, 1)
        for index, item in enumerate(items):
            cell = QVBoxLayout()
            cell.setSpacing(2)
            title = label(item.title.upper(), "eyebrow")
            title.setToolTip(item.detail)
            value = label(item.value, "h3", wrap=True)
            value.setToolTip(item.detail)
            tone = DIAGNOSTIC_TONES.get(str(item.status).lower(), "")
            if tone in {"warning", "danger"}:
                value.setStyleSheet(f"color: {getattr(active_palette(), tone)};")
            cell.addWidget(title)
            cell.addWidget(value)
            holder = QWidget()
            holder.setLayout(cell)
            self.metrics_layout.addWidget(holder, index // 2, index % 2)

    def _refresh_history(self, controller) -> None:
        clear_layout(self.history_layout)
        transactions = controller.store.list_transactions()[:5]
        if not transactions:
            self.history_layout.addWidget(EmptyState(ICONS["clock"], "No changes yet", "Applied plans and rollbacks show up here."))
            return
        for transaction in transactions:
            failed = len(transaction.failed_results)
            row = QHBoxLayout()
            row.setSpacing(10)
            icon = Glyph(ICONS["warning"] if failed else ICONS["check"], tone="warning" if failed else "positive", size_pt=10)
            icon.setFixedWidth(18)
            row.addWidget(icon, 0, Qt.AlignTop)
            text = QVBoxLayout()
            text.setSpacing(1)
            titles = [controller.actions_by_id[i].definition.title for i in transaction.action_ids if i in controller.actions_by_id]
            headline = titles[0] if len(titles) == 1 else f"{len(transaction.action_ids)} changes applied"
            if not transaction.action_ids:
                headline = "Nothing applied"
            text.addWidget(label(headline, "h3"))
            text.addWidget(label(_ago(transaction.created_at) + (f"  ·  {failed} failed" if failed else ""), "subtle"))
            row.addLayout(text, 1)
            holder = QWidget()
            holder.setLayout(row)
            self.history_layout.addWidget(holder)

    def _stage_recommended_fixes(self) -> None:
        added = self.controller.stage_recommended_fixes()
        if self.stage_fixes_callback is not None:
            self.stage_fixes_callback(added)

    # ------------------------------------------------ live monitor
    def update_live(self, sample) -> None:
        self.cpu_tile.set_value(sample.cpu_percent)
        detail = ""
        if sample.memory_used_bytes is not None and sample.memory_total_bytes:
            detail = f"{sample.memory_used_bytes / 1024**3:.1f} / {sample.memory_total_bytes / 1024**3:.0f} GB"
        self.memory_tile.set_value(sample.memory_percent, detail)
        self.gpu_tile.set_value(sample.gpu_percent, "3D engine")
        self.disk_tile.set_value(sample.disk_percent, "All drives")

    def set_live_paused(self, paused: bool) -> None:
        self.live_state.setText("Paused" if paused else "Monitoring")
        self.live_state.set_tone("muted" if paused else "positive")


__all__ = ["DashboardPage", "LiveTile", "QuickAction", "palette_for"]
