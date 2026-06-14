# Contributing to Tweakify

Thanks for helping improve Tweakify.

## Before You Start

- Read the README to understand the project goals and release model.
- Keep changes focused and reviewable.
- Avoid unrelated formatting or dependency churn.

## Local Setup

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

## What We Look For

- Behavior that matches the Windows tuning and recovery workflow described in the README.
- Clear test coverage for new logic.
- UI changes that do not regress startup behavior, diagnostics, or restore flows.

## Pull Request Guidance

- Describe the user-visible change.
- Call out any Windows-only assumptions.
- Include screenshots for UI work when practical.
- Mention the tests you ran.

## Style

- Keep the code straightforward and explicit.
- Prefer small functions and clear names.
- Match the existing project structure and test style.
