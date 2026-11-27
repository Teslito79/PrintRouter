"""Handoff 2026-11-17_11: Get Quote / Add Email fit the screen. Screen sizes are simulated with the work area (what
the taskbar leaves) and Windows scaling with Tk's scaling (150%: 2.0, 125%: 1.667, 100%: 1.333). Temp copy of the
folders, the trial price sheet, pictures of ORCA's own windows only. Files are dropped as Explorer's WM_DROPFILES."""
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
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):  # the trial price list: every price 0
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_screens as ws, walkin_catalogue as cat
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order (as before)
from tkinter import messagebox
import pypdfium2 as pdfium
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
warned = []
messagebox.showwarning = lambda **k: warned.append(k["message"])
messagebox.askyesno = lambda *a, **k: True
ws.ask_keep = lambda parent: True
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:400])


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
REAL_WORK = ws.work_area(root)


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


def explorer_drop(widget, paths, dx=40, dy=20):
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


def fully_visible(w, win, clip=None):
    """The widget is mapped, not squashed, inside the window's client area (and inside `clip` if given)."""
    if not w.winfo_ismapped():
        return False
    x, y = w.winfo_rootx() - win.winfo_rootx(), w.winfo_rooty() - win.winfo_rooty()
    inside = x >= 0 and y >= 0 and x + w.winfo_width() <= win.winfo_width() + 1 and y + w.winfo_height() <= win.winfo_height() + 1
    if clip is not None:
        cx, cy = clip.winfo_rootx(), clip.winfo_rooty()
        inside = inside and w.winfo_rootx() >= cx and w.winfo_rooty() >= cy \
            and w.winfo_rootx() + w.winfo_width() <= cx + clip.winfo_width() + 1 \
            and w.winfo_rooty() + w.winfo_height() <= cy + clip.winfo_height() + 1
    return inside and w.winfo_height() >= w.winfo_reqheight() - 2


def find_button(win, text):
    stack = [win]
    while stack:
        w = stack.pop()
        if w.winfo_class() == "TButton" and w.cget("text") == text:
            return w
        stack += w.winfo_children()
    return None


def entries_of(frame):
    out, stack = [], [frame]
    while stack:
        w = stack.pop()
        if w.winfo_class() == "TEntry":
            out.append(w)
        stack += w.winfo_children()
    return out


most = max(cat.PRODUCTS, key=lambda p: len(p["options"]))
CASES = [("1366x768 at 100%", (0, 0, 1366, 728), 96 / 72), ("1600x900 at 100%", (0, 0, 1600, 860), 96 / 72),
         ("1920x1080 at 100%", (0, 0, 1920, 1032), 96 / 72), ("1920x1080 at 125%", (0, 0, 1920, 1032), 120 / 72),
         ("1920x1080 at 150%", (0, 0, 1920, 1032), 144 / 72)]
