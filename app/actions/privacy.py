from __future__ import annotations

from app.actions.base import EffectAction, RegistryEffect, RegistryPlanAction, ShellRefreshEffect
from app.actions.helpers import definition, policy, setting
from app.domain.models import RestartRequirement, SafetyTier, Scope


CDM = r"HKCU\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
EXPLORER_ADVANCED = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"


def _privacy(id: str, title: str, group: str, description: str, changes: str, why: str, downside: str, **kwargs):
    return definition(id, title, "privacy", group, description, changes, why, downside, **kwargs)


def build_actions(platform) -> list:
    return [
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_advertising_id",
                "Disable Advertising ID",
                "Ads & Suggestions",
                "Stops apps from using your per-user advertising ID for personalised ads.",
                "Sets AdvertisingInfo\\Enabled to 0 for the current user.",
                "Apps can no longer correlate your activity across apps for ad targeting.",
                "Ads in apps become generic rather than personalised.",
                scope=Scope.USER,
            ),
            [setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0, 1)],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_tailored_experiences",
                "Disable Tailored Experiences",
                "Ads & Suggestions",
                "Stops Microsoft from using diagnostic data to personalise tips, ads, and recommendations.",
                "Sets TailoredExperiencesWithDiagnosticDataEnabled to 0 for the current user.",
                "Fewer nudges and promotions based on how you use Windows.",
                "None in normal use.",
                scope=Scope.USER,
            ),
            [setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled", 0, 1)],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_start_menu_suggestions",
                "Disable Start and Settings Suggestions",
                "Ads & Suggestions",
                "Removes suggested apps, promoted content, and silent app installs from Start and Settings.",
                "Turns off the ContentDeliveryManager suggestion and silent-install switches.",
                "Stops Windows from installing sponsored apps and filling Start with promotions.",
                "None. Microsoft Store still works normally.",
                scope=Scope.USER,
                restart=RestartRequirement.EXPLORER,
            ),
            [
                setting(CDM, "SystemPaneSuggestionsEnabled", 0, 1),
                setting(CDM, "SubscribedContent-338388Enabled", 0, 1),
                setting(CDM, "SubscribedContent-338389Enabled", 0, 1),
                setting(CDM, "SubscribedContent-338393Enabled", 0, 1),
                setting(CDM, "SubscribedContent-353694Enabled", 0, 1),
                setting(CDM, "SubscribedContent-353696Enabled", 0, 1),
                setting(CDM, "SilentInstalledAppsEnabled", 0, 1),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_lock_screen_tips",
                "Disable Lock Screen Tips and Ads",
                "Ads & Suggestions",
                "Removes the 'fun facts, tips, and more' overlay from the lock screen.",
                "Turns off RotatingLockScreenOverlayEnabled and SubscribedContent-338387Enabled.",
                "A clean lock screen without promoted content.",
                "None.",
                scope=Scope.USER,
            ),
            [
                setting(CDM, "RotatingLockScreenOverlayEnabled", 0, 1),
                setting(CDM, "SubscribedContent-338387Enabled", 0, 1),
            ],
        ),
        EffectAction(
            platform,
            _privacy(
                "disable_web_search_in_start",
                "Disable Bing Web Results in Start",
                "Search",
                "Keeps Start menu search local instead of sending every keystroke to Bing.",
                "Sets the DisableSearchBoxSuggestions policy for the current user.",
                "Faster, private local search. Typing in Start no longer goes to the web.",
                "Web results and Bing answers no longer appear in Start search.",
                scope=Scope.USER,
                restart=RestartRequirement.EXPLORER,
            ),
            [
                RegistryEffect(platform, policy(r"HKCU\Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", 1)),
                ShellRefreshEffect(platform, broadcast_key="Policy"),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_activity_history",
                "Disable Activity History",
                "Tracking",
                "Stops Windows from recording and uploading a timeline of the apps and files you use.",
                "Sets the EnableActivityFeed, PublishUserActivities, and UploadUserActivities policies to 0.",
                "Less usage data stored locally and synced to your Microsoft account.",
                "Cross-device 'pick up where you left off' features stop working.",
                restart=RestartRequirement.LOGOFF,
            ),
            [
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", 0),
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", 0),
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\System", "UploadUserActivities", 0),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_app_launch_tracking",
                "Disable App Launch Tracking",
                "Tracking",
                "Stops Windows from tracking which apps you launch to rank Start and search.",
                "Sets Start_TrackProgs to 0 under Explorer\\Advanced.",
                "Less local usage tracking.",
                "The 'Most used' list in Start stops updating.",
                scope=Scope.USER,
                restart=RestartRequirement.EXPLORER,
            ),
            [setting(EXPLORER_ADVANCED, "Start_TrackProgs", 0, 1)],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_feedback_requests",
                "Disable Feedback Requests",
                "Tracking",
                "Stops Windows from asking for feedback and rating prompts.",
                "Sets the Siuf NumberOfSIUFInPeriod rule to 0 and the DoNotShowFeedbackNotifications policy.",
                "No more 'How likely are you to recommend Windows' pop-ups.",
                "None.",
            ),
            [
                policy(r"HKCU\Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", 0),
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection", "DoNotShowFeedbackNotifications", 1),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_input_personalization",
                "Disable Inking and Typing Personalization",
                "Tracking",
                "Stops Windows from collecting what you type and write to build a personal dictionary.",
                "Restricts implicit ink and text collection and turns off contact harvesting.",
                "Typing and handwriting samples stay off Microsoft's servers.",
                "Handwriting recognition and text suggestions learn less from you.",
                scope=Scope.USER,
            ),
            [
                setting(r"HKCU\Software\Microsoft\InputPersonalization", "RestrictImplicitInkCollection", 1, 0),
                setting(r"HKCU\Software\Microsoft\InputPersonalization", "RestrictImplicitTextCollection", 1, 0),
                setting(r"HKCU\Software\Microsoft\InputPersonalization\TrainedDataStore", "HarvestContacts", 0, 1),
                setting(r"HKCU\Software\Microsoft\Personalization\Settings", "AcceptedPrivacyPolicy", 0, 1),
            ],
        ),
        EffectAction(
            platform,
            _privacy(
                "disable_copilot",
                "Disable Windows Copilot",
                "AI Features",
                "Turns off Windows Copilot and hides its taskbar button.",
                "Sets the TurnOffWindowsCopilot policy and ShowCopilotButton=0.",
                "Removes an always-on AI entry point and its background integration.",
                "Copilot is unavailable until this is turned back off. The standalone Copilot app can still be installed.",
                restart=RestartRequirement.EXPLORER,
                min_build=22000,
            ),
            [
                RegistryEffect(platform, policy(r"HKCU\Software\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1)),
                RegistryEffect(platform, policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", 1)),
                RegistryEffect(platform, setting(EXPLORER_ADVANCED, "ShowCopilotButton", 0, 1)),
                ShellRefreshEffect(platform, refresh_explorer=True),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_recall",
                "Disable Recall Snapshots",
                "AI Features",
                "Blocks Recall from being enabled and stops AI analysis of screen snapshots.",
                "Sets the AllowRecallEnablement=0 and DisableAIDataAnalysis=1 policies.",
                "No periodic screenshots of your activity are captured or indexed.",
                "Recall cannot be turned on in Settings while this policy is in place.",
                restart=RestartRequirement.RESTART,
                min_build=26100,
            ),
            [
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "AllowRecallEnablement", 0),
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 1),
                policy(r"HKCU\Software\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 1),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_office_telemetry",
                "Disable Microsoft Office Telemetry",
                "Tracking",
                "Turns off Office client telemetry for the current user.",
                "Sets the Office ClientTelemetry DisableTelemetry=1 and SendTelemetry=3 policies.",
                "Office stops sending optional usage and diagnostic data.",
                "None for normal Office use.",
                scope=Scope.USER,
            ),
            [
                policy(r"HKCU\Software\Policies\Microsoft\Office\Common\ClientTelemetry", "DisableTelemetry", 1),
                policy(r"HKCU\Software\Policies\Microsoft\Office\Common\ClientTelemetry", "SendTelemetry", 3),
            ],
        ),
        RegistryPlanAction(
            platform,
            _privacy(
                "disable_location_services",
                "Disable Location Access",
                "Tracking",
                "Denies location access to every app system-wide.",
                "Sets the location ConsentStore value to Deny.",
                "No app can read your position.",
                "Maps, weather, Find My Device, and automatic time zone stop working.",
                tier=SafetyTier.ADVANCED,
            ),
            [
                setting(
                    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location",
                    "Value",
                    "Deny",
                    "Allow",
                    "REG_SZ",
                )
            ],
        ),
    ]
