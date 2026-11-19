from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.actions.catalog import build_action_catalog
from app.actions.game_profiles import GAME_PRIORITY_ACTION_ID, build_game_priority_action, parse_game_executables
from app.domain.compatibility import CompatibilityService
from app.domain.health import CLEANUP_TARGETS, HealthReport, build_health_report
from app.domain.models import (
    ActionResult,
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
    ("gaming", "Gaming"),
    ("network", "Network"),
    ("privacy", "Privacy"),
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
        self.actions.append(build_game_priority_action(platform, self.settings.game_executables))
        self.actions_by_id = {action.definition.id: action for action in self.actions}
        self.compatibility = CompatibilityService()
        self.diagnostics_collector = DiagnosticsCollector(platform)
        self.staged_targets: dict[str, bool] = {}
        self.staged_startup_entries: dict[str, bool] = {}
        self.cleanup_sizes: dict[str, int] = {}
        self.last_stage_notice = ""
        # The full profile replaces this with the probed context from the runtime snapshot below.
        self.machine_context = self.platform.bootstrap_machine_context()
        if self.runtime_pending:
            self.compatibility_by_action = self._loading_compatibility()
            self.action_states = self._placeholder_action_states()
            self.startup_inventory = self._placeholder_startup_inventory()
            self.startup_inventory_by_id: dict[str, StartupEntry] = {}
            self.diagnostics = self.store.load_diagnostics() or self._placeholder_diagnostics()
        else:
            # One cached, parallel probe pass instead of ~115 uncached serial probes
            # (the CLI path took ~47 s on a real machine before this).
            self.diagnostics = self.store.load_diagnostics() or self._placeholder_diagnostics()
            live = self.settings.diagnostics_refresh_on_launch or self.store.load_diagnostics() is None
            self.apply_runtime_snapshot(self.build_runtime_snapshot(force_live_diagnostics=live))
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
        if name == "game_executables":
            self._rebuild_game_priority_action()
        return self.settings

    def _rebuild_game_priority_action(self) -> None:
        action = build_game_priority_action(self.platform, self.settings.game_executables)
        index = next(i for i, item in enumerate(self.actions) if item.definition.id == GAME_PRIORITY_ACTION_ID)
        self.actions[index] = action
        self.actions_by_id[GAME_PRIORITY_ACTION_ID] = action
        self.staged_targets.pop(GAME_PRIORITY_ACTION_ID, None)
        if not self.runtime_pending:
            self.action_states[GAME_PRIORITY_ACTION_ID] = action.probe()
            self.compatibility_by_action[GAME_PRIORITY_ACTION_ID] = self._evaluate(self.machine_context, action)

    def _evaluate(self, machine_context, action) -> CompatibilityDecision:
        decision = self.compatibility.evaluate(machine_context, action.definition)
        if action.definition.id == GAME_PRIORITY_ACTION_ID and not parse_game_executables(self.settings.game_executables):
            decision = CompatibilityDecision(
                allowed=False,
                reasons=["Add your game executables under Settings > Games first."] + decision.reasons,
                warnings=decision.warnings,
            )
        return decision

    def stage_disable_all_startup(self) -> int:
        """Stage every enabled startup entry Off, the 'disable all startup apps' button tweak packs offer."""
        count = 0
        for entry in self.startup_inventory.get("items", []):
            if entry.enabled and entry.id not in self.staged_startup_entries:
                self.stage_startup_entry(entry.id, False)
                count += 1
        return count

    def run_latency_test(self) -> dict[str, float | None]:
        tester = getattr(self.platform, "network_latency", None)
        return dict(tester(["1.1.1.1", "8.8.8.8", "9.9.9.9"])) if tester else {}

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
        self.machine_context = replace(
            self.machine_context,
            nvidia_profile_inspector_path=resolved_profile or None,
        )
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
        workers = max(1, int(getattr(self.platform, "probe_workers", 1)))
        with probe_session:
            if workers == 1:
                machine_context = self.platform.machine_context()
                action_states = {action.definition.id: action.probe() for action in self.actions}
                startup_inventory = self.platform.startup_inventory()
                cleanup_sizes = self._scan_cleanup_sizes()
            else:
                # Nearly every probe waits on a subprocess (PowerShell, powercfg,
                # schtasks), so overlapping them is the single biggest win for
                # time-to-interactive. The platform's probe cache is lock-protected.
                bind = self._bind_probe_session
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tweakify-probe") as pool:
                    context_future = pool.submit(bind(self.platform.machine_context))
                    inventory_future = pool.submit(bind(self.platform.startup_inventory))
                    cleanup_future = pool.submit(bind(self._scan_cleanup_sizes))
                    probe_futures = {action.definition.id: pool.submit(bind(action.probe)) for action in self.actions}
                    machine_context = context_future.result()
                    startup_inventory = inventory_future.result()
                    cleanup_sizes = cleanup_future.result()
                    action_states = {action_id: future.result() for action_id, future in probe_futures.items()}
            if force_live_diagnostics:
                diagnostics = self.diagnostics_collector.collect(startup_inventory=startup_inventory)
            else:
                diagnostics = self.store.load_diagnostics() or self.diagnostics
            compatibility = {
                action.definition.id: self._evaluate(machine_context, action)
                for action in self.actions
            }
        return {
            "machine_context": machine_context,
            "action_states": action_states,
            "startup_inventory": startup_inventory,
            "diagnostics": diagnostics,
            "compatibility_by_action": compatibility,
            "cleanup_sizes": cleanup_sizes,
        }

    def _bind_probe_session(self, fn):
        binder = getattr(self.platform, "bind_probe_session", None)
        return binder(fn) if binder is not None else fn

    def _scan_cleanup_sizes(self) -> dict[str, int]:
        estimator = getattr(self.platform, "cleanup_estimate", None)
        if estimator is None:
            return {}
        try:
            return dict(estimator({key: list(value["paths"]) for key, value in CLEANUP_TARGETS.items()}))
        except Exception:
            return {}

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
        self.cleanup_sizes = dict(snapshot.get("cleanup_sizes") or {})  # type: ignore[arg-type]
        self.runtime_pending = False
        self.store.save_diagnostics(self.diagnostics)
        self.refresh_presets()
        return snapshot

    def _evaluate_actions(self):
        return {
            action.definition.id: self._evaluate(self.machine_context, action)
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
        self.last_stage_notice = ""
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
        if target_state:
            self._unstage_conflicts(action_id)

    def _unstage_conflicts(self, action_id: str) -> None:
        """Two actions that write the same setting cannot both be On in one plan."""
        definition = self.actions_by_id[action_id].definition
        conflicting = set(definition.conflicts_with)
        conflicting.update(
            other.definition.id for other in self.actions if action_id in other.definition.conflicts_with
        )
        removed = [
            self.actions_by_id[other_id].definition.title
            for other_id in sorted(conflicting)
            if self.staged_targets.get(other_id) is True and self.staged_targets.pop(other_id, None) is not None
        ]
        if removed:
            self.last_stage_notice = f"{definition.title} replaces {', '.join(removed)} in this plan."

    def stage_action_ids(self, action_ids: list[str]) -> list[str]:
        """Stage actions On by id. Returns the ids that do not exist."""
        unknown = []
        for action_id in action_ids:
            if action_id not in self.actions_by_id:
                unknown.append(action_id)
                continue
            if self.compatibility_by_action.get(action_id, CompatibilityDecision(allowed=True)).allowed:
                self.stage_action(action_id, True)
        return unknown

    def stage_plan_payload(self, payload: dict) -> list[str]:
        """Stage an exported plan. Returns titles of entries that could not be staged."""
        skipped: list[str] = []
        for change in payload.get("changes", []):
            action_id = change.get("action_id")
            if action_id not in self.actions_by_id:
                skipped.append(str(change.get("title") or action_id))
                continue
            decision = self.compatibility_by_action.get(action_id)
            if decision is not None and not decision.allowed:
                skipped.append(self.actions_by_id[action_id].definition.title)
                continue
            self.stage_action(action_id, bool(change.get("target_state")))
        for change in payload.get("startup_changes", []):
            entry_id = change.get("entry_id")
            if entry_id not in self.startup_inventory_by_id:
                skipped.append(str(change.get("name") or entry_id))
                continue
            self.stage_startup_entry(entry_id, bool(change.get("target_enabled")))
        return skipped

    def export_staged_plan(self, path: Path | str) -> Path:
        target = Path(path)
        payload = self.build_plan().to_dict()
        payload["format"] = "tweakify-plan/1"
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def import_plan(self, path: Path | str) -> list[str]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("This file is not a Tweakify plan.")
        return self.stage_plan_payload(payload)

    def health_report(self) -> HealthReport:
        return build_health_report(self)

    def recommended_fix_ids(self) -> list[str]:
        """Safe, compatible, not-yet-applied actions the health findings point at."""
        if self.runtime_pending:
            return []
        ids: list[str] = []
        for finding in self.health_report().findings:
            for action_id in finding.action_ids:
                action = self.actions_by_id.get(action_id)
                if action is None or action_id in ids or action_id in self.staged_targets:
                    continue
                if action.definition.safety_tier != SafetyTier.SAFE:
                    continue
                decision = self.compatibility_by_action.get(action_id)
                if decision is None or not decision.allowed:
                    continue
                if action.definition.kind == ActionKind.SETTING and self.current_state(action_id):
                    continue
                ids.append(action_id)
        return ids

    def stage_recommended_fixes(self) -> int:
        ids = self.recommended_fix_ids()
        for action_id in ids:
            self.stage_action(action_id, True)
        return len(ids)

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
        action_ids = [change.action_id for change in plan.changes] + [change.entry_id for change in plan.startup_changes]
        if plan.requires_elevation:
            plan_path = self.elevation.write_plan_file(plan.to_dict())
            notes = []
            if getattr(self.platform, "supports_elevated_helper", False):
                try:
                    self.elevation.launch_elevated(self.elevation.build_apply_command(plan_path))
                    notes.append("Machine-scope changes were handed to the elevated helper. Approve the UAC prompt to apply them.")
                except Exception as exc:
                    notes.append(f"The elevated helper could not start: {exc}")
            else:
                notes.append(f"Machine-scope changes were saved to {plan_path} for the elevated helper.")
            transaction = ApplyTransaction(
                transaction_id=transaction_id,
                created_at=datetime.now(UTC).isoformat(),
                dry_run=False,
                action_ids=action_ids,
                results=[],
                requested_elevation=True,
                notes=notes,
            )
            self.store.save_transaction(transaction)
            self.clear_staging()
            self.refresh_presets()
            return transaction

        notes: list[str] = []
        if self.settings.auto_restore_point_advanced and any(
            self.actions_by_id[change.action_id].definition.safety_tier != SafetyTier.SAFE
            for change in plan.changes
        ):
            try:
                created = self.platform.create_restore_point("Tweakify Advanced Apply")
            except Exception:
                created = False
            notes.append(
                "Windows restore point created before applying Advanced changes."
                if created
                else "Windows could not create a restore point (System Protection may be off). "
                "Tweakify's own snapshot still records every change for rollback."
            )

        writer = self.platform.snapshot_writer()
        results: list[ActionResult] = []
        # One failing action must not stop the rest, and must never lose the
        # snapshot of the actions that already ran.
        try:
            for change in plan.changes:
                action = self.actions_by_id[change.action_id]
                try:
                    results.append(action.apply(change.target_state, writer))
                except Exception as exc:  # pragma: no cover - BaseAction.apply already isolates failures
                    results.append(
                        ActionResult(
                            action_id=change.action_id,
                            success=False,
                            message=f"{action.definition.title} failed: {exc}",
                            failure_reason=str(exc),
                        )
                    )
            for change in plan.startup_changes:
                current_enabled = self.current_startup_entry_enabled(change.entry_id)
                try:
                    self.platform.startup_entry_set_enabled(change.entry_id, change.target_enabled)
                except Exception as exc:
                    results.append(
                        ActionResult(
                            action_id=change.entry_id,
                            success=False,
                            message=f"Startup entry {change.name} could not be changed: {exc}",
                            failure_reason=str(exc),
                        )
                    )
                    continue
                snapshot_entry = writer.capture(
                    action_id=change.entry_id,
                    target_state=change.target_enabled,
                    before_state=self._startup_snapshot_state(change.entry_id, change.name, current_enabled),
                    after_state=self._startup_snapshot_state(change.entry_id, change.name, change.target_enabled),
                    reversible=True,
                    notes=f"Startup entry::{change.name}",
                )
                results.append(
                    self._startup_entry_result(
                        change.entry_id,
                        change.name,
                        change.target_enabled,
                        snapshot_entry,
                    )
                )
        finally:
            snapshot_id = self._save_apply_snapshot(writer)

        transaction = ApplyTransaction(
            transaction_id=transaction_id,
            created_at=datetime.now(UTC).isoformat(),
            dry_run=False,
            action_ids=action_ids,
            results=results,
            snapshot_id=snapshot_id,
            notes=notes,
        )
        self.store.save_transaction(transaction)
        self.clear_staging()
        self.refresh_machine_context()
        self.refresh_action_states()
        self.refresh_startup_inventory()
        self.refresh_diagnostics()
        self.refresh_presets()
        return transaction

    def _save_apply_snapshot(self, writer) -> str | None:
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
        return snapshot_id

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
        # Undo newest-first, the reverse of the order the changes were applied.
        for entry in reversed(snapshot.action_entries):
            try:
                if self._is_startup_snapshot(entry):
                    results.append(self._rollback_startup_snapshot(entry))
                    continue
                action = self.actions_by_id.get(entry.action_id)
                if action is None:
                    results.append(
                        ActionResult(
                            action_id=entry.action_id,
                            success=False,
                            message=f"{entry.action_id} is not part of this Tweakify version and was skipped.",
                        )
                    )
                    continue
                results.append(action.rollback(entry))
            except Exception as exc:
                results.append(
                    ActionResult(
                        action_id=entry.action_id,
                        success=False,
                        message=f"Rollback of {entry.action_id} failed: {exc}",
                        failure_reason=str(exc),
                    )
                )

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
        def read(action):
            try:
                return action.capture_state(), action.is_enabled()
            except Exception:
                return None

        settings_actions = [action for action in self.actions if action.definition.kind == ActionKind.SETTING]
        workers = max(1, int(getattr(self.platform, "probe_workers", 1)))
        probe_session = self.platform.probe_session() if hasattr(self.platform, "probe_session") else nullcontext()
        # Nothing is written while a baseline is captured, so one cached, parallel
        # read pass is safe (it took ~25 s serially on first launch).
        with probe_session:
            if workers == 1:
                readings = [read(action) for action in settings_actions]
            else:
                bound = self._bind_probe_session(read)
                with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tweakify-baseline") as pool:
                    readings = list(pool.map(bound, settings_actions))
        entries: list[SnapshotEntry] = []
        for action, reading in zip(settings_actions, readings):
            if reading is None:
                continue
            before_state, enabled = reading
            entries.append(
                SnapshotEntry(
                    action_id=action.definition.id,
                    target_state=bool(enabled),
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
        try:
            return bool(self.platform.create_restore_point("Tweakify Restore Point"))
        except Exception:
            return False

    def open_task_manager(self) -> None:
        self.platform.open_task_manager()

    def baseline_targets(self) -> dict[str, bool]:
        baseline = self.store.latest_baseline()
        if baseline is None:
            return {}
        return {entry.action_id: entry.target_state for entry in baseline.action_entries}

    def _startup_entry_result(self, entry_id: str, name: str, target_enabled: bool, snapshot_entry=None):
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
