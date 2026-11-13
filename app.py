"""PrintRouter: pick files, choose the options and the printer, and print.

Every file is first turned into a PDF, then sent to the printer picked in the
options, or with Auto to the one the rules in rules.json choose. Receipts with the price print afterwards, either one for the whole
batch or one per file.

The options panel edits the files selected in the list. Newly added files are
all selected, so by default the options apply to every file; click one file
to change just that one.
"""
import datetime
import itertools
import json
import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import analyze
import cleanup
import convert
import jobs
import layout
import printhub
import printing
import receipt
import routing
import sync
import theme

WORK_DIR = Path(tempfile.gettempdir()) / "PrintRouter"
FILE_TYPES = [
    ("Printable files", "*.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.png *.jpg *.jpeg"),
    ("All files", "*.*"),
]
PAPERS = [("A4", "A4"), ("A3", "A3"), ("A5", "A5 (2 on A4)")]
FONT = ("Segoe UI", 12)
# Option names; each file in the list keeps its own copy of these.
OPTIONS = ("color", "printer", "sides", "paper", "per_side", "paper_type", "tray", "copies", "rotate")


def _count(n, singular, plural=None):
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


class Item:
    """One file in the list."""

    def __init__(self, item_id, src, settings, name=None, from_inbox=False):
        self.id = item_id
        self.src = src
        self.name = name or src.name  # shown in the list, e.g. 'Client A\flyer.pdf' from the inbox
        self.from_inbox = from_inbox
        self.settings = dict(settings)
        self.status = "loading"  # loading / ready / error
        self.error = None
        self.pdf = self.pdf_paper = self.pages = self.coverage = None
        self.page_colors = None  # True/False per page: has color


