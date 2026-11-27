"""Handoff 2026-11-17_05: ORCA opens only once. Real starts (pyw app.py, ORCA.bat) in a temp clone of the repo
whose 'GitHub' is a temp bare repo one commit ahead, so a pull shows in HEAD and the reflog."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, os, shutil, subprocess, sys, time
from ctypes import wintypes
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:300])


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


helpers.remove_tree(TMP)
TMP.mkdir(parents=True)
CLONE = TMP / "ORCA" / "ADMIN"
subprocess.run(["git", "clone", "-q", "-b", "walk-in-rebuild", str(APP), str(CLONE)], check=True)
for f in ("already_open.py", "app.py", "theme.py", "ORCA.bat"):
    shutil.copyfile(APP / f, CLONE / f)
for f in ("prices.json",):
    if (APP / f).exists() and not (CLONE / f).exists():
        shutil.copyfile(APP / f, CLONE / f)
git("-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qam", "test: this handoff", cwd=CLONE)
BARE = TMP / "origin.git"
subprocess.run(["git", "clone", "-q", "--bare", str(CLONE), str(BARE)], check=True)
OTHER = TMP / "other"
subprocess.run(["git", "clone", "-q", str(BARE), str(OTHER)], check=True)
(OTHER / "pull_marker.txt").write_text("a newer commit on 'GitHub'\n")
git("add", "pull_marker.txt", cwd=OTHER)
git("-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "newer", cwd=OTHER)
git("push", "-q", "origin", "HEAD", cwd=OTHER)
git("remote", "set-url", "origin", str(BARE), cwd=CLONE)
git("fetch", "-q", "origin", cwd=CLONE)
git("branch", "-q", "--set-upstream-to=origin/walk-in-rebuild", cwd=CLONE)
git("reset", "-q", "--hard", "HEAD", cwd=CLONE)
START = git("rev-parse", "HEAD", cwd=CLONE)
NEWER = git("rev-parse", "origin/walk-in-rebuild", cwd=CLONE)
check("setup: the clone is one commit behind its 'GitHub'", START != NEWER and git("rev-list", "--count", "HEAD..origin/walk-in-rebuild", cwd=CLONE) == "1")

sys.path.insert(0, str(CLONE))
import already_open  # the clone's copy: its lock name and window mark belong to the clone's folder

u32 = ctypes.windll.user32
u32.GetForegroundWindow.restype = wintypes.HWND


def all_app_pids():
    """Every pythonw.exe running an app.py on this PC (any ORCA)."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
                          "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"], capture_output=True, text=True).stdout
    return {int(pid) for pid, _, cmd in (line.partition("|") for line in out.splitlines()) if "app.py" in cmd}


BEFORE = all_app_pids()  # an ORCA already running here (Tesla's own) is never counted, touched or ended


def orca_pids():
    """pythonw.exe processes running the clone's app.py (the pyw launcher's child): only those started by this
    test, never one that was running before it."""
    return [pid for pid in all_app_pids() if pid not in BEFORE]


def _old_orca_pids():
    """(The 2026-11-17_05 version, kept for reference: it counted every app.py.)"""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
                          "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        pid, _, cmd = line.partition("|")
        if "app.py" in cmd:
            try:
                cwd_ok = True  # the command line has no folder: count all, there was none before the test
            except Exception:
                cwd_ok = False
            if cwd_ok:
                pids.append(int(pid))
    return pids


def wait(cond, secs=25):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.25)
    return False


def start_direct():
    subprocess.Popen(["pyw", "-3.14", "app.py"], cwd=CLONE)


def run_bat():
    t = time.time()
    # The output goes to a file, not a pipe: the ORCA that ORCA.bat starts would hold a pipe open (and this wait)
    # for as long as it runs.
    out = TMP / "orca_bat_output.txt"
    with open(out, "wb") as f:
        subprocess.run(["cmd", "/c", str(CLONE / "ORCA.bat")], cwd=CLONE, stdout=f, stderr=f, stdin=subprocess.DEVNULL,
                       timeout=120)
    print("  ORCA.bat said:", out.read_text(encoding="utf-8", errors="replace").strip().replace(chr(10), " | ")[:400])
    return time.time() - t


def kill_all():
    for pid in orca_pids():
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    wait(lambda: not orca_pids() and not already_open.running(), 15)


import atexit
atexit.register(kill_all)  # even if the test stops half way, every ORCA it started is ended (18_02's leftovers)


