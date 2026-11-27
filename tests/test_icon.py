"""Every ORCA window and dialog: ORCA's icon and a dark title bar; the process's taskbar ID and the menu window's
relaunch details; a missing icon.ico doesn't stop ORCA (2026-11-16 icon, 2026-11-27_03: dialogs since 19_03 and the
Spare toners window, whose title bar was light). Temp folders; pictures of ORCA's own windows only (never the
taskbar or the screen)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, gc, json, os, shutil, subprocess, time, tkinter as tk

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
MODE = sys.argv[1] if len(sys.argv) > 1 else "icon"
TMP, OUT = helpers.dirs(__file__ if MODE == "icon" else __file__.replace(".py", "_noicon.py"))
ADMIN = TMP / "ORCA" / "ADMIN"
ADMIN.mkdir(parents=True)
for f in ("prices.json",) + (("icon.ico",) if MODE == "icon" else ()):
    shutil.copyfile(APP / f, ADMIN / f)
(ADMIN / "ORCA.bat").write_text("@echo off\r\nrem test copy\r\n", encoding="ascii")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
import price_sheet
price_sheet.test_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
helpers.use_temp_admin(ADMIN)
import appicon, mainmenu, driverprint, costs, toners, inventory as inv, inventory_screens as iscr
import walkin_orders as wo, walkin_pricing as P, walkin_prices, walkin_screens as ws
from tkinter import messagebox
from PIL import Image
import window_shot
helpers.no_printing()
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers"))
toners.TIMEOUT = 0.3
messagebox.askyesno = lambda *a, **k: True
messagebox.showwarning = lambda *a, **k: None

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:300])


# The start, as app.main does it
appicon.set_app_id()
root = tk.Tk(); root.withdraw()
appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.3


def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


def orange_in_title(win, name):
    """Orange pixels in the title bar's icon spot (the icon's folded corner is orange), from ORCA's own window."""
    path = OUT / f"_{name}.png"
    window_shot.shot(win, path)
    img = Image.open(path).convert("RGB")
    spot = list(img.crop((0, 0, 48, 40)).get_flattened_data())
    path.unlink()
    orange = sum(1 for r, g, b in spot if r > 200 and 90 < g < 190 and b < 90)
    white = sum(1 for r, g, b in spot if r > 240 and g > 240 and b > 240)
    print(f"  ({name}: {orange} orange, {white} white pixels in the icon spot)")
    return orange if white >= 20 else 0  # ORCA's icon: white pages with an orange corner


def dark(win):
    """Windows says the title bar is dark (DWMWA_USE_IMMERSIVE_DARK_MODE)."""
    hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
    v = ctypes.c_int(0)
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 20, ctypes.byref(v), ctypes.sizeof(v))
    return v.value == 1


def top(obj):
    for name in ("dlg", "win"):
        w = getattr(obj, name, None)
        if isinstance(w, (tk.Toplevel, tk.Tk)):
            return w
    raise AttributeError(f"{type(obj).__name__}: no window")


if MODE == "noicon":
    pump(1)
    check("icon.ico missing: ORCA still starts, the menu opens", menu.win.winfo_exists() and menu.win.state() == "normal")
    check("icon.ico missing: no orange icon (the default one)", orange_in_title(menu.win, "menu") == 0)
    root.destroy()
    print(f"{sum(results)}/{len(results)} passed")
    sys.exit(0)

buf = ctypes.c_wchar_p()
ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(buf))
check("the process has its own taskbar ID", buf.value == "ORCA.App", buf.value)

# ------------------------------------------------------------------ every screen and dialog
windows = {"menu": menu.win}
pump(1)


def opened(title_start):
    return next(w for w in reversed(root.winfo_children()) if isinstance(w, tk.Toplevel)
                and w.winfo_exists() and w.title().startswith(title_start))


menu.open_walkin(); pump(0.5); windows["Walk-in"] = opened("ORCA - Walk-in")
menu.open_printhub(); pump(1); windows["PrintHub"] = menu.printhub.win
menu.open_counter(); pump(0.5); windows["Counter"] = opened("ORCA - Counter")
menu.open_toners(); pump(0.5); windows["Data"] = opened("ORCA - Data")
prices = costs.PricesScreen(root, rules, on_back=lambda: None); windows["Prices"] = prices.win
windows["Password dialog"] = costs.PasswordDialog(menu.win, "new").dlg
data_screen = next(o for o in gc.get_objects() if isinstance(o, toners.TonersScreen))
pid = list(rules["printers"])[0]
spare = toners.SpareTonersWindow(data_screen)
windows["Spare toners"] = spare.dlg
windows["Spare toner edit"] = toners.EditTonerDialog(spare, None).dlg
windows["Toner replaced dialog"] = toners.ReplacedDialog(data_screen).dlg
windows["Address dialog"] = toners.AddressDialog(data_screen, pid).dlg

