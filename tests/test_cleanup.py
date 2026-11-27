"""Finished Orders cleanup test, in a temp folder only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, json, os, shutil, sys, time, tkinter as tk
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
helpers.temp_admin(OUT / "admin")  # ORCA reads its files from a temp ADMIN, never the real one
sys.path.insert(0, str(APP)); os.chdir(APP)
import cleanup, routing

if TMP.exists():
    shutil.rmtree(TMP)
fin = TMP / ".test-finished"
fin.mkdir(parents=True)
log = TMP / "cleanup_log.txt"
now = cleanup.now()
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, info)


def make(name, age_days=None, raw=None):
    d = fin / name
    (d / "01").mkdir(parents=True)
    (d / "01" / "a.pdf").write_bytes(b"x" * 100)
    if age_days is not None:
        cleanup.write_finished(d, now - datetime.timedelta(days=age_days))
    if raw is not None:
        (d / "finished.txt").write_text(raw, encoding="utf-8")
    return d


make("PH-90001", 9)
make("PH-90002", 7)
make("PH-90003")                       # no finished.txt
make("PH-90004", raw="not a date")     # unreadable
make("PH-90005", 8, )                  # exactly 192 h -> deleted
locked = make("PH-90006", 10)
make("PH-90007 (2)", 9)                # a second copy of a number
(fin / "Keep me").mkdir()
(fin / "Keep me" / "x.txt").write_text("x")
(fin / "notes.txt").write_text("loose file")
old = make("Old-PH-90008", 30)         # not starting with PH-

held = open(locked / "01" / "a.pdf", "rb")  # a file held open
deleted = cleanup.run_once(fin, log, now)
check("9 days old -> deleted", not (fin / "PH-90001").exists() and "PH-90001" in deleted)
check("exactly 8 days (192 h) -> deleted", not (fin / "PH-90005").exists())
check("PH-90007 (2), 9 days -> deleted", not (fin / "PH-90007 (2)").exists())
check("7 days old -> kept", (fin / "PH-90002").is_dir())
t3 = cleanup.read_finished(fin / "PH-90003")
check("no finished.txt -> gets one now, kept", (fin / "PH-90003").is_dir() and t3 == now, t3)
t4 = cleanup.read_finished(fin / "PH-90004")
check("unreadable finished.txt -> rewritten now, kept", (fin / "PH-90004").is_dir() and t4 == now, t4)
check("non-PH folder and loose file untouched", (fin / "Keep me" / "x.txt").is_file() and (fin / "notes.txt").is_file()
      and old.is_dir())
check("held-open folder skipped", locked.is_dir() and "PH-90006" not in deleted)
text = log.read_text(encoding="utf-8")
check("deletions logged", all(f"{n}  deleted (to the Recycle Bin)" in text for n in ("PH-90001", "PH-90005", "PH-90007 (2)")))
check("failure logged", "PH-90006  failed to delete, will try again" in text)
held.close()
time.sleep(0.5)
deleted = cleanup.run_once(fin, log, now)
check("next run, file closed -> deleted", not locked.exists() and deleted == ["PH-90006"], deleted)
later = cleanup.run_once(fin, log, now + datetime.timedelta(days=8))
check("8 days later the folders that got finished.txt go too", sorted(later) == ["PH-90002", "PH-90003", "PH-90004"], later)
check("still untouched at the end", (fin / "Keep me").is_dir() and (fin / "notes.txt").is_file() and old.is_dir())

# move_finished writes finished.txt
import jobs, printhub
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()
num = "PH-90100"
o = TMP / "orders" / num
(o / "01").mkdir(parents=True)
(o / "order.json").write_text(json.dumps({"format": 1, "order": num, "paid_at": now.astimezone().isoformat(),
                                          "delivery": "courier", "steps": ["PRINT"], "documents": ["01"]}))
(o / "01" / "job.json").write_text(json.dumps({"format": 1, "file": "a.pdf", "pages": 1, "copies": 1, "color": "bw",
                                               "sides": "single", "paper": "A4", "per_side": 1,
                                               "paper_type": "Plain & Recycled"}))
import pypdfium2 as pdfium
pdf = pdfium.PdfDocument.new(); pdf.new_page(595, 842); pdf.save(str(o / "01" / "a.pdf")); pdf.close()
rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"), finished_folder=str(TMP / "finished"))
root = tk.Tk(); root.withdraw()
view = printhub.PrintHubView(root, rules, jobs.Jobs(rules, routing.load_json("prices.json")))
view.win.withdraw()
end = time.time() + 20
while time.time() < end and not view.orders:
    root.update(); time.sleep(0.1)
before = cleanup.now()
ok = view.move_finished(view.orders[0])
for _ in range(20):
    root.update(); time.sleep(0.05)
t = cleanup.read_finished(TMP / "finished" / num)
check("move_finished writes finished.txt", ok and t is not None and abs((t - before).total_seconds()) < 5, t)
root.destroy()
print(text)
print("ALL OK" if all(results) else "SOME FAILED")
