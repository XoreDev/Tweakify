"""Review panel: the staged plan, a live dry run, and the only Apply button in the app."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import ActionKind
from app.ui.theme import ICONS
from app.ui.widgets import EmptyState, StatusChip, button, divider, icon_button, label


class StagedRow(QWidget):
    def __init__(self, title: str, transition: str, on_remove) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 6, 8)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_label = label(title, "h3", wrap=True)
        self.transition_label = label(transition, "subtle")
        text.addWidget(self.title_label)
        text.addWidget(self.transition_label)
        layout.addLayout(text, 1)
        remove = icon_button(ICONS["close"], f"Remove {title} from the plan", on_remove)
        remove.setFixedSize(28, 28)
        layout.addWidget(remove, 0, Qt.AlignVCenter)


class ReviewDrawer(QFrame):
    def __init__(self, controller, stage_refresh_callback, apply_callback, close_callback=None) -> None:
        super().__init__()
        self.controller = controller
        self.stage_refresh_callback = stage_refresh_callback
        self.apply_callback = apply_callback
        self.close_callback = close_callback
        self.result_message = ""
        self._apply_animation_frames = ("Applying staged changes.", "Applying staged changes..", "Applying staged changes...")
        self._apply_animation_index = 0
        self._apply_animation_timer = QTimer(self)
        self._apply_animation_timer.setInterval(220)
        self._apply_animation_timer.timeout.connect(self._advance_apply_animation)
        self.setObjectName("reviewPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(label("Review", "h2"))
        self.count_chip = StatusChip("0", tone="muted")
        header.addWidget(self.count_chip)
        header.addStretch(1)
        self.close_button = icon_button(ICONS["close"], "Close review", self._close)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.summary_label = label("", "muted", wrap=True)
        layout.addWidget(self.summary_label)

        self.staged_list = QListWidget()
        self.staged_list.setSelectionMode(QListWidget.NoSelection)
        self.staged_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        layout.addWidget(self.staged_list, 3)
        self.empty_state = EmptyState(ICONS["check"], "Nothing staged", "Flip any switch to add it here. Nothing changes until you apply.")
        layout.addWidget(self.empty_state, 3)

        layout.addWidget(divider())
        plan_header = QHBoxLayout()
        plan_header.addWidget(label("PLAN", "eyebrow"))
        plan_header.addStretch(1)
        self.preview_button = button("Refresh", "quietButton", self.show_dry_run)
        plan_header.addWidget(self.preview_button)
        layout.addLayout(plan_header)
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        self.plan_text.setObjectName("mono")
        layout.addWidget(self.plan_text, 2)

        self.apply_button = button("Apply", "primaryButton", self.apply)
        self.apply_button.setMinimumHeight(40)
        layout.addWidget(self.apply_button)
        secondary = QHBoxLayout()
        secondary.setSpacing(6)
        self.clear_button = button("Discard", "quietButton", self.clear)
        self.export_button = button("Export", "quietButton", self.export_plan, tooltip="Save this plan as a file to apply on another PC.")
        self.import_button = button("Import", "quietButton", self.import_plan, tooltip="Stage a plan exported from Tweakify.")
        for widget in (self.clear_button, self.export_button, self.import_button):
            secondary.addWidget(widget)
        secondary.addStretch(1)
        layout.addLayout(secondary)
        self.refresh()

    def sizeHint(self) -> QSize:  # pragma: no cover - layout hint
        return QSize(360, 600)

    def _close(self) -> None:
        if self.close_callback is not None:
            self.close_callback()

    # -- plan files
    def export_plan(self) -> None:
        if not self.controller.total_staged_count():
            self.show_stage_result("Stage some changes before exporting a plan.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export Tweakify plan", str(Path.home() / "tweakify-plan.json"), "Tweakify plan (*.json)")
        if not path:
            return
        self.controller.export_staged_plan(path)
        self.result_message = f"Plan exported to {path}. Apply it on another PC with Import, or Tweakify.py --apply-plan."
        self.plan_text.setPlainText(self.result_message)

    def import_plan(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import Tweakify plan", str(Path.home()), "Tweakify plan (*.json)")
        if not path:
            return
        try:
            skipped = self.controller.import_plan(path)
        except (OSError, ValueError) as exc:
            self.show_error(f"Could not import the plan: {exc}")
            return
        self.result_message = "Plan imported." + (f" Skipped (not available on this PC): {', '.join(skipped)}." if skipped else "")
        self.stage_refresh_callback()

    # -- list
    def _remove_action(self, action_id: str) -> None:
        self.controller.staged_targets.pop(action_id, None)
        self.stage_refresh_callback()

    def _remove_startup(self, entry_id: str) -> None:
        self.controller.staged_startup_entries.pop(entry_id, None)
        self.stage_refresh_callback()

    def _add_row(self, title: str, transition: str, on_remove) -> None:
        item = QListWidgetItem(self.staged_list)
        row = StagedRow(title, transition, on_remove)
        # sizeHint() is computed before the stylesheet polishes the row, so it is too short.
        item.setSizeHint(QSize(0, max(60, row.sizeHint().height() + 12)))
        self.staged_list.setItemWidget(item, row)

    def refresh(self) -> None:
        self.staged_list.clear()
        count = self.controller.total_staged_count()
        self.count_chip.setText(str(count))
        self.count_chip.set_tone("accent" if count else "muted")
        self.summary_label.setText(f"{count} pending change(s) staged for review." if count else "No pending changes.")
        self.staged_list.setVisible(bool(count))
        self.empty_state.setVisible(not count)
        self.apply_button.setText(f"Apply {count} change{'s' if count != 1 else ''}" if count else "Apply")
        self.apply_button.setEnabled(bool(count) and not self._apply_animation_timer.isActive())
        if not count:
            self.plan_text.setPlainText(self.result_message or "The dry-run plan appears here as you stage changes.")
        for action_id, target in self.controller.staged_targets.items():
            action = self.controller.actions_by_id[action_id]
            if action.definition.kind == ActionKind.MAINTENANCE:
                transition = "Runs once on Apply"
            else:
                current = self.controller.current_state(action_id)
                transition = f"{'On' if current else 'Off'}  →  {'On' if target else 'Off'}"
            self._add_row(action.definition.title, transition, lambda _c=False, i=action_id: self._remove_action(i))
        for entry_id, target in self.controller.staged_startup_entries.items():
            entry = self.controller.startup_inventory_by_id.get(entry_id)
            if entry is None:
                continue
            current = self.controller.current_startup_entry_enabled(entry_id)
            self._add_row(
                f"Startup: {entry.name}",
                f"{'On' if current else 'Off'}  →  {'On' if target else 'Off'}",
                lambda _c=False, i=entry_id: self._remove_startup(i),
            )
        if count and self.controller.settings.auto_preview and not self._apply_animation_timer.isActive():
            self.result_message = ""
            self.plan_text.setPlainText(self.controller.preview_staged().dry_run_text)

    def show_dry_run(self) -> None:
        self.plan_text.setPlainText(self.controller.preview_staged().dry_run_text)

    def show_stage_result(self, message: str) -> None:
        self.result_message = message
        self.refresh()

    # -- apply
    def apply(self) -> None:
        if not self.controller.total_staged_count():
            return
        if self.controller.settings.confirm_before_apply:
            count = self.controller.total_staged_count()
            answer = QMessageBox.question(
                self, "Apply changes", f"Apply {count} staged change(s) to this PC now?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
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
            self.result_message = "\n".join(transaction.notes) or "Machine-scope changes were handed to the elevated helper."
        else:
            lines = [("FAILED  " if not result.success else "OK      ") + result.message for result in transaction.results]
            failed = len(transaction.failed_results)
            header = f"{len(transaction.results) - failed} applied, {failed} failed." if failed else f"{len(transaction.results)} applied."
            self.result_message = "\n".join(part for part in [header, *transaction.notes, "", *lines] if part is not None).strip() or "Nothing applied."
        self.refresh()

    def show_error(self, message: str) -> None:
        self._stop_apply_animation()
        self.set_busy(False)
        self.result_message = f"Apply failed: {message}"
        self.plan_text.setPlainText(self.result_message)

    def set_busy(self, busy: bool) -> None:
        for widget in (self.preview_button, self.apply_button, self.clear_button, self.export_button, self.import_button):
            widget.setEnabled(not busy)
        if not busy:
            self.apply_button.setEnabled(bool(self.controller.total_staged_count()))

    def _start_apply_animation(self) -> None:
        self._apply_animation_index = 0
        self.result_message = self._apply_animation_frames[0]
        self.plan_text.setPlainText(self.result_message)
        self.apply_button.setText("Applying...")
        if not self._apply_animation_timer.isActive():
            self._apply_animation_timer.start()

    def _advance_apply_animation(self) -> None:
        self._apply_animation_index = (self._apply_animation_index + 1) % len(self._apply_animation_frames)
        self.result_message = self._apply_animation_frames[self._apply_animation_index]
        self.plan_text.setPlainText(self.result_message)

    def _stop_apply_animation(self) -> None:
        if self._apply_animation_timer.isActive():
            self._apply_animation_timer.stop()
