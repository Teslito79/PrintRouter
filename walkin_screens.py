"""The walk-in screens (2026-11-17): Walk-in (Get Quote, Add Email, Print Jobs), the quote / email order screen,
Print Jobs and Orders. Data in walkin_orders, prices in walkin_prices / walkin_pricing, printing in walkin_print,
the print queue in walkin_queue. Walk-in orders are never mixed with PrintHub (website) orders.

Files can be dropped from Explorer onto an item wherever an open order's items show (filedrop.py): they are copied
into the item's folder (the original stays), or kept with the quote until Place order.
"""
import ctypes
import datetime
import math
import os
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import messagebox, ttk

import analyze
import copier_queue
import copy_counter
import costs
import filedrop
import theme
import walkin_catalogue as cat
import walkin_orders as wo
import walkin_prices
import walkin_pricing
import walkin_print
import walkin_queue

FONT = costs.FONT
COLOUR_CHOICES = {"B&W": "bw", "Colour": "color", "Some pages in colour": "mixed"}
SIDE_CHOICES = {"One side": "single", "Both sides": "double"}
FINISH_CHOICES = {"None": "none", "Staple": "staple", "Spiral": "spiral"}


def euro(x):
    return f"EUR {x:,.2f}"


def rounding_buttons(parent, on_press, width=10):
    """The six rounding buttons, shared by Get Quote / Add Email and the Copy counter so they can't drift apart
    (Tesla, 2026-11-17: Up to 1 | 5 | 10 above, Down to 1 | 5 | 10 below, No rounding on the right over both rows).
    on_press(mode or None). Returns (frame, {mode: button})."""
    frame = ttk.Frame(parent)
    buttons = {}
    for mode, (text, way, step) in walkin_pricing.ROUNDINGS.items():
        b = ttk.Button(frame, text=text, width=width, command=lambda m=mode: on_press(m))
        b.grid(row=0 if way > 0 else 1, column=(1, 5, 10).index(step), padx=(0, 4), pady=(0, 3))
        buttons[mode] = b
    ttk.Button(frame, text="No rounding", command=lambda: on_press(None)).grid(
        row=0, column=3, rowspan=2, sticky="ns", padx=(8, 0), pady=(0, 3))
    return frame, buttons


KEEP_QUESTION ="First order from this customer. Keep their details for loyalty and their own folder?"


def ask_keep(parent):
    """The first-time question: True (Keep details), False (Don't keep) or None (closed with X / Esc: cancel)."""
    dlg = tk.Toplevel(parent)
    dlg.title("ORCA - new customer")
    dlg.transient(parent)
    f = ttk.Frame(dlg, padding=22)
    f.grid()
    ttk.Label(f, text=KEEP_QUESTION, wraplength=440, justify="left", font=("Segoe UI", 12)).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(f, text="Don't keep: the order is placed and printed as usual, with name and phone on the cover sheet; "
                      "nothing about them is saved, and the order's folder is deleted for good once it is collected "
                      "or cancelled.", style="Small.TLabel", wraplength=440, justify="left").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
    choice = {"keep": None}

    def pick(value):
        choice["keep"] = value
        dlg.destroy()

    b = ttk.Frame(f)
    b.grid(row=2, column=0, columnspan=2, sticky="e", pady=(16, 0))
    dlg.keep_btn = ttk.Button(b, text="Keep details", style="Print.TButton", command=lambda: pick(True))
    dlg.keep_btn.pack(side="left")
    dlg.dont_btn = ttk.Button(b, text="Don't keep", command=lambda: pick(False))
    dlg.dont_btn.pack(side="left", padx=(8, 0))
    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
    theme.dark_title_bar(dlg)
    dlg.grab_set()
    parent.wait_window(dlg)
    return choice["keep"]


def customer_text(c):
    return " · ".join(x for x in (c.get("name"), c.get("phone"), c.get("email")) if x) or "No details"


def group_by_customer(orders):
    """[(customer text, [orders])], each customer once, the customer with the oldest order first."""
    groups = {}
    for o in sorted(orders, key=lambda o: o["created"]):
        groups.setdefault(o["customer"]["id"], []).append(o)
    return [(customer_text(v[0]["customer"]), v) for v in groups.values()]


def when(text):
    if not text:
        return "-"
    d = datetime.datetime.fromisoformat(text)
    return f"{d.day} {d:%b %H:%M}"


DROP_TEXT = {"product": "⤓  Drop the customer's file here", "document": "⤓  Drop the file to print here"}


def pdf_pages(path):
    """A PDF's page count, or None (not a PDF, or it can't be read)."""
    if Path(path).suffix.lower() != ".pdf":
        return None
    try:
        import jobs
        with jobs.PDF_LOCK:
            return analyze.page_count(Path(path)) or None
    except Exception:
        return None


def file_pages(path):
    """Pages a file prints as a document, when ORCA knows at once: a PDF's page count, an image 1; else None (an
    Office file: counted in the background, count_pages)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return pdf_pages(path)
    import convert
    return 1 if suffix in convert.IMAGE_EXT else None


def count_pages(path, size):
    """An Office file's page count the way the order's conversion does it (convert.py, on a thread), or None."""
    import tempfile
    import convert
    out = Path(tempfile.mkdtemp(prefix="orca_pages_")) / "count.pdf"
    try:
        convert.to_pdf(path, out, size)
        return pdf_pages(out)
    except Exception:
        return None
    finally:
        try:
            out.unlink()
            out.parent.rmdir()
        except OSError:
            pass


def same_file(path, others):
    """True when this file is already among others: the same path, or the same name and size (a second copy)."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    for other in others:
        o = Path(other)
        if o == path:
            return True
        try:
            if o.name.lower() == path.name.lower() and o.stat().st_size == size:
                return True
        except OSError:
            pass
    return False


MULTI_COLOURS = {"B&W": "bw", "Colour": "color"}  # several files: no list of colour pages (it can't fit them all)


DOWNLOADS = Path.home() / "Downloads"  # where customers' and Shopify's files usually land (2026-11-19_10)


def choose_files(parent, many, title="Choose file", types=None):
    """The file window (Tesla, 2026-11-19: always a drop box and a button): opens on Downloads; several files where a
    drop takes several. [] when closed."""
    from tkinter import filedialog
    start = str(DOWNLOADS) if DOWNLOADS.is_dir() else None
    types = types or [("All files", "*.*")]
    if many:
        return list(filedialog.askopenfilenames(parent=parent, title=title, initialdir=start, filetypes=types) or [])
    one = filedialog.askopenfilename(parent=parent, title=title, initialdir=start, filetypes=types)
    return [one] if one else []


def drop_area(parent, kind, on_drop):
    """The box under an item that files can be dropped on (filedrop.py), with a Choose file… button beside it
    (2026-11-19_10) whose files take exactly the same path as a drop: on_drop(paths, x, y). The box's text is
    area.label (a product item takes several files, a document one)."""
    area = ttk.Frame(parent)
    label = tk.Label(area, text=DROP_TEXT[kind], background=theme.FIELD, foreground=theme.MUTED,
                     font=("Segoe UI", 10), padx=12, pady=3, highlightthickness=1,
                     highlightbackground=theme.BORDER, highlightcolor=theme.BORDER, anchor="w", justify="left")
    label.pack(side="left")
    filedrop.target(label, on_drop)

    top = parent.winfo_toplevel()

    def choose():
        paths = choose_files(top, many=kind == "product")
        if paths:
            on_drop(paths, 0, 0)

    ttk.Button(area, text="Choose file…", command=choose).pack(side="left", padx=(8, 0))
    area.label = label
    area.choose = choose
    return filedrop.target(area, on_drop)


def ask_item(parent, labels):
    """Which item files dropped on a whole order are for: its index, or None (Cancel)."""
    dlg = tk.Toplevel(parent)
    dlg.title("ORCA - which item?")
    dlg.transient(parent)
    f = ttk.Frame(dlg, padding=18)
    f.grid()
    ttk.Label(f, text="This order has several items. Which one is the file for?").grid(row=0, column=0, sticky="w",
                                                                                        pady=(0, 8))
    choice = {"index": None}

    def pick(k):
        choice["index"] = k
        dlg.destroy()

    for i, text in enumerate(labels):
        ttk.Button(f, text=text, command=lambda k=i: pick(k)).grid(row=i + 1, column=0, sticky="we", pady=2)
    ttk.Button(f, text="Cancel", command=dlg.destroy).grid(row=len(labels) + 1, column=0, sticky="e", pady=(10, 0))
    theme.dark_title_bar(dlg)
    dlg.grab_set()
    parent.wait_window(dlg)
    return choice["index"]


def check_drop(parent, kind, paths):
    """True when the dropped files can go onto an item of this kind; else says why (nothing is copied)."""
    problems = [p for p in (wo.drop_problem(x, kind) for x in paths) if p]
    if problems:
        messagebox.showwarning(parent=parent, title="ORCA", message="\n".join(problems) + "\n\nNothing was copied.")
        return False
    if kind == "document" and len(paths) > 1:
        messagebox.showwarning(parent=parent, title="ORCA", message="A document item takes one file: drop only the "
                                                                    "file to print.\n\nNothing was copied.")
        return False
    return True


def drop_onto_item(parent, order, index, paths, done):
    """Copy dropped files into an item's folder (asks before replacing a file); done(text, failed) afterwards."""
    item = order["items"][index]
    if not check_drop(parent, item["kind"], paths):
        return
    conflicts = wo.drop_conflicts(order, item, paths)
    if conflicts and not messagebox.askyesno(
            parent=parent, title="ORCA",
            message=f"#{order['number']} item {index + 1} already has {', '.join(c.name for c in conflicts)}.\n\n"
                    f"Replace it with {', '.join(Path(x).name for x in paths)}? The old file goes to the Recycle Bin."):
        return
    tasks = [(order, item, x, conflicts if item["kind"] == "document" else
              [c for c in conflicts if c.name == Path(x).name]) for x in paths]
    copy_in_background(parent, tasks, done)


def copy_in_background(widget, tasks, done):
    """Copy [(order, item, source, files it replaces)] on a thread (a big file from a USB stick takes a while);
    done(text, failed) on the Tk thread once all are copied."""
    result = {}

    def work():
        copied, failed = [], []
        for order, item, src, replace in tasks:
            try:
                wo.add_file(order, item, src, replace)
                copied.append(f"#{order['number']} item {wo.item_index(order, item)}: {Path(src).name}")
            except OSError as e:
                failed.append(f"{Path(src).name}: {e}")
        result["value"] = (copied, failed)

    def wait():
        try:
            if "value" not in result:
                widget.after(100, wait)
                return
        except tk.TclError:
            return
        copied, failed = result["value"]
        if failed:
            messagebox.showwarning(parent=widget, title="ORCA", message="Not copied:\n" + "\n".join(failed))
        done(("Copied " + "; ".join(copied)) if copied else "", failed)

    threading.Thread(target=work, daemon=True).start()
    widget.after(100, wait)


def work_area(window):
    """(left, top, right, bottom) in pixels of the work area (screen minus taskbar) of the monitor the window is on;
    the whole Tk screen when Windows can't say."""
    try:
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD)]

        u32 = ctypes.windll.user32
        u32.MonitorFromWindow.restype = ctypes.c_void_p
        u32.MonitorFromWindow.argtypes = (ctypes.c_void_p, wintypes.DWORD)
        u32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        hwnd = u32.GetParent(window.winfo_id()) or window.winfo_id()
        mon = u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if mon and u32.GetMonitorInfoW(mon, ctypes.byref(info)):
            r = info.rcWork
            if r.right > r.left and r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()


class FormScroll(ttk.Frame):
    """A part of a form that scrolls up and down when it is taller than the room it gets (2026-11-17_11): the
    scrollbar shows only then, and the mouse wheel over the fields scrolls it (never a combobox's value)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=theme.SURFACE, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._inner_changed)
        self.bind_all("<MouseWheel>", self._wheel_all, add="+")

    def _inner_changed(self, _=None):
        """The canvas asks for the fields' full size (the grid gives less when the window is short)."""
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()),
                              width=self.inner.winfo_reqwidth(), height=self.inner.winfo_reqheight())

    def _scrolled(self, lo, hi):
        self.bar.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.bar.grid_remove()
        else:
            self.bar.grid(row=0, column=1, sticky="ns")

    def needed(self):
        lo, hi = self.canvas.yview()
        return lo > 0.0 or hi < 1.0

    def wheel(self, event):
        if self.needed():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _wheel_all(self, event):
        try:
            if str(event.widget).startswith(str(self.canvas)) and self.winfo_ismapped():
                self.wheel(event)
        except tk.TclError:
            pass

    def guard(self, widget):
        """A combobox in the form: the wheel scrolls the form instead of changing its value."""
        widget.bind("<MouseWheel>", self.wheel)

    def top(self):
        self.canvas.yview_moveto(0)


