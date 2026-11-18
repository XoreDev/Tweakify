from __future__ import annotations

import os
from typing import Any

from app.actions.base import BaseEffect, CommandSpec, EffectAction, MaintenanceAction, RegistryPlanAction, RegistryValueSpec
from app.actions.helpers import definition
from app.domain.models import ActionDefinition, ActionKind, RestartRequirement, SafetyTier, Scope


WEEKLY_CLEANUP_TASK = r"\Tweakify\Weekly Cleanup"
WEEKLY_CLEANUP_ACTIONS = (
    "clear_temp_files",
    "clear_error_reports",
    "clear_delivery_optimization_cache",
    "clear_thumbnail_cache",
)
# winget returns APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (0x8A15002B) when nothing needs updating.
WINGET_NOTHING_TO_UPDATE = (0x8A15002B, 0x8A15002B - 2**32)
BLOATWARE_PACKAGES = (
    "Microsoft.BingNews",
    "Microsoft.BingWeather",
    "Microsoft.GetHelp",
    "Microsoft.Getstarted",
    "Microsoft.MicrosoftSolitaireCollection",
    "Microsoft.People",
    "Microsoft.WindowsFeedbackHub",
    "Microsoft.WindowsMaps",
    "Microsoft.ZuneVideo",
    "Microsoft.MicrosoftOfficeHub",
    "Microsoft.PowerAutomateDesktop",
    "Microsoft.Todos",
    "Microsoft.549981C3F5F10",
    "Clipchamp.Clipchamp",
)


def _ps(script: str, ok_codes: tuple[int, ...] = (0,), timeout: int = 1800) -> CommandSpec:
    # `exit 0` matters: a single locked file makes Remove-Item set $? to false, and
    # powershell.exe would then exit 1 and the whole cleanup would report failure.
    return CommandSpec(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"{script}; exit 0"],
        ok_codes=ok_codes,
        timeout=timeout,
    )


def _maintenance(id: str, title: str, group: str, description: str, changes: str, why: str, downside: str, **kwargs):
    kwargs.setdefault("rollback", "No direct rollback. This is a one-time maintenance task.")
    kwargs.setdefault("kind", ActionKind.MAINTENANCE)
    return definition(id, title, "cleanup", group, description, changes, why, downside, **kwargs)


class ScheduledMaintenanceEffect(BaseEffect):
    """Registers a weekly Task Scheduler job that runs Tweakify's own cleanup actions headless."""

    def __init__(self, platform, task_name: str, action_ids: tuple[str, ...]) -> None:
        super().__init__(platform)
        self.task_name = task_name
        self.action_ids = action_ids

    def capture_state(self) -> dict[str, Any]:
        return {"registered": self.platform.scheduled_task_get(self.task_name) is not None}

    def restore_state(self, state: dict[str, Any]) -> None:
        self.apply_target(bool(state.get("registered")))

    def is_enabled(self) -> bool | None:
        return self.platform.scheduled_task_get(self.task_name) is not None

    def plan_commands(self, target_state: bool) -> list[str]:
        if target_state:
            return [f"schtasks create {self.task_name} weekly -> Tweakify --run-actions {','.join(self.action_ids)}"]
        return [f"schtasks delete {self.task_name}"]

    def apply_target(self, target_state: bool) -> None:
        if target_state:
            self.platform.scheduled_task_register(self.task_name, ["--run-actions", ",".join(self.action_ids)])
        else:
            self.platform.scheduled_task_delete(self.task_name)


