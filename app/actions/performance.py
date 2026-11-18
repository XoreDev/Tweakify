from __future__ import annotations

from app.actions.base import (
    EffectAction,
    HibernationEffect,
    MemoryAgentEffect,
    PowerPlanAction,
    PowerSettingEffect,
    RegistryPlanAction,
    RegistryValueSpec,
)
from app.actions.helpers import definition, setting
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


SUB_USB = "2a737441-1930-4402-8d77-b2bebba308a3"
USB_SELECTIVE_SUSPEND = "48e6b7a6-50f5-4782-a5d4-53bb8f07e226"
SUB_PCIEXPRESS = "501a4d13-42af-4429-9fd1-a8218c268e20"
PCIE_ASPM = "ee12f906-d277-404b-b6da-e5fa1a576df5"


def build_actions(platform) -> list:
    return [
        PowerPlanAction(
            platform,
            ActionDefinition(
                id="high_performance_power_plan",
                title="High Performance Power Plan",
                module_id="performance",
                legacy_label="TweakifyPowerPlan",
                description="Switches Windows to the High performance power plan.",
                what_it_changes="Sets the active power plan to High performance and restores Balanced when turned off.",
                why_it_may_help="Helps desktops and plugged-in gaming systems favor performance over power savings.",
                downside="Can increase power draw, heat, and fan noise.",
                rollback="Returns the active plan to the previous plan (by GUID) from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                public_group="Power",
                conflicts_with=("ultimate_performance_power_plan",),
            ),
            enabled_plan="High performance",
            disabled_plan="Balanced",
        ),
        PowerPlanAction(
            platform,
            definition(
                "ultimate_performance_power_plan",
                "Ultimate Performance Power Plan",
                "performance",
                "Power",
                "Unlocks and activates the hidden Ultimate Performance plan.",
                "Duplicates the Ultimate Performance scheme if it is missing, then makes it active.",
                "Removes the last micro power-saving delays. Meant for desktop workstations and gaming rigs.",
                "Highest idle power draw of any plan. Not for laptops on battery.",
                rollback="Returns the active plan to the previous plan (by GUID) from the snapshot.",
                tier=SafetyTier.ADVANCED,
                conflicts_with=("high_performance_power_plan",),
            ),
            enabled_plan="Ultimate Performance",
            disabled_plan="Balanced",
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="adjust_visual_effects",
                title="Adjust Visual Effects",
                module_id="performance",
                legacy_label="AdjustVisualEffects",
                description="Applies the classic best-performance Explorer visual-effects preference.",
                what_it_changes="Sets VisualFXSetting to favor performance.",
                why_it_may_help="Cuts animation overhead and makes the shell feel snappier.",
                downside="Windows visuals become plainer.",
                rollback="Restores the previous VisualFXSetting value from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.EXPLORER,
                safety_tier=SafetyTier.SAFE,
                public_group="Shell & Power",
            ),
            [
                RegistryValueSpec(
                    path=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
                    name="VisualFXSetting",
                    value_type="REG_DWORD",
                    enabled_value=2,
                    disabled_value=0,
                    delete_on_disable=False,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_last_access_timestamp",
                title="Disable Last Access Timestamp",
                module_id="performance",
                legacy_label="DisableLastAccessTimestamp",
                description="Stops NTFS from writing a last-access time on every file read.",
                what_it_changes="Sets NtfsDisableLastAccessUpdate to 1 (user-managed, disabled).",
                why_it_may_help="Reduces metadata writes on busy disks, especially HDDs.",
                downside="Tools that rely on last-access timestamps lose fidelity.",
                rollback="Restores the prior NtfsDisableLastAccessUpdate state from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="File System",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem",
                    name="NtfsDisableLastAccessUpdate",
                    value_type="REG_DWORD",
                    enabled_value=1,
                    # 0x80000002 is the system-managed value fresh Windows 10/11 installs ship with.
                    # The old code wrote 0 here, which forced last-access updates *on*.
                    disabled_value=0x80000002,
                    delete_on_disable=False,
                )
            ],
        ),
        EffectAction(
            platform,
            definition(
                "disable_usb_selective_suspend",
                "Disable USB Selective Suspend",
                "performance",
                "Devices",
                "Stops Windows from powering down idle USB devices on the active power plan.",
                "Sets the USB selective suspend power setting to Disabled for AC and battery.",
                "Fixes mice, headsets, and DACs that drop out or lag after being idle.",
                "Slightly higher idle power draw, mostly noticeable on laptops.",
                tier=SafetyTier.ADVANCED,
                legacy_label="OptimizeUSBSelectiveSuspend",
            ),
            [PowerSettingEffect(platform, SUB_USB, USB_SELECTIVE_SUSPEND, 0, 1, "USB selective suspend")],
        ),
        EffectAction(
            platform,
            definition(
                "disable_pcie_link_power_management",
                "Disable PCIe Link State Power Management",
                "performance",
                "Devices",
                "Keeps PCI Express links at full power instead of dropping into ASPM low-power states.",
                "Sets Link State Power Management to Off on the active power plan.",
                "Avoids wake-up latency on GPUs and NVMe drives coming out of low-power link states.",
                "Higher idle power draw.",
                tier=SafetyTier.ADVANCED,
            ),
            [PowerSettingEffect(platform, SUB_PCIEXPRESS, PCIE_ASPM, 0, 1, "PCIe link state power management")],
        ),
        EffectAction(
            platform,
            definition(
                "disable_hibernation",
                "Disable Hibernation",
                "performance",
                "Shell & Power",
                "Turns hibernation off and deletes hiberfil.sys.",
                "Runs powercfg /hibernate off.",
                "Frees disk space equal to a large share of installed RAM.",
                "Fast Startup and Hibernate stop working. Laptops lose their low-battery safety net.",
                rollback="Runs powercfg /hibernate on when the snapshot had it enabled.",
                tier=SafetyTier.ADVANCED,
            ),
            [HibernationEffect(platform)],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "disable_fast_startup",
                "Disable Fast Startup",
                "performance",
                "Shell & Power",
                "Makes Shut down a real shutdown instead of a partial hibernate.",
                "Sets HiberbootEnabled to 0 under Session Manager\\Power.",
                "Drivers and the kernel start fresh every boot, which fixes many 'only after shutdown' bugs.",
                "Cold boots take a few seconds longer.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.SAFE,
            ),
            [setting(r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power", "HiberbootEnabled", 0, 1)],
        ),
        EffectAction(
            platform,
            definition(
                "disable_memory_compression",
                "Disable Memory Compression",
                "performance",
                "Memory",
                "Turns off the Memory Manager's in-RAM page compression.",
                "Runs Disable-MMAgent -MemoryCompression.",
                "On systems with plenty of RAM (16 GB+), avoids CPU time spent compressing pages.",
                "On 8 GB or less it makes paging to disk more likely, which is much slower.",
                rollback="Runs Enable-MMAgent -MemoryCompression when the snapshot had it on.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.ADVANCED,
            ),
            [MemoryAgentEffect(platform, "MemoryCompression", enabled_value=False)],
        ),
    ]
