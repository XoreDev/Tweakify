"""Per-game CPU and I/O priority, the "game exe priority" feature paid tweak packs sell.

Windows applies Image File Execution Options\\<exe>\\PerfOptions every time that
executable starts, so no background service is needed and removing the value undoes it.
"""

from __future__ import annotations

import re

from app.actions.base import EffectAction, RegistryEffect, RegistryValueSpec
from app.actions.helpers import definition
from app.domain.models import RestartRequirement, SafetyTier

GAME_PRIORITY_ACTION_ID = "game_cpu_priority"
IFEO = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
CPU_PRIORITY_HIGH = 3
IO_PRIORITY_HIGH = 3
# Executables that must never get a priority override.
PROTECTED_EXECUTABLES = {
    "csrss.exe", "lsass.exe", "smss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "svchost.exe", "explorer.exe", "dwm.exe", "system", "audiodg.exe",
}


def parse_game_executables(raw: str) -> list[str]:
    """Turn "FortniteClient-Win64-Shipping.exe, cs2" into clean, de-duplicated exe names."""
    names: list[str] = []
    for token in re.split(r"[,;\n]+", raw or ""):
        name = token.strip().strip('"').split("\\")[-1].split("/")[-1]
        if not name:
            continue
        if not name.lower().endswith(".exe"):
            name += ".exe"
        if not re.fullmatch(r"[\w .()+-]+\.exe", name) or name.lower() in PROTECTED_EXECUTABLES:
            continue
        if name.lower() not in {existing.lower() for existing in names}:
            names.append(name)
    return names


def build_game_priority_action(platform, raw_executables: str) -> EffectAction:
    executables = parse_game_executables(raw_executables)
    listed = ", ".join(executables) if executables else "the games listed in Settings > Games"
    effects = []
    for exe in executables:
        perf = rf"{IFEO}\{exe}\PerfOptions"
        effects.append(RegistryEffect(platform, RegistryValueSpec(perf, "CpuPriorityClass", "REG_DWORD", CPU_PRIORITY_HIGH)))
        effects.append(RegistryEffect(platform, RegistryValueSpec(perf, "IoPriority", "REG_DWORD", IO_PRIORITY_HIGH)))
    return EffectAction(
        platform,
        definition(
            GAME_PRIORITY_ACTION_ID,
            "High CPU and I/O Priority for My Games",
            "gaming",
            "Game Profiles",
            "Starts your chosen games at High CPU priority and high disk priority, every time.",
            f"Sets Image File Execution Options PerfOptions CpuPriorityClass=3 and IoPriority=3 for {listed}.",
            "The game wins CPU and disk contention against launchers, browsers, and updaters running alongside it.",
            "Background apps such as voice chat or streaming software get less CPU while the game runs.",
            rollback="Deletes the PerfOptions values again.",
            restart=RestartRequirement.NONE,
            tier=SafetyTier.ADVANCED,
        ),
        effects,
    )
