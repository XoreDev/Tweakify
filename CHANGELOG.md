# Changelog

All notable changes to Tweakify. Versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-11-19

A ground-up rebuild of the interface, a much faster scan, a live system monitor, and six new tweaks.
Tweaks: 115 -> 121. Tests: 130 -> 153.

### Highlights

- **New interface, rebuilt from scratch.** A new "Obsidian" design system: near-black surfaces, one accent
  color you pick (light-blue Sky by default, or Volt, Cyan, Azure, Ember, Rose), dense tweak lists instead of card stacks, animated
  switches, and a dashboard built around one health gauge and live data.
- **Live monitor.** CPU, memory, GPU, and disk activity with one-minute sparklines on the dashboard, plus a
  compact readout in the top bar. It uses direct Windows APIs (about 0.5 ms per sample), pauses while
  the window is minimized, and never starts a subprocess.
- **Command palette (Ctrl+K).** Jump to any page or tweak, or run a command (Optimize now, Rescan,
  Free memory, Restore point, Ping test, Apply) from the keyboard.
- **3x faster scan.** Tweak states are now read in parallel: the background scan went from 14.1 s to
  4.6 s on a real machine, and the command-line startup path from 47 s to 7 s.

### Interface

- Navigation rail with section labels and Ctrl+1..9 page shortcuts; top bar with search, live readout,
  elevation status, and a Review button that shows how many changes are waiting.
- The review panel slides in when you stage something and gets out of the way when the plan is empty
  (pin it open in Settings). Each staged change can be removed individually, and Apply shows the count.
- Every tweak page has filters (All, Recommended, Active, Pending), live counts, and an
  "Enable recommended" button that stages only the Safe tweaks that are still off.
- Tweak rows show the current state, the pending change, a colored tier badge only when a tweak is not
  Safe, and an expandable panel with what it changes, why it helps, the trade-off, and the rollback.
- Dashboard: animated health gauge with findings, "Optimize now" (stages recommended fixes), system facts
  with warning colors, quick actions (Free memory, Restore point, Ping test, Task Manager), and recent
  activity.
- Toast confirmations for applies, restore points, rollbacks, and quick actions.
- Settings rebuilt as Windows-style rows with switches, an accent picker, and plain-language descriptions.
- Compatibility lists each blocked tweak with its reason; Restore shows snapshots and details side by side.
- The loading screen uses your saved theme and accent.
- Reduced motion turns off every animation (switches, gauge, page fades, toasts).

### Added tweaks

- **Disable VBS and Memory Integrity** (Gaming, Advanced): turns off Virtualization-Based Security and HVCI.
- **Disable Automatic Maintenance** (Performance, Advanced): stops surprise idle-time maintenance spikes.
- **Disable 8.3 Short Name Creation** (Performance, Advanced): faster file creation in large folders.
- **Disable Update Peer-to-Peer Upload** (Network, Safe): stops Delivery Optimization uploading to other PCs.
- **Disable Transparency Effects** (Input + UI, Safe): less GPU composition work on weaker graphics.
- **Free Standby Memory** (Cleanup, one-time): empties the standby list, like RAMMap or ISLC. Also a
  dashboard quick action.

### Performance and reliability

- Tweak probes, the machine-context probe, the startup inventory, and the cleanup size scan run on a
  thread pool. The first-launch baseline capture is parallel and cached too.
- The probe cache is now scoped to the scan that opened it. Before, an Apply that ran while a background
  scan was in progress could read cached (stale) values for its before/after checks.
- Concurrent probes for the same value share one PowerShell call instead of each starting their own.
- After a rescan or apply, the tweak lists are updated in place when the catalog has not changed instead
  of rebuilding about 120 widgets, and rows skip redrawing when nothing about them changed.
- Preset cards are reused across refreshes.
- Closing the window during an apply or rollback now waits for it to finish instead of cutting it off.
- A background task that finishes after the window closed no longer raises an error.

### Fixed

- A unit test reached the real "relaunch as administrator" path and could leave a UAC prompt waiting,
  which stalled the test run. Tests can no longer trigger a real elevation.
- "Use Google Public DNS DNS" is now "Use Google Public DNS".

