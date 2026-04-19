from __future__ import annotations

from app.domain.models import ActionDefinition, CompatibilityDecision, MachineContext


class CompatibilityService:
    def evaluate(
        self, machine_context: MachineContext, action_or_preset: ActionDefinition
    ) -> CompatibilityDecision:
        reasons: list[str] = []
        warnings: list[str] = []

        if action_or_preset.requires_dependency and not machine_context.nvidia_inspector_path:
            reasons.append(
                f"{action_or_preset.requires_dependency} was not detected, so this control is unavailable."
            )

        if action_or_preset.id == "disable_bluetooth" and machine_context.bluetooth_devices > 0:
            reasons.append(
                "Bluetooth hardware is currently active on this machine, so Tweakify is leaving it alone."
            )

        if action_or_preset.min_build and machine_context.windows_build < action_or_preset.min_build:
            reasons.append(
                f"This action needs Windows build {action_or_preset.min_build} or newer."
            )

        if action_or_preset.max_build and machine_context.windows_build > action_or_preset.max_build:
            reasons.append(
                f"This action is only intended for Windows builds up to {action_or_preset.max_build}."
            )

        if action_or_preset.scope.value == "machine" and not machine_context.is_admin:
            warnings.append("Machine-scope apply will trigger the elevated helper.")

        if machine_context.oem_vendor and action_or_preset.id == "optimize_usb_selective_suspend":
            warnings.append(
                f"{machine_context.oem_vendor} hardware may rely on vendor power management, so test this change before keeping it."
            )

        if action_or_preset.id == "disable_cortana" and machine_context.windows_build >= 22000:
            warnings.append(
                "Modern Windows builds already reduced classic Cortana integration, so impact may be limited."
            )

        if action_or_preset.id == "disable_uac":
            warnings.append(
                "This is an Advanced security tradeoff and requires a full reboot."
            )

        if action_or_preset.id == "disable_ipv6":
            warnings.append(
                "Only use this when actively troubleshooting a network stack issue or following a known requirement."
            )

        return CompatibilityDecision(allowed=not reasons, reasons=reasons, warnings=warnings)
