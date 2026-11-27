"""Handoff 2026-11-27_01: spare toners that fit more than one copier, and the Data screen's counts from the row
totals. A temp folder, no copiers (nothing is read); pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, datetime, json, os, shutil, subprocess, sys, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
routing.app_dir = lambda: TMP
import toners, theme, costs, counter_page as cp, copy_counter as cc
from tkinter import messagebox, ttk
import window_shot

rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
P = rules["printers"]
results = []
asked = []
ANSWERS = []
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message")) or (ANSWERS.pop(0) if ANSWERS else True)


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


def stock():
    return toners.load_stock(P)


def by_name(name):
    return next(t for t in stock()["toners"] if t["name"] == name)


T0 = datetime.datetime(2026, 11, 27, 9, 0)

# ------------------------------------------------------------------ moving an old file
old = {"saved": True, "copiers": {"C4510": {"black": {"count": 2, "min": 1}, "cyan": {"count": 1, "min": 1}},
                                  "C3000": {"black": {"count": 1, "min": 1}}}, "taken": []}
(TMP / "toner_stock.json").write_text(json.dumps(old), encoding="utf-8")
with open(TMP / "toner_stock_log.csv", "w", newline="", encoding="utf-8-sig") as f:  # an old log, 6 columns
    w = csv.writer(f)
    w.writerow(["time", "copier", "colour", "change", "new count", "reason"])
    w.writerow(["2026-11-20 10:00:00", "C4510", "black", "+2", "2", "added"])
s1 = stock()
check("an old file moves: C4510 black 2 / min 1 and C3000 black 1 become two toners with those counts",
      by_name("IM C4510 black")["count"] == 2 and by_name("IM C4510 black")["min"] == 1
      and by_name("IM C3000 black")["count"] == 1 and len(s1["toners"]) == 12,
      [(t["name"], t["count"]) for t in s1["toners"]][:5])
check("…a copy of the old file is kept as toner_stock.before-shared.json",
      json.loads((TMP / "toner_stock.before-shared.json").read_text(encoding="utf-8")) == old)
before = (TMP / "toner_stock.json").read_text(encoding="utf-8")
s2 = stock()
check("…loading twice changes nothing", s1 == s2 and (TMP / "toner_stock.json").read_text(encoding="utf-8") == before)
check("…nothing changes for staff: each copier line shows its own count",
      toners.spare_text(P, s2, "C4510", "black") == ("Spare: 2", "")
      and toners.spare_text(P, s2, "C3000", "black") == ("Spare: 1", "Order more"),
      (toners.spare_text(P, s2, "C4510", "black"), toners.spare_text(P, s2, "C3000", "black")))

# ------------------------------------------------------------------ the window: joining C3000 black into C4510 black
root = tk.Tk(); root.withdraw(); theme.apply(root)
watch = toners.TonerWatch(rules, timeout=0.2)
screen = toners.TonersScreen(root, rules, watch, on_back=lambda: None)
screen.win.geometry("1500x1000+10+10")


def all_w(w):
    return [w] + [c for ch in w.winfo_children() for c in all_w(ch)]


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


win = toners.SpareTonersWindow(screen)
pump()
t4510 = by_name("IM C4510 black")
ed = toners.EditTonerDialog(win, t4510["id"])
ed.ticks[("C3000", "black")].set(True)
ed.name.set("Black for IM C3000 / IM C4510")
ANSWERS[:] = [True]
asked.clear()
ed.save(); pump()
check("ticking C3000 black on the C4510 black toner asks once, with the counts",
      asked == ["IM C3000 black has its own spare toner (1 on the shelf). Join them into one? The counts are added "
                "(1 + 2 = 3)."], asked)
shared = by_name("Black for IM C3000 / IM C4510")
check("…Yes joins them: one toner, count 3, fits C4510 and C3000 black; the other is gone",
      shared["count"] == 3 and sorted(map(tuple, shared["fits"])) == [("C3000", "black"), ("C4510", "black")]
      and not any(t["name"] == "IM C3000 black" for t in stock()["toners"]), shared)
log = toners.read_stock_log()
check("…logged as joined, with the toner column; the old line still reads (toner empty)",
      log[0]["toner"] == "" and log[0]["reason"] == "added"
      and any(r["reason"].startswith("joined") and r["toner"] == "Black for IM C3000 / IM C4510" for r in log), log[-2:])
s = stock()
check("both copier lines show “Spare: 3 (shared …)”",
      toners.spare_text(P, s, "C4510", "black")[0] == "Spare: 3 (shared with IM C3000)"
      and toners.spare_text(P, s, "C3000", "black")[0] == "Spare: 3 (shared with IM C4510)",
      (toners.spare_text(P, s, "C4510", "black"), toners.spare_text(P, s, "C3000", "black")))
win.fill(); pump(0.5)
window_shot.shot(win.dlg, OUT / "spare_toners_window.png")
screen.fill(); pump(0.5)
window_shot.shot(screen.win, OUT / "data_screen_shared.png")
check("the Data screen shows it", any(isinstance(x, ttk.Label) and "shared with" in str(x.cget("text"))
                                     for x in all_w(screen.win)))

# ------------------------------------------------------------------ a change on the C3000 black takes from the shared one
why = watch.add_by_hand("C3000", "black", 1000, 800, 200, when=T0)
s = stock()
check("a change on the C3000 black takes from the shared toner (3 -> 2); both lines show 2",
      why is None and by_name("Black for IM C3000 / IM C4510")["count"] == 2
      and toners.spare_text(P, s, "C4510", "black")[0].startswith("Spare: 2")
      and toners.spare_text(P, s, "C3000", "black")[0].startswith("Spare: 2"), why)
cid = toners.read_changes()[-1]["id"]
check("…the change remembers which toner it took", s["taken"].get(cid) == shared["id"], s["taken"])
watch.remove(cid)
check("removing that change gives it back (2 -> 3)", by_name("Black for IM C3000 / IM C4510")["count"] == 3)
check("…the log names the toner on the new lines",
      [r["toner"] for r in toners.read_stock_log()[-2:]] == ["Black for IM C3000 / IM C4510"] * 2,
      toners.read_stock_log()[-2:])

# ------------------------------------------------------------------ two toners fit C4510 black: the first is used first
compat = toners.add_toner(P, "Compatible black", [["C4510", "black"]])
check("adding a second toner for C4510 black without joining is allowed (No keeps both)",
      len(toners.fitting(stock(), "C4510", "black")) == 2)
toners.set_count(P, compat, 2, "added")
toners.set_count(P, shared["id"], 1, "counted")
watch.add_by_hand("C4510", "black", 2000, 1600, 400, when=T0 + datetime.timedelta(days=2))
check("a change on the C4510 black takes from the first in the list (the original: 1 -> 0)",
      by_name("Black for IM C3000 / IM C4510")["count"] == 0 and by_name("Compatible black")["count"] == 2)
watch.add_by_hand("C4510", "black", 3000, 2600, 400, when=T0 + datetime.timedelta(days=4))
check("…at 0, the next change takes from the compatible one (2 -> 1)", by_name("Compatible black")["count"] == 1)
toners.set_count(P, shared["id"], 1, "added")
ids_now = lambda: [t["id"] for t in stock()["toners"]]
clicks = 0
while ids_now().index(compat) > ids_now().index(shared["id"]):  # Move up, one place per click
    toners.move_toner(P, compat, -1)
    clicks += 1
check(f"Move up ({clicks} clicks) puts the compatible one above the original", clicks > 0)
toners.move_toner(P, compat, +1); toners.move_toner(P, compat, -1)
check("…Move down then Move up again: back above", ids_now().index(compat) < ids_now().index(shared["id"]))
watch.add_by_hand("C4510", "black", 4000, 3600, 400, when=T0 + datetime.timedelta(days=6))
check("Move up puts the compatible one first: the next change takes from it (1 -> 0)",
      by_name("Compatible black")["count"] == 0 and by_name("Black for IM C3000 / IM C4510")["count"] == 1)

# ------------------------------------------------------------------ none left anywhere
toners.set_count(P, shared["id"], 0, "counted")
n_changes = len(toners.read_changes())
watch.add_by_hand("C4510", "black", 5000, 4600, 400, when=T0 + datetime.timedelta(days=8))
s = stock()
check("none left anywhere: the change is recorded, nothing goes below 0, and the line says None left",
      len(toners.read_changes()) == n_changes + 1 and all(t["count"] >= 0 for t in s["toners"])
      and toners.spare_text(P, s, "C4510", "black") == ("Spare: 0 (shared with IM C3000)", "None left"),
      toners.spare_text(P, s, "C4510", "black"))
toners.remove_toner(P, compat)

# ------------------------------------------------------------------ the minimum: one red dot per toner
for t in stock()["toners"]:
    toners.set_count(P, t["id"], 5, "added")
check("no toner at its minimum: no red dot", not toners.stock_low(P))
toners.set_count(P, shared["id"], 1, "counted")
low = [t for t in stock()["toners"] if t["count"] <= t["min"]]
check("a shared toner at its minimum: the red dot, once (one toner), and “Order more” in the window",
      toners.stock_low(P) and len(low) == 1 and toners.toner_status(low[0]) == "Order more", [t["name"] for t in low])
win.fill(); pump(0.3)
check("…the window shows “Order more” for it",
      any(isinstance(w, ttk.Label) and w.cget("text") == "Order more" for w in all_w(win.dlg)))

# ------------------------------------------------------------------ a toner that fits all three copiers' black
all3 = toners.add_toner(P, "Black for all three", [["C4510", "black"], ["C3000", "black"], ["C3004", "black"]])
toners.remove_toner(P, shared["id"])
toners.remove_toner(P, "C3004-black")
toners.set_count(P, all3, 4, "added")
s = stock()
check("a toner fitting all three copiers' black: every line shows its count, shared with the other two",
      toners.spare_text(P, s, "C3004", "black")[0] == "Spare: 4 (shared with IM C4510, IM C3000)"
      and toners.spare_text(P, s, "C4510", "black")[0].startswith("Spare: 4"),
      toners.spare_text(P, s, "C3004", "black"))
watch.add_by_hand("C3004", "black", 9000, 9000, 0, when=T0 + datetime.timedelta(days=10))
check("…a change on the MP C3004 takes from it (4 -> 3)", by_name("Black for all three")["count"] == 3)

# joining through a new toner (Add toner… with a tick another toner has): asks; No keeps both
ANSWERS[:] = [False]; asked.clear()
ed = toners.EditTonerDialog(win, None)
ed.name.set("Cyan test"); ed.ticks[("C4510", "cyan")].set(True)
ed.save(); pump()
check("Add toner… ticking C4510 cyan (it has its own) asks; No leaves both",
      len(asked) == 1 and len(toners.fitting(stock(), "C4510", "cyan")) == 2, asked)

# ------------------------------------------------------------------ the Data screen's counts (answer to 24_03)
after = cp.parse((helpers.COUNTER_PAGES / "IM-C4510_after.html").read_text(encoding="utf-8",
                                                                                         errors="replace"))
old_src = subprocess.run(["git", "show", "1e06c32:counter_page.py"], capture_output=True, text=True,
                         encoding="utf-8", cwd=APP).stdout
old_ns = {}
exec(compile(old_src, "counter_page_before_24_03.py", "exec"), old_ns)
old_counts = old_ns["toner_counts"](old_ns["parse"]((helpers.COUNTER_PAGES / "IM-C4510_after.html")
                                                     .read_text(encoding="utf-8", errors="replace")))
counts = cp.toner_counts(after)
check("Data counts: B&W and colour are the Copier + Printer row totals (A3 = 2): 563616 / 101341",
      counts == (230250 + 333366, 14281 + 0 + 0 + 86792 + 3 + 265), counts)
check("…the same numbers the page gave before 24_03 (the old parser, from git)", counts == old_counts,
      (counts, old_counts))
split = cp.sheet_split(after)
check("…the copy counter's sheets split is unchanged (Copier B&W 5392 / 84380 / 1055 / 65433, sheets mode)",
      split["bw"] == {"s_a3": 5392, "s_other": 84380, "d_a3": 1055, "d_other": 65433}
      and cc.from_page(after)["how"] == "sheets", split["bw"])

root.destroy()
print(f"{sum(results)} of {len(results)} passed")
