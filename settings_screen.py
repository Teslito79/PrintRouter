"""Settings (2026-11-18_02, Tesla: "a configuration page so people can connect there own printer to the app"):
the sixth menu button, behind the same password as Prices.

Any shop running ORCA sets up its own printers here without editing files:
- Printers: the Windows printer (picked from the printers installed on this PC), the name in ORCA, colour or black
  and white only, the largest paper (A4 / A3), the heaviest paper (gsm), the network address (the Data screen and
  the copy counter) and whether the Copy counter counts copies made at it. Print test page, Check address.
- Which printer does what: three rows (black and white; colour documents on plain paper; everything else in
  colour), each with an "If busy" printer or Wait. Rules that can't be shown that way stay as they are.
- The receipt printer (or None), prices on paper, the walk-in price list, the copy counter's numbers.

Save writes only what differs from rules.json (the shipped default, never written) into settings.json next to it
(local, gitignored; routing.load_rules lays it over rules.json). The menu then applies it at once. Reset deletes it.
Settings only reads the list of printers: it never changes a driver, port, preference or the default printer.
"""
import copy
import datetime
import os
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import copy_counter
import costs
import routing
import theme
import toners
import walkin_prices
from walkin_screens import FONT, Screen

COLOURS = {"color": "Colour", "bw": "Black and white only"}
SIZES = ("A4", "A3")
WAIT = "Wait"
NONE = "None"
NOT_FOUND = "Not found on this PC"


def key_for(name, taken):
    """A new printer's key: the letters and digits of its name, made unique ("IM C4510" -> "IMC4510")."""
    base = re.sub(r"[^A-Za-z0-9]", "", name) or "Printer"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}{n}", n + 1
    return key


def colour_of(p):
    return "bw" if p.get("color") == "bw" else "color"


def largest_of(p):
    return "A4" if p.get("max_paper") == "A4" else "A3"


def counts_copies(p):
    return p.get("copy_counter", True)


# ------------------------------------------------------------------ the test page

def test_page_pdf(path, label, when=None):
    """One plain A4 page: "ORCA test page", the printer's name in ORCA, the date and time (150 dpi, black)."""
    from PIL import Image, ImageDraw
    import receipt
    when = when or datetime.datetime.now()
    img = Image.new("L", (1240, 1754), 255)
    d = ImageDraw.Draw(img)
    y = 260
    for text, font in (("ORCA test page", receipt._font(90, True)), (label, receipt._font(60)),
                       (when.strftime("%d/%m/%Y  %H:%M"), receipt._font(48))):
        d.text(((1240 - d.textlength(text, font=font)) / 2, y), text, font=font, fill=0)
        y += font.size + 60
    img.save(path, "PDF", resolution=150)
    return path


def print_test_page(queue, label, path):
    """The test page through the normal print queue: A4, black and white, one side, one copy; per-job driver
    settings only (the printer's own settings are never changed)."""
    import driverprint
    test_page_pdf(path, label)
    devmode = driverprint.build_devmode(queue, "A4", False, False, 1)
    driverprint.print_pdf(path, queue, devmode, "ORCA test page")
    return path


# ------------------------------------------------------------------ the screen

