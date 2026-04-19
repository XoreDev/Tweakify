from __future__ import annotations

import os
import subprocess
from typing import Any


def hidden_process_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)

    kwargs: dict[str, Any] = {}
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo
    if creationflags:
        kwargs["creationflags"] = creationflags
    return kwargs
