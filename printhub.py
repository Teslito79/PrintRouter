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
"""
import datetime
import json
import os
import queue
import shutil
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import analyze
import jobs
import orders
import routing

SAMPLES_FOLDER = "sample_orders"
WORK_DIR = Path(tempfile.gettempdir()) / "PrintRouter" / "printhub"
STEP_NAMES = {"PRINT": "Printing", "LAMINATE": "Laminating", "SPIRAL": "Spiral", "CUTTING": "Cutting"}
BUSY = ("sending", "sent", "failed", "interrupted")  # part states that keep a copier taken
# (pdf, size, modified) -> (coverage, page colors), kept when the window is closed and opened again.
_analysis = {}


def _count(n, singular, plural=None):
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


class PrintHubView:
    def __init__(self, root, rules, shared_jobs):
        self.rules = rules
        self.jobs = shared_jobs
        self.printers = rules["printers"]
        self.folder = orders.orders_dir(rules)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.orders = []  # orders.Order, oldest payment first
        # Order number -> progress, as in status.json: {"step": index into the order's steps,
        # "parts": {printer: {"documents", "state", "sent", ...}}, "history": [...]}
        self.status = {}
        self.progress = {}  # (order, printer) -> (document n, of total) while sending
        self.running = False  # Start printing orders pressed (and not stopped)
        self.seen = None  # the orders folder at the last load, to notice changes
        self.loading = False
        self.load_again = False
        self.results = queue.Queue()  # messages from the threads
        self.to_send = queue.Queue()  # parts waiting to be sent, one at a time

        self.win = tk.Toplevel(root)
        self._build()
        # Closing only hides the window: sending and the order progress carry on.
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)
        threading.Thread(target=self._send_worker, daemon=True).start()
        self.reload()
        self.win.after(100, self.poll)
        self.win.after(3000, self.watch)

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
        ttk.Button(top, text="Reload", command=self.reload).pack(side="left")
        ttk.Button(top, text="Open orders folder", command=lambda: os.startfile(self.folder)).pack(
            side="left", padx=(8, 0))
        if (routing.app_dir() / SAMPLES_FOLDER).is_dir():
            ttk.Button(top, text="Add sample orders", command=self.add_samples).pack(side="left", padx=(8, 0))
        self.summary = ttk.Label(top, text="", style="Summary.TLabel")
        self.summary.pack(side="right")

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
        self.tree.tag_configure("error", foreground="#B00020")
        self.tree.tag_configure("done", foreground="#777777")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.empty_hint = ttk.Label(box, text="", style="Hint.TLabel")

        # Orders whose pages are all collected, each with the button for its next step.
        self.steps_box = ttk.LabelFrame(f, text="Next steps", padding=8, style="Section.TLabelframe")
        self.steps_box.grid(row=4, column=0, sticky="we", pady=(10, 0))
        self.details = ttk.Label(f, text="", wraplength=1100, justify="left")
        self.details.grid(row=5, column=0, sticky="we", padx=6, pady=(10, 0))
        self.refresh_run_label()

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
        """Order folders and when their order.json last changed."""
        found = []
        try:
            for sub in self.folder.iterdir():
                try:
                    found.append((sub.name, (sub / "order.json").stat().st_mtime_ns))
                except OSError:
                    pass  # no order.json yet: still downloading
        except OSError:
            pass
        return sorted(found)

    def watch(self):
        """Reload by itself when orders arrive, change or go away (new orders never start printing by themselves)."""
        if not self.loading and self._signature() != self.seen:
            self.reload()
        self.win.after(3000, self.watch)

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
                found = orders.load_orders(self.folder, self.rules)
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
        elif kind == "part_sent":
            part["state"] = "sent"
            self.progress.pop((number, printer), None)
            self.save(number, f"all sent to {printer}")
        elif kind == "failed":
            part.update(state="failed", error=msg[3])
            self.progress.pop((number, printer), None)
            self.save(number, f"sending to {printer} failed: {msg[3]}")
        self.refresh()

    def add_samples(self):
        """Copy the sample orders that aren't there yet into the orders folder, for testing."""
        added = []
        try:
            for src in sorted((routing.app_dir() / SAMPLES_FOLDER).iterdir()):
                dest = self.folder / src.name
                if not src.is_dir() or dest.exists():
                    continue
                # Copy under a hidden name, then rename, so a half-copied order is never read.
                tmp = self.folder / f".{src.name}.copying"
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.copytree(src, tmp)
                tmp.rename(dest)
                added.append(src.name)
        except OSError as e:
            messagebox.showwarning("PrintHub", f"Could not copy the sample orders.\n\n{e}", parent=self.win)
        if not added:
            messagebox.showinfo("PrintHub", "The sample orders are already in the orders folder.", parent=self.win)
        self.reload()

    # ------------------------------------------------------------- progress

    def status_of(self, order):
        """The order's progress, read from its status.json the first time it is seen."""
        st = self.status.get(order.number)
        if st is None:
            st = {"step": 0, "parts": {}, "history": []}
            try:
                data = json.loads((order.folder / "status.json").read_text(encoding="utf-8"))
                st.update(step=int(data["step"]), parts=dict(data["parts"]), history=list(data["history"]))
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
        path = self.folder / number / "status.json"
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({k: st[k] for k in ("step", "parts", "history")}, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            messagebox.showwarning("PrintHub", f"The progress of order {number} could not be saved; it may be "
                                               f"lost if the app closes.\n\n{e}", parent=self.win)

    def document_job(self, doc, printer=None):
        """(settings, job, problem) for one document; settings and job are None if it can't be routed.

        printer: the copier this document was given when its order started, if the rules
        would now pick another one (e.g. rules.json changed meanwhile)."""
        if doc.problems:
            return None, None, doc.problems[0]
        settings = doc.settings()
        job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors)
        if job and printer and job["printer"] != printer:
            settings["printer"] = printer
            job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors)
        if job is None:
            return settings, None, "Can't print with these settings"
        return settings, job, job["problem"]

    def problems_of(self, order):
        problems = list(order.problems)
        st = self.status_of(order)
        if "broken" in st:
            problems.append(st["broken"])
        for doc in order.documents:
            problem = self.document_job(doc)[2]
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
            job = self.document_job(doc)[1]
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
                and self.part_state(o, printer) == "waiting" and not self.problems_of(o)]

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

    def start_next(self, printer):
        """Send the next waiting order to this copier, if it is free."""
        if not self.running or self.busy_with(printer):
            return
        waiting = self.queue(printer)
        if not waiting:
            return
        order = waiting[0]
        docs = {d.name: d for d in order.documents}
        part_jobs = [self.document_job(docs[name], printer)[1] for name in self.parts_of(order)[printer]
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
        tasks = []
        for name in part["documents"]:
            if name in part["sent"]:
                continue
            job = self.document_job(docs[name], printer)[1] if name in docs else None
            if job is None or job["problem"]:
                part.update(state="failed", error=f"{name}: can't be printed any more")
                self.save(order.number, f"{name} can't be printed on {printer}")
                return
            # The order number in the name shows in the copier's queue and in print_log.csv.
            job["file_name"] = f"{order.number} {name} {docs[name].title}"
            tasks.append((name, job, docs[name].pdf, WORK_DIR / order.number / name))
        part.update(state="sending", error=None)
        self.progress[(order.number, printer)] = (0, len(tasks))
        self.save(order.number, f"sending to {printer}")
        self.to_send.put((order.number, printer, tasks))

    def _send_worker(self):
        """Send the parts one after another; the copiers then print them at the same time."""
        while True:
            number, printer, tasks = self.to_send.get()
            for n, (name, job, pdf, work_dir) in enumerate(tasks, start=1):
                self.results.put(("progress", number, printer, (n, len(tasks))))
                try:
                    work_dir.mkdir(parents=True, exist_ok=True)
                    self.jobs.print_one(work_dir, job, pdf, pdf, job["paper"], None)
                except Exception as e:
                    self.results.put(("failed", number, printer, f"{name}: {e}"))
                    break
                self.jobs.log(job, self.printers[printer]["label"])
                self.results.put(("doc_sent", number, printer, name))
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
        order = self.busy_with(printer)
        if order:
            self.send_part(order, printer)
            self.refresh()

    def it_printed(self, printer):
        """After the app closed mid-send: staff checked and everything came out."""
        order = self.busy_with(printer)
        if order is None:
            return
        part = self.status_of(order)["parts"][printer]
        part.update(state="sent", sent=list(part["documents"]))
        self.save(order.number, f"checked by hand: all printed on {printer}")
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
        self.refresh()

    # ------------------------------------------------------------ the views

    def refresh(self):
        self.fill()
        self.refresh_printers()
        self.refresh_steps()

    def order_text(self, order):
        """The order's status column."""
        if self.problems_of(order):
            return "Needs attention"
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
                settings, job, problem = self.document_job(doc, printer)
                label = self.printers[job["printer"]]["label"] if job else ""
                self.tree.insert(oid, "end", iid=f"{oid}/{doc.name}", text=f"{doc.name}   {doc.title}",
                                 values=(doc.pages or "", self.jobs.settings_text(settings, job) if settings else "",
                                         label, problem or "OK"),
                                 tags=("error",) if problem else ())
            attention += bad
            waiting += not bad and not ready
            when = order.paid_at.strftime("%d/%m %H:%M") if order.paid_at else "?"
            steps = " › ".join(map(str, order.steps))
            self.tree.item(oid, values=("", f"{order.delivery} · {steps} · paid {when}", " + ".join(parts),
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
            self.empty_hint.config(text=f"No orders yet. Orders appear here when they arrive in\n{self.folder}")
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
        if not rows:
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

    def show_details(self):
        """Note, problems, sheets per copier and progress of the selected order."""
        selected = self.tree.selection()
        number = selected[0].split("/")[0].removeprefix("order:") if selected else None
        order = next((o for o in self.orders if o.number == number), None)
        if order is None:
            self.details.config(text="Click an order to see its details.")
            return
        lines = [f"{order.number} · paid {order.paid_at:%Y-%m-%d %H:%M} · {order.delivery}"
                 if order.paid_at else order.number]
        if order.note:
            lines.append(f"Note: {order.note}")
        docs = {d.name: d for d in order.documents}
        sheets = []
        for pid, names in self.parts_of(order).items():
            jobs_ = [self.document_job(docs[n], pid)[1] for n in names if n in docs]
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
        self.details.config(text="\n".join(lines))
