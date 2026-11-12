"""Finished Orders cleanup: each order folder goes to the Recycle Bin 8 days after Ready for courier.

move_finished writes finished.txt (the local time, ISO) into the moved folder. At app start and then
every hour, a background thread looks at every folder directly inside Finished Orders whose name starts
with "PH-":
- finished.txt 8 full days (192 hours) or more ago: sent to the Recycle Bin (never deleted for good);
- no finished.txt, or one that can't be read: one is written with the current time; never deleted on
  the same run.
Anything else in Finished Orders is left alone. Pending Orders and Orders are never touched.
A folder that can't be deleted (a file is open) is skipped and tried again at the next run.
Every deletion and failure is logged in cleanup_log.txt (gitignored).
"""
import ctypes
import datetime
import threading
from ctypes import wintypes
from pathlib import Path

import orders
import routing

FINISHED_TXT = "finished.txt"
LOG_FILE = "cleanup_log.txt"
KEEP = datetime.timedelta(hours=192)  # 8 full days after Ready for courier
EVERY = 3600  # seconds between runs while the app is open


def now():
    return datetime.datetime.now().replace(microsecond=0)


def write_finished(folder, when=None):
    """Write finished.txt (one line, local time ISO) into an order folder. True if written."""
    try:
        (Path(folder) / FINISHED_TXT).write_text((when or now()).isoformat() + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def read_finished(folder):
    """The time in finished.txt, or None if it is missing or can't be read."""
    try:
        text = (Path(folder) / FINISHED_TXT).read_text(encoding="utf-8-sig").strip()
        return datetime.datetime.fromisoformat(text).replace(tzinfo=None)
    except (OSError, ValueError):
        return None


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def recycle(path):
    """Send a folder to the Recycle Bin, silently. Returns None if done, else the reason it wasn't."""
    op = _SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = str(Path(path).resolve()) + "\0"  # the list must end with two NULs (one added by ctypes)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result:
        return f"Windows error {result:#x}"
    if op.fAnyOperationsAborted:
        return "aborted"
    if Path(path).exists():  # a file was open: part may be left
        return "still there (a file is open?)"
    return None


def log(path, name, text):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{now():%Y-%m-%d %H:%M:%S}  {name}  {text}\n")
    except OSError:
        pass  # the log must never stop the cleanup


def run_once(finished_dir, log_path, when=None):
    """One look at Finished Orders. Returns the names of the folders sent to the Recycle Bin."""
    when = when or now()
    deleted = []
    try:
        folders = sorted(p for p in Path(finished_dir).iterdir() if p.is_dir() and p.name.startswith("PH-"))
    except OSError:
        return deleted
    for folder in folders:
        at = read_finished(folder)
        if at is None:
            if not write_finished(folder, when):
                log(log_path, folder.name, f"failed: can't write {FINISHED_TXT}")
            continue
        if when - at < KEEP:
            continue
        why = recycle(folder)
        if why is None:
            deleted.append(folder.name)
            log(log_path, folder.name, f"deleted (to the Recycle Bin), finished {at:%Y-%m-%d %H:%M}")
        else:
            log(log_path, folder.name, f"failed to delete, will try again: {why}")
    return deleted


def start(rules):
    """Run at app start and then every hour, on a background thread."""
    finished = orders.finished_dir(rules)
    log_path = routing.app_dir() / LOG_FILE
    stop = threading.Event()

    def loop():
        while True:
            try:
                run_once(finished, log_path)
            except Exception as e:  # never let the thread die
                log(log_path, "-", f"failed: {e}")
            if stop.wait(EVERY):
                return

    threading.Thread(target=loop, daemon=True).start()
    return stop
