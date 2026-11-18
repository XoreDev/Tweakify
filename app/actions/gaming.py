from __future__ import annotations

from app.actions.base import BcdValueEffect, EffectAction, PowerSettingEffect, RegistryPlanAction, RegistryValueSpec
from app.actions.helpers import definition, policy, setting
from app.domain.models import ActionDefinition, RestartRequirement, SafetyTier, Scope


MULTIMEDIA = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
GAMES_TASK = MULTIMEDIA + r"\Tasks\Games"
SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
CPMINCORES = "0cc5b647-c1df-4637-891a-dec35c318583"
PROCTHROTTLEMIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"
PERFBOOSTMODE = "be337238-0d82-4146-a960-4f3749d470c7"
IDLEDISABLE = "5d76a2ca-e8c0-402f-a133-2158492d58ad"


def build_actions(platform) -> list:
    return [
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="disable_game_mode",
                title="Disable Game Mode",
                module_id="gaming",
                legacy_label="DisableGameMode",
                description="Turns off Windows Game Mode for users who prefer a fixed background profile instead.",
                what_it_changes="Sets AutoGameModeEnabled to zero in the current-user Game Bar settings.",
                why_it_may_help="Useful when Game Mode interferes with a manually tuned setup or benchmark flow.",
                downside="Most systems perform better with Game Mode left on.",
                rollback="Restores the previous Game Mode toggle from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Game Mode",
            ),
            [setting(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 0, 1)],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="optimize_cpu_priority",
                title="Favor Foreground Apps (Priority Separation)",
                module_id="gaming",
                legacy_label="OptimizeCPUPriority",
                description="Gives the focused window longer, variable CPU time slices.",
                what_it_changes="Sets Win32PrioritySeparation to 0x26 (short, variable quanta, 3x foreground boost).",
                why_it_may_help="Games and other foreground apps get scheduled ahead of background work more often.",
                downside="Background encodes or compiles run a little slower while you game.",
                rollback="Restores the previous Win32PrioritySeparation value (Windows default is 2).",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Scheduler",
            ),
            [
                # The old value, 2, *is* the Windows client default, so this tweak did nothing.
                setting(r"HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 0x26, 2),
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="increase_system_responsiveness",
                title="Lower Multimedia CPU Reservation",
                module_id="gaming",
                legacy_label="IncreaseSystemResponsiveness",
                description="Reduces the CPU share MMCSS reserves for low-priority background tasks.",
                what_it_changes="Sets SystemResponsiveness to 10 (the minimum Windows honours) under Multimedia\\SystemProfile.",
                why_it_may_help="Leaves more CPU time for games and audio running at multimedia priority.",
                downside="Workload-dependent benefit. Background tasks get less guaranteed CPU.",
                rollback="Restores the previous SystemResponsiveness value (Windows default is 20).",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.ADVANCED,
                public_group="Scheduler",
            ),
            [
                # Windows treats anything below 10 as 10, so 0 only looked more aggressive.
                setting(MULTIMEDIA, "SystemResponsiveness", 10, 20),
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="reduce_input_delay",
                title="Disable Network Throttling",
                module_id="gaming",
                legacy_label="ReduceInputDelay",
                description="Stops MMCSS from throttling network packet processing while media plays.",
                what_it_changes="Sets NetworkThrottlingIndex to 0xFFFFFFFF under Multimedia\\SystemProfile.",
                why_it_may_help="Can steady network throughput in games while music or video plays in the background.",
                downside="Experimental with mixed real-world results. It does not change mouse or keyboard input delay.",
                rollback="Restores the previous NetworkThrottlingIndex value (Windows default is 10).",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.RESTART,
                safety_tier=SafetyTier.EXPERIMENTAL,
                public_group="Scheduler",
            ),
            [setting(MULTIMEDIA, "NetworkThrottlingIndex", 0xFFFFFFFF, 10)],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "prioritize_games_mmcss",
                "Prioritize Games in MMCSS",
                "gaming",
                "Scheduler",
                "Raises the CPU and I/O priority Windows gives to processes registered as games.",
                "Sets the MMCSS Games task to Priority 6, Scheduling Category High, SFIO Priority High.",
                "Games that register with MMCSS get scheduled ahead of normal desktop work.",
                "Only affects games that use MMCSS. Little effect on others.",
                rollback="Restores the previous Games task values from the snapshot.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.ADVANCED,
            ),
            [
                setting(GAMES_TASK, "Priority", 6, 2),
                setting(GAMES_TASK, "Scheduling Category", "High", "Medium", "REG_SZ"),
                setting(GAMES_TASK, "SFIO Priority", "High", "Normal", "REG_SZ"),
            ],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "disable_power_throttling",
                "Disable Power Throttling",
                "gaming",
                "CPU Power",
                "Stops Windows from moving background processes onto efficiency cores and low clocks.",
                "Sets PowerThrottlingOff=1 under Control\\Power\\PowerThrottling.",
                "Helps launchers, voice chat, and streaming tools that run in the background while you play.",
                "Higher power draw and heat, especially on hybrid Intel CPUs and laptops.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.ADVANCED,
            ),
            [policy(r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", 1)],
        ),
        EffectAction(
            platform,
            definition(
                "disable_cpu_core_parking",
                "Disable CPU Core Parking",
                "gaming",
                "CPU Power",
                "Keeps every CPU core available instead of parking idle ones.",
                "Sets Processor performance core parking min cores to 100% on the active plan (AC power).",
                "Avoids the small delay of unparking cores when a game's load spikes.",
                "Higher idle power. Modern CPUs and the High Performance plan often do this already.",
                rollback="Restores the previous core parking minimum from the snapshot.",
                tier=SafetyTier.ADVANCED,
            ),
            [PowerSettingEffect(platform, SUB_PROCESSOR, CPMINCORES, 100, 5, "core parking min cores", ac_only=True)],
        ),
        EffectAction(
            platform,
            definition(
                "max_processor_performance",
                "Keep CPU at Full Clocks (AC)",
                "gaming",
                "CPU Power",
                "Stops the CPU from dropping to low clocks between bursts of game load while plugged in.",
                "Sets Minimum processor state to 100% and Processor performance boost mode to Aggressive on AC power.",
                "Removes clock ramp-up delay that shows up as frame-time spikes in CPU-bound games.",
                "Higher idle power draw and temperature while plugged in. Battery settings are untouched.",
                rollback="Restores the previous processor power settings from the snapshot.",
                tier=SafetyTier.ADVANCED,
            ),
            [
                PowerSettingEffect(platform, SUB_PROCESSOR, PROCTHROTTLEMIN, 100, 5, "minimum processor state", ac_only=True),
                PowerSettingEffect(platform, SUB_PROCESSOR, PERFBOOSTMODE, 2, 1, "processor boost mode", ac_only=True),
            ],
        ),
        EffectAction(
            platform,
            definition(
                "disable_cpu_idle_states",
                "Disable CPU Idle States (C-States)",
                "gaming",
                "CPU Power",
                "Keeps every core out of deep sleep states so it never has to wake up for work.",
                "Sets Processor idle disable to 1 on AC power for the active plan.",
                "Shaves wake-up latency some competitive players chase. Benefit is small on modern CPUs.",
                "The CPU runs much hotter and louder at idle, and can lose boost headroom. Desktop only.",
                rollback="Restores the previous idle setting from the snapshot.",
                tier=SafetyTier.EXPERIMENTAL,
            ),
            [PowerSettingEffect(platform, SUB_PROCESSOR, IDLEDISABLE, 1, 0, "processor idle disable", ac_only=True)],
        ),
        EffectAction(
            platform,
            definition(
                "remove_forced_hpet",
                "Remove Forced HPET Timer (useplatformclock)",
                "gaming",
                "Timers",
                "Undoes the old 'force HPET' boot tweak that many tweak packs and guides apply.",
                "Deletes the useplatformclock value from the current boot entry, so Windows picks its own timer.",
                "Forcing HPET makes timer reads much slower on modern CPUs and is a common cause of stutter.",
                "None on current hardware. Only change it back if a specific tool requires HPET.",
                rollback="Puts the previous useplatformclock value back on the boot entry.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.ADVANCED,
            ),
            [BcdValueEffect(platform, "useplatformclock", None, "Yes")],
        ),
        RegistryPlanAction(
            platform,
            definition(
                "disable_game_bar_tips",
                "Disable Game Bar Tips and Startup Panel",
                "gaming",
                "Game Mode",
                "Stops the Xbox Game Bar from popping tips and its startup panel over games.",
                "Sets ShowStartupPanel=0 and GamePanelStartupTipIndex=3 in the current-user Game Bar key.",
                "Removes an overlay that can steal focus when a game launches.",
                "None beyond losing Game Bar tips.",
                scope=Scope.USER,
                tier=SafetyTier.SAFE,
            ),
            [
                setting(r"HKCU\Software\Microsoft\GameBar", "ShowStartupPanel", 0, 1),
                RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "GamePanelStartupTipIndex", "REG_DWORD", 3),
            ],
        ),
    ]
