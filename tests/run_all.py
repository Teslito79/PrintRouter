"""Run every ORCA test, one after another: py -3.14 tests\\run_all.py [--slow] [name ...]

Prints one line per file ("copy counter: 39/39") and a total; the exit code is 0 only if everything passed. Each test
runs in its own process with a time limit, in its own temp folder (tests\\helpers.py). Before and after, the real
ADMIN folder's local files (the gitignored ones: settings, inventory, toners, logs, Walk-in, ...) are listed with sizes
and times: any change is reported as a failure. --slow also runs tests\\slow\\ (the one-ORCA test starts real ORCA
processes). Names limit the run: run_all.py copy_counter inventory.
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent
LIMIT = 420  # seconds per file


def label(path):
    return path.stem.removeprefix("test_").replace("_", " ")


def local_files():
    """{path: (size, mtime)} of ADMIN's local (gitignored) files and the walk-in folders next to it."""
    out = {}
    try:
        names = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard"], cwd=APP,
                               capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    except OSError:
        names = []
    for n in names:
        if n.startswith(("__pycache__", "tests/")) or "/__pycache__/" in n:
            continue
        p = APP / n
        try:
            st = p.stat()
            out[n] = (st.st_size, st.st_mtime_ns)
        except OSError:
            pass
    walkin = APP.parent / "Walk-in"
    if walkin.is_dir():
        for p in walkin.rglob("*"):
            if p.is_file():
                st = p.stat()
                out[str(p)] = (st.st_size, st.st_mtime_ns)
    return out


def counts(text):
    """(passed, total) from a test's output: its "n/m passed" / "n of m passed" line, else its PASS / FAIL lines."""
    m = re.findall(r"(\d+)\s*(?:/|of)\s*(\d+)\s*passed", text)
    passes = len(re.findall(r"^PASS", text, re.M))
    fails = len(re.findall(r"^FAIL", text, re.M))
    if m:
        a, b = map(int, m[-1])
        return a, b, fails
    if not passes and not fails and re.search(r"^ALL OK", text, re.M):  # older tests print only "ALL OK"
        return 1, 1, 0
    return passes, passes + fails, fails


def python_processes():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {line.split('","')[1] for line in out.splitlines()
            if line.lower().startswith(('"python', '"py.exe', '"pythonw'))}


def main(argv):
    slow = "--slow" in argv
    names = [a for a in argv if not a.startswith("--")]
    files = sorted(TESTS.glob("test_*.py"))
    if slow:
        files += sorted((TESTS / "slow").glob("test_*.py"))
    if names:
        files = [f for f in files if any(n in f.stem for n in names)]
    before = local_files()
    procs_before = python_processes()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_SHOTS=os.environ.get("NO_SHOTS", "1"))
    total_ok = total = 0
    bad = []
    logs = Path(os.environ.get("TEMP", ".")) / "ORCA-tests" / "_logs"
    logs.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for f in files:
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable, "-u", str(f)], cwd=APP, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=LIMIT)
            text, code = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:
            text = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) \
                + f"\nTIMEOUT after {LIMIT} s"
            code = -1
        (logs / f"{f.stem}.txt").write_text(text, encoding="utf-8")
        ok, n, fails = counts(text)
        crashed = code != 0 and "Traceback" in text
        skipped = code == 0 and not fails and re.search(r"^SKIPPED: (.*)$", text, re.M)
        if skipped and n == 0:
            print(f"{label(f)}: skipped ({skipped.group(1)})", flush=True)
            continue
        good = n > 0 and ok == n and not fails and code == 0
        total_ok += ok
        total += n
        tail = "" if good else ("  crashed: " + text.strip().splitlines()[-1][:150] if crashed or code == -1
                                else "  failing: " + "; ".join(l[5:90] for l in text.splitlines()
                                                                if l.startswith("FAIL"))[:300])
        print(f"{label(f)}: {ok}/{n}  ({time.time() - t0:.0f} s){tail}", flush=True)
        if not good:
            bad.append(label(f))
    after = local_files()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    left = python_processes() - procs_before - {str(os.getpid())}
    print(f"\nTotal: {total_ok}/{total} checks, {len(files) - len(bad)}/{len(files)} files all green "
          f"({(time.time() - start) / 60:.1f} min). Logs: {logs}")
    if changed:
        print("FAIL safety: ADMIN's local files changed: " + ", ".join(changed[:10]))
    else:
        print("Safety: ADMIN's local files are unchanged.")
    if left:
        print(f"FAIL safety: {len(left)} Python process(es) left running: {', '.join(sorted(left))}")
    else:
        print("Safety: no Python processes left running.")
    if bad:
        print("Not all green: " + ", ".join(bad))
    return 0 if not bad and not changed and not left else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
