from __future__ import annotations

from app.actions.base import PowerPlanAction, RegistryPlanAction, RegistryValueSpec
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


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
                rollback="Returns the active plan to the previous baseline or Balanced when disabled directly.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                public_group="Power",
            ),
            enabled_plan="High performance",
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
                    disabled_value=1,
                    delete_on_disable=False,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_game_mode",
                title="Disable Game Mode",
                module_id="performance",
                legacy_label="DisableGameMode",
                description="Turns off Windows Game Mode for users who prefer a fixed background profile instead.",
                what_it_changes="Sets AutoGameModeEnabled to zero in the current-user Game Bar settings.",
                why_it_may_help="Useful when Game Mode interferes with a manually tuned setup or benchmark flow.",
                downside="Some systems perform better with Game Mode left on.",
                rollback="Restores the previous Game Mode toggle from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Gaming",
            ),
            [
                RegistryValueSpec(
                    path=r"HKCU\Software\Microsoft\GameBar",
                    name="AutoGameModeEnabled",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    disabled_value=1,
                    delete_on_disable=False,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="optimize_cpu_priority",
                title="Optimize CPU Priority",
                module_id="performance",
                legacy_label="OptimizeCPUPriority",
                description="Biases Windows scheduling slightly toward foreground responsiveness.",
                what_it_changes="Sets Win32PrioritySeparation under PriorityControl.",
                why_it_may_help="Can improve responsiveness for active foreground workloads.",
                downside="May reduce fairness for background workloads.",
                rollback="Restores or removes the Win32PrioritySeparation override from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Scheduler",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl",
                    name="Win32PrioritySeparation",
                    value_type="REG_DWORD",
                    enabled_value=2,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="increase_system_responsiveness",
                title="Increase System Responsiveness",
                module_id="performance",
                legacy_label="IncreaseSystemResponsiveness",
                description="Tunes the Multimedia System Profile responsiveness percentage.",
                what_it_changes="Sets SystemResponsiveness under the Multimedia SystemProfile key.",
                why_it_may_help="Can reduce background multimedia reservation and favor foreground work.",
                downside="It is an advanced scheduler tweak with workload-dependent benefit.",
                rollback="Restores the previous SystemResponsiveness value from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Scheduler",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                    name="SystemResponsiveness",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    disabled_value=20,
                    delete_on_disable=False,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="reduce_input_delay",
                title="Reduce Input Delay",
                module_id="performance",
                legacy_label="ReduceInputDelay",
                description="Sets NetworkThrottlingIndex to its unthrottled value.",
                what_it_changes="Writes NetworkThrottlingIndex under the Multimedia SystemProfile key.",
                why_it_may_help="Can reduce background multimedia throttling on some gaming workloads.",
                downside="This is an experimental latency tweak with mixed real-world benefit.",
                rollback="Restores the previous NetworkThrottlingIndex value from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.EXPERIMENTAL,
                public_group="Latency",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                    name="NetworkThrottlingIndex",
                    value_type="REG_DWORD",
                    enabled_value=0xFFFFFFFF,
                    disabled_value=10,
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
                description="Removes NTFS last-access updates on the local machine.",
                what_it_changes="Sets NtfsDisableLastAccessUpdate in the file-system policy key.",
                why_it_may_help="Reduces metadata writes on busy disks.",
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
                    disabled_value=0,
                    delete_on_disable=False,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="optimize_usb_selective_suspend",
                title="Optimize USB Selective Suspend",
                module_id="performance",
                legacy_label="OptimizeUSBSelectiveSuspend",
                description="Applies the old USB soft-remove tweak for devices that dislike power-state transitions.",
                what_it_changes="Sets DisableOnSoftRemove under the USB hub parameters key.",
                why_it_may_help="Can reduce reconnect delays on devices that dislike suspend transitions.",
                downside="May slightly increase idle power usage on some systems.",
                rollback="Restores the previous USB hub parameter value from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Devices",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SYSTEM\CurrentControlSet\Services\usbhub\Parameters",
                    name="DisableOnSoftRemove",
                    value_type="REG_DWORD",
                    enabled_value=1,
                    disabled_value=0,
                    delete_on_disable=False,
                )
            ],
        ),
    ]
