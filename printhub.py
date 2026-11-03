"""PrintHub view: the website's orders, each document with the copier the rules pick.

Opened with the PrintHub button in the main window. Routing and the printer
checks come from jobs.Jobs, the same code the main window uses. This stage
only shows the orders; printing them comes next (see PRINTHUB_SPEC.md).
"""
import os
import queue
import shutil
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import analyze
import jobs
import orders
import routing

SAMPLES_FOLDER = "sample_orders"
# (pdf, size, modified) -> (coverage, page colors), kept when the window is closed and opened again.
_analysis = {}


class PrintHubView:
    def __init__(self, root, rules, shared_jobs):
        self.rules = rules
        self.jobs = shared_jobs
        self.printers = rules["printers"]
        self.folder = orders.orders_dir(rules)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.orders = []  # orders.Order, oldest payment first
        self.seen = None  # the orders folder at the last load, to notice changes
        self.loading = False
        self.load_again = False
        self.results = queue.Queue()  # messages from the load thread
        self.timers = []

        self.win = tk.Toplevel(root)
        self._build()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.reload()
        self.timers.append(self.win.after(100, self.poll))
        self.timers.append(self.win.after(3000, self.watch))

    # ------------------------------------------------------------------ UI

    def _build(self):
        win = self.win
        win.title("PrintRouter: PrintHub")
        win.geometry("1150x680")
        win.minsize(900, 500)
        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we", pady=(0, 6))
        ttk.Button(top, text="Reload", command=self.reload).pack(side="left")
        ttk.Button(top, text="Open orders folder", command=lambda: os.startfile(self.folder)).pack(
            side="left", padx=(8, 0))
        if (routing.app_dir() / SAMPLES_FOLDER).is_dir():
            ttk.Button(top, text="Add sample orders", command=self.add_samples).pack(side="left", padx=(8, 0))
        self.summary = ttk.Label(top, text="", style="Summary.TLabel")
        self.summary.pack(side="right")

        box = ttk.Frame(f)
        box.grid(row=1, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        columns = ("pages", "settings", "printer", "status")
        self.tree = ttk.Treeview(box, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Order / document", anchor="w")
        self.tree.column("#0", width=260, stretch=True)
        for col, text, width, stretch in (("pages", "Pages", 60, False), ("settings", "Settings", 380, True),
                                          ("printer", "Printer", 190, False), ("status", "Status", 230, True)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="w")
        self.tree.tag_configure("order", font=("Segoe UI", 12, "bold"))
        self.tree.tag_configure("error", foreground="#B00020")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.empty_hint = ttk.Label(box, text="", style="Hint.TLabel")

        self.details = ttk.Label(f, text="", wraplength=1050, justify="left")
        self.details.grid(row=2, column=0, sticky="we", padx=6, pady=(10, 0))
        ttk.Label(f, text="Printing orders from here comes in the next stage.", style="Hint.TLabel").grid(
            row=3, column=0, sticky="w", padx=6, pady=(10, 0))

    def is_open(self):
        try:
            return bool(self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def close(self):
        for timer in self.timers:
            try:
                self.win.after_cancel(timer)
            except tk.TclError:
                pass
        self.win.destroy()

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
        """Reload by itself when orders arrive, change or go away."""
        if not self.loading and self._signature() != self.seen:
            self.reload()
        self.timers.append(self.win.after(3000, self.watch))

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
                kind, found, error = self.results.get_nowait()
                if kind == "loaded":
                    self.loading = False
                    self.orders = found
                    self.fill()
                    if error:
                        messagebox.showwarning("PrintHub", f"Could not read the orders folder.\n\n{error}",
                                               parent=self.win)
                    if self.load_again:
                        self.load_again = False
                        self.reload()
        except queue.Empty:
            pass
        self.timers.append(self.win.after(100, self.poll))

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

    # ------------------------------------------------------------ the list

    def document_job(self, doc):
        """(settings, job, problem) for one document; settings and job are None if it can't be routed."""
        if doc.problems:
            return None, None, doc.problems[0]
        settings = doc.settings()
        job = self.jobs.job_for(doc.title, settings, doc.pages, doc.coverage, doc.page_colors)
        if job is None:
            return settings, None, "Can't print with these settings"
        return settings, job, job["problem"]

    def fill(self):
        """Show the orders, keeping the selection."""
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        attention = 0
        for order in self.orders:
            oid = f"order:{order.number}"
            used, bad = [], bool(order.problems)  # printer ids, short enough for the order row
            self.tree.insert("", "end", iid=oid, open=True, text=order.number)
            for doc in order.documents:
                settings, job, problem = self.document_job(doc)
                bad = bad or bool(problem)
                label = self.printers[job["printer"]]["label"] if job else ""
                if job and job["printer"] not in used:
                    used.append(job["printer"])
                self.tree.insert(oid, "end", iid=f"{oid}/{doc.name}", text=f"{doc.name}   {doc.title}",
                                 values=(doc.pages or "", self.jobs.settings_text(settings, job) if settings else "",
                                         label, problem or "OK"),
                                 tags=("error",) if problem else ())
            attention += bad
            when = order.paid_at.strftime("%d/%m %H:%M") if order.paid_at else "?"
            steps = " › ".join(map(str, order.steps))
            self.tree.item(oid, values=("", f"{order.delivery} · {steps} · paid {when}", " + ".join(used),
                                        "Needs attention" if bad else "Ready to print"),
                           tags=("order", "error") if bad else ("order",))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        if self.orders:
            self.empty_hint.place_forget()
            text = f"{len(self.orders)} order{'s' if len(self.orders) != 1 else ''}"
            if attention:
                text += f" · {attention} need{'s' if attention == 1 else ''} attention"
        else:
            self.empty_hint.config(text=f"No orders yet. Orders appear here when they arrive in\n{self.folder}")
            self.empty_hint.place(relx=0.5, rely=0.5, anchor="center")
            text = "No orders"
        self.summary.config(text=text)
        self.show_details()

    def show_details(self):
        """Note, problems and sheets per copier for the selected order."""
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
        sheets = {}
        for doc in order.documents:
            _, job, problem = self.document_job(doc)
            if job and not problem:
                label = self.printers[job["printer"]]["label"]
                sheets[label] = sheets.get(label, 0) + job["sheets"]
        if sheets:
            lines.append("Sheets: " + " · ".join(f"{label}: {n}" for label, n in sheets.items()))
        problems = order.problems + [f"{d.name} ({d.title}): {p}" for d in order.documents
                                     for p in [self.document_job(d)[2]] if p]
        if problems:
            lines.append("Needs attention:")
            lines += [f"    • {p}" for p in problems]
        self.details.config(text="\n".join(lines))
