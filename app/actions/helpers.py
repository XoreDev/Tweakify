"""Small builders that keep the action catalogs readable."""

from __future__ import annotations

from app.actions.base import RegistryValueSpec
from app.domain.models import ActionDefinition, ActionKind, RestartRequirement, SafetyTier, Scope


def definition(
    id: str,
    title: str,
    module_id: str,
    group: str,
    description: str,
    changes: str,
    why: str,
    downside: str,
    rollback: str = "Restores the previous values from the snapshot.",
    scope: Scope = Scope.MACHINE,
    restart: RestartRequirement = RestartRequirement.NONE,
    tier: SafetyTier = SafetyTier.SAFE,
    kind: ActionKind = ActionKind.SETTING,
    **extra,
) -> ActionDefinition:
    return ActionDefinition(
        id=id,
        title=title,
        module_id=module_id,
        legacy_label=extra.pop("legacy_label", id),
        description=description,
        what_it_changes=changes,
        why_it_may_help=why,
        downside=downside,
        rollback=rollback,
        scope=scope,
        restart_requirement=restart,
        safety_tier=tier,
        kind=kind,
        public_group=group,
        **extra,
    )


def policy(path: str, name: str, value, value_type: str = "REG_DWORD") -> RegistryValueSpec:
    """A Group Policy value. Turning the tweak off deletes it.

    Writing the opposite value into a Policies key instead would *lock* the
    setting on and show "managed by your organization" in Settings.
    """
    return RegistryValueSpec(path, name, value_type, value, delete_on_disable=True)


def setting(path: str, name: str, on, off, value_type: str = "REG_DWORD") -> RegistryValueSpec:
    """A normal (non-policy) value with an explicit Windows default to return to."""
    return RegistryValueSpec(path, name, value_type, on, disabled_value=off, delete_on_disable=False)