class App:
    def __init__(self, root):
        self.root = root
        self.rules = routing.load_json("rules.json")
        self.prices = routing.load_json("prices.json")
        self.printers = self.rules["printers"]
        self.jobs = jobs.Jobs(self.rules, self.prices)  # routing, checks and sending, shared with PrintHub
        self.sending_to = set()  # copiers of the batch being sent now: busy for PrintHub's colour choice
        self.jobs.busy_sources.append(lambda: set(self.sending_to))
        self.printhub = None  # the PrintHub window, once opened
        # Website orders into Pending Orders, while the app is open (only with printhub_token.txt: the work PC).
        self.sync = sync.WebsiteSync(self.rules)
        self.sync.start()
        # Finished Orders: each order goes to the Recycle Bin 8 days after Ready for courier.
        cleanup.start(self.rules)

        self.items = {}  # id -> Item, in the order they were added
        self.next_id = 1
        self.busy = False  # printing
        self.filling_panel = False  # True while the panel is being filled from a file
        self.results = queue.Queue()  # messages from worker threads to the window
        self.to_load = queue.Queue()  # files waiting to be converted, one at a time

        self.inbox = routing.app_dir() / self.rules.get("inbox_folder", "Inbox")
        self.printed_dir = routing.app_dir() / self.rules.get("printed_folder", "Printed")
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.inbox_known = set()  # inbox files already in the list, printed, or removed by hand
        self.inbox_sizes = {}  # new inbox files: size at the last look, to wait until copying ends

        # Print runs added to the counter, waiting for one shared receipt. Kept in a file so a
        # restart doesn't lose them: [{"time": ..., "entries": [{"job": ..., "printer": label}]}]
        self.counter_path = routing.app_dir() / "counter.json"
        self.counter = self._load_counter()
        self.counter_printing = False

        shutil.rmtree(WORK_DIR, ignore_errors=True)
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        threading.Thread(target=self._load_worker, daemon=True).start()
        threading.Thread(target=self.jobs.warm_up_checks, daemon=True).start()

        self._build()
        self.template = self.default_settings()
        self.fill_panel(self.template)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        root.after(500, self.scan_inbox)

    # ------------------------------------------------------------------ UI

    def _build(self):
        root = self.root
        root.title("PrintRouter")
        style = ttk.Style()
        theme.apply(root)
        style.configure(".", font=FONT)
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"))
        style.configure("Print.TButton", font=("Segoe UI", 16, "bold"), padding=10)
        style.configure("Summary.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 12, "bold"))
        root.option_add("*TCombobox*Listbox.font", FONT)

        self.vars = {name: tk.StringVar() for name in OPTIONS}
        self.receipt_mode = tk.StringVar(value=self.rules["defaults"].get("receipt", "one_for_all"))

        f = ttk.Frame(root, padding=16)
        f.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        # File list
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we", pady=(0, 6))
        self.add_btn = ttk.Button(top, text="Add files…", command=self.add_files)
        self.add_btn.pack(side="left")
        self.remove_btn = ttk.Button(top, text="Remove selected", command=self.remove_selected)
        self.remove_btn.pack(side="left", padx=(8, 0))
        self.select_all_btn = ttk.Button(top, text="Select all", command=self.select_all)
        self.select_all_btn.pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Open inbox folder", command=lambda: os.startfile(self.inbox)).pack(
            side="left", padx=(8, 0))
        self.clear_btn = ttk.Button(top, text="Start over", command=self.clear)
        self.clear_btn.pack(side="right")
        ttk.Button(top, text="PrintHub", command=self.open_printhub).pack(side="right", padx=(0, 24))

        list_box = ttk.Frame(f)
        list_box.grid(row=1, column=0, sticky="nsew")
        list_box.columnconfigure(0, weight=1)
        list_box.rowconfigure(0, weight=1)
        columns = ("file", "pages", "settings", "printer", "price")
        self.tree = ttk.Treeview(list_box, columns=columns, show="headings", height=6, selectmode="extended")
        for col, text, width, stretch in (("file", "File", 220, True), ("pages", "Pages", 60, False),
                                          ("settings", "Settings", 420, True), ("printer", "Printer", 190, False),
                                          ("price", "Price", 80, False)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure("error", foreground=theme.ERROR)
        self.tree.tag_configure("loading", foreground=theme.MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.on_select())
        self.tree.bind("<Delete>", lambda _: self.remove_selected())
        self.empty_hint = ttk.Label(list_box, text="Click “Add files…”, or put files in the inbox folder.",
                                    style="Hint.TLabel")
        self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")

        # Options for the selected files
        self.panel = ttk.LabelFrame(f, text="Options", padding=10, style="Section.TLabelframe")
        self.panel.grid(row=2, column=0, sticky="we", pady=10)
        p = self.panel
        p.columnconfigure(1, weight=1)
        pad = {"padx": 6, "pady": 4}

        def row_label(r, text):
            ttk.Label(p, text=text).grid(row=r, column=0, sticky="w", **pad)

        def radios(r, var, options):
            box = ttk.Frame(p)
            box.grid(row=r, column=1, sticky="w", **pad)
            buttons = []
            for value, text in options:
                b = ttk.Radiobutton(box, text=text, value=value, variable=var)
                b.pack(side="left", padx=(0, 18))
                buttons.append(b)
            return box, buttons

        v = self.vars
        row_label(0, "Color")
        radios(0, v["color"], [("bw", "Black & white"), ("color", "Color"),
                               ("auto", "Auto (each page as it is)")])

        row_label(1, "Printer")
        radios(1, v["printer"], [("auto", "Auto")] + [(pid, p["label"]) for pid, p in self.printers.items()])

        row_label(2, "Sides")
        radios(2, v["sides"], [("single", "One-sided"), ("long", "Double, flip on long edge"),
                               ("short", "Double, flip on short edge")])

        row_label(3, "Paper")
        paper_box, _ = radios(3, v["paper"], PAPERS)
        ttk.Label(paper_box, text="Pages per side").pack(side="left", padx=(12, 8))
        ttk.Combobox(paper_box, textvariable=v["per_side"], values=[str(n) for n in layout.PER_SIDE],
                     state="readonly", width=4, font=FONT).pack(side="left")

        row_label(4, "Paper type")
        media_box = ttk.Frame(p)
        media_box.grid(row=4, column=1, sticky="w", **pad)
        ttk.Combobox(media_box, textvariable=v["paper_type"], values=self.rules["paper_types"],
                     state="readonly", width=28, font=FONT).pack(side="left")
        ttk.Label(media_box, text="Tray").pack(side="left", padx=(24, 8))
        ttk.Combobox(media_box, textvariable=v["tray"], values=self.rules["trays"],
                     state="readonly", width=18, font=FONT).pack(side="left")

        row_label(5, "Copies")
        copies_box = ttk.Frame(p)
        copies_box.grid(row=5, column=1, sticky="w", **pad)
        ttk.Spinbox(copies_box, from_=1, to=999, textvariable=v["copies"], width=6, font=FONT).pack(side="left")
        rs = self.rules["rotate_sort"]
        ttk.Checkbutton(copies_box, variable=v["rotate"], onvalue="1", offvalue="0",
                        text=f"Rotate sort (A4, {' / '.join(rs['trays'])}, "
                             f"{self.printers[rs['printer']]['label']})").pack(side="left", padx=(24, 0))

        # Totals, receipt choice and print button
        theme.on_surface(self.panel)

        self.summary = ttk.Label(f, text="", style="Summary.TLabel")
        self.summary.grid(row=3, column=0, sticky="w", padx=6)
        receipt_box = ttk.Frame(f)
        receipt_box.grid(row=4, column=0, sticky="w", padx=6, pady=(4, 8))
        ttk.Label(receipt_box, text="Receipt:").pack(side="left", padx=(0, 12))
        for value, text in (("one_for_all", "One for all files"), ("one_per_file", "One per file"),
                            ("counter", "Add to counter"), ("none", "No receipt")):
            ttk.Radiobutton(receipt_box, text=text, value=value, variable=self.receipt_mode).pack(
                side="left", padx=(0, 18))

        counter_box = ttk.Frame(f)
        counter_box.grid(row=5, column=0, sticky="w", padx=6, pady=(0, 8))
        self.counter_label = ttk.Label(counter_box, text="")
        self.counter_label.pack(side="left", padx=(0, 18))
        self.counter_print_btn = ttk.Button(counter_box, text="Print counter receipt", command=self.print_counter)
        self.counter_print_btn.pack(side="left")
        self.counter_clear_btn = ttk.Button(counter_box, text="Clear counter", command=self.clear_counter)
        self.counter_clear_btn.pack(side="left", padx=(8, 0))
        self.refresh_counter()

        self.print_btn = ttk.Button(f, text="PRINT ALL", style="Print.TButton", command=self.on_print)
        self.print_btn.grid(row=6, column=0, sticky="we")
        self.status = ttk.Label(f, text="", style="Hint.TLabel", wraplength=820)
        self.status.grid(row=7, column=0, sticky="w", padx=6, pady=(10, 0))

        for name, var in self.vars.items():
            var.trace_add("write", lambda *_, n=name: self.on_option_changed(n))

        root.minsize(1000, 760)

    def default_settings(self):
        d = self.rules["defaults"]
        return {
            "color": "color" if d["color"] else "bw",
            "printer": "auto",
            "sides": "long" if d["duplex"] else "single",
            "paper": d["paper"],
            "per_side": "1",
            "paper_type": d["paper_type"],
            "tray": d["tray"],
            "copies": str(d["copies"]),
            "rotate": "1" if d.get("rotate_sort") else "0",
        }

    def fill_panel(self, settings):
        """Show a file's settings in the panel without changing any file."""
        self.filling_panel = True
        try:
            for name in OPTIONS:
                self.vars[name].set(settings[name])
        finally:
            self.filling_panel = False
        self.refresh()

    def selected_items(self):
        return [self.items[int(i)] for i in self.tree.selection() if int(i) in self.items]

    def on_select(self):
        selected = self.selected_items()
        if selected:
            self.fill_panel(selected[0].settings)
        else:
            self.refresh()

    def on_option_changed(self, name):
        if self.filling_panel:
            return
        value = self.vars[name].get()
        targets = self.selected_items()
        self.template[name] = value  # files added later start with the latest choices
        for item in targets:
            item.settings[name] = value
        self.refresh()

    def open_printhub(self):
        if self.printhub and self.printhub.is_open():
            self.printhub.show()
        else:
            self.printhub = printhub.PrintHubView(self.root, self.rules, self.jobs, self.sync)

    # ------------------------------------------------------------- the jobs

    def job_for(self, item):
        """The print job for one file, or None if it can't print yet."""
        if item.status != "ready":
            return None
        return self.jobs.job_for(item.name, item.settings, item.pages, item.coverage, item.page_colors)

    def refresh(self):
        """Update the list, the panel and the totals from the current settings."""
        jobs = {}
        for item in self.items.values():
            if item.status == "loading":
                values = (item.name, "", "", "Preparing…", "")
                tag = "loading"
            elif item.status == "error":
                values = (item.name, "", item.error, "Can't print", "")
                tag = "error"
            else:
                job = self.job_for(item)
                jobs[item.id] = job
                tag = ""
                if job:
                    label = self.printers[job["printer"]]["label"]
                    if item.settings["printer"] == "auto":
                        label += " (auto)"
                    price =receipt.fmt(self.prices, receipt.total_price(self.prices, job))
                    if job["problem"]:
                        label, price, tag = f"{label}: {job['problem']}", "", "error"
                elif item.settings["printer"] not in self.printers and item.settings["printer"] != "auto":
                    label, price = "Pick a printer", ""
                else:
                    label, price = "Check copies", ""
                values = (item.name, item.pages, self.jobs.settings_text(item.settings, job), label, price)
            self.tree.item(str(item.id), values=values, tags=(tag,))
        if self.items:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")

        # Panel title
        selected = self.selected_items()
        if not self.items:
            self.panel.config(text="Options")
        elif len(selected) == len(self.items):
            self.panel.config(text="Options for all files")
        elif selected:
            self.panel.config(text=f"Options for {_count(len(selected), 'selected file')}")
        else:
            self.panel.config(text="Options (select files in the list to change them)")

        # Totals
        loading = sum(1 for i in self.items.values() if i.status == "loading")
        errors = sum(1 for i in self.items.values() if i.status == "error")
        unready = sum(1 for i in self.items.values()
                      if i.status == "ready" and (jobs.get(i.id) is None or jobs[i.id]["problem"]))
        ready = [j for j in jobs.values() if j and not j["problem"]]
        if not self.items:
            text = "Add files to start."
        elif loading:
            text = f"Preparing {_count(loading, 'file')}…"
        elif errors:
            text = f"Remove the {_count(errors, 'file')} that can't be printed (in red)."
        elif any(i.status == "ready" and i.settings["printer"] not in self.printers
                 and i.settings["printer"] != "auto" for i in self.items.values()):
            text = "Pick a printer for every file."
        elif unready:
            text = "Fix the files without a price (copies, or paper type/tray the printer doesn't have)."
        else:
            total = sum(receipt.total_price(self.prices, j) for j in ready)
            printers = len({j["printer"] for j in ready})
            text = (f"{_count(len(ready), 'file')} · {_count(sum(j['sheets'] for j in ready), 'sheet')} · "
                    f"{_count(printers, 'printer')} · Total: {receipt.fmt(self.prices, total)}")
        self.summary.config(text=text)
        can_print = bool(ready) and not (loading or errors or unready or self.busy)
        self.print_btn.config(state="normal" if can_print else "disabled")

    # -------------------------------------------------------- adding files

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Choose files to print", filetypes=FILE_TYPES)
        if not paths:
            return
        bad = [Path(p).name for p in paths if Path(p).suffix.lower() not in convert.SUPPORTED_EXT]
        if bad:
            messagebox.showwarning("PrintRouter", "These files can't be printed and were skipped:\n\n"
                                   + "\n".join(bad) + "\n\nSupported: PDF, Word, Excel, PowerPoint, PNG, JPG.")
        for p in paths:
            if Path(p).suffix.lower() in convert.SUPPORTED_EXT:
                self._add_item(Path(p))
        self.status.config(text="")
        self.select_all()

    def _add_item(self, path, name=None, from_inbox=False):
        # New files start with the options currently shown in the panel.
        settings = {n: self.vars[n].get() for n in OPTIONS}
        item = Item(self.next_id, path, settings, name, from_inbox)
        self.next_id += 1
        self.items[item.id] = item
        self.tree.insert("", "end", iid=str(item.id))
        self.to_load.put((item.id, path, settings["paper"]))

    def scan_inbox(self):
        """Add new files from the inbox folder (and folders inside it), in folder and name order."""
        try:
            found = []
            for folder, dirs, files in os.walk(self.inbox):
                dirs.sort()
                for f in sorted(files):
                    path = Path(folder) / f
                    if (path.suffix.lower() in convert.SUPPORTED_EXT and not f.startswith(("~$", "."))
                            and path not in self.inbox_known):
                        found.append(path)
            new = []
            for path in found:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                # Only take a file once its size stopped changing (it may still be copying).
                if size and self.inbox_sizes.get(path) == size:
                    new.append(path)
                else:
                    self.inbox_sizes[path] = size
            if new and not self.busy:
                everything_selected = len(self.tree.selection()) == len(self.items)
                for path in new:
                    self.inbox_known.add(path)
                    self.inbox_sizes.pop(path, None)
                    self._add_item(path, str(path.relative_to(self.inbox)), from_inbox=True)
                if everything_selected:
                    self.select_all()
                else:
                    self.refresh()
        except OSError:
            pass  # the folder may be briefly unavailable; try again next time
        self.root.after(2000, self.scan_inbox)

    def _move_printed(self, item):
        """Move a printed inbox file to the printed folder (today's date), keeping its subfolders."""
        try:
            dest = self.printed_dir / datetime.date.today().isoformat() / item.src.relative_to(self.inbox)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(f"{dest.stem} ({datetime.datetime.now():%H%M%S}){dest.suffix}")
            shutil.move(str(item.src), str(dest))
            self.inbox_known.discard(item.src)
            folder = item.src.parent
            while folder != self.inbox and not any(folder.iterdir()):  # tidy emptied folders
                folder.rmdir()
                folder = folder.parent
        except OSError:
            pass  # still open somewhere; it stays in the inbox but won't be added again this session

    def select_all(self):
        self.tree.selection_set([str(i) for i in self.items])
        self.refresh()

    def remove_selected(self):
        if self.busy:
            return
        for item in self.selected_items():
            del self.items[item.id]
            self.tree.delete(str(item.id))
        self.refresh()

    def clear(self):
        if self.busy:
            return
        self.items.clear()
        self.tree.delete(*self.tree.get_children())
        self.template = self.default_settings()
        self.fill_panel(self.template)
        self.status.config(text="")

    def _load_worker(self):
        """Convert files one at a time (Office can only do one safely)."""
        while True:
            item_id, path, paper = self.to_load.get()
            try:
                item_dir = WORK_DIR / str(item_id)
                item_dir.mkdir(parents=True, exist_ok=True)
                pdf = item_dir / f"document_{paper}.pdf"
                with jobs.PDF_LOCK:
                    convert.to_pdf(path, pdf, paper)
                    pages = analyze.page_count(pdf)
                    coverage = analyze.color_coverage(pdf)  # for Auto printer choice
                    page_colors = analyze.color_pages(pdf)  # for Auto color
                self.results.put(("loaded", item_id, pdf, paper, pages, coverage, page_colors))
            except Exception as e:
                self.results.put(("load_failed", item_id, str(e)))

    # ------------------------------------------------------------- printing

    def on_print(self):
        if self.busy:
            return
        batch = []
        for item in self.items.values():
            job = self.job_for(item)
            if job is None or job["problem"]:
                return
            batch.append((item.id, job, item.src, item.pdf, item.pdf_paper))
        sheets = sum(job["sheets"] for _, job, *_ in batch)
        limit = self.rules.get("confirm_above_sheets", 0)
        if limit and sheets > limit:
            if not messagebox.askyesno("PrintRouter", f"This uses {sheets} sheets in total.\n\nPrint it?"):
                return
        self.busy = True
        self.sending_to = {job["printer"] for _, job, *_ in batch}
        for b in (self.add_btn, self.remove_btn, self.select_all_btn, self.clear_btn):
            b.config(state="disabled")
        self.refresh()
        self.refresh_counter()
        self.status.config(text=f"Sending {_count(len(batch), 'file')}…")
        threading.Thread(target=self._print_worker, args=(batch, self.receipt_mode.get()), daemon=True).start()

    def _print_receipt(self, entries, name):
        path = WORK_DIR / f"receipt_{name}.pdf"
        receipt.make_receipt_pdf(path, self.prices, entries)
        printing.send(path, self.rules["receipt_printer"])

    def _print_worker(self, batch, receipt_mode):
        done, failed, receipt_errors = [], [], []
        rotate_trays = itertools.cycle(self.rules["rotate_sort"]["trays"])
        for n, (item_id, job, src, pdf, pdf_paper) in enumerate(batch, start=1):
            label = self.printers[job["printer"]]["label"]
            self.results.put(("progress", f"Sending {n} of {len(batch)}: {job['file_name']} → {label}…"))
            try:
                if job.get("hand"):
                    # Both sides on heavy special paper: fronts, the staff turn the stack, then backs.
                    self.jobs.print_one(WORK_DIR / str(item_id), job, src, pdf, pdf_paper, rotate_trays,
                                        side="fronts")
                    answer = {"event": threading.Event(), "ok": False}
                    self.results.put(("turn", job["file_name"], label, answer))
                    answer["event"].wait()
                    if not answer["ok"]:
                        failed.append((item_id, job["file_name"], "the fronts were sent, the backs were NOT"))
                        continue
                    self.results.put(("progress", f"Sending the backs of {job['file_name']} → {label}…"))
                    self.jobs.print_one(WORK_DIR / str(item_id), job, src, pdf, pdf_paper, rotate_trays,
                                        side="backs")
                else:
                    self.jobs.print_one(WORK_DIR / str(item_id), job, src, pdf, pdf_paper, rotate_trays)
            except Exception as e:
                failed.append((item_id, job["file_name"], str(e)))
                continue
            done.append((item_id, job, label))
            self.jobs.log(job, label)
            if receipt_mode == "one_per_file":
                try:
                    self._print_receipt([(job, label)], str(item_id))
                except Exception as e:
                    receipt_errors.append(f"{job['file_name']}: {e}")
        if receipt_mode == "one_for_all" and done:
            try:
                self._print_receipt([(job, label) for _, job, label in done], "batch")
            except Exception as e:
                receipt_errors.append(str(e))
        self.results.put(("batch_done", done, failed, receipt_errors, receipt_mode))

    # -------------------------------------------------------------- counter

    def _load_counter(self):
        try:
            return json.loads(self.counter_path.read_text(encoding="utf-8"))["runs"]
        except (OSError, ValueError, KeyError):
            return []

    def _save_counter(self):
        """Write the counter file; raises OSError if it can't."""
        tmp = self.counter_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"runs": self.counter}, indent=1), encoding="utf-8")
        os.replace(tmp, self.counter_path)  # never leave a half-written file

    def _counter_entries(self):
        return [(e["job"], e["printer"]) for run in self.counter for e in run["entries"]]

    def counter_total(self):
        return sum(receipt.total_price(self.prices, job) for job, _ in self._counter_entries())

    def refresh_counter(self):
        files = len(self._counter_entries())
        if files:
            text = (f"Counter: {_count(len(self.counter), 'print')} · {_count(files, 'file')} · "
                    f"Total {receipt.fmt(self.prices, self.counter_total())}")
        else:
            text = "Counter: empty"
        self.counter_label.config(text=text)
        state = "normal" if files and not self.busy and not self.counter_printing else "disabled"
        for b in (self.counter_print_btn, self.counter_clear_btn):
            b.config(state=state)

    def print_counter(self):
        if self.busy or self.counter_printing or not self.counter:
            return
        self.counter_printing = True
        self.refresh_counter()
        self.status.config(text="Printing the counter receipt…")
        threading.Thread(target=self._counter_receipt_worker,
                         args=(self._counter_entries(), len(self.counter)), daemon=True).start()

    def _counter_receipt_worker(self, entries, runs):
        try:
            self._print_receipt(entries, "counter")
            error = None
        except Exception as e:
            error = str(e)
        self.results.put(("counter_printed", runs, error))

    def finish_counter_receipt(self, runs, error):
        self.counter_printing = False
        if error:
            self.refresh_counter()
            self.status.config(text="")
            messagebox.showwarning("PrintRouter", f"The counter receipt did not print; the counter is kept.\n\n{error}")
            return
        total = self.counter_total()
        del self.counter[:runs]  # only what was on the receipt
        self.refresh_counter()
        self.status.config(text=f"✓ Counter receipt printed  ·  Total {receipt.fmt(self.prices, total)}")
        try:
            self._save_counter()
        except OSError as e:
            messagebox.showwarning("PrintRouter", f"The receipt printed, but the counter file could not be "
                                                  f"updated, so it may come back after a restart.\n\n{e}")

    def clear_counter(self):
        if not self.counter or self.counter_printing:
            return
        if not messagebox.askyesno("PrintRouter", f"Clear the counter ({receipt.fmt(self.prices, self.counter_total())}) "
                                                  f"without printing a receipt?"):
            return
        self.counter = []
        self.refresh_counter()
        try:
            self._save_counter()
        except OSError as e:
            messagebox.showwarning("PrintRouter", f"The counter file could not be updated.\n\n{e}")

    # ------------------------------------------------- results from workers

    def poll(self):
        try:
            while True:
                self.handle(self.results.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def handle(self, msg):
        kind = msg[0]
        if kind == "loaded":
            _, item_id, pdf, paper, pages, coverage, page_colors = msg
            item = self.items.get(item_id)
            if item:  # it may have been removed meanwhile
                item.pdf, item.pdf_paper, item.pages, item.coverage = pdf, paper, pages, coverage
                item.page_colors = page_colors
                item.status = "ready"
                self.on_select()
        elif kind == "load_failed":
            _, item_id, error = msg
            item = self.items.get(item_id)
            if item:
                item.status, item.error = "error", error
                self.refresh()
        elif kind == "progress":
            self.status.config(text=msg[1])
        elif kind == "turn":
            _, name, label, answer = msg
            answer["ok"] = messagebox.askokcancel(
                "PrintRouter", f"The fronts of {name} were sent to {label}.\n\n"
                               f"When they are all out, turn the stack over, put it back in the "
                               f"Bypass Tray, then click OK to print the backs.\n\n"
                               f"Cancel: the backs are not printed.")
            answer["event"].set()
        elif kind == "batch_done":
            self.finish_batch(*msg[1:])
        elif kind == "counter_printed":
            self.finish_counter_receipt(*msg[1:])

    def finish_batch(self, done, failed, receipt_errors, receipt_mode):
        self.busy = False
        self.sending_to = set()
        for b in (self.add_btn, self.remove_btn, self.select_all_btn, self.clear_btn):
            b.config(state="normal")
        if receipt_mode == "counter" and done:
            self.counter.append({"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 "entries": [{"job": job, "printer": label} for _, job, label in done]})
            try:
                self._save_counter()
            except OSError as e:
                receipt_errors.append(f"Added to the counter, but it could not be saved (lost if the app closes): {e}")
        self.refresh_counter()
        # Printed files leave the list; failed ones stay so they can be retried.
        for item_id, _, _ in done:
            if item_id in self.items:
                if self.items[item_id].from_inbox:
                    self._move_printed(self.items[item_id])
                del self.items[item_id]
                self.tree.delete(str(item_id))
        if not self.items:
            self.template = self.default_settings()
            self.fill_panel(self.template)
        else:
            self.select_all()

        lines = []
        if done:
            by_printer = {}
            for _, job, label in done:
                by_printer.setdefault(label, []).append(job["file_name"])
            total = sum(receipt.total_price(self.prices, job) for _, job, _ in done)
            lines.append("Collect the prints here:\n")
            for label, names in by_printer.items():
                lines.append(f"{label}:")
                lines += [f"    • {name}" for name in names]
            lines.append(f"\nTotal: {receipt.fmt(self.prices, total)}")
            if receipt_mode == "counter":
                lines.append(f"Added to the counter, now {receipt.fmt(self.prices, self.counter_total())}. "
                             f"Click “Print counter receipt” when the customer is done.")
            self.status.config(text=f"✓ {_count(len(done), 'file')} sent  ·  "
                                    f"Total {receipt.fmt(self.prices, total)}  ·  "
                                    + "  ·  ".join(f"{label}: {len(n)}" for label, n in by_printer.items()))
        else:
            self.status.config(text="")
        if failed:
            lines.append("\nNOT printed (still in the list):")
            lines += [f"    • {name}: {error}" for _, name, error in failed]
        if receipt_errors:
            lines.append("\nThe receipt did not print:")
            lines += [f"    • {e}" for e in receipt_errors]
        show = messagebox.showwarning if failed or receipt_errors else messagebox.showinfo
        show("PrintRouter", "\n".join(lines))

    def on_close(self):
        if self.busy and not messagebox.askyesno("PrintRouter", "Files are still being sent. Close anyway?"):
            return
        if (self.printhub and self.printhub.sending()
                and not messagebox.askyesno("PrintRouter", "PrintHub orders are still being sent. Close anyway?")):
            return
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled screens
    except Exception:
        pass
    root = tk.Tk()
    try:
        rules = routing.load_json("rules.json")
        routing.load_json("prices.json")
    except Exception as e:
        root.withdraw()
        messagebox.showerror("PrintRouter", f"Could not read the settings files.\n\n{e}")
        return
    problems = routing.check_rules(rules)
    if problems:
        root.withdraw()
        messagebox.showerror("PrintRouter", "There is a problem in rules.json:\n\n" + "\n".join(problems))
        return
    App(root)
    theme.dark_title_bar(root)
    root.mainloop()
    # Let PDF work in progress finish first: pdfium crashes if Python shuts down under it.
    jobs.PDF_LOCK.acquire()


if __name__ == "__main__":
    main()
