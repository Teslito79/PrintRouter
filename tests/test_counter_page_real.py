"""Handoff 2026-11-24_03: the copy counter reads the IM C4510's real counter page (saved at work before and after
1 A4 one side, 1 A3 one side and 1 A4 both sides). Temp copy of the folder layout; readings faked from the two real
pages; the receipt printer faked; pictures of ORCA's own window only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, json, os, shutil, sys, time, tkinter as tk
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
ps.test_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, copier_queue, copy_counter as cc, counter_page as cp, driverprint, mainmenu, printing, toners
import walkin_screens as ws
import page_fixtures as F
from tkinter import messagebox
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


PAGES = helpers.COUNTER_PAGES
before_html = (PAGES / "IM-C4510_before.html").read_text(encoding="utf-8", errors="replace")
after_html = (PAGES / "IM-C4510_after.html").read_text(encoding="utf-8", errors="replace")
work = APP / "work" / "reports" / "W03"
check("the fixtures are exact copies of the pages saved at work (the originals stay in work\\reports\\W03)",
      (work / "before_C4510.html").read_bytes() == (PAGES / "IM-C4510_before.html").read_bytes()
      and (work / "after_C4510.html").read_bytes() == (PAGES / "IM-C4510_after.html").read_bytes())

# ------------------------------------------------------------------ parsing the real page
after = cp.parse(after_html)
before = cp.parse(before_html)
bw, fc = after["sections"]["Copier"]["bw"], after["sections"]["Copier"]["color"]
check("Copier B&W: simplex A3 5392, Others 84380; duplex A3 1055, Others 65433",
      bw["simplex"]["A3/DLT"] == 5392 and bw["simplex"]["Others"] == 84380
      and bw["duplex"]["A3/DLT"] == 1055 and bw["duplex"]["Others"] == 65433, bw)
check("Copier Full Color: simplex 1267 / 7547, duplex 77 / 1946",
      (fc["simplex"]["A3/DLT"], fc["simplex"]["Others"], fc["duplex"]["A3/DLT"], fc["duplex"]["Others"])
      == (1267, 7547, 77, 1946), fc)
check("the row totals are kept (B&W 230250, colour 14281) and Total Counter 664957",
      bw["total"] == 230250 and fc["total"] == 14281 and after["total"] == 664957)
tot = after["sections"]["Total"]
check("the Total section parses the same way (B&W simplex 13606 / 205228, duplex 1239 / 163110)",
      (tot["bw"]["simplex"]["A3/DLT"], tot["bw"]["simplex"]["Others"], tot["bw"]["duplex"]["A3/DLT"],
       tot["bw"]["duplex"]["Others"]) == (13606, 205228, 1239, 163110), tot["bw"])
pr = after["sections"]["Printer"]
check("the Printer section too (B&W simplex 8214 / 120848, duplex 184 / 97677; Two-color 54 / 135, 0 / 11)",
      (pr["bw"]["simplex"]["A3/DLT"], pr["bw"]["duplex"]["Others"], pr["two"]["simplex"]["Others"],
       pr["two"]["duplex"]["Others"]) == (8214, 97677, 135, 11), pr["bw"])
check("Other Function(s): A3/DLT 27794, Duplex 170553, Banner 0",
      after["other"] == {"A3/DLT": 27794, "Duplex": 170553, "Banner": 0}, after["other"])
check("sheet_split isn't None, and from_page says \"sheets\"",
      cp.sheet_split(after) is not None and cc.from_page(after)["how"] == "sheets", cc.from_page(after)["how"])
check("Settings' Check address would say “Counter page: detailed (sheets)”",
      cc.HOW_TEXT[cc.how_of(cc.from_page(after))] == "Counter page: detailed (sheets)")

# the old 2026-11-18_01 layout (side words next to the numbers) parses as before
old = cp.parse(F.c4510_raw(656415, bw=(318002, (512, 83021), (306, 71500)), fc=(17000, (1247, 6100), (80, 3200))))
ob = old["sections"]["Copier"]["bw"]
check("the old fixtures' layout still parses the same way",
      ob == {"total": 318002, "simplex": {"A3/DLT": 512, "Others": 83021, "Banner": 0},
             "duplex": {"A3/DLT": 306, "Others": 71500, "Banner": 0}}
      or (ob["simplex"]["A3/DLT"], ob["simplex"]["Others"], ob["duplex"]["A3/DLT"], ob["duplex"]["Others"])
      == (512, 83021, 306, 71500), ob)

# ------------------------------------------------------------------ the Data screen
counts = cp.toner_counts(after)
check("the Data screen's black / colour counts (27_01): the Copier + Printer row totals, A3 = 2: 563616 / 101341",
      counts == (563616, 101341), counts)

# ------------------------------------------------------------------ before -> after through the Counter
root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
MM = menu.copy_counter
READ = {"C4510": cc.from_page(before)}
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


cc.STABLE_SECONDS = 0
S = ws.CopyCounterScreen(menu, on_back=lambda: None)
S.win.geometry("1500x1000+10+10"); pump(0.5)
S.start("C4510"); pump(0.2)
c = MM.counters["C4510"]
panel = S.panels["C4510"]
check("the IM C4510 counts in sheets mode, and the copier is not held",
      c.data["mode"] == "counter" and cc.how_of(c.data["start"]) == "sheets" and "C4510" not in copier_queue.HELD,
      (c.data["mode"], copier_queue.HELD))
READ["C4510"] = cc.from_page(after)
c.poll(); S.refresh_live("C4510"); pump(0.3)
t = texts(panel)
counted = {e["type"]: e for e in c.counted(c.data["last"])} if hasattr(c, "counted") else {}
check("the running line: “A4 B&W 3, A3 B&W 1 prints, on 2 A4 + 1 A3 sheets”",
      "A4 B&W 3, A3 B&W 1 prints, on 2 A4 + 1 A3 sheets" in t, [x for x in t if "print" in x])
check("…no A4 / A3, sides or copy type buttons, and no paper drop-down while counting",
      not widgets(panel, "TRadiobutton") and not [x for x in widgets(panel, "TCombobox") if x.winfo_ismapped() and "Smooth white 80 gsm" in x.cget("values")]
      and not [x for x in t if x in ("A4", "A3", "One side", "Both sides", "A4 B&W", "A3 B&W")], t)
check("…no colour counted", "colour" not in c.running_text(), c.running_text())
window_shot.shot(S.win, OUT / "c4510_counting_real_page.png")

S.finish("C4510"); pump(0.2)
pump(8, until=lambda: "C4510" not in S.finishing); pump(0.3)
t = texts(panel)
check("Finish: Paper used, “A4: 2 sheets” and “A3: 1 sheet”, Smooth white 80 gsm preselected",
      "Paper used" in t and "A4: 2 sheets" in t and "A3: 1 sheet" in t
      and c.paper_rows("A4") == [("Smooth white 80 gsm", 2)] and c.paper_rows("A3") == [("Smooth white 80 gsm", 1)], t)
p = c.priced()
check("…priced as prints: “A4 B&W: 3 prints”, “A3 B&W: 1 print”",
      [x for x, _ in p["lines"]][:2] == ["A4 B&W: 3 prints", "A3 B&W: 1 print"], p["lines"])
window_shot.shot(S.win, OUT / "c4510_paper_used.png")
header, rows, total = cc.receipt_rows(c, p, False)
check("the receipt (no money) says “A4 B&W: 3 prints”, “A3 B&W: 1 print”",
      [r[0] for r in rows][:2] == ["A4 B&W: 3 prints", "A3 B&W: 1 print"] and total is None, rows)
S.cancel("C4510") if hasattr(S, "cancel") else None
pump(0.3)
check("Cancel throws the count away, and the copier was never held",
      "C4510" not in MM.counters and "C4510" not in copier_queue.HELD, list(MM.counters))

print(f"{sum(results)} of {len(results)} passed")
