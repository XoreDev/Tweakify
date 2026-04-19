from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.actions.catalog import build_action_catalog
from app.domain.compatibility import CompatibilityService
from app.domain.models import (
    ActionProbeResult,
    ActionKind,
    ActionPlan,
    AppSettings,
    ApplyTransaction,
    CompatibilityDecision,
    DiagnosticItem,
    DiagnosticsSnapshot,
    DependencyInstallResult,
    MachineContext,
    PresetStageResult,
    PresetStats,
    SafetyTier,
    SnapshotEntry,
    SnapshotManifest,
    StagedAction,
    StartupEntry,
    StartupEntryChange,
)
from app.domain.presets import build_presets
from app.platform.diagnostics import DiagnosticsCollector
from app.platform.elevation import ElevationManager
from app.storage.state import TweakifyStateStore


MODULES = [
    ("dashboard", "Dashboard"),
    ("presets", "Presets"),
    ("startup", "Startup"),
    ("performance", "Performance"),
    ("network", "Network"),
    ("services", "Services"),
    ("cleanup", "Cleanup"),
    ("input_ui", "Input + UI"),
    ("graphics", "Graphics"),
    ("compatibility", "Compatibility"),
    ("restore", "Restore"),
    ("settings", "Settings"),
]


LOADING_RUNTIME_MESSAGE = "Live machine state is loading. Controls unlock after the background refresh finishes."


