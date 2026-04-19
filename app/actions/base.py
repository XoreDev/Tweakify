from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.domain.models import (
    ActionDefinition,
    ActionKind,
    ActionProbeResult,
    ActionResult,
    DryRunDescription,
    RestartRequirement,
    SnapshotEntry,
    VerificationStatus,
)


@dataclass(slots=True)
class RegistryValueSpec:
    path: str
    name: str
    value_type: str
    enabled_value: Any
    disabled_value: Any | None = None
    delete_on_disable: bool = True
    delete_on_enable: bool = False


class BaseEffect(ABC):
    stateful = True

    def __init__(self, platform) -> None:
        self.platform = platform

    @abstractmethod
    def capture_state(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def restore_state(self, state: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self) -> bool | None:
        raise NotImplementedError

    @abstractmethod
    def plan_commands(self, target_state: bool) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def apply_target(self, target_state: bool) -> None:
        raise NotImplementedError


class RegistryEffect(BaseEffect):
    def __init__(self, platform, spec: RegistryValueSpec) -> None:
        super().__init__(platform)
        self.spec = spec

    def capture_state(self) -> dict[str, Any]:
        return {
            "path": self.spec.path,
            "name": self.spec.name,
            "value": self.platform.registry_get(self.spec.path, self.spec.name),
            "value_type": self.spec.value_type,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        if state["value"] is None:
            self.platform.registry_delete(state["path"], state["name"])
            return
        self.platform.registry_set(
            state["path"],
            state["name"],
            state["value"],
            state["value_type"],
        )

    def is_enabled(self) -> bool | None:
        current = self.platform.registry_get(self.spec.path, self.spec.name)
        if self.spec.delete_on_enable:
            return current is None
        return current == self.spec.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        if target_state and self.spec.delete_on_enable:
            return [f"reg delete {self.spec.path}::{self.spec.name}"]
        if target_state:
            return [f"reg set {self.spec.path}::{self.spec.name} -> {self.spec.enabled_value!r}"]
        if self.spec.delete_on_disable:
            return [f"reg delete {self.spec.path}::{self.spec.name}"]
        return [f"reg set {self.spec.path}::{self.spec.name} -> {self.spec.disabled_value!r}"]

    def apply_target(self, target_state: bool) -> None:
        if target_state and self.spec.delete_on_enable:
            self.platform.registry_delete(self.spec.path, self.spec.name)
            return
        if target_state:
            self.platform.registry_set(
                self.spec.path,
                self.spec.name,
                self.spec.enabled_value,
                self.spec.value_type,
            )
            return
        if self.spec.delete_on_disable:
            self.platform.registry_delete(self.spec.path, self.spec.name)
            return
        self.platform.registry_set(
            self.spec.path,
            self.spec.name,
            self.spec.disabled_value,
            self.spec.value_type,
        )


class ServiceEffect(BaseEffect):
    def __init__(
        self,
        platform,
        service: str,
        enabled_start_mode: str = "disabled",
        disabled_start_mode: str = "manual",
        stop_on_enable: bool = True,
        start_on_disable: bool = False,
    ) -> None:
        super().__init__(platform)
        self.service = service
        self.enabled_start_mode = enabled_start_mode
        self.disabled_start_mode = disabled_start_mode
        self.stop_on_enable = stop_on_enable
        self.start_on_disable = start_on_disable

    def capture_state(self) -> dict[str, Any]:
        return {"name": self.service, **self.platform.service_get(self.service)}

    def restore_state(self, state: dict[str, Any]) -> None:
        self.platform.service_set(state["name"], state["start_mode"])
        if state["running"]:
            self.platform.service_start(state["name"])
        else:
            self.platform.service_stop(state["name"])

    def is_enabled(self) -> bool | None:
        item = self.platform.service_get(self.service)
        return item["start_mode"] == self.enabled_start_mode

    def plan_commands(self, target_state: bool) -> list[str]:
        commands = []
        target_mode = self.enabled_start_mode if target_state else self.disabled_start_mode
        commands.append(f"service {self.service} start_mode -> {target_mode}")
        if target_state and self.stop_on_enable:
            commands.append(f"service {self.service} stop")
        if (not target_state) and self.start_on_disable:
            commands.append(f"service {self.service} start")
        return commands

    def apply_target(self, target_state: bool) -> None:
        target_mode = self.enabled_start_mode if target_state else self.disabled_start_mode
        self.platform.service_set(self.service, target_mode)
        if target_state and self.stop_on_enable:
            self.platform.service_stop(self.service)
        if (not target_state) and self.start_on_disable:
            self.platform.service_start(self.service)


class ScheduledTaskEffect(BaseEffect):
    def __init__(self, platform, task_name: str, enabled_when_on: bool = False) -> None:
        super().__init__(platform)
        self.task_name = task_name
        self.enabled_when_on = enabled_when_on

    def capture_state(self) -> dict[str, Any] | None:
        return self.platform.scheduled_task_get(self.task_name)

    def restore_state(self, state: dict[str, Any] | None) -> None:
        if state is None:
            return
        self.platform.scheduled_task_set(state["name"], state["enabled"])

    def is_enabled(self) -> bool | None:
        state = self.platform.scheduled_task_get(self.task_name)
        if state is None:
            return False
        return state["enabled"] is self.enabled_when_on

    def plan_commands(self, target_state: bool) -> list[str]:
        desired = self.enabled_when_on if target_state else (not self.enabled_when_on)
        action = "enable" if desired else "disable"
        return [f"scheduled task {self.task_name} -> {action}"]

    def apply_target(self, target_state: bool) -> None:
        desired = self.enabled_when_on if target_state else (not self.enabled_when_on)
        self.platform.scheduled_task_set(self.task_name, desired)


class InterfaceRegistryEffect(BaseEffect):
    def __init__(
        self,
        platform,
        value_name: str,
        enabled_value: Any,
        disabled_value: Any | None = None,
        delete_on_disable: bool = True,
    ) -> None:
        super().__init__(platform)
        self.value_name = value_name
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value
        self.delete_on_disable = delete_on_disable

    def capture_state(self) -> dict[str, Any]:
        return self.platform.get_interface_value(self.value_name)

    def restore_state(self, state: dict[str, Any]) -> None:
        self.platform.clear_interface_value(self.value_name)
        for value in state.values():
            if value is not None:
                self.platform.set_interface_value(self.value_name, value)

    def is_enabled(self) -> bool | None:
        state = self.capture_state()
        values = [value for value in state.values() if value is not None]
        return bool(values) and all(value == self.enabled_value for value in values)

    def plan_commands(self, target_state: bool) -> list[str]:
        if target_state:
            return [f"interface {self.value_name} -> {self.enabled_value!r}"]
        if self.delete_on_disable:
            return [f"interface {self.value_name} clear"]
        return [f"interface {self.value_name} -> {self.disabled_value!r}"]

    def apply_target(self, target_state: bool) -> None:
        if target_state:
            self.platform.set_interface_value(self.value_name, self.enabled_value)
            return
        if self.delete_on_disable:
            self.platform.clear_interface_value(self.value_name)
            return
        self.platform.set_interface_value(self.value_name, self.disabled_value)


class TcpGlobalEffect(BaseEffect):
    def __init__(self, platform, key: str, enabled_value: str, disabled_value: str) -> None:
        super().__init__(platform)
        self.key = key
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value

    def capture_state(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.platform.get_tcp_global(self.key)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state["value"] is not None:
            self.platform.set_tcp_global(state["key"], state["value"])

    def is_enabled(self) -> bool | None:
        return self.platform.get_tcp_global(self.key) == self.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        return [f"netsh tcp global {self.key}={value}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.set_tcp_global(self.key, self.enabled_value if target_state else self.disabled_value)


class PowerPlanEffect(BaseEffect):
    def __init__(self, platform, enabled_plan: str, disabled_plan: str = "Balanced") -> None:
        super().__init__(platform)
        self.enabled_plan = enabled_plan
        self.disabled_plan = disabled_plan

    def capture_state(self) -> dict[str, Any]:
        return self.platform.power_get_active_plan()

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("name"):
            self.platform.power_set_active_plan(state["name"])

    def is_enabled(self) -> bool | None:
        state = self.platform.power_get_active_plan()
        return state.get("name", "").lower() == self.enabled_plan.lower()

    def plan_commands(self, target_state: bool) -> list[str]:
        name = self.enabled_plan if target_state else self.disabled_plan
        return [f"power plan -> {name}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.power_set_active_plan(self.enabled_plan if target_state else self.disabled_plan)


class SystemParameterEffect(BaseEffect):
    def __init__(
        self,
        platform,
        name: str,
        enabled_value: Any,
        disabled_value: Any,
        broadcast_key: str | None = None,
    ) -> None:
        super().__init__(platform)
        self.name = name
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value
        self.broadcast_key = broadcast_key

    def capture_state(self) -> Any:
        return self.platform.system_parameter_get(self.name)

    def restore_state(self, state: Any) -> None:
        self.platform.system_parameter_set(self.name, state)
        if self.broadcast_key:
            self.platform.broadcast_setting_change(self.broadcast_key)

    def is_enabled(self) -> bool | None:
        return self.platform.system_parameter_get(self.name) == self.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        commands = [f"system parameter {self.name} -> {value!r}"]
        if self.broadcast_key:
            commands.append(f"broadcast {self.broadcast_key}")
        return commands

    def apply_target(self, target_state: bool) -> None:
        value = self.enabled_value if target_state else self.disabled_value
        self.platform.system_parameter_set(self.name, value)
        if self.broadcast_key:
            self.platform.broadcast_setting_change(self.broadcast_key)


class DisplayRefreshEffect(BaseEffect):
    def __init__(self, platform, disabled_refresh_rate: int = 60) -> None:
        super().__init__(platform)
        self.disabled_refresh_rate = disabled_refresh_rate

    def capture_state(self) -> dict[str, Any]:
        return {"refresh_rate": self.platform.display_get_current_refresh_rate()}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("refresh_rate"):
            self.platform.display_set_refresh_rate(int(state["refresh_rate"]))

    def is_enabled(self) -> bool | None:
        highest = self.platform.display_get_highest_refresh_rate()
        current = self.platform.display_get_current_refresh_rate()
        if highest is None or current is None:
            return None
        return current == highest

    def plan_commands(self, target_state: bool) -> list[str]:
        target = self.platform.display_get_highest_refresh_rate() if target_state else self.disabled_refresh_rate
        return [f"display refresh -> {target}Hz"]

    def apply_target(self, target_state: bool) -> None:
        target = self.platform.display_get_highest_refresh_rate() if target_state else self.disabled_refresh_rate
        if target is not None:
            self.platform.display_set_refresh_rate(target)


class NetAdapterFeatureEffect(BaseEffect):
    def __init__(self, platform, feature: str, enabled_value: bool, disabled_value: bool) -> None:
        super().__init__(platform)
        self.feature = feature
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value

    def capture_state(self) -> dict[str, Any]:
        return {"feature": self.feature, "value": self.platform.net_adapter_feature_get(self.feature)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state["value"] is not None:
            self.platform.net_adapter_feature_set(state["feature"], bool(state["value"]))

    def is_enabled(self) -> bool | None:
        value = self.platform.net_adapter_feature_get(self.feature)
        if value is None:
            return None
        return bool(value) == self.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        return [f"net adapter feature {self.feature} -> {value}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.net_adapter_feature_set(
            self.feature,
            self.enabled_value if target_state else self.disabled_value,
        )


class CommandEffect(BaseEffect):
    stateful = False

    def __init__(self, platform, command: list[str], description: str = "") -> None:
        super().__init__(platform)
        self.command = command
        self.description = description

    def capture_state(self) -> dict[str, Any]:
        return {"kind": "command"}

    def restore_state(self, state: Any) -> None:
        return

    def is_enabled(self) -> bool | None:
        return None

    def plan_commands(self, target_state: bool) -> list[str]:
        if not target_state:
            return []
        return [" ".join(self.command)]

    def apply_target(self, target_state: bool) -> None:
        if target_state:
            self.platform.run_command(self.command, description=self.description)


class ShellRefreshEffect(BaseEffect):
    stateful = False

    def __init__(self, platform, broadcast_key: str | None = None, refresh_explorer: bool = False) -> None:
        super().__init__(platform)
        self.broadcast_key = broadcast_key
        self.refresh_explorer_flag = refresh_explorer

    def capture_state(self) -> dict[str, Any]:
        return {"kind": "shell_refresh"}

    def restore_state(self, state: Any) -> None:
        return

    def is_enabled(self) -> bool | None:
        return None

    def plan_commands(self, target_state: bool) -> list[str]:
        if not target_state and not self.refresh_explorer_flag and not self.broadcast_key:
            return []
        commands: list[str] = []
        if self.broadcast_key:
            commands.append(f"broadcast {self.broadcast_key}")
        if self.refresh_explorer_flag:
            commands.append("refresh explorer")
        return commands

    def apply_target(self, target_state: bool) -> None:
        if self.broadcast_key:
            self.platform.broadcast_setting_change(self.broadcast_key)
        if self.refresh_explorer_flag:
            self.platform.refresh_explorer()


class NvidiaInspectorEffect(BaseEffect):
    def __init__(self, platform, on_args: list[str], off_args: list[str]) -> None:
        super().__init__(platform)
        self.on_args = on_args
        self.off_args = off_args

    def capture_state(self) -> dict[str, Any]:
        return {"dependency_present": bool(self.platform.machine_context().nvidia_inspector_path)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if self.off_args:
            self.platform.invoke_nvidia(self.off_args)

    def is_enabled(self) -> bool | None:
        return None

    def plan_commands(self, target_state: bool) -> list[str]:
        args = self.on_args if target_state else self.off_args
        return [f"nvidiaInspector.exe {' '.join(args)}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.invoke_nvidia(self.on_args if target_state else self.off_args)


class BaseAction(ABC):
    def __init__(self, platform, definition: ActionDefinition) -> None:
        self.platform = platform
        self.definition = definition

    def probe(self) -> ActionProbeResult:
        try:
            current_state = self.is_enabled()
            verification_status = (
                VerificationStatus.VERIFIED if current_state is not None else VerificationStatus.NOT_VERIFIED
            )
            return ActionProbeResult(
                action_id=self.definition.id,
                current_state=current_state,
                available=True,
                summary=self.definition.description,
                effective_value=current_state,
                verification_status=verification_status,
            )
        except Exception as exc:
            return ActionProbeResult(
                action_id=self.definition.id,
                current_state=None,
                available=False,
                summary=self.definition.description,
                reasons=[str(exc)],
            )

    def apply(self, target_state: bool, snapshot_writer) -> ActionResult:
        before_state = self.capture_state()
        self._apply_target(target_state)
        after_state = self.capture_state()
        entry = snapshot_writer.capture(
            action_id=self.definition.id,
            target_state=target_state,
            before_state=before_state,
            after_state=after_state,
            reversible=self.definition.kind == ActionKind.SETTING,
            notes=self.definition.rollback,
        )
        verification_status, effective_value, failure_reason = self.verify_target(target_state)
        return ActionResult(
            action_id=self.definition.id,
            success=failure_reason is None,
            message=self._build_result_message(verification_status, failure_reason),
            snapshot_entry=entry,
            requires_restart=self.definition.restart_requirement != RestartRequirement.NONE,
            verification_status=verification_status,
            effective_value=effective_value,
            failure_reason=failure_reason,
        )

    def rollback(self, snapshot_entry: SnapshotEntry) -> ActionResult:
        if not snapshot_entry.reversible:
            return ActionResult(
                action_id=self.definition.id,
                success=False,
                message=f"{self.definition.title} is not directly reversible.",
                snapshot_entry=snapshot_entry,
                verification_status=VerificationStatus.NOT_VERIFIED,
            )
        self.restore_state(snapshot_entry.before_state)
        return ActionResult(
            action_id=self.definition.id,
            success=True,
            message=f"{self.definition.title} rolled back.",
            snapshot_entry=snapshot_entry,
            verification_status=VerificationStatus.VERIFIED,
            effective_value=self.is_enabled(),
        )

    def verify_target(self, target_state: bool) -> tuple[VerificationStatus, Any | None, str | None]:
        if self.definition.kind == ActionKind.MAINTENANCE:
            return VerificationStatus.NOT_VERIFIED, None, None
        current_state = self.is_enabled()
        if current_state == target_state:
            return VerificationStatus.VERIFIED, current_state, None
        pending = {
            RestartRequirement.RESTART: VerificationStatus.PENDING_RESTART,
            RestartRequirement.LOGOFF: VerificationStatus.PENDING_LOGOFF,
            RestartRequirement.EXPLORER: VerificationStatus.PENDING_EXPLORER,
        }.get(self.definition.restart_requirement)
        if pending is not None:
            return pending, current_state, None
        return VerificationStatus.NOT_VERIFIED, current_state, "State probe did not match the requested target."

    def _build_result_message(
        self,
        verification_status: VerificationStatus,
        failure_reason: str | None,
    ) -> str:
        suffix = {
            VerificationStatus.VERIFIED: "Verified.",
            VerificationStatus.PENDING_RESTART: "Pending restart.",
            VerificationStatus.PENDING_LOGOFF: "Pending logoff.",
            VerificationStatus.PENDING_EXPLORER: "Pending Explorer refresh.",
            VerificationStatus.NOT_VERIFIED: "Not verified.",
        }[verification_status]
        if failure_reason:
            suffix = f"{suffix} {failure_reason}"
        return f"{self.definition.title} applied. {suffix}".strip()

    @abstractmethod
    def capture_state(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def restore_state(self, state: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self) -> bool | None:
        raise NotImplementedError

    @abstractmethod
    def plan(self, target_state: bool) -> DryRunDescription:
        raise NotImplementedError

    @abstractmethod
    def _apply_target(self, target_state: bool) -> None:
        raise NotImplementedError


class EffectAction(BaseAction):
    def __init__(self, platform, definition: ActionDefinition, effects: list[BaseEffect]) -> None:
        super().__init__(platform, definition)
        self.effects = effects

    def capture_state(self) -> list[Any]:
        return [effect.capture_state() for effect in self.effects]

    def restore_state(self, state: list[Any]) -> None:
        for effect, effect_state in zip(self.effects, state, strict=True):
            effect.restore_state(effect_state)

    def is_enabled(self) -> bool | None:
        if self.definition.kind == ActionKind.MAINTENANCE:
            return False
        states = [
            effect.is_enabled()
            for effect in self.effects
            if effect.stateful
        ]
        states = [state for state in states if state is not None]
        if not states:
            return None
        return all(states)

    def plan(self, target_state: bool) -> DryRunDescription:
        commands: list[str] = []
        for effect in self.effects:
            commands.extend(effect.plan_commands(target_state))
        return DryRunDescription(
            action_id=self.definition.id,
            target_state=target_state,
            summary=self.definition.title,
            commands=commands,
        )

    def _apply_target(self, target_state: bool) -> None:
        for effect in self.effects:
            effect.apply_target(target_state)


class RegistryPlanAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, specs: list[RegistryValueSpec]) -> None:
        super().__init__(platform, definition, [RegistryEffect(platform, spec) for spec in specs])


class ServicePlanAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        services: list[str],
        enabled_start_mode: str = "disabled",
        disabled_start_mode: str = "manual",
        stop_on_enable: bool = True,
        start_on_disable: bool = False,
    ) -> None:
        effects = [
            ServiceEffect(
                platform,
                service=service,
                enabled_start_mode=enabled_start_mode,
                disabled_start_mode=disabled_start_mode,
                stop_on_enable=stop_on_enable,
                start_on_disable=start_on_disable,
            )
            for service in services
        ]
        super().__init__(platform, definition, effects)


class ScheduledTaskPlanAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, tasks: list[str], enabled_when_on: bool = False) -> None:
        super().__init__(
            platform,
            definition,
            [ScheduledTaskEffect(platform, task, enabled_when_on=enabled_when_on) for task in tasks],
        )


class InterfaceRegistryAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        value_name: str,
        enabled_value: Any,
        disabled_value: Any | None = None,
        delete_on_disable: bool = True,
    ) -> None:
        super().__init__(
            platform,
            definition,
            [
                InterfaceRegistryEffect(
                    platform,
                    value_name=value_name,
                    enabled_value=enabled_value,
                    disabled_value=disabled_value,
                    delete_on_disable=delete_on_disable,
                )
            ],
        )


class CompositeInterfaceRegistryAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, specs: list[dict[str, Any]]) -> None:
        effects = [
            InterfaceRegistryEffect(
                platform,
                value_name=spec["value_name"],
                enabled_value=spec["enabled_value"],
                disabled_value=spec.get("disabled_value"),
                delete_on_disable=spec.get("delete_on_disable", True),
            )
            for spec in specs
        ]
        super().__init__(platform, definition, effects)


class TcpGlobalAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, key: str, enabled_value: str, disabled_value: str) -> None:
        super().__init__(platform, definition, [TcpGlobalEffect(platform, key, enabled_value, disabled_value)])


class CompositeTcpAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        enabled_values: dict[str, str],
        disabled_values: dict[str, str],
    ) -> None:
        effects = [
            TcpGlobalEffect(
                platform,
                key=key,
                enabled_value=enabled_values[key],
                disabled_value=disabled_values[key],
            )
            for key in enabled_values
        ]
        super().__init__(platform, definition, effects)


class PowerPlanAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, enabled_plan: str, disabled_plan: str = "Balanced") -> None:
        super().__init__(platform, definition, [PowerPlanEffect(platform, enabled_plan, disabled_plan)])


class SystemParameterPlanAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        name: str,
        enabled_value: Any,
        disabled_value: Any,
        broadcast_key: str | None = None,
        extra_effects: list[BaseEffect] | None = None,
    ) -> None:
        effects: list[BaseEffect] = [
            SystemParameterEffect(
                platform,
                name=name,
                enabled_value=enabled_value,
                disabled_value=disabled_value,
                broadcast_key=broadcast_key,
            )
        ]
        if extra_effects:
            effects.extend(extra_effects)
        super().__init__(platform, definition, effects)


class DisplayRefreshAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, disabled_refresh_rate: int = 60) -> None:
        super().__init__(platform, definition, [DisplayRefreshEffect(platform, disabled_refresh_rate)])


class NetAdapterFeatureAction(EffectAction):
    def __init__(self, platform, definition: ActionDefinition, feature: str, enabled_value: bool, disabled_value: bool) -> None:
        super().__init__(platform, definition, [NetAdapterFeatureEffect(platform, feature, enabled_value, disabled_value)])


class MaintenanceAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        commands: list[list[str]],
    ) -> None:
        effects = [CommandEffect(platform, command, description=definition.title) for command in commands]
        super().__init__(platform, definition, effects)


class NvidiaInspectorAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        on_args: list[str],
        off_args: list[str],
    ) -> None:
        super().__init__(platform, definition, [NvidiaInspectorEffect(platform, on_args, off_args)])