class Screen:
    """A screen window: title bar text, Back at the top left, closing with the X goes back too."""

    def __init__(self, ctx, title, on_back, size="1200x880"):
        self.ctx, self.on_back = ctx, on_back
        self.win = win = tk.Toplevel(ctx.root)
        win.title(f"ORCA - {title}")
        self.fit(size)
        win.protocol("WM_DELETE_WINDOW", self.back)
        self.frame = f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        self.top = ttk.Frame(f)
        self.top.grid(row=0, column=0, sticky="we")
        self.back_btn = ttk.Button(self.top, text="← Back", command=self.back)
        self.back_btn.pack(side="left", padx=(0, 24))
        ttk.Label(self.top, text=title, style="Summary.TLabel").pack(side="left")
        style = ttk.Style(win)
        style.configure("Huge.TLabel", font=("Segoe UI", 54, "bold"))
        style.configure("Big.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 10), foreground=theme.MUTED)
        style.configure("Warn.TLabel", foreground=theme.WARN)
        style.configure("Bad.TLabel", foreground=theme.ERROR)
        style.configure("Good.TLabel", foreground=theme.OK)
        style.configure("Walkin.TButton", font=("Segoe UI", 20, "bold"), padding=(24, 30))

    def fit(self, size):
        """Open at `size` (designed at 100% Windows scaling), grown with the scaling, but never bigger than the work
        area of the screen ORCA is on (the screen minus the taskbar), centred on it (2026-11-17_11)."""
        win = self.win
        req_w, req_h = (int(v) for v in size.split("x"))
        scale = max(1.0, win.winfo_fpixels("1i") / 96)
        left, top, right, bottom = work_area(getattr(self.ctx, "win", None) or win)
        title = round(32 * scale)  # the title bar, outside the size Tk sets
        w = min(round(req_w * scale), right - left - 16)
        h = min(round(req_h * scale), bottom - top - title - 8)
        x = left + max(0, (right - left - w) // 2)
        y = top + max(0, (bottom - top - title - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(min(round(760 * scale), w), min(round(500 * scale), h))

    def ready(self):
        theme.dark_title_bar(self.win)
        filedrop.enable(self.win)  # files dropped from Explorer onto an item

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def back(self):
        self.win.destroy()
        self.on_back()

    def warnings(self, parent, row):
        """The yellow lines about the price sheet (empty when it reads fine)."""
        pl = walkin_prices.current()
        text = "\n".join(pl.warnings[:6]) + (f"\n…and {len(pl.warnings) - 6} more" if len(pl.warnings) > 6 else "")
        label = ttk.Label(parent, text=text, style="Warn.TLabel", justify="left", wraplength=1100)
        label.grid(row=row, column=0, sticky="w", pady=(6, 0))
        return label


# ------------------------------------------------------------------ Walk-in

class WalkinScreen(Screen):
    """Six big buttons in three rows (2026-11-19_08): Get Quote, Add Email, Copy counter / Print Jobs, Orders /
    Customers, left-aligned in the same columns."""

    ROWS = ((("Get Quote", "open_quote_quote"), ("Add Email", "open_quote_email"), ("Copy counter", "open_copy_counter")),
            (("Print Jobs", "open_print_jobs"), ("Orders", "open_orders")),
            (("Customers", "open_customers"),))
    HINTS = ("Get Quote: a customer at the counter (name and phone needed).   Add Email: an order that came by email.",
             "Copy counter: count copies made at the copier.   Print Jobs: orders ready to print.",
             "Orders: open orders, search, Collected.   Customers: spending and loyalty.")

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Walk-in", on_back, size="1160x720")
        self.warn = self.warnings(self.frame, 1)
        box = ttk.Frame(self.frame)
        box.grid(row=2, column=0, pady=(30, 0))
        self.buttons = {}
        for r, row in enumerate(self.ROWS):
            for c, (text, name) in enumerate(row):
                b = ttk.Button(box, text=text, style="Walkin.TButton", width=11, command=getattr(self, name))
                b.grid(row=r, column=c, padx=12, pady=10, sticky="w")
                self.buttons[text] = b
        self.counter_btn = self.buttons["Copy counter"]
        ttk.Label(self.frame, text="\n".join(self.HINTS), style="Small.TLabel", justify="center").grid(
            row=3, column=0, pady=(20, 0))
        self.ready()
        self.poll()

    def open_quote_quote(self):
        self.open_quote("quote")

    def open_quote_email(self):
        self.open_quote("email")

    def open_orders(self):
        """Orders (moved here from the main menu, 2026-11-19_08): Back returns to the Walk-in menu."""
        self.win.withdraw()
        OrdersScreen(self.ctx, on_back=self.show)

    def poll(self):
        if not self.win.winfo_exists():
            return
        pl = walkin_prices.current()
        self.warn.config(text="\n".join(pl.warnings[:6]))
        self.win.after(3000, self.poll)

    def open_quote(self, mode):
        self.win.withdraw()
        QuoteScreen(self.ctx, mode, on_back=self.show)

    def open_print_jobs(self):
        self.win.withdraw()
        PrintJobsScreen(self.ctx, on_back=self.show)

    def open_customers(self):
        self.win.withdraw()
        CustomersScreen(self.ctx, on_back=self.show)

    def open_copy_counter(self):
        self.win.withdraw()
        CopyCounterScreen(self.ctx, on_back=self.show)


# ------------------------------------------------------------------ Copy counter (2026-11-17_10)

class CopyCounterScreen(Screen):
    """One panel per copier: Start counting, the copy type / paper / sides of the copies being made, extras, the
    running total (screen only), rounding, Finish, Print receipt, Done, Cancel. The counting itself lives in
    ctx.copy_counter (copy_counter.Manager), so it goes on when this window is closed (and after a restart)."""

    TYPE_NAMES = list(copy_counter.TYPES)
    HOW_HINTS = {
        "sheets": "The copier counts B&W / colour, A4 / A3 and the sides by itself. The paper is given at Finish.",
        "pages": "The copier counts B&W / colour by itself: pick the size and the sides. The paper is given at "
                 "Finish."}

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Copy counter", on_back, size="1500x900")
        self.manager = ctx.copy_counter
        self.panels = {}
        self.live = {}  # copier -> the labels refresh_live updates
        self.messages = {}  # copier -> a line for its panel (no answer, refused, …)
        self.finishing = set()
        self.reading = set()
        self.built_how = {}  # copier -> how its panel was built (a fallback while counting rebuilds it)
        self.paper_live = {}  # copier -> the Paper used labels refresh_papers updates
        body = ttk.Frame(self.frame)
        body.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.frame.rowconfigure(2, weight=1)
        for c, pid in enumerate(copy_counter.counting_printers(self.manager.printers)):
            body.columnconfigure(c, weight=1, uniform="copier")
            box = ttk.LabelFrame(body, text=self.manager.label(pid), padding=10, style="Section.TLabelframe")
            box.grid(row=0, column=c, sticky="nsew", padx=6)
            self.panels[pid] = box
        body.rowconfigure(0, weight=1)
        for pid in self.panels:
            self.build(pid)
        self.ready()
        self.win.after(1000, self.tick)

    # -------------------------------------------------------------- helpers
    def busy_text(self, pid):
        """Why ORCA's own printing refuses Start counting on this copier, or None."""
        label = self.manager.label(pid)
        c = self.ctx.print_queue.copiers.get(pid, {"state": "idle"})
        if c["state"] != "idle":
            n = (c.get("orders") or ["?"])[0]
            return f"{label} is busy printing #{n}: press Pages collected first."
        ph = getattr(self.ctx, "printhub", None)
        order = ph.busy_with(pid) if ph is not None else None
        if order is not None:
            return f"{label} is busy printing {order.number}: press Pages collected first."
        return None

    def in_background(self, pid, work, done):
        """Run work() on a thread (reading a copier can take a moment); done(result or exception) on the Tk thread."""
        box = {}

        def run():
            try:
                box["value"] = work()
            except Exception as e:  # CounterError, OSError: shown in the panel
                box["value"] = e

        def wait():
            if "value" not in box:
                self.win.after(100, wait)
                return
            try:
                done(box["value"])
            except tk.TclError:
                pass

        threading.Thread(target=run, daemon=True).start()
        self.win.after(100, wait)

    # -------------------------------------------------------------- one panel
    def build(self, pid):
        box = self.panels.get(pid)
        if box is None:  # not shown (Settings: not counted at this printer)
            return
        for w in box.winfo_children():
            w.destroy()
        box.columnconfigure(0, weight=1)
        counter = self.manager.counters.get(pid)
        message = self.messages.get(pid, "")
        if counter is None:
            self.build_idle(box, pid, message)
        elif counter.data["finished"]:
            self.build_summary(box, pid, counter, message)
        else:
            self.build_counting(box, pid, counter, message)
        theme.on_surface(box)

    def build_idle(self, box, pid, message):
        ttk.Label(box, text="Free", style="Big.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(box, text="Start counting", style="Print.TButton", command=lambda: self.start(pid)).grid(
            row=1, column=0, sticky="w", pady=(10, 0))
        if message:
            ttk.Label(box, text=message, style="Bad.TLabel", wraplength=420, justify="left").grid(
                row=2, column=0, sticky="w", pady=(10, 0))
        if pid in self.messages and self.messages[pid].startswith(f"{self.manager.label(pid)} doesn't answer"):
            ttk.Button(box, text="Type the copies instead", command=lambda: self.start(pid, typed=True)).grid(
                row=3, column=0, sticky="w", pady=(8, 0))

    def build_counting(self, box, pid, counter, message):
        d = counter.data
        r = 0
        how = counter.how if d["mode"] == "counter" else "typed"
        self.built_how[pid] = how
        head = "Counting" if d["mode"] == "counter" else "Typing the copies (the copier didn't answer)"
        ttk.Label(box, text=head, style="Big.TLabel").grid(row=r, column=0, sticky="w")
        r += 1
        if how in self.HOW_HINTS:  # the copier's page: what it counts by itself
            ttk.Label(box, text=self.HOW_HINTS[how], style="Hint.TLabel", wraplength=440, justify="left").grid(
                row=r, column=0, sticky="w", pady=(4, 0))
            r += 1
        elif how == "total":
            ttk.Label(box, text=copy_counter.FALLBACK_TEXT, style="Warn.TLabel", wraplength=440, justify="left").grid(
                row=r, column=0, sticky="w", pady=(4, 0))
            r += 1
        if how in ("total", "typed"):  # 10's way: staff pick the copy type
            types = ttk.Frame(box)
            types.grid(row=r, column=0, sticky="w", pady=(8, 0))
            var = tk.StringVar(value=d["current"]["type"])
            for k, name in enumerate(self.TYPE_NAMES):
                ttk.Radiobutton(types, text=name, value=name, variable=var,
                                command=lambda v=var: self.change(pid, type=v.get())).grid(
                    row=k // 2, column=k % 2, sticky="w", padx=(0, 14))
            r += 1
        elif how == "pages":  # MP C3004 mode: colour is counted, staff pick the size
            sizes = ttk.Frame(box)
            sizes.grid(row=r, column=0, sticky="w", pady=(8, 0))
            zvar = tk.StringVar(value=copy_counter.TYPES[d["current"]["type"]][0])
            for size in ("A4", "A3"):
                ttk.Radiobutton(sizes, text=size, value=size, variable=zvar,
                                command=lambda: self.change(pid, type=f"{zvar.get()} B&W")).pack(side="left",
                                                                                                 padx=(0, 14))
            r += 1
        if how != "sheets":  # with the sheets reading the copier counts one side / both sides by itself
            sides = ttk.Frame(box)
            sides.grid(row=r, column=0, sticky="w", pady=(6, 0))
            svar = tk.StringVar(value=d["current"]["sides"])
            for value, text in (("single", "One side"), ("double", "Both sides")):
                ttk.Radiobutton(sides, text=text, value=value, variable=svar,
                                command=lambda: self.change(pid, sides=svar.get())).pack(side="left", padx=(0, 14))
            r += 1
        if d["mode"] == "typed":
            typed = ttk.Frame(box)
            typed.grid(row=r, column=0, sticky="w", pady=(6, 0))
            ttk.Label(typed, text="Copies made:").pack(side="left")
            cvar = tk.StringVar()
            ttk.Entry(typed, textvariable=cvar, width=8, font=FONT).pack(side="left", padx=6)
            ttk.Button(typed, text="Add copies", command=lambda: self.add_typed(pid, cvar.get())).pack(side="left")
            r += 1
        live = self.live[pid] = {}
        live["segs"] = self.panel_label(box, r, "")
        r += 1
        r = self.extras_block(box, r, pid, counter)
        live["total"] = self.total_block(box, r, pid, counter, counter.priced())
        r += 2
        if d["mode"] == "counter":
            live["last"] = ttk.Label(box, text="", style="Small.TLabel")
            live["last"].grid(row=r, column=0, sticky="w")
            r += 1
        self.refresh_live(pid)
        if message:
            ttk.Label(box, text=message, style="Bad.TLabel", wraplength=420, justify="left").grid(
                row=r, column=0, sticky="w", pady=(4, 0))
            r += 1
        buttons = ttk.Frame(box)
        buttons.grid(row=r, column=0, sticky="w", pady=(10, 0))
        finish = ttk.Button(buttons, text="Finishing…" if pid in self.finishing else "Finish", style="Print.TButton",
                            command=lambda: self.finish(pid))
        finish.pack(side="left")
        if pid in self.finishing:
            finish.state(["disabled"])
        ttk.Button(buttons, text="Cancel", command=lambda: self.cancel(pid)).pack(side="left", padx=(8, 0))

    def panel_label(self, box, r, text):
        label = ttk.Label(box, text=text, justify="left", wraplength=440)
        label.grid(row=r, column=0, sticky="w", pady=(10, 0))
        return label

    def total_text(self, priced):
        total, due = priced["total"], priced["due"]
        text = (f"Total: {euro(total)}" if abs(due - total) < 0.005 else
                f"Total: {euro(due)} (rounded {'up' if due > total else 'down'} from {total:,.2f})")
        if priced["problems"]:
            text += "\n" + "\n".join(priced["problems"])
        return text

    def refresh_live(self, pid):
        """The lines that change while counting (segments, total, Last read), without rebuilding the panel (so a
        count being typed is not lost)."""
        counter, live = self.manager.counters.get(pid), self.live.get(pid)
        if counter is None or not live or counter.data["finished"]:
            return
        d = counter.data
        try:
            live["segs"].config(text=counter.running_text())  # what the copier counted so far (2026-11-19_02)
            priced = counter.priced()
            live["total"].config(text=self.total_text(priced),
                                 style="Bad.TLabel" if priced["problems"] else "Head.TLabel")
            if "last" in live:
                live["last"].config(text=f"Last read {(d.get('last_time') or '')[11:19]}")
        except tk.TclError:
            pass

    def extras_block(self, box, r, pid, counter):
        pl = walkin_prices.current()
        rows = copy_counter.extra_rows(pl)
        f = ttk.Frame(box)
        f.grid(row=r, column=0, sticky="w", pady=(10, 0))
        ttk.Label(f, text="Extra:").grid(row=0, column=0, sticky="w")
        names = [f"{name} ({what})" for name, what in rows]
        evar = tk.StringVar(value=names[0])
        ttk.Combobox(f, textvariable=evar, values=names, state="readonly", width=26, font=FONT).grid(
            row=0, column=1, sticky="w", padx=6)
        nvar, svar = tk.StringVar(), tk.StringVar()
        ttk.Label(f, text="how many:").grid(row=0, column=2, sticky="e")
        ttk.Entry(f, textvariable=nvar, width=6, font=FONT).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Label(f, text="sheets per copy (spiral):").grid(row=1, column=1, columnspan=2, sticky="e")
        ttk.Entry(f, textvariable=svar, width=6, font=FONT).grid(row=1, column=3, sticky="w", padx=4, pady=(4, 0))
        ttk.Button(f, text="Add", command=lambda: self.add_extra(pid, rows[names.index(evar.get())][0], nvar.get(),
                                                                 svar.get())).grid(row=0, column=4, padx=(6, 0))
        r += 1
        for k, e in enumerate(counter.data["extras"]):
            line = ttk.Frame(box)
            line.grid(row=r, column=0, sticky="w")
            extra = f" ({e['per_copy']} sheets per copy)" if e.get("per_copy") else ""
            ttk.Label(line, text=f"{e['name']} x {e['count']}{extra}").pack(side="left")
            ttk.Button(line, text="Remove", command=lambda i=k: self.remove_extra(pid, i)).pack(side="left", padx=8)
            r += 1
        return r

    def total_block(self, box, r, pid, counter, priced):
        f = ttk.Frame(box)
        f.grid(row=r, column=0, sticky="w", pady=(10, 0))
        ttk.Label(f, text="Round the total:").grid(row=0, column=0, sticky="w")
        rb, buttons = rounding_buttons(f, lambda m: self.set_rounding(pid, m), width=9)
        rb.grid(row=1, column=0, sticky="w", pady=(4, 0))
        for mode, b in buttons.items():
            b.state(["pressed"] if mode == counter.data.get("rounding") else ["!pressed"])
        label = ttk.Label(box, text=self.total_text(priced), style="Bad.TLabel" if priced["problems"] else "Head.TLabel",
                          justify="left", wraplength=440)
        label.grid(row=r + 1, column=0, sticky="w", pady=(6, 0))
        return label

    def papers(self):
        """The price sheet's papers for the Paper used part, Smooth white 80 gsm first."""
        pl = walkin_prices.current()
        papers = [p for p in pl.papers if p != walkin_prices.LABEL_SHEET] or [copy_counter.FIRST_PAPER]
        if copy_counter.FIRST_PAPER in papers:
            papers.remove(copy_counter.FIRST_PAPER)
            papers.insert(0, copy_counter.FIRST_PAPER)
        return papers

    def paper_block(self, box, r, pid, counter):
        """Paper used (2026-11-19_02): one block per size with sheets. All on one paper (the default), or Different
        papers: rows of paper + sheets, the first taking what is left, + Add paper, ✕; "28 of 28 A4 sheets given",
        red when it doesn't add up."""
        live = self.paper_live[pid] = {"first": {}, "given": {}}
        papers = self.papers()
        for size, total in counter.sheet_totals().items():
            plan = counter.plan(size)
            f = ttk.Frame(box)
            f.grid(row=r, column=0, sticky="w", pady=(8, 0))
            r += 1
            ttk.Label(f, text=f"{size}: {total} sheet{'' if total == 1 else 's'}", style="Head.TLabel").grid(
                row=0, column=0, columnspan=4, sticky="w")
            mode = tk.StringVar(value="split" if plan["split"] else "one")
            choice = ttk.Frame(f)
            choice.grid(row=1, column=0, columnspan=4, sticky="w")
            second = next((x for x in papers if x != plan["rows"][0][0]), None)
            for value, text in (("one", "All on one paper"), ("split", "Different papers")):
                ttk.Radiobutton(choice, text=text, value=value, variable=mode, command=lambda z=size, m=mode, x=second:
                                self.paper_mode(pid, z, m.get() == "split", x)).pack(side="left", padx=(0, 14))
            rows = counter.paper_rows(size)
            for k, (paper, n) in enumerate(rows if plan["split"] else rows[:1]):
                pvar = tk.StringVar(value=paper)
                cb = ttk.Combobox(f, textvariable=pvar, values=papers, state="readonly", width=24, font=FONT)
                cb.grid(row=2 + k, column=0, sticky="w", pady=2)
                cb.bind("<<ComboboxSelected>>", lambda _e, z=size, i=k, v=pvar: self.paper_set(pid, z, i, paper=v.get()))
                if not plan["split"]:
                    continue
                if k == 0:  # takes whatever is left: filled in by itself, never typed
                    live["first"][size] = ttk.Label(f, text=str(n), width=6)
                    live["first"][size].grid(row=2 + k, column=1, sticky="w", padx=6)
                else:
                    nvar = tk.StringVar(value=str(n))
                    ttk.Entry(f, textvariable=nvar, width=6, font=FONT).grid(row=2 + k, column=1, sticky="w", padx=6)
                    nvar.trace_add("write", lambda *_a, z=size, i=k, v=nvar: self.paper_typed(pid, z, i, v.get()))
                    ttk.Button(f, text="✕", width=3, command=lambda z=size, i=k: self.paper_remove(pid, z, i)).grid(
                        row=2 + k, column=2, sticky="w")
            if plan["split"]:
                ttk.Button(f, text="+ Add paper", command=lambda z=size: self.paper_add(pid, z)).grid(
                    row=2 + len(rows), column=0, sticky="w", pady=(4, 0))
            live["given"][size] = ttk.Label(f, text="")
            live["given"][size].grid(row=3 + len(rows), column=0, columnspan=4, sticky="w", pady=(2, 0))
        self.refresh_papers(pid)
        return r

    def refresh_papers(self, pid):
        """While a paper's sheets are typed: the first row, the "x of y given" lines, the total and the buttons,
        without building the panel again (so the typing isn't lost)."""
        counter, live = self.manager.counters.get(pid), self.paper_live.get(pid)
        if counter is None or not live:
            return
        try:
            totals = counter.sheet_totals()
            for size, label in live["first"].items():
                label.config(text=str(counter.paper_rows(size)[0][1]))
            for size, label in live["given"].items():
                given, total = counter.given(size), totals.get(size, 0)
                label.config(text=f"{given} of {total} {size} sheets given",
                             style="Good.TLabel" if given == total else "Bad.TLabel")
            priced = counter.priced()
            if "lines" in live:
                live["lines"].config(text="\n".join(f"{t}   {euro(a)}" for t, a in priced["lines"]) or "No copies")
            if "total" in live:
                live["total"].config(text=self.total_text(priced),
                                     style="Bad.TLabel" if priced["problems"] else "Head.TLabel")
            for b in live.get("buttons", []):
                b.state(["disabled"] if priced["problems"] else ["!disabled"])
        except tk.TclError:
            pass

    def paper_mode(self, pid, size, split, second):
        self.manager.counters[pid].set_split(size, split, second)
        self.build(pid)

    def paper_set(self, pid, size, index, paper):
        self.manager.counters[pid].set_row(size, index, paper=paper)
        self.refresh_papers(pid)

    def paper_typed(self, pid, size, index, text):
        text = text.strip()
        self.manager.counters[pid].set_row(size, index, sheets=int(text) if text.isdigit() else 0)
        self.refresh_papers(pid)

    def paper_add(self, pid, size):
        counter = self.manager.counters[pid]
        used = {x for x, _ in counter.paper_rows(size)}
        counter.add_row(size, next((x for x in self.papers() if x not in used), self.papers()[0]))
        self.build(pid)

    def paper_remove(self, pid, size, index):
        self.manager.counters[pid].remove_row(size, index)
        self.build(pid)

    def back_to_counting(self, pid):
        """The customer makes more copies after Finish: counting again, the papers given kept."""
        self.manager.counters[pid].reopen()
        self.messages.pop(pid, None)
        self.build(pid)

    def build_summary(self, box, pid, counter, message):
        priced = counter.priced()
        ttk.Label(box, text="Finished", style="Big.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(box, text=counter.running_text(), justify="left", wraplength=440).grid(row=1, column=0, sticky="w")
        if counter.sheet_totals():
            ttk.Label(box, text="Paper used", style="Head.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
        r = self.paper_block(box, 3, pid, counter)
        live = self.paper_live[pid]
        live["lines"] = self.panel_label(box, r, "\n".join(f"{t}   {euro(a)}" for t, a in priced["lines"]) or "No copies")
        live["total"] = self.total_block(box, r + 1, pid, counter, priced)
        r += 3
        if message:
            ttk.Label(box, text=message, style="Bad.TLabel", wraplength=420, justify="left").grid(
                row=r, column=0, sticky="w", pady=(4, 0))
            r += 1
        buttons = ttk.Frame(box)
        buttons.grid(row=r, column=0, sticky="w", pady=(10, 0))
        pr = None
        if self.ctx.rules.get("receipt_printer"):  # Settings: Receipt printer None hides it (2026-11-18_02)
            pr = ttk.Button(buttons, text="Print receipt", command=lambda: self.print_receipt(pid))
            pr.pack(side="left", padx=(0, 8))
        dn = ttk.Button(buttons, text="Done", style="Print.TButton", command=lambda: self.done(pid))
        dn.pack(side="left")
        ttk.Button(buttons, text="Back to counting", command=lambda: self.back_to_counting(pid)).pack(
            side="left", padx=(8, 0))
        live["buttons"] = [b for b in (pr, dn) if b is not None]
        if priced["problems"]:
            for b in live["buttons"]:
                b.state(["disabled"])

    # -------------------------------------------------------------- actions
    def start(self, pid, typed=False):
        try:
            self.manager.start(pid, self.busy_text(pid), typed=typed)
            self.messages.pop(pid, None)
        except ValueError as e:
            self.messages[pid] = str(e)
        except copy_counter.CounterError as e:
            self.messages[pid] = f"{self.manager.label(pid)} doesn't answer ({e}). Type the copies instead?"
        self.build(pid)

    def change(self, pid, **what):
        counter = self.manager.counters.get(pid)
        if counter is None:
            return
        try:
            counter.change(**what)
            self.messages.pop(pid, None)
        except copy_counter.CounterError as e:
            self.messages[pid] = f"Couldn't read the counter ({e}): the change wasn't made. Try again."
        self.build(pid)

    def add_typed(self, pid, text):
        counter = self.manager.counters[pid]
        try:
            if not text.strip().isdigit():
                raise ValueError("Copies made: a whole number (a count, not money).")
            counter.add_typed(int(text))
            self.messages.pop(pid, None)
        except ValueError as e:
            self.messages[pid] = str(e)
        self.build(pid)

    def add_extra(self, pid, name, count, per_copy):
        counter = self.manager.counters[pid]
        try:
            if not count.strip().isdigit():
                raise ValueError(f"{name}: how many is a whole number (a count, not money).")
            if per_copy.strip() and not per_copy.strip().isdigit():
                raise ValueError("Sheets per copy: a whole number.")
            counter.add_extra(name, int(count), int(per_copy) if per_copy.strip() else None)
            self.messages.pop(pid, None)
        except ValueError as e:
            self.messages[pid] = str(e)
        self.build(pid)

    def remove_extra(self, pid, index):
        self.manager.counters[pid].remove_extra(index)
        self.build(pid)

    def set_rounding(self, pid, mode):
        self.manager.counters[pid].set_rounding(mode)
        self.build(pid)

    def finish(self, pid):
        counter = self.manager.counters.get(pid)
        if counter is None or pid in self.finishing:
            return
        self.finishing.add(pid)
        self.build(pid)

        def done(result):
            self.finishing.discard(pid)
            if isinstance(result, Exception):
                self.messages[pid] = f"Couldn't read the counter ({result}). Press Finish again."
            elif result is False:
                self.messages[pid] = "The counter kept changing for 30 seconds: the last reading was used."
            else:
                self.messages.pop(pid, None)
            self.build(pid)

        self.in_background(pid, counter.finish, done)

    def cancel(self, pid):
        if not messagebox.askyesno(parent=self.win, title="ORCA", message="Stop counting and throw these copies away?"):
            return
        self.manager.cancel(pid)
        self.messages.pop(pid, None)
        self.build(pid)

    def print_receipt(self, pid):
        counter = self.manager.counters[pid]
        priced = counter.priced()
        path = walkin_print.WORK_DIR / f"copy_counter_{pid}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)

        def done(result):
            if isinstance(result, Exception):
                messagebox.showwarning(parent=self.win, title="ORCA", message=f"The receipt didn't print.\n\n{result}")
            else:
                self.messages[pid] = "Receipt sent to the receipt printer."
                self.build(pid)

        self.in_background(pid, lambda: copy_counter.print_receipt(counter, priced, self.ctx.rules, path), done)

    def done(self, pid):
        try:
            self.manager.done(pid)
        except ValueError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=str(e))
            return
        self.messages.pop(pid, None)
        self.build(pid)

    def tick(self):
        """Every few seconds: read every counting copier again (on a thread) and show it."""
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        for pid, counter in list(self.manager.counters.items()):
            if counter.data["finished"] or counter.data["mode"] != "counter" or pid in self.reading \
                    or pid in self.finishing:
                continue
            self.reading.add(pid)

            def done(result, p=pid):
                self.reading.discard(p)
                if isinstance(result, Exception):
                    self.messages[p] = f"Couldn't read the counter ({result}): trying again."
                elif self.messages.get(p, "").startswith("Couldn't read the counter"):
                    self.messages.pop(p, None)
                if p in self.finishing:
                    return
                c = self.manager.counters.get(p)
                if c is not None and self.built_how.get(p) not in (None, c.how):
                    self.build(p)  # the page stopped answering: the copy type and sides come back
                else:
                    self.refresh_live(p)

            self.in_background(pid, counter.poll, done)
        self.win.after(copy_counter.poll_seconds(self.ctx.rules) * 1000, self.tick)


# ------------------------------------------------------------------ Customers (2026-11-17_07)

class CustomersScreen(Screen):
    """Every kept customer with orders, last visit, spending (12 months, all time) and loyalty; search and sort;
    the selected customer's orders below. Open folder, Loyalty…, Edit details…, Forget customer…. Nothing else here
    deletes anything or changes prices or orders."""

    COLUMNS = (("name", "Name", 170), ("phones", "Phone(s)", 150), ("emails", "Email(s)", 190),
               ("orders", "Orders", 60), ("last", "Last visit", 95), ("spent", "12 months (EUR)", 135),
               ("all", "All time (EUR)", 125), ("loyalty", "Loyalty", 130))

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Customers", on_back, size="1240x860")
        f = self.frame
        f.rowconfigure(2, weight=3)
        f.rowconfigure(5, weight=2)
        ttk.Label(self.top, text="Search:").pack(side="left", padx=(40, 6))
        self.search = tk.StringVar()
        ttk.Entry(self.top, textvariable=self.search, width=28, font=FONT).pack(side="left")
        self.search.trace_add("write", lambda *_: self.fill())
        ttk.Label(self.top, text="phone, name or email", style="Small.TLabel").pack(side="left", padx=8)
        self.sort_by, self.descending = "spent", True
        self.tree = ttk.Treeview(f, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="browse")
        for key, text, width in self.COLUMNS:
            self.tree.heading(key, text=text, anchor="w", command=lambda k=key: self.sort(k))
            self.tree.column(key, width=width, anchor="e" if key in ("orders", "spent", "all") else "w",
                             stretch=key in ("name", "emails"))
        self.tree.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_orders())
        buttons = ttk.Frame(f)
        buttons.grid(row=3, column=0, sticky="w", pady=(8, 0))
        for text, command in (("Open folder", self.open_folder), ("Loyalty…", self.loyalty),
                              ("Edit details…", self.edit), ("Forget customer…", self.forget)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 8))
        self.totals = ttk.Label(buttons, text="", style="Head.TLabel")
        self.totals.pack(side="left", padx=(24, 0))
        self.orders_title = ttk.Label(f, text="Select a customer to see their orders.", style="Head.TLabel")
        self.orders_title.grid(row=4, column=0, sticky="w", pady=(14, 4))
        self.orders = ttk.Treeview(f, columns=("date", "n", "items", "amount", "status"), show="headings", height=7)
        for key, text, width, stretch in (("date", "Date", 100, False), ("n", "#", 60, False),
                                          ("items", "Items", 640, True), ("amount", "Amount", 110, False),
                                          ("status", "Status", 110, False)):
            self.orders.heading(key, text=text, anchor="w")
            self.orders.column(key, width=width, stretch=stretch, anchor="e" if key == "amount" else "w")
        self.orders.grid(row=5, column=0, sticky="nsew")
        self.rows = {}
        self.refresh()
        self.ready()

    # -------------------------------------------------------------- data

    def refresh(self):
        """Read the customers and their spending again (after a change here)."""
        pl = walkin_prices.current()
        self.customers = wo.Customers()
        self.rows = {}
        for cid, c in self.customers.all.items():
            s = wo.spending(cid)
            if c.get("loyalty_mode") == "manual":
                level, how = int(c.get("loyalty") or 0), "set by hand"
            else:
                level, how = pl.level_for(s["spent_12"]), "auto"
            self.rows[cid] = {"c": c, "s": s, "name": c.get("name") or c["folder"],
                              "phones": ", ".join(c.get("phones", [])), "emails": ", ".join(c.get("emails", [])),
                              "orders": s["orders"], "last": s["last_visit"] or "", "spent": s["spent_12"],
                              "all": s["all_time"], "loyalty": f"{level or 'None'} ({how})"}
        self.fill()

    def sort(self, key):
        if self.sort_by == key:
            self.descending = not self.descending
        else:
            self.sort_by, self.descending = key, key in ("spent", "all", "orders", "last")
        self.fill()

    def fill(self):
        keep = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        text = self.search.get()
        shown = [r for r in self.rows.values() if wo.customer_matches(r["c"], text)]
        key = self.sort_by
        shown.sort(key=lambda r: (r[key].lower() if isinstance(r[key], str) else r[key]), reverse=self.descending)
        for r in shown:
            self.tree.insert("", "end", iid=r["c"]["id"], values=(
                r["name"], r["phones"], r["emails"], r["orders"], r["last"], f"{r['spent']:,.2f}",
                f"{r['all']:,.2f}", r["loyalty"]))
        for k, text_, _ in self.COLUMNS:
            arrow = (" ▼" if self.descending else " ▲") if k == key else ""
            self.tree.heading(k, text=text_ + arrow)
        self.totals.config(text=f"{len(self.rows)} customers   ·   spent in the last 12 months: "
                                f"{euro(sum(r['spent'] for r in self.rows.values()))}")
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        self.show_orders()

    def selected_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def show_orders(self):
        self.orders.delete(*self.orders.get_children())
        cid = self.selected_id()
        if not cid or cid not in self.rows:
            self.orders_title.config(text="Select a customer to see their orders.")
            return
        r = self.rows[cid]
        self.orders_title.config(text=f"{r['name']}: orders")
        lines = []
        for o in wo.list_open():
            if o["customer"].get("id") == cid:
                lines.append((o["created"][:10], o["number"], wo.items_short(o), euro(wo.price_due(o)), "open"))
        for o in r["s"]["history"]:
            if o["status"] == "cancelled":
                lines.append(((o["times"].get("cancelled") or o["created"])[:10], o["number"], wo.items_short(o),
                              "-", "cancelled"))
            else:
                lines.append((wo.collected_on(o).isoformat(), o["number"], wo.items_short(o), euro(wo.price_due(o)),
                              "collected"))
        lines = [x for x in lines if x[4] == "open"] + sorted((x for x in lines if x[4] != "open"),
                                                              key=lambda x: x[0], reverse=True)
        for k, (day, number, items, amount, status) in enumerate(lines):
            self.orders.insert("", "end", iid=str(k), values=(day, f"#{number}", items, amount, status))

    # -------------------------------------------------------------- buttons

    def need(self):
        cid = self.selected_id()
        if not cid:
            messagebox.showinfo(parent=self.win, title="ORCA", message="Select a customer first.")
        return cid

    def open_folder(self):
        cid = self.need()
        if not cid:
            return
        folder = wo.customers_dir() / self.rows[cid]["c"]["folder"]
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(folder)
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=f"Could not open the folder.\n\n{e}")

    def loyalty(self):
        cid = self.need()
        if cid:
            LoyaltyDialog(self, self.rows[cid]["c"])

    def edit(self):
        cid = self.need()
        if cid:
            DetailsDialog(self, self.rows[cid]["c"])

    def forget(self):
        cid = self.need()
        if not cid:
            return
        name = self.rows[cid]["name"]
        if not messagebox.askyesno(parent=self.win, title="ORCA",
                                   message=f"Delete {name}'s details and folder for good? Their sales stay without "
                                           f"a name."):
            return
        try:
            wo.Customers().forget(cid)
        except ValueError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=str(e))
            return
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA",
                                   message=f"Could not delete the folder (is a file in it open?).\n\n{e}")
        self.refresh()


class LoyaltyDialog:
    """Loyalty…: Automatic, None, 1, 2 or 3 for one customer."""

    def __init__(self, screen, customer):
        self.screen, self.customer = screen, customer
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("ORCA - loyalty")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=18)
        f.grid()
        ttk.Label(f, text=f"Loyalty for {customer.get('name') or customer['folder']}:").grid(row=0, column=0, sticky="w")
        value = ("Automatic" if customer.get("loyalty_mode", "auto") == "auto" else
                 (str(customer.get("loyalty")) if customer.get("loyalty") else "None"))
        self.var = tk.StringVar(value=value)
        ttk.Combobox(f, textvariable=self.var, values=["Automatic", "None", "1", "2", "3"], state="readonly",
                     width=12, font=FONT).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(f, text="Automatic: the level follows what they spent in the last 12 months. Any other choice "
                          "stays until set back to Automatic.", style="Small.TLabel", wraplength=380,
                  justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        b = ttk.Frame(f)
        b.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.save).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def save(self):
        v = self.var.get()
        wo.Customers().set_loyalty(self.customer["id"], "auto" if v == "Automatic" else (0 if v == "None" else int(v)))
        self.dlg.destroy()
        self.screen.refresh()


