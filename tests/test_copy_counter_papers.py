"""Handoff 2026-11-19_02: the copy counter's papers are given at Finish, the same panel on every copier. Temp copy
of the folder layout; the copiers are pretend readings (page fixtures); the receipt printer faked; pictures of ORCA's
own window only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, json, os, shutil, sys, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
ADMIN.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico"):
    shutil.copyfile(APP / f, ADMIN / f)
import price_sheet as ps
ps.test_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")  # A4 B&W 0.10, plain A4 0.02, others 0.20
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, copier_queue, copy_counter as cc, counter_page as cp, driverprint, jobs, mainmenu, printing, toners
import walkin_orders as wo, walkin_prices as wp, walkin_screens as ws
import page_fixtures as F
from tkinter import messagebox, ttk
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append(str(pdf))
toners.TIMEOUT = 0.2
messagebox.askyesno = lambda *a, **k: True
messagebox.showwarning = lambda **k: None
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


def reading(bw=(0, 0, 0, 0), fc=(0, 0, 0, 0), total=0):
    """A sheets reading: Copier (s_a3, s_other, d_a3, d_other) per colour, on top of fixed numbers."""
    base_bw, base_fc = (512, 83021, 306, 71500), (1247, 6100, 80, 3200)
    b = [x + y for x, y in zip(base_bw, bw)]
    f = [x + y for x, y in zip(base_fc, fc)]
    return cc.from_page(cp.parse(F.c4510_raw(656415 + total, bw=(0, (b[0], b[1]), (b[2], b[3])),
                                             fc=(0, (f[0], f[1]), (f[2], f[3])))))


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
MM = menu.copy_counter
READ = {"C4510": reading()}
MM.read_func = lambda pid: READ[pid]


def pump(secs=0.3, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def texts(w):
    return [x.cget("text") for x in widgets(w) if x.winfo_class() in ("TLabel", "TButton", "TRadiobutton")]


def button(w, text):
    return [b for b in widgets(w, "TButton") if b.cget("text") == text][0]


def finish(pid):
    S.finish(pid); pump(0.2)
    pump(8, until=lambda: pid not in S.finishing)
    pump(0.3)


cc.STABLE_SECONDS = 0  # Finish reads until it stands still: no waiting in the test
S = ws.CopyCounterScreen(menu, on_back=lambda: None)
S.win.geometry("1500x1000+10+10"); pump(0.5)

# ------------------------------------------------------------------ the panel while counting: the same everywhere
S.start("C4510"); pump(0.2)
panel = S.panels["C4510"]
c = MM.counters["C4510"]
READ["C4510"] = reading(bw=(0, 6, 0, 14))  # 6 one side + 14 both sides = 34 A4 B&W copies on 20 sheets
c.poll(); S.refresh_live("C4510"); pump(0.2)
t = texts(panel)
check("counting: no paper drop-down and no copy type, size or sides buttons",
      not widgets(panel, "TCombobox")[:0] and not [x for x in widgets(panel, "TCombobox") if x.cget("values")
                                                   and "Smooth white 80 gsm" in x.cget("values")]
      and not widgets(panel, "TRadiobutton"), t)
check("…a running line of what the copier counted: “A4 B&W 34 prints, on 20 A4 sheets”",
      "A4 B&W 34 prints, on 20 A4 sheets" in t, t)
check("…the extras, the running total, Finish and Cancel are there",
      "Extra:" in t and any(x.startswith("Total:") for x in t) and "Finish" in t and "Cancel" in t)
window_shot.shot(S.win, OUT / "panel_counting.png")

# ------------------------------------------------------------------ one paper: no extra click
finish("C4510")
t = texts(panel)
check("Finish: “Paper used” with one block, “A4: 20 sheets”, All on one paper, Smooth white 80 gsm preselected",
      "Paper used" in t and "A4: 20 sheets" in t and c.plan("A4")["split"] is False
      and c.paper_rows("A4") == [("Smooth white 80 gsm", 20)], t)
p = c.priced()
check("…priced with no extra click: 34 x 0.10 = 3.40 and 20 Smooth white 80 A4 sheets x 0.02 = 0.40",
      p["lines"] == [("A4 B&W: 34 prints", 3.4), ("Smooth white 80 gsm: 20 A4 sheets", 0.4)] and not p["problems"], p)
check("…“20 of 20 A4 sheets given”, Print receipt and Done enabled", "20 of 20 A4 sheets given" in t
      and button(panel, "Done").instate(["!disabled"]) and button(panel, "Print receipt").instate(["!disabled"]))
k = len(wo.read_sales())
S.done("C4510"); pump(0.2)
sale = wo.read_sales()[-1]
check("…Done writes the sale", len(wo.read_sales()) == k + 1 and sale["items"] == "A4 B&W x 34" and sale["paid"] == "3.80",
      sale)

# ------------------------------------------------------------------ Tesla's case: two papers
READ["C4510"] = reading()
S.start("C4510"); pump(0.2)
c = MM.counters["C4510"]
READ["C4510"] = reading(bw=(0, 20, 0, 0))
c.poll()
finish("C4510")
S.paper_set("C4510", "A4", 0, "Smooth white 100 gsm")
S.paper_mode("C4510", "A4", True, "Silk 200 gsm"); pump(0.2)
entry = [e for e in widgets(panel, "TEntry") if e.winfo_ismapped()][-1]
entry.delete(0, "end"); entry.insert(0, "10"); pump(0.2)
t = texts(panel)
check("Different papers: Silk 200 gsm 10, the first row (Smooth white 100 gsm) fills itself with 10",
      c.paper_rows("A4") == [("Smooth white 100 gsm", 10), ("Silk 200 gsm", 10)] and "10" in t
      and "20 of 20 A4 sheets given" in t, (c.paper_rows("A4"), t))
p = c.priced()
check("…the total uses both paper prices (20 x 0.10 + 10 x 0.20 + 10 x 0.20 = 6.00)",
      ("Smooth white 100 gsm: 10 A4 sheets", 2.0) in p["lines"] and ("Silk 200 gsm: 10 A4 sheets", 2.0) in p["lines"]
      and p["total"] == 6.0, p)
window_shot.shot(S.win, OUT / "paper_used_two_papers.png")
header, rows, total = cc.receipt_rows(c, p, prices_on=False)
check("…the receipt lists the copies and both papers, no money",
      [r[0] for r in rows] == ["A4 B&W: 20 prints", "Smooth white 100 gsm: 10 A4 sheets", "Silk 200 gsm: 10 A4 sheets"]
      and all(r[1] == "" for r in rows) and total is None, rows)
entry.delete(0, "end"); entry.insert(0, "22"); pump(0.2)
t = texts(panel)
red = [x for x in widgets(panel, "TLabel") if x.cget("text") == "22 of 20 A4 sheets given"]
check("not adding up: “22 of 20 A4 sheets given” in red, Print receipt and Done disabled",
      red and str(red[0].cget("style")).endswith("Bad.TLabel") and button(panel, "Done").instate(["disabled"])
      and button(panel, "Print receipt").instate(["disabled"]), t)
entry.delete(0, "end"); entry.insert(0, "10"); pump(0.2)
check("…fixing it enables them again", button(panel, "Done").instate(["!disabled"])
      and button(panel, "Print receipt").instate(["!disabled"]))

# ------------------------------------------------------------------ restart mid-paper, back to counting
M2 = cc.Manager(rules, read_func=lambda pid: READ[pid])
check("restart mid-paper: the count and the papers given come back",
      M2.counters["C4510"].data["finished"] and M2.counters["C4510"].paper_rows("A4") == c.paper_rows("A4"))
S.back_to_counting("C4510"); pump(0.2)
check("Back to counting reopens it (the paper typed is kept)", not c.data["finished"] and "Finish" in texts(panel)
      and c.plan("A4")["rows"][1] == ["Silk 200 gsm", 10])
READ["C4510"] = reading(bw=(0, 26, 0, 0), fc=(2, 0, 0, 0))  # 6 more A4 B&W and 2 A3 colour
c.poll()
M3 = cc.Manager(rules, read_func=lambda pid: READ[pid])
check("restart mid-count: the count comes back", not M3.counters["C4510"].data["finished"]
      and M3.counters["C4510"].running_text() == c.running_text(), c.running_text())
finish("C4510")
t = texts(panel)
check("Finish again: the blocks grow (A4: 26 sheets) and the typed row is kept; the first row takes 16",
      "A4: 26 sheets" in t and c.paper_rows("A4") == [("Smooth white 100 gsm", 16), ("Silk 200 gsm", 10)], t)
check("A4 and A3 in one count: two blocks, each adding up on its own",
      "A3: 2 sheets" in t and "2 of 2 A3 sheets given" in t and "26 of 26 A4 sheets given" in t)
p = c.priced()
check("…priced by size and colour, the A3 sheets on Smooth white 80 (A3 0.04)",
      ("A4 B&W: 26 prints", 2.6) in p["lines"] and ("A3 colour: 2 prints", 1.2) in p["lines"]
      and ("Smooth white 80 gsm: 2 A3 sheets", 0.08) in p["lines"], p["lines"])
before = len(list(csv.reader(open(ADMIN / jobs.LOG_FILE, encoding="utf-8-sig"))))
S.done("C4510"); pump(0.2)
rows = list(csv.reader(open(ADMIN / jobs.LOG_FILE, encoding="utf-8-sig")))[before:]
log = [(r[6], r[4], r[2], r[12], r[-1]) for r in rows]
check("print_log.csv: one line per size and colour, split by the sheets given (16 + 10 A4, 2 A3)",
      log == [("A4", "bw", "16", "16", "Smooth white 100 gsm"), ("A4", "bw", "10", "10", "Silk 200 gsm"),
              ("A3", "color", "2", "2", "Smooth white 80 gsm")], log)
check("…split lines where copies aren't exact add up (both sides: 5 sheets 10 copies over 3 + 2)",
      cc.log_lines([{"type": "A4 B&W", "sides": "double", "copies": 10, "sheets": 5}],
                   {"A4": [("Silk 200 gsm", 3), ("Gloss 130 gsm", 2)]})
      == [("A4", "bw", 6, 3, "double", "Silk 200 gsm"), ("A4", "bw", 4, 2, "double", "Gloss 130 gsm")])

# ------------------------------------------------------------------ fallback and C3004 mode
READ["C3004"] = cc.from_page(cp.parse(F.c3004()))
S.start("C3004"); pump(0.2)
p3 = S.panels["C3004"]
c3 = MM.counters["C3004"]
check("MP C3004 mode: the size and sides buttons remain, no paper while counting",
      [x.cget("text") for x in widgets(p3, "TRadiobutton")] == ["A4", "A3", "One side", "Both sides"]
      and not widgets(p3, "TCombobox")[1:], texts(p3))
READ["C3004"] = cc.from_page(cp.parse(F.c3004(bw=318005, fc=49921)))
c3.poll(); finish("C3004")
check("…the paper is given at Finish: A4: 5 sheets (3 B&W + 2 colour copies, one side)",
      "A4: 5 sheets" in texts(p3) and c3.paper_rows("A4") == [("Smooth white 80 gsm", 5)], texts(p3))
MM.cancel("C3004")
READ["C3000"] = {"how": "total", "total": 1000}
S.start("C3000"); pump(0.2)
p0 = S.panels["C3000"]
check("fallback: the type buttons remain (with its yellow line), no paper while counting",
      cc.FALLBACK_TEXT in texts(p0) and "A3 colour" in [x.cget("text") for x in widgets(p0, "TRadiobutton")]
      and not [x for x in widgets(p0, "TCombobox") if "Smooth white 80 gsm" in x.cget("values")])
READ["C3000"] = {"how": "total", "total": 1012}
MM.counters["C3000"].poll(); finish("C3000")
check("…and the paper is given at Finish", "A4: 12 sheets" in texts(p0) and "Paper used" in texts(p0), texts(p0))
MM.cancel("C3000")

# ------------------------------------------------------------------ an old saved count with its paper
old = {"copier": "C3000", "mode": "counter", "how": "total", "start": {"how": "total", "total": 100},
       "last": {"how": "total", "total": 100}, "current": {"type": "A4 B&W", "paper": "Silk 200 gsm", "sides": "single"},
       "segments": [{"type": "A4 B&W", "paper": "Silk 200 gsm", "sides": "single", "copies": 5, "group": 1}],
       "extras": [], "rounding": None, "finished": True, "started": "2026-11-18T10:00:00"}
cc.save_all({"C3000": old})
M4 = cc.Manager(rules, read_func=lambda pid: READ[pid])
po = M4.counters["C3000"].priced()
check("an old saved count whose segments name their paper still finishes: priced on that paper, nothing to give",
      po["lines"] == [("A4 B&W: 5 prints", 0.5), ("Silk 200 gsm: 5 A4 sheets", 1.0)] and not po["problems"]
      and M4.counters["C3000"].sheet_totals() == {}, po)
print(f"{sum(results)}/{len(results)} passed")
