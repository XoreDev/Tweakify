"""Low-overhead live system metrics for the dashboard monitor.

Everything here is a direct Win32 call (no subprocesses), so a sample costs well
under a millisecond and can run on the GUI thread once a second:

- CPU: GetSystemTimes deltas.
- Memory: GlobalMemoryStatusEx.
- GPU and disk: PDH counters ("GPU Engine(*engtype_3D)" and "PhysicalDisk(_Total)"),
  added by English name so they work on localized Windows. Either may be missing
  (old drivers, PDH disabled); the sample then reports None for it.
"""

from __future__ import annotations

import ctypes
import math
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class LiveSample:
    cpu_percent: float | None
    memory_percent: float | None
    memory_used_bytes: int | None
    memory_total_bytes: int | None
    gpu_percent: float | None
    disk_percent: float | None


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def ticks(self) -> int:
        return (self.high << 32) | self.low


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _PdhCounterValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PdhCounterItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PdhCounterValue)]


PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2


class WindowsLiveSampler:
    def __init__(self) -> None:
        self._kernel32 = ctypes.windll.kernel32
        self._previous_times: tuple[int, int, int] | None = None
        self._pdh = None
        self._query = None
        self._gpu_counter = None
        self._disk_counter = None
        self._open_pdh()
        self.sample()  # prime the CPU/PDH deltas so the first visible sample is real

    def _open_pdh(self) -> None:
        try:
            pdh = ctypes.WinDLL("pdh")
            # PDH returns unsigned status codes (PDH_MORE_DATA is 0x800007D2).
            for name in ("PdhOpenQueryW", "PdhAddEnglishCounterW", "PdhCollectQueryData", "PdhGetFormattedCounterArrayW", "PdhCloseQuery"):
                getattr(pdh, name).restype = wintypes.DWORD
            query = wintypes.HANDLE()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
                return
            self._pdh, self._query = pdh, query
            self._gpu_counter = self._add_counter(r"\GPU Engine(*engtype_3D)\Utilization Percentage")
            self._disk_counter = self._add_counter(r"\PhysicalDisk(_Total)\% Idle Time")
            pdh.PdhCollectQueryData(query)
        except (AttributeError, OSError):
            self._pdh = None

    def _add_counter(self, path: str):
        counter = wintypes.HANDLE()
        status = self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(counter))
        return counter if status == 0 else None

    def _cpu_percent(self) -> float | None:
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        if not self._kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        current = (idle.ticks(), kernel.ticks(), user.ticks())
        previous, self._previous_times = self._previous_times, current
        if previous is None:
            return None
        idle_delta = current[0] - previous[0]
        # Kernel time includes idle time.
        total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))

    def _memory(self) -> tuple[float | None, int | None, int | None]:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not self._kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None, None
        used = status.ullTotalPhys - status.ullAvailPhys
        return float(status.dwMemoryLoad), int(used), int(status.ullTotalPhys)

    def _counter_sum(self, counter) -> float | None:
        if counter is None:
            return None
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        status = self._pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != PDH_MORE_DATA or size.value == 0:
            return 0.0 if status == 0 else None
        buffer = (ctypes.c_byte * size.value)()
        status = self._pdh.PdhGetFormattedCounterArrayW(
            counter, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, ctypes.byref(size), ctypes.byref(count), buffer
        )
        if status != 0:
            return None
        items = ctypes.cast(buffer, ctypes.POINTER(_PdhCounterItem))
        total = 0.0
        for index in range(count.value):
            value = items[index].FmtValue.doubleValue
            if items[index].FmtValue.CStatus in (0, 1) and math.isfinite(value):
                total += value
        return total

    def sample(self) -> LiveSample:
        cpu = self._cpu_percent()
        memory_percent, used, total = self._memory()
        gpu = disk = None
        if self._pdh is not None and self._query is not None:
            try:
                if self._pdh.PdhCollectQueryData(self._query) == 0:
                    gpu = self._counter_sum(self._gpu_counter)
                    idle = self._counter_sum(self._disk_counter)
                    disk = None if idle is None else max(0.0, min(100.0, 100.0 - idle))
            except OSError:
                gpu = disk = None
        return LiveSample(
            cpu_percent=cpu,
            memory_percent=memory_percent,
            memory_used_bytes=used,
            memory_total_bytes=total,
            gpu_percent=None if gpu is None else max(0.0, min(100.0, gpu)),
            disk_percent=disk,
        )

    def close(self) -> None:
        if self._pdh is not None and self._query is not None:
            try:
                self._pdh.PdhCloseQuery(self._query)
            except OSError:
                pass
        self._pdh = self._query = None


class SyntheticLiveSampler:
    """Deterministic waveform for tests, screenshots, and non-Windows runs."""

    def __init__(self) -> None:
        self._tick = 0

    def sample(self) -> LiveSample:
        self._tick += 1
        t = self._tick
        total = 32 * 1024**3
        memory_percent = 46 + 6 * math.sin(t / 9)
        return LiveSample(
            cpu_percent=round(18 + 12 * math.sin(t / 3) + 6 * math.sin(t / 1.7), 1),
            memory_percent=round(memory_percent, 1),
            memory_used_bytes=int(total * memory_percent / 100),
            memory_total_bytes=total,
            gpu_percent=round(max(0.0, 34 + 22 * math.sin(t / 4.5)), 1),
            disk_percent=round(max(0.0, 6 + 5 * math.sin(t / 2.3)), 1),
        )

    def close(self) -> None:
        return


def purge_standby_list() -> bool:
    """Empty the standby page list (what ISLC and RAMMap 'Empty Standby List' do).

    Needs administrator rights: SeProfileSingleProcessPrivilege must be enabled on
    the process token before NtSetSystemInformation accepts the request.
    """
    SE_PRIVILEGE_ENABLED = 0x2
    TOKEN_ADJUST_PRIVILEGES = 0x20
    TOKEN_QUERY = 0x8
    SYSTEM_MEMORY_LIST_INFORMATION = 80
    MEMORY_PURGE_STANDBY_LIST = 4

    class _Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _TokenPrivileges(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Luid", _Luid), ("Attributes", wintypes.DWORD)]

    try:
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            ctypes.windll.kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)
        ):
            return False
        try:
            luid = _Luid()
            if not advapi32.LookupPrivilegeValueW(None, "SeProfileSingleProcessPrivilege", ctypes.byref(luid)):
                return False
            privileges = _TokenPrivileges(1, luid, SE_PRIVILEGE_ENABLED)
            ctypes.set_last_error(0)
            advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
            if ctypes.get_last_error() != 0:  # ERROR_NOT_ALL_ASSIGNED: not elevated
                return False
        finally:
            ctypes.windll.kernel32.CloseHandle(token)
        command = ctypes.c_int(MEMORY_PURGE_STANDBY_LIST)
        status = ctypes.windll.ntdll.NtSetSystemInformation(
            SYSTEM_MEMORY_LIST_INFORMATION, ctypes.byref(command), ctypes.sizeof(command)
        )
        return status == 0
    except (AttributeError, OSError):
        return False
