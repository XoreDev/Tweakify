from __future__ import annotations

from app.actions.base import DisplayRefreshAction, NvidiaProfileAction, RegistryPlanAction, RegistryValueSpec
from app.actions.helpers import definition, policy, setting
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


# Driver setting IDs and values from NVIDIA's NvApiDriverSettings.h.
PREFERRED_PSTATE = 0x1057EB71
PREFERRED_PSTATE_PREFER_MAX = 0x00000001
PREFERRED_PSTATE_OPTIMAL_POWER = 0x00000005  # driver default
VSYNCMODE = 0x00A879CF
VSYNCMODE_FORCEOFF = 0x08416747
VSYNCMODE_PASSIVE = 0x60925292  # "Use the 3D application setting", driver default
REFRESH_RATE_OVERRIDE = 0x0064B541
REFRESH_RATE_OVERRIDE_HIGHEST_AVAILABLE = 0x00000001
REFRESH_RATE_OVERRIDE_APPLICATION_CONTROLLED = 0x00000000  # driver default
PRERENDERLIMIT = 0x007BA09E  # "Low Latency Mode" in the NVIDIA Control Panel
PRERENDERLIMIT_ONE_FRAME = 0x00000001
PRERENDERLIMIT_APP_CONTROLLED = 0x00000000  # driver default
QUALITY_ENHANCEMENTS = 0x00CE2691  # Texture filtering - Quality
QUALITY_ENHANCEMENTS_HIGHPERFORMANCE = 0x00000014
QUALITY_ENHANCEMENTS_QUALITY = 0x00000000  # driver default

NVIDIA_ROLLBACK = "Imports the driver default value for this setting back into the global profile."


def _nvidia(id: str, title: str, description: str, changes: str, why: str, downside: str) -> ActionDefinition:
    return definition(
        id,
        title,
        "graphics",
        "NVIDIA",
        description,
        changes,
        why,
        downside,
        rollback=NVIDIA_ROLLBACK,
        tier=SafetyTier.ADVANCED,
        requires_dependency="nvidiaProfileInspector.exe",
        requires_gpu_vendor="NVIDIA",
    )


