from __future__ import annotations

from app.domain.models import ActionDefinition, CompatibilityDecision, MachineContext


LAPTOP_SENSITIVE_ACTIONS = {
    "high_performance_power_plan": "On battery this plan shortens runtime noticeably.",
    "ultimate_performance_power_plan": "Ultimate Performance is meant for desktops; on battery it drains fast.",
    "disable_usb_selective_suspend": "Keeping USB devices awake costs battery life on laptops.",
    "disable_pcie_link_power_management": "PCIe link power savings matter most on laptops.",
    "disable_cpu_core_parking": "Unparking every core raises idle power draw on laptops.",
    "disable_power_throttling": "Power throttling is what keeps background apps from draining the battery.",
    "disable_hibernation": "Hibernate is the laptop fallback when the battery runs flat.",
}


class CompatibilityService:
    def evaluate(
        self, machine_context: MachineContext, action_or_preset: ActionDefinition
    ) -> CompatibilityDecision:
        reasons: list[str] = []
        warnings: list[str] = []

        dependency = action_or_preset.requires_dependency
        if dependency:
            available = {
                "nvidiaInspector.exe": machine_context.nvidia_inspector_path,
                "nvidiaProfileInspector.exe": machine_context.nvidia_profile_inspector_path,
            }.get(dependency)
            if not available:
                reasons.append(f"{dependency} was not detected, so this control is unavailable.")

        vendor = action_or_preset.requires_gpu_vendor
        if vendor and machine_context.gpu_vendors and vendor not in machine_context.gpu_vendors:
            reasons.append(f"No {vendor} graphics card was detected on this machine.")

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

        if machine_context.is_laptop and action_or_preset.id in LAPTOP_SENSITIVE_ACTIONS:
            warnings.append("Laptop detected. " + LAPTOP_SENSITIVE_ACTIONS[action_or_preset.id])

        known_vendor = machine_context.oem_vendor and machine_context.oem_vendor.lower() not in {"unknown", "generic"}
        if known_vendor and action_or_preset.id == "disable_usb_selective_suspend":
            warnings.append(
                f"{machine_context.oem_vendor} hardware may rely on vendor power management, so test this change before keeping it."
            )

        if action_or_preset.id == "disable_cortana" and machine_context.windows_build >= 22000:
            warnings.append(
                "Modern Windows builds already reduced classic Cortana integration, so impact may be limited."
            )

        if action_or_preset.id == "disable_uac":
            warnings.append(
                "This is an Advanced security tradeoff and requires a full reboot. Microsoft Store apps stop launching while UAC is off."
            )

        if action_or_preset.id == "disable_ipv6":
            warnings.append(
                "Only use this when actively troubleshooting a network stack issue or following a known requirement."
            )

        if action_or_preset.id in {"disable_smartscreen", "disable_memory_integrity_warning"}:
            warnings.append("This lowers malware protection. Keep it on unless you have a specific reason.")

        return CompatibilityDecision(allowed=not reasons, reasons=reasons, warnings=warnings)
