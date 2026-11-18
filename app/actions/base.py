from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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


TWEAKIFY_STATE_KEY = r"HKCU\Software\Tweakify\State"


@dataclass(slots=True)
class RegistryValueSpec:
    path: str
    name: str
    value_type: str
    enabled_value: Any
    disabled_value: Any | None = None
    delete_on_disable: bool = True
    delete_on_enable: bool = False


@dataclass(slots=True)
class CommandSpec:
    """A one-shot command plus the exit codes that count as success."""

    command: list[str]
    ok_codes: tuple[int, ...] = (0,)
    timeout: int | None = 1800
    description: str = ""


class ActionFailure(RuntimeError):
    """Raised by an effect when the platform reports that a change did not happen."""


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

    def _read(self) -> tuple[Any, str | None]:
        reader = getattr(self.platform, "registry_get_typed", None)
        if reader is not None:
            return reader(self.spec.path, self.spec.name)
        value = self.platform.registry_get(self.spec.path, self.spec.name)
        return value, (self.spec.value_type if value is not None else None)

    def capture_state(self) -> dict[str, Any]:
        value, value_type = self._read()
        return {
            "path": self.spec.path,
            "name": self.spec.name,
            "value": value,
            # Keep the type that was really there (REG_EXPAND_SZ, REG_QWORD, ...),
            # not the type this tweak writes, so a rollback is byte-for-byte.
            "value_type": value_type or self.spec.value_type,
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
        if isinstance(self.spec.enabled_value, str) and current is not None:
            return str(current) == self.spec.enabled_value
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

    def _installed(self, item: dict[str, Any]) -> bool:
        return item.get("start_mode") not in {"missing", "unknown"}

    def capture_state(self) -> dict[str, Any]:
        return {"name": self.service, **self.platform.service_get(self.service)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("start_mode") in {"missing", "unknown", None}:
            return
        self.platform.service_set(state["name"], state["start_mode"])
        if state["running"]:
            self.platform.service_start(state["name"])
        else:
            self.platform.service_stop(state["name"])

    def is_enabled(self) -> bool | None:
        item = self.platform.service_get(self.service)
        if not self._installed(item):
            return None
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
        if not self._installed(self.platform.service_get(self.service)):
            return
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
            # The task is not on this build. It neither counts for nor against the action.
            return None
        return state["enabled"] is self.enabled_when_on

    def plan_commands(self, target_state: bool) -> list[str]:
        desired = self.enabled_when_on if target_state else (not self.enabled_when_on)
        action = "enable" if desired else "disable"
        return [f"scheduled task {self.task_name} -> {action}"]

    def apply_target(self, target_state: bool) -> None:
        if self.platform.scheduled_task_get(self.task_name) is None:
            return
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
        # Restore each interface to its own previous value. Writing one value to
        # every adapter would flatten per-adapter settings into whichever came last.
        current = self.platform.get_interface_value(self.value_name)
        for adapter in set(current) | set(state):
            previous = state.get(adapter)
            if previous is None:
                self.platform.clear_interface_value_for(adapter, self.value_name)
            else:
                self.platform.set_interface_value_for(adapter, self.value_name, previous)

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
        value = self.platform.get_tcp_global(self.key)
        if value is None:
            return None
        return value == self.enabled_value

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
        # Prefer the GUID: plan names are localized ("Équilibré", "Ausbalanciert", ...).
        token = state.get("guid") or state.get("name")
        if token:
            self.platform.power_set_active_plan(token)

    def is_enabled(self) -> bool | None:
        state = self.platform.power_get_active_plan()
        matcher = getattr(self.platform, "power_plan_matches", None)
        if matcher is not None:
            return bool(matcher(state, self.enabled_plan))
        return state.get("name", "").lower() == self.enabled_plan.lower()

    def plan_commands(self, target_state: bool) -> list[str]:
        name = self.enabled_plan if target_state else self.disabled_plan
        return [f"power plan -> {name}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.power_set_active_plan(self.enabled_plan if target_state else self.disabled_plan)


class PowerSettingEffect(BaseEffect):
    """One powercfg setting on the active scheme, for both AC and battery."""

    def __init__(
        self,
        platform,
        subgroup: str,
        setting: str,
        enabled_value: int,
        disabled_value: int,
        label: str,
        ac_only: bool = False,
    ) -> None:
        super().__init__(platform)
        self.subgroup = subgroup
        self.setting = setting
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value
        self.label = label
        self.ac_only = ac_only

    def capture_state(self) -> dict[str, Any]:
        return {"subgroup": self.subgroup, "setting": self.setting, **self.platform.power_setting_get(self.subgroup, self.setting)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("ac") is None and state.get("dc") is None:
            return
        self.platform.power_setting_set(self.subgroup, self.setting, state.get("ac"), state.get("dc"))

    def is_enabled(self) -> bool | None:
        state = self.platform.power_setting_get(self.subgroup, self.setting)
        if state.get("ac") is None:
            return None
        if self.ac_only:
            return state["ac"] == self.enabled_value
        return state["ac"] == self.enabled_value and state.get("dc") in {None, self.enabled_value}

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        scope = "AC" if self.ac_only else "AC+DC"
        return [f"powercfg {self.label} ({scope}) -> {value}"]

    def apply_target(self, target_state: bool) -> None:
        value = self.enabled_value if target_state else self.disabled_value
        self.platform.power_setting_set(self.subgroup, self.setting, value, None if self.ac_only else value)


class HibernationEffect(BaseEffect):
    """Hibernation on/off. Turning it off deletes hiberfil.sys and Fast Startup with it."""

    def capture_state(self) -> dict[str, Any]:
        return {"hibernate_enabled": self.platform.hibernation_enabled()}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("hibernate_enabled") is None:
            return
        self.platform.hibernation_set(bool(state["hibernate_enabled"]))

    def is_enabled(self) -> bool | None:
        enabled = self.platform.hibernation_enabled()
        return None if enabled is None else not enabled

    def plan_commands(self, target_state: bool) -> list[str]:
        return ["powercfg /hibernate off" if target_state else "powercfg /hibernate on"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.hibernation_set(not target_state)


class MemoryAgentEffect(BaseEffect):
    """Windows Memory Manager agent features such as memory compression."""

    def __init__(self, platform, feature: str, enabled_value: bool) -> None:
        super().__init__(platform)
        self.feature = feature
        self.enabled_value = enabled_value

    def capture_state(self) -> dict[str, Any]:
        return {"feature": self.feature, "value": self.platform.mmagent_get(self.feature)}

    def restore_state(self, state: dict[str, Any]) -> None:
        if state.get("value") is not None:
            self.platform.mmagent_set(self.feature, bool(state["value"]))

    def is_enabled(self) -> bool | None:
        value = self.platform.mmagent_get(self.feature)
        return None if value is None else value == self.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else not self.enabled_value
        verb = "Enable" if value else "Disable"
        return [f"{verb}-MMAgent -{self.feature}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.mmagent_set(self.feature, self.enabled_value if target_state else not self.enabled_value)


class DnsServerEffect(BaseEffect):
    """Point every connected adapter at one DNS provider, and put each one back afterwards."""

    def __init__(self, platform, servers: list[str], provider: str) -> None:
        super().__init__(platform)
        self.servers = list(servers)
        self.provider = provider

    def capture_state(self) -> dict[str, Any]:
        return {"adapters": self.platform.dns_get_servers()}

    def restore_state(self, state: dict[str, Any]) -> None:
        for alias, servers in (state.get("adapters") or {}).items():
            # An empty list means the adapter used DHCP-assigned DNS before.
            self.platform.dns_set_servers(alias, list(servers) or None)

    def is_enabled(self) -> bool | None:
        adapters = self.platform.dns_get_servers()
        if not adapters:
            return None
        return all(list(servers)[: len(self.servers)] == self.servers for servers in adapters.values())

    def plan_commands(self, target_state: bool) -> list[str]:
        if target_state:
            return [f"dns servers -> {', '.join(self.servers)} ({self.provider})"]
        return ["dns servers -> automatic (DHCP)"]

    def apply_target(self, target_state: bool) -> None:
        for alias in self.platform.dns_get_servers():
            self.platform.dns_set_servers(alias, self.servers if target_state else None)


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
        if state is None:
            return
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

    def __init__(self, platform, command: list[str] | CommandSpec, description: str = "") -> None:
        super().__init__(platform)
        self.spec = command if isinstance(command, CommandSpec) else CommandSpec(list(command), description=description)
        if not self.spec.description:
            self.spec.description = description
        self.last_return_code: int | None = None

    @property
    def command(self) -> list[str]:
        return self.spec.command

    def capture_state(self) -> dict[str, Any]:
        return {"kind": "command"}

    def restore_state(self, state: Any) -> None:
        return

    def is_enabled(self) -> bool | None:
        return None

    def plan_commands(self, target_state: bool) -> list[str]:
        if not target_state:
            return []
        return [" ".join(self.spec.command)]

    def apply_target(self, target_state: bool) -> None:
        if not target_state:
            return
        code = self.platform.run_command(
            self.spec.command,
            description=self.spec.description,
            timeout=self.spec.timeout,
        )
        self.last_return_code = code
        if code is not None and code not in self.spec.ok_codes:
            raise ActionFailure(f"`{self.spec.command[0]}` exited with code {code}.")


class ShellRefreshEffect(BaseEffect):
    stateful = False

    def __init__(self, platform, broadcast_key: str | None = None, refresh_explorer: bool = False) -> None:
        super().__init__(platform)
        self.broadcast_key = broadcast_key
        self.refresh_explorer_flag = refresh_explorer

    def capture_state(self) -> dict[str, Any]:
        return {"kind": "shell_refresh"}

    def restore_state(self, state: Any) -> None:
        self.apply_target(True)

    def is_enabled(self) -> bool | None:
        return None

    def plan_commands(self, target_state: bool) -> list[str]:
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


class NvidiaProfileEffect(BaseEffect):
    """Driver profile settings written through NVIDIA Profile Inspector.

    The driver database cannot be read back cheaply, so Tweakify keeps its own
    marker of what it applied and restores the driver default values on rollback.
    Setting IDs and values come from NVIDIA's NvApiDriverSettings.h.
    """

    def __init__(self, platform, marker: str, on_settings: dict[int, int], off_settings: dict[int, int]) -> None:
        super().__init__(platform)
        self.marker = marker
        self.on_settings = dict(on_settings)
        self.off_settings = dict(off_settings)

    def capture_state(self) -> dict[str, Any]:
        return {"applied": self.platform.registry_get(TWEAKIFY_STATE_KEY, self.marker) == 1}

    def restore_state(self, state: dict[str, Any]) -> None:
        self.apply_target(bool(state.get("applied")))

    def is_enabled(self) -> bool | None:
        return self.platform.registry_get(TWEAKIFY_STATE_KEY, self.marker) == 1

    def plan_commands(self, target_state: bool) -> list[str]:
        settings = self.on_settings if target_state else self.off_settings
        rendered = ", ".join(f"0x{key:08X}=0x{value:08X}" for key, value in settings.items())
        return [f"nvidiaProfileInspector import Base Profile [{rendered}]"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.nvidia_profile_apply(self.on_settings if target_state else self.off_settings)
        if target_state:
            self.platform.registry_set(TWEAKIFY_STATE_KEY, self.marker, 1, "REG_DWORD")
        else:
            self.platform.registry_delete(TWEAKIFY_STATE_KEY, self.marker)


class NetAdapterAdvancedPropertyEffect(BaseEffect):
    """A standardized NDIS keyword (for example *EEE) on every physical adapter that has it.

    Standard keywords start with '*' and are the same on every driver and language,
    unlike the display names Device Manager shows.
    """

    def __init__(self, platform, keyword: str, enabled_value: str, disabled_value: str) -> None:
        super().__init__(platform)
        self.keyword = keyword
        self.enabled_value = str(enabled_value)
        self.disabled_value = str(disabled_value)

    def capture_state(self) -> dict[str, Any]:
        return {"keyword": self.keyword, "adapters": self.platform.net_adapter_property_get(self.keyword)}

    def restore_state(self, state: dict[str, Any]) -> None:
        for adapter, value in (state.get("adapters") or {}).items():
            if value is not None:
                self.platform.net_adapter_property_set(adapter, self.keyword, str(value))

    def is_enabled(self) -> bool | None:
        values = [value for value in self.platform.net_adapter_property_get(self.keyword).values() if value is not None]
        if not values:
            return None
        return all(str(value) == self.enabled_value for value in values)

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        return [f"net adapter property {self.keyword} -> {value} (adapters restart briefly)"]

    def apply_target(self, target_state: bool) -> None:
        value = self.enabled_value if target_state else self.disabled_value
        for adapter, current in self.platform.net_adapter_property_get(self.keyword).items():
            if current is not None and str(current) != value:
                self.platform.net_adapter_property_set(adapter, self.keyword, value)


class BcdValueEffect(BaseEffect):
    """One boot configuration value on the current boot entry. `None` means "not set"."""

    def __init__(self, platform, name: str, enabled_value: str | None, disabled_value: str | None) -> None:
        super().__init__(platform)
        self.name = name
        self.enabled_value = enabled_value
        self.disabled_value = disabled_value

    def capture_state(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.platform.bcd_get(self.name)}

    def restore_state(self, state: dict[str, Any]) -> None:
        self.platform.bcd_set(self.name, state.get("value"))

    def is_enabled(self) -> bool | None:
        # bcd_get raises when the store cannot be read (it needs admin); probe() reports that.
        return self.platform.bcd_get(self.name) == self.enabled_value

    def plan_commands(self, target_state: bool) -> list[str]:
        value = self.enabled_value if target_state else self.disabled_value
        if value is None:
            return [f"bcdedit /deletevalue {self.name}"]
        return [f"bcdedit /set {self.name} {value}"]

    def apply_target(self, target_state: bool) -> None:
        self.platform.bcd_set(self.name, self.enabled_value if target_state else self.disabled_value)


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
        reversible = self.definition.kind == ActionKind.SETTING
        try:
            before_state = self.capture_state()
        except Exception as exc:
            return ActionResult(
                action_id=self.definition.id,
                success=False,
                message=f"{self.definition.title} was skipped: its current state could not be read ({exc}).",
                failure_reason=str(exc),
            )

        try:
            self._apply_target(target_state)
        except Exception as exc:
            # Put back whatever the half-finished apply already changed, and still
            # record the snapshot so the user can retry the rollback later.
            rollback_note = ""
            if reversible:
                try:
                    self.restore_state(before_state)
                    rollback_note = " Partial changes were reverted."
                except Exception as restore_exc:  # pragma: no cover - double fault path
                    rollback_note = f" Reverting partial changes also failed: {restore_exc}."
            entry = snapshot_writer.capture(
                action_id=self.definition.id,
                target_state=target_state,
                before_state=before_state,
                after_state=self._safe_capture(),
                reversible=reversible,
                notes=self.definition.rollback,
            )
            return ActionResult(
                action_id=self.definition.id,
                success=False,
                message=f"{self.definition.title} failed: {exc}.{rollback_note}",
                snapshot_entry=entry,
                failure_reason=str(exc),
            )

        after_state = self._safe_capture()
        entry = snapshot_writer.capture(
            action_id=self.definition.id,
            target_state=target_state,
            before_state=before_state,
            after_state=after_state,
            reversible=reversible,
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

    def _safe_capture(self) -> Any:
        try:
            return self.capture_state()
        except Exception:
            return None

    def rollback(self, snapshot_entry: SnapshotEntry) -> ActionResult:
        if not snapshot_entry.reversible:
            return ActionResult(
                action_id=self.definition.id,
                success=False,
                message=f"{self.definition.title} is not directly reversible.",
                snapshot_entry=snapshot_entry,
                verification_status=VerificationStatus.NOT_VERIFIED,
            )
        try:
            self.restore_state(snapshot_entry.before_state)
        except Exception as exc:
            return ActionResult(
                action_id=self.definition.id,
                success=False,
                message=f"{self.definition.title} rollback failed: {exc}",
                snapshot_entry=snapshot_entry,
                failure_reason=str(exc),
            )
        try:
            effective = self.is_enabled()
        except Exception:
            effective = None
        status = VerificationStatus.VERIFIED if effective is not None else VerificationStatus.NOT_VERIFIED
        return ActionResult(
            action_id=self.definition.id,
            success=True,
            message=f"{self.definition.title} rolled back.",
            snapshot_entry=snapshot_entry,
            verification_status=status,
            effective_value=effective,
        )

    def verify_target(self, target_state: bool) -> tuple[VerificationStatus, Any | None, str | None]:
        if self.definition.kind == ActionKind.MAINTENANCE:
            return VerificationStatus.NOT_VERIFIED, None, None
        current_state = self.is_enabled()
        if current_state == target_state:
            return VerificationStatus.VERIFIED, current_state, None
        if current_state is None:
            # Nothing on this machine could be probed (missing task, service, or adapter).
            return VerificationStatus.NOT_VERIFIED, None, None
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
        if self.definition.kind == ActionKind.MAINTENANCE and failure_reason is None:
            suffix = "Completed."
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
        # Undo in reverse order so effects that build on each other unwind cleanly.
        pairs = list(zip(self.effects, state, strict=True))
        errors: list[str] = []
        for effect, effect_state in reversed(pairs):
            try:
                effect.restore_state(effect_state)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise ActionFailure("; ".join(errors))

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
        commands: list[list[str] | CommandSpec],
    ) -> None:
        effects = [CommandEffect(platform, command, description=definition.title) for command in commands]
        super().__init__(platform, definition, effects)


class NvidiaProfileAction(EffectAction):
    def __init__(
        self,
        platform,
        definition: ActionDefinition,
        on_settings: dict[int, int],
        off_settings: dict[int, int],
    ) -> None:
        super().__init__(
            platform,
            definition,
            [NvidiaProfileEffect(platform, definition.id, on_settings, off_settings)],
        )
