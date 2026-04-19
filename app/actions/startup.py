from __future__ import annotations

from app.actions.base import RegistryPlanAction, RegistryValueSpec, ScheduledTaskPlanAction
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


def build_actions(platform) -> list:
    return [
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_startup_delay",
                title="Disable Startup Delay",
                module_id="startup",
                legacy_label="DisableStartupDelay",
                description="Removes the Explorer startup app delay so login items do not stagger unnecessarily.",
                what_it_changes="Sets StartupDelayInMSec to zero under the Explorer Serialize key.",
                why_it_may_help="Makes the desktop feel ready faster after sign-in on systems with a few trusted startup apps.",
                downside="Several startup apps may hit the system at once right after login.",
                rollback="Restores the previous startup delay behavior from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Windows Startup",
            ),
            [
                RegistryValueSpec(
                    path=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize",
                    name="StartupDelayInMSec",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    delete_on_disable=True,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_browser_background_mode",
                title="Disable Browser Background Mode",
                module_id="startup",
                legacy_label="DisableBrowserBackgroundMode",
                description="Turns off Chrome and Edge background mode so they stop keeping extra processes alive after close.",
                what_it_changes="Writes background-mode policy keys for Chrome and Microsoft Edge.",
                why_it_may_help="Cuts idle RAM and background wakeups on gaming or battery-focused systems.",
                downside="Background notifications or sync helpers can become less immediate.",
                rollback="Restores the previous browser background-mode policy state from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Browsers",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Policies\Google\Chrome",
                    name="BackgroundModeEnabled",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    disabled_value=1,
                    delete_on_disable=False,
                ),
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Policies\Microsoft\Edge",
                    name="BackgroundModeEnabled",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    disabled_value=1,
                    delete_on_disable=False,
                ),
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_edge_startup_boost",
                title="Disable Edge Startup Boost",
                module_id="startup",
                legacy_label="DisableEdgeStartupBoost",
                description="Turns off Edge Startup Boost so Edge stops prelaunching background helpers at login.",
                what_it_changes="Writes the Edge StartupBoostEnabled policy key.",
                why_it_may_help="Reduces background startup noise on systems that do not want browser preloading.",
                downside="Edge can take a little longer to cold-start.",
                rollback="Restores the previous Edge Startup Boost policy state from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Browsers",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Policies\Microsoft\Edge",
                    name="StartupBoostEnabled",
                    value_type="REG_DWORD",
                    enabled_value=0,
                    disabled_value=1,
                    delete_on_disable=False,
                )
            ],
        ),
        ScheduledTaskPlanAction(
            platform,
            ActionDefinition(
                id="disable_telemetry_tasks",
                title="Disable Telemetry Tasks",
                module_id="startup",
                legacy_label="DisableTelemetryTasks",
                description="Disables a small set of Windows telemetry-oriented scheduled tasks surfaced in the old optimizer ideas.",
                what_it_changes="Disables Application Experience telemetry tasks when they exist.",
                why_it_may_help="Cuts routine background task wakeups tied to compatibility and telemetry collection.",
                downside="Some Microsoft compatibility data collection tasks will stop running.",
                rollback="Re-enables the scheduled tasks captured in the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                public_group="Scheduled Tasks",
            ),
            tasks=[
                r"\Microsoft\Windows\Application Experience\Microsoft Compatibility Appraiser",
                r"\Microsoft\Windows\Application Experience\ProgramDataUpdater",
            ],
            enabled_when_on=False,
        ),
        ScheduledTaskPlanAction(
            platform,
            ActionDefinition(
                id="disable_ceip_tasks",
                title="Disable CEIP Tasks",
                module_id="startup",
                legacy_label="DisableCEIPTasks",
                description="Disables Customer Experience Improvement Program scheduled tasks when they are present.",
                what_it_changes="Turns off the Consolidator and UsbCeip tasks in the Windows CEIP task folder.",
                why_it_may_help="Reduces periodic telemetry-style scheduled task activity.",
                downside="Some opt-in customer-experience telemetry stops running.",
                rollback="Re-enables the CEIP tasks from the captured snapshot state.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                public_group="Scheduled Tasks",
            ),
            tasks=[
                r"\Microsoft\Windows\Customer Experience Improvement Program\Consolidator",
                r"\Microsoft\Windows\Customer Experience Improvement Program\UsbCeip",
            ],
            enabled_when_on=False,
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_onedrive_startup",
                title="Disable OneDrive Startup",
                module_id="startup",
                legacy_label="DisableOneDriveStartup",
                description="Removes the OneDrive Run entry so it stops auto-starting with Windows.",
                what_it_changes="Deletes the OneDrive value from the current-user Run key.",
                why_it_may_help="Cuts sign-in background work when OneDrive sync is not needed immediately.",
                downside="OneDrive will not start automatically until you re-enable it or launch it manually.",
                rollback="Restores the previous OneDrive Run entry from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="App Launchers",
            ),
            [
                RegistryValueSpec(
                    path=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                    name="OneDrive",
                    value_type="REG_SZ",
                    enabled_value=None,
                    disabled_value=r"%LOCALAPPDATA%\Microsoft\OneDrive\OneDrive.exe /background",
                    delete_on_enable=True,
                    delete_on_disable=False,
                )
            ],
        ),
    ]