class DetailsDialog:
    """Edit details…: the name, and a phone or email to add. Matching stays by phone and email, never by name; the
    folder name stays as it was."""

    def __init__(self, screen, customer):
        self.screen, self.customer = screen, customer
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("ORCA - customer details")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=18)
        f.grid()
        self.vars = {"name": tk.StringVar(value=customer.get("name") or ""), "phone": tk.StringVar(),
                     "email": tk.StringVar()}
        for r, (key, label) in enumerate((("name", "Name"), ("phone", "Add a phone"), ("email", "Add an email"))):
            ttk.Label(f, text=label + ":").grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=self.vars[key], width=30, font=FONT).grid(row=r, column=1, sticky="w", padx=8)
        ttk.Label(f, text=f"Now: {', '.join(customer.get('phones', []) + customer.get('emails', [])) or '-'}",
                  style="Small.TLabel", wraplength=400, justify="left").grid(row=3, column=0, columnspan=2, sticky="w",
                                                                            pady=(6, 0))
        self.error = ttk.Label(f, text="", style="Bad.TLabel", wraplength=400, justify="left")
        self.error.grid(row=4, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.save).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def save(self):
        try:
            wo.Customers().edit(self.customer["id"], self.vars["name"].get(), self.vars["phone"].get(),
                                self.vars["email"].get())
        except ValueError as e:
            self.error.config(text=str(e))
            return
        self.dlg.destroy()
        self.screen.refresh()


