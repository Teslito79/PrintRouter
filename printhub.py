"""PrintHub view: print the website's orders, one order at a time per copier.

Opened with the PrintHub button in the main window. Routing, the printer
checks and sending come from jobs.Jobs, the same code the main window uses.

Each order's documents are grouped by the copier the rules pick (a "part").
A copier prints one order's part at a time, and nothing is sent unless a
button is pressed: "Start printing orders" fills every free copier, and
"Pages collected" frees a copier and starts its next order. Once all parts of
an order are collected, its next step (Spiral, Cutting, ...) is started by
hand, up to Ready for courier / pickup. Progress is kept in status.json in each
order folder. See PRINTHUB_SPEC.md.

Orders arrive in Pending Orders. Once every product item is laid out (or straight
away, if the order has documents only) the order folder moves to Orders, where it
can print; when it is Ready for courier / pickup it moves to Finished Orders.

Product items (business cards, flyers, ...) wait for the owner's layout: he opens
the CorelDRAW file named after the order (PH-10240.cdr), lays out the sheet and
exports PH-10240.pdf into the item folder, then presses Layout done and gives the
number of sheets. That PDF is printed as it is, at actual size. An order goes to the copiers only once all
its product items are laid out.
"""
import datetime
import json
import math
import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pypdfium2 as pdfium

import analyze
import cleanup
import jobs
import orders
import receipt
import routing
import theme

WORK_DIR = Path(tempfile.gettempdir()) / "PrintRouter" / "printhub"
STEP_NAMES = {"PRINT": "Printing", "LAMINATE": "Laminating", "SPIRAL": "Spiral", "CUTTING": "Cutting",
              "STAPLE": "Stapling"}
# Part states that keep a copier taken. 'turn': fronts of a hand-turned item are out, waiting for Print backs.
BUSY = ("sending", "turn", "sent", "failed", "interrupted")
PRODUCT_MAX_SHEETS = 9999  # products: more than 999 are sent as several jobs (jobs.MAX_COPIES each)
SIDE_NAMES = {"single": "One side", "long": "Both sides, flip on long edge",
              "short": "Both sides, flip on short edge", orders.HAND: "Both sides, turned by hand"}
# (pdf, size, modified) -> (coverage, page colors), kept when the window is closed and opened again.
_analysis = {}


def _count(n, singular, plural=None):
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


def choose_template(doc, templates):
    """(template path or None, "CorelDRAW template: ..." line) for a product item. First match wins:
    <product id>.cdr, then <W>x<H>.cdr from cut_mm in whole mm, then <H>x<W>.cdr, then blank.cdr.
    File names compare without regard to upper/lower case."""
    try:
        found = {p.name.lower(): p for p in templates.iterdir() if p.is_file()}
    except OSError:
        found = {}
    product = f"{doc.job.get('product')}.cdr"
    if orders._plain_name(product) and product.lower() in found:
        return found[product.lower()], f"CorelDRAW template: {found[product.lower()].name}"
    cut = orders._size_mm(doc.job.get("cut_mm"))
    if cut is not None:
        w, h = (math.floor(v + 0.5) for v in cut)
        for name in (f"{w}x{h}.cdr", f"{h}x{w}.cdr"):
            if name in found:
                return found[name], f"CorelDRAW template: {found[name].name}"
    why = f"no template for {w} x {h} mm" if cut is not None else "no cut size"
    blank = found.get("blank.cdr")
    return blank, f"CorelDRAW template: {blank.name if blank else 'blank.cdr (missing!)'} ({why})"


def pieces_entry(doc, rules):
    """(size text "85 x 55", {"A4": 8, "A3": 18}) from rules.json pieces_per_sheet for a product
    item's cut_mm in whole mm, WxH first, then HxW (as the templates); None when not in the table."""
    cut = orders._size_mm(doc.job.get("cut_mm"))
    if cut is None:
        return None
    table = rules.get("pieces_per_sheet") or {}
    w, h = (math.floor(v + 0.5) for v in cut)
    for a, b in ((w, h), (h, w)):
        entry = table.get(f"{a}x{b}")
        if isinstance(entry, dict):
            found = {k: v for k, v in entry.items() if k in ("A4", "A3") and orders._whole(v) and v > 0}
            if found:
                return f"{a} x {b}", found
    return None


def pieces_line(doc, rules):
    """'Pieces per sheet: 8 on A4, 18 on A3' for Options.txt, or None."""
    entry = pieces_entry(doc, rules)
    if entry is None:
        return None
    return "Pieces per sheet: " + ", ".join(f"{entry[1][k]} on {k}" for k in ("A4", "A3") if k in entry[1])


def tray_lines(doc, rules):
    """'Tray: Bypass Tray' for paper that isn't plain, and the hand-turned line, from what was ordered
    (Tesla, 2026-11-13). Empty for plain paper or an unknown paper."""
    if doc.product:
        paper_type = doc.default_paper_type(rules)
        hand = paper_type and doc.default_sides(rules) == orders.HAND
    else:
        paper_type = doc.job.get("paper_type")
        hand = doc.job.get("sides") in ("long", "short") and routing.hand_turned(rules, paper_type)
    if not paper_type or routing.plain(rules, paper_type):
        return []
    lines = [f"Tray: {orders.BYPASS} (the paper isn't plain paper)"]
    if hand:
        lines.append("Both sides, turned by hand: fronts first, turn the stack over, then Print backs")
    return lines


def options_text(order, doc, template_line=None, pieces=None, rules=None):
    """Options.txt for an item: what the customer ordered, in plain words."""
    j = doc.job
    when = order.paid_at.strftime("%Y-%m-%d %H:%M") if order.paid_at else "?"
    lines = [f"Order {order.number}   item {doc.name}", f"Paid {when}   Delivery: {order.delivery}",
             f"Steps: {' > '.join(map(str, order.steps))}"]
    if order.courier:
        lines.append(f"Courier: {orders.COURIERS[order.courier]}")
    if order.note:
        lines.append(f"Order note: {order.note}")
    lines.append("")
    if doc.product:
        lines.append(f"{j.get('name', 'Product')}   quantity {j.get('quantity', '?')}")
        lines += [f"  {line}" for line in orders.product_lines(doc) + tray_lines(doc, rules or {})]
        if template_line:
            lines += ["", template_line]
        if pieces:
            lines += ([] if template_line else [""]) + [pieces]
        lines += ["", f"Lay it out in {doc.cdr_path().name} and export {doc.pdf_name} into this folder,",
                  "then press Layout done in PrintHub."]
    else:
        lines.append(f"Document: {doc.title}   {j.get('pages', '?')} pages")
        sides = {"single": "One side", "long": "Both sides, long edge", "short": "Both sides, short edge"}
        lines += [f"  Copies: {j.get('copies')}", f"  Colour: {j.get('color')}",
                  f"  Sides: {sides.get(j.get('sides'), j.get('sides'))}", f"  Paper: {j.get('paper')}",
                  f"  Pages per side: {j.get('per_side')}", f"  Paper type: {j.get('paper_type')}"]
        lines += [f"  {line}" for line in orders.document_lines(doc) + tray_lines(doc, rules or {})]
    if doc.problems:
        lines += ["", "Problems:"] + [f"  {p}" for p in doc.problems]
    return "\n".join(lines) + "\n"  # written in text mode: Windows line ends are added then


