"""Handoff 2026-11-19_04: many files in one drop (Get Quote / Add Email) and a simple Orders list with Details….
Temp copy of the folder layout; drops are sent as Windows' own WM_DROPFILES; Office page counting is pretended
(count_pages faked: Word isn't run in the test); pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, json, os, shutil, sys, time, tkinter as tk
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
SRC = TMP / "Desktop"
ADMIN.mkdir(parents=True); SRC.mkdir(); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico"):
    shutil.copyfile(APP / f, ADMIN / f)
import price_sheet
price_sheet.website_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_prices, walkin_pricing as P
import walkin_screens as ws
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
from PIL import Image
import window_shot

ws.ask_keep = lambda parent: True

ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
asked, warned = [], []
messagebox.showwarning = lambda **k: warned.append(k["message"])
ANSWER = {"yes": True}
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message") or a[1]) or ANSWER["yes"]
COUNTED = {}
ws.count_pages = lambda path, size: (time.sleep(0.3), COUNTED.get(Path(path).name))[1]
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


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


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)
    for _ in range(3):
        root.update(); time.sleep(0.02)


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


def labels(w):
    return [x.cget("text") for x in widgets(w) if x.winfo_class() in ("Label", "TLabel")]


def inside(inner, outer):
    a = (inner.winfo_rootx(), inner.winfo_rooty(), inner.winfo_rootx() + inner.winfo_width(),
         inner.winfo_rooty() + inner.winfo_height())
    b = (outer.winfo_rootx(), outer.winfo_rooty(), outer.winfo_rootx() + outer.winfo_width(),
         outer.winfo_rooty() + outer.winfo_height())
    return a[0] >= b[0] and a[1] >= b[1] and a[2] <= b[2] and a[3] <= b[3]


PAGES = [3, 7, 1, 12, 5, 2, 9, 4, 6, 10]
pdfs = [pdf(SRC / f"Report_{k + 1:02d}.pdf", n) for k, n in enumerate(PAGES)]

# ------------------------------------------------------------------ 10 PDFs at once
q = ws.QuoteScreen(menu, "email", on_back=menu.show_menu)
q.win.geometry("1320x940+10+10"); pump(1)
v = q.option_vars
v["sides"].set("Both sides"); v["copies"].set("2")
explorer_drop(q.box, pdfs)
check("10 PDFs dropped at once with Document: all kept in the box, in the order dropped",
      q.held == [str(p) for p in pdfs], [Path(x).name for x in q.held])
check("…the box says “10 files: Add item makes 10 document items with these settings”",
      "10 files: Add item makes 10 document items with these settings" in labels(q.box), labels(q.box)[:2])
check("…Pages shows “from each file” and can't be typed", v["pages"].get() == "from each file"
      and q.pages_entry.instate(["disabled"]))
check("…colour pages can't be listed: Colour offers B&W and Colour only",
      tuple(q.colour_box.cget("values")) == ("B&W", "Colour"), q.colour_box.cget("values"))
check("…the file list scrolls inside the box; Add item and Place order stay on the screen",
      q.box_files.winfo_height() <= ws.QuoteScreen.BOX_ROWS * 26 + 4 and inside(q.add_btn, q.win)
      and inside([b for b in widgets(q.win, "TButton") if b.cget("text") == "Place order"][0], q.win),
      q.box_files.winfo_height())
window_shot.shot(q.win, OUT / "drop_box_10_files.png")
q.add_item(); pump(0.5)
check("Add item: 10 document items, each with its own pages and the same settings",
      len(q.items) == 10 and [it["pages"] for it in q.items] == PAGES
      and all(it["sides"] == "double" and it["copies"] == 2 and it["color"] == "bw" for it in q.items)
      and [d for d in q.drops] == [[str(p)] for p in pdfs], [it["pages"] for it in q.items])
check("…each item is named by its file", P.describe(q.items[3]).startswith("Document A4, Report_04.pdf, 12 pages x 2"),
      P.describe(q.items[3]))
copies = sum(PAGES) * 2
tier = walkin_prices.current().tier_of(copies)
check(f"…priced together for the tier ({copies} A4 B&W copies over the order: tier {tier})",
      all(f"(tier {tier})" in line["working"][1] for line in q.priced["lines"]), q.priced["lines"][0]["working"])
window_shot.shot(q.win, OUT / "item_list_after_add.png")
q.cust_vars["name"].set("Maria Georgiou"); q.cust_vars["phone"].set("99 123 456"); pump(0.2)
q.place(); pump(3)
order = wo.load_order(wo.open_dir() / f"#{q.placed_number}")
check("Place order puts each file in its own item folder",
      [sorted(p.name for p in (order["_folder"] / it["folder"]).iterdir() if p.suffix == ".pdf") for it in order["items"]]
      == [[p.name] for p in pdfs], [it["folder"] for it in order["items"]][:3])
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w.title() == "ORCA - order placed":
        w.destroy()

# ------------------------------------------------------------------ drops in steps, ✕, mixed, folder, duplicates
explorer_drop(q.box, pdfs[:3]); explorer_drop(q.box, pdfs[3:5])
check("drops in steps: 3 PDFs, then 2 more, before Add item: 5 held", len(q.held) == 5)
q.unhold(1); pump(0.2)
check("…an ✕ takes one off (4 left)", [Path(x).name for x in q.held] == ["Report_01.pdf", "Report_03.pdf",
                                                                        "Report_04.pdf", "Report_05.pdf"])
q.cancel_edit(); pump(0.2)
img = SRC / "photo.jpg"; Image.new("RGB", (60, 40), "red").save(img)
docx = SRC / "Letter.docx"; docx.write_bytes(b"PK\x03\x04 pretend word file")
docx2 = SRC / "Notes.docx"; docx2.write_bytes(b"PK\x03\x04 another pretend word file")
COUNTED["Notes.docx"] = 4
folder = SRC / "a folder"; folder.mkdir()
warned.clear()
explorer_drop(q.box, [pdfs[0], pdfs[1], img, docx, docx2, folder, pdfs[0]])
check("a folder (and a second copy of a file) in the drop is refused with a message; the rest are taken",
      len(q.held) == 5 and warned and "folder" in warned[-1].lower() and "already added" in warned[-1], warned[-1:])
q.add_item(); pump(0.2)
items = q.items
check("mixed drop: the image is 1 page, a Word file whose pages ORCA can't count says “type the pages”",
      items[2]["pages"] == 1 and items[3].get("pages_unknown") and "type the pages" in P.describe(items[3]),
      [(it.get("source_name"), it["pages"], it.get("pages_unknown")) for it in items])
pump(2, until=lambda: not items[4].get("pages_unknown"))
check("…a Word file ORCA can count gets its pages in the background (Notes.docx: 4)",
      items[4]["pages"] == 4 and not items[4].get("pages_unknown"))
warned.clear()
q.cust_vars["name"].set("Nikos P."); q.cust_vars["phone"].set("99 222 333"); pump(0.2)
before = len(wo.list_open())
q.place(); pump(0.5)
check("…Place order is refused until the pages are typed",
      len(wo.list_open()) == before and warned and "type the pages of Letter.docx" in warned[-1], warned[-1:])
q.tree.selection_set("3"); q.edit_item(); pump(0.2)
q.option_vars["pages"].set("6"); q.add_item(); pump(0.2)
check("…typed with Edit: the item has its pages and keeps its name",
      q.items[3]["pages"] == 6 and not q.items[3].get("pages_unknown") and q.items[3].get("source_name") == "Letter.docx",
      q.items[3])
q.place(); pump(3)
check("…then Place order works", len(wo.list_open()) == before + 1)
for w in root.winfo_children():
    if isinstance(w, tk.Toplevel) and w.title() == "ORCA - order placed":
        w.destroy()

# ------------------------------------------------------------------ one PDF: as today
explorer_drop(q.box, [pdfs[3]])
check("one PDF works as today: Pages filled from it and typeable, the usual box wording",
      q.option_vars["pages"].get() == "12" and q.pages_entry.instate(["!disabled"])
      and "files: Add item makes" not in " ".join(labels(q.box)), labels(q.box))
q.option_vars["pages"].set("11"); q.add_item(); pump(0.2)
check("…one item, with the typed pages", len(q.items) == 1 and q.items[0]["pages"] == 11
      and not q.items[0].get("source_name"))

# ------------------------------------------------------------------ several files on an item in the list
asked.clear()
explorer_drop(q.tree, pdfs[5:8], dx=60, dy=34)
check("several files dropped on an item in the list ask once (“Add 3 more items like item 1?”) and add the items",
      asked == ["Add 3 more items like item 1?"] and len(q.items) == 4
      and [it.get("source_name") for it in q.items[1:]] == ["Report_06.pdf", "Report_07.pdf", "Report_08.pdf"]
      and q.drops[0] == [str(pdfs[3])] and q.items[1]["sides"] == q.items[0]["sides"], (asked, len(q.items)))
q.tree.selection_set("0"); q.edit_item(); pump(0.2)
asked.clear()
explorer_drop(q.box, pdfs[8:10])
check("…and while editing an item: “Add 2 more items like item 1?”, the edited item keeps its own file",
      asked == ["Add 2 more items like item 1?"] and len(q.items) == 6 and q.drops[0] == [str(pdfs[3])], asked)
q.back(); pump(0.3)

# ------------------------------------------------------------------ the simple Orders list
o = menu.open_orders(); pump(1.5)
import gc
S = [x for x in gc.get_objects() if isinstance(x, ws.OrdersScreen) and x.win.winfo_exists()][-1]
S.win.geometry("1200x900+10+10"); pump(1.5)
texts = labels(S.scroll.inner)
first = order["number"]
check("Orders: one line per order with the number, the customer, the status and the date placed",
      f"#{first}" in texts and "Maria Georgiou · 99 123 456" in texts
      and any(t.startswith("Ready to print") or t.startswith("Waiting for PDF") for t in texts), texts[:12])
check("…no items, files, drop zones, working lines or prices in the list",
      not any("Report_" in t or "copies x" in t or "EUR" in t or t.startswith("⤓") for t in texts), texts)
buttons = [b.cget("text") for b in widgets(S.scroll.inner, "TButton")]
check("…each order keeps Open folder, Collected, Cancel order, and has Details…",
      all(buttons.count(t) == 2 for t in ("Details…", "Open folder", "Collected", "Cancel order")), buttons)
window_shot.shot(S.win, OUT / "orders_list.png")
S.search.set("Nikos"); pump(2)
texts2 = labels(S.scroll.inner)
check("…the search box works", "Nikos P. · 99 222 333" in texts2 and "Maria Georgiou · 99 123 456" not in texts2)
S.search.set(""); pump(2)
S.details(order); pump(2)
D = [x for x in gc.get_objects() if isinstance(x, ws.OrderDetailsScreen) and x.win.winfo_exists()][-1]
D.win.geometry("1200x900+10+10"); pump(1.5)
dt = labels(D.scroll.inner)
check("Details… shows the items with their files, drop zones and working lines",
      any("Report_01.pdf" in t for t in dt) and any(t.startswith("⤓") for t in dt) and any("copies x" in t for t in dt),
      dt[:8])
window_shot.shot(D.win, OUT / "order_details.png")
target = [x for x in widgets(D.scroll.inner, "Label") if x.cget("text").startswith("⤓")][2]
new = pdf(SRC / "Replacement.pdf", 2)
asked.clear()
explorer_drop(target, [new])
pump(3, until=lambda: (order["_folder"] / order["items"][2]["folder"] / "Replacement.pdf").exists())
check("…a file dropped there lands in the right item (item 3)",
      (order["_folder"] / order["items"][2]["folder"] / "Replacement.pdf").exists(), asked)
D.back(); pump(1)
check("…Back goes back to the list", S.win.winfo_viewable() and not D.win.winfo_exists())
asked.clear()
S.collected(wo.load_order(order["_folder"])); pump(1)
check("Collected still works from the list", not (wo.open_dir() / f"#{first}").exists() and asked)
print(f"{sum(results)}/{len(results)} passed")