# ------------------------------------------------------------------ Get Quote / Add Email

class QuoteScreen(Screen):
    """Items with their prices, loyalty, change price, the customer, Place order (or discard)."""

    def __init__(self, ctx, mode, on_back):
        super().__init__(ctx, "Get Quote" if mode == "quote" else "Add Email", on_back, size="1320x900")
        self.mode = mode
        self.items = []
        self.drops = []  # per item: files dropped on it, copied into its folder at Place order
        self.held = []  # files dropped in the box next to Add item, for the item on the form
        self.editing = None  # index of the item being edited
        self.option_vars = {}
        self.filled_from = None  # the customer whose details were filled in
        f = self.frame
        f.rowconfigure(2, weight=1)
        self.warn = self.warnings(f, 1)
        body = ttk.Frame(f)
        body.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # The item editor
        self.editor = ttk.LabelFrame(body, text="Add an item", padding=12, style="Section.TLabelframe")
        self.editor.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        ttk.Label(self.editor, text="What:").grid(row=0, column=0, sticky="w", pady=3)
        self.what = tk.StringVar(value="Document")
        cb = ttk.Combobox(self.editor, textvariable=self.what, state="readonly", width=30, font=FONT,
                          values=["Document"] + [p["name"] for p in cat.PRODUCTS])
        cb.grid(row=0, column=1, sticky="w", pady=3)
        cb.bind("<<ComboboxSelected>>", lambda _: self.what_changed())
        # Only the fields scroll (2026-11-17_11): Add item, the drop box, the customer and Place order stay in view.
        self.form = FormScroll(self.editor)
        self.form.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.editor.rowconfigure(1, weight=1)
        self.options = self.form.inner
        buttons = ttk.Frame(self.editor)
        buttons.grid(row=2, column=0, columnspan=2, sticky="we", pady=(12, 0))
        buttons.columnconfigure(1, weight=1)
        left = ttk.Frame(buttons)
        left.grid(row=0, column=0, sticky="nw")
        self.add_btn = ttk.Button(left, text="Add item", style="Print.TButton", command=self.add_item)
        self.add_btn.pack(anchor="w")
        self.cancel_edit_btn = ttk.Button(left, text="Cancel edit", command=self.cancel_edit)
        # The drop box: files for the item on the form, attached to it by Add item (2026-11-17_06).
        self.box = tk.Frame(buttons, background=theme.FIELD, highlightthickness=2,
                            highlightbackground=theme.PRIMARY, highlightcolor=theme.PRIMARY, padx=8, pady=6)
        self.box.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self.box.columnconfigure(0, weight=1)
        filedrop.target(self.box, lambda paths, x, y: self.drop_in_box(paths))
        self.editor_error = ttk.Label(self.editor, text="", style="Bad.TLabel", wraplength=380, justify="left")
        self.editor_error.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # The price list
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(right, columns=("n", "item", "price"), show="headings", height=12, selectmode="browse")
        self.tree.tag_configure("working", foreground=theme.MUTED)
        for col, text, width, stretch in (("n", "#", 40, False), ("item", "Item", 520, True), ("price", "Price", 110, False)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="e" if col == "price" else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        row = ttk.Frame(right)
        row.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(row, text="Edit", command=self.edit_item).pack(side="left")
        ttk.Button(row, text="Remove", command=self.remove_item).pack(side="left", padx=(8, 0))
        ttk.Label(row, text="Drop files in the box next to Add item, or onto an item in the list.",
                  style="Small.TLabel").pack(side="left", padx=(16, 0))
        filedrop.target(self.tree, self.drop_on_list)
        self.notes = ttk.Label(right, text="", style="Small.TLabel", justify="left", wraplength=760)
        self.notes.grid(row=2, column=0, sticky="w", pady=(4, 0))
        totals = ttk.Frame(right)
        totals.grid(row=3, column=0, sticky="we", pady=(8, 0))
        totals.columnconfigure(0, weight=1)
        self.total_lines = ttk.Label(totals, text="", justify="right", anchor="e")
        self.total_lines.grid(row=1, column=0, rowspan=2, sticky="ne", padx=(0, 16), pady=(8, 0))  # beside, not above
        ttk.Label(totals, text="Loyalty:").grid(row=1, column=1, sticky="e", pady=(8, 0))
        self.auto = (0, 0.0)  # (level, spent in 12 months) of the recognised customer, for Automatic
        self.loyalty = tk.StringVar(value="Automatic")
        self.loyalty_box = lc = ttk.Combobox(totals, textvariable=self.loyalty, state="readonly", width=40, font=FONT,
                                             values=["Automatic", "None", "1", "2", "3"])
        lc.grid(row=1, column=2, sticky="w", padx=6, pady=(8, 0))
        lc.bind("<<ComboboxSelected>>", lambda _: self.reprice())
        # Prices are fixed: staff can only round the total (Tesla, 2026-11-17).
        ttk.Label(totals, text="Round the total:").grid(row=2, column=1, sticky="e", pady=(6, 0))
        self.rounding = None
        rb, self.round_buttons = rounding_buttons(totals, self.set_rounding)
        rb.grid(row=2, column=2, sticky="w", padx=6, pady=(6, 0))
        self.total_label = ttk.Label(totals, text="", style="Big.TLabel")
        self.total_label.grid(row=3, column=0, columnspan=4, sticky="e", pady=(8, 0))
        self.problems = ttk.Label(right, text="", style="Bad.TLabel", justify="left", wraplength=760)
        self.problems.grid(row=4, column=0, sticky="w")

        # The customer
        cust = ttk.LabelFrame(f, text="Customer", padding=12, style="Section.TLabelframe")
        cust.grid(row=3, column=0, sticky="we", pady=(12, 0))
        need = "required" if mode == "quote" else "at least one of the three"
        self.cust_vars = {k: tk.StringVar() for k in ("name", "phone", "email")}
        for c, (key, label) in enumerate((("name", "Name"), ("phone", "Phone"), ("email", "Email"))):
            text = label + (" *" if mode == "quote" and key != "email" else "")
            ttk.Label(cust, text=text).grid(row=0, column=c * 2, sticky="w", padx=(0 if c == 0 else 18, 6))
            ttk.Entry(cust, textvariable=self.cust_vars[key], width=24, font=FONT).grid(row=0, column=c * 2 + 1)
        for key in ("phone", "email"):
            self.cust_vars[key].trace_add("write", lambda *_: self.lookup())
        info = ttk.Frame(cust)  # the hint and "Known customer" share one line (2026-11-17_11)
        info.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        ttk.Label(info, text=("* required. Email optional." if mode == "quote" else f"Name, phone, email: {need}."),
                  style="Small.TLabel").pack(side="left")
        self.known = ttk.Label(info, text="", style="Good.TLabel")
        self.known.pack(side="left", padx=(24, 0))
        actions = ttk.Frame(f)
        actions.grid(row=4, column=0, sticky="e", pady=(12, 0))
        ttk.Button(actions, text="Discard", command=self.discard).pack(side="left", padx=(0, 10))
        ttk.Button(actions, text="Place order", style="Print.TButton", command=self.place).pack(side="left")
        self.build_options()
        self.reprice()
        theme.on_surface(self.editor)
        theme.on_surface(cust)
        self.ready()

    # -------------------------------------------------------------- the editor

    def build_options(self, item=None):
        for w in self.options.winfo_children():
            w.destroy()
        self.option_vars = {}
        pl = walkin_prices.current()
        row = 0

        def combo(label, values, value, typed=False):
            nonlocal row
            ttk.Label(self.options, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=value)
            cb = ttk.Combobox(self.options, textvariable=var, values=values, state="normal" if typed else "readonly",
                              width=28, font=FONT)
            cb.grid(row=row, column=1, sticky="w", pady=2)
            self.form.guard(cb)  # the wheel scrolls the form, never the value
            row += 1
            return var

        def entry(label, value, width=8):
            nonlocal row
            ttk.Label(self.options, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(value))
            ttk.Entry(self.options, textvariable=var, width=width, font=FONT).grid(row=row, column=1, sticky="w", pady=2)
            row += 1
            return var

        if self.what.get() == "Document":
            d = item or {"size": "A4", "pages": 1, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
                         "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0,
                         "cuts": 0}
            v = self.option_vars
            v["size"] = combo("Size", ["A4", "A3"], d["size"])
            v["pages"] = entry("Pages", d["pages"] if d["pages"] else "")
            self.pages_entry = self.options.grid_slaves(row=row - 1, column=1)[0]
            v["copies"] = entry("Copies", d["copies"])
            v["color"] = combo("Colour", list(COLOUR_CHOICES), next(k for k, x in COLOUR_CHOICES.items() if x == d["color"]))
            self.colour_box = self.options.grid_slaves(row=row - 1, column=1)[0]
            v["color_pages"] = entry("Colour pages (e.g. 1, 3-5)", d["color_pages"], 16)
            v["sides"] = combo("Sides", list(SIDE_CHOICES), next(k for k, x in SIDE_CHOICES.items() if x == d["sides"]))
            v["per_side"] = combo("Pages per side", [str(n) for n in cat.PER_SIDE], str(d["per_side"]))
            papers = pl.doc_papers()
            v["paper"] = combo("Paper", papers if d["paper"] in papers else papers + [d["paper"]], d["paper"])
            v["finish"] = combo("Finishing", list(FINISH_CHOICES),
                                next(k for k, x in FINISH_CHOICES.items() if x == d["finish"]))
            v["lam"] = tk.BooleanVar(value=d["lam"])  # Laminate and its sheets on one row (2026-11-17_11)
            ttk.Checkbutton(self.options, text="Laminate", variable=v["lam"]).grid(row=row, column=0, sticky="w", pady=2)
            lam = ttk.Frame(self.options)
            lam.grid(row=row, column=1, sticky="w", pady=2)
            ttk.Label(lam, text="Sheets to laminate (0 = all):").pack(side="left")
            v["lam_sheets"] = tk.StringVar(value=str(d["lam_sheets"]))
            ttk.Entry(lam, textvariable=v["lam_sheets"], width=6, font=FONT).pack(side="left", padx=(6, 0))
            row += 1
            v["cuts"] = entry("Cuts (how many)", d.get("cuts", 0))
            # Rotate sort (2026-11-19_05): each set lies crosswise on the one before (A4 plain paper, one copier).
            v["rotate"] = tk.BooleanVar(value=bool(d.get("rotate")))
            self.rotate_box = ttk.Checkbutton(self.options, text="Rotate sort", variable=v["rotate"])
            self.rotate_box.grid(row=row, column=0, sticky="w", pady=2)
            self.rotate_why = ttk.Label(self.options, text="", style="Hint.TLabel", wraplength=300, justify="left")
            self.rotate_why.grid(row=row, column=1, sticky="w", pady=2)
            row += 1
            for key in ("size", "paper"):
                v[key].trace_add("write", lambda *_: self.check_rotate())
            self.rotate_item = item
            self.check_rotate()
        else:
            p = next(p for p in cat.PRODUCTS if p["name"] == self.what.get())
            picks = item["picks"] if item else cat.default_picks(p)
            for o in p["options"]:
                self.option_vars[o["key"]] = combo(o["label"], o["choices"], o["choices"][picks.get(o["key"], 0)])
            label = "Quantity (A4 label sheets)" if p["id"] == "labels" else "Quantity"
            self.option_vars["qty"] = combo(label, [str(q) for q in p["qty"]], str(item["qty"] if item else p["qty"][0]),
                                            typed=True)  # any number of 1 or more; the list only offers the usual ones
        # Services (Extras sheet): ticked on any item; per piece on a document: staff type how many.
        self.service_vars = {}
        chosen = (item or {}).get("services") or {}
        if pl.services:
            ttk.Label(self.options, text="Services:").grid(row=row, column=0, sticky="nw", pady=(4, 0))
            box = ttk.Frame(self.options)
            box.grid(row=row, column=1, sticky="w", pady=(4, 0))
            for k, name in enumerate(pl.services):
                tick = tk.BooleanVar(value=name in chosen)
                ttk.Checkbutton(box, text=name, variable=tick, padding=0).grid(row=k, column=0, sticky="w", pady=0)
                count = tk.StringVar(value=str(chosen[name]) if isinstance(chosen.get(name), int)
                                     and not isinstance(chosen.get(name), bool) else "")
                if self.what.get() == "Document" and pl.services[name][1] == "piece":
                    ttk.Label(box, text="how many:").grid(row=k, column=1, sticky="e", padx=(10, 4))
                    ttk.Entry(box, textvariable=count, width=6, font=FONT).grid(row=k, column=2, sticky="w", pady=0)
                self.service_vars[name] = (tick, count)
            row += 1
        self.show_box()
        self.form.top()  # a new form starts at its first field
        theme.on_surface(self.editor)

    # -------------------------------------------------------------- the drop box

    def form_kind(self):
        return "document" if self.what.get() == "Document" else "product"

    def multi(self):
        """Several files held for a Document: Add item makes one item per file (2026-11-19_04)."""
        return self.form_kind() == "document" and len(self.held) > 1 and self.editing is None

    BOX_ROWS = 5  # files shown in the box before its list scrolls (Add item and Place order stay on the screen)

    def show_box(self):
        """The box: its wording (as the boxes in Orders), then each held file with an x to take it off. Several files
        for a Document say what Add item will do; a long list scrolls inside the box."""
        for w in self.box.winfo_children():
            w.destroy()
        n = len(self.held)
        text = (f"{n} files: Add item makes {n} document items with these settings" if self.multi()
                else DROP_TEXT[self.form_kind()].replace("⤓  ", "⤓ "))
        tk.Label(self.box, text=text, background=theme.FIELD, foreground=theme.TEXT if not self.held or self.multi()
                 else theme.MUTED, font=("Segoe UI", 11, "bold" if self.multi() else "normal"),
                 justify="center", wraplength=260).grid(row=0, column=0, sticky="we",
                                                        pady=(8 if not self.held else 0, 8 if not self.held else 4))
        if self.held:
            line = 22
            canvas = tk.Canvas(self.box, background=theme.FIELD, highlightthickness=0, borderwidth=0,
                               height=min(n, self.BOX_ROWS) * line, width=260)
            canvas.grid(row=1, column=0, sticky="we")
            inner = tk.Frame(canvas, background=theme.FIELD)
            inner.columnconfigure(0, weight=1)
            item = canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
            inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
            if n > self.BOX_ROWS:
                bar = ttk.Scrollbar(self.box, orient="vertical", command=canvas.yview)
                bar.grid(row=1, column=1, sticky="ns")
                canvas.configure(yscrollcommand=bar.set)
                canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
            self.box_files = canvas
            for k, path in enumerate(self.held):
                name = tk.Label(inner, text=f"📎 {Path(path).name}", background=theme.FIELD, foreground=theme.OK,
                                font=("Segoe UI", 10), anchor="w", justify="left", height=1)
                name.grid(row=k, column=0, sticky="we")
                x = tk.Label(inner, text="✕", background=theme.FIELD, foreground=theme.MUTED, cursor="hand2",
                             font=("Segoe UI", 10, "bold"), padx=4)
                x.grid(row=k, column=1, sticky="e")
                x.bind("<Button-1>", lambda _e, i=k: self.unhold(i))
                if n > self.BOX_ROWS:
                    for w in (name, x):
                        w.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"), add="+")
        # Choose file… (2026-11-19_10): the same as a drop; several files for a product, and for a document (19_04)
        tk.Button(self.box, text="Choose file…", command=self.choose_for_box, background=theme.BUTTON,
                  foreground=theme.TEXT, activebackground=theme.BUTTON, activeforeground=theme.TEXT, relief="flat",
                  font=("Segoe UI", 10), padx=8, pady=1, cursor="hand2").grid(row=2, column=0, sticky="w", pady=(4, 2))
        self.show_multi()

    def choose_for_box(self):
        paths = choose_files(self.win, many=True)
        if paths:
            self.drop_in_box(paths)

    def rotate_reason(self, item):
        import routing
        installed = routing.installed_printers()
        return walkin_print.rotate_reason(self.ctx.rules, dict(item, print=(getattr(self, "rotate_item", None) or {})
                                                                 .get("print")), installed)

    def check_rotate(self):
        """Grey the Rotate sort tick with the reason when it can't be used; a tick that no longer fits (size or paper
        changed) is taken off, saying why."""
        v = self.option_vars
        box = getattr(self, "rotate_box", None)
        if box is None or "rotate" not in v:
            return
        try:
            why = self.rotate_reason({"size": v["size"].get(), "paper": v["paper"].get()})
            if why:
                if v["rotate"].get():
                    v["rotate"].set(False)
                box.state(["disabled"])
            else:
                box.state(["!disabled"])
            self.rotate_why.config(text=why or "")
        except tk.TclError:
            pass

    def show_multi(self):
        """Several files: Pages says "from each file" and can't be typed, and colour is B&W or Colour only."""
        entry, box, v = getattr(self, "pages_entry", None), getattr(self, "colour_box", None), self.option_vars
        if self.form_kind() != "document" or entry is None or "pages" not in v:
            return
        try:
            if self.multi():
                v["pages"].set("from each file")
                entry.state(["disabled"])
                entry.config(width=14)
                box.config(values=list(MULTI_COLOURS))
                if COLOUR_CHOICES.get(v["color"].get()) == "mixed":
                    v["color"].set("B&W")
                    self.editor_error.config(text="Several files: colour pages can't be listed for them all, so "
                                                  "Colour is B&W (or pick Colour).", style="Warn.TLabel")
            else:
                entry.state(["!disabled"])
                entry.config(width=8)
                if v["pages"].get() == "from each file":
                    v["pages"].set(str(file_pages(self.held[0]) or "") if self.held else "1")
                box.config(values=list(COLOUR_CHOICES))
        except tk.TclError:
            pass

    def usable(self, paths, kind):
        """(the files that can be taken, why the others can't): a folder, an empty file, over 200 MB, a file of a
        type a document can't print, or a second copy of a file already here (2026-11-19_04: the rest are taken)."""
        good, bad = [], []
        for x in paths:
            why = wo.drop_problem(x, kind)
            if not why and same_file(x, good + self.held + [f for files in self.drops for f in files]):
                why = f"{Path(x).name}: already added"
            (bad if why else good).append(why or x)
        return good, bad

    def drop_in_box(self, paths):
        """Files dropped in the box: held for the item on the form. A Document takes several (2026-11-19_04: Add item
        makes one item per file); one PDF fills in Pages. Editing a document: several files make new items like it."""
        kind = self.form_kind()
        if kind == "product":
            if not check_drop(self.win, kind, paths):
                return
            self.held += [x for x in paths if x not in self.held]
        else:
            good, bad = self.usable(paths, "document")
            if bad:
                messagebox.showwarning(parent=self.win, title="ORCA", message="Not taken:\n" + "\n".join(bad)
                                       + ("\n\nThe other files were taken." if good else ""))
            if not good:
                return
            if self.editing is not None and len(good) > 1:
                self.add_like(self.editing, good)
                return
            if self.editing is not None:
                self.held = good
            else:
                self.held += good
            if len(self.held) == 1:
                pages = pdf_pages(self.held[0])
                if pages and "pages" in self.option_vars:
                    self.option_vars["pages"].set(str(pages))
        self.editor_error.config(text="")
        self.show_box()
        self.reprice()

    def add_like(self, index, files):
        """Files dropped onto a document item (or while editing it): asks once, then one new item per file with its
        settings. The item keeps its own file; one with no file yet takes the first."""
        files = list(files)
        own = self.drops[index] if index < len(self.drops) else []
        first = None if own else files.pop(0)
        if files and not messagebox.askyesno(parent=self.win, title="ORCA",
                                             message=f"Add {len(files)} more item{'s' if len(files) > 1 else ''} "
                                                     f"like item {index + 1}?"):
            return
        if first:
            self.drops[index] = [first]
        self.make_items(dict(self.items[index]), files)
        self.cancel_edit()
        self.reprice()

    def make_items(self, template, files):
        """One document item per file, all with the template's settings; Pages from each file (a PDF's pages, an
        image 1, an Office file counted in the background, else "type the pages")."""
        template.pop("source_name", None)
        template.pop("pages_unknown", None)
        for path in files:
            item = dict(template, source_name=Path(path).name)
            pages = file_pages(path)
            if pages:
                item["pages"] = pages
            else:
                item["pages"], item["pages_unknown"] = 0, True
                self.count_later(item, path)
            self.items.append(item)
            self.drops.append([path])

    def count_later(self, item, path):
        """An Office file's pages, counted on a thread; filled in (and repriced) when known, never freezing."""
        box = {}

        def run():
            box["pages"] = count_pages(path, item["size"])

        def wait():
            if "pages" not in box:
                self.win.after(200, wait)
                return
            if box["pages"] and any(it is item for it in self.items) and item.get("pages_unknown"):
                item["pages"] = box["pages"]
                item.pop("pages_unknown", None)
                try:
                    self.reprice()
                except tk.TclError:
                    pass

        threading.Thread(target=run, daemon=True).start()
        self.win.after(200, wait)

    def unhold(self, index):
        if 0 <= index < len(self.held):
            del self.held[index]
        self.show_box()
        self.reprice()

    def what_changed(self):
        """A product's files kept when switching to Document: one file, of a type a document takes."""
        note = ""
        if self.what.get() == "Document" and self.held:
            fits = [x for x in self.held if wo.drop_problem(x, "document") is None]
            if len(self.held) > 1 and fits:
                note = f"Documents take one file: kept {Path(fits[0]).name}"
            elif not fits:
                note = f"A document can't print {', '.join(Path(x).name for x in self.held)}: taken off"
            self.held = fits[:1]
        self.build_options()
        self.editor_error.config(text=note)

    def read_item(self):
        """The item from the editor, or raises ValueError with what is wrong."""
        v = self.option_vars
        if self.what.get() == "Document":
            def whole(key, name, low=1):
                t = v[key].get().strip()
                if not t.isdigit() or int(t) < low:
                    raise ValueError(f"{name}: a whole number of {low} or more.")
                return int(t)
            item = {"kind": "document", "size": v["size"].get(), "pages": 1 if self.multi() else whole("pages", "Pages"),
                    "copies": whole("copies", "Copies"), "color": COLOUR_CHOICES[v["color"].get()],
                    "color_pages": v["color_pages"].get().strip(), "sides": SIDE_CHOICES[v["sides"].get()],
                    "per_side": int(v["per_side"].get()), "paper": v["paper"].get(),
                    "finish": FINISH_CHOICES[v["finish"].get()], "lam": bool(v["lam"].get()),
                    "lam_sheets": whole("lam_sheets", "Sheets to laminate", 0), "cuts": whole("cuts", "Cuts", 0)}
            if v.get("rotate") is not None and v["rotate"].get() and not self.rotate_reason(item):
                item["rotate"] = True
            if item["color"] == "mixed" and not walkin_pricing.page_set(item["color_pages"], item["pages"]):
                raise ValueError("Colour pages: say which pages are in colour (e.g. 1, 3-5).")
            if item["copies"] > 999:
                raise ValueError("Copies: 999 at most.")
        else:
            p = next(p for p in cat.PRODUCTS if p["name"] == self.what.get())
            picks = {o["key"]: o["choices"].index(v[o["key"]].get()) for o in p["options"]}
            qty = v["qty"].get().strip()
            if not qty.isdigit() or int(qty) < 1:
                raise ValueError("Quantity: a whole number of 1 or more.")
            item = {"kind": "product", "product": p["id"], "qty": int(qty), "picks": picks}
        services = {}
        for name, (tick, count) in getattr(self, "service_vars", {}).items():
            if not tick.get():
                continue
            text = count.get().strip()
            if text and not text.isdigit():
                raise ValueError(f"{name}: how many is a whole number (not money).")
            services[name] = int(text) if text else True
        if services:
            item["services"] = services
        return item

    def add_item(self):
        try:
            item = self.read_item()
        except ValueError as e:
            self.editor_error.config(text=str(e), style="Bad.TLabel")
            return
        if self.editing is not None and item["kind"] == "document":
            old = self.items[self.editing]
            if old.get("source_name") and self.held and Path(self.held[0]).name == old["source_name"]:
                item["source_name"] = old["source_name"]  # still the file it was named after
        # An item the price list has no price for can't be added (prices are fixed: nobody types one).
        trial = list(self.items)
        index = len(trial) if self.editing is None else self.editing
        trial[index:index + 1] = [item]
        own = f"Item {index + 1}: "
        pl = walkin_prices.current()
        self.warn.config(text="\n".join(pl.warnings[:6]))  # the yellow line follows the file (missing, no prices yet)
        problems = [p[len(own):] for p in walkin_pricing.price_order(pl, trial)["problems"] if p.startswith(own)]
        if problems:
            self.editor_error.config(text="\n".join(problems), style="Bad.TLabel")
            return
        self.editor_error.config(text="", style="Bad.TLabel")
        if self.multi():  # several files: one item per file, with these settings (2026-11-19_04)
            files = list(self.held)
            self.make_items(item, files)
            self.cancel_edit()
            self.reprice()
            return
        if self.editing is None:
            self.items.append(item)
            self.drops.append(list(self.held))  # the box's files go with the new item
        else:
            self.items[self.editing] = item
            self.drops[self.editing] = list(self.held)  # the box showed the item's files: saved back
        self.cancel_edit()
        self.reprice()

    def selected(self):
        """(item index, file index or None) of the selected row, or None."""
        sel = self.tree.selection()
        if not sel:
            return None
        if sel[0].startswith("f:"):
            _, i, k = sel[0].split(":")
            return int(i), int(k)
        if sel[0].startswith("w:"):  # a working line: its item
            return int(sel[0].split(":")[1]), None
        return int(sel[0]), None

    def edit_item(self):
        sel = self.selected()
        if not sel:
            return
        self.editing = sel[0]
        item = self.items[self.editing]
        self.held = list(self.drops[self.editing]) if self.editing < len(self.drops) else []
        self.what.set("Document" if item["kind"] == "document" else walkin_pricing.product_of(item)["name"])
        self.build_options(item)
        self.editor.config(text=f"Edit item {self.editing + 1}")
        self.add_btn.config(text="Save item")
        self.cancel_edit_btn.pack(side="left", padx=(8, 0))

    def cancel_edit(self):
        self.editing = None
        self.held = []  # files never added to an item are let go (nothing was copied)
        self.editor.config(text="Add an item")
        self.add_btn.config(text="Add item")
        self.cancel_edit_btn.pack_forget()
        self.build_options()

    def remove_item(self):
        """Remove the selected item, or the selected dropped file (only ORCA's note of it: the file stays put)."""
        sel = self.selected()
        if not sel:
            return
        i, k = sel
        if k is not None:
            del self.drops[i][k]
        else:
            del self.items[i]
            del self.drops[i]
            self.cancel_edit()
        self.reprice()

    def drop_on_list(self, paths, x, y):
        """Files dropped on the item list: kept with the item under the mouse (one item: that one; else asks)."""
        if not self.items:
            messagebox.showwarning(parent=self.win, title="ORCA", message="Add the item first, then drop its file "
                                                                          "onto it.\n\nNothing was kept.")
            return
        row = self.tree.identify_row(y - self.tree.winfo_rooty())
        if row:
            i = int(row.split(":")[1]) if row.startswith(("f:", "w:")) else int(row)
        elif len(self.items) == 1:
            i = 0
        else:
            i = ask_item(self.win, [f"{k + 1}. {walkin_pricing.describe(it)}" for k, it in enumerate(self.items)])
            if i is None:
                return
        kind = self.items[i]["kind"]
        if kind == "document" and len(paths) > 1:  # several files: new items like this one (2026-11-19_04)
            good, bad = self.usable(paths, "document")
            if bad:
                messagebox.showwarning(parent=self.win, title="ORCA", message="Not taken:\n" + "\n".join(bad)
                                       + ("\n\nThe other files were taken." if good else ""))
            if good:
                self.add_like(i, good)
            return
        if not check_drop(self.win, kind, paths):
            return
        if kind == "document" and self.drops[i]:
            if not messagebox.askyesno(parent=self.win, title="ORCA",
                                       message=f"Item {i + 1} already has {Path(self.drops[i][0]).name}.\n\n"
                                               f"Use {Path(paths[0]).name} instead?"):
                return
            self.drops[i] = []
        for path in paths:
            if path not in self.drops[i]:
                self.drops[i].append(path)
        self.reprice()

    # -------------------------------------------------------------- prices

    def loyalty_choice(self):
        """"auto" (Automatic) or the level 0-3 picked by hand."""
        value = self.loyalty.get()
        if value.startswith("Automatic"):
            return "auto"
        return 0 if value == "None" else int(value)

    def loyalty_level(self):
        choice = self.loyalty_choice()
        return self.auto[0] if choice == "auto" else choice

    def auto_text(self):
        """The Automatic choice: with the recognised customer's level and spending."""
        if self.filled_from is None:
            return "Automatic"
        level, spent = self.auto
        return f"Automatic ({f'Level {level}' if level else 'no level yet'}, {euro(spent)} in 12 months)"

    def set_rounding(self, mode):
        """A rounding button: replaces any rounding; the same one again (or No rounding) goes back."""
        self.rounding = None if mode == self.rounding else mode
        self.reprice()

    def reprice(self):
        pl = walkin_prices.current()
        self.warn.config(text="\n".join(pl.warnings[:6]))
        self.priced = walkin_pricing.price_order(pl, self.items, self.loyalty_level(), self.rounding)
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self.drops = (self.drops + [[] for _ in self.items])[:len(self.items)]
        notes = []
        self.tree.tag_configure("type_pages", foreground=theme.WARN)
        for i, (item, line) in enumerate(zip(self.items, self.priced["lines"])):
            text = walkin_pricing.describe(item)
            tags = ("type_pages",) if item.get("pages_unknown") else ()
            self.tree.insert("", "end", iid=str(i), values=(i + 1, text, euro(line["price"])), open=True, tags=tags)
            for k, work in enumerate(line["working"][1:-1]):  # how the price is worked out (2026-11-17_08)
                self.tree.insert(str(i), "end", iid=f"w:{i}:{k}", values=("", f"      {work}", ""), tags=("working",))
            for k, path in enumerate(self.drops[i] if i < len(self.drops) else []):
                self.tree.insert(str(i), "end", iid=f"f:{i}:{k}",
                                 values=("", f"      📎 {Path(path).name}   (select it and press Remove to take it off)", ""))
            if line["note"] and line["note"] not in notes:
                notes.append(line["note"])
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep)
        self.notes.config(text="\n".join(notes))
        lines = [f"Items: {euro(sum(l['price'] for l in self.priced['lines']))}"]
        if self.priced["volume"]:
            lines.append(f"Volume price (never more for fewer copies): {euro(self.priced['volume'])}")
        loyalty = self.priced["loyalty"]
        if loyalty:
            lines.append(f"{loyalty['text']}: -{euro(-loyalty['amount'])}" if loyalty["amount"] else loyalty["text"])
        self.total_lines.config(text="\n".join(lines))
        total, due = self.priced["total"], self.priced["due"]
        if abs(due - total) < 0.005:
            self.total_label.config(text=f"Total: {euro(total)}")
        else:
            way = "up" if due > total else "down"
            self.total_label.config(text=f"Total: {euro(due)} (rounded {way} from {total:,.2f})")
        for mode, b in self.round_buttons.items():
            b.state(["pressed"] if mode == self.rounding else ["!pressed"])
        self.problems.config(text="\n".join(self.priced["problems"]))

    # -------------------------------------------------------------- the customer

    def lookup(self):
        """A phone or email ORCA knows fills in the name and loyalty: Automatic with the level their spending gives,
        or the level set by hand (staff can change both)."""
        c = wo.Customers().lookup(self.cust_vars["phone"].get(), self.cust_vars["email"].get())
        if c and c["id"] != self.filled_from:
            self.filled_from = c["id"]
            self.cust_vars["name"].set(c["name"])
            level, mode, spent = wo.level_of(c)
            self.auto = (walkin_prices.current().level_for(spent), spent)
            self.loyalty_box.config(values=[self.auto_text(), "None", "1", "2", "3"])
            self.loyalty.set(self.auto_text() if mode == "auto" else (str(level) if level else "None"))
            self.known.config(text=f"Known customer: {c['name']} ({', '.join(c['phones'] + c['emails'])})")
            self.reprice()
        elif not c and self.filled_from is not None:
            self.known.config(text="")
            self.filled_from = None
            self.auto = (0, 0.0)
            auto = self.loyalty.get().startswith("Automatic")
            self.loyalty_box.config(values=["Automatic", "None", "1", "2", "3"])
            if auto:
                self.loyalty.set("Automatic")
            self.reprice()

    def discard(self):
        if self.items and not messagebox.askyesno(parent=self.win, title="ORCA",
                                                  message="Discard this quote? Nothing is saved."):
            return
        self.back()

    def place(self):
        name, phone, email = (self.cust_vars[k].get().strip() for k in ("name", "phone", "email"))
        if not self.items:
            messagebox.showwarning(parent=self.win, title="ORCA", message="Add at least one item.")
            return
        if self.priced["problems"]:
            messagebox.showwarning(parent=self.win, title="ORCA", message="\n".join(self.priced["problems"]))
            return
        if self.mode == "quote" and (not name or not wo.norm_phone(phone)):
            messagebox.showwarning(parent=self.win, title="ORCA", message="Name and phone are both needed.")
            return
        if self.mode == "email" and not (name or wo.norm_phone(phone) or wo.norm_email(email)):
            messagebox.showwarning(parent=self.win, title="ORCA", message="Give a name, a phone or an email.")
            return
        customers = wo.Customers()
        keep = True
        if not customers.known(phone, email):  # a first-time customer: keep their details? (2026-11-17_07)
            keep = ask_keep(self.win)
            if keep is None:
                return  # closed: nothing is placed
        join = None
        clash = customers.conflict(phone, email)
        if clash:
            join = messagebox.askyesno(parent=self.win, title="ORCA",
                                       message=f"This phone is {clash[0]['name'] or clash[0]['folder']} and this email "
                                               f"is {clash[1]['name'] or clash[1]['folder']} in ORCA. Same customer?")
        try:  # a name with no phone or email: a new customer every time (Customers.resolve)
            if keep:
                customer = customers.resolve(name, phone, email, self.loyalty_choice(), join=join)
            else:  # Don't keep: no record; only what is needed to call them and hand the order over
                customer = {"id": "x" + uuid.uuid4().hex[:10], "name": name}
            customer = dict(customer, entered_name=name, entered_phone=phone, entered_email=email)
            order = wo.place(self.items, self.priced, customer, self.mode, self.priced["loyalty"], keep_data=keep)
        except ValueError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=str(e))
            return
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=f"Could not make the order folder.\n\n{e}")
            return
        try:
            os.startfile(order["_folder"])
        except OSError:
            pass
        self.placed_number = order["number"]
        dialog = NumberDialog(self.win, order)
        # Files dropped on the quote's items: copied into the item folders now (the originals stay where they are).
        tasks, problems = [], []
        for item, files in zip(order["items"], self.drops):
            for path in files:
                why = wo.drop_problem(path, item["kind"])
                if why:
                    problems.append(why)
                else:
                    tasks.append((order, item, path, []))
        if problems:
            messagebox.showwarning(parent=self.win, title="ORCA", message="Not copied into the order:\n"
                                                                          + "\n".join(problems))
        if tasks:
            copy_in_background(dialog.dlg, tasks, dialog.copied)
        self.items = []
        self.drops = []
        self.rounding = None
        for v in self.cust_vars.values():
            v.set("")
        self.loyalty.set("Automatic")
        self.cancel_edit()
        self.reprice()