def build_actions(platform) -> list:
    return [
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_game_dvr",
                title="Disable Game DVR",
                module_id="graphics",
                legacy_label="DisableGameDVR",
                description="Turns off the Game DVR capture stack and related policy values.",
                what_it_changes="Turns off Game DVR policy, capture, and related GameConfigStore values.",
                why_it_may_help="Background capture can cost frame time on lower-end GPUs.",
                downside="Xbox Game Bar clip capture stops working.",
                rollback="Restores the previous Game DVR values from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.SAFE,
                public_group="Windows Graphics",
            ),
            [
                policy(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 0),
                setting(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 0, 1),
                setting(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, 1),
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_hardware_gpu_scheduling",
                title="Disable Hardware GPU Scheduling",
                module_id="graphics",
                legacy_label="DisableHardwareGPUScheduling",
                description="Turns off hardware-accelerated GPU scheduling for troubleshooting.",
                what_it_changes="Sets HwSchMode to 1 (off) under GraphicsDrivers.",
                why_it_may_help="Can fix stutter or capture issues on some driver and game combinations.",
                downside="DLSS Frame Generation requires hardware scheduling to stay on.",
                rollback="Restores the previous HwSchMode value from the snapshot.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Windows Graphics",
                min_build=19041,
            ),
            [
                # 1 = off, 2 = on. 0 is not a documented value.
                RegistryValueSpec(
                    r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                    "HwSchMode",
                    "REG_DWORD",
                    1,
                    disabled_value=2,
                    delete_on_disable=False,
                )
            ],
        ),
        DisplayRefreshAction(
            platform,
            ActionDefinition(
                id="set_highest_refresh_rate",
                title="Set Highest Refresh Rate",
                module_id="graphics",
                legacy_label="SetHighestRefreshRate",
                description="Switches the primary display to the highest refresh rate it supports at the current resolution.",
                what_it_changes="Changes and saves the primary display mode refresh rate.",
                why_it_may_help="Many 120-240Hz monitors ship running at 60Hz until someone changes it.",
                downside="Higher refresh rates use slightly more GPU power.",
                rollback="Restores the previous refresh rate from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                public_group="Windows Graphics",
            ),
            disabled_refresh_rate=60,
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_multiplane_overlay",
                title="Disable Multiplane Overlay",
                module_id="graphics",
                legacy_label="DisableMultiplaneOverlay",
                description="Sets the DWM overlay test mode used in MPO troubleshooting.",
                what_it_changes="Writes OverlayTestMode=5 under the DWM machine key.",
                why_it_may_help="Fixes flicker and black-screen issues some multi-monitor setups have with MPO.",
                downside="Can raise GPU usage slightly while videos play.",
                rollback="Removes OverlayTestMode again.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Windows Graphics",
            ),
            [
                RegistryValueSpec(
                    path=r"HKLM\SOFTWARE\Microsoft\Windows\Dwm",
                    name="OverlayTestMode",
                    value_type="REG_DWORD",
                    enabled_value=5,
                    delete_on_disable=True,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "disable_fullscreen_optimizations",
                "Disable Fullscreen Optimizations",
                "graphics",
                "Windows Graphics",
                "Turns off fullscreen optimizations so exclusive-fullscreen games really run exclusive.",
                "Sets the GameConfigStore fullscreen-exclusive behaviour flags for the current user.",
                "Some older DirectX 9-11 games have lower input latency in true exclusive fullscreen.",
                "Alt-Tab out of fullscreen games is slower, and overlays may not appear.",
                scope=Scope.USER,
                restart=RestartRequirement.LOGOFF,
                tier=SafetyTier.ADVANCED,
            ),
            [
                setting(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2, 0),
                setting(r"HKCU\System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 1, 0),
                setting(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehavior", 2, 0),
                setting(r"HKCU\System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 1, 0),
            ],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "enable_windowed_game_optimizations",
                "Optimizations for Windowed Games",
                "graphics",
                "Windows Graphics",
                "Turns on the Windows 11 flip-model presentation upgrade for DirectX 10/11 windowed games.",
                "Adds SwapEffectUpgradeEnable=1 to the DirectX user GPU preferences.",
                "Gives borderless-windowed games lower latency and enables Auto HDR / VRR there.",
                "A few old games render incorrectly with the upgraded swap chain.",
                scope=Scope.USER,
                restart=RestartRequirement.NONE,
                tier=SafetyTier.SAFE,
                min_build=22000,
            ),
            [
                RegistryValueSpec(
                    r"HKCU\Software\Microsoft\DirectX\UserGpuPreferences",
                    "DirectXUserGlobalSettings",
                    "REG_SZ",
                    "SwapEffectUpgradeEnable=1;",
                    delete_on_disable=True,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "enable_variable_refresh_rate",
                "Variable Refresh Rate for Games",
                "graphics",
                "Windows Graphics",
                "Lets games that do not support VRR themselves still use G-Sync / FreeSync.",
                "Adds VRROptimizeEnable=1 to the DirectX user GPU preferences.",
                "Smoother frame pacing without tearing on VRR displays.",
                "No effect on displays without VRR support.",
                scope=Scope.USER,
                restart=RestartRequirement.NONE,
                tier=SafetyTier.ADVANCED,
                min_build=19041,
                conflicts_with=("enable_windowed_game_optimizations",),
            ),
            [
                RegistryValueSpec(
                    r"HKCU\Software\Microsoft\DirectX\UserGpuPreferences",
                    "DirectXUserGlobalSettings",
                    "REG_SZ",
                    "SwapEffectUpgradeEnable=1;VRROptimizeEnable=1;",
                    delete_on_disable=True,
                )
            ],
        ),
        NvidiaProfileAction(
            platform,
            _nvidia(
                "nvidia_set_max_refresh_rate",
                "NVIDIA Preferred Refresh Rate: Highest",
                "Makes the driver use the highest available refresh rate in every game.",
                "Sets Preferred refresh rate (0x0064B541) to Highest available in the global driver profile.",
                "Stops games from silently dropping a high-refresh monitor to 60Hz.",
                "Games that need a specific refresh rate can no longer pick it themselves.",
            ),
            on_settings={REFRESH_RATE_OVERRIDE: REFRESH_RATE_OVERRIDE_HIGHEST_AVAILABLE},
            off_settings={REFRESH_RATE_OVERRIDE: REFRESH_RATE_OVERRIDE_APPLICATION_CONTROLLED},
        ),
        NvidiaProfileAction(
            platform,
            _nvidia(
                "nvidia_prefer_maximum_performance",
                "NVIDIA Power: Prefer Maximum Performance",
                "Keeps the GPU at full clocks while a 3D app runs instead of downclocking between frames.",
                "Sets Power management mode (0x1057EB71) to Prefer maximum performance globally.",
                "Removes clock ramp-up stutter in games with uneven load.",
                "Higher idle power, heat, and fan noise while any 3D app is open.",
            ),
            on_settings={PREFERRED_PSTATE: PREFERRED_PSTATE_PREFER_MAX},
            off_settings={PREFERRED_PSTATE: PREFERRED_PSTATE_OPTIMAL_POWER},
        ),
        NvidiaProfileAction(
            platform,
            _nvidia(
                "nvidia_vertical_sync_off",
                "NVIDIA Vertical Sync: Force Off",
                "Forces V-Sync off in the driver regardless of the in-game setting.",
                "Sets Vertical sync (0x00A879CF) to Force off globally.",
                "Lowest input latency on fixed-refresh displays.",
                "Screen tearing returns. On G-Sync displays prefer an FPS cap instead.",
            ),
            on_settings={VSYNCMODE: VSYNCMODE_FORCEOFF},
            off_settings={VSYNCMODE: VSYNCMODE_PASSIVE},
        ),
        NvidiaProfileAction(
            platform,
            _nvidia(
                "nvidia_low_latency_mode",
                "NVIDIA Low Latency Mode: On",
                "Limits the CPU to queueing one frame ahead of the GPU.",
                "Sets Maximum pre-rendered frames (0x007BA09E) to 1 globally.",
                "Lowers input latency when the game is GPU-bound.",
                "Can lower average FPS slightly in CPU-bound games. Reflex in-game is better where offered.",
            ),
            on_settings={PRERENDERLIMIT: PRERENDERLIMIT_ONE_FRAME},
            off_settings={PRERENDERLIMIT: PRERENDERLIMIT_APP_CONTROLLED},
        ),
        NvidiaProfileAction(
            platform,
            _nvidia(
                "nvidia_texture_filtering_performance",
                "NVIDIA Texture Filtering: High Performance",
                "Trades a little texture sharpness for frame rate in the driver's filtering path.",
                "Sets Texture filtering - Quality (0x00CE2691) to High performance globally.",
                "A small FPS gain on older or entry-level GPUs.",
                "Textures at oblique angles look slightly blurrier.",
            ),
            on_settings={QUALITY_ENHANCEMENTS: QUALITY_ENHANCEMENTS_HIGHPERFORMANCE},
            off_settings={QUALITY_ENHANCEMENTS: QUALITY_ENHANCEMENTS_QUALITY},
        ),
    ]