## [1.1.0] - 2026-11-18

A full audit of 1.0.0, a redesigned interface, and features drawn from a survey of
44 paid, free, and community optimizers (see [docs/competitive-research.md](docs/competitive-research.md)).
Tweaks: 63 -> 115. Tests: 92 -> 130.

### Highlights

- System health score, recoverable-space scan, and one-click "Stage Recommended Fixes".
- New Privacy and Gaming pages, real NVIDIA driver settings, repair tools, and weekly automatic cleanup.
- New dark and light design, including a redesigned loading screen.
- About 30 bug fixes, several of which meant tweaks silently never applied.

### Upgrading from 1.0.0

- Settings, snapshots, and apply history from 1.0.0 load as-is. Most 1.0.0 snapshots can still be rolled
  back; entries for tweaks that were removed or reshaped (keyboard buffer, the old USB tweak, the old
  NVIDIA commands, the DCA network option) are reported as failed and skipped, never half-applied.
- Service tweaks applied with 1.0.0 never took effect (see below). Re-apply them in 1.1.0 if you want them.
- If you turned a policy tweak *off* in 1.0.0 (SmartScreen, Cortana, telemetry, LLMNR, QoS, browser
  background mode, Edge startup boost), Windows may show "managed by your organization". Turn the tweak
  on and off once in 1.1.0 to remove the leftover policy.
- The NVIDIA tweaks now need NVIDIA Profile Inspector instead of nvidiaInspector.exe. Use
  Settings > Integrations > Download Latest.

### Fixed: changes that never applied or did the wrong thing

- **Service tweaks never applied.** `sc config <svc> "start= disabled"` was passed as one
  argument, which sc.exe rejects. Every Disable-service action silently did nothing.
- **Clear Temp Files deleted nothing.** `Remove-Item -LiteralPath $env:TEMP\*` treats `*`
  literally. It now empties both user and Windows TEMP.
- **NVIDIA tweaks were fake.** The four NVIDIA actions passed made-up switches
  (`-setVSync`, `-setPowerMizerMode`, ...) to nvidiaInspector.exe, and the repo shipped a
  4-byte text file named `nvidiaInspector.exe`. They now import real driver setting IDs
  through NVIDIA Profile Inspector, and are blocked on non-NVIDIA GPUs.
- **Turning a policy tweak off locked it on.** Off wrote the opposite value into
  `HKLM\SOFTWARE\Policies` (SmartScreen, Cortana, telemetry, LLMNR, QoS, Chrome/Edge
  background mode, Edge startup boost), which shows "managed by your organization".
  Off now deletes the policy.
- **Optimize CPU Priority was a no-op.** It wrote `Win32PrioritySeparation=2`, the Windows
  default. It now writes 0x26.
- **Disable Last Access Timestamp, turned off, forced last-access updates on** (wrote 0
  instead of the system-managed default).
- **Hardware GPU Scheduling** wrote the undocumented `HwSchMode=0`; off is 1.
- **Disk Cleanup hung the apply** by opening the interactive cleanmgr dialog. It now runs
  unattended with `/sagerun`.
- **Reset Search Index failed** because the index is locked while WSearch runs, and
  Windows 11 24H2+ uses `Windows.db`.
- **Refresh rate reverted on reboot** (`ChangeDisplaySettings` flag 0), and "highest rate"
  could pick a rate only offered at another resolution.
- **Startup disable broke `REG_EXPAND_SZ` entries** by rewriting them as `REG_SZ`.
  `desktop.ini` appeared as a startup app. 32-bit (WOW6432Node) Run entries were missing.
- **"USB Selective Suspend"** edited an unrelated hub value. It now sets the real powercfg
  setting. "Reduce Input Delay" is renamed to what it does (network throttling).
- **Gaming presets turned mouse trails on.**
- TCP probes parsed English-only netsh output; now locale-independent. DCA (removed in
  Windows 10) dropped.
- Power plans restore by GUID, so rollback works on non-English Windows. Ultimate
  Performance is unlocked with `-duplicatescheme` when missing.

### Fixed: safety and robustness

