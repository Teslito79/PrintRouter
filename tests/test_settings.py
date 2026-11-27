"""Handoff 2026-11-18_02: the Settings page. Temp copy of the folder layout; the installed printers are a pretend
list (no printer is added, changed or used); nothing is printed (driverprint.print_pdf is faked); pictures of ORCA's
own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import copy, ctypes, importlib.util, itertools, json, os, shutil, subprocess, sys, time, tkinter as tk
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
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
shipped = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
shipped.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
               finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(shipped, indent=1), encoding="utf-8")
routing.app_dir = lambda: ADMIN
INSTALLED = ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6", "XP-80C", "HP LaserJet Test",
             "Microsoft Print to PDF"]
routing.installed_printers = lambda: list(INSTALLED)
import appicon, copier_queue, copy_counter as cc, costs, driverprint, jobs, mainmenu, printing, toners
import walkin_orders as wo, walkin_prices as wp, walkin_pricing as P, walkin_print, walkin_screens as ws
import settings_screen as ss
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


# the routing before this handoff, from git, to compare with
spec = importlib.util.spec_from_loader("old_routing", loader=None)
old = importlib.util.module_from_spec(spec)
exec(subprocess.run(["git", "show", "87ac879:routing.py"], capture_output=True, text=True, check=True,
                    encoding="utf-8").stdout, old.__dict__)

PLAIN = shipped["plain_paper_types"]["types"]
JOBS = []
for color, content, product, paper_type, paper, gsm in itertools.product(
        (False, True), ("document", "pictures"), (False, True), (PLAIN[0], "Thick 3(221 to 256 g/m2)", "Labels"),
        ("A4", "A3"), (None, 80, 250, 300, 350, 400)):
    JOBS.append({"color": color, "content": content, "product": product, "paper_type": paper_type, "paper": paper,
                 "gsm": gsm, "duplex": False, "tray": "Auto Tray Select"})
BUSY = [(), ("C3000",), ("C4510",), ("C3000", "C4510"), ("C3004",)]

# ------------------------------------------------------------------ 1. no settings.json: exactly as today
rules = routing.load_rules()
check("no settings.json: the rules in force are rules.json", rules == shipped and routing.load_local() == {})
same = all(routing.choose_printer(rules, j, b) == old.choose_printer(shipped, j, b) for j in JOBS for b in BUSY)
check(f"…routing gives exactly today's choice and reason for {len(JOBS) * len(BUSY)} jobs x busy copiers", same)
same_missing = all(routing.choose_printer(rules, j, b, set(rules["printers"])) == old.choose_printer(shipped, j, b)
                   for j in JOBS for b in BUSY)
check("…and on a PC where none of them is installed (the home PC) as well", same_missing)
check("…every rules.json reader goes through routing.load_rules (no other read of rules.json)",
      [l.split(":")[0] + ":" + l.split(":", 2)[2].strip() for l in
       subprocess.run(["git", "grep", "-n", 'load_json("rules.json")', "--", "*.py", ":!tests"], capture_output=True,
                      text=True, cwd=APP).stdout.strip().splitlines()]
      == ['routing.py:return load_json("rules.json")'])  # routing.shipped_rules, the one read (load_rules uses it)
toners.save_settings({"community": "public", "addresses": {"C4510": "192.168.10.85"}})
check("…the Data screen's typed address is used as before",
      toners.copier_address(rules["printers"], "C4510") == ("192.168.10.85", "typed in the Data screen"))

# ------------------------------------------------------------------ the menu
SENT = []
driverprint.print_pdf = lambda pdf, q, devmode, name, **kw: SENT.append((q, name, str(pdf)))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, *a, **k: (paper, color, duplex, copies)
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
printing.send = lambda pdf, queue, settings=None: SENT.append((queue, "receipt", str(pdf)))
toners.TIMEOUT = 0.2
ASKED, WARNED = [], []
ANSWER = {"yes": True}
messagebox.askyesno = lambda *a, **k: ASKED.append(k.get("message")) or ANSWER["yes"]
messagebox.showwarning = lambda *a, **k: WARNED.append(k.get("message"))
os.startfile = lambda p: SENT.append(("startfile", str(p)))
root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


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
    return [x.cget("text") for x in widgets(w) if x.winfo_class() in ("TLabel", "TButton", "TLabelframe", "TCheckbutton",
                                                                    "TRadiobutton")]


buttons = [b.cget("text") for b in widgets(menu.win, "TButton")]
check("menu: Settings the last button (19_08 order)", buttons[:7] == ["Walk-in", "Inventory management", "Data",
                                                                     "PrintHub", "Counter", "Prices", "Settings"], buttons)
check("…no “No printers set up yet” line while the printers are installed", menu.printer_line.cget("text") == "")

# ------------------------------------------------------------------ password
costs.set_password("secret1")


def tops(w):
    """Every Toplevel under w (dialogs belong to the window that opened them)."""
    out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            out.append(c)
        out += tops(c)
    return out


def answer_password(text):
    def go():
        dlg = [w for w in tops(root) if w.title() == "Prices"]  # the dialog belongs to the menu window
        if not dlg:
            root.after(50, go); return
        d = dlg[-1]
        entry = [x for x in widgets(d) if x.winfo_class() == "TEntry"][0]
        entry.delete(0, "end"); entry.insert(0, text)
        ok = [x for x in widgets(d, "TButton") if x.cget("text") == "OK"][0]
        ok.invoke()
        if text != "secret1":
            root.after(100, lambda: d.destroy() if d.winfo_exists() else None)
    root.after(50, go)


def settings_windows():
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "ORCA - Settings"
            and w.winfo_exists()]


answer_password("wrong")
menu.open_settings(); pump(0.3)
check("password: a wrong password keeps Settings closed", not settings_windows())
answer_password("secret1")
menu.open_settings(); pump(0.5)
check("…the Prices password opens it", len(settings_windows()) == 1)
import gc


def screen():
    return [x for x in gc.get_objects() if isinstance(x, ss.SettingsScreen) and x.win.winfo_exists()][-1]


S = screen()
S.win.geometry("1240x1000+10+10"); pump(0.4)
t = texts(S.win)
check("Settings shows the three copiers with their settings as today", all(x in t for x in (
    "IM C4510", "IM C3000", "MP C3004", "RICOH IM C4510 PCL 6", "350 gsm", "300 gsm", "No limit")), t)
check("…the routing as today: B&W IM C4510, colour documents MP C3004, else IM C3000 if busy IM C4510",
      S.rows == {"bw": ("C4510", None), "doc": ("C3004", None), "colour": ("C3000", "C4510")}
      and [(p.get(), b.get()) for p, b in S.route_vars.values()] == [("IM C4510", "Wait"), ("MP C3004", "Wait"),
                                                                    ("IM C3000", "IM C4510")])
check("…the address typed in the Data screen shows in Settings", S.printers["C4510"].get("address") == "192.168.10.85")
check("…the receipt printer, prices on paper off, A3 counts 2, read every 5 s",
      S.receipt == "XP-80C" and S.prices_on.get() is False and S.a3.get() == "2" and S.poll.get() == "5")
window_shot.shot(S.win, OUT / "settings_page.png")
S.scroll.canvas.yview_moveto(0.25); pump(0.3)
window_shot.shot(S.win, OUT / "settings_routing.png")
S.scroll.canvas.yview_moveto(0); pump(0.1)
S.dirty = False
S.back(); pump(0.2)
check("Back with nothing changed asks nothing and saves nothing", not ASKED and not (ADMIN / "settings.json").exists())

# ------------------------------------------------------------------ the printer edit, add a printer, round trip
answer_password("secret1"); menu.open_settings(); pump(0.5)
S = screen(); S.win.geometry("1240x1000+10+10"); pump(0.3)
S.add(); pump(0.3)
dlg = [x for x in gc.get_objects() if isinstance(x, ss.PrinterDialog)][-1]
check("Add printer: the Windows printer is a drop-down of the printers installed on this PC",
      [x for x in widgets(dlg.dlg) if x.winfo_class() == "TCombobox"][0].cget("values") == tuple(INSTALLED))
dlg.vars["queue"].set("HP LaserJet Test"); dlg.vars["label"].set("IM C4510")
dlg.done(); pump(0.1)
check("…a name already used is refused", "already used" in dlg.error.cget("text"), dlg.error.cget("text"))
dlg.vars["label"].set("HP Office"); dlg.vars["color"].set(ss.COLOURS["bw"]); dlg.vars["max_paper"].set("A4")
dlg.vars["max_gsm"].set("abc"); dlg.done(); pump(0.1)
check("…a heaviest paper that isn't a whole number is refused", "Heaviest paper" in dlg.error.cget("text"))
dlg.vars["max_gsm"].set("160")
dlg.vars["address"].set("192.168.10.99")
check("…Copy counter is ticked by itself once there is a network address", dlg.vars["copy_counter"].get() is True)
window_shot.shot(dlg.dlg, OUT / "printer_edit.png")
dlg.done(); pump(0.3)
check("…the new printer gets a key from its name", S.printers.get("HPOffice", {}).get("queue") == "HP LaserJet Test"
      and S.printers["HPOffice"]["color"] == "bw" and S.printers["HPOffice"]["max_gsm"] == 160, S.printers.get("HPOffice"))
S.route_vars["bw"][0].set("HP Office"); S.route_changed(); pump(0.2)
S.receipt = None
S.prices_on.set(True)
S.save(); pump(0.3)
local = json.loads((ADMIN / "settings.json").read_text(encoding="utf-8"))
check("Save writes settings.json with only what changed (printers, rules, fallback, receipt, prices on paper)",
      set(local) == {"printers", "rules", "fallback_printer", "receipt_printer", "walkin_paper_prices"}
      and local["fallback_printer"] == "HPOffice" and local["receipt_printer"] is None, sorted(local))
check("…rules.json is never written", json.loads((ADMIN / "rules.json").read_text(encoding="utf-8")) == shipped)
check("…it is in use at once: the menu's rules have the new printer and routing",
      "HPOffice" in menu.rules["printers"] and menu.rules["rules"][0]["printer"] == "HPOffice"
      and menu.jobs.printers is menu.rules["printers"] and menu.print_queue.copiers.get("HPOffice") == {"state": "idle"})
r2 = routing.load_rules()
check("restart: the saved settings come back (a new load_rules)", r2["printers"]["HPOffice"]["label"] == "HP Office"
      and routing.rows_of(r2) == {"bw": ("HPOffice", None), "doc": ("C3004", None), "colour": ("C3000", "C4510")})
check("the address typed in Settings is used by the Data screen and the copy counter",
      toners.copier_address(r2["printers"], "HPOffice") == ("192.168.10.99", "set in Settings")
      and toners.copier_address(r2["printers"], "C4510") == ("192.168.10.85", "set in Settings"))
S.back(); pump(0.2)

# ------------------------------------------------------------------ routing with the rows
rules = menu.rules
bw = {"color": False, "content": "document", "product": False, "paper_type": PLAIN[0], "paper": "A4", "gsm": None}
check("B&W goes to the B&W row's printer (HP Office)", routing.choose_printer(rules, bw)[0] == "HPOffice")
check("…B&W A3 skips the A4-only HP and goes to the next printer that takes A3",
      routing.choose_printer(rules, dict(bw, paper="A3"))[0] == "C4510", routing.choose_printer(rules, dict(bw, paper="A3")))
check("…B&W on 300 gsm skips the HP (up to 160 gsm)", routing.choose_printer(rules, dict(bw, gsm=300))[0] == "C4510",
      routing.choose_printer(rules, dict(bw, gsm=300)))
doc = dict(bw, color=True)
check("colour plain document: MP C3004", routing.choose_printer(rules, doc)[0] == "C3004")
prod = dict(doc, product=True, paper_type="Thick 3(221 to 256 g/m2)", gsm=250)
check("colour product: IM C3000, if busy IM C4510", routing.choose_printer(rules, prod)[0] == "C3000"
      and routing.choose_printer(rules, prod, busy={"C3000"})[0] == "C4510")
check("colour on 350 gsm: over the IM C3000's 300 gsm, to the IM C4510",
      routing.choose_printer(rules, dict(prod, gsm=350))[0] == "C4510")
check("colour A3: IM C3000", routing.choose_printer(rules, dict(prod, paper="A3"))[0] == "C3000")
check("a printer “Not found on this PC” is skipped like a busy one",
      routing.choose_printer(rules, bw, missing={"HPOffice"})[0] == "C4510"
      and "isn't installed on this PC" in routing.choose_printer(rules, bw, missing={"HPOffice"})[1])
only_hp = copy.deepcopy(rules); only_hp["printers"] = {"HPOffice": rules["printers"]["HPOffice"]}
only_hp["rules"] = routing.rules_from_rows(only_hp, {k: ("HPOffice", None) for k, _ in routing.ROWS})
job = menu.jobs
job_rules = job.rules
job.rules = only_hp; job.printers = only_hp["printers"]
s = {"printer": "auto", "copies": "1", "per_side": "1", "color": "color", "sides": "single", "paper": "A3",
     "paper_type": PLAIN[0], "tray": "Auto Tray Select", "rotate": "0"}
j = job.job_for("x.pdf", s, 1, None, [True])
check("no printer can take it: said on screen (“No printer can take this: HP Office prints black and white only”)",
      j["problem"] == "No printer can take this: HP Office prints black and white only", j["problem"])
job.rules = job_rules; job.printers = job_rules["printers"]

# ------------------------------------------------------------------ receipt None, prices on paper
check("Receipt printer None: the copy counter panel has no Print receipt, Done still writes the sale", True)
S2 = ws.CopyCounterScreen(menu, on_back=lambda: None); pump(0.3)
menu.copy_counter.read_func = lambda pid: {"how": "total", "total": 100}
S2.start("C4510"); pump(0.2)
c = menu.copy_counter.counters["C4510"]
menu.copy_counter.read_func = lambda pid: {"how": "total", "total": 103}
c.finish(sleep=lambda s: None, clock=lambda: 0); S2.build("C4510"); pump(0.2)
t = texts(S2.panels["C4510"])
k = len(wo.read_sales())
results.pop()
check("Receipt printer None: the copy counter panel has no Print receipt", "Print receipt" not in t and "Done" in t, t)
S2.done("C4510"); pump(0.2)
check("…and Done still writes the sale", len(wo.read_sales()) == k + 1)
check("…the Copy counter shows a panel per ticked printer (HP Office has an address, so it counts too)",
      list(S2.panels) == ["C4510", "C3000", "C3004", "HPOffice"], list(S2.panels))
S2.win.destroy()
order = {"number": 101, "customer": {"name": "Ann", "phone": "+35799111222"}, "placed": "2026-11-18T10:00:00",
         "created": "2026-11-18T10:00:00",
         "items": [], "total": 12.5, "due": 12.5, "priced": {"total": 12.5, "due": 12.5}}


def cover_text(rules_now):
    path = TMP / "cover.pdf"
    walkin_print.cover_pdf(order, path, rules=rules_now)
    d = pdfium.PdfDocument(str(path)); text = d[0].get_textpage().get_text_range(); d.close()
    return text


check("prices on paper ticked: the total is on a cover sheet PDF", "12.50" in cover_text(menu.rules), cover_text(menu.rules))
answer_password("secret1"); menu.open_settings(); pump(0.5)
S = screen()
S.prices_on.set(False); S.save(); pump(0.2)
check("…unticked: it is gone", "12.50" not in cover_text(menu.rules) and menu.rules["walkin_paper_prices"] is False)

# ------------------------------------------------------------------ Remove
run = menu.print_queue
run.orders = {150: {"number": 150}}
real_batches = run.batches
run.batches = lambda pid: [[150]] if pid == "HPOffice" else []
WARNED.clear()
S.remove("HPOffice"); pump(0.1)
check("Remove is refused while an order waits on the printer, naming it",
      "HPOffice" in S.printers and WARNED and "walk-in order #150 waiting on it" in WARNED[-1], WARNED)
run.batches = real_batches; run.orders = {}
ASKED.clear()
S.remove("HPOffice"); pump(0.1)
check("…allowed when free, after asking once", "HPOffice" not in S.printers and ASKED == ["Remove HP Office from ORCA?"]
      and S.rows["bw"] == ("C4510", None), (ASKED, S.rows))
ASKED.clear(); ANSWER["yes"] = False
S.back(); pump(0.2)
check("Back with unsaved changes asks “Throw away the changes?” (No: stays open)", ASKED == ["Throw away the changes?"]
      and S.win.winfo_exists())
ANSWER["yes"] = True
S.save(); pump(0.2)
check("…saved: the printer is gone from the rules in force", "HPOffice" not in menu.rules["printers"])

# ------------------------------------------------------------------ test page, check address
ASKED.clear(); SENT.clear()
S.test_page("C3000"); pump(1.5, until=lambda: SENT)
check("Print test page asks first, then sends one page through the normal print queue",
      ASKED == ["Print one test page on IM C3000?"] and SENT and SENT[0][0] == "RICOH IM C3000 PCL 6_1"
      and SENT[0][1] == "ORCA test page", (ASKED, SENT))
d = pdfium.PdfDocument(SENT[0][2]); w, h = d[0].get_size(); n = len(d); d.close()
check("…the test page PDF: one A4 page", n == 1 and abs(w - 595) < 2 and abs(h - 842) < 2, (n, w, h))
img = pdfium.PdfDocument(SENT[0][2])[0].render(scale=0.5).to_pil()
img.save(OUT / "test_page.png")
ASKED.clear(); SENT.clear(); ANSWER["yes"] = False
S.test_page("C3000"); pump(0.3)
check("…No: nothing is sent", ASKED and not SENT)
ANSWER["yes"] = True
cc_read = cc.read_at
cc.read_at = lambda address, page=True: {"how": "sheets", "total": 1, "copier": {}}
S.check_address("C4510"); pump(1.5, until=lambda: "detailed" in S.checks.get("C4510", ""))
check("Check address says what it found: “Counter page: detailed (sheets)”",
      S.checks["C4510"] == "192.168.10.85: Counter page: detailed (sheets)", S.checks.get("C4510"))
cc.read_at = lambda address, page=True: (_ for _ in ()).throw(cc.CounterError("no answer"))
toners.save_settings(dict(toners.load_settings(), addresses=dict(toners.load_settings()["addresses"],
                                                                 C3000="192.168.10.86")))  # not this PC's own ports
S.check_address("C3000"); pump(1.5, until=lambda: "No" in S.checks.get("C3000", "")[-12:])
check("…or “No answer”", S.checks["C3000"].endswith("No answer"), S.checks.get("C3000"))
cc.read_at = cc_read

# ------------------------------------------------------------------ one printer only
for pid in ("C3000", "C3004"):
    S.remove(pid)
S.save(); pump(0.3)
check("one printer only: all three rows are that printer, no If busy",
      routing.rows_of(menu.rules) == {k: ("C4510", None) for k, _ in routing.ROWS}
      and not any(x.cget("text") == "If busy" for x in widgets(S.win, "TLabel")))
check("…everything goes to it", all(routing.choose_printer(menu.rules, j)[0] == "C4510" for j in JOBS))
S3 = ws.CopyCounterScreen(menu, on_back=lambda: None); pump(0.3)
check("…the Copy counter shows one panel", list(S3.panels) == ["C4510"], list(S3.panels))
S3.win.destroy()

# ------------------------------------------------------------------ a shop that starts from nothing
INSTALLED[:] = ["Microsoft Print to PDF"]
menu.show_printer_line(); pump(0.1)
check("no printer in force installed: the menu shows “No printers set up yet: open Settings”",
      menu.printer_line.cget("text") == "No printers set up yet: open Settings")
window_shot.shot(menu.win, OUT / "menu_no_printers.png")
INSTALLED[:] = ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6", "XP-80C"]

# ------------------------------------------------------------------ custom routing, reset
ASKED.clear()
S.reset(); pump(0.5)
check("Reset (asks once) deletes settings.json and brings back the shipped behaviour",
      len(ASKED) == 1 and not (ADMIN / "settings.json").exists() and menu.rules["printers"].keys() == shipped["printers"].keys()
      and menu.rules["rules"] == shipped["rules"] and menu.rules["receipt_printer"] == "XP-80C")
custom = copy.deepcopy(shipped); custom["rules"].insert(0, {"if": {"paper_type": "Labels"}, "printer": "C3000", "reason": "Labels"})
(ADMIN / "rules.json").write_text(json.dumps(custom), encoding="utf-8")
menu.apply_settings()
for w in settings_windows():
    w.destroy()
answer_password("secret1"); menu.open_settings(); pump(0.5)
S = screen()
check("rules that can't be shown as the three rows: “Custom routing from rules.json”, left alone",
      S.rows is None and "Custom routing from rules.json" in texts(S.win))
S.prices_on.set(True); S.save(); pump(0.2)
check("…saving other settings keeps the custom rules", menu.rules["rules"] == custom["rules"]
      and "rules" not in json.loads((ADMIN / "settings.json").read_text(encoding="utf-8")))
(ADMIN / "rules.json").write_text(json.dumps(shipped, indent=1), encoding="utf-8")
print(f"{sum(results)}/{len(results)} passed")