class SettingsScreen(Screen):
    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Settings", on_back, size="1240x900")
        self.shipped = routing.shipped_rules()
        self.installed = routing.installed_printers()
        rules = ctx.rules
        typed = toners.load_settings()["addresses"]
        self.printers = copy.deepcopy(rules["printers"])
        for pid, p in self.printers.items():  # an address typed in the Data screen shows here (it moves here)
            if not p.get("address") and typed.get(pid):
                p["address"] = typed[pid]
        self.addresses_before = {pid: p.get("address") for pid, p in self.printers.items()}
        self.rows = routing.rows_of(rules)  # None: custom routing from rules.json, left alone
        self.custom_rules = None if self.rows else copy.deepcopy(rules.get("rules"))
        self.fallback = rules.get("fallback_printer")
        self.receipt = rules.get("receipt_printer") or None
        self.prices_on = tk.BooleanVar(value=rules.get("walkin_paper_prices") is True)
        self.a3 = tk.StringVar(value=str(rules.get("copy_counter_a3_counts_as", 2)))
        self.poll = tk.StringVar(value=str(rules.get("copy_counter_poll_seconds", 5)))
        self.checks = {}  # printer -> Check address result
        self.dirty = False
        for var in (self.prices_on, self.a3, self.poll):
            var.trace_add("write", lambda *_: self.changed())
        self.scroll = costs.ScrollFrame(self.frame)
        self.scroll.grid(row=2, column=0, sticky="nsew", pady=(10, 0))
        self.frame.rowconfigure(2, weight=1)
        bottom = ttk.Frame(self.frame)
        bottom.grid(row=3, column=0, sticky="we", pady=(10, 0))
        ttk.Button(bottom, text="Save", style="Print.TButton", command=self.save).pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.back).pack(side="left", padx=(10, 0))
        self.message = ttk.Label(bottom, text="", style="Hint.TLabel")
        self.message.pack(side="left", padx=(16, 0))
        ttk.Button(bottom, text="Reset to the shipped settings", command=self.reset).pack(side="right")
        self.fill()
        self.ready()

    # -------------------------------------------------------------- helpers
    def changed(self):
        self.dirty = True
        try:
            self.message.config(text="Not saved yet")
        except (tk.TclError, AttributeError):
            pass

    def label(self, pid):
        return self.printers.get(pid, {}).get("label", pid)

    def in_background(self, work, done):
        """work() on a thread (reading an address, sending a page can take a while); done(result) back on the Tk
        thread, which asks for it (Tk must never be touched from the thread)."""
        box = {}

        def run():
            try:
                box["value"] = work()
            except Exception as e:
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

    def found(self, pid):
        return self.installed is None or self.printers[pid].get("queue") in self.installed

    def section(self, row, title):
        box = ttk.LabelFrame(self.scroll.inner, text=title, padding=12, style="Section.TLabelframe")
        box.grid(row=row, column=0, sticky="we", pady=(0, 12))
        box.columnconfigure(0, weight=1)
        return box

    def fill(self):
        """(Re)build every part from the edited values."""
        top = self.scroll.canvas.yview()[0] if self.scroll.inner.winfo_children() else 0
        for w in self.scroll.inner.winfo_children():
            w.destroy()
        self.scroll.inner.columnconfigure(0, weight=1)
        self.fill_printers(self.section(0, "Printers"))
        self.fill_routing(self.section(1, "Which printer does what"))
        self.fill_receipt(self.section(2, "Receipt printer"))
        self.fill_walkin(self.section(3, "Walk-in"))
        for box in self.scroll.inner.winfo_children():
            theme.on_surface(box)
        self.win.update_idletasks()
        self.scroll.canvas.yview_moveto(top)

    # -------------------------------------------------------------- printers
    def fill_printers(self, box):
        head = ("Name in ORCA", "Windows printer", "Colour", "Largest", "Heaviest", "Network address", "Copy counter")
        table = ttk.Frame(box)
        table.grid(row=0, column=0, sticky="we")
        for c, text in enumerate(head):
            ttk.Label(table, text=text, style="Head.TLabel").grid(row=0, column=c, sticky="w", padx=(0, 16))
        for r, (pid, p) in enumerate(self.printers.items(), start=1):
            queue = p.get("queue", "")
            values = (p.get("label", pid), queue if self.found(pid) else f"{queue}: {NOT_FOUND}",
                      COLOURS[colour_of(p)], largest_of(p), f"{p['max_gsm']} gsm" if p.get("max_gsm") else "No limit",
                      p.get("address") or "-", "Yes" if counts_copies(p) else "No")
            for c, text in enumerate(values):
                style = "Bad.TLabel" if c == 1 and not self.found(pid) else "TLabel"
                ttk.Label(table, text=text, style=style).grid(row=2 * r - 1, column=c, sticky="w", padx=(0, 16),
                                                              pady=(8, 0))
            buttons = ttk.Frame(table)
            buttons.grid(row=2 * r, column=0, columnspan=len(head), sticky="w", pady=(2, 0))
            for text, command in (("Edit…", lambda k=pid: self.edit(k)), ("Remove", lambda k=pid: self.remove(k)),
                                  ("Print test page", lambda k=pid: self.test_page(k)),
                                  ("Check address", lambda k=pid: self.check_address(k))):
                ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 8))
            if pid in self.checks:
                ttk.Label(buttons, text=self.checks[pid], style="Hint.TLabel").pack(side="left", padx=(8, 0))
        ttk.Button(box, text="Add printer…", command=self.add).grid(row=1, column=0, sticky="w", pady=(12, 0))
        if self.installed is not None and not any(self.found(pid) for pid in self.printers):
            ttk.Label(box, text="None of these printers is installed on this PC: add your own with Add printer.",
                      style="Warn.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))

    def add(self):
        PrinterDialog(self, None)

    def edit(self, pid):
        PrinterDialog(self, pid)

    def saved_printer(self, pid, values):
        """PrinterDialog's OK: a new printer (pid None) or changes to one."""
        if pid is None:
            pid = key_for(values["label"], set(self.printers))
            self.printers[pid] = {}
            if self.rows is not None and len(self.printers) == 1:
                self.rows = {key: (pid, None) for key, _ in routing.ROWS}
        p = self.printers[pid]
        p.update(queue=values["queue"], label=values["label"], color=values["color"], max_paper=values["max_paper"],
                 copy_counter=values["copy_counter"])
        for key in ("max_gsm", "address", "paper_map", "tray_map"):
            if values.get(key):
                p[key] = values[key]
            else:
                p.pop(key, None)
        self.checks.pop(pid, None)
        self.changed()
        self.fill()

    def blockers(self, pid):
        """What stops a printer being removed: an order sending or waiting on it, a copy count running."""
        out = []
        run = getattr(self.ctx, "print_queue", None)
        if run is not None:
            if run.copiers.get(pid, {}).get("state", "idle") != "idle":
                out.append("the walk-in queue is printing on it")
            waiting = [n for batch in run.batches(pid) for n in batch]
            if waiting:
                out.append("walk-in order" + ("s " if len(waiting) > 1 else " ")
                           + ", ".join(f"#{n}" for n in waiting) + " waiting on it")
        ph = getattr(self.ctx, "printhub", None)
        if ph is not None:
            busy = ph.busy_with(pid)
            if busy is not None:
                out.append(f"PrintHub order {busy.number} is printing on it")
            waiting = ph.queue(pid)
            if waiting:
                out.append("PrintHub order" + ("s " if len(waiting) > 1 else " ")
                           + ", ".join(o.number for o in waiting) + " waiting on it")
        manager = getattr(self.ctx, "copy_counter", None)
        if manager is not None and pid in manager.counters:
            out.append("the Copy counter is counting on it")
        if self.rows is None and any(pid in (r.get("printer"), r.get("if_busy")) for r in self.custom_rules or []):
            out.append("the custom routing from rules.json uses it")
        return out

    def remove(self, pid):
        why = self.blockers(pid)
        if why:
            messagebox.showwarning(parent=self.win, title="Settings",
                                   message=f"{self.label(pid)} can't be removed now: " + "; ".join(why) + ".")
            return
        if len(self.printers) == 1:
            messagebox.showwarning(parent=self.win, title="Settings", message="ORCA needs at least one printer.")
            return
        if not messagebox.askyesno(parent=self.win, title="Settings", message=f"Remove {self.label(pid)} from ORCA?"):
            return
        del self.printers[pid]
        first = next(iter(self.printers))
        if self.rows is not None:
            self.rows = {key: (first if p == pid else p, None if b == pid else b) for key, (p, b) in self.rows.items()}
        if self.fallback == pid:
            self.fallback = first
        self.changed()
        self.fill()

    def test_page(self, pid):
        p = self.printers[pid]
        if not self.found(pid):
            messagebox.showwarning(parent=self.win, title="Settings",
                                   message=f"{p.get('queue')} is not installed on this PC.")
            return
        if not messagebox.askyesno(parent=self.win, title="Settings",
                                   message=f"Print one test page on {p.get('label', pid)}?"):
            return
        import walkin_print
        path = walkin_print.WORK_DIR / f"test_page_{pid}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.message.config(text=f"Sending the test page to {p.get('label', pid)}…")

        def done(result):
            self.message.config(text=f"The test page didn't print: {result}" if isinstance(result, Exception)
                                else f"Test page sent to {p.get('label', pid)}.")

        self.in_background(lambda: print_test_page(p["queue"], p.get("label", pid), path), done)

    def check_address(self, pid):
        """Read the address once (copy_counter.read / toners) and say what it gives."""
        address, _ = toners.copier_address(self.printers, pid)
        self.checks[pid] = f"Checking {address or 'no address'}…"
        self.fill()

        def work():
            if not address:
                return "No address: type one with Edit"
            return f"{address}: {copy_counter.check_text(address)}"

        def done(text):
            self.checks[pid] = f"Couldn't check: {text}" if isinstance(text, Exception) else text
            self.fill()

        self.in_background(work, done)

    # -------------------------------------------------------------- routing
    def choices(self):
        return {self.label(pid): pid for pid in self.printers}

    def fill_routing(self, box):
        if self.rows is None:
            ttk.Label(box, text="Custom routing from rules.json", style="Head.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(box, text="These rules can't be shown as the three rows below, so they are left as they are.",
                      style="Hint.TLabel").grid(row=1, column=0, sticky="w")
            return
        one = len(self.printers) == 1
        names = self.choices()
        self.route_vars = {}
        grid = ttk.Frame(box)
        grid.grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="Printer", style="Head.TLabel").grid(row=0, column=1, sticky="w")
        if not one:
            ttk.Label(grid, text="If busy", style="Head.TLabel").grid(row=0, column=2, sticky="w", padx=(16, 0))
        for r, (key, title) in enumerate(routing.ROWS, start=1):
            printer, if_busy = self.rows[key]
            ttk.Label(grid, text=title).grid(row=r, column=0, sticky="w", padx=(0, 16), pady=4)
            pvar = tk.StringVar(value=self.label(printer))
            cb = ttk.Combobox(grid, textvariable=pvar, values=list(names), state="readonly", width=24, font=FONT)
            cb.grid(row=r, column=1, sticky="w", pady=4)
            bvar = tk.StringVar(value=self.label(if_busy) if if_busy else WAIT)
            self.route_vars[key] = (pvar, bvar)
            cb.bind("<<ComboboxSelected>>", lambda _: self.route_changed())
            if not one:
                bb = ttk.Combobox(grid, textvariable=bvar, values=[WAIT] + list(names), state="readonly", width=24,
                                  font=FONT)
                bb.grid(row=r, column=2, sticky="w", padx=(16, 0), pady=4)
                bb.bind("<<ComboboxSelected>>", lambda _: self.route_changed())
        ttk.Label(box, text="A job on paper heavier than a printer takes, A3 on an A4-only printer, or colour on a black "
                            "and white printer goes to the next printer that can take it. A printer that isn't "
                            "installed here is skipped like a busy one.", style="Hint.TLabel", wraplength=1000,
                  justify="left").grid(row=1, column=0, sticky="w", pady=(8, 0))
        problems = self.routing_problems()
        if problems:
            ttk.Label(box, text="\n".join(problems), style="Warn.TLabel", justify="left").grid(
                row=2, column=0, sticky="w", pady=(6, 0))

    def route_changed(self):
        names = self.choices()
        for key, (pvar, bvar) in self.route_vars.items():
            busy = bvar.get()
            self.rows[key] = (names.get(pvar.get()), None if busy == WAIT else names.get(busy))
        self.changed()
        self.fill()

    def routing_problems(self):
        """What can't work in the rows (shown in yellow; Save refuses the first two)."""
        out = []
        if self.rows is None:
            return out
        for key, title in routing.ROWS:
            printer, if_busy = self.rows[key]
            if key != "bw":
                for pid in (printer, if_busy):
                    if pid and colour_of(self.printers.get(pid, {})) == "bw":
                        out.append(f"{title}: {self.label(pid)} prints black and white only.")
        if all(largest_of(p) == "A4" for p in self.printers.values()):
            out.append("No printer takes A3: A3 jobs can't be printed.")
        if all(colour_of(p) == "bw" for p in self.printers.values()):
            out.append("No printer prints colour: colour jobs can't be printed.")
        return out

    # -------------------------------------------------------------- receipt printer and walk-in
    def fill_receipt(self, box):
        installed = list(self.installed or [])
        if self.receipt and self.receipt not in installed:
            installed.append(self.receipt)
        var = tk.StringVar(value=self.receipt or NONE)
        cb = ttk.Combobox(box, textvariable=var, values=[NONE] + installed, state="readonly", width=40, font=FONT)
        cb.grid(row=0, column=0, sticky="w")

        def picked(_):
            self.receipt = None if var.get() == NONE else var.get()
            self.changed()
            self.fill()

        cb.bind("<<ComboboxSelected>>", picked)
        text = ("None: the Copy counter's Print receipt button is hidden; Done still works." if not self.receipt else
                f"{NOT_FOUND}." if self.installed is not None and self.receipt not in self.installed else
                "The Copy counter's receipts print here.")
        ttk.Label(box, text=text, style="Bad.TLabel" if text == f"{NOT_FOUND}." else "Hint.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0))

    def fill_walkin(self, box):
        ttk.Checkbutton(box, text="Show the total on cover sheets and receipts", variable=self.prices_on).grid(
            row=0, column=0, sticky="w")
        ttk.Label(box, text="Price list", style="Head.TLabel").grid(row=1, column=0, sticky="w", pady=(12, 0))
        path = routing.app_dir() / walkin_prices.FILE
        ttk.Label(box, text=str(path)).grid(row=2, column=0, sticky="w")
        pl = walkin_prices.current()
        if pl.trial:
            ttk.Label(box, text=walkin_prices.TRIAL, style="Warn.TLabel").grid(row=3, column=0, sticky="w")
        elif pl.warnings:
            ttk.Label(box, text=pl.warnings[0], style="Warn.TLabel", wraplength=1000, justify="left").grid(
                row=3, column=0, sticky="w")
        ttk.Button(box, text="Open price list", command=lambda: self.open_price_list(path)).grid(
            row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Label(box, text="Copy counter", style="Head.TLabel").grid(row=5, column=0, sticky="w", pady=(12, 0))
        f = ttk.Frame(box)
        f.grid(row=6, column=0, sticky="w")
        ttk.Label(f, text="One A3 copy adds to the total counter:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(f, textvariable=self.a3, width=6, font=FONT).grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(f, text="Read every").grid(row=1, column=0, sticky="w", pady=3)
        g = ttk.Frame(f)
        g.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Entry(g, textvariable=self.poll, width=6, font=FONT).pack(side="left")
        ttk.Label(g, text="seconds").pack(side="left", padx=(6, 0))

    def open_price_list(self, path):
        try:
            os.startfile(path)  # the default program (Excel); ORCA itself never writes it
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="Settings", message=f"Could not open it.\n\n{e}")

    # -------------------------------------------------------------- saving
    def wanted(self):
        """The settings as edited, as rules (raises ValueError with what's wrong)."""
        rules = copy.deepcopy(self.ctx.rules)
        if not self.printers:
            raise ValueError("ORCA needs at least one printer.")
        rules["printers"] = copy.deepcopy(self.printers)
        if self.rows is not None:
            if len(self.printers) == 1:
                only = next(iter(self.printers))
                self.rows = {key: (only, None) for key, _ in routing.ROWS}
            bad = [p for p in self.routing_problems() if p.endswith("prints black and white only.")]
            if bad:
                raise ValueError(bad[0])
            rules["rules"] = routing.rules_from_rows(rules, self.rows)
            rules["fallback_printer"] = self.rows["bw"][0]
        else:
            rules["rules"] = copy.deepcopy(self.custom_rules)
            rules["fallback_printer"] = self.fallback if self.fallback in self.printers else next(iter(self.printers))
        rules["receipt_printer"] = self.receipt
        rules["walkin_paper_prices"] = bool(self.prices_on.get())
        for var, key, what in ((self.a3, "copy_counter_a3_counts_as", "One A3 copy adds to the total counter"),
                               (self.poll, "copy_counter_poll_seconds", "Read every … seconds")):
            text = var.get().strip()
            if not text.isdigit() or int(text) < 1:
                raise ValueError(f"{what}: a whole number of 1 or more.")
            rules[key] = int(text)
        return rules

    def save(self):
        try:
            wanted = self.wanted()
            routing.save_local(routing.local_diff(self.shipped, wanted))
        except ValueError as e:
            messagebox.showwarning(parent=self.win, title="Settings", message=str(e))
            return
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="Settings", message=f"Could not save.\n\n{e}")
            return
        self.dirty = False
        self.apply()
        self.message.config(text="Saved: in use now for new jobs.")

    def apply(self):
        apply = getattr(self.ctx, "apply_settings", None)
        if apply:
            apply()
        else:  # no menu (tests): the rules in force, changed in place
            new = routing.load_rules()
            self.ctx.rules["printers"].clear()
            self.ctx.rules["printers"].update(new.pop("printers"))
            self.ctx.rules.update(new)

    def reset(self):
        if not messagebox.askyesno(parent=self.win, title="Settings",
                                   message="Go back to the shipped settings? This deletes this PC's settings.json."):
            return
        routing.reset_local()
        self.apply()
        self.dirty = False
        self.win.destroy()
        SettingsScreen(self.ctx, self.on_back)  # shown again from the shipped settings

    def back(self):
        if self.dirty and not messagebox.askyesno(parent=self.win, title="Settings",
                                                  message="Throw away the changes?"):
            return
        super().back()


class PrinterDialog:
    """Add printer / Edit: the Windows printer (installed on this PC), name, colour, largest and heaviest paper,
    network address, copy counter."""

    def __init__(self, screen, pid):
        self.screen, self.pid = screen, pid
        p = screen.printers.get(pid, {}) if pid else {}
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Edit printer" if pid else "Add printer")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        installed = list(screen.installed or [])
        if p.get("queue") and p["queue"] not in installed:
            installed.append(p["queue"])
        self.vars = {"queue": tk.StringVar(value=p.get("queue", "")), "label": tk.StringVar(value=p.get("label", "")),
                     "color": tk.StringVar(value=COLOURS[colour_of(p)]),
                     "max_paper": tk.StringVar(value=largest_of(p)),
                     "max_gsm": tk.StringVar(value=str(p.get("max_gsm") or "")),
                     "address": tk.StringVar(value=p.get("address", "")),
                     "copy_counter": tk.BooleanVar(value=counts_copies(p) if pid else False)}
        r = 0

        def row(text, widget):
            nonlocal r
            ttk.Label(f, text=text).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            widget.grid(row=r, column=1, sticky="w", pady=4)
            r += 1

        queue_box = ttk.Combobox(f, textvariable=self.vars["queue"], values=installed, state="readonly", width=36,
                                 font=FONT)
        row("Windows printer:", queue_box)
        queue_box.bind("<<ComboboxSelected>>", lambda _: self.fill_maps(suggest=True))
        row("Name in ORCA:", ttk.Entry(f, textvariable=self.vars["label"], width=24, font=FONT))
        c = ttk.Frame(f)
        for value in COLOURS.values():
            ttk.Radiobutton(c, text=value, value=value, variable=self.vars["color"]).pack(side="left", padx=(0, 14))
        row("Colour:", c)
        s = ttk.Frame(f)
        for value in SIZES:
            ttk.Radiobutton(s, text=value, value=value, variable=self.vars["max_paper"]).pack(side="left", padx=(0, 14))
        row("Largest paper:", s)
        g = ttk.Frame(f)
        ttk.Entry(g, textvariable=self.vars["max_gsm"], width=6, font=FONT).pack(side="left")
        ttk.Label(g, text="gsm (empty: no limit)", style="Hint.TLabel").pack(side="left", padx=(6, 0))
        row("Heaviest paper:", g)
        row("Network address:", ttk.Entry(f, textvariable=self.vars["address"], width=24, font=FONT))
        ttk.Label(f, text="Optional: an IP address or name. The Data screen and the Copy counter use it.",
                  style="Hint.TLabel").grid(row=r, column=1, sticky="w")
        r += 1
        self.counter_box = ttk.Checkbutton(f, text="Count copies made at this printer",
                                           variable=self.vars["copy_counter"])
        row("Copy counter:", self.counter_box)
        if not pid:  # on by default for a printer with a network address
            self.vars["address"].trace_add("write", lambda *_: self.vars["copy_counter"].set(
                bool(self.vars["address"].get().strip())))
        # Paper and trays (2026-11-18_03): ORCA's names translated to this driver's, for printers of other brands.
        self.maps_box = ttk.LabelFrame(f, text="Paper and trays", padding=8, style="Section.TLabelframe")
        self.maps_box.grid(row=r, column=0, columnspan=2, sticky="we", pady=(10, 0))
        r += 1
        self.map_vars = None  # {"paper": {ORCA name: StringVar}, "tray": {...}} while a translation is shown
        self.saved_maps = {"paper": p.get("paper_map"), "tray": p.get("tray_map")} if p.get("paper_map") else None
        self.saved_queue = p.get("queue")
        self.error = ttk.Label(f, text="", style="Bad.TLabel", wraplength=480, justify="left")
        self.error.grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1
        b = ttk.Frame(f)
        b.grid(row=r, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(b, text="OK", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        self.fill_maps(suggest=not self.saved_maps)
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    # -------------------------------------------------------------- paper and trays
    def orca_names(self):
        rules = self.screen.ctx.rules
        return list(rules.get("paper_types", [])), list(rules.get("trays", []))

    def used_trays(self):
        """The trays ORCA sends by itself: the default one and the bypass (special paper)."""
        import routing
        return [self.screen.ctx.rules.get("defaults", {}).get("tray", "Auto Tray Select"), routing.BYPASS]

    def fill_maps(self, suggest=False):
        """Read the driver's paper types and trays (read only) and show the translation, suggested or as saved."""
        import driverprint
        box = self.maps_box
        for w in box.winfo_children():
            w.destroy()
        self.map_vars, self.map_good = None, {}
        queue = self.vars["queue"].get()
        papers, trays = self.orca_names()
        if not queue:
            ttk.Label(box, text="Pick the Windows printer first.", style="Hint.TLabel").grid(row=0, column=0, sticky="w")
            return
        try:
            features = driverprint.capabilities(queue)["features"]
        except Exception:
            ttk.Label(box, text="Couldn't read this printer's paper types and trays: ORCA's names are sent as they are.",
                      style="Warn.TLabel", wraplength=460, justify="left").grid(row=0, column=0, sticky="w")
            return
        if driverprint.uses_orca_names(queue, papers, self.used_trays()):
            ttk.Label(box, text="This printer uses ORCA's paper names: nothing to set", style="Good.TLabel").grid(
                row=0, column=0, sticky="w")
            return
        offered = {"paper": list(features.get("PageMediaType", {})), "tray": list(features.get("JobInputBin", {}))}
        saved = self.saved_maps if (self.saved_maps and queue == self.saved_queue and not suggest) else None
        ttk.Label(box, text="ORCA's names on the left; pick this printer's own. Yellow: no good match found, pick by "
                            "hand.", style="Hint.TLabel", wraplength=460, justify="left").grid(row=0, column=0,
                                                                                               columnspan=2, sticky="w")
        ttk.Button(box, text="Suggest again", command=lambda: self.fill_maps(suggest=True)).grid(
            row=0, column=2, sticky="e")
        scroll = costs.ScrollFrame(box)
        scroll.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        scroll.canvas.configure(height=240, width=480)
        self.map_vars = {"paper": {}, "tray": {}}
        r = 0
        for kind, names, title in (("paper", papers, "Paper types"), ("tray", trays, "Trays")):
            ttk.Label(scroll.inner, text=title, style="Head.TLabel").grid(row=r, column=0, sticky="w", pady=(4, 2))
            r += 1
            suggestions = driverprint.suggest(names, offered[kind], kind)
            for name in names:
                choice, good = suggestions[name]
                if saved and name in (saved.get(kind) or {}):
                    choice, good = saved[kind][name], True
                var = tk.StringVar(value=choice)
                label = ttk.Label(scroll.inner, text=name, style="TLabel" if good else "Warn.TLabel")
                label.grid(row=r, column=0, sticky="w", padx=(0, 10))
                cb = ttk.Combobox(scroll.inner, textvariable=var, values=offered[kind] + [driverprint.DEFAULT],
                                  state="readonly", width=28, font=FONT)
                cb.grid(row=r, column=1, sticky="w", pady=1)
                cb.bind("<<ComboboxSelected>>", lambda _e, l=label: l.config(style="TLabel"))
                self.map_vars[kind][name] = var
                self.map_good[(kind, name)] = good
                r += 1
        theme.on_surface(box)

    def maps(self):
        """{"paper_map", "tray_map"} as shown, or {} (nothing to set: ORCA's names are sent as they are)."""
        if not self.map_vars:
            return {}
        return {"paper_map": {n: v.get() for n, v in self.map_vars["paper"].items()},
                "tray_map": {n: v.get() for n, v in self.map_vars["tray"].items()}}

    def values(self):
        """The typed values, or raises ValueError naming what's wrong."""
        v = {k: var.get() for k, var in self.vars.items()}
        if not v["queue"]:
            raise ValueError("Pick the Windows printer.")
        label = v["label"].strip()
        if not label:
            raise ValueError("Name in ORCA: required.")
        if any(p.get("label", k).strip().lower() == label.lower() for k, p in self.screen.printers.items()
               if k != self.pid):
            raise ValueError(f"Name in ORCA: “{label}” is already used.")
        gsm = v["max_gsm"].strip()
        if gsm and (not gsm.isdigit() or int(gsm) < 1):
            raise ValueError("Heaviest paper: a whole number of gsm, or empty for no limit.")
        return dict({"queue": v["queue"], "label": label, "color": "bw" if v["color"] == COLOURS["bw"] else "color",
                     "max_paper": v["max_paper"], "max_gsm": int(gsm) if gsm else None,
                     "address": v["address"].strip(), "copy_counter": bool(v["copy_counter"])}, **self.maps())

    def done(self):
        try:
            values = self.values()
        except ValueError as e:
            self.error.config(text=str(e))
            return
        self.dlg.destroy()
        self.screen.saved_printer(self.pid, values)