class NumberDialog:
    """The new order's number, large, and its items, each with a drop area for its file."""

    def __init__(self, parent, order):
        self.order = order
        self.dlg = dlg = tk.Toplevel(parent)
        dlg.title("ORCA - order placed")
        dlg.transient(parent)
        f = ttk.Frame(dlg, padding=30)
        f.grid()
        ttk.Label(f, text="Order placed").grid(row=0, column=0)
        ttk.Label(f, text=f"#{order['number']}", style="Huge.TLabel").grid(row=1, column=0, pady=10)
        ttk.Label(f, text=f"{customer_text(order['customer'])}\n{euro(wo.price_due(order))}\n"
                          f"Drop each item's file onto it below, or put it into its folder (open in Explorer).",
                  justify="center").grid(row=2, column=0)
        items = ttk.Frame(f)
        items.grid(row=3, column=0, sticky="we", pady=(12, 0))
        self.areas = []
        for i, item in enumerate(order["items"]):
            ttk.Label(items, text=f"{i + 1}. {item['description']}", wraplength=560, justify="left").grid(
                row=2 * i, column=0, sticky="w", pady=(6, 0))
            area = drop_area(items, item["kind"], lambda paths, x, y, k=i: self.drop(k, paths))
            area.grid(row=2 * i + 1, column=0, sticky="we", padx=(18, 0))
            self.areas.append(area)
        self.status = ttk.Label(f, text="", style="Small.TLabel", wraplength=600, justify="center")
        self.status.grid(row=4, column=0, pady=(8, 0))
        ttk.Button(f, text="OK", style="Print.TButton", command=dlg.destroy).grid(row=5, column=0, pady=(16, 0))
        theme.dark_title_bar(dlg)
        filedrop.enable(dlg)
        self.refresh()

    def drop(self, index, paths):
        drop_onto_item(self.dlg, self.order, index, paths, self.copied)

    def copied(self, text, failed):
        try:
            self.status.config(text=text)
            self.refresh()
        except tk.TclError:
            pass  # closed meanwhile: the files are in the folders anyway

    def refresh(self):
        """Each item's drop area names the files in its folder (ORCA's own .cdr and Options.txt left out)."""
        for item, area in zip(self.order["items"], self.areas):
            if item["kind"] == "document":
                f = wo.item_file(self.order, item)
                names = [f.name] if f else []
            else:
                f = wo.item_file(self.order, item)
                names = [p.name for p in wo.customer_files(self.order, item)] + ([f.name] if f else [])
            if names:
                area.label.config(text=f"✓ {', '.join(names)}   (drop here to add or replace)", foreground=theme.OK)
            else:
                area.label.config(text=DROP_TEXT[item["kind"]], foreground=theme.MUTED)


