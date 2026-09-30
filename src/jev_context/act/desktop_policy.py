"""Deterministic safety gates for hosted desktop execution; they run before any Jev signal.

* Sensitive targets are refused unless the caller opts in: terminals and shells (typing there
  executes commands), password managers, credential and elevation prompts, system settings,
  registry and process managers.
* Abort: a STOP file (``JEV_STOP_FILE`` or ``~/.jev-filter/STOP``) or the pointer parked in the
  top-left screen corner stops the run before the next input.
* Environment: a locked or secure desktop, or (Windows) an elevated target while this process is
  not elevated — UIPI would silently drop input — is a hard error, not a retry.
"""

import os
import sys
from pathlib import Path

DENY_WINDOW_CLASSES = {
    "consolewindowclass",  # conhost: cmd, PowerShell, Python consoles
    "cascadia_hosting_window_class",  # Windows Terminal
    "pseudoconsolewindow",
    "credential dialog xaml host",
    "$$$secure uap dummy window class for interim dialog",
}
DENY_PROCESSES = {
    # shells and terminals
    "windowsterminal.exe",
    "wt.exe",
    "powershell_ise.exe",
    "mintty.exe",
    "alacritty.exe",
    "wezterm-gui.exe",
    "terminal",
    "iterm2",
    "warp",
    "ghostty",
    "kitty",
    # credentials and security
    "keepass.exe",
    "keepassxc.exe",
    "keepassxc",
    "1password.exe",
    "1password",
    "bitwarden.exe",
    "bitwarden",
    "credentialuibroker.exe",
    "consent.exe",
    "securityhealthsystray.exe",
    "keychain access",
    # system configuration and process control
    "systemsettings.exe",
    "system settings",
    "system preferences",
    "regedit.exe",
    "mmc.exe",
    "taskmgr.exe",
    "activity monitor",
    "script editor",
    "automator",
    "control.exe",
    "gpedit.msc",
}


class DesktopRefused(RuntimeError):
    """The target or the environment is not allowed for hosted execution."""


def stop_file():
    return Path(os.environ.get("JEV_STOP_FILE") or Path.home() / ".jev-filter" / "STOP")


def check_target(process, window_class=None, allow_sensitive=False):
    name = (process or "").lower()
    cls = (window_class or "").lower()
    if allow_sensitive:
        return
    if cls in DENY_WINDOW_CLASSES or name in DENY_PROCESSES:
        raise DesktopRefused(
            f"refused_sensitive_target: {process or window_class!s} (terminals, credential managers and "
            "system settings are excluded; pass --allow-sensitive-app to override)"
        )


def pointer_in_corner():
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            point = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
            return point.x <= 1 and point.y <= 1
        if sys.platform == "darwin":  # pragma: no cover - macOS only
            import Quartz

            location = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
            return location.x <= 1 and location.y <= 1
    except Exception:
        return False
    return False


def desktop_locked():
    """True when the interactive desktop is locked or a secure desktop (UAC) is showing."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        handle = user32.OpenInputDesktop(0, False, 0x0001)
        if not handle:
            return True
        try:
            buffer = ctypes.create_unicode_buffer(256)
            needed = ctypes.c_ulong()
            user32.GetUserObjectInformationW(
                handle, 2, buffer, ctypes.sizeof(buffer), ctypes.byref(needed)
            )
            return buffer.value.lower() != "default"
        finally:
            user32.CloseDesktop(handle)
    except Exception:
        return False


def _elevated(pid=None):
    """Windows token elevation of a process (None = this process); None if it cannot be read."""
    import ctypes
    from ctypes import wintypes

    kernel32, advapi32 = ctypes.windll.kernel32, ctypes.windll.advapi32
    process = (
        kernel32.GetCurrentProcess() if pid is None else kernel32.OpenProcess(0x1000, False, pid)
    )
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
            return None
        elevation = wintypes.DWORD()
        size = wintypes.DWORD()
        ok = advapi32.GetTokenInformation(
            token, 20, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(size)
        )
        kernel32.CloseHandle(token)
        return bool(elevation.value) if ok else None
    finally:
        if pid is not None:
            kernel32.CloseHandle(process)


def check_elevation(pid):
    if sys.platform != "win32":
        return
    try:
        target, own = _elevated(pid), _elevated()
    except Exception:
        return
    if target and not own:
        raise DesktopRefused(
            "target_elevated: the application runs as administrator and this process does not; Windows "
            "would silently drop input (UIPI). Run jev-filter elevated or the target unelevated."
        )


class CornerSwitch:
    """Abort when the pointer is MOVED into the top-left corner during a run. A pointer that
    already rests there at start (headless runners often report 0,0) arms the switch only
    after it has left the corner once."""

    def __init__(self):
        self.armed = not pointer_in_corner()

    def tripped(self):
        inside = pointer_in_corner()
        if not self.armed:
            self.armed = not inside
            return False
        return inside


def check_before_input(corner=None):
    if stop_file().exists():
        raise DesktopRefused(f"aborted: stop file present ({stop_file()})")
    if corner is not None and corner.tripped():
        raise DesktopRefused("aborted: pointer parked in the top-left corner")
    if desktop_locked():
        raise DesktopRefused("desktop_locked: the session is locked or a secure desktop is active")