def build_actions(platform) -> list:
    system_drive = os.environ.get("SystemDrive", "C:")
    return [
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="disk_cleanup",
                title="Disk Cleanup",
                module_id="cleanup",
                legacy_label="DiskCleanup",
                description="Runs Windows Disk Cleanup unattended with every cleanup handler selected.",
                what_it_changes="Selects all Disk Cleanup handlers under profile 777, then runs cleanmgr /sagerun:777.",
                why_it_may_help="Removes old update files, logs, and caches Windows itself considers safe to delete.",
                downside="Takes a while. Removes the ability to uninstall already-installed Windows updates.",
                rollback="No direct rollback. This is a one-way cleanup task.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                kind=ActionKind.MAINTENANCE,
                public_group="Space Recovery",
            ),
            [
                # The old `cleanmgr /d C:` opened an interactive dialog and blocked the apply forever.
                _ps(
                    "$k = 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\VolumeCaches'; "
                    "Get-ChildItem -Path $k | ForEach-Object { Set-ItemProperty -Path $_.PSPath -Name StateFlags0777 "
                    "-Value 2 -Type DWord -ErrorAction SilentlyContinue }; "
                    "Start-Process -FilePath cleanmgr.exe -ArgumentList '/sagerun:777' -Wait -WindowStyle Hidden",
                    timeout=3600,
                )
            ],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="clear_temp_files",
                title="Clear Temp Files",
                module_id="cleanup",
                legacy_label="ClearTempFiles",
                description="Deletes files in your TEMP folder and the Windows TEMP folder.",
                what_it_changes="Removes the contents of %TEMP% and %SystemRoot%\\Temp. Files in use are skipped.",
                why_it_may_help="Temp folders grow for years and are never cleaned automatically.",
                downside="An installer that is running right now may need to be restarted.",
                rollback="No direct rollback. Deleted temp files are not recreated.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                kind=ActionKind.MAINTENANCE,
                public_group="Space Recovery",
            ),
            [
                # -LiteralPath does not expand wildcards, so the old `-LiteralPath $env:TEMP\*`
                # matched a file literally named "*" and deleted nothing.
                _ps(
                    "foreach ($dir in @($env:TEMP, (Join-Path $env:SystemRoot 'Temp'))) { "
                    "if (Test-Path -LiteralPath $dir) { Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | "
                    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue } }"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "clear_windows_update_cache",
                "Clear Windows Update Cache",
                "Space Recovery",
                "Deletes already-installed update downloads from SoftwareDistribution\\Download.",
                "Stops Windows Update and BITS, empties the download cache, and starts them again.",
                "Often frees several GB and fixes updates stuck at 0% or failing to download.",
                "Updates that were downloaded but not installed yet download again.",
            ),
            [
                _ps(
                    "Stop-Service -Name wuauserv, bits -Force -ErrorAction SilentlyContinue; "
                    "Get-ChildItem -LiteralPath (Join-Path $env:SystemRoot 'SoftwareDistribution\\Download') -Force "
                    "-ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; "
                    "Start-Service -Name wuauserv -ErrorAction SilentlyContinue"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "clear_delivery_optimization_cache",
                "Clear Delivery Optimization Cache",
                "Space Recovery",
                "Deletes the peer-to-peer update cache Windows keeps for sharing updates.",
                "Runs Delete-DeliveryOptimizationCache -Force.",
                "Frees space used to seed updates to other PCs.",
                "None. The cache refills only if peer sharing stays on.",
            ),
            [_ps("Delete-DeliveryOptimizationCache -Force -ErrorAction SilentlyContinue")],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "clear_error_reports",
                "Clear Crash Dumps and Error Reports",
                "Space Recovery",
                "Deletes queued and archived Windows Error Reports and app crash dumps.",
                "Empties %LOCALAPPDATA%\\CrashDumps, WER ReportArchive/ReportQueue, and %SystemRoot%\\Minidump.",
                "Crash dumps from games and drivers can take gigabytes.",
                "Old crash data is gone if you later need it for troubleshooting.",
            ),
            [
                _ps(
                    "foreach ($dir in @((Join-Path $env:LOCALAPPDATA 'CrashDumps'), "
                    "(Join-Path $env:ProgramData 'Microsoft\\Windows\\WER\\ReportArchive'), "
                    "(Join-Path $env:ProgramData 'Microsoft\\Windows\\WER\\ReportQueue'), "
                    "(Join-Path $env:SystemRoot 'Minidump'))) { if (Test-Path -LiteralPath $dir) { "
                    "Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | "
                    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue } }"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "clear_thumbnail_cache",
                "Clear Thumbnail Cache",
                "Space Recovery",
                "Deletes Explorer's thumbnail and icon caches so they rebuild.",
                "Removes thumbcache_*.db and iconcache_*.db files that are not in use.",
                "Fixes wrong or stale thumbnails and reclaims space.",
                "Folders with many images show thumbnails a bit slower until the cache rebuilds.",
                scope=Scope.USER,
            ),
            [
                _ps(
                    "Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\\Windows\\Explorer') "
                    "-Include thumbcache_*.db, iconcache_*.db -File -Force -Recurse -ErrorAction SilentlyContinue | "
                    "Remove-Item -Force -ErrorAction SilentlyContinue"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="reset_search_index",
                title="Reset Search Index",
                module_id="cleanup",
                legacy_label="ResetSearchIndex",
                description="Deletes the Windows Search index so it rebuilds from scratch.",
                what_it_changes="Stops Windows Search, deletes Windows.edb / Windows*.db, and starts it again.",
                why_it_may_help="Fixes search that misses files or an index that has grown to several GB.",
                downside="Search results are incomplete for a while as the index rebuilds.",
                rollback="No direct rollback. Windows rebuilds the index after removal.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.ADVANCED,
                kind=ActionKind.MAINTENANCE,
                public_group="Maintenance",
            ),
            [
                # The index is locked while WSearch runs. Windows 11 24H2+ uses Windows.db, not Windows.edb.
                _ps(
                    "Stop-Service -Name WSearch -Force -ErrorAction SilentlyContinue; "
                    "$dir = Join-Path $env:ProgramData 'Microsoft\\Search\\Data\\Applications\\Windows'; "
                    "Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | "
                    "Where-Object { $_.Name -like 'Windows*.db' -or $_.Name -eq 'Windows.edb' } | "
                    "Remove-Item -Force -ErrorAction SilentlyContinue; "
                    "Start-Service -Name WSearch -ErrorAction SilentlyContinue"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="clear_browser_cache",
                title="Clear Browser Caches",
                module_id="cleanup",
                legacy_label="ClearBrowserCache",
                description="Clears the disk caches of Chrome, Edge, Brave, and Firefox for every profile.",
                what_it_changes="Empties each profile's Cache, Code Cache, and GPUCache folders. Cookies, logins, and history are untouched.",
                why_it_may_help="Browser caches commonly reach several GB.",
                downside="Sites load a little slower the first time after cleaning. Close browsers first for a full clean.",
                rollback="No direct rollback. Cache contents are re-created over time by the browser.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.ADVANCED,
                kind=ActionKind.MAINTENANCE,
                public_group="Maintenance",
            ),
            [
                _ps(
                    "$roots = @('Google\\Chrome\\User Data', 'Microsoft\\Edge\\User Data', 'BraveSoftware\\Brave-Browser\\User Data') | "
                    "ForEach-Object { Join-Path $env:LOCALAPPDATA $_ } | Where-Object { Test-Path -LiteralPath $_ }; "
                    "foreach ($root in $roots) { Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | "
                    "ForEach-Object { foreach ($c in @('Cache', 'Code Cache', 'GPUCache')) { $p = Join-Path $_.FullName $c; "
                    "if (Test-Path -LiteralPath $p) { Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue | "
                    "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue } } } }; "
                    "$ff = Join-Path $env:LOCALAPPDATA 'Mozilla\\Firefox\\Profiles'; if (Test-Path -LiteralPath $ff) { "
                    "Get-ChildItem -LiteralPath $ff -Directory | ForEach-Object { $p = Join-Path $_.FullName 'cache2'; "
                    "if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue } } }"
                )
            ],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="empty_recycle_bin",
                title="Empty Recycle Bin",
                module_id="cleanup",
                legacy_label="EmptyRecycleBin",
                description="Empties the Recycle Bin on every drive.",
                what_it_changes="Invokes Clear-RecycleBin with force.",
                why_it_may_help="Deleted files keep using disk space until the bin is emptied.",
                downside="Files in the Recycle Bin are permanently deleted.",
                rollback="No direct rollback. Emptying the Recycle Bin is intentionally destructive.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.ADVANCED,
                kind=ActionKind.MAINTENANCE,
                public_group="Space Recovery",
            ),
            [_ps("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="optimize_defrag_drives",
                title="Optimize Drives",
                module_id="cleanup",
                legacy_label="OptimizeDefragDrives",
                description="Runs Windows drive optimization on the system drive: TRIM on SSDs, defrag on HDDs.",
                what_it_changes="Runs defrag <system drive> /O.",
                why_it_may_help="Keeps SSD write performance up and HDD seek times down.",
                downside="Can take a long time on large hard drives.",
                rollback="No direct rollback. This is a maintenance operation rather than a persistent setting.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                kind=ActionKind.MAINTENANCE,
                public_group="Maintenance",
            ),
            [CommandSpec(["defrag", system_drive, "/O"], timeout=7200)],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="check_disk_errors",
                title="Check Disk Errors",
                module_id="cleanup",
                legacy_label="CheckDiskErrors",
                description="Runs a non-destructive online disk scan on the system drive.",
                what_it_changes="Runs chkdsk /scan against the system drive.",
                why_it_may_help="Finds file system corruption before it turns into lost data.",
                downside="Read-heavy for a few minutes.",
                rollback="No rollback needed. This is a read-oriented maintenance scan.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.NONE,
                safety_tier=SafetyTier.SAFE,
                kind=ActionKind.MAINTENANCE,
                public_group="Repair",
            ),
            # chkdsk: 0 = clean, 1 = errors found and fixed, 2 = cleanup done, 3 = could not check/fix.
            [CommandSpec(["chkdsk", system_drive, "/scan"], ok_codes=(0, 1, 2), timeout=7200)],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "repair_system_files",
                "Repair System Files (SFC)",
                "Repair",
                "Scans protected Windows files and replaces corrupted ones.",
                "Runs sfc /scannow.",
                "Fixes crashes and broken Windows features caused by damaged system files.",
                "Takes 5-20 minutes.",
                tier=SafetyTier.SAFE,
            ),
            [CommandSpec(["sfc", "/scannow"], ok_codes=(0, 1), timeout=3600)],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "repair_windows_image",
                "Repair Windows Image (DISM)",
                "Repair",
                "Repairs the Windows component store that SFC uses as its source.",
                "Runs DISM /Online /Cleanup-Image /RestoreHealth.",
                "Fixes cases where SFC cannot repair files, and failing Windows updates.",
                "Needs an internet connection and can take 10-30 minutes.",
                tier=SafetyTier.SAFE,
            ),
            [CommandSpec(["DISM", "/Online", "/Cleanup-Image", "/RestoreHealth"], ok_codes=(0, 3010), timeout=5400)],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "cleanup_component_store",
                "Clean Up Component Store (WinSxS)",
                "Space Recovery",
                "Removes superseded Windows component versions from WinSxS.",
                "Runs DISM /Online /Cleanup-Image /StartComponentCleanup.",
                "Typically frees 1-5 GB on systems that have taken many cumulative updates.",
                "Installed updates can no longer be uninstalled after cleanup.",
                tier=SafetyTier.ADVANCED,
            ),
            [CommandSpec(["DISM", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], ok_codes=(0, 3010), timeout=5400)],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "flush_dns_cache",
                "Flush DNS Cache",
                "Repair",
                "Clears cached DNS lookups.",
                "Runs ipconfig /flushdns.",
                "Fixes sites that moved servers and still fail to load.",
                "None.",
                tier=SafetyTier.SAFE,
            ),
            [CommandSpec(["ipconfig", "/flushdns"], timeout=60)],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "reset_network_stack",
                "Reset Network Stack",
                "Repair",
                "Resets Winsock and the TCP/IP stack to defaults.",
                "Runs netsh winsock reset, netsh int ip reset, and ipconfig /flushdns.",
                "Fixes broken connectivity left behind by VPNs, proxies, and other network tools.",
                "Static IP and custom adapter settings are cleared. A restart is required.",
                restart=RestartRequirement.RESTART,
                tier=SafetyTier.ADVANCED,
            ),
            [
                CommandSpec(["netsh", "winsock", "reset"], timeout=120),
                CommandSpec(["netsh", "int", "ip", "reset"], ok_codes=(0, 1), timeout=120),
                CommandSpec(["ipconfig", "/flushdns"], timeout=60),
            ],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "update_all_apps",
                "Update All Apps (winget)",
                "Software",
                "Updates every installed app that winget knows a newer version of.",
                "Runs winget upgrade --all silently, accepting package and source agreements.",
                "Keeps apps patched without visiting each vendor site, like paid 'software updater' tools.",
                "Apps may close during their update. Needs App Installer (winget) from the Microsoft Store.",
                tier=SafetyTier.ADVANCED,
            ),
            [
                CommandSpec(
                    [
                        "winget",
                        "upgrade",
                        "--all",
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                        "--disable-interactivity",
                    ],
                    ok_codes=(0, *WINGET_NOTHING_TO_UPDATE),
                    timeout=7200,
                )
            ],
        ),
        MaintenanceAction(
            platform,
            _maintenance(
                "remove_bloatware_apps",
                "Remove Preinstalled Bloat Apps",
                "Software",
                "Uninstalls a curated list of consumer apps Windows ships with, for the current user.",
                "Removes: " + ", ".join(name.split(".", 1)[-1] for name in BLOATWARE_PACKAGES) + ".",
                "Fewer apps updating and running in the background, and a cleaner Start menu.",
                "Each app can be reinstalled from the Microsoft Store.",
                scope=Scope.USER,
                tier=SafetyTier.ADVANCED,
            ),
            [
                _ps(
                    "foreach ($name in @(" + ", ".join(f"'{name}'" for name in BLOATWARE_PACKAGES) + ")) { "
                    "Get-AppxPackage -Name $name -ErrorAction SilentlyContinue | Remove-AppxPackage -ErrorAction SilentlyContinue }",
                    timeout=1800,
                )
            ],
        ),
        RegistryPlanAction(
            platform,
            ActionDefinition(
                id="remove_shortcut_text",
                title="Remove Shortcut Text",
                module_id="cleanup",
                legacy_label="RemoveShortcutText",
                description="Stops Explorer from adding ' - Shortcut' to new shortcut names.",
                what_it_changes="Sets ShortcutNameTemplate under Explorer NamingTemplates.",
                why_it_may_help="Cleaner shortcut names without manual renaming.",
                downside="None.",
                rollback="Restores the previous shortcut naming template from the snapshot.",
                scope=Scope.USER,
                restart_requirement=RestartRequirement.EXPLORER,
                safety_tier=SafetyTier.SAFE,
                public_group="Shell",
            ),
            [
                RegistryValueSpec(
                    path=r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\NamingTemplates",
                    name="ShortcutNameTemplate",
                    value_type="REG_SZ",
                    enabled_value="%s.lnk",
                    delete_on_disable=True,
                )
            ],
        ),
        MaintenanceAction(
            platform,
            ActionDefinition(
                id="remove_onedrive",
                title="Remove OneDrive",
                module_id="cleanup",
                legacy_label="RemoveOneDrive",
                description="Uninstalls OneDrive using whichever OneDriveSetup.exe this PC has.",
                what_it_changes="Stops OneDrive and runs OneDriveSetup.exe /uninstall (System32, SysWOW64, or per-user install).",
                why_it_may_help="Removes a sync client that runs at every sign-in.",
                downside="Files only stored in OneDrive (online-only) are no longer available locally.",
                rollback="No direct automatic rollback. Reinstall OneDrive from microsoft.com or winget.",
                scope=Scope.MACHINE,
                restart_requirement=RestartRequirement.LOGOFF,
                safety_tier=SafetyTier.ADVANCED,
                kind=ActionKind.MAINTENANCE,
                public_group="Shell",
            ),
            [
                CommandSpec(
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        "$candidates = @((Join-Path $env:SystemRoot 'System32\\OneDriveSetup.exe'), "
                        "(Join-Path $env:SystemRoot 'SysWOW64\\OneDriveSetup.exe')) + "
                        "@(Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Microsoft\\OneDrive\\*\\OneDriveSetup.exe') "
                        "-ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }); "
                        "$setup = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1; "
                        "if (-not $setup) { exit 2 }; "
                        "Stop-Process -Name OneDrive -Force -ErrorAction SilentlyContinue; "
                        "Start-Process -FilePath $setup -ArgumentList '/uninstall' -Wait; exit 0",
                    ],
                    timeout=900,
                )
            ],
        ),
        EffectAction(
            platform,
            definition(
                "schedule_weekly_cleanup",
                "Weekly Automatic Cleanup",
                "cleanup",
                "Automation",
                "Runs Tweakify's temp, crash-dump, Delivery Optimization, and thumbnail cleanup every week.",
                f"Registers the scheduled task {WEEKLY_CLEANUP_TASK} that runs Tweakify headless each Sunday at noon.",
                "Keeps junk from piling up without remembering to run a cleaner.",
                "Runs with administrator rights in the background once a week.",
                rollback="Deletes the scheduled task again.",
                tier=SafetyTier.SAFE,
            ),
            [ScheduledMaintenanceEffect(platform, WEEKLY_CLEANUP_TASK, WEEKLY_CLEANUP_ACTIONS)],
        ),
    ]
