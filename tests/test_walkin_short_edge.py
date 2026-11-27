"""Handoff 2026-11-27_02: long or short edge chosen in Get Quote / Add Email. Temp copy of the folder layout, the test
price sheet; pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, gc, json, os, shutil, sys, time, tkinter as tk
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
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_prices, walkin_print
import walkin_pricing as P, walkin_screens as ws
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
messagebox.showwarning = lambda **k: None
messagebox.askyesno = lambda *a, **k: True
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


def pdf(path, pages=2):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(842, 595)
    d.save(str(path)); d.close()
    return str(path)


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


walkin = ws.WalkinScreen(menu, on_back=menu.show_menu)
walkin.open_quote("email"); pump()
E = [x for x in gc.get_objects() if isinstance(x, ws.QuoteScreen) and x.mode == "email" and x.win.winfo_exists()][-1]
E.what.set("Document"); E.build_options(); pump()
v = E.option_vars
check("the Sides drop-down offers One side / Both sides, long edge / Both sides, short edge (flip on top)",
      list(E.sides_box.cget("values")) == ["One side", "Both sides, long edge", "Both sides, short edge (flip on top)"],
      E.sides_box.cget("values"))
v["pages"].set("2"); v["sides"].set("Both sides, short edge (flip on top)")
# the drop-down open, for the picture
E.win.geometry("1300x900+10+10"); pump(0.4)
import combo_shot
combo_shot.shot(E.win, E.sides_box, OUT / "sides_dropdown.png", pump)
pump(0.3)
v["sides"].set("Both sides, short edge (flip on top)")
E.add_item(); pump()
item = E.items[-1]
check("Add item: sides double, flip short", item["sides"] == "double" and item["flip"] == "short", item)
check("…its line says “both sides, short edge”", "both sides, short edge" in P.describe(item), P.describe(item))
row = E.tree.item(E.tree.get_children()[-1])["values"]
check("…and so does the list in Add Email", "both sides, short edge" in str(row[1]), row)
E.tree.selection_set(E.tree.get_children()[-1]); E.edit_item(); pump()
check("Edit shows it again", E.option_vars["sides"].get() == "Both sides, short edge (flip on top)",
      E.option_vars["sides"].get())
E.cancel_edit(); pump()

# printing
s_short = walkin_print.settings_for(rules, item, None)
long_item = dict(item, flip="long")
old_item = {k: x for k, x in item.items() if k != "flip"}
one = dict(old_item, sides="single")
check("print settings: short gives sides short", s_short["sides"] == "short", s_short["sides"])
check("…long, and an old item without flip, give long; one side gives single",
      walkin_print.settings_for(rules, long_item, None)["sides"] == "long"
      and walkin_print.settings_for(rules, old_item, None)["sides"] == "long"
      and walkin_print.settings_for(rules, one, None)["sides"] == "single")
check("…a long-edge item's line says just “both sides”", "both sides," in P.describe(long_item)
      and "short edge" not in P.describe(long_item))

# price and the Counter identical
pl = walkin_prices.current()
a, b = P.price_order(pl, [item]), P.price_order(pl, [long_item])
check("the price is the same for long and short", a["total"] == b["total"] and a["lines"][0]["price"] == b["lines"][0]["price"],
      (a["total"], b["total"]))
ca = walkin_print.counter_lines({"items": [item]})
cb = walkin_print.counter_lines({"items": [long_item]})
check("…and so is the cover sheet's Counter", ca == cb, (ca, cb))

# 10 files dropped with short edge
files = [pdf(SRC / f"Report_{i}.pdf") for i in range(10)]
E.held = list(files); E.show_box(); E.build_options(); pump()
E.option_vars["sides"].set("Both sides, short edge (flip on top)")
n = len(E.items)
E.add_item(); pump(1.5)
new = E.items[n:]
check("10 files dropped with short edge: 10 items, all short", len(new) == 10
      and all(x["sides"] == "double" and x.get("flip") == "short" for x in new), [x.get("flip") for x in new])

# "Add N more items like item 1?" copies it
E.items = [dict(item)]; E.drops = [[]]; E.reprice()
E.add_like(0, [pdf(SRC / "a.pdf"), pdf(SRC / "b.pdf"), pdf(SRC / "c.pdf")]); pump(1.0)
check("“Add N more items like item 1?” copies it", len(E.items) == 3 and all(x.get("flip") == "short" for x in E.items),
      [x.get("flip") for x in E.items])

# order.json keeps it; Print Jobs > Settings… shows it and can change it
E.items = [dict(item)]; E.drops = [[]]; E.reprice()
E.cust_vars["email"].set("edge@example.com"); E.cust_vars["name"].set("Edge Test")
E.place(); pump(0.5)
order = sorted(wo.list_open(), key=lambda o: o["number"])[-1]
check("order.json keeps flip short", order["items"][0].get("flip") == "short", order["items"][0])
pdf(order["_folder"] / order["items"][0]["folder"] / "file.pdf")
order = wo.refresh(order)


class Ctx:  # what SettingsDialog needs of the Print Jobs screen
    pass


ctx = Ctx(); ctx.rules = rules; ctx.jobs = menu.jobs if hasattr(menu, "jobs") else menu.print_queue.jobs
ctx.preparer = type("Prep", (), {"get": staticmethod(lambda o, it: {"pdf": None, "paper": "A4"})})()
fake = type("Screen", (), {})(); fake.ctx = ctx; fake.win = E.win; fake.signature = None; fake.poll = lambda: None
dlg = ws.SettingsDialog(fake, order, 0); pump(0.3)
var, mapping = dlg.fields["sides"]
check("Print Jobs > Settings… shows “Both sides, short edge”", var.get() == "Both sides, short edge", var.get())
window_shot.shot(dlg.dlg, OUT / "settings_dialog.png")
var.set("Both sides, long edge")
try:
    dlg.save()
except Exception as e:
    print("save:", e)
order = wo.load_order(order["_folder"])
check("…and can still change it (long edge)", walkin_print.settings_for(rules, order["items"][0], None)["sides"] == "long",
      order["items"][0].get("print"))

root.destroy()
print(f"{sum(results)} of {len(results)} passed")
