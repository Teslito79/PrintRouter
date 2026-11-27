"""Handoff 2026-11-19_07: jobs go around a copier that is out of toner. Temp copy of the folder layout, pretend
readings and pretend installed printers; nothing is printed; pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, datetime, importlib.util, itertools, json, os, shutil, subprocess, sys, time, tkinter as tk
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
routing.installed_printers = lambda: ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6", "XP-80C"]
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_prices as wp, walkin_pricing as P
import walkin_print, walkin_screens as ws, settings_screen as ss
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
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


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
menu.toners.stop()
J = menu.jobs
PLAIN = rules["plain_paper_types"]["types"][0]


def pump(secs=0.3, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)


FULL = {"black": 80, "cyan": 70, "magenta": 60, "yellow": 50}


def readings(at=None, ok=True, **empty):
    """The Data screen's newest readings: empty={"C3000": ["yellow"]}."""
    at = at or datetime.datetime.now()
    menu.toners.latest = {pid: {"ok": ok, "time": at, "toners": {c: (0 if c in empty.get(pid, []) else v)
                                                                for c, v in FULL.items()}} for pid in rules["printers"]}


def settings(color="color", paper="A4", paper_type=None, printer="auto", product=False, gsm=None):
    s = {"printer": printer, "copies": "1", "per_side": "1", "color": color, "sides": "single", "paper": paper,
         "paper_type": paper_type or PLAIN, "tray": "Auto Tray Select", "rotate": "0"}
    if product:
        s.update(product=True, gsm=gsm)
    return s


def job(s, colours=None, coverage=30.0):
    return J.job_for("x.pdf", s, 1, coverage, colours or [s["color"] != "bw"], busy=set())


product = settings(paper_type="Thick 3(221 to 256 g/m2)", product=True, gsm=250)  # rules: IM C3000
doc = settings()  # a colour document on plain paper: MP C3004
bw = settings(color="bw")  # IM C4510

# ------------------------------------------------------------------ moved
readings(C3000=["yellow"])
j = job(product)
check("colour product, IM C3000 out of yellow: goes to the IM C4510, “IM C3000 is out of yellow toner” in its reason",
      j["printer"] == "C4510" and "IM C3000 is out of yellow toner" in j["reason"] and not j["problem"], (j["printer"], j["reason"]))
check("…the job line says it: “IM C3000 is out of yellow toner: sent to IM C4510”",
      J.settings_text(product, j).endswith("IM C3000 is out of yellow toner: sent to IM C4510"), J.settings_text(product, j))
readings(C3004=["magenta", "yellow"])
menu.toners.latest = {}
before = J.job_for("d.pdf", doc, 1, 5.0, [True], busy=set())["printer"]
readings(C3004=["magenta", "yellow"])
j = job(doc, coverage=5.0)
check("MP C3004 out of magenta and yellow: a colour plain document goes to the next copier that can take it",
      before == "C3004" and j["printer"] in ("C4510", "C3000") and j["printer"] != "C3004"
      and "MP C3004 is out of magenta and yellow toner" in j["reason"], (j["printer"], j["reason"]))
mixed = settings(color="auto")
menu.toners.latest = {}
plain_route = J.job_for("m.pdf", mixed, 3, 30.0, [True, False, False], busy=set())["printer"]
readings(**{plain_route: ["yellow"]})
j = J.job_for("m.pdf", mixed, 3, 30.0, [True, False, False], busy=set())
check("…a mixed job (one colour page of three) counts as colour: it leaves a copier out of yellow",
      j["printer"] != plain_route and "out of yellow toner" in j["reason"], (plain_route, j["printer"], j["reason"]))
readings(C4510=["yellow"])
j = job(bw)
check("B&W jobs aren't moved for a missing colour toner", j["printer"] == "C4510" and not j.get("toner"), j["reason"])
readings(C4510=["black"])
j = job(bw)
check("…but are moved when the copier is out of black", j["printer"] != "C4510"
      and "IM C4510 is out of black toner" in j["reason"], (j["printer"], j["reason"]))

# ------------------------------------------------------------------ not moved
readings(at=datetime.datetime.now() - datetime.timedelta(minutes=31), C3000=["yellow"])
check("a reading older than 30 minutes moves nothing", job(product)["printer"] == "C3000")
readings(ok=False, C3000=["yellow"])
check("a failed reading moves nothing", job(product)["printer"] == "C3000")
readings(at=datetime.datetime.now() - datetime.timedelta(minutes=5), C3000=["yellow"])
menu.toners.add_by_hand("C3000", "yellow", None, None, None, when=datetime.datetime.now().replace(microsecond=0))
check("Toner replaced pressed after the empty reading: not moved", job(product)["printer"] == "C3000")
for c in toners.read_changes():
    menu.toners.remove(c["id"])
readings(C3000=["yellow"])
j = job(settings(paper_type="Thick 3(221 to 256 g/m2)", product=True, gsm=250, printer="C3000"))
check("a copier picked by hand: not moved (its line says the toner is out)", j["printer"] == "C3000"
      and j["toner"] == "IM C3000 is out of yellow toner", (j["printer"], j.get("toner")))
readings(C3000=["yellow"], C4510=["yellow"], C3004=["yellow"])
j = job(product)
check("nowhere to go (all three out of yellow): the job stays where the rules put it, its line says the toner is out",
      j["printer"] == "C3000" and not j["problem"]
      and J.settings_text(product, j).endswith("IM C3000 is out of yellow toner"), J.settings_text(product, j))

