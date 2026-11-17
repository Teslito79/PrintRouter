"""ORCA opens only once (Tesla, 2026-11-17).

app.py takes a named Windows mutex before anything else: Local\\ORCA-<short hash of the ADMIN folder>. A second
start finds it taken, brings the running ORCA's window to the front (restored if minimised) and quits at once,
touching nothing. Windows frees the mutex when the process ends, even after a crash or Task Manager, so no lock
file is ever left behind.

Every ORCA window carries a window property (mark(), from theme.dark_title_bar) so the second start finds it
without relying on window titles.

Run as a script (ORCA.bat, before its git pull): exit code 1 while ORCA is open, else 0. Only the standard
library is used here, so the check is quick.
"""
import ctypes
import hashlib
import sys
from ctypes import wintypes
from pathlib import Path

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
SW_RESTORE = 9
PROP = "ORCA.Instance"

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_user32.SetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE)
_user32.GetPropW.restype = wintypes.HANDLE
_user32.GetPropW.argtypes = (wintypes.HWND, wintypes.LPCWSTR)
_user32.IsWindowVisible.argtypes = (wintypes.HWND,)
_user32.IsIconic.argtypes = (wintypes.HWND,)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SwitchToThisWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
_user32.GetParent.restype = wintypes.HWND
_user32.GetParent.argtypes = (wintypes.HWND,)
_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = (_ENUM, wintypes.LPARAM)

_lock = None  # the mutex handle, held for the life of the process


def folder():
    """The ADMIN folder (as routing.app_dir: next to the .exe when packaged)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _digest():
    return hashlib.sha1(str(folder()).lower().encode("utf-8")).hexdigest()


def mutex_name():
    return f"Local\\ORCA-{_digest()[:12]}"


def tag():
    """The window property value: the same folder gives the same number (never 0)."""
    return int(_digest()[:7], 16) | 1


def acquire():
    """Take the lock. False when another ORCA (for this ADMIN folder) already holds it."""
    global _lock
    if _lock is not None:
        return True
    handle = _kernel32.CreateMutexW(None, False, mutex_name())
    if not handle:
        return True  # Windows refused to make it: never block ORCA over the lock itself
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _lock = handle
    return True


def running():
    """True while an ORCA for this folder holds the lock (nothing is taken or changed)."""
    handle = _kernel32.OpenMutexW(SYNCHRONIZE, False, mutex_name())
    if handle:
        _kernel32.CloseHandle(handle)
        return True
    return False


def mark(window):
    """Give a Tk window ORCA's property, so a second start can find it."""
    try:
        hwnd = _user32.GetParent(window.winfo_id()) or window.winfo_id()
        _user32.SetPropW(hwnd, PROP, tag())
    except Exception:
        pass


def find_window():
    """The running ORCA's window to show: the topmost visible one carrying the property, else a minimised one."""
    want = tag()
    found = []

    def each(hwnd, _):
        if (_user32.GetPropW(hwnd, PROP) or 0) == want and _user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    _user32.EnumWindows(_ENUM(each), 0)  # top to bottom
    normal = [h for h in found if not _user32.IsIconic(h)]
    return (normal or found or [None])[0]


def bring_to_front():
    """Show the running ORCA (restored if minimised). False when its window can't be found."""
    hwnd = find_window()
    if hwnd is None:
        return False
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    if _user32.GetForegroundWindow() != hwnd:
        # Windows keeps the front for the window in use unless the user started this; this switch (as Alt+Tab)
        # is usually allowed where SetForegroundWindow is not.
        _user32.SwitchToThisWindow(hwnd, True)
    return True


def second_start():
    """What a second ORCA does instead of opening: bring the first to the front, or say it is open."""
    if not bring_to_front():
        _user32.MessageBoxW(None, "ORCA is already open.", "ORCA", 0x40 | 0x10000)  # information, foreground


if __name__ == "__main__":
    sys.exit(1 if running() else 0)