# ------------------------------------------------------------------ shared order cards

class OrderList(Screen):
    """A screen of order cards, refreshed while it is open (files dropped in, prints done)."""

    def __init__(self, ctx, title, on_back):
        super().__init__(ctx, title, on_back)
        self.frame.rowconfigure(3, weight=1)
        self.status = ttk.Label(self.frame, text="", style="Small.TLabel")
        self.status.grid(row=2, column=0, sticky="w", pady=(6, 4))
        self.scroll = costs.ScrollFrame(self.frame)
        self.scroll.grid(row=3, column=0, sticky="nsew")
        self.signature = None

    def poll(self):
        if not self.win.winfo_exists():
            return
        self.handle_results()
        orders = [wo.refresh(o) for o in wo.list_open()]
        self.got_orders(orders)
        sig = self.signature_of(orders)
        if sig != self.signature:
            self.signature = sig
            top = self.scroll.canvas.yview()[0]
            for w in self.scroll.inner.winfo_children():
                w.destroy()
            self.scroll.inner.columnconfigure(0, weight=1)
            self.fill(orders)
            self.win.update_idletasks()
            self.scroll.canvas.yview_moveto(top)
        self.win.after(1500, self.poll)

    def handle_results(self):
        pass

    def got_orders(self, orders):
        """The open orders as just read (the print queue's states and the order lines follow them)."""
        self.ctx.print_queue.update(orders)

    def signature_of(self, orders):
        prep, run = self.ctx.preparer, self.ctx.print_queue
        return tuple((o["number"], o["status"], o.get("changed_total"), run.order_state(o), tuple(
            (i.get("file"), i.get("sheets"), str(i.get("print")), bool(prep.get(o, i)),
             tuple(p.name for p in wo._files(o, i))) for i in o["items"]))
            for o in orders) + (self.extra_signature(),)

    def extra_signature(self):
        return None

    def card(self, parent, order, buttons):
        box = ttk.LabelFrame(parent, text=f"#{order['number']}  ·  {order['source']}  ·  {euro(wo.price_due(order))}"
                             + wo.rounded_text(order).replace(" (", "  ("),
                             padding=10, style="Section.TLabelframe")
        box.columnconfigure(0, weight=1)
        times = order["times"]
        ttk.Label(box, text=f"Placed {when(times['placed'])}   ·   printed {when(times['printed'])}   ·   "
                            f"ready {when(times['ready'])}", style="Small.TLabel").grid(row=0, column=0, sticky="w")
        r = 1
        droppable = self.can_drop(order)
        box.item_rows = []
        for i, item in enumerate(order["items"]):
            state = self.item_state(order, item)
            working = "   ·   ".join(item.get("working", [])[1:-1])  # how the price was worked out (2026-11-17_08)
            line = ttk.Label(box, text=f"{i + 1}. {item['description']}   {euro(item['price'])}"
                                       + (f"\n      {working}" if working else ""))
            line.grid(row=r, column=0, sticky="w")
            note = ttk.Label(box, text=f"     {state[0]}", style=state[1])
            note.grid(row=r + 1, column=0, sticky="w")
            box.item_rows.append(r)
            r += 2
            if droppable:
                on_drop = (lambda paths, x, y, k=i: self.drop_on_item(order, k, paths))
                filedrop.target(line, on_drop)
                filedrop.target(note, on_drop)
                drop_area(box, item["kind"], on_drop).grid(row=r, column=0, sticky="w", padx=(22, 0), pady=(2, 4))
                r += 1
        if droppable:
            filedrop.target(box, lambda paths, x, y: self.drop_on_order(order, paths))
        row = ttk.Frame(box)
        row.grid(row=r, column=0, sticky="w", pady=(6, 0))
        for text, command, style in buttons:
            ttk.Button(row, text=text, command=command, style=style or "TButton").pack(side="left", padx=(0, 8))
        theme.on_surface(box)
        return box

    def can_drop(self, order):
        """Files can be dropped onto an order still waiting or ready, not while a copier prints it."""
        parts = order.get("parts") or {}
        return order["status"] in ("waiting", "ready_to_print") and not any(
            p["state"] == "printing" for p in parts.values())

    def drop_on_order(self, order, paths):
        """Dropped on the order, not on an item: its one item, or the item staff pick."""
        if len(order["items"]) == 1:
            index = 0
        else:
            index = ask_item(self.win, [f"{i + 1}. {item['description']}" for i, item in enumerate(order["items"])])
            if index is None:
                return
        self.drop_on_item(order, index, paths)

    def drop_on_item(self, order, index, paths):
        drop_onto_item(self.win, order, index, paths, self.copied)

    def copied(self, text, failed):
        try:
            if text:
                self.status.config(text=text)
            self.signature = None
        except tk.TclError:
            pass

    def item_state(self, order, item):
        if item["kind"] == "product":
            return self.product_state(order, item)
        f = wo.item_file(order, item)
        if f is None:
            return (f"waiting for the file in “{item['folder']}”", "Warn.TLabel")
        return (f"✓ {f.name}", "Good.TLabel")

    def product_state(self, order, item):
        """Waiting for the customer's file, for layout, for Layout done; or ready (only W100-2.pdf prints)."""
        name = wo.stem(order, wo.item_index(order, item))
        customer = [p.name for p in wo.customer_files(order, item)]
        files = f" · customer files: {', '.join(customer)}" if customer else ""
        state, text, stamp = wo.sheet_state(order, item)
        if state == "none":
            if not customer:
                return (f"Waiting for the customer's file (put it in “{item['folder']}”)", "Warn.TLabel")
            return (f"Waiting for layout: lay it out in {name}.cdr and export {name}.pdf{files}", "Warn.TLabel")
        if state == "saving":
            return (text + files, "Small.TLabel")
        if state == "bad":
            return (text + files, "Bad.TLabel")
        if not wo.laid_out(order, item):
            again = item.get("stamp") and item.get("sheets")
            return (f"{name}.pdf {'changed: press Layout done again' if again else 'found: press Layout done'}{files}",
                    "Warn.TLabel")
        return (f"✓ {name}.pdf, {item['sheets']} sheets{files}", "Good.TLabel")

    def open_folder(self, order):
        try:
            os.startfile(order["_folder"])
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA", message=f"Could not open the folder.\n\n{e}")

    def ready_for_pickup(self, order):
        wo.set_status(order, "ready_for_pickup")
        self.signature = None