- One failing action no longer aborts the apply. It reverts its own partial changes, the
  rest still run, and the snapshot is always saved.
- Rollback runs newest-first and isolates failures per entry.
- Registry rollbacks restore the original value type.
- Per-adapter TCP values roll back per adapter instead of flattening to one value.
- Missing services and scheduled tasks are skipped instead of reported as failures.
- Snapshot/settings/log writes are atomic. Corrupt or newer-format files no longer stop
  the app from starting. Apply logs are capped at 200.
- Restore points: the 24-hour creation limit is lifted for the call, the result is
  verified, and a failure is shown instead of ignored.
- UAC relaunch quotes paths correctly (spaces, apostrophes) and a declined prompt no
  longer makes the app exit silently.
- Restore point, rollback, and baseline capture run off the GUI thread. Open Task Manager
  no longer freezes the window until Task Manager closes. Rollback asks for confirmation.
- Network downloads have timeouts, a size cap, and a github.com host check.
- CLI `--apply-plan` / `--rollback-snapshot` print per-action results and return a
  non-zero exit code on failure.
- `pytest-qt` was used by tests but not declared; added `requirements-dev.txt`.

### Redesigned UI

- New design system: carbon-dark neutral base with one electric-cyan accent, replacing the
  pink/purple gradients and glow. Matching light theme.
- Sidebar with icons, OVERVIEW / TUNE / SYSTEM sections, and an accent indicator on the
  active page. Page headers are plain titles instead of gradient banners.
- Health score shown as a colored ring gauge, findings as colored severity dots.
- Safety tiers are color-coded (green Safe, amber Advanced, red Experimental). Staged
  cards get an amber outline. Toggles are pill switches that fill with the accent when On.
- Each tweak's "What it changes / Why / Downside / Rollback" text is now behind a
  Details toggle, so pages are scannable. The dry-run plan uses a monospace font.
- Even metric grid, thin scrollbars, underlined tabs, styled checkboxes and tooltips.
- New loading screen: brand mark, status line, and an animated progress bar. It follows the
  Windows light/dark setting.

### Added from community tweak utilities

- Per-game High CPU and I/O priority (Settings > Games), minimum processor state +
  Aggressive boost, CPU idle states off (Experimental), remove forced HPET,
  NIC interrupt moderation off, Energy-Efficient Ethernet off, Teredo off, a ping test on
  the dashboard, and "Disable All" for startup apps. 108 actions -> 115.

### Added

- **Dashboard health score** with explained findings and "Stage Recommended Fixes"
  (Safe actions only), plus a **recoverable space** scan.
- **Privacy page**: advertising ID, tailored experiences, Start/Settings suggestions,
  lock screen tips, Bing in Start, activity history, app launch tracking, feedback
  prompts, inking/typing personalization, Copilot, Recall, Office telemetry, location.
- **Gaming page**: foreground priority, MMCSS game priority, power throttling, core
  parking, network throttling, Game Bar tips.
- **Performance**: Ultimate Performance plan, USB selective suspend, PCIe ASPM,
  hibernation, Fast Startup, memory compression.
- **Graphics**: fullscreen optimizations, windowed-game optimizations, VRR, five real
  NVIDIA driver settings.
- **Network**: Cloudflare / Google / Quad9 DNS with per-adapter restore.
- **Services**: SysMain, Windows Search, Print Spooler, rarely used services to Manual.
- **Cleanup & repair**: Windows Update cache, Delivery Optimization cache, crash dumps,
  thumbnail cache, multi-browser caches, SFC, DISM RestoreHealth, WinSxS cleanup, DNS
  flush, network stack reset, winget "Update All Apps", bloat app removal, weekly
  scheduled cleanup.
- Sidebar **search** across all tweaks, **conflict handling** (for example two power plans),
  **plan export/import**, laptop-aware warnings, and `--run-actions` for headless runs.

## [1.0.0]

First public release of the rebuilt Tweakify: staged review panel, diagnostics, presets, startup manager, snapshots with rollback, and a portable source package.

[1.2.0]: https://github.com/XoreDev/Tweakify/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/XoreDev/Tweakify/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/XoreDev/Tweakify/releases/tag/v1.0.0
