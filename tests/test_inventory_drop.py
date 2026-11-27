"""Handoff 2026-11-19_10: drop the Shopify file or an item list on the Inventory screen; a Choose file… button next to
every walk-in drop box. Temp copy of the folder layout; drops are sent as Windows' own WM_DROPFILES; the file window is
faked (it records where it opens); pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, gc, json, os, shutil, sys, time, tkinter as tk
from ctypes import wintypes
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
SRC = TMP / "Downloads"
ADMIN.mkdir(parents=True); SRC.mkdir(); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, inventory as inv, inventory_screens as iscr, mainmenu, printing, toners
import walkin_orders as wo, walkin_prices as wp, walkin_pricing as P, walkin_screens as ws
from tkinter import filedialog, messagebox, ttk
import pypdfium2 as pdfium
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
printing.send = lambda pdf, queue, settings=None: None
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
asked, warned = [], []
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message")) or True
messagebox.showwarning = lambda *a, **k: warned.append(k.get("message"))
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
OPENED = []  # (initialdir, several?) of each file window
PICK = {"files": []}
filedialog.askopenfilename = lambda **k: OPENED.append((k.get("initialdir"), False)) or (PICK["files"][0] if PICK["files"] else "")
filedialog.askopenfilenames = lambda **k: OPENED.append((k.get("initialdir"), True)) or tuple(PICK["files"])
ws.DOWNLOADS = SRC
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


WM_DROPFILES = 0x0233
k32 = ctypes.windll.kernel32
k32.GlobalAlloc.restype = ctypes.c_void_p; k32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
k32.GlobalLock.restype = ctypes.c_void_p; k32.GlobalLock.argtypes = (ctypes.c_void_p,)
k32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
u32 = ctypes.windll.user32
u32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
u32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))


def explorer_drop(widget, paths, dx=8, dy=6):
    win = widget.winfo_toplevel()
    win.lift(); win.update()
    hwnd = int(win.wm_frame(), 16)
    pt = wintypes.POINT(widget.winfo_rootx() + dx, widget.winfo_rooty() + dy)
    u32.ScreenToClient(hwnd, ctypes.byref(pt))
    data = ("\0".join(str(p) for p in paths) + "\0\0").encode("utf-16-le")
    h = k32.GlobalAlloc(0x0042, 20 + len(data))
    ptr = k32.GlobalLock(h)
    header = (ctypes.c_uint32 * 5)(20, pt.x & 0xFFFFFFFF, pt.y & 0xFFFFFFFF, 0, 1)
    ctypes.memmove(ptr, header, 20)
    ctypes.memmove(ptr + 20, data, len(data))
    k32.GlobalUnlock(h)
    u32.PostMessageW(hwnd, WM_DROPFILES, h, 0)
    pump(1.2)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def close_popups():
    for w in widgets(root):
        if isinstance(w, tk.Toplevel) and w.title() in ("End of day: Shopify stock", "Restock") or (
                isinstance(w, tk.Toplevel) and w.title().startswith("Import list")):
            w.destroy()
    pump(0.2)


HEADER = ["Handle", "Title", "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name",
          "Option3 Value", "SKU", "HS Code", "COO", "Location", "Bin name", "Incoming (not editable)",
          "Unavailable (not editable)", "Committed (not editable)", "Available (not editable)", "On hand (current)",
          "On hand (new)"]
T = {"t": time.time() - 5 * 86400}


def shopify(name, pen):
    path = SRC / name
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerow(["pen-blue", "Pen blue", "Title", "Default Title", "", "", "", "", "5201234000011", "", "", "Shop", "",
                    0, 0, 0, pen, pen, pen])
    T["t"] += 86400
    os.utime(path, (T["t"], T["t"]))
    return path


# ------------------------------------------------------------------ the Inventory screen's drop box
menu.open_inventory(); pump(0.6)
S = [x for x in gc.get_objects() if isinstance(x, iscr.InventoryScreen) and x.win.winfo_exists()][-1]
S.win.geometry("1300x880+10+10"); pump(0.4)
check("the Inventory screen has a drop box: “Drop the Shopify stock file or an item list here”",
      "Drop the Shopify stock file or an item list here" in S.drop_box.cget("text")
      and str(S.drop_box.cget("highlightbackground")) == ws.theme.PRIMARY)
window_shot.shot(S.win, OUT / "inventory_drop_box.png")
explorer_drop(S.drop_box, [shopify("export_1.csv", 20)], dx=60, dy=10)
check("a Shopify export dropped on the box runs the end-of-day load (first load)",
      S.inventory.data.get("shopify_load", {}).get("file") == "export_1.csv" and S.inventory.by_name("Pen blue")["stock"] == 20)
close_popups()
explorer_drop(S.drop_box, [shopify("export_2.csv", 14)], dx=60, dy=10)
rep = [x for x in gc.get_objects() if isinstance(x, iscr.LoadReport) and x.dlg.winfo_exists()]
check("…a second one: the report with Sold / Came in", rep and rep[-1].rows["sold"] == [("Pen blue", 6)])
close_popups()


def import_dialogs():
    return [x for x in gc.get_objects() if isinstance(x, iscr.ImportDialog) and x.dlg.winfo_exists()]


import xlsx_maker as mx
xlsx = SRC / "items.xlsx"
mx.make_xlsx(xlsx, {"Items": [["Name", "Barcode", "Price"], ["Stapler", 5201234000059, 3.5]]})
explorer_drop(S.drop_box, [xlsx], dx=60, dy=10)
d = import_dialogs()
check("an item-list .xlsx dropped on the box opens the Import column picker", d and d[-1].columns()["name"] == 0)
close_popups()
plain = SRC / "list.csv"
plain.write_text("Name;Barcode;Stock\nEraser;5201234000097;30\n", encoding="utf-8-sig")
explorer_drop(S.drop_box, [plain], dx=60, dy=10)
d = import_dialogs()
check("a .csv that isn't Shopify opens the Import column picker", d and d[-1].columns()["name"] == 0)
close_popups()
end_btn = [b for b in widgets(S.win, "TButton") if b.cget("text").startswith("End of day")][0]
imp_btn = [b for b in widgets(S.win, "TButton") if b.cget("text") == "Import list…"][0]
explorer_drop(end_btn, [shopify("export_3.csv", 11)])
check("dropped on the End of day button: the same (the load runs)",
      S.inventory.data["shopify_load"]["file"] == "export_3.csv")
close_popups()
explorer_drop(imp_btn, [plain])
check("dropped on the Import list button: the same (the column picker)", bool(import_dialogs()))
close_popups()
folder = SRC / "a folder"; folder.mkdir()
empty = SRC / "empty.csv"; empty.write_text("")
pdf = SRC / "doc.pdf"; pdf.write_bytes(b"%PDF-1.4 x")
before = json.dumps(S.inventory.data, sort_keys=True)
for paths, msg in (([plain, xlsx], "Drop one file at a time."), ([folder], "is a folder"), ([empty], "is empty"),
                   ([pdf], "drop a .csv or .xlsx file")):
    warned.clear()
    explorer_drop(S.drop_box, paths, dx=60, dy=10)
    check(f"refused with its message: {msg}", warned and msg in warned[-1] and not import_dialogs()
          and json.dumps(S.inventory.data, sort_keys=True) == before, warned)
OPENED.clear(); PICK["files"] = []
S.load_shopify(); S.import_list(); pump(0.2)
check("the buttons' file windows open on Downloads", OPENED == [(str(SRC), False), (str(SRC), False)], OPENED)
S.back(); pump(0.3)

# ------------------------------------------------------------------ walk-in: Choose file… next to every drop box
pdfs = []
for k in range(3):
    p = SRC / f"part_{k + 1}.pdf"
    doc = pdfium.PdfDocument.new()
    for _ in range(k + 1):
        doc.new_page(595, 842)
    doc.save(str(p)); doc.close()
    t = time.time() - 60; os.utime(p, (t, t))
    pdfs.append(p)
q = ws.QuoteScreen(menu, "email", on_back=menu.show_menu)
q.win.geometry("1320x940+10+10"); pump(0.8)
btn = [b for b in widgets(q.box, "Button") if b.cget("text") == "Choose file…"]
check("Add Email: the Add-item drop box has a Choose file… button", len(btn) == 1)
OPENED.clear(); PICK["files"] = [str(p) for p in pdfs]
btn[0].invoke(); pump(0.3)
check("…3 PDFs picked with Document make the same 3-file list a drop makes (window on Downloads, several allowed)",
      q.held == [str(p) for p in pdfs] and OPENED == [(str(SRC), True)]
      and any("3 files: Add item makes 3 document items" in w.cget("text") for w in widgets(q.box, "Label")), q.held)
window_shot.shot(q.win, OUT / "add_email_drop_box_with_button.png")
q.add_item(); pump(0.2)
q.cust_vars["name"].set("Drop Test"); q.cust_vars["phone"].set("99 313 131"); pump(0.2)
q.place(); pump(3)
order = wo.load_order(wo.open_dir() / f"#{q.placed_number}")
for w in widgets(root):
    if isinstance(w, tk.Toplevel) and w.title() == "ORCA - order placed":
        w.destroy()
q.back(); pump(0.3)
o = wo.place([{"kind": "document", "size": "A4", "pages": 1, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
               "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}],
             P.price_order(wp.current(), [{"kind": "document", "size": "A4", "pages": 1, "copies": 1, "color": "bw",
                                           "color_pages": "", "sides": "single", "per_side": 1, "paper": "Normal 80 gsm",
                                           "finish": "none", "lam": False, "lam_sheets": 0}]),
             dict(wo.Customers().resolve("Drop Two", "99 414 141", "", 0), entered_name="Drop Two",
                  entered_phone="99 414 141"), "quote", None)
D = ws.OrderDetailsScreen(menu, o["number"], on_back=lambda: None)
D.win.geometry("1200x900+10+10"); pump(2)
areas = [w for w in widgets(D.scroll.inner) if hasattr(w, "choose")]
check("Orders > Details…: each item's drop box has a Choose file… button", len(areas) == 1
      and any(b.cget("text") == "Choose file…" for b in widgets(areas[0], "TButton")))
OPENED.clear(); PICK["files"] = [str(pdfs[1])]
areas[0].choose(); pump(3)
check("…a picked file lands in that item's folder (one file for a document: the window allows one)",
      (o["_folder"] / o["items"][0]["folder"] / "part_2.pdf").exists() and OPENED == [(str(SRC), False)], OPENED)
warned.clear()
PICK["files"] = [str(empty)]
areas[0].choose(); pump(1)
check("…a picked empty file gets the same message as a drop", warned and "empty" in warned[-1].lower(), warned)
D.win.destroy()
print(f"{sum(results)}/{len(results)} passed")
