# Tweakify

[Download Latest Release](https://github.com/XoreDev/Tweakify/releases/latest)

Windows tuning, startup cleanup, and diagnostics in a staged desktop workflow.

Tweakify is a source-first PySide6 app for reviewing Windows tweaks before you apply them. It keeps the fast utility feel of a tweak tool, but adds a safer review rail, clearer diagnostics, restore support, and a portable release package.

## Why It Exists

- Stage changes before they touch the machine.
- See live diagnostics and compatibility gates in one place.
- Keep restore points, rollback history, and startup cleanup close to the actions that need them.
- Ship a portable source release that can be inspected, modified, and rebuilt locally.

## Administrator Access

Tweakify launches with Administrator privileges for normal interactive use.

It does this so machine-scope Windows changes, restore point creation, and apply flows can run without interrupting the session with mid-action UAC prompts.

`--help`, `--apply-plan`, and `--rollback-snapshot` remain non-interactive exceptions and do not trigger the startup elevation flow.

## Quick Start

### Source Run

```powershell
python -m pip install -r requirements.txt
python .\Tweakify.py
```

### Portable Run

```powershell
python .\tools\build_portable.py
cd .\TweakifyPortable
.\install_requirements.bat
py .\Tweakify.py
```

## Repository Layout

```text
app/                      PySide6 application code
tests/                    pytest coverage for launcher, UI, platform, and packaging
tools/build_portable.py   portable bundle builder
Tweakify.py               console launcher
Tweakify.pyw              GUI launcher
install_requirements.bat  Windows dependency bootstrapper
```

## Release Artifact

Public releases ship the repository source on GitHub plus one portable asset:

- `Tweakify-v1.0.0-portable.rar`

The RAR contains the portable folder produced by `tools/build_portable.py`.

## Development

```powershell
python -m pytest
```

The project targets Python 3.13+ and PySide6.
