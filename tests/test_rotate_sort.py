"""Handoff 2026-11-19_05: Rotate sort for walk-in document items. Temp copy of the folder layout; pretend installed
printers and a faked driver (nothing reaches a copier); pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, importlib.util, json, os, shutil, subprocess, sys, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
SRC = TMP / "Desktop"
ADMIN.mkdir(parents=True); SRC.mkdir(); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules, indent=1), encoding="utf-8")
routing.app_dir = lambda: ADMIN
INSTALLED = ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6", "XP-80C"]
routing.installed_printers = lambda: list(INSTALLED)
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_prices as wp, walkin_pricing as P
import walkin_print, walkin_screens as ws, settings_screen as ss, costs
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

SENT = []
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt=None, tray=None, short_edge=False: (
    paper, color, duplex, pt, tray, copies)
driverprint.print_pdf = lambda pdf, q, devmode, name, **kw: SENT.append((q, name) + tuple(devmode))
QUEUES = {p["queue"]: pid for pid, p in rules["printers"].items()}
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
messagebox.showwarning = lambda **k: None
messagebox.askyesno = lambda *a, **k: True
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


def pdf(path, pages=1):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(595, 842)
    d.save(str(path)); d.close()
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
run = menu.print_queue


def pump(secs=0.3, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)


def idle():
    pump(15, until=lambda: not run.busy() and run.to_send.empty())
    pump(0.5)


# ------------------------------------------------------------------ the tick
q = ws.QuoteScreen(menu, "email", on_back=menu.show_menu)
q.win.geometry("1320x940+10+10"); pump(0.8)
v = q.option_vars
check("Document: a “Rotate sort” tick, usable for A4 Normal 80 gsm", q.rotate_box.instate(["!disabled"])
      and q.rotate_why.cget("text") == "")
v["rotate"].set(True); pump(0.1)
q.form.canvas.yview_moveto(1.0); pump(0.2)
window_shot.shot(q.win, OUT / "rotate_tick_on.png")
v["size"].set("A3"); pump(0.1)
check("changing the size to A3 after ticking unticks it and says why: “Rotate sort is for A4 plain paper only”",
      not v["rotate"].get() and q.rotate_box.instate(["disabled"])
      and q.rotate_why.cget("text") == "Rotate sort is for A4 plain paper only", q.rotate_why.cget("text"))
window_shot.shot(q.win, OUT / "rotate_greyed_with_reason.png")
v["size"].set("A4"); pump(0.1)
v["paper"].set("Silk 250 gsm"); pump(0.1)
check("Silk 250 greys it with the same reason", q.rotate_box.instate(["disabled"])
      and q.rotate_why.cget("text") == "Rotate sort is for A4 plain paper only")
v["paper"].set("Normal 80 gsm"); pump(0.1)
check("a non-default tray (a staff override) greys it",
      walkin_print.rotate_reason(rules, {"size": "A4", "paper": "Normal 80 gsm", "print": {"tray": "Tray 2"}})
      == "Rotate sort uses Tray 1 and Tray 4: keep the tray on Auto Tray Select")
check("no rotate-sort copier on this PC (not installed) greys it: “Rotate sort isn't set up on this PC's printers”",
      walkin_print.rotate_reason(rules, {"size": "A4", "paper": "Normal 80 gsm"}, installed=["XP-80C"])
      == "Rotate sort isn't set up on this PC's printers"
      and walkin_print.rotate_reason(dict(rules, rotate_sort={"printer": None, "trays": []}),
                                     {"size": "A4", "paper": "Normal 80 gsm"}) == "Rotate sort isn't set up on this PC's printers")

# ------------------------------------------------------------------ one item and a 10-file drop, saved
v["rotate"].set(True); v["copies"].set("5"); v["pages"].set("1")
q.held = [str(pdf(SRC / "five.pdf"))]; q.show_box()
q.add_item(); pump(0.2)
check("ticked on one item: saved on the item and shown in its line", q.items[0].get("rotate") is True
      and "Rotate sort" in P.describe(q.items[0]), P.describe(q.items[0]))
files = [pdf(SRC / f"set_{k:02d}.pdf") for k in range(1, 11)]
q.held = [str(f) for f in files]; q.show_box()
q.option_vars["rotate"].set(True); q.option_vars["copies"].set("1")
q.add_item(); pump(0.2)
check("ticked on a 10-file drop: every item made from them has it", len(q.items) == 11
      and all(it.get("rotate") for it in q.items[1:]))
q.cust_vars["name"].set("Rota Test"); q.cust_vars["phone"].set("99 555 666"); pump(0.2)
q.place(); pump(3)
order = wo.load_order(wo.open_dir() / f"#{q.placed_number}")
check("reopening the order keeps it (order.json and Details… show it)",
      all(it.get("rotate") for it in order["items"]) and all("Rotate sort" in it["description"] for it in order["items"]))
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w.title() == "ORCA - order placed":
        w.destroy()
q.back(); pump(0.3)

# ------------------------------------------------------------------ printing: the trays alternate
pump(8, until=lambda: all(wo.item_file(order, it) for it in order["items"]))
orders = [wo.refresh(o) for o in wo.list_open()]
for _ in range(60):
    run.update([wo.refresh(o) for o in wo.list_open()]); pump(0.3)
    if isinstance(run.plans.get(order["number"]), tuple):
        break
SENT.clear()
run.start_printing(); idle()
jobs_ = [(QUEUES.get(s[0], s[0]), s[1], s[6]) for s in SENT if "Cover sheet" not in s[1]]
five = [j for j in jobs_ if " 1 Document A4" in j[1]]  # item 1 (not item 11)
sets = [j for j in jobs_ if " 1 Document A4" not in j[1]]
trays = [j[2] for j in jobs_]
check("one file, 5 copies: 5 jobs on the IM C4510, alternating Tray 1 / Tray 4",
      len(five) == 5 and all(j[0] == "C4510" for j in five) and [j[2] for j in five] == ["Tray 1", "Tray 4"] * 2 + ["Tray 1"],
      five)
check("10 one-copy files: 10 jobs on the IM C4510, and the alternation goes on from file to file (one rotation for "
      "the whole batch)", len(sets) == 10 and all(j[0] == "C4510" for j in sets)
      and trays == (["Tray 1", "Tray 4"] * 8)[:15], trays)
check("B&W items (here all B&W) go to the IM C4510 with Rotate sort", all(j[0] == "C4510" for j in jobs_))

# ------------------------------------------------------------------ without the tick: exactly as before
spec = importlib.util.spec_from_loader("old_wp", loader=None)
old = importlib.util.module_from_spec(spec)
src = subprocess.run(["git", "show", "564c105:walkin_print.py"], capture_output=True, text=True, check=True,
                     encoding="utf-8").stdout
exec(compile(src, "old_walkin_print.py", "exec"), old.__dict__)
items = [{"kind": "document", "size": "A4", "pages": 3, "copies": 2, "color": c, "color_pages": "1", "sides": s,
          "per_side": 1, "paper": p, "finish": "none", "lam": False, "lam_sheets": 0, "folder": "1 Document A4"}
         for c in ("bw", "color", "mixed") for s in ("single", "double") for p in ("Normal 80 gsm", "Silk 250 gsm")]
prep = {"pages": 3, "coverage": 2.0, "page_colors": [True, False, False], "paper": "A4"}
same = all(walkin_print.settings_for(rules, it, prep) == old.settings_for(rules, it, prep) for it in items)
jsame = all(walkin_print.job_for(menu.jobs, rules, it, prep) == old.job_for(menu.jobs, rules, it, prep) for it in items)
check("without the tick: the settings and jobs are exactly as before (12 document items)", same and jsame)

# ------------------------------------------------------------------ Settings
costs.set_password("pw")
S = ss.SettingsScreen(menu, on_back=lambda: None)
S.win.geometry("1240x1000+10+10"); pump(0.4)
check("Settings: a Rotate sort block with IM C4510, Tray 1 / Tray 4 as shipped",
      S.rotate.get("printer") == "C4510" and S.rotate.get("trays") == ["Tray 1", "Tray 4"])
S.rotate = {"printer": "C3000", "trays": ["Tray 2", "Tray 3"]}
S.save(); pump(0.3)
check("another printer and trays are picked up at once",
      menu.rules["rotate_sort"]["printer"] == "C3000" and menu.rules["rotate_sort"]["trays"] == ["Tray 2", "Tray 3"]
      and json.loads((ADMIN / "settings.json").read_text(encoding="utf-8"))["rotate_sort"]["printer"] == "C3000")
item = dict(items[0], rotate=True)
j = walkin_print.job_for(menu.jobs, menu.rules, item, prep)
check("…a ticked item then goes to that copier", j["printer"] == "C3000" and not j["problem"], (j["printer"], j["problem"]))
S.rotate = {"printer": None, "trays": []}
S.save(); pump(0.3)
q2 = ws.QuoteScreen(menu, "email", on_back=menu.show_menu); pump(0.6)
check("“Off” greys the tick", q2.rotate_box.instate(["disabled"])
      and q2.rotate_why.cget("text") == "Rotate sort isn't set up on this PC's printers", q2.rotate_why.cget("text"))
q2.back()
print(f"{sum(results)}/{len(results)} passed")
