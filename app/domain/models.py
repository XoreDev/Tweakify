from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any


class Scope(str, Enum):
    USER = "user"
    MACHINE = "machine"


class RestartRequirement(str, Enum):
    NONE = "none"
    EXPLORER = "explorer"
    LOGOFF = "logoff"
    RESTART = "restart"


class SafetyTier(str, Enum):
    SAFE = "Safe"
    ADVANCED = "Advanced"
    EXPERIMENTAL = "Experimental"


class ActionKind(str, Enum):
    SETTING = "setting"
    MAINTENANCE = "maintenance"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PENDING_RESTART = "pending_restart"
    PENDING_LOGOFF = "pending_logoff"
    PENDING_EXPLORER = "pending_explorer_restart"
    NOT_VERIFIED = "not_verified"


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _json_ready(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


@dataclass(slots=True)
class ActionDefinition:
    id: str
    title: str
    module_id: str
    legacy_label: str
    description: str
    what_it_changes: str
    why_it_may_help: str
    downside: str
    rollback: str
    scope: Scope
    restart_requirement: RestartRequirement
    safety_tier: SafetyTier
    kind: ActionKind = ActionKind.SETTING
    public_group: str = "General"
    tags: tuple[str, ...] = ()
    requires_dependency: str | None = None
    min_build: int | None = None
    max_build: int | None = None
    user_scope_only: bool = False
    verification_policy: str = "state_probe"
    visibility_policy: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class ActionProbeResult:
    action_id: str
    current_state: bool | None
    available: bool
    summary: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    effective_value: Any | None = None
    verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class DryRunDescription:
    action_id: str
    target_state: bool
    summary: str
    commands: list[str]

    def render(self) -> str:
        command_text = "\n".join(f"  - {command}" for command in self.commands)
        state = "On" if self.target_state else "Off"
        return f"{self.summary}\nTarget: {state}\n{command_text}"


@dataclass(slots=True)
class SnapshotEntry:
    action_id: str
    target_state: bool
    before_state: Any
    after_state: Any
    reversible: bool = True
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotEntry":
        return cls(**payload)


@dataclass(slots=True)
class SnapshotManifest:
    snapshot_id: str
    created_at: str
    label: str
    is_baseline: bool
    machine_name: str
    action_entries: list[SnapshotEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "label": self.label,
            "is_baseline": self.is_baseline,
            "machine_name": self.machine_name,
            "action_entries": [entry.to_dict() for entry in self.action_entries],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotManifest":
        entries = [SnapshotEntry.from_dict(item) for item in payload["action_entries"]]
        return cls(
            snapshot_id=payload["snapshot_id"],
            created_at=payload["created_at"],
            label=payload["label"],
            is_baseline=payload["is_baseline"],
            machine_name=payload["machine_name"],
            action_entries=entries,
        )


@dataclass(slots=True)
class ActionResult:
    action_id: str
    success: bool
    message: str
    snapshot_entry: SnapshotEntry | None = None
    requires_restart: bool = False
    verification_status: VerificationStatus = VerificationStatus.NOT_VERIFIED
    effective_value: Any | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ActionResult":
        snapshot_entry = payload.get("snapshot_entry")
        status = payload.get("verification_status", VerificationStatus.NOT_VERIFIED.value)
        return cls(
            action_id=payload["action_id"],
            success=payload["success"],
            message=payload["message"],
            snapshot_entry=SnapshotEntry.from_dict(snapshot_entry) if snapshot_entry else None,
            requires_restart=payload.get("requires_restart", False),
            verification_status=VerificationStatus(status),
            effective_value=payload.get("effective_value"),
            failure_reason=payload.get("failure_reason"),
        )


@dataclass(slots=True)
class CompatibilityDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class CompatibilityRule:
    id: str
    title: str
    description: str
    severity: str = "warning"


@dataclass(slots=True)
class StagedAction:
    action_id: str
    target_state: bool
    module_id: str
    title: str
    scope: Scope
    kind: ActionKind

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class ActionPlan:
    plan_id: str
    created_at: str
    changes: list[StagedAction]
    startup_changes: list["StartupEntryChange"]
    dry_run_text: str
    requires_elevation: bool
    compatibility: dict[str, CompatibilityDecision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "changes": [change.to_dict() for change in self.changes],
            "startup_changes": [change.to_dict() for change in self.startup_changes],
            "dry_run_text": self.dry_run_text,
            "requires_elevation": self.requires_elevation,
            "compatibility": {
                key: decision.to_dict() for key, decision in self.compatibility.items()
            },
        }


@dataclass(slots=True)
class ApplyTransaction:
    transaction_id: str
    created_at: str
    dry_run: bool
    action_ids: list[str]
    results: list[ActionResult]
    snapshot_id: str | None = None
    requested_elevation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "created_at": self.created_at,
            "dry_run": self.dry_run,
            "action_ids": self.action_ids,
            "results": [result.to_dict() for result in self.results],
            "snapshot_id": self.snapshot_id,
            "requested_elevation": self.requested_elevation,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApplyTransaction":
        return cls(
            transaction_id=payload["transaction_id"],
            created_at=payload["created_at"],
            dry_run=payload["dry_run"],
            action_ids=payload["action_ids"],
            results=[ActionResult.from_dict(item) for item in payload["results"]],
            snapshot_id=payload.get("snapshot_id"),
            requested_elevation=payload.get("requested_elevation", False),
        )


@dataclass(slots=True)
class PresetDefinition:
    id: str
    title: str
    description: str
    accent: str
    action_targets: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class DiagnosticItem:
    id: str
    title: str
    value: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class DiagnosticsSnapshot:
    captured_at: str
    items: list[DiagnosticItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiagnosticsSnapshot":
        return cls(
            captured_at=payload["captured_at"],
            items=[DiagnosticItem(**item) for item in payload["items"]],
        )


@dataclass(slots=True)
class StartupEntry:
    id: str
    name: str
    location: str
    enabled: bool
    status_source: str = "active"
    command: str = ""
    duplicate: bool = False
    source_kind: str = "registry"
    scope: str = "user"
    registry_path: str = ""
    value_name: str = ""
    file_path: str = ""
    original_path: str = ""
    managed_by_tweakify: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StartupEntry":
        return cls(**payload)


@dataclass(slots=True)
class AppSettings:
    theme_mode: str = "system"
    accent_intensity: float = 0.62
    compact_mode: bool = False
    reduced_motion: bool = False
    font_scale: float = 1.0
    auto_preview: bool = True
    confirm_before_apply: bool = True
    auto_capture_baseline: bool = True
    auto_restore_point_advanced: bool = True
    review_tray_open: bool = True
    auto_open_review_drawer: bool = True
    diagnostics_refresh_on_launch: bool = True
    diagnostics_refresh_interval_seconds: int = 300
    diagnostics_background_poll: bool = False
    diagnostics_cache_retention_days: int = 7
    nvidia_inspector_path: str = ""
    nvidia_profile_inspector_path: str = ""
    show_advanced: bool = True
    show_experimental: bool = False
    strict_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AppSettings":
        return cls(**payload)


@dataclass(slots=True)
class MachineContext:
    machine_name: str
    windows_build: int
    edition: str
    oem_vendor: str
    is_admin: bool
    nvidia_inspector_path: str | None
    bluetooth_devices: int


@dataclass(slots=True)
class StartupEntryChange:
    entry_id: str
    name: str
    location: str
    source_kind: str
    target_enabled: bool
    command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(self)


@dataclass(slots=True)
class PresetStats:
    preset_id: str
    total: int
    compatible: int
    blocked: int
    already_at_target: int
    will_stage: int
    reduced: bool
    enabled: bool = True
    message: str = ""


@dataclass(slots=True)
class PresetStageResult:
    preset_id: str
    total: int
    compatible: int
    blocked: int
    already_at_target: int
    will_stage: int
    added_to_review: int
    message: str = ""


@dataclass(slots=True)
class DependencyInstallResult:
    dependency_name: str
    success: bool
    message: str
    installed_path: str | None = None


class SnapshotWriter:
    def __init__(self) -> None:
        self.entries: list[SnapshotEntry] = []

    def capture(
        self,
        action_id: str,
        target_state: bool,
        before_state: Any,
        after_state: Any,
        reversible: bool = True,
        notes: str = "",
    ) -> SnapshotEntry:
        entry = SnapshotEntry(
            action_id=action_id,
            target_state=target_state,
            before_state=before_state,
            after_state=after_state,
            reversible=reversible,
            notes=notes,
        )
        self.entries.append(entry)
        return entry