class TweakifyController:
    def __init__(
        self,
        platform,
        storage_root: Path | str | None,
        startup_profile: str = "full",
    ) -> None:
        self.platform = platform
        self.store = TweakifyStateStore(storage_root)
        self.settings = self.store.load_settings()
        self.startup_profile = startup_profile if startup_profile in {"full", "light"} else "full"
        self.runtime_pending = self.startup_profile == "light"
        self.platform.set_dependency_path("nvidiaInspector.exe", self.settings.nvidia_inspector_path or None)
        self.platform.set_dependency_path("nvidiaProfileInspector.exe", self.settings.nvidia_profile_inspector_path or None)
        self.elevation = ElevationManager(self.store.plans_dir)
        self.actions = build_action_catalog(platform)
        self.actions_by_id = {action.definition.id: action for action in self.actions}
        self.compatibility = CompatibilityService()
        self.diagnostics_collector = DiagnosticsCollector(platform)
        self.staged_targets: dict[str, bool] = {}
        self.staged_startup_entries: dict[str, bool] = {}
        self.machine_context = (
            self.platform.bootstrap_machine_context()
            if self.runtime_pending
            else self.platform.machine_context()
        )
        if self.runtime_pending:
            self.compatibility_by_action = self._loading_compatibility()
            self.action_states = self._placeholder_action_states()
            self.startup_inventory = self._placeholder_startup_inventory()
            self.startup_inventory_by_id: dict[str, StartupEntry] = {}
            self.diagnostics = self.store.load_diagnostics() or self._placeholder_diagnostics()
        else:
            self.compatibility_by_action = self._evaluate_actions()
            self.action_states = self.refresh_action_states()
            self.startup_inventory = self.refresh_startup_inventory()
            cached_diagnostics = self.store.load_diagnostics()
            if self.settings.diagnostics_refresh_on_launch or cached_diagnostics is None:
                self.diagnostics = self.refresh_diagnostics(startup_inventory=self.startup_inventory)
            else:
                self.diagnostics = cached_diagnostics
            self.ensure_baseline_snapshot()
        self.presets = self.refresh_presets()

    def refresh_machine_context(self) -> MachineContext:
        self.platform.set_dependency_path("nvidiaInspector.exe", self.settings.nvidia_inspector_path or None)
        self.machine_context = self.platform.machine_context()
        self.compatibility_by_action = (
            self._loading_compatibility() if self.runtime_pending else self._evaluate_actions()
        )
        return self.machine_context

    def refresh_diagnostics(self, startup_inventory: dict[str, object] | None = None):
        self.diagnostics = self.diagnostics_collector.collect(startup_inventory=startup_inventory)
        self.store.save_diagnostics(self.diagnostics)
        return self.diagnostics

    def refresh_action_states(self):
        self.action_states = {action.definition.id: action.probe() for action in self.actions}
        return self.action_states

    def refresh_startup_inventory(self):
        self.startup_inventory = self.platform.startup_inventory()
        self.startup_inventory_by_id = {
            item.id: item
            for item in self.startup_inventory["items"]
        }
        return self.startup_inventory

    def refresh_presets(self):
        self.presets = build_presets(self.actions, self.baseline_targets())
        return self.presets

    def update_setting(self, name: str, value) -> AppSettings:
        if name == "theme_mode" and value not in {"system", "light", "dark"}:
            value = "system"
        setattr(self.settings, name, value)
        self.store.save_settings(self.settings)
        if name == "nvidia_inspector_path":
            self.platform.set_dependency_path("nvidiaInspector.exe", value or None)
        if name == "nvidia_profile_inspector_path":
            self.platform.set_dependency_path("nvidiaProfileInspector.exe", value or None)
        return self.settings

    def refresh_appearance_only(self) -> AppSettings:
        return self.settings

    def refresh_visibility_only(self):
        self.compatibility_by_action = (
            self._loading_compatibility() if self.runtime_pending else self._evaluate_actions()
        )
        self.refresh_presets()
        return self.compatibility_by_action

    def refresh_integrations_only(self) -> dict[str, str | None]:
        configured = self.settings.nvidia_inspector_path.strip()
        detected = Path(configured) if configured else None
        if detected is None or not detected.exists():
            detected = self.platform.detect_nvidia_inspector_known_locations()
        resolved = str(detected) if detected and detected.exists() else ""
        if resolved != self.settings.nvidia_inspector_path:
            self.settings.nvidia_inspector_path = resolved
            self.store.save_settings(self.settings)
        self.platform.set_dependency_path("nvidiaInspector.exe", resolved or None)
        self.machine_context = replace(
            self.machine_context,
            nvidia_inspector_path=resolved or None,
        )
        configured_profile = self.settings.nvidia_profile_inspector_path.strip()
        detected_profile = Path(configured_profile) if configured_profile else None
        if detected_profile is None or not detected_profile.exists():
            detected_profile = self.platform.detect_nvidia_profile_inspector_known_locations()
        resolved_profile = str(detected_profile) if detected_profile and detected_profile.exists() else ""
        if resolved_profile != self.settings.nvidia_profile_inspector_path:
            self.settings.nvidia_profile_inspector_path = resolved_profile
            self.store.save_settings(self.settings)
        self.platform.set_dependency_path("nvidiaProfileInspector.exe", resolved_profile or None)
        self.compatibility_by_action = (
            self._loading_compatibility() if self.runtime_pending else self._evaluate_actions()
        )
        self.refresh_presets()
        return {
            "nvidia_inspector_path": resolved or None,
            "nvidia_profile_inspector_path": resolved_profile or None,
        }

    def download_nvidia_profile_inspector(self) -> DependencyInstallResult:
        result = self.platform.download_nvidia_profile_inspector()
        if result.success and result.installed_path:
            self.settings.nvidia_profile_inspector_path = result.installed_path
            self.store.save_settings(self.settings)
            self.platform.set_dependency_path("nvidiaProfileInspector.exe", result.installed_path)
        return result

    def build_runtime_snapshot(self, force_live_diagnostics: bool = True) -> dict[str, object]:
        probe_session = self.platform.probe_session() if hasattr(self.platform, "probe_session") else nullcontext()
        with probe_session:
            machine_context = self.platform.machine_context()
            action_states = {
                action.definition.id: action.probe()
                for action in self.actions
            }
            startup_inventory = self.platform.startup_inventory()
            if force_live_diagnostics:
                diagnostics = self.diagnostics_collector.collect(startup_inventory=startup_inventory)
            else:
                diagnostics = self.store.load_diagnostics() or self.diagnostics
            compatibility = {
                action.definition.id: self.compatibility.evaluate(machine_context, action.definition)
                for action in self.actions
            }
        return {
            "machine_context": machine_context,
            "action_states": action_states,
            "startup_inventory": startup_inventory,
            "diagnostics": diagnostics,
            "compatibility_by_action": compatibility,
        }

    def apply_runtime_snapshot(self, snapshot: dict[str, object]):
        self.machine_context = snapshot["machine_context"]  # type: ignore[assignment]
        self.action_states = snapshot["action_states"]  # type: ignore[assignment]
        self.startup_inventory = snapshot["startup_inventory"]  # type: ignore[assignment]
        self.startup_inventory_by_id = {
            item.id: item
            for item in self.startup_inventory["items"]  # type: ignore[index]
        }
        self.diagnostics = snapshot["diagnostics"]  # type: ignore[assignment]
        self.compatibility_by_action = snapshot["compatibility_by_action"]  # type: ignore[assignment]
        self.runtime_pending = False
        self.store.save_diagnostics(self.diagnostics)
        self.refresh_presets()
        return snapshot

    def _evaluate_actions(self):
        return {
            action.definition.id: self.compatibility.evaluate(self.machine_context, action.definition)
            for action in self.actions
        }

    def module_actions(self, module_id: str):
        return [action for action in self.actions if action.definition.module_id == module_id]

    def visible_actions(self, module_id: str):
        actions = self.module_actions(module_id)
        visible = []
        for action in actions:
            if action.definition.safety_tier == SafetyTier.EXPERIMENTAL and not self.settings.show_experimental:
                continue
            if (
                action.definition.safety_tier == SafetyTier.ADVANCED
                and not self.settings.show_advanced
            ):
                continue
            visible.append(action)
        return visible

    def module_sections(self, module_id: str) -> list[tuple[str, list]]:
        sections: dict[str, list] = {}
        for action in self.visible_actions(module_id):
            sections.setdefault(action.definition.public_group, []).append(action)
        return list(sections.items())

    def current_state(self, action_id: str) -> bool:
        probe = self.action_states[action_id]
        return bool(probe.current_state)

    def target_state(self, action_id: str) -> bool:
        return self.staged_targets.get(action_id, self.current_state(action_id))

    def is_changed(self, action_id: str) -> bool:
        return action_id in self.staged_targets

    def current_startup_entry_enabled(self, entry_id: str) -> bool:
        entry = self.startup_inventory_by_id[entry_id]
        return bool(entry.enabled)

    def target_startup_entry_enabled(self, entry_id: str) -> bool:
        return self.staged_startup_entries.get(entry_id, self.current_startup_entry_enabled(entry_id))

    def is_startup_entry_changed(self, entry_id: str) -> bool:
        return entry_id in self.staged_startup_entries

    def stage_action(self, action_id: str, target_state: bool) -> None:
        if self.runtime_pending:
            return
        action = self.actions_by_id[action_id]
        if action.definition.kind == ActionKind.MAINTENANCE and not target_state:
            self.staged_targets.pop(action_id, None)
            return
        if action.definition.kind == ActionKind.MAINTENANCE:
            self.staged_targets[action_id] = True
            return
        if target_state == self.current_state(action_id):
            self.staged_targets.pop(action_id, None)
            return
        self.staged_targets[action_id] = target_state

    def stage_startup_entry(self, entry_id: str, target_enabled: bool) -> None:
        if self.runtime_pending:
            return
        if entry_id not in self.startup_inventory_by_id:
            return
        if target_enabled == self.current_startup_entry_enabled(entry_id):
            self.staged_startup_entries.pop(entry_id, None)
            return
        self.staged_startup_entries[entry_id] = target_enabled

    def preset_stats(self, preset_id: str) -> PresetStats:
        preset = next(preset for preset in self.presets if preset.id == preset_id)
        total = len(preset.action_targets)
        if self.runtime_pending:
            return PresetStats(
                preset_id=preset_id,
                total=total,
                compatible=0,
                blocked=total,
                already_at_target=0,
                will_stage=0,
                reduced=True,
                enabled=False,
                message=LOADING_RUNTIME_MESSAGE,
            )
        if preset_id == "baseline_restore" and total == 0:
            return PresetStats(
                preset_id=preset_id,
                total=0,
                compatible=0,
                blocked=0,
                already_at_target=0,
                will_stage=0,
                reduced=True,
                enabled=False,
                message="Capture a baseline first to restore actions back to their saved state.",
            )

        compatible = 0
        blocked = 0
        already_at_target = 0
        will_stage = 0
        for action_id, target_state in preset.action_targets.items():
            action = self.actions_by_id.get(action_id)
            if action is None:
                continue
            decision = self.compatibility_by_action.get(action_id)
            if not decision or not decision.allowed:
                blocked += 1
                continue
            compatible += 1
            if action.definition.kind == ActionKind.MAINTENANCE:
                will_stage += 1
                continue
            if target_state == self.current_state(action_id):
                already_at_target += 1
            else:
                will_stage += 1

        message = ""
        if preset_id == "baseline_restore" and compatible and will_stage == 0:
            message = "Already at baseline."

        return PresetStats(
            preset_id=preset_id,
            total=total,
            compatible=compatible,
            blocked=blocked,
            already_at_target=already_at_target,
            will_stage=will_stage,
            reduced=compatible < 15,
            enabled=True,
            message=message,
        )

    def preset_availability(self, preset_id: str) -> dict[str, int | bool]:
        stats = self.preset_stats(preset_id)
        return {
            "available": stats.compatible,
            "total": stats.total,
            "reduced": stats.reduced,
        }

    def stage_preset(self, preset_id: str) -> PresetStageResult:
        stats = self.preset_stats(preset_id)
        if not stats.enabled:
            return PresetStageResult(
                preset_id=preset_id,
                total=stats.total,
                compatible=stats.compatible,
                blocked=stats.blocked,
                already_at_target=stats.already_at_target,
                will_stage=stats.will_stage,
                added_to_review=0,
                message=stats.message,
            )

        before = len(self.staged_targets)
        preset = next(preset for preset in self.presets if preset.id == preset_id)
        for action_id, target_state in preset.action_targets.items():
            action = self.actions_by_id.get(action_id)
            if action is None:
                continue
            decision = self.compatibility_by_action[action_id]
            if not decision.allowed:
                continue
            self.stage_action(action_id, target_state)
        added_to_review = max(0, len(self.staged_targets) - before)
        message = stats.message
        if not message:
            message = (
                f"Added {added_to_review} item(s) to review."
                if added_to_review
                else "No new changes were added to review."
            )
        return PresetStageResult(
            preset_id=preset_id,
            total=stats.total,
            compatible=stats.compatible,
            blocked=stats.blocked,
            already_at_target=stats.already_at_target,
            will_stage=stats.will_stage,
            added_to_review=added_to_review,
            message=message,
        )

    def clear_staging(self) -> None:
        self.staged_targets.clear()
        self.staged_startup_entries.clear()

    def total_staged_count(self) -> int:
        return len(self.staged_targets) + len(self.staged_startup_entries)

    def build_plan(self) -> ActionPlan:
        created_at = datetime.now(UTC).isoformat()
        changes: list[StagedAction] = []
        startup_changes: list[StartupEntryChange] = []
        dry_run_parts: list[str] = []
        compatibility: dict[str, CompatibilityDecision] = {}
        requires_elevation = False

        for action_id, target_state in self.staged_targets.items():
            action = self.actions_by_id[action_id]
            decision = self.compatibility_by_action[action_id]
            compatibility[action_id] = decision
            if not decision.allowed:
                dry_run_parts.append(
                    f"{action.definition.title}: blocked\n  - " + "\n  - ".join(decision.reasons)
                )
                continue
            staged = StagedAction(
                action_id=action.definition.id,
                target_state=target_state,
                module_id=action.definition.module_id,
                title=action.definition.title,
                scope=action.definition.scope,
                kind=action.definition.kind,
            )
            changes.append(staged)
            dry_run_parts.append(action.plan(target_state).render())
            if action.definition.scope.value == "machine":
                requires_elevation = True

        for entry_id, target_enabled in self.staged_startup_entries.items():
            entry = self.startup_inventory_by_id.get(entry_id)
            if entry is None:
                continue
            startup_changes.append(
                StartupEntryChange(
                    entry_id=entry.id,
                    name=entry.name,
                    location=entry.location,
                    source_kind=entry.source_kind,
                    target_enabled=target_enabled,
                    command=entry.command or entry.original_path or entry.file_path,
                )
            )
            if entry.scope == "machine":
                requires_elevation = True
            dry_run_parts.append(
                "\n".join(
                    [
                        f"Startup Entry: {entry.name}",
                        f"Target: {'Enabled' if target_enabled else 'Disabled'}",
                        f"  - Source: {entry.source_kind}",
                        f"  - Location: {entry.location}",
                        f"  - Command: {entry.command or entry.original_path or entry.file_path or 'Unavailable'}",
                    ]
                )
            )

        return ActionPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            created_at=created_at,
            changes=changes,
            startup_changes=startup_changes,
            dry_run_text="\n\n".join(dry_run_parts) if dry_run_parts else "No staged changes.",
            requires_elevation=requires_elevation and not self.machine_context.is_admin,
            compatibility=compatibility,
        )

    def preview_staged(self) -> ActionPlan:
        return self.build_plan()

    def apply_staged(self) -> ApplyTransaction:
        plan = self.build_plan()
        transaction_id = f"apply-{uuid.uuid4().hex[:12]}"
        if plan.requires_elevation:
            self.elevation.write_plan_file(plan.to_dict())
            transaction = ApplyTransaction(
                transaction_id=transaction_id,
                created_at=datetime.now(UTC).isoformat(),
                dry_run=False,
                action_ids=[change.action_id for change in plan.changes] + [change.entry_id for change in plan.startup_changes],
                results=[],
                requested_elevation=True,
            )
            self.store.save_transaction(transaction)
            self.clear_staging()
            self.refresh_presets()
            return transaction

        if self.settings.auto_restore_point_advanced and any(
            self.actions_by_id[change.action_id].definition.safety_tier != SafetyTier.SAFE
            for change in plan.changes
        ):
            self.platform.create_restore_point("Tweakify Advanced Apply")

        writer = self.platform.snapshot_writer()
        results = []
        for change in plan.changes:
            action = self.actions_by_id[change.action_id]
            results.append(action.apply(change.target_state, writer))
        for change in plan.startup_changes:
            current_enabled = self.current_startup_entry_enabled(change.entry_id)
            snapshot_entry = writer.capture(
                action_id=change.entry_id,
                target_state=change.target_enabled,
                before_state=self._startup_snapshot_state(change.entry_id, change.name, current_enabled),
                after_state=self._startup_snapshot_state(change.entry_id, change.name, change.target_enabled),
                reversible=True,
                notes=f"Startup entry::{change.name}",
            )
            self.platform.startup_entry_set_enabled(change.entry_id, change.target_enabled)
            results.append(
                self._startup_entry_result(
                    change.entry_id,
                    change.name,
                    change.target_enabled,
                    snapshot_entry,
                )
            )

        snapshot_id = None
        if writer.entries:
            snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
            manifest = SnapshotManifest(
                snapshot_id=snapshot_id,
                created_at=datetime.now(UTC).isoformat(),
                label="Applied review tray",
                is_baseline=False,
                machine_name=self.machine_context.machine_name,
                action_entries=writer.entries,
            )
            self.store.save_snapshot(manifest)

        transaction = ApplyTransaction(
            transaction_id=transaction_id,
            created_at=datetime.now(UTC).isoformat(),
            dry_run=False,
            action_ids=[change.action_id for change in plan.changes] + [change.entry_id for change in plan.startup_changes],
            results=results,
            snapshot_id=snapshot_id,
        )
        self.store.save_transaction(transaction)
        self.clear_staging()
        self.refresh_machine_context()
        self.refresh_action_states()
        self.refresh_startup_inventory()
        self.refresh_diagnostics()
        self.refresh_presets()
        return transaction

    def rollback_snapshot(self, snapshot_id: str) -> ApplyTransaction:
        snapshot = self.store.load_snapshot(snapshot_id)
        if snapshot is None:
            return ApplyTransaction(
                transaction_id=f"rollback-{uuid.uuid4().hex[:12]}",
                created_at=datetime.now(UTC).isoformat(),
                dry_run=False,
                action_ids=[],
                results=[],
            )

        results = []
        for entry in snapshot.action_entries:
            if self._is_startup_snapshot(entry):
                results.append(self._rollback_startup_snapshot(entry))
                continue
            action = self.actions_by_id.get(entry.action_id)
            if action is None:
                continue
            results.append(action.rollback(entry))

        transaction = ApplyTransaction(
            transaction_id=f"rollback-{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(UTC).isoformat(),
            dry_run=False,
            action_ids=[entry.action_id for entry in snapshot.action_entries],
            results=results,
            snapshot_id=snapshot.snapshot_id,
        )
        self.store.save_transaction(transaction)
        self.refresh_machine_context()
        self.refresh_action_states()
        self.refresh_startup_inventory()
        self.refresh_diagnostics()
        self.refresh_presets()
        return transaction

    def ensure_baseline_snapshot(self) -> None:
        self.capture_initial_baseline_if_needed()

    def capture_initial_baseline_if_needed(self) -> SnapshotManifest | None:
        if not self.settings.auto_capture_baseline:
            return None
        if self.store.latest_baseline() is not None:
            return None
        manifest = self._capture_baseline(label="Initial Baseline", notes="Initial baseline capture.")
        self.refresh_presets()
        return manifest

    def capture_new_baseline(self) -> SnapshotManifest:
        manifest = self._capture_baseline(label="Manual Baseline", notes="Manual baseline capture.")
        self.refresh_presets()
        return manifest

    def _capture_baseline(self, label: str, notes: str) -> SnapshotManifest:
        entries: list[SnapshotEntry] = []
        for action in self.actions:
            if action.definition.kind != ActionKind.SETTING:
                continue
            before_state = action.capture_state()
            entries.append(
                SnapshotEntry(
                    action_id=action.definition.id,
                    target_state=bool(action.is_enabled()),
                    before_state=before_state,
                    after_state=before_state,
                    reversible=True,
                    notes=notes,
                )
            )
        manifest = SnapshotManifest(
            snapshot_id=f"baseline-{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(UTC).isoformat(),
            label=label,
            is_baseline=True,
            machine_name=self.machine_context.machine_name,
            action_entries=entries,
        )
        self.store.save_snapshot(manifest)
        return manifest

    def create_restore_point(self) -> bool:
        return self.platform.create_restore_point("Tweakify Restore Point")

    def open_task_manager(self) -> None:
        self.platform.open_task_manager()

    def baseline_targets(self) -> dict[str, bool]:
        baseline = self.store.latest_baseline()
        if baseline is None:
            return {}
        return {entry.action_id: entry.target_state for entry in baseline.action_entries}

    def _startup_entry_result(self, entry_id: str, name: str, target_enabled: bool, snapshot_entry=None):
        from app.domain.models import ActionResult

        state_copy = "Enabled" if target_enabled else "Disabled"
        return ActionResult(
            action_id=entry_id,
            success=True,
            message=f"Startup entry {name} {state_copy.lower()}.",
            effective_value=target_enabled,
            snapshot_entry=snapshot_entry,
        )

    def _startup_snapshot_state(self, entry_id: str, name: str, enabled: bool) -> dict[str, object]:
        return {
            "kind": "startup_entry",
            "entry_id": entry_id,
            "entry_name": name,
            "enabled": enabled,
        }

    def _is_startup_snapshot(self, entry: SnapshotEntry) -> bool:
        return isinstance(entry.before_state, dict) and entry.before_state.get("kind") == "startup_entry"

    def _rollback_startup_snapshot(self, snapshot_entry: SnapshotEntry):
        before_state = snapshot_entry.before_state if isinstance(snapshot_entry.before_state, dict) else {}
        target_enabled = bool(before_state.get("enabled"))
        entry = self.startup_inventory_by_id.get(snapshot_entry.action_id)
        entry_name = str(before_state.get("entry_name") or (entry.name if entry else snapshot_entry.action_id))
        self.platform.startup_entry_set_enabled(snapshot_entry.action_id, target_enabled)
        self.refresh_startup_inventory()
        result = self._startup_entry_result(snapshot_entry.action_id, entry_name, target_enabled)
        result.snapshot_entry = snapshot_entry
        return result

    def blocked_actions_text(self) -> str:
        if self.runtime_pending:
            return "Compatibility is loading. Live dependency, build, and capability checks will appear shortly."
        lines = []
        for action in self.actions:
            decision = self.compatibility_by_action[action.definition.id]
            if decision.allowed:
                continue
            lines.append(f"- {action.definition.title}: {'; '.join(decision.reasons)}")
        return "\n".join(lines) if lines else "No current compatibility blocks."

    def machine_summary_text(self) -> str:
        if self.runtime_pending:
            return (
                f"Build {self.machine_context.windows_build} | "
                f"{self.machine_context.edition} | "
                "Refreshing live machine state in the background."
            )
        startup_duplicates = len(self.startup_inventory["duplicates"]) if self.startup_inventory else 0
        return (
            f"Build {self.machine_context.windows_build} | "
            f"{self.machine_context.edition} | "
            f"OEM {self.machine_context.oem_vendor or 'Unknown'} | "
            f"Startup duplicates {startup_duplicates} | "
            f"Elevation {'On' if self.machine_context.is_admin else 'Required for machine-scope apply'}"
        )

    def serialize_plan(self, plan: ActionPlan) -> str:
        return json.dumps(plan.to_dict(), indent=2)

    def _loading_compatibility(self) -> dict[str, CompatibilityDecision]:
        return {
            action.definition.id: CompatibilityDecision(
                allowed=False,
                reasons=[LOADING_RUNTIME_MESSAGE],
            )
            for action in self.actions
        }

    def _placeholder_action_states(self) -> dict[str, ActionProbeResult]:
        return {
            action.definition.id: ActionProbeResult(
                action_id=action.definition.id,
                current_state=None,
                available=False,
                summary=action.definition.description,
                reasons=[LOADING_RUNTIME_MESSAGE],
            )
            for action in self.actions
        }

    def _placeholder_startup_inventory(self) -> dict[str, object]:
        return {"count": 0, "duplicates": [], "items": []}

    def _placeholder_diagnostics(self) -> DiagnosticsSnapshot:
        return DiagnosticsSnapshot(
            captured_at=datetime.now(UTC).isoformat(),
            items=[
                DiagnosticItem(
                    id="loading",
                    title="Diagnostics",
                    value="Loading...",
                    status="info",
                    detail="Live diagnostics are loading in the background.",
                )
            ],
        )
