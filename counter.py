"""The Counter screen: what ORCA sent to the copiers in a date range (Tesla, 2026-11-15).

Reads print_log.csv (jobs.Jobs.log), old lines too, and shows Total, Walk-in and PrintHub: printed
sides and sheets by sheet size and colour, by paper, and (PrintHub) by product, with the cost from
the Prices screen (costs.py). Read-only: a broken line is skipped.
"""
import csv
import datetime
import json

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import costs
import jobs
import routing
import theme

SIZES = ("A3", "A4")
SETTINGS_FILE = "counter_export.json"  # the two Export PDF tick boxes (local, not on GitHub)


def load_settings():
    out = {"include_costs": True, "include_jobs": True}
    try:
        saved = json.loads((routing.app_dir() / SETTINGS_FILE).read_text(encoding="utf-8"))
        out.update({k: bool(saved[k]) for k in out if k in saved})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return out


def documents_dir():
    """The user's Documents folder (also when Windows moved it, e.g. to OneDrive)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and os.path.isdir(buf.value):
            return buf.value  # CSIDL_PERSONAL
    except Exception:
        pass
    return os.path.expanduser("~")


# ------------------------------------------------------------------ reading the log

def _int(text):
    text = str(text or "").strip()
    return int(text) if text.isdigit() else None


def parse_row(row):
    """One print_log.csv line as a dict, or None for the header or a broken line."""
    if len(row) < 14 or row[0] == "time":
        return None
    when = datetime.datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M:%S")
    file_name = row[1]
    pages, copies, sheets = int(row[2]), int(row[3]), int(row[12])
    color = row[4].strip()
    extra = (row[14:] + [""] * 8)[:8]
    source, order, product, quantity, size, color_sides, bw_sides, paper_name = (x.strip() for x in extra)
    if source:  # a line written since 2026-11-15
        cs, bs = _int(color_sides), _int(bw_sides)
        if cs is None or bs is None:
            raise ValueError("sides")
    else:
        # Older line: PrintHub when the file name starts with an order number; sides = pages x copies.
        first = file_name.split(" ", 1)[0]
        source = "printhub" if first.upper().startswith("PH-") else "walk-in"
        order = first if source == "printhub" else ""
        size = jobs.sheet_size(row[6].strip())
        total = pages * copies
        cs, bs = (0, total) if color == "bw" else (total, 0)  # "mixed" counts as colour
    if source not in ("printhub", "walk-in"):
        raise ValueError("source")
    return {"time": when, "file": file_name, "source": source, "order": order, "product": product,
            "quantity": _int(quantity), "size": size or jobs.sheet_size(row[6].strip()),
            "color": cs, "bw": bs, "sheets": sheets, "paper": paper_name or row[7].strip()}


def read_log(path=None):
    """Every readable line of print_log.csv, oldest first; broken lines are skipped."""
    path = path or routing.app_dir() / jobs.LOG_FILE
    entries = []
    try:
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            for row in csv.reader(f):
                try:
                    entry = parse_row(row)
                except (ValueError, IndexError, TypeError):
                    continue
                if entry:
                    entries.append(entry)
    except (OSError, csv.Error):
        pass
    return entries


# ------------------------------------------------------------------ adding up

def summarize(entries, cost_table):
    """Totals for one section: {"sizes": {size: {...}}, "papers": [...], "products": [...], "cost", "missing"}."""
    sizes, papers, products, orders = {}, {}, {}, set()
    total_cost, missing = 0.0, False
    for e in entries:
        size = e["size"] if e["size"] in SIZES else "Other"
        cost, miss = cost_table.job_cost(e["size"], e["color"], e["bw"], e["sheets"], e["paper"])
        total_cost += cost
        missing = missing or miss
        s = sizes.setdefault(size, {"color": 0, "bw": 0, "color_sheets": 0, "bw_sheets": 0, "cost": 0.0})
        s["color"] += e["color"]
        s["bw"] += e["bw"]
        # A sheet with any colour on it counts under Colour.
        s["color_sheets" if e["color"] else "bw_sheets"] += e["sheets"]
        s["cost"] += cost
        p = papers.setdefault((e["paper"], size), {"paper": e["paper"], "size": size, "sheets": 0, "color": 0,
                                                   "bw": 0, "cost": 0.0})
        p["sheets"] += e["sheets"]
        p["color"] += e["color"]
        p["bw"] += e["bw"]
        p["cost"] += cost
        if e["source"] == "printhub":
            if e["order"]:
                orders.add(e["order"])
            name = e["product"] or "Unknown (older log line)"
            pr = products.setdefault(name, {"product": name, "orders": set(), "pieces": 0, "sheets": 0, "cost": 0.0})
            if e["order"]:
                pr["orders"].add(e["order"])
            pr["pieces"] += e["quantity"] or 0
            pr["sheets"] += e["sheets"]
            pr["cost"] += cost
    return {"sizes": sizes, "papers": sorted(papers.values(), key=lambda p: (-p["sheets"], p["paper"])),
            "products": sorted(products.values(), key=lambda p: (-p["sheets"], p["product"])),
            "orders": len(orders), "cost": total_cost, "missing": missing, "count": len(entries)}


def sections(entries, start, end, cost_table):
    """Total, Walk-in and PrintHub for the days start..end (dates, both included)."""
    chosen = [e for e in entries if start <= e["time"].date() <= end]
    return [("Total", summarize(chosen, cost_table)),
            ("Walk-in", summarize([e for e in chosen if e["source"] == "walk-in"], cost_table)),
            ("PrintHub", summarize([e for e in chosen if e["source"] == "printhub"], cost_table))]


# ------------------------------------------------------------------ dates

def period(name, today):
    """(first day, last day) for Today, Yesterday, This week (Monday to Sunday), This month, This year."""
    if name == "Today":
        return today, today
    if name == "Yesterday":
        d = today - datetime.timedelta(days=1)
        return d, d
    if name == "This week":
        monday = today - datetime.timedelta(days=today.weekday())
        return monday, monday + datetime.timedelta(days=6)
    if name == "This month":
        first = today.replace(day=1)
        nxt = (first + datetime.timedelta(days=32)).replace(day=1)
        return first, nxt - datetime.timedelta(days=1)
    if name == "This year":
        return today.replace(month=1, day=1), today.replace(month=12, day=31)
    raise ValueError(name)


def parse_date(text):
    """'15/11/2026', '15.11.2026', '15-11-2026' or '2026-11-15' -> date. Raises ValueError."""
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def range_text(start, end):
    """'9 Nov - 15 Nov 2026', '15 Nov 2026', '28 Dec 2026 - 3 Jan 2027'."""
    def day(d):
        return f"{d.day} {d:%b}"
    if start == end:
        return f"{day(start)} {start.year}"
    if start.year == end.year:
        return f"{day(start)} - {day(end)} {end.year}"
    return f"{day(start)} {start.year} - {day(end)} {end.year}"


def number(n):
    return f"{n:,}".replace(",", " ")  # 12 345


def sheets_text(n):
    return f"{number(n)} sheet" + ("" if n == 1 else "s")


# ------------------------------------------------------------------ the screen

class CounterScreen:
    def __init__(self, root, rules, on_back, today=None):
        self.rules, self.on_back = rules, on_back
        self.today = today  # tests pass a fixed day
        self.win = win = tk.Toplevel(root)
        win.title("ORCA - Counter")
        win.geometry("1000x900")
        win.minsize(820, 600)
        win.protocol("WM_DELETE_WINDOW", self.back)
        style = ttk.Style(win)
        style.configure("Big.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=theme.MUTED)
        style.configure("Surface.Big.TLabel", font=("Segoe UI", 15, "bold"), background=theme.SURFACE)
        style.configure("Surface.Small.TLabel", font=("Segoe UI", 9), foreground=theme.MUTED,
                        background=theme.SURFACE)
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Selected.TButton", background=theme.SELECT, foreground=theme.WHITE)

        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(4, weight=1)

        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="← Back", command=self.back).pack(side="left", padx=(0, 24))
        ttk.Label(top, text="Counter", style="Summary.TLabel").pack(side="left")
        ttk.Button(top, text="Open in Excel", command=self.open_log).pack(side="right")
        ttk.Button(top, text="Export PDF", command=self.export_pdf).pack(side="right", padx=(0, 8))
        saved = load_settings()
        self.with_jobs = tk.BooleanVar(value=saved["include_jobs"])
        self.with_costs = tk.BooleanVar(value=saved["include_costs"])
        for text, var in (("Include the list of jobs", self.with_jobs), ("Include costs", self.with_costs)):
            ttk.Checkbutton(top, text=text, variable=var, command=self.save_settings).pack(side="right", padx=(0, 14))

        bar = ttk.Frame(f)
        bar.grid(row=1, column=0, sticky="we", pady=(12, 0))
        self.period_buttons = {}
        for name in ("Today", "Yesterday", "This week", "This month", "This year"):
            b = ttk.Button(bar, text=name, command=lambda n=name: self.choose(n))
            b.pack(side="left", padx=(0, 6))
            self.period_buttons[name] = b
        ttk.Label(bar, text="From").pack(side="left", padx=(18, 4))
        self.from_var = tk.StringVar()
        ttk.Entry(bar, font=costs.FONT, textvariable=self.from_var, width=11).pack(side="left")
        ttk.Label(bar, text="to").pack(side="left", padx=4)
        self.to_var = tk.StringVar()
        e = ttk.Entry(bar, font=costs.FONT, textvariable=self.to_var, width=11)
        e.pack(side="left")
        e.bind("<Return>", lambda _: self.custom())
        self.custom_btn = ttk.Button(bar, text="Show", command=self.custom)
        self.custom_btn.pack(side="left", padx=(6, 0))

        self.range_label = ttk.Label(f, text="", style="Big.TLabel")
        self.range_label.grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Label(f, text="Counts what was sent from ORCA. Photocopies made at the copier are not included.",
                  style="Hint.TLabel").grid(row=3, column=0, sticky="w", pady=(2, 8))
        self.scroll = costs.ScrollFrame(f)
        self.scroll.grid(row=4, column=0, sticky="nsew")
        self.choose("This week")
        theme.dark_title_bar(win)

    def day(self):
        return self.today or datetime.date.today()

    def choose(self, name):
        start, end = period(name, self.day())
        self.from_var.set(f"{start:%d/%m/%Y}")
        self.to_var.set(f"{end:%d/%m/%Y}")
        self.show(start, end, name)

    def custom(self):
        try:
            start, end = parse_date(self.from_var.get()), parse_date(self.to_var.get())
        except ValueError:
            messagebox.showwarning(parent=self.win, title="Counter",
                                   message="Type the dates as day/month/year, e.g. 1/11/2026.")
            return
        if start > end:
            start, end = end, start
        self.show(start, end, None)

    def show(self, start, end, chosen):
        self.start, self.end, self.chosen = start, end, chosen
        for name, b in self.period_buttons.items():
            b.config(style="Selected.TButton" if name == chosen else "TButton")
        self.range_label.config(text=range_text(start, end))
        self.cost_table = cost_table = costs.Costs(costs.load(self.rules))
        entries = read_log()
        self.entries = [e for e in entries if start <= e["time"].date() <= end]
        self.result = sections(entries, start, end, cost_table)
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        inner.columnconfigure(0, weight=1)
        for row, (title, s) in enumerate(self.result):
            self.section(inner, row, title, s)
        self.scroll.canvas.yview_moveto(0)

    def section(self, parent, row, title, s):
        box = ttk.LabelFrame(parent, text=title, padding=12, style="Section.TLabelframe")
        box.grid(row=row, column=0, sticky="we", pady=(0, 12))
        if not s["count"]:
            ttk.Label(box, text="Nothing printed in this period", style="Hint.TLabel").grid(sticky="w")
            theme.on_surface(box)
            return
        head = ttk.Frame(box)
        head.grid(row=0, column=0, sticky="w")
        ttk.Label(head, text=f"Cost: {costs.euro(s['cost'])}", style="Big.TLabel").pack(side="left")
        if title == "PrintHub":
            ttk.Label(head, text=f"Orders printed: {s['orders']}", style="Big.TLabel").pack(side="left", padx=(30, 0))
        if s["missing"]:
            ttk.Label(box, text="Some costs are not set (see Prices)", foreground=theme.ERROR).grid(
                row=1, column=0, sticky="w")

        grid = ttk.Frame(box)
        grid.grid(row=2, column=0, sticky="w", pady=(10, 0))
        for c, text in enumerate(("", "Colour", "Black and white", "Cost")):
            ttk.Label(grid, text=text, style="Head.TLabel").grid(row=0, column=c, sticky="w", padx=(0, 40))
        sizes = [x for x in SIZES + ("Other",) if x in s["sizes"] or x in SIZES]
        for r, size in enumerate(sizes, start=1):
            cell = s["sizes"].get(size, {"color": 0, "bw": 0, "color_sheets": 0, "bw_sheets": 0, "cost": 0.0})
            ttk.Label(grid, text=size, style="Head.TLabel").grid(row=r, column=0, sticky="nw", padx=(0, 40), pady=4)
            for c, mode in ((1, "color"), (2, "bw")):
                f = ttk.Frame(grid)
                f.grid(row=r, column=c, sticky="nw", padx=(0, 40), pady=4)
                ttk.Label(f, text=number(cell[mode]), style="Big.TLabel").pack(anchor="w")
                ttk.Label(f, text=sheets_text(cell[mode + "_sheets"]), style="Small.TLabel").pack(anchor="w")
            ttk.Label(grid, text=costs.euro(cell["cost"])).grid(row=r, column=3, sticky="nw", pady=6)

        self.table(box, 3, "By paper", ("Paper", "Sheet size", "Sheets", "Colour sides", "B&W sides", "Cost"),
                   [(p["paper"], p["size"], number(p["sheets"]), number(p["color"]), number(p["bw"]),
                     costs.euro(p["cost"])) for p in s["papers"]])
        if title == "PrintHub":
            self.table(box, 4, "By product", ("Product", "Orders", "Pieces ordered", "Sheets", "Cost"),
                       [(p["product"], number(len(p["orders"])), number(p["pieces"]), number(p["sheets"]),
                         costs.euro(p["cost"])) for p in s["products"]])
        theme.on_surface(box)

    def table(self, box, row, title, headings, rows):
        ttk.Label(box, text=title, style="Head.TLabel").grid(row=row * 2, column=0, sticky="w", pady=(14, 2))
        t = ttk.Frame(box)
        t.grid(row=row * 2 + 1, column=0, sticky="w")
        for c, text in enumerate(headings):
            ttk.Label(t, text=text, style="Hint.TLabel").grid(row=0, column=c, sticky="w", padx=(0, 28))
        for r, values in enumerate(rows, start=1):
            for c, text in enumerate(values):
                ttk.Label(t, text=text).grid(row=r, column=c, sticky="w", padx=(0, 28), pady=1)

    def save_settings(self):
        try:
            path = routing.app_dir() / SETTINGS_FILE
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(json.dumps({"include_costs": self.with_costs.get(),
                                       "include_jobs": self.with_jobs.get()}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass  # only a convenience

    def export_pdf(self):
        """The period now showing as a PDF: Save as (Documents), write it, open it."""
        import counter_pdf  # pypdfium2's drawing is only needed here
        path = filedialog.asksaveasfilename(
            parent=self.win, title="Export the Counter to PDF", initialdir=documents_dir(),
            initialfile=counter_pdf.file_name(self.start, self.end), defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            with jobs.PDF_LOCK:
                counter_pdf.export(path, self.result, self.entries, self.start, self.end, self.cost_table,
                                   self.with_costs.get(), self.with_jobs.get())
        except OSError:
            messagebox.showwarning(parent=self.win, title="Counter",
                                   message=f"Could not save {os.path.basename(path)}.\n\n"
                                           f"Close the PDF and try again.")
            return
        except Exception as e:
            messagebox.showwarning(parent=self.win, title="Counter", message=f"Could not make the PDF.\n\n{e}")
            return
        try:
            os.startfile(path)
        except OSError:
            pass

    def open_log(self):
        path = routing.app_dir() / jobs.LOG_FILE
        if not path.exists():
            messagebox.showinfo(parent=self.win, title="Counter", message="Nothing has been printed yet: "
                                                                          f"there is no {jobs.LOG_FILE}.")
            return
        try:
            os.startfile(path)
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="Counter", message=f"Could not open {path.name}.\n\n{e}")

    def back(self):
        self.win.destroy()
        self.on_back()
