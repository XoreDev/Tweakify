from __future__ import annotations

from app.actions.base import EffectAction, RegistryPlanAction, RegistryValueSpec, ServiceEffect, ServicePlanAction
from app.actions.helpers import definition, policy, setting
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


SERVICE_ROLLBACK = "Restores the previous service start mode and running state from the snapshot."


def _service(id: str, title: str, group: str, description: str, changes: str, why: str, downside: str, **kwargs):
    kwargs.setdefault("rollback", SERVICE_ROLLBACK)
    return definition(id, title, "services", group, description, changes, why, downside, **kwargs)


def build_actions(platform) -> list:
    return [
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_telemetry",
                title="Disable Telemetry",
                module_id="privacy",
                legacy_label="DisableTelemetry",
                description="Lowers the Windows diagnostic data policy to its minimum.",
                what_it_changes="Writes the AllowTelemetry=0 policy under DataCollection.",
                why_it_may_help="Sends as little diagnostic data as the edition allows. Home and Pro treat 0 as Required (1).",
                downside="Some Insider and troubleshooting features need optional diagnostic data.",
                rollback="Removes the policy again so Settings controls diagnostic data.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.SAFE,
                public_group="Tracking",
            ),
            [policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0)],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_background_apps",
                title="Disable Background Apps",
                module_id="services",
                legacy_label="DisableBackgroundApps",
                description="Restricts Store apps from running in the background for the current user.",
                what_it_changes="Sets GlobalUserDisabled and turns off ContentDeliveryAllowed for the current user.",
                why_it_may_help="Fewer background processes, less memory and battery use.",
                downside="Store apps such as Mail and Calendar stop syncing and notifying in the background.",
                rollback="Restores the previous background access and content-delivery settings from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Background",
            ),
            [
                setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", 1, 0),
                setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "ContentDeliveryAllowed", 0, 1),
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_cortana",
                title="Disable Cortana Web Search",
                module_id="privacy",
                legacy_label="DisableCortana",
                description="Reduces web-backed search behavior and the older Cortana policy surface.",
                what_it_changes="Sets the AllowCortana policy to 0 and turns off BingSearchEnabled and AllowSearchToUseLocation.",
                why_it_may_help="Search stays local and does not use your location.",
                downside="Web answers in search disappear.",
                rollback="Removes the policy and restores the previous search settings from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Search",
            ),
            [
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCortana", 0),
                setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Search", "BingSearchEnabled", 0, 1),
                setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Search", "AllowSearchToUseLocation", 0, 1),
            ],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_xbox_services",
                "Disable Xbox Services",
                "Gaming",
                "Disables the core Xbox background services used by sign-in and cloud saves.",
                "Sets XblAuthManager, XblGameSave, and XboxNetApiSvc to Disabled and stops them.",
                "Removes background services on PCs that never use Xbox or Game Pass.",
                "Game Pass games, Xbox sign-in, and cloud saves stop working.",
                tier=SafetyTier.ADVANCED,
                legacy_label="DisableXboxServices",
            ),
            services=["XblAuthManager", "XblGameSave", "XboxNetApiSvc"],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_bluetooth",
                "Disable Bluetooth",
                "Hardware",
                "Disables the Bluetooth Support Service on systems that do not need Bluetooth.",
                "Sets the Bluetooth support service to Disabled and stops it.",
                "One less background service on desktops without Bluetooth.",
                "Bluetooth devices stop connecting.",
                tier=SafetyTier.ADVANCED,
                legacy_label="DisableBluetooth",
            ),
            services=["bthserv"],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_notifications",
                title="Disable Notifications",
                module_id="services",
                legacy_label="DisableNotifications",
                description="Turns off toast notifications for the current user.",
                what_it_changes="Sets ToastEnabled to zero in PushNotifications settings.",
                why_it_may_help="Stops pop-ups from interrupting games and focused work.",
                downside="You miss notifications from every app until it is turned back on.",
                rollback="Restores the previous toast-notification setting from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Notifications",
            ),
            [setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled", 0, 1)],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_diagnostic_tracking",
                "Disable Diagnostic Tracking",
                "Background",
                "Disables the Connected User Experiences and Telemetry (DiagTrack) service.",
                "Sets DiagTrack and dmwappushservice to Disabled and stops them.",
                "Stops the main telemetry upload service and its WAP push helper.",
                "Some Windows Insider and diagnostics features stop working.",
                tier=SafetyTier.ADVANCED,
                legacy_label="DisableDiagnosticTracking",
            ),
            services=["DiagTrack", "dmwappushservice"],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_smartscreen",
                title="Disable SmartScreen",
                module_id="services",
                legacy_label="DisableSmartScreen",
                description="Turns off Windows SmartScreen for downloaded apps and files.",
                what_it_changes="Sets the EnableSmartScreen policy to 0 under Windows\\System.",
                why_it_may_help="Removes the 'Windows protected your PC' prompt for trusted unsigned tools.",
                downside="You lose a layer of protection against malicious downloads.",
                rollback="Removes the policy again so Windows Security controls SmartScreen.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Security",
            ),
            [policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System", "EnableSmartScreen", 0)],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_uac",
                title="Disable UAC",
                module_id="services",
                legacy_label="DisableUAC",
                description="Turns off the main UAC EnableLUA switch.",
                what_it_changes="Sets EnableLUA to zero under the Windows system policy key.",
                why_it_may_help="Removes elevation prompts on single-user lab or test machines.",
                downside="Every program runs as administrator, and Microsoft Store apps refuse to launch.",
                rollback="Restores the previous EnableLUA state from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.EXPERIMENTAL,
                public_group="Security",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
                    name="EnableLUA",
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
                id="disable_error_reporting",
                title="Disable Error Reporting",
                module_id="services",
                legacy_label="DisableErrorReporting",
                description="Turns off Windows Error Reporting uploads.",
                what_it_changes="Sets Disabled to one under the Windows Error Reporting key.",
                why_it_may_help="No crash data is collected or uploaded after app failures.",
                downside="Microsoft and app vendors get no crash reports to fix problems you hit.",
                rollback="Restores the previous Windows Error Reporting state from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Background",
            ),
            [setting(r"HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 1, 0)],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_sysmain",
                "Disable SysMain (Superfetch)",
                "Background",
                "Disables the SysMain service that preloads frequently used apps into RAM.",
                "Sets SysMain to Disabled and stops it.",
                "Cuts background disk activity on HDD systems and frees RAM on low-memory PCs.",
                "On SSD systems with enough RAM, app launches can get slightly slower.",
                tier=SafetyTier.ADVANCED,
            ),
            services=["SysMain"],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_windows_search_service",
                "Disable Windows Search Indexing",
                "Background",
                "Disables the Windows Search indexer service.",
                "Sets WSearch to Disabled and stops it.",
                "Removes indexer disk and CPU activity on low-end machines.",
                "Start, Explorer, and Outlook search become much slower and less complete.",
                tier=SafetyTier.ADVANCED,
            ),
            services=["WSearch"],
        ),
        ServicePlanAction(
            platform,
            _service(
                "disable_print_spooler",
                "Disable Print Spooler",
                "Hardware",
                "Disables the Print Spooler on PCs that never print.",
                "Sets Spooler to Disabled and stops it.",
                "One less service, and it closes the PrintNightmare-style attack surface.",
                "Printing, Print to PDF, and some scan apps stop working.",
                tier=SafetyTier.ADVANCED,
            ),
            services=["Spooler"],
        ),
        EffectAction(
            platform,
            _service(
                "set_rarely_used_services_manual",
                "Set Rarely Used Services to Manual",
                "Background",
                "Moves auto-start services most home PCs rarely need to manual start, so they only run on demand.",
                "Sets MapsBroker, TrkWks, PcaSvc, and the Edge/Google updater services to Manual. Nothing is disabled.",
                "Fewer services start at boot while still starting automatically if something needs them.",
                "Practically none: Manual services still start when requested. Updaters run when their app opens.",
                tier=SafetyTier.SAFE,
            ),
            [
                ServiceEffect(platform, name, enabled_start_mode="manual", disabled_start_mode=default, stop_on_enable=False)
                for name, default in (
                    ("MapsBroker", "delayed-auto"),
                    ("TrkWks", "auto"),
                    ("PcaSvc", "auto"),
                    ("edgeupdate", "delayed-auto"),
                    ("gupdate", "delayed-auto"),
                )
            ],
        ),
    ]