# ------------------------------------------------------------------ Print Jobs

class PrintJobsScreen(OrderList):
    """The copier queue (walkin_queue.py) and the orders ready to print, grouped by customer. Nothing is sent until
    Start printing orders (every free copier takes its first customer) or Print now (one order, free copiers only).
    Each copier's block shows what it prints, its buttons and its waiting customers, which staff drag into another
    order (or Move up / Move down)."""

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Print Jobs", on_back)
        self.fit("1320x960")
        self.run = ctx.print_queue
        self.run.parent = self.win
        ttk.Button(self.top, text="Start printing orders", style="Print.TButton", command=self.start).pack(
            side="left", padx=(40, 0))
        ttk.Button(self.top, text="Stop printing orders", command=self.stop).pack(side="left", padx=(10, 0))
        bar = ttk.Frame(self.frame)
        bar.grid(row=1, column=0, sticky="we", pady=(8, 0))
        bar.columnconfigure(0, weight=1)
        self.run_label = ttk.Label(bar, text="", style="Small.TLabel")
        self.run_label.grid(row=0, column=0, sticky="w")
        blocks = ttk.Frame(bar)
        blocks.grid(row=1, column=0, sticky="we", pady=(6, 0))
        self.panels = {}
        self.drag = None
        for n, (pid, p) in enumerate(ctx.rules["printers"].items()):
            blocks.columnconfigure(n, weight=1, uniform="copiers")
            box = ttk.LabelFrame(blocks, text=p["label"], padding=8, style="Section.TLabelframe")
            box.grid(row=0, column=n, sticky="nsew", padx=(0 if n == 0 else 8, 0))
            box.columnconfigure(0, weight=1)
            state = ttk.Label(box, text="", wraplength=380, justify="left", font=("Segoe UI", 11, "bold"))
            state.grid(row=0, column=0, sticky="w")
            buttons = ttk.Frame(box)
            buttons.grid(row=1, column=0, sticky="w", pady=4)
            ttk.Label(box, text="Waiting (drag to change the order):", style="Small.TLabel").grid(row=2, column=0,
                                                                                                 sticky="w")
            tree = ttk.Treeview(box, show="tree", height=6, selectmode="browse")
            tree.column("#0", width=380, stretch=True)
            tree.tag_configure("join", background=theme.SELECT)
            tree.grid(row=3, column=0, sticky="we")
            tree.bind("<ButtonPress-1>", lambda e, k=pid: self.press(k, e))
            tree.bind("<B1-Motion>", lambda e, k=pid: self.motion(k, e))
            tree.bind("<ButtonRelease-1>", lambda e, k=pid: self.release(k, e))
            moves = ttk.Frame(box)
            moves.grid(row=4, column=0, sticky="w", pady=(4, 0))
            ttk.Button(moves, text="Move up", command=lambda k=pid: self.move(k, -1)).pack(side="left")
            ttk.Button(moves, text="Move down", command=lambda k=pid: self.move(k, 1)).pack(side="left", padx=(8, 0))
            line = tk.Frame(tree, height=3, background=theme.PRIMARY)
            self.panels[pid] = {"state": state, "buttons": buttons, "tree": tree, "line": line, "button_sig": None,
                                "tree_sig": None, "batches": []}
            theme.on_surface(box)
        self.refresh_panels()
        self.ready()
        self.poll()
        self.quick()

    def quick(self):
        """The copier blocks follow the sending closely (the order cards every 1.5 s, with the poll)."""
        if not self.win.winfo_exists():
            return
        self.handle_results()
        self.refresh_panels()
        self.win.after(400, self.quick)

    def back(self):
        self.run.parent = self.ctx.win  # the queue carries on behind the menu
        super().back()

    # -------------------------------------------------------------- run

    def start(self):
        self.run.start_printing()
        self.refresh_panels()
        self.signature = None

    def stop(self):
        self.run.stop_printing()
        self.refresh_panels()

    def handle_results(self):
        self.run.handle_results()
        if self.run.messages:
            self.status.config(text=self.run.messages[-1])

    def got_orders(self, orders):
        self.run.update(orders)
        self.refresh_panels()

    def extra_signature(self):
        return tuple((pid, c["state"], tuple(c.get("orders", ()))) for pid, c in self.run.copiers.items())

    def print_now(self, order):
        message = self.run.print_now(order["number"])
        if message:
            messagebox.showwarning(parent=self.win, title="ORCA", message=message)
        self.refresh_panels()
        self.signature = None

    def collected(self, pid):
        self.run.collected(pid)
        self.refresh_panels()
        self.signature = None

    def send_backs(self, pid):
        self.run.send_backs(pid)
        self.refresh_panels()

    def retry(self, pid):
        self.run.retry(pid)
        self.refresh_panels()

    # -------------------------------------------------------------- the copier blocks

    def refresh_panels(self):
        self.run_label.config(text=copier_queue.run_text(self.run.running, "customer"))
        for pid, panel in self.panels.items():
            c = self.run.copiers[pid]
            panel["state"].config(text=self.run.copier_text(pid),
                                  foreground=theme.ERROR if c["state"] == "failed" else "")
            buttons = {"sent": [("Pages collected", self.collected)], "turn": [("Print backs", self.send_backs)],
                       "failed": [("Retry", self.retry)]}.get(c["state"], [])
            sig = (c["state"], tuple(b[0] for b in buttons))
            if sig != panel["button_sig"]:
                panel["button_sig"] = sig
                for w in panel["buttons"].winfo_children():
                    w.destroy()
                for text, command in buttons:
                    ttk.Button(panel["buttons"], text=text, style="Print.TButton",
                               command=lambda k=pid, f=command: f(k)).pack(side="left", padx=(0, 8))
            if self.drag is None:
                self.fill_queue(pid)

    def fill_queue(self, pid):
        """The copier's waiting batches: one line each, with its orders under it when it holds several."""
        panel = self.panels[pid]
        tree = panel["tree"]
        batches = self.run.batches(pid)
        lines = [(self.run.batch_text(pid, b), tuple(self.order_line(pid, n) for n in b) if len(b) > 1 else ())
                 for b in batches]
        sig = (tuple(map(tuple, batches)), tuple(lines))
        if sig == panel["tree_sig"]:
            return
        selected = self.selected_numbers(pid)
        panel["tree_sig"], panel["batches"] = sig, batches
        tree.delete(*tree.get_children())
        if not batches:
            tree.insert("", "end", iid="none", text="No customer waiting", tags=("none",))
        for k, (batch, (text, children)) in enumerate(zip(batches, lines)):
            tree.insert("", "end", iid=f"b{k}", text=text, open=True)
            for n, child in zip(batch, children):
                tree.insert(f"b{k}", "end", iid=f"o{n}", text=child)
        for iid in selected:
            if tree.exists(iid):
                tree.selection_set(iid)
                break

    def order_line(self, pid, number):
        sheets, colour, side = self.run.batch_info(pid, [number])
        cover = "" if self.run.cover_here(number, pid) else ", no cover sheet"
        return f"#{number}  ({walkin_queue.sheets_text(sheets)}, {colour}, {side}{cover})"

    def selected_numbers(self, pid):
        """Row ids to select again after the list is rebuilt (the same order, or the batch now holding it)."""
        tree, batches = self.panels[pid]["tree"], self.panels[pid]["batches"]
        sel = tree.selection()
        if not sel or sel[0] == "none":
            return []
        if sel[0].startswith("o"):
            return [sel[0]]
        first = batches[int(sel[0][1:])][0]
        return [f"o{first}"] + [f"b{k}" for k, b in enumerate(self.run.batches(pid)) if first in b]

    def batch_index(self, iid):
        if iid.startswith("o"):
            iid = self.panels_tree_parent(iid)
        return int(iid[1:]) if iid.startswith("b") else None

    def panels_tree_parent(self, iid):
        for panel in self.panels.values():
            if panel["tree"].exists(iid):
                return panel["tree"].parent(iid)
        return ""

    def move(self, pid, step):
        """Move up / Move down: the selected batch (or the batch of the selected order) one place."""
        tree = self.panels[pid]["tree"]
        sel = tree.selection()
        if not sel or sel[0] == "none":
            return
        k = int((tree.parent(sel[0]) if sel[0].startswith("o") else sel[0])[1:])
        batches = self.panels[pid]["batches"]
        if not 0 <= k + step < len(batches):
            return
        first = batches[k][0]
        self.run.move_batch(pid, k, k - 1 if step < 0 else k + 2)
        self.panels[pid]["tree_sig"] = None
        self.fill_queue(pid)
        for j, b in enumerate(self.panels[pid]["batches"]):
            if first in b:
                tree.selection_set(f"b{j}")
        self.signature = None

    # -------------------------------------------------------------- dragging in a copier's queue

    def press(self, pid, event):
        tree = self.panels[pid]["tree"]
        iid = tree.identify_row(event.y)
        self.drag = {"pid": pid, "iid": iid, "y": event.y, "moved": False} if iid and iid != "none" else None

    def dragged_number(self):
        """The order being dragged: an order line, or a batch line that holds one order (else None)."""
        d = self.drag
        batches = self.panels[d["pid"]]["batches"]
        if d["iid"].startswith("o"):
            return int(d["iid"][1:])
        batch = batches[int(d["iid"][1:])]
        return batch[0] if len(batch) == 1 else None

    def target(self, pid, y):
        """("before", k): the batch lands before batch k (k = the count: at the end); ("join", k): an order joins
        batch k, its own customer's."""
        tree = self.panels[pid]["tree"]
        batches = self.panels[pid]["batches"]
        tops = tree.get_children("")
        if not batches:
            return ("before", 0)
        row = tree.identify_row(y)
        if not row:
            last = tree.bbox(tops[-1]) if tops else None
            return ("before", 0 if last and y < last[1] else len(batches))
        top = tree.parent(row) or row
        k = int(top[1:])
        first = tree.bbox(top)
        kids = tree.get_children(top)
        end = tree.bbox(kids[-1]) if kids else first
        if not first or not end:
            return ("before", k)
        y0, y1 = first[1], end[1] + end[3]
        number = self.dragged_number()
        if number is not None and number not in batches[k]:
            same = self.run.orders[batches[k][0]]["customer"]["id"] == self.run.orders[number]["customer"]["id"]
            if same and y0 + (y1 - y0) * 0.25 <= y <= y1 - (y1 - y0) * 0.25:
                return ("join", k)
        return ("before", k if y < (y0 + y1) / 2 else k + 1)

    def motion(self, pid, event):
        d = self.drag
        if d is None or d["pid"] != pid:
            return
        if abs(event.y - d["y"]) > 4:
            d["moved"] = True
        if not d["moved"]:
            return
        tree, line = self.panels[pid]["tree"], self.panels[pid]["line"]
        for iid in tree.get_children(""):
            tree.item(iid, tags=())
        kind, k = self.target(pid, event.y)
        tops = tree.get_children("")
        if kind == "join":
            line.place_forget()
            tree.item(tops[k], tags=("join",))
            return
        if k < len(tops):
            box = tree.bbox(tops[k])
            y = box[1] if box else 0
        else:
            last = tops[-1]
            kids = tree.get_children(last)
            box = tree.bbox(kids[-1] if kids else last)
            y = box[1] + box[3] if box else 0
        line.place(x=0, y=max(0, y - 1), relwidth=1.0)
        line.lift()

    def release(self, pid, event):
        d = self.drag
        where = self.target(pid, event.y) if d is not None and d["pid"] == pid and d["moved"] else None
        self.drag = None
        tree, line = self.panels[pid]["tree"], self.panels[pid]["line"]
        line.place_forget()
        for iid in tree.get_children(""):
            tree.item(iid, tags=())
        if where is not None:
            self.drop_in_queue(pid, d["iid"], where)

    def drop_in_queue(self, pid, iid, where):
        """Apply a drag: iid the dragged line ("b<k>" a batch, "o<n>" one order), where from target()."""
        kind, k = where
        self.drag = {"pid": pid, "iid": iid}
        number = self.dragged_number()
        self.drag = None
        first = None
        if kind == "join":
            self.run.move_order(pid, number, join=k)
            first = number
        elif iid.startswith("o"):
            self.run.move_order(pid, number, before=k)
            first = number
        else:
            batch = self.panels[pid]["batches"][int(iid[1:])]
            first = batch[0]
            self.run.move_batch(pid, int(iid[1:]), k)
        self.panels[pid]["tree_sig"] = None
        self.fill_queue(pid)
        tree = self.panels[pid]["tree"]
        if tree.exists(f"o{first}"):
            tree.selection_set(f"o{first}")
        else:
            for j, b in enumerate(self.panels[pid]["batches"]):
                if first in b:
                    tree.selection_set(f"b{j}")
        self.signature = None

    # -------------------------------------------------------------- the order cards

    def fill(self, orders):
        shown = [o for o in orders if o["status"] in ("ready_to_print", "printed")]
        if not self.status.cget("text"):
            self.status.config(text="Nothing prints until you press Start printing orders (or Print now).")
        if not shown:
            ttk.Label(self.scroll.inner, text="No order is ready to print.", style="Small.TLabel").grid(sticky="w")
            return
        r = 0
        for name, group in group_by_customer(shown):
            ttk.Label(self.scroll.inner, text=name, style="Big.TLabel").grid(row=r, column=0, sticky="w", pady=(10, 4))
            r += 1
            for order in group:
                where = self.run.order_state(order)
                plan = self.run.plans.get(order["number"])
                if order["status"] == "printed":
                    buttons = [("Ready for pickup", lambda o=order: self.ready_for_pickup(o), "Print.TButton"),
                               ("Open folder", lambda o=order: self.open_folder(o), None)]
                else:
                    printing = where and where.startswith("Printing")
                    buttons = ([] if printing or not isinstance(plan, tuple) else
                               [("Print now", lambda o=order: self.print_now(o), "Print.TButton")])
                    buttons.append(("Open folder", lambda o=order: self.open_folder(o), None))
                box = self.card(self.scroll.inner, order, buttons)
                box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                if order["status"] == "printed":
                    ttk.Label(box, text="Printed", style="Good.TLabel").grid(row=0, column=0, sticky="e")
                elif where:
                    ttk.Label(box, text=where, style="Warn.TLabel").grid(row=0, column=0, sticky="e")
                elif isinstance(plan, str):
                    ttk.Label(box, text=f"Can't print yet: {plan}", style="Bad.TLabel").grid(row=0, column=0,
                                                                                         sticky="e")
                theme.on_surface(box)
                r += 1

    def item_state(self, order, item):
        f = wo.item_file(order, item)
        if f is None or (item["kind"] == "product" and not wo.laid_out(order, item)):
            return super().item_state(order, item)
        prepared = self.ctx.preparer.get(order, item)
        if prepared is None:
            return (f"{f.name}: checking the file…", "Small.TLabel")
        if "error" in prepared:
            return (prepared["error"], "Bad.TLabel")
        fixed = {int(i): p for p, part in (order.get("parts") or {}).items() for i in part["items"]}
        job = walkin_print.job_for(self.ctx.jobs, self.ctx.rules, item, prepared,
                                   printer=fixed.get(wo.item_index(order, item) - 1))
        if job is None:
            return ("these settings can't print: use Settings…", "Bad.TLabel")
        s = walkin_print.settings_for(self.ctx.rules, item, prepared)
        text = (f"{f.name} → {self.ctx.jobs.printers[job['printer']]['label']} · "
                f"{self.ctx.jobs.settings_text(s, job)}")
        return (text + (f" · {job['problem']}" if job["problem"] else ""), "Bad.TLabel" if job["problem"] else "Good.TLabel")

    def card(self, parent, order, buttons):
        box = super().card(parent, order, buttons)
        if order["status"] == "ready_to_print" and not order.get("parts"):  # once sent, where items go is fixed
            for i, r in enumerate(box.item_rows):
                ttk.Button(box, text="Settings…", command=lambda o=order, k=i: SettingsDialog(self, o, k)).grid(
                    row=r, column=1, rowspan=2, sticky="e")
        return box