for label, area, scaling in CASES:
    ws.work_area = lambda window, a=area: a
    root.tk.call("tk", "scaling", scaling)
    for mode in ("email", "quote"):
        Q = ws.QuoteScreen(menu, mode, on_back=menu.show_menu)
        pump(0.8)
        win = Q.win
        inside_screen = (win.winfo_rootx() >= area[0] and win.winfo_rooty() >= area[1]
                         and win.winfo_rootx() + win.winfo_width() <= area[2]
                         and win.winfo_rooty() + win.winfo_height() <= area[3])
        cust = entries_of(Q.known.master.master)
        for what in ("Document", most["name"]):
            Q.what.set(what); Q.what_changed(); pump(0.4)
            need = {"Add item": Q.add_btn, "the drop box": Q.box, "Discard": find_button(win, "Discard"),
                    "Place order": find_button(win, "Place order")}
            for k, e in enumerate(cust):
                need[f"customer field {k + 1}"] = e
            hidden = [n for n, w in need.items() if not fully_visible(w, win)]
            box_in_frame = fully_visible(Q.add_btn, win, Q.editor) and fully_visible(Q.box, win, Q.editor)
            check(f"{label}, {'Add Email' if mode == 'email' else 'Get Quote'}, {what}: the window fits the screen; "
                  f"Add item, the drop box, the customer fields, Discard and Place order fully visible",
                  inside_screen and not hidden and box_in_frame and len(cust) == 3,
                  (win.winfo_geometry(), hidden, box_in_frame))
            if Q.form.needed():
                before = Q.form.canvas.yview()[0]
                field = Q.options.winfo_children()[0]
                field.event_generate("<MouseWheel>", delta=-120); pump(0.1)
                cb = next(w for w in Q.options.winfo_children() if w.winfo_class() == "TCombobox")
                value = str(tk.StringVar(value="").get())
                cb_value = cb.get()
                cb.event_generate("<MouseWheel>", delta=-120); pump(0.1)
                check(f"{label}: the form is longer than the room: the wheel scrolls it (over a combobox too, "
                      f"without changing its value), the scrollbar shows",
                      Q.form.canvas.yview()[0] > before and cb.get() == cb_value and Q.form.bar.winfo_ismapped(),
                      (before, Q.form.canvas.yview(), cb_value, cb.get()))
            elif what == "Document":
                check(f"{label}: everything fits: no scrollbar", not Q.form.bar.winfo_ismapped())
        if label in ("1366x768 at 100%", "1920x1080 at 100%") and mode == "email":
            Q.what.set("Document"); Q.what_changed(); pump(0.3)
            window_shot.shot(win, OUT / f"add_email_document_{label.split()[0]}.png")
        if label == "1920x1080 at 150%" and mode == "email":
            Q.what.set("Document"); Q.what_changed(); pump(0.3)
            window_shot.shot(win, OUT / "add_email_document_1920x1080_150pct.png")
        if label in ("1366x768 at 100%", "1920x1080 at 150%") and mode == "quote":
            # use it: a document item, a file dropped on the box, Place order, no resizing
            size_before = win.winfo_geometry()
            Q.what.set("Document"); Q.what_changed(); pump(0.2)
            d = pdfium.PdfDocument.new(); [d.new_page(595, 842) for _ in range(3)]
            pdf = SRC / f"letter {label[:4]}.pdf"; d.save(str(pdf)); d.close()
            explorer_drop(Q.box, [pdf])
            Q.add_item(); pump(0.3)
            rows = [r for r in ("0", "w:0:0", "w:0:1", "f:0:0") if Q.tree.exists(r)]
            seen = [r for r in rows if Q.tree.bbox(r)]
            check(f"{label}: the item list shows the item with its working and file lines (it scrolls for more)",
                  len(rows) == 4 and seen == rows, (rows, seen, Q.tree.winfo_height()))
            Q.cust_vars["name"].set("Fit Test"); Q.cust_vars["phone"].set("99 555 777"); pump(0.2)
            before = set(wo.used_numbers())
            find_button(win, "Place order").invoke(); pump(1.5)
            new = set(wo.used_numbers()) - before
            o = wo.load_order(wo.open_dir() / f"#{new.pop()}") if new else None
            files = sorted(p.name for p in (o["_folder"] / o["items"][0]["folder"]).iterdir()) if o else []
            check(f"{label}: add a document, drop a file on the box (Pages 3), place the order, with no resizing",
                  o and o["items"][0]["pages"] == 3 and pdf.name in files and win.winfo_geometry() == size_before
                  and not warned, (size_before, win.winfo_geometry(), files, warned))
            for w in win.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()
        Q.back(); pump(0.2)
    # the other walk-in windows fit too
    for name, make in (("Walk-in", lambda: ws.WalkinScreen(menu, on_back=menu.show_menu)),
                       ("Customers", lambda: ws.CustomersScreen(menu, on_back=menu.show_menu)),
                       ("Copy counter", lambda: ws.CopyCounterScreen(menu, on_back=menu.show_menu)),
                       ("Orders", lambda: ws.OrdersScreen(menu, on_back=menu.show_menu)),
                       ("Print Jobs", lambda: ws.PrintJobsScreen(menu, on_back=menu.show_menu))):
        s = make(); pump(0.5)
        w = s.win
        fits = (w.winfo_rootx() >= area[0] and w.winfo_rooty() >= area[1]
                and w.winfo_rootx() + w.winfo_width() <= area[2] and w.winfo_rooty() + w.winfo_height() <= area[3])
        check(f"{label}: {name} fits the screen", fits and fully_visible(s.back_btn, w), w.winfo_geometry())
        s.back(); pump(0.2)
root.tk.call("tk", "scaling", 96 / 72)
ws.work_area = lambda window: REAL_WORK
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu); pump(0.5)
g = Q.win.winfo_geometry()
check("on this PC's own 1920x1080 screen: Get Quote opens at today's size, capped (1320x900)", g.startswith("1320x900"), g)
Q.back(); pump(0.2)
print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