# Inventory (19_03 on): the screen and its dialogs
I = inv.Inventory()
pen = I.add({"name": "Pen blue", "category": "Writing", "stock": 3, "minimum": 5, "price": 0.5, "display": 4})
menu.open_inventory(); pump(0.6)
inv_screen = next(o for o in gc.get_objects() if isinstance(o, iscr.InventoryScreen) and o.win.winfo_exists())
windows["Inventory"] = inv_screen.win
for name, make in (("Item edit", lambda: iscr.ItemDialog(inv_screen, pen["id"])),
                   ("Delivery", lambda: iscr.QtyDialog(inv_screen, pen, "delivery")),
                   ("History", lambda: iscr.HistoryDialog(inv_screen, pen)),
                   ("Minimum", lambda: iscr.MinimumDialog(inv_screen, [pen["id"]], "Pen blue")),
                   ("Low stock", lambda: iscr.LowStockWindow(inv_screen)),
                   ("Categories", lambda: iscr.CategoriesWindow(inv_screen)),
                   ("On display", lambda: iscr.DisplayDialog(inv_screen, pen)),
                   ("Restock", lambda: iscr.RestockWindow(inv_screen)),
                   ("Sell", lambda: iscr.SellScreen(menu, on_back=lambda: None))):
    try:
        windows[name] = top(make())
    except Exception as e:
        check(f"{name}: opens", False, f"{type(e).__name__}: {e}")
csvf = TMP / "items.csv"
csvf.write_text("Name;Barcode;Stock\nPen red;5201234000011;4\n", encoding="utf-8-sig")
windows["Import list"] = top(iscr.ImportDialog(inv_screen, str(csvf)))

# Walk-in: the add-to-order question (24_02) and the number window
pl = walkin_prices.current()
c = wo.Customers().resolve("Maria Georgiou", "99 123 456", "", 0)
doc = {"kind": "document", "size": "A4", "pages": 1, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
       "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
o = wo.place([doc], P.price_order(pl, [doc]), dict(c, entered_name="Maria Georgiou", entered_phone="99 123 456"),
             "quote", None)
windows["Add to order question"] = ws.AddQuestion(menu.win, [o], [doc], None).dlg
windows["Order placed"] = ws.NumberDialog(menu.win, o).dlg

for name, win in windows.items():
    win.deiconify(); win.lift(); win.update()
pump(0.8)
for name, win in windows.items():
    n = orange_in_title(win, name.replace(" ", "_"))
    check(f"{name}: ORCA's icon and a dark title bar", n >= 1 and dark(win), f"{n} orange pixels, dark {dark(win)}")
spare.dlg.lift(); pump(0.5)
window_shot.shot(spare.dlg, OUT / "spare_toners_dark_title.png")

# ------------------------------------------------------------------ taskbar details on a window (for pinning)
from win32com.propsys import propsys, pscon
hwnd = ctypes.windll.user32.GetParent(menu.win.winfo_id())
store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
got = {k: store.GetValue(getattr(pscon, k)).GetValue() for k in
       ("PKEY_AppUserModel_ID", "PKEY_AppUserModel_RelaunchCommand", "PKEY_AppUserModel_RelaunchIconResource",
        "PKEY_AppUserModel_RelaunchDisplayNameResource")}
check("the menu window carries the taskbar ID, relaunch command, name and icon", got["PKEY_AppUserModel_ID"] == "ORCA.App"
      and got["PKEY_AppUserModel_RelaunchCommand"] == f'"{ADMIN / "ORCA.bat"}"'
      and got["PKEY_AppUserModel_RelaunchIconResource"] == f"{ADMIN / 'icon.ico'},0"
      and got["PKEY_AppUserModel_RelaunchDisplayNameResource"] == "ORCA", got)
root.destroy()

# ------------------------------------------------------------------ icon.ico missing (its own process)
r = subprocess.run([sys.executable, __file__, "noicon"], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=120)
for line in r.stdout.splitlines():
    if line.startswith(("PASS", "FAIL")):
        check(line[5:].split(" | ")[0], line.startswith("PASS"), line.split(" | ", 1)[-1])
if "icon.ico missing" not in r.stdout:
    check("icon.ico missing: the run finished", False, (r.stdout + r.stderr)[-300:])
print(f"{sum(results)}/{len(results)} passed")