def hand_job(job):
    """A hand-turned item: fronts and backs are each one page x the sheets, so the paper used is the sheets."""
    job["hand"] = True
    job["sheets"] = job["print_copies"]
    job["pages"] = 1  # each of the two jobs holds one page


def prepare_item(order, doc, templates, rules=None):
    """Put Options.txt (and, for products, a blank CorelDRAW file named after the order) into the
    item folder, once. Never overwrites: staff may have written in Options.txt or laid out the
    CorelDRAW file already (an older print.cdr counts too)."""
    jobs_to_do = [(doc.folder / orders.OPTIONS_TXT, None)]
    line = pieces = None
    if doc.product:
        pieces = pieces_line(doc, rules or {})
        template, line = choose_template(doc, templates)
        if template is not None:
            jobs_to_do.append((doc.cdr_path(), template))
    for dest, template in jobs_to_do:
        if dest.exists():
            continue
        tmp = dest.with_name(f".{dest.name}.tmp")
        try:
            if template is None:
                tmp.write_text(options_text(order, doc, line, pieces, rules), encoding="utf-8-sig")
            else:
                shutil.copyfile(template, tmp)
            os.replace(tmp, dest)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass


class PrintHubView:
    def __init__(self, root, rules, shared_jobs, website=None):
        self.rules = rules
        self.jobs = shared_jobs
        self.website = website  # sync.WebsiteSync, started by the main window (None in tests)
        self.printers = rules["printers"]
        self.pending = orders.pending_dir(rules)
        self.pending.mkdir(parents=True, exist_ok=True)
        self.folder = orders.orders_dir(rules)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.move_errors = {}  # order number -> why it couldn't move from Pending Orders to Orders
        self.laid_out = set()  # orders given Layout done while printing is ON: started when their copier is free
        self.finished = orders.finished_dir(rules)
        self.finished.mkdir(parents=True, exist_ok=True)
        self.templates = orders.templates_dir(rules)
        self.orders = []  # orders.Order, oldest payment first
        # Order number -> progress, as in status.json: {"step": index into the order's steps,
        # "parts": {printer: {"documents", "state", "sent", ...}},
        # "layout": {product item: {"sheets", "paper_type", "sides", "stamp" of print.pdf, ...}}, "history": [...]}
        self.status = {}
        self.progress = {}  # (order, printer) -> (document n, of total) while sending
        self.running = False  # Start printing orders pressed (and not stopped)
        self.seen = None  # the orders folder at the last load, to notice changes
        self.loading = False
        self.load_again = False
        self.results = queue.Queue()  # messages from the threads
        self.to_send = queue.Queue()  # parts waiting to be sent, one at a time
        # A copier taken by an order (sending, sent and not collected yet, waiting for Print backs,
        # failed or interrupted) is busy: colour goes to the IM C4510 instead of the IM C3000.
        self.jobs.busy_sources.append(lambda: {pid for pid in self.printers if self.busy_with(pid)})

        self.win = tk.Toplevel(root)
        self._build()
        theme.dark_title_bar(self.win)
        # Closing only hides the window: sending and the order progress carry on.
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)
        threading.Thread(target=self._send_worker, daemon=True).start()
        self.reload()
        self.win.after(100, self.poll)
        self.win.after(3000, self.watch)
        self.win.after(500, self.show_sync)

    # ------------------------------------------------------------------ UI

    def _build(self):
        win = self.win
        win.title("PrintRouter: PrintHub")
        win.geometry("1200x900")
        win.minsize(1000, 700)
        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(3, weight=1)

        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we", pady=(0, 8))
        ttk.Button(top, text="Reload", command=self.press_reload).pack(side="left")
        for folder in (self.pending, self.folder, self.finished):
            ttk.Button(top, text=f"Open {folder.name}", command=lambda d=folder: self.open_path(d)).pack(
                side="left", padx=(8, 0))
        self.summary = ttk.Label(top, text="", style="Summary.TLabel")
        self.summary.pack(side="right")
        self.sync_label = ttk.Label(top, text="", style="Hint.TLabel", justify="right")
        self.sync_label.pack(side="right", padx=(0, 24))

        # One panel per copier: the order it is printing, its buttons, and what's next.
        panels = ttk.Frame(f)
        panels.grid(row=1, column=0, sticky="we")
        self.panels = {}
        for n, (pid, p) in enumerate(self.printers.items()):
            panels.columnconfigure(n, weight=1, uniform="printers")
            box = ttk.LabelFrame(panels, text=p["label"], padding=8, style="Section.TLabelframe")
            box.grid(row=0, column=n, sticky="nsew", padx=(0 if n == 0 else 8, 0))
            state = ttk.Label(box, text="", wraplength=330, font=("Segoe UI", 12, "bold"))
            state.pack(anchor="w")
            buttons = ttk.Frame(box)
            buttons.pack(anchor="w", pady=4)
            upcoming = ttk.Label(box, text="", wraplength=330, style="Hint.TLabel")
            upcoming.pack(anchor="w")
            self.panels[pid] = {"state": state, "buttons": buttons, "next": upcoming}
            theme.on_surface(box)

        run = ttk.Frame(f)
        run.grid(row=2, column=0, sticky="we", pady=10)
        ttk.Button(run, text="Start printing orders", style="Print.TButton", command=self.start_printing).pack(
            side="left")
        ttk.Button(run, text="Stop after current orders", command=self.stop_printing).pack(side="left", padx=(12, 0))
        self.run_label = ttk.Label(run, text="", wraplength=600, style="Hint.TLabel")
        self.run_label.pack(side="left", padx=(16, 0))

        box = ttk.Frame(f)
        box.grid(row=3, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        columns = ("pages", "settings", "printer", "status")
        self.tree = ttk.Treeview(box, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Order / document", anchor="w")
        self.tree.column("#0", width=260, stretch=True)
        for col, text, width, stretch in (("pages", "Pages", 60, False), ("settings", "Settings", 380, True),
                                          ("printer", "Printer", 190, False), ("status", "Status", 260, True)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure("order", font=("Segoe UI", 12, "bold"))
        self.tree.tag_configure("error", foreground=theme.ERROR)
        self.tree.tag_configure("done", foreground=theme.MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.tree.bind("<Double-1>", lambda _: self.open_first_file())
        self.empty_hint = ttk.Label(box, text="", style="Hint.TLabel")
        # Buttons for the selected product item: open the customer's files, Layout done.
        self.item_bar = ttk.Frame(f)
        self.item_bar.grid(row=4, column=0, sticky="we", pady=(6, 0))

        # Orders whose pages are all collected, each with the button for its next step.
        self.steps_box = ttk.LabelFrame(f, text="Next steps", padding=8, style="Section.TLabelframe")
        self.steps_box.grid(row=5, column=0, sticky="we", pady=(10, 0))
        self.details = ttk.Label(f, text="", wraplength=1100, justify="left")
        self.details.grid(row=6, column=0, sticky="we", padx=6, pady=(10, 0))
        self.refresh_run_label()

    def show_sync(self):
        """The website sync's state in the top bar: off, last check, or red when it can't connect."""
        if self.website is not None:
            text, red, stuck = self.website.status()
            self.sync_label.config(text="\n".join([text] + stuck),
                                   foreground=theme.ERROR if red or stuck else "")
        self.win.after(2000, self.show_sync)

    def is_open(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    # -------------------------------------------------------------- loading

    def _signature(self):
        """Order folders and when their order.json last changed, plus every file in the item folders
        (job.json, customer files, print.pdf), except the ones PrintRouter writes or CorelDRAW keeps saving."""
        found = []
        for folder in (self.pending, self.folder):
            try:
                for sub in folder.iterdir():
                    try:
                        found.append((folder.name, sub.name, (sub / "order.json").stat().st_mtime_ns))
                    except OSError:
                        continue  # no order.json yet: still downloading
                    try:
                        for item in sub.iterdir():
                            if not item.is_dir():
                                continue
                            for f in item.iterdir():
                                if (f.name.startswith(".") or f.name == orders.OPTIONS_TXT
                                        or f.suffix.lower() == ".cdr"):  # CorelDRAW saves often
                                    continue
                                try:
                                    st = f.stat()
                                    found.append((folder.name, f"{sub.name}/{item.name}/{f.name}",
                                                  st.st_size, st.st_mtime_ns))
                                except OSError:
                                    pass
                    except OSError:
                        pass
            except OSError:
                pass
        return sorted(found)

    def watch(self):
        """Reload by itself when orders arrive, change or go away, or a print.pdf is saved
        (new orders never start printing by themselves)."""
        saving = any(d.print_state == "saving" for o in self.orders for d in o.documents)
        if not self.loading and (saving or self._signature() != self.seen):
            self.reload()
        elif not self.loading and self.move_errors:
            self.promote()  # try again: the file that was open may be closed now
        self.win.after(3000, self.watch)

    def press_reload(self):
        """The Reload button: also clears the website's red notices (shown until then)."""
        if self.website is not None:
            self.website.clear_notices()
        self.reload()

    def reload(self):
        if self.loading:
            self.load_again = True
            return
        self.loading = True
        self.seen = self._signature()
        self.summary.config(text="Reading orders…")
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):
        """Read the orders and analyse each PDF's colors, as the main window does for its files."""
        try:
            with jobs.PDF_LOCK:
                pending = orders.load_orders(self.pending, self.rules)
                ready = orders.load_orders(self.folder, self.rules)
            numbers = {o.number for o in ready}
            for order in pending:
                if order.number in numbers:
                    order.problems.append(f"{order.number} is also in {self.folder.name}: remove one of them")
            found = orders.sort_orders(pending + ready)
            for order in found:
                for doc in order.documents:
                    if doc.job and doc.folder.is_dir():
                        prepare_item(order, doc, self.templates, self.rules)
            for order in found:
                for doc in order.documents:
                    doc.coverage = doc.page_colors = None
                    if doc.pdf is None:
                        continue
                    try:
                        st = doc.pdf.stat()
                        key = (str(doc.pdf), st.st_size, st.st_mtime_ns)
                        if key not in _analysis:
                            with jobs.PDF_LOCK:
                                _analysis[key] = (analyze.color_coverage(doc.pdf), analyze.color_pages(doc.pdf))
                        doc.coverage, doc.page_colors = _analysis[key]
                    except Exception as e:
                        doc.problems.append(f"Can't read the colors: {e}")
            self.results.put(("loaded", found, None))
        except Exception as e:
            self.results.put(("loaded", [], str(e)))

    def poll(self):
        try:
            while True:
                self.handle(self.results.get_nowait())
        except queue.Empty:
            pass
        self.win.after(100, self.poll)

    def handle(self, msg):
        kind = msg[0]
        if kind == "loaded":
            _, found, error = msg
            self.loading = False
            self.orders = found
            self.refresh()
            self.promote()
            self.start_laid_out()
            if error:
                messagebox.showwarning("PrintHub", f"Could not read the orders folder.\n\n{error}", parent=self.win)
            if self.load_again:
                self.load_again = False
                self.reload()
            return
        number, printer = msg[1], msg[2]
        part = self.status[number]["parts"][printer]
        if kind == "progress":
            self.progress[(number, printer)] = msg[3]
        elif kind == "doc_sent":
            part["sent"].append(msg[3])
            self.save(number, f"{msg[3]} sent to {printer}")
        elif kind == "step_sent":  # fronts or backs of a hand-turned item
            name, step = msg[3], msg[4]
            if step == "fronts":
                part.setdefault("fronts", []).append(name)
            else:
                part["sent"].append(name)
                part.pop("turn", None)
            self.save(number, f"{name} {step} sent to {printer}")
        elif kind == "part_sent":
            self.progress.pop((number, printer), None)
            self.batch_done(number, printer)
        elif kind == "failed":
            part.update(state="failed", error=msg[3])
            self.progress.pop((number, printer), None)
            self.save(number, f"sending to {printer} failed: {msg[3]}")
        self.refresh()

    # ------------------------------------------------------------- progress

    def status_of(self, order):
        """The order's progress, read from its status.json the first time it is seen."""
        st = self.status.get(order.number)
        if st is None:
            st = {"step": 0, "parts": {}, "layout": {}, "history": []}
            try:
                data = json.loads((order.folder / "status.json").read_text(encoding="utf-8"))
                st.update(step=int(data["step"]), parts=dict(data["parts"]), layout=dict(data.get("layout", {})),
                          history=list(data["history"]))
                for part in st["parts"].values():
                    part["documents"], part["sent"] = list(part["documents"]), list(part.get("sent", []))
                    if part["state"] == "sending":
                        part["state"] = "interrupted"  # the app closed while sending
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                # Never start over from scratch: that could print the order twice.
                st["broken"] = f"status.json can't be read ({e}): check the order by hand"
            self.status[order.number] = st
        return st

    def save(self, number, event):
        """Note the event and write the order's status.json; never leave a half-written file."""
        st = self.status[number]
        st["history"].append({"time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": event})
        path = next((o.folder for o in self.orders if o.number == number), self.folder / number) / "status.json"
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: st[k] for k in ("step", "parts", "layout", "history")}, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            messagebox.showwarning("PrintHub", f"The progress of order {number} could not be saved; it may be "
                                               f"lost if the app closes.\n\n{e}", parent=self.win)

    def layout_of(self, order, doc):
        """The owner's Layout done for a product item, while print.pdf is still the file he confirmed."""
        entry = self.status_of(order)["layout"].get(doc.name)
        if entry and doc.print_state == "ok" and entry.get("stamp") == doc.print_stamp:
            return entry
        return None

    def sent_already(self, order, doc):
        return any(doc.name in part["sent"] for part in self.status_of(order)["parts"].values())

    def waiting_layout(self, order):
        """Product items of the order that aren't laid out yet (and not printed already)."""
        return [d for d in order.documents if d.product and not d.problems
                and not self.layout_of(order, d) and not self.sent_already(order, d)]

    def document_job(self, order, doc, printer=None):
        """(settings, job, problem) for one item; settings and job are None if it can't be routed.
        A product item that isn't laid out yet gives (None, None, None): waiting, not a problem.

        printer: the copier this item was given when its order started, if the rules
        would now pick another one (e.g. rules.json changed meanwhile)."""
        if doc.problems:
            return None, None, doc.problems[0]
        if doc.product:
            entry = self.layout_of(order, doc)
            if entry is None:
                return None, None, None
            settings = doc.product_settings(entry["sheets"], entry["paper_type"], entry["sides"], self.rules)
        else:
            settings = doc.settings()
        limit = PRODUCT_MAX_SHEETS if doc.product else jobs.MAX_COPIES
        job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors, limit)
        if job and printer and job["printer"] != printer:
            settings["printer"] = printer
            job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors, limit)
        if job is None:
            return settings, None, "Can't print with these settings"
        if doc.product:
            job["actual_size"] = True  # the owner's sheet exactly as it is: no fitting, no scaling
            if entry["sides"] == orders.HAND:
                hand_job(job)
        return settings, job, job["problem"]

    def settings_text(self, settings, job):
        """As the main window shows settings; a hand-turned item says so instead of Single."""
        text = self.jobs.settings_text(settings, job)
        return text.replace(" · Single · ", " · Both sides by hand · ", 1) if job and job.get("hand") else text


    def problems_of(self, order):
        problems = list(order.problems)
        st = self.status_of(order)
        if "broken" in st:
            problems.append(st["broken"])
        for doc in order.documents:
            problem = self.document_job(order, doc)[2]
            if problem:
                problems.append(f"{doc.name} ({doc.title}): {problem}")
        return problems

    def parts_of(self, order):
        """{printer: [document names]}, fixed in status.json once the order starts, else from the rules now."""
        st = self.status_of(order)
        if st["parts"]:
            return {pid: part["documents"] for pid, part in st["parts"].items()}
        parts = {}
        for doc in order.documents:
            job = self.document_job(order, doc)[1]
            if job:
                parts.setdefault(job["printer"], []).append(doc.name)
        return parts

    def part_state(self, order, printer):
        part = self.status_of(order)["parts"].get(printer)
        return part["state"] if part else "waiting"

    def printed(self, order):
        """True when every part's pages have been collected."""
        st = self.status_of(order)
        return bool(st["parts"]) and all(p["state"] == "collected" for p in st["parts"].values())

    def queue(self, printer):
        """Orders waiting for this copier, oldest payment first."""
        return [o for o in self.orders if self.status_of(o)["step"] == 0 and printer in self.parts_of(o)
                and self.part_state(o, printer) == "waiting" and not self.problems_of(o)
                and not self.waiting_layout(o) and not self.in_pending(o)]

    def busy_with(self, printer):
        """The order this copier is printing (or waiting to be collected), or None."""
        for order in self.orders:
            if self.part_state(order, printer) in BUSY:
                return order
        return None

    def sending(self):
        return any(p["state"] == "sending" for st in self.status.values() for p in st["parts"].values())

    def next_step(self, order):
        """(label of the button for the order's next step, or None; text for where it is now)."""
        st = self.status_of(order)
        steps, step = order.steps, st["step"]
        if step >= len(steps):
            return None, f"Ready for {order.delivery}"
        if step == 0 and not self.printed(order):
            return None, None
        now = "Printed" if step == 0 else f"{STEP_NAMES.get(steps[step], steps[step].title())} in progress"
        if step + 1 < len(steps):
            name = steps[step + 1]
            return f"Start {STEP_NAMES.get(name, name.title())} Process", now
        return f"Ready for {order.delivery}", now

    # -------------------------------------------------------------- actions

    def start_printing(self):
        self.running = True
        self.refresh_run_label()
        for pid in self.printers:
            self.start_next(pid)
        self.refresh()

    def stop_printing(self):
        self.running = False
        self.refresh_run_label()

    def refresh_run_label(self):
        self.run_label.config(text="Printing orders: ON. “Pages collected” starts that copier's next order."
                              if self.running else
                              "Printing orders: OFF. Nothing is sent until you press Start printing orders.")

    def start_laid_out(self):
        """Orders that got Layout done while printing is ON start by themselves once they are in
        Orders, on each of their copiers that is free (other new orders still wait for a button)."""
        if not self.running:
            self.laid_out.clear()
            return
        for number in list(self.laid_out):
            order = next((o for o in self.orders if o.number == number), None)
            if order is None or self.in_pending(order):
                continue  # still moving (or the move waits for a file to be closed)
            self.laid_out.discard(number)
            for pid in self.parts_of(order):
                self.start_next(pid, order)
        self.refresh()

    def start_next(self, printer, only=None):
        """Send the next waiting order to this copier, if it is free (only: just this order, if it waits)."""
        if not self.running or self.busy_with(printer):
            return
        waiting = self.queue(printer)
        if only is not None:
            waiting = [o for o in waiting if o is only]
        if not waiting:
            return
        order = waiting[0]
        docs = {d.name: d for d in order.documents}
        part_jobs = [self.document_job(order, docs[name], printer)[1] for name in self.parts_of(order)[printer]
                     if name in docs]
        sheets = sum(job["sheets"] for job in part_jobs if job)
        limit = self.rules.get("confirm_above_sheets", 0)
        if limit and sheets > limit and not messagebox.askyesno(
                "PrintHub", f"Order {order.number} uses {sheets} sheets on {self.printers[printer]['label']}.\n\n"
                            f"Print it?", parent=self.win):
            return
        self.send_part(order, printer)

    def send_part(self, order, printer):
        """Send this order's documents for one copier (the ones not sent yet)."""
        st = self.status_of(order)
        if not st["parts"]:  # fix where every document goes, for all copiers at once
            st["parts"] = {pid: {"documents": names, "state": "waiting", "sent": []}
                           for pid, names in self.parts_of(order).items()}
        part = st["parts"][printer]
        docs = {d.name: d for d in order.documents}
        tasks, hand = [], None
        for name in part["documents"]:
            if name in part["sent"]:
                continue
            job = self.document_job(order, docs[name], printer)[1] if name in docs else None
            if job is None or job["problem"]:
                part.update(state="failed", error=f"{name}: can't be printed any more")
                self.save(order.number, f"{name} can't be printed on {printer}")
                return
            if job.get("hand"):
                # Fronts after the other documents, one hand-turned item at a time; its backs wait
                # for Print backs (and are never part of this).
                if hand is None and name not in part.get("fronts", []):
                    hand = (name, job)
                continue
            # The order number in the name shows in the copier's queue and in print_log.csv.
            job["file_name"] = f"{order.number} {name} {docs[name].title}"
            tasks.append((name, job, docs[name].pdf, WORK_DIR / order.number / name, None))
        if hand:
            name, job = hand
            job["file_name"] = f"{order.number} {name} {docs[name].title} fronts"
            tasks.append((name, job, docs[name].pdf, WORK_DIR / order.number / name, "fronts"))
        if not tasks:  # only backs are left: they wait for Print backs
            self.batch_done(order.number, printer)
            return
        self.start_batch(order, printer, tasks, f"sending to {printer}")

    def start_batch(self, order, printer, tasks, event):
        part = self.status_of(order)["parts"][printer]
        # What this send holds, so "Everything printed" after a crash knows what came out.
        part.update(state="sending", error=None, batch=[[name, step] for name, _, _, _, step in tasks])
        self.progress[(order.number, printer)] = (0, len(tasks))
        self.save(order.number, event)
        self.to_send.put((order.number, printer, tasks))

    def send_backs(self, printer):
        """Print backs: the stack of fronts was turned over and put back; send page 2."""
        order = self.busy_with(printer)
        if order is None:
            return
        part = self.status_of(order)["parts"][printer]
        name = part.get("turn")
        doc = next((d for d in order.documents if d.name == name), None)
        job = self.document_job(order, doc, printer)[1] if doc else None
        if job is None or job["problem"]:
            part.update(state="failed", error=f"{name}: can't be printed any more")
            self.save(order.number, f"{name} backs can't be printed on {printer}")
            self.refresh()
            return
        job["file_name"] = f"{order.number} {name} {doc.title} backs"
        self.start_batch(order, printer, [(name, job, doc.pdf, WORK_DIR / order.number / name, "backs")],
                         f"{name} sending backs to {printer}")
        self.refresh()

    def batch_done(self, number, printer):
        """A send finished: wait for Print backs, send the next hand-turned item's fronts, or all sent."""
        order = next((o for o in self.orders if o.number == number), None)
        part = self.status[number]["parts"][printer]
        part.pop("batch", None)
        waiting = [n for n in part["documents"] if n in part.get("fronts", []) and n not in part["sent"]]
        if waiting:
            part.update(state="turn", turn=waiting[0])
            self.save(number, f"{waiting[0]} fronts out on {printer}: turn the stack over, then Print backs")
        elif order is not None and any(n not in part["sent"] for n in part["documents"]):
            self.send_part(order, printer)  # another hand-turned item's fronts
        else:
            part["state"] = "sent"
            self.save(number, f"all sent to {printer}")

    def _send_worker(self):
        """Send the parts one after another; the copiers then print them at the same time."""
        while True:
            number, printer, tasks = self.to_send.get()
            for n, (name, job, pdf, work_dir, step) in enumerate(tasks, start=1):
                self.results.put(("progress", number, printer, (n, len(tasks))))
                try:
                    work_dir.mkdir(parents=True, exist_ok=True)
                    # step: fronts = the odd printed sides, backs = the even ones, each as its own job
                    self.jobs.print_one(work_dir, job, pdf, pdf, job["paper"], None, side=step)
                except Exception as e:
                    what = f"{name} {step}" if step else name
                    self.results.put(("failed", number, printer, f"{what}: {e}"))
                    break
                self.jobs.log(job, self.printers[printer]["label"])
                self.results.put(("step_sent", number, printer, name, step) if step
                                 else ("doc_sent", number, printer, name))
            else:
                self.results.put(("part_sent", number, printer))

    def collected(self, printer):
        """The pages were taken off this copier: free it and start its next order."""
        order = self.busy_with(printer)
        if order is None:
            return
        self.status_of(order)["parts"][printer]["state"] = "collected"
        self.save(order.number, f"pages collected from {printer}")
        self.start_next(printer)
        self.refresh()

    def retry(self, printer):
        """Send again only what didn't go: the backs if they failed, otherwise what isn't sent yet."""
        order = self.busy_with(printer)
        if order:
            part = self.status_of(order)["parts"][printer]
            if part.get("turn") and part["turn"] not in part["sent"]:
                self.send_backs(printer)
            else:
                self.send_part(order, printer)
            self.refresh()

    def it_printed(self, printer):
        """After the app closed mid-send: staff checked and everything in that send came out."""
        order = self.busy_with(printer)
        if order is None:
            return
        part = self.status_of(order)["parts"][printer]
        batch = part.get("batch") or [[n, None] for n in part["documents"] if n not in part["sent"]]
        for name, step in batch:
            if step == "fronts":
                if name not in part.setdefault("fronts", []):
                    part["fronts"].append(name)
            elif name not in part["sent"]:
                part["sent"].append(name)
                if step == "backs":
                    part.pop("turn", None)
        self.save(order.number, f"checked by hand: printed on {printer}")
        self.batch_done(order.number, printer)
        self.refresh()

    def do_next_step(self, number):
        order = next((o for o in self.orders if o.number == number), None)
        if order is None:
            return
        label, _ = self.next_step(order)
        if label is None:
            return
        self.status_of(order)["step"] += 1
        self.save(number, label)
        if self.status_of(order)["step"] >= len(order.steps):
            if self.website is not None:
                self.website.report_ready(number)  # the website's admin page: Ready to ship
            self.move_finished(order)
        self.refresh()

    def in_pending(self, order):
        return order.folder.parent == self.pending

    def promote(self):
        """Move every Pending order that is ready (all products laid out, no problems) to Orders."""
        moved = False
        for order in [o for o in self.orders if self.in_pending(o)]:
            if self.problems_of(order) or self.waiting_layout(order):
                self.move_errors.pop(order.number, None)
                continue
            dest = self.folder / order.number
            try:
                if dest.exists():
                    raise OSError(f"{self.folder.name} already has {order.number}")
                os.replace(order.folder, dest)
            except OSError as e:
                if order.number not in self.move_errors:
                    self.move_errors[order.number] = str(e)
                    self.refresh()
                continue
            self.move_errors.pop(order.number, None)
            self.orders = [o for o in self.orders if o is not order]  # back after the reload, from Orders
            moved = True
        if moved:
            self.refresh()
            self.reload()

    def move_finished(self, order):
        """Move a Ready order's folder from Orders to Finished Orders."""
        dest = self.finished / order.number
        n = 2
        while dest.exists():  # the same number finished before: keep both
            dest = self.finished / f"{order.number} ({n})"
            n += 1
        try:
            os.replace(order.folder, dest)
        except OSError as e:
            messagebox.showwarning(
                "PrintHub", f"Order {order.number} is ready but could not be moved to {self.finished.name}.\n\n"
                            f"Close its files (CorelDRAW, PDF viewer, the folder in Explorer), then press "
                            f"Move to {self.finished.name}.\n\n{e}", parent=self.win)
            return False
        cleanup.write_finished(dest)  # the time it is deleted from: 8 days after this (cleanup.py)
        self.status.pop(order.number, None)
        self.orders = [o for o in self.orders if o is not order]
        self.reload()
        return True

    # ------------------------------------------------------------ the views

    def refresh(self):
        self.fill()
        self.refresh_printers()
        self.refresh_steps()

    def order_text(self, order):
        """The order's status column."""
        if self.problems_of(order):
            return "Needs attention"
        waiting = self.waiting_layout(order)
        if waiting and self.status_of(order)["step"] == 0:
            return f"Waiting for layout ({len(waiting)})" if len(waiting) > 1 else "Waiting for layout"
        if self.in_pending(order):
            if order.number in self.move_errors:
                return f"Laid out, but can't move to {self.folder.name}: close its files"
            return f"Moving to {self.folder.name}…"
        label, now = self.next_step(order)
        if now:
            return now
        st = self.status_of(order)
        if not st["parts"]:
            return "Waiting to print"
        return " · ".join(f"{pid}: {part['state']}" for pid, part in st["parts"].items())

    def fill(self):
        """Show the orders, keeping the selection."""
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        attention = waiting = 0
        for order in self.orders:
            oid = f"order:{order.number}"
            bad = bool(self.problems_of(order))
            ready = self.status_of(order)["step"] >= len(order.steps) and not bad
            parts = self.parts_of(order)
            self.tree.insert("", "end", iid=oid, open=not ready, text=order.number)
            for doc in order.documents:
                printer = next((pid for pid, names in parts.items() if doc.name in names), None)
                settings, job, problem = self.document_job(order, doc, printer)
                label = self.printers[job["printer"]]["label"] if job else ""
                if doc.product:
                    text, red = self.product_state(order, doc, job, problem)
                    shown = " · ".join(doc.job.get("options", {}).values())
                    if job:
                        shown = f"{doc.pdf_name} {self.settings_text(settings, job)}  ({shown})"
                    values = (doc.pages or "", shown, label, text)
                else:
                    red = bool(problem)
                    values = (doc.pages or "", self.jobs.settings_text(settings, job) if settings else "",
                              label, problem or "OK")
                self.tree.insert(oid, "end", iid=f"{oid}/{doc.name}", text=f"{doc.name}   {doc.title}",
                                 values=values, tags=("error",) if red else ())
            attention += bad
            waiting += not bad and not ready
            when = order.paid_at.strftime("%d/%m %H:%M") if order.paid_at else "?"
            steps = " › ".join(map(str, order.steps))
            where = f"{self.pending.name} · " if self.in_pending(order) else ""
            self.tree.item(oid, values=("", f"{where}{order.delivery} · {steps} · paid {when}", " + ".join(parts),
                                        self.order_text(order)),
                           tags=("order", "error") if bad else ("order", "done") if ready else ("order",))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        if self.orders:
            self.empty_hint.place_forget()
            text = f"{_count(len(self.orders), 'order')} · {waiting} in progress"
            if attention:
                text += f" · {attention} need{'s' if attention == 1 else ''} attention"
        else:
            self.empty_hint.config(text=f"No orders yet. Orders appear here when they arrive in\n{self.pending}")
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
            text = "No orders"
        self.summary.config(text=text)
        self.show_details()

    def refresh_printers(self):
        for pid, panel in self.panels.items():
            for b in panel["buttons"].winfo_children():
                b.destroy()
            order = self.busy_with(pid)
            buttons = []
            if order is None:
                text = "Free"
            else:
                part = self.status_of(order)["parts"][pid]
                state = part["state"]
                if state == "sending":
                    n, total = self.progress.get((order.number, pid), (0, len(part["documents"])))
                    text = f"{order.number}: sending {n} of {total}…"
                elif state == "sent":
                    text = f"{order.number}: sent. Take the pages off when they're done."
                    buttons = [("Pages collected", lambda p=pid: self.collected(p))]
                elif state == "turn":
                    name = part.get("turn", "")
                    doc = next((d for d in order.documents if d.name == name), None)
                    job = self.document_job(order, doc, pid)[1] if doc is not None else None
                    tray = f"the {orders.BYPASS}" if job and job["tray"] == orders.BYPASS else "the tray"
                    text = (f"{order.number} {name}: fronts sent. When they're out, turn the stack over, "
                            f"put it back in {tray}, then press Print backs.")
                    buttons = [("Print backs", lambda p=pid: self.send_backs(p))]
                elif state == "failed":
                    text = f"{order.number}: NOT sent. {part.get('error', '')}"
                    buttons = [("Retry", lambda p=pid: self.retry(p))]
                else:  # interrupted
                    text = (f"{order.number}: the app closed while sending. Check what came out of the copier, "
                            f"then choose.")
                    buttons = [("Everything printed", lambda p=pid: self.it_printed(p)),
                               ("Send the rest again", lambda p=pid: self.retry(p))]
            for label, command in buttons:
                ttk.Button(panel["buttons"], text=label, command=command).pack(side="left", padx=(0, 8))
            panel["state"].config(text=text)
            upcoming = [o.number for o in self.queue(pid)]
            panel["next"].config(text="Next: " + ", ".join(upcoming[:6]) + (f" +{len(upcoming) - 6} more"
                                                                               if len(upcoming) > 6 else "")
                                 if upcoming else "Nothing waiting")

    def refresh_steps(self):
        for w in self.steps_box.winfo_children():
            w.destroy()
        rows = [(order, *self.next_step(order)) for order in self.orders if not self.problems_of(order)]
        rows = [(order, label, now) for order, label, now in rows if label]
        # Ready, but the move to Finished Orders failed (a file was open): offer it again.
        stuck = [o for o in self.orders if not self.problems_of(o) and self.status_of(o)["step"] >= len(o.steps)]
        for order in stuck[:8]:
            row = ttk.Frame(self.steps_box)
            row.pack(anchor="w", fill="x", pady=2)
            ttk.Label(row, text=f"{order.number}", width=12, font=("Segoe UI", 12, "bold")).pack(side="left")
            ttk.Label(row, text=f"Ready for {order.delivery}", width=22).pack(side="left")
            ttk.Button(row, text=f"Move to {self.finished.name}",
                       command=lambda o=order: self.move_finished(o) and self.refresh()).pack(side="left")
        if not rows and not stuck:
            ttk.Label(self.steps_box, text="No order is waiting for its next step.", style="Hint.TLabel").pack(
                anchor="w")
        for order, label, now in rows[:8]:
            row = ttk.Frame(self.steps_box)
            row.pack(anchor="w", fill="x", pady=2)
            ttk.Label(row, text=f"{order.number}", width=12, font=("Segoe UI", 12, "bold")).pack(side="left")
            ttk.Label(row, text=now, width=22).pack(side="left")
            ttk.Button(row, text=label, command=lambda n=order.number: self.do_next_step(n)).pack(side="left")
        if len(rows) > 8:
            ttk.Label(self.steps_box, text=f"and {len(rows) - 8} more", style="Hint.TLabel").pack(anchor="w")
        theme.on_surface(self.steps_box)

    def selected_item(self):
        """(order, item or None) for the selected row, or (None, None)."""
        selected = self.tree.selection()
        if not selected:
            return None, None
        number, _, name = selected[0].removeprefix("order:").partition("/")
        order = next((o for o in self.orders if o.number == number), None)
        if order is None:
            return None, None
        return order, next((d for d in order.documents if d.name == name), None)

    def show_details(self):
        """Note, problems, sheets per copier and progress of the selected order; the product item's
        choices, files and layout."""
        self.refresh_item_bar()
        order, item = self.selected_item()
        if order is None:
            self.details.config(text="Click an order to see its details.")
            return
        lines = [f"{order.number} · paid {order.paid_at:%Y-%m-%d %H:%M} · {order.delivery}"
                 if order.paid_at else order.number]
        if order.courier:
            lines[0] += f" · {orders.COURIERS[order.courier]}"
        if order.note:
            lines.append(f"Note: {order.note}")
        docs = {d.name: d for d in order.documents}
        sheets = []
        for pid, names in self.parts_of(order).items():
            jobs_ = [self.document_job(order, docs[n], pid)[1] for n in names if n in docs]
            if all(jobs_):
                sheets.append(f"{self.printers[pid]['label']}: {sum(j['sheets'] for j in jobs_)}")
        if sheets:
            lines.append("Sheets: " + " · ".join(sheets))
        problems = self.problems_of(order)
        if problems:
            lines.append("Needs attention:")
            lines += [f"    • {p}" for p in problems]
        history = self.status_of(order)["history"]
        if history:
            lines.append("Last: " + " · ".join(f"{h['time'][11:16]} {h['event']}" for h in history[-3:]))
        if item is not None and item.product:
            lines += [""] + self.product_lines(order, item)
        elif item is not None and (orders.document_lines(item) or tray_lines(item, self.rules)):
            lines += ["", f"{item.name}  {item.title}"] + [
                f"    {line}" for line in orders.document_lines(item) + tray_lines(item, self.rules)]
        self.details.config(text="\n".join(lines))

    # -------------------------------------------------------- product items

    def product_state(self, order, doc, job, problem):
        """(status text, shown in red) for a product item."""
        if doc.problems:
            return doc.problems[0], True
        if self.sent_already(order, doc):
            entry = self.status_of(order)["layout"].get(doc.name, {})
            if doc.print_stamp != entry.get("stamp"):
                return f"Sent. {doc.pdf_name} changed afterwards (not printed again)", True
            return "Sent", False
        entry = self.layout_of(order, doc)
        if entry:
            if problem:
                return f"{problem}: press Layout done to change", True
            return f"Ready to print: {_count(entry['sheets'], 'sheet')}", False
        if doc.print_state is None:
            wrong = next((w for *_, w in doc.files if w), None)
            return ("Waiting for layout" + (f" · file is {wrong}" if wrong else "")), False
        if doc.print_state == "saving":
            return f"{doc.pdf_name} is being saved…", False
        if doc.print_state == "bad":
            return doc.print_problem, True
        if doc.name in self.status_of(order)["layout"]:
            return f"{doc.pdf_name} changed: press Layout done again", True
        return f"{doc.pdf_name} found: press Layout done", False

    def product_lines(self, order, doc):
        lines = [f"{doc.name}  {doc.title}"] + [f"    {line}" for line in orders.product_lines(doc)]
        lines.append(f"    {choose_template(doc, self.templates)[1]}")
        if doc.print_state == "ok":
            lines.append(f"    {doc.pdf_name}: {_count(doc.pages, 'page')}, {doc.print_paper}")
        entry = self.layout_of(order, doc)
        if entry:
            lines.append(f"    Layout done {entry.get('time', '')[:16]}: {_count(entry['sheets'], 'sheet')}"
                         + (f" ({entry['per_sheet']} per sheet)" if entry.get("per_sheet") else "")
                         + f", {receipt.short_paper_type(entry['paper_type'])}, {SIDE_NAMES[entry['sides']]}")
            job = self.document_job(order, doc)[1]
            if job:
                lines.append(f"    Tray: {job['tray']}" + (", both sides turned by hand" if job.get("hand") else ""))
        else:
            lines += [f"    {line}" for line in tray_lines(doc, self.rules)]
        return lines

    def refresh_item_bar(self):
        for w in self.item_bar.winfo_children():
            w.destroy()
        order, doc = self.selected_item()
        if doc is None or not doc.product:
            return
        cdr = doc.cdr_path()
        if cdr.is_file():
            ttk.Button(self.item_bar, text=f"Open {cdr.name}", style="Print.TButton",
                       command=lambda: self.open_path(cdr)).pack(side="left", padx=(0, 8))
        for path, title, _, warning in doc.files:
            ttk.Button(self.item_bar, text=f"Open {title}" + ("  (wrong size)" if warning else ""),
                       command=lambda p=path: self.open_path(p)).pack(side="left", padx=(0, 8))
        ttk.Button(self.item_bar, text="Open folder", command=lambda: self.open_path(doc.folder)).pack(
            side="left", padx=(0, 8))
        can = doc.print_state == "ok" and not doc.problems and not self.sent_already(order, doc)
        ttk.Button(self.item_bar, text="Layout done…", style="Print.TButton" if can else "TButton",
                   state="normal" if can else "disabled",
                   command=lambda: self.layout_dialog(order, doc)).pack(side="left", padx=(8, 0))
        if not can and not doc.problems and not self.sent_already(order, doc):
            hint = (f"Lay it out in {cdr.name}, then export {doc.pdf_name} into the same folder."
                    if doc.print_state is None else doc.print_problem or "")
            if doc.print_state is None and not cdr.is_file():
                hint = (f"No {cdr.name}: save an empty CorelDRAW file as {self.templates.name}\\blank.cdr. "
                        f"Export the laid-out sheet as {doc.pdf_name} into the item folder.")
            ttk.Label(self.item_bar, text=hint, style="Hint.TLabel").pack(side="left", padx=(12, 0))

    def open_path(self, path):
        try:
            os.startfile(path)
        except OSError as e:
            messagebox.showwarning("PrintHub", f"Could not open {path.name}.\n\n{e}", parent=self.win)

    def open_first_file(self):
        _, doc = self.selected_item()
        if doc is not None and doc.product and doc.files:
            self.open_path(doc.files[0][0])

    def layout_dialog(self, order, doc):
        """Layout done: how many sheets of print.pdf, on which paper, one or both sides."""
        st = self.status_of(order)
        before = st["layout"].get(doc.name) or {}
        quantity = doc.job.get("quantity") if orders._whole(doc.job.get("quantity")) else None
        dlg = tk.Toplevel(self.win)
        dlg.title(f"Layout done: {order.number} {doc.name}")
        dlg.transient(self.win)
        dlg.resizable(False, False)
        f = ttk.Frame(dlg, padding=16)
        f.grid()
        info = [f"{doc.title}   ·   {doc.pdf_name}: {_count(doc.pages, 'page')}, {doc.print_paper}"]
        if doc.default_sides(self.rules) != "single" and doc.pages == 1:
            info.append(f"Both sides were ordered, but {doc.pdf_name} has 1 page.")
        if doc.default_sides(self.rules) == "single" and doc.pages > 1:
            info.append(f"One side was ordered; {doc.pdf_name} has {doc.pages} pages, "
                        f"each printed on its own sheet side.")
        info.append("Printed at actual size. The copier can't print about 4 mm at the edges: keep cut marks inside.")
        ttk.Label(f, text="\n".join(info), justify="left", wraplength=520).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        per_var = tk.StringVar(value=str(before.get("per_sheet") or ""))
        sheets_var = tk.StringVar(value=str(before.get("sheets") or ""))
        # From the size table, only when nothing was saved for this item yet: what he typed wins.
        table = pieces_entry(doc, self.rules) if quantity and not before else None
        table_per = table[1].get(doc.print_paper) if table else None
        table_hint = f"from the size table ({table[0]} on {doc.print_paper}: {table_per})" if table_per else ""
        if table_per:
            per_var.set(str(table_per))
            sheets_var.set(str(math.ceil(quantity / table_per)))
        paper_var = tk.StringVar(value=before.get("paper_type") or doc.default_paper_type(self.rules) or "")
        sides_var = tk.StringVar(value=SIDE_NAMES[before.get("sides") or doc.default_sides(self.rules)])

        row = 1
        if quantity:
            ttk.Label(f, text=f"Pieces ordered: {quantity}.  Pieces per sheet:").grid(row=row, column=0, sticky="w")
            ttk.Entry(f, textvariable=per_var, width=8).grid(row=row, column=1, sticky="w", padx=6)
            if table_hint:
                hint = ttk.Label(f, text=table_hint, style="Hint.TLabel")
                hint.grid(row=row, column=2, sticky="w")
                per_var.trace_add("write", lambda *_: hint.config(
                    text=table_hint if per_var.get().strip() == str(table_per) else ""))
            row += 1
        ttk.Label(f, text=f"Sheets (copies of {doc.pdf_name}):").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=sheets_var, width=8).grid(row=row, column=1, sticky="w", padx=6)
        row += 1
        ttk.Label(f, text="Paper type:").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=paper_var, values=self.rules["paper_types"], state="readonly", width=30).grid(
            row=row, column=1, columnspan=2, sticky="w", padx=6)
        row += 1
        paper_choice = doc.job.get("options", {}).get("Paper")
        if paper_choice and not doc.default_paper_type(self.rules):
            ttk.Label(f, text=f"“{paper_choice}” isn't in product_papers in rules.json: pick the paper type.",
                      style="Hint.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
            row += 1
        ttk.Label(f, text="Sides:").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=sides_var, values=list(SIDE_NAMES.values()), state="readonly", width=30).grid(
            row=row, column=1, columnspan=2, sticky="w", padx=6)
        row += 1
        check = ttk.Label(f, text="", justify="left", wraplength=520)
        check.grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))
        row += 1
        buttons = ttk.Frame(f)
        buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ok = ttk.Button(buttons, text="Ready to print", style="Print.TButton")
        ok.pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        result = {}

        def on_per_sheet(*_):
            per = per_var.get().strip()
            if quantity and per.isdigit() and int(per) > 0:
                sheets_var.set(str(math.ceil(quantity / int(per))))  # calls update()

        def update(*_):
            result.clear()
            sides = next(k for k, v in SIDE_NAMES.items() if v == sides_var.get())
            sheets = sheets_var.get().strip()
            good = False
            if not (sheets.isdigit() and 1 <= int(sheets) <= PRODUCT_MAX_SHEETS):
                text = f"Sheets: a whole number from 1 to {PRODUCT_MAX_SHEETS}."
            elif not paper_var.get():
                text = "Pick the paper type."
            elif sides == orders.HAND and doc.pages != 2:
                text = (f"Turned by hand needs {doc.pdf_name} with 2 pages: page 1 the front, "
                        f"page 2 the back.")
            elif sides != "single" and doc.pages == 1:
                # Finding 5: the backs would come out blank.
                text = (f"Both sides, but {doc.pdf_name} has 1 page: export the back as page 2, "
                        f"or choose One side.")
            else:
                settings = doc.product_settings(int(sheets), paper_var.get(), sides, self.rules)
                job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors,
                                        PRODUCT_MAX_SHEETS)
                if job is not None and sides == orders.HAND:
                    hand_job(job)
                if job is None:
                    text = "Can't print with these settings."
                elif job["problem"]:
                    text = f"{self.printers[job['printer']]['label']}: {job['problem']}"
                else:
                    good = True
                    text = (f"{self.printers[job['printer']]['label']} · {_count(job['sheets'], 'sheet')} of paper · "
                            f"{self.settings_text(settings, job)}"
                            + (" · fronts first, then turn the stack and Print backs" if job.get("hand") else ""))
                    if job["print_copies"] > jobs.MAX_COPIES:
                        text += f"\nSent as {-(-job['print_copies'] // jobs.MAX_COPIES)} jobs of at most {jobs.MAX_COPIES}."
                    result.update(sheets=int(sheets), paper_type=paper_var.get(), sides=sides)
            check.config(text=text, foreground=theme.TEXT if good else theme.ERROR)
            ok.config(state="normal" if good else "disabled")

        def done():
            if not result:
                return
            per = per_var.get().strip()
            per = int(per) if per.isdigit() and int(per) > 0 and quantity else None
            if per and math.ceil(quantity / per) != result["sheets"]:
                per = None  # the sheets were typed by hand afterwards
            st["layout"][doc.name] = {
                "sheets": result["sheets"], "per_sheet": per,
                "paper_type": result["paper_type"], "sides": result["sides"], "stamp": doc.print_stamp,
                "pages": doc.pages, "paper": doc.print_paper,
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            self.save(order.number, f"{doc.name} layout done: {_count(result['sheets'], 'sheet')}")
            dlg.destroy()
            if self.running:
                self.laid_out.add(order.number)  # start it once it is in Orders, if its copier is free
            self.refresh()
            self.promote()
            self.start_laid_out()

        ok.config(command=done)
        per_var.trace_add("write", on_per_sheet)
        for var in (sheets_var, paper_var, sides_var):
            var.trace_add("write", update)
        update()
        theme.dark_title_bar(dlg)
        dlg.grab_set()
        dlg.focus_force()