# ------------------------------------------------------------------ exactly as before: the tick off, no readings
spec = importlib.util.spec_from_loader("old_routing", loader=None)
old = importlib.util.module_from_spec(spec)
exec(subprocess.run(["git", "show", "87ac879:routing.py"], capture_output=True, text=True, check=True,
                    encoding="utf-8").stdout, old.__dict__)
JOBS = []
for color, content, prod, paper_type, paper, gsm in itertools.product(
        (False, True), ("document", "pictures"), (False, True), (PLAIN, "Thick 3(221 to 256 g/m2)", "Labels"),
        ("A4", "A3"), (None, 80, 250, 300, 350, 400)):
    JOBS.append({"color": color, "content": content, "product": prod, "paper_type": paper_type, "paper": paper, "gsm": gsm})
BUSY = [(), ("C3000",), ("C4510",), ("C3000", "C4510"), ("C3004",)]
shipped = routing.load_rules()
readings(C3000=["yellow"], C3004=["magenta"])
J.rules["avoid_empty_toner"] = False
same_off = all(routing.choose_printer(shipped, j_, b, (), J.no_toner()) == old.choose_printer(shipped, j_, b)
               for j_ in JOBS for b in BUSY)
check(f"the tick off: routing exactly as before for the {len(JOBS) * len(BUSY)}-job set (02's)", same_off and J.no_toner() == {})
J.rules["avoid_empty_toner"] = True
menu.toners.latest = {}
same_none = all(routing.choose_printer(shipped, j_, b, (), J.no_toner()) == old.choose_printer(shipped, j_, b)
                for j_ in JOBS for b in BUSY)
check("no readings at all (the home PC): routing exactly as before", same_none and J.no_toner() == {})
readings(C3000=["yellow"])
check("(the empty yellow moves the job)", job(product)["printer"] == "C4510")
readings()
check("the toner back on the next reading: routing goes back to the rules", job(product)["printer"] == "C3000"
      and not job(product).get("toner"))

# ------------------------------------------------------------------ Print Jobs, a job already sent, the Data screen
d = pdfium.PdfDocument.new(); d.new_page(595, 842); d.save(str(SRC / "flyer.pdf")); d.close()
item = {"kind": "document", "size": "A4", "pages": 1, "copies": 1, "color": "color", "color_pages": "", "sides": "single",
        "per_side": 1, "paper": "Silk 250 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
c = wo.Customers().resolve("Toner Test", "99 777 888", "", 0)
o = wo.place([item], P.price_order(wp.current(), [item]), dict(c, entered_name="Toner Test", entered_phone="99 777 888"),
             "quote", None)
shutil.copyfile(SRC / "flyer.pdf", o["_folder"] / o["items"][0]["folder"] / "flyer.pdf")
t = time.time() - 60; os.utime(o["_folder"] / o["items"][0]["folder"] / "flyer.pdf", (t, t))
readings(C3000=["yellow"])
run = menu.print_queue
for _ in range(60):
    run.update([wo.refresh(x) for x in wo.list_open()]); pump(0.3)
    if isinstance(run.plans.get(o["number"]), tuple):
        break
check("Print Jobs: the walk-in order's colour item is planned for the IM C4510", set(run.plans[o["number"]][0]) == {"C4510"},
      run.plans.get(o["number"]))
pj = ws.PrintJobsScreen(menu, on_back=lambda: None); pj.win.geometry("1320x900+10+10"); pump(2)
o = wo.refresh(wo.load_order(o["_folder"]))
line = pj.item_state(o, o["items"][0])[0]
check("…and its line says why: “IM C3000 is out of yellow toner: sent to IM C4510”",
      "→ IM C4510" in line and "IM C3000 is out of yellow toner: sent to IM C4510" in line, line)
window_shot.shot(pj.win, OUT / "print_jobs_line.png")
pj.win.destroy()
o["parts"] = {"C3000": {"items": [0], "cover": True, "state": "printing", "sent": [], "fronts": []}}
wo.save_order(o)
plan = run.plan(wo.load_order(o["_folder"]))
check("a job already sent (its copier fixed) isn't moved", set(plan[0]) == {"C3000"}, plan[0])
data = toners.TonersScreen(root, menu.rules, menu.toners, on_back=lambda: None)
data.win.geometry("1400x900+10+10"); pump(0.5)
texts = []


def walk(w):
    if w.winfo_class() == "TLabel":
        texts.append(w.cget("text"))
    for ch in w.winfo_children():
        walk(ch)


walk(data.win)
check("the Data screen: “Out of yellow toner: colour jobs go to IM C4510”",
      "Out of yellow toner: colour jobs go to IM C4510" in texts, [x for x in texts if "Out of" in x])
window_shot.shot(data.win, OUT / "data_screen_out_of_yellow.png")
data.win.destroy()

# ------------------------------------------------------------------ Settings: the tick
import costs
S = ss.SettingsScreen(menu, on_back=lambda: None); pump(0.4)
check("Settings: “Send jobs away from a copier that's out of toner”, on by default", S.avoid_toner.get() is True)
S.avoid_toner.set(False); S.save(); pump(0.2)
check("…off is saved and routing then is as before", menu.rules["avoid_empty_toner"] is False
      and job(product)["printer"] == "C3000"
      and json.loads((ADMIN / "settings.json").read_text(encoding="utf-8"))["avoid_empty_toner"] is False)
S.avoid_toner.set(True); S.save(); pump(0.2)
check("…on again: moved again", job(product)["printer"] == "C4510")
print(f"{sum(results)}/{len(results)} passed")
