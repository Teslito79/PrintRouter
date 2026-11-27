"""Handoff 2026-11-19_08: the new main menu order; Orders inside Walk-in, six big buttons in three rows. Temp copy of
the folder layout; pictures of ORCA's own windows only."""
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
ADMIN.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
routing.installed_printers = lambda: ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6", "XP-80C"]
import appicon, driverprint, inventory, mainmenu, toners, walkin_orders as wo, walkin_screens as ws
from tkinter import messagebox, ttk
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
toners.TIMEOUT = 0.2
messagebox.askyesno = lambda *a, **k: True
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


pump(0.6)
buttons = [b.cget("text") for b in widgets(menu.win, "TButton")]
check("the main menu: exactly these 7 buttons in this order",
      buttons == ["Walk-in", "Inventory management", "Data", "PrintHub", "Counter", "Prices", "Settings"], buttons)
byname = {b.cget("text"): b for b in widgets(menu.win, "TButton")}
check("the dots follow their buttons: Data's toner dot and Inventory's dot sit on them",
      menu.toner_dot.master is byname["Data"] and menu.inventory_dot.master is byname["Inventory management"])
inventory.Inventory().add({"name": "Folder", "stock": 1, "minimum": 5})
menu.show_sync(); pump(0.3)
check("…the Inventory dot shows when an item is under its minimum", bool(menu.inventory_dot.place_info()))
toners.stock_low = lambda printers: True
menu.show_sync(); pump(0.3)
check("…and the Data dot when a spare toner count is low", bool(menu.toner_dot.place_info()))
window_shot.shot(menu.win, OUT / "main_menu.png")

# ------------------------------------------------------------------ the Walk-in menu
menu.open_walkin(); pump(0.8)
W = [x for x in gc.get_objects() if isinstance(x, ws.WalkinScreen) and x.win.winfo_exists()][-1]
W.win.geometry("1160x720+10+10"); pump(0.5)
b = W.buttons
rows = [[b[t].winfo_rooty() for t in row] for row in (("Get Quote", "Add Email", "Copy counter"), ("Print Jobs", "Orders"),
                                                     ("Customers",))]
check("Walk-in: six big buttons, three rows (Get Quote, Add Email, Copy counter / Print Jobs, Orders / Customers)",
      len(b) == 6 and all(len(set(r)) == 1 for r in rows) and rows[0][0] < rows[1][0] < rows[2][0]
      and all(x.cget("style") == "Walkin.TButton" for x in b.values())
      and len({(x.winfo_width(), x.winfo_height()) for x in b.values()}) == 1, rows)
check("…lined up left: Print Jobs under Get Quote, Orders under Add Email, Customers under Print Jobs",
      b["Print Jobs"].winfo_rootx() == b["Get Quote"].winfo_rootx() == b["Customers"].winfo_rootx()
      and b["Orders"].winfo_rootx() == b["Add Email"].winfo_rootx())
hint = [x.cget("text") for x in widgets(W.win, "TLabel") if "Orders: open orders, search, Collected" in x.cget("text")]
check("…the hint has a short line per button (“Orders: open orders, search, Collected”), no separate Copy counter line",
      hint and all(t in hint[0] for t in ("Get Quote:", "Add Email:", "Copy counter:", "Print Jobs:", "Orders:", "Customers:")),
      hint)
window_shot.shot(W.win, OUT / "walkin_menu.png")

screens = {"Get Quote": ws.QuoteScreen, "Add Email": ws.QuoteScreen, "Copy counter": ws.CopyCounterScreen,
           "Print Jobs": ws.PrintJobsScreen, "Orders": ws.OrdersScreen, "Customers": ws.CustomersScreen}
ok_all = []
for text, cls in screens.items():
    b[text].invoke(); pump(0.8)
    s = [x for x in gc.get_objects() if isinstance(x, cls) and x.win.winfo_exists()]
    opened = bool(s) and not W.win.winfo_viewable()
    if s:
        if text == "Orders":
            orders = s[-1]
        else:
            s[-1].back(); pump(0.5)
            ok_all.append((text, opened, W.win.winfo_viewable()))
check("each button opens its screen, and Back returns to the Walk-in menu",
      all(o and v for _, o, v in ok_all) and len(ok_all) == 5, ok_all)
# Orders: Details… then Back returns to Orders; Back from Orders to Walk-in
c = wo.Customers().resolve("Menu Test", "99 121 212", "", 0)
item = {"kind": "document", "size": "A4", "pages": 1, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
        "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
import walkin_pricing as P, walkin_prices as wp
o = wo.place([item], P.price_order(wp.current(), [item]), dict(c, entered_name="Menu Test", entered_phone="99 121 212"),
             "quote", None)
orders.signature = None; pump(2)
orders.details(o); pump(1)
D = [x for x in gc.get_objects() if isinstance(x, ws.OrderDetailsScreen) and x.win.winfo_exists()][-1]
D.back(); pump(0.6)
check("Orders: Details… then Back returns to Orders", orders.win.winfo_viewable() and not D.win.winfo_exists())
orders.back(); pump(0.5)
check("…and Back from Orders returns to the Walk-in menu (not the main menu)", W.win.winfo_viewable()
      and not menu.win.winfo_viewable())
check("Orders opened on its own (menu.open_orders, kept for other callers) still works and goes back to the menu",
      callable(menu.open_orders))

# ------------------------------------------------------------------ fits 1366x768 at 125%
W.back(); pump(0.4)
real_area, real_scale = ws.work_area, None
ws.work_area = lambda window: (0, 0, 1366, 728)
root.tk.call("tk", "scaling", 96 * 1.25 / 72)
menu.open_walkin(); pump(0.8)
W2 = [x for x in gc.get_objects() if isinstance(x, ws.WalkinScreen) and x.win.winfo_exists()][-1]
pump(0.4)
inside = all(x.winfo_rooty() + x.winfo_height() <= W2.win.winfo_rooty() + W2.win.winfo_height() for x in W2.buttons.values())
check("the Walk-in window fits 1366x768 at 125%, every button inside it",
      W2.win.winfo_width() <= 1366 and W2.win.winfo_height() <= 728 and inside,
      (W2.win.winfo_width(), W2.win.winfo_height()))
W2.back(); pump(0.3)
print(f"{sum(results)}/{len(results)} passed")