check("no ORCA from this test is running at the start", orca_pids() == [], orca_pids())

# 1. first start
start_direct()
check("pyw app.py: ORCA opens (lock taken, its window found by the mark)",
      wait(lambda: already_open.running() and already_open.find_window()), (already_open.running(), already_open.find_window()))
time.sleep(1.5)
first = orca_pids()
check("one ORCA process", len(first) == 1, first)

# 2. ORCA.bat while it is open
secs = run_bat()
time.sleep(4)
check("ORCA.bat while ORCA is open: still one process", orca_pids() == first, orca_pids())
check("…and no pull happened (HEAD unchanged, nothing in the reflog)", git("rev-parse", "HEAD", cwd=CLONE) == START
      and "pull" not in git("reflog", "-5", cwd=CLONE), (git("reflog", "-3", cwd=CLONE), round(secs, 1)))
hwnd = already_open.find_window()
fg = u32.GetForegroundWindow()
print("   foreground is ORCA's window:", fg == hwnd, "(Windows only lets a start that the user made take the front)")

# 3. minimised, then started again
u32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
time.sleep(1)
check("setup: ORCA minimised", bool(u32.IsIconic(hwnd)))
start_direct()
check("started again while minimised: the window is restored", wait(lambda: not u32.IsIconic(hwnd), 15), u32.IsIconic(hwnd))
time.sleep(4)
check("…still one process", orca_pids() == first, orca_pids())

# 4. two direct starts at once
start_direct(); start_direct()
time.sleep(6)
check("pyw app.py twice more: still one process", orca_pids() == first, orca_pids())

# 5. ended in Task Manager (taskkill /F), then started
kill_all()
check("setup: ORCA ended by force, the lock is gone with it", not already_open.running() and not orca_pids())
start_direct()
check("started after that: it opens normally", wait(lambda: already_open.running() and already_open.find_window())
      and wait(lambda: len(orca_pids()) == 1, 10), orca_pids())
kill_all()

# 6. the running ORCA's window can't be found (still starting): one message, then exit
hold = ctypes.WinDLL("kernel32", use_last_error=True)
hold.CreateMutexW.restype = wintypes.HANDLE
hold.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
h = hold.CreateMutexW(None, False, already_open.mutex_name())  # this test holds the lock, with no ORCA window
start_direct()
u32.FindWindowW.restype = wintypes.HWND
u32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
box = None
if wait(lambda: u32.FindWindowW("#32770", "ORCA"), 15):
    box = u32.FindWindowW("#32770", "ORCA")
    buf = ctypes.create_unicode_buffer(200)
    child = u32.FindWindowExW(box, None, "Static", None) if hasattr(u32, "FindWindowExW") else None
    texts = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(c, _):
        u32.GetWindowTextW(c, buf, 200)
        texts.append(buf.value)
        return True
    end = time.time() + 5
    while time.time() < end and "ORCA is already open." not in texts:  # the box's text comes a moment after the box
        texts.clear()
        u32.EnumChildWindows(box, each, 0)
        time.sleep(0.2)
    check("lock held but no ORCA window: the message “ORCA is already open.”", "ORCA is already open." in texts, texts)
    u32.PostMessageW(box, 0x0010, 0, 0)  # WM_CLOSE: OK
else:
    check("lock held but no ORCA window: the message “ORCA is already open.”", False, "no message box")
check("…and that start exits (no ORCA process left)", wait(lambda: orca_pids() == [], 10), orca_pids())
ctypes.windll.kernel32.CloseHandle(h)

# 7. ORCA closed: ORCA.bat pulls and starts as before
check("setup: nothing holds the lock", not already_open.running())
secs = run_bat()
check("ORCA.bat with ORCA closed: it pulls (HEAD moves to the newer commit)", git("rev-parse", "HEAD", cwd=CLONE) == NEWER
      and (CLONE / "pull_marker.txt").is_file(), git("reflog", "-2", cwd=CLONE))
check("…and starts ORCA", wait(lambda: already_open.running() and already_open.find_window()) and len(orca_pids()) == 1,
      orca_pids())
kill_all()
check("clean-up: no ORCA started by this test is left running (an ORCA from before is untouched)",
      not orca_pids(), (orca_pids(), sorted(BEFORE)))
print(f"{sum(map(bool, results))}/{len(results)} passed")