class SettingsDialog:
    """Change one item's print settings before printing (copier, paper type, sides, colour, copies, tray)."""

    def __init__(self, screen, order, index):
        self.screen, self.order, self.index = screen, order, index
        rules = screen.ctx.rules
        item = order["items"][index]
        prepared = screen.ctx.preparer.get(order, item)
        s = walkin_print.settings_for(rules, item, prepared)
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(f"ORCA - #{order['number']} item {index + 1}")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=18)
        f.grid()
        ttk.Label(f, text=item["description"], style="Head.TLabel", wraplength=460).grid(row=0, column=0, columnspan=2,
                                                                                     sticky="w", pady=(0, 8))
        printers = {"Auto": "auto", **{p["label"]: pid for pid, p in screen.ctx.jobs.printers.items()}}
        self.fields = {}

        def combo(r, label, key, mapping, value):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=next((k for k, v in mapping.items() if v == value), value))
            ttk.Combobox(f, textvariable=var, values=list(mapping), state="readonly", width=30, font=FONT).grid(
                row=r, column=1, sticky="w", pady=3)
            self.fields[key] = (var, mapping)

        combo(1, "Copier:", "printer", printers, s["printer"])
        combo(2, "Paper type:", "paper_type", {t: t for t in rules["paper_types"]}, s["paper_type"])
        combo(3, "Sides:", "sides", {"One side": "single", "Both sides, long edge": "long",
                                     "Both sides, short edge": "short"}, s["sides"])
        combo(4, "Colour:", "color", {"B&W": "bw", "Colour": "color", "Auto (each page)": "auto"}, s["color"])
        combo(5, "Tray:", "tray", {t: t for t in rules["trays"]}, s["tray"])
        ttk.Label(f, text="Copies (products: sheets):").grid(row=6, column=0, sticky="w", pady=3)
        self.copies = tk.StringVar(value=s["copies"])
        ttk.Entry(f, textvariable=self.copies, width=8, font=FONT).grid(row=6, column=1, sticky="w", pady=3)
        self.error = ttk.Label(f, text="", foreground=theme.ERROR)
        self.error.grid(row=7, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.save).pack(side="left")
        ttk.Button(b, text="As ordered", command=self.reset).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def save(self):
        if not self.copies.get().strip().isdigit() or int(self.copies.get()) < 1:
            self.error.config(text="Copies: a whole number of 1 or more.")
            return
        item = self.order["items"][self.index]
        prepared = self.screen.ctx.preparer.get(self.order, item)
        base = walkin_print.settings_for(self.screen.ctx.rules, dict(item, print={}), prepared)
        new = {key: mapping[var.get()] if var.get() in mapping else var.get() for key, (var, mapping) in self.fields.items()}
        new["copies"] = str(int(self.copies.get()))
        item["print"] = {k: v for k, v in new.items() if base.get(k) != v}
        wo.save_order(self.order)
        self.screen.signature = None
        self.dlg.destroy()

    def reset(self):
        self.order["items"][self.index]["print"] = {}
        wo.save_order(self.order)
        self.screen.signature = None
        self.dlg.destroy()


# ------------------------------------------------------------------ Orders

STATUS_TEXT = {"waiting": "Waiting for PDF", "ready_to_print": "Ready to print", "printed": "Printed",
               "ready_for_pickup": "Ready for pickup", "collected": "Collected", "cancelled": "Cancelled"}


class OrdersScreen(OrderList):
    """Waiting for PDF, Ready to print (with printed ones), Ready for pickup; grouped by customer; search.
    2026-11-19_04 (Tesla: "just the order number and the customers details"): one line per order, the number, the
    customer, the status and the date placed, with Details… (or a double-click) for the items, their files, drop
    zones, Layout done and working lines (OrderDetailsScreen)."""

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Orders", on_back)
        ttk.Label(self.top, text="Search:").pack(side="left", padx=(40, 6))
        self.search = tk.StringVar()
        ttk.Entry(self.top, textvariable=self.search, width=28, font=FONT).pack(side="left")
        self.search.trace_add("write", lambda *_: setattr(self, "signature", None))
        ttk.Label(self.top, text="phone, name, email or order number", style="Small.TLabel").pack(side="left", padx=8)
        self.ready()
        self.poll()

    def extra_signature(self):
        return self.search.get()

    def fill(self, orders):
        text = self.search.get()
        shown = [o for o in orders if wo.matches(o, text)]
        lists = (("Waiting for PDF", [o for o in shown if o["status"] == "waiting"]),
                 ("Ready to print", [o for o in shown if o["status"] in ("ready_to_print", "printed")]),
                 ("Ready for pickup", [o for o in shown if o["status"] == "ready_for_pickup"]))
        self.status.config(text="   ·   ".join(f"{title}: {len(group)}" for title, group in lists))
        r = 0
        for title, group in lists:
            ttk.Label(self.scroll.inner, text=f"{title} ({len(group)})", style="Big.TLabel").grid(
                row=r, column=0, sticky="w", pady=(12, 4))
            r += 1
            if not group:
                ttk.Label(self.scroll.inner, text="None", style="Small.TLabel").grid(row=r, column=0, sticky="w")
                r += 1
            for name, orders_of in group_by_customer(group):
                ttk.Label(self.scroll.inner, text=name, style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(6, 2))
                r += 1
                for order in orders_of:
                    where = self.ctx.print_queue.order_state(order) if order["status"] == "ready_to_print" else None
                    box = self.line(self.scroll.inner, order, self.buttons(order), where)
                    box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                    r += 1
        if text.strip():
            history = [o for o in wo.list_history() if wo.matches(o, text)]
            ttk.Label(self.scroll.inner, text=f"Collected and cancelled ({len(history)})", style="Big.TLabel").grid(
                row=r, column=0, sticky="w", pady=(12, 4))
            r += 1
            for order in sorted(history, key=lambda o: o["created"], reverse=True):
                state = (f"Cancelled {when(order['times']['cancelled'])}" if order["status"] == "cancelled" else
                         f"Collected {when(order['times']['collected'])}")
                box = self.line(self.scroll.inner, order, [("Open folder", lambda o=order: self.open_folder(o), None)],
                                state, details=False)
                box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                r += 1

    def line(self, parent, order, buttons, state=None, details=True):
        """One order: the number large, the customer, the status and the date placed; its buttons. No items, files,
        drop zones, working lines or prices (those are in Details…)."""
        box = ttk.Frame(parent, padding=(12, 8), style="Card.TFrame")
        ttk.Style(box).configure("Card.TFrame", background=theme.SURFACE)
        box.columnconfigure(2, weight=1)
        number = ttk.Label(box, text=f"#{order['number']}", style="Number.TLabel")
        ttk.Style(box).configure("Number.TLabel", font=("Segoe UI", 24, "bold"))
        number.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        who = ttk.Label(box, text=customer_text(order["customer"]), style="Head.TLabel")
        who.grid(row=0, column=1, columnspan=2, sticky="w")
        status = state or STATUS_TEXT.get(order["status"], order["status"])
        info = ttk.Label(box, text=f"{status}   ·   placed {when(order['times'].get('placed') or order['created'])}",
                         style="Good.TLabel" if order["status"] in ("printed", "ready_for_pickup") else "Small.TLabel")
        info.grid(row=1, column=1, columnspan=2, sticky="w")
        row = ttk.Frame(box)
        row.grid(row=0, column=3, rowspan=2, sticky="e")
        if details:
            buttons = [("Details…", lambda: self.details(order), None)] + list(buttons)
        for text, command, style in buttons:
            ttk.Button(row, text=text, command=command, style=style or "TButton").pack(side="left", padx=(8, 0))
        if details:
            for w in (box, number, who, info):
                w.bind("<Double-Button-1>", lambda _e: self.details(order))
        theme.on_surface(box)
        return box

    def details(self, order):
        """The order's items, files, drop zones, Layout done and working lines (as the list showed them before)."""
        self.win.withdraw()
        OrderDetailsScreen(self.ctx, order["number"], on_back=self.details_closed)

    def details_closed(self):
        self.signature = None  # the list updates
        self.show()

    def buttons(self, order):
        out = [("Open folder", lambda: self.open_folder(order), None)]
        if order["status"] == "printed":
            out.insert(0, ("Ready for pickup", lambda: self.ready_for_pickup(order), "Print.TButton"))
        out += [("Collected", lambda: self.collected(order), None),
                ("Cancel order", lambda: self.cancel(order), None)]
        return out

    def collected(self, order):
        if not messagebox.askyesno(parent=self.win, title="ORCA",
                                   message=f"Order #{order['number']}, {euro(wo.price_due(order))}: "
                                           f"the customer has picked it up and paid?" + self.gone_text(order)):
            return
        self.finish(order, False)

    def cancel(self, order):
        kept = ("" if order.get("keep_data") is False else
                " Its folder is kept in the customer's folder, marked cancelled.")
        if not messagebox.askyesno(parent=self.win, title="ORCA",
                                   message=f"Cancel order #{order['number']}?{kept} The number is free again."
                                           + self.gone_text(order)):
            return
        self.finish(order, True)

    @staticmethod
    def gone_text(order):
        """A customer who said Don't keep: their order's folder is deleted for good."""
        return ("\n\nThis customer didn't want their details kept: the order's folder is deleted for good "
                "(only a line with no name stays in the sales list).") if order.get("keep_data") is False else ""

    def finish(self, order, cancelled):
        if not cancelled:  # Inventory (2026-11-19_03): lamination, spiral, envelopes, label sheets at Collected
            try:
                import inventory
                inventory.take_collected(order, rules=self.ctx.rules)
            except Exception:
                pass  # stock never stops anything
        try:
            wo.finish(order, cancelled)
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA",
                                   message=f"Could not move or delete the order folder (is a file in it open?).\n\n{e}")
        self.signature = None


class OrderDetailsScreen(OrderList):
    """Details… of one open order (2026-11-19_04): its items as the Orders list showed them before, with their
    files, drop zones, Layout done and working lines. Back (or the X) goes back to the list, which updates."""

    def __init__(self, ctx, number, on_back):
        super().__init__(ctx, f"Order #{number}", on_back)
        self.number = number
        self.ready()
        self.poll()

    def got_orders(self, orders):
        pass  # the list's own poll keeps the print queue up to date

    def fill(self, orders):
        order = next((o for o in orders if o["number"] == self.number), None)
        if order is None:
            ttk.Label(self.scroll.inner, text=f"#{self.number} is no longer open (collected or cancelled).",
                      style="Warn.TLabel").grid(row=0, column=0, sticky="w")
            return
        status = STATUS_TEXT.get(order["status"], order["status"])
        self.status.config(text=f"{customer_text(order['customer'])}   ·   {status}")
        box = self.card(self.scroll.inner, order, self.buttons(order))
        box.grid(row=0, column=0, sticky="we")

    def buttons(self, order):
        out = [("Open folder", lambda: self.open_folder(order), None)]
        for i, item in enumerate(order["items"]):
            if (item["kind"] == "product" and wo.sheet_state(order, item)[0] in ("ok", "bad")
                    and not wo.laid_out(order, item)):
                out.insert(0, (f"Layout done (item {i + 1})…", lambda k=i: SheetsDialog(self, order, k), "Print.TButton"))
        return out


class SheetsDialog:
    """Layout done for a product item: the sheet count for W100-2.pdf, suggested from pieces per sheet, as
    PrintHub's Layout done. Only the exported print sheet is checked (A4 or A3)."""

    def __init__(self, screen, order, index):
        self.screen, self.order, self.index = screen, order, index
        item = order["items"][index]
        path = wo.item_file(order, item)
        paper, info = wo.pdf_sheet(path) if path else (None, "no PDF")
        p = walkin_pricing.product_of(item)
        cut = cat.CUT_MM.get(cat.size_of(p, item["picks"]))
        per = wo.pieces_for(screen.ctx.rules, cut, paper) if paper else None
        suggest = math.ceil(item["qty"] / per) if per else ""
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(f"ORCA - #{order['number']} item {index + 1}: Layout done")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=18)
        f.grid()
        ttk.Label(f, text=item["description"], style="Head.TLabel", wraplength=460).grid(row=0, column=0, columnspan=2,
                                                                                     sticky="w")
        if paper is None:
            ttk.Label(f, text=f"{path.name if path else 'PDF'}: {info}", foreground=theme.ERROR).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=6)
        else:
            hint = (f"{per} pieces per {paper} sheet (size table): {item['qty']} ÷ {per} = {suggest} sheets"
                    if per else f"No size-table number for this size on {paper}: type the sheets.")
            ttk.Label(f, text=f"{path.name}: {info} page(s), {paper}.\n{hint}", justify="left").grid(
                row=1, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Label(f, text="Sheets (copies of the PDF):").grid(row=2, column=0, sticky="w")
        self.var = tk.StringVar(value=str(suggest))
        ttk.Entry(f, textvariable=self.var, width=8, font=FONT).grid(row=2, column=1, sticky="w", padx=6)
        self.error = ttk.Label(f, text="", foreground=theme.ERROR)
        self.error.grid(row=3, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.ok = ttk.Button(b, text="Confirm", style="Print.TButton", command=self.save,
                             state="normal" if paper else "disabled")
        self.ok.pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def save(self):
        t = self.var.get().strip()
        if not t.isdigit() or not 1 <= int(t) <= 9999:
            self.error.config(text="A whole number from 1 to 9999.")
            return
        wo.layout_done(self.order, self.order["items"][self.index], int(t))
        self.screen.signature = None
        self.dlg.destroy()
