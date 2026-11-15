"""The Prices screen: what each copy and each paper costs the shop (Tesla, 2026-11-15).

Not the selling prices: those are in prices.json and print on the walk-in receipt. These costs are
used only by the Counter screen and shown only there and here, never in PrintHub or Walk-in.

Local files next to the app, not on GitHub:
- costs.json: copy costs, paper extras and other consumables;
- prices_password.json: a salted hash of the Prices password. Deleting it resets the password.
"""
import hashlib
import hmac
import json
import os
import secrets
import tkinter as tk
from tkinter import messagebox, ttk

import routing
import theme

COSTS_FILE = "costs.json"
PASSWORD_FILE = "prices_password.json"
SIZES = ("A4", "A3")
MODES = (("bw", "Black and white"), ("color", "Colour"))
# The website's document papers (Website lib/papers.ts). Website documents reach PrintRouter only with
# a driver paper type, so the Counter finds their paper extra under that driver type.
DOCUMENT_PAPERS = ("Normal 80 gsm", "Thick 160 gsm", "Glossy 100 gsm", "Glossy 200 gsm", "Glossy 300 gsm")
ITERATIONS = 200_000
FONT = ("Segoe UI", 12)  # entries: ttk styles don't set their font


# ------------------------------------------------------------------ the costs file

def default_papers(rules):
    """Every paper name PrintRouter knows: website product papers, website document papers, driver types."""
    names = [n for n in rules.get("product_papers", {}) if not n.startswith("_")]
    names += list(DOCUMENT_PAPERS) + list(rules.get("paper_types", []))
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def empty(rules):
    return {"format": 1, "copy": {size: {mode: None for mode, _ in MODES} for size in SIZES},
            "papers": [{"name": n, "A4": None, "A3": None} for n in default_papers(rules)],
            "consumables": []}


def _amount(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def load(rules):
    """The saved costs; a missing or unreadable file starts with the paper lists and empty costs."""
    data = empty(rules)
    try:
        saved = json.loads((routing.app_dir() / COSTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    try:
        for size in SIZES:
            for mode, _ in MODES:
                data["copy"][size][mode] = _amount(saved.get("copy", {}).get(size, {}).get(mode))
        if isinstance(saved.get("papers"), list):
            data["papers"] = [{"name": str(p["name"]), "A4": _amount(p.get("A4")), "A3": _amount(p.get("A3"))}
                              for p in saved["papers"] if isinstance(p, dict) and str(p.get("name", "")).strip()]
        if isinstance(saved.get("consumables"), list):
            data["consumables"] = [{"name": str(c.get("name", "")), "unit": str(c.get("unit", "")),
                                    "cost": _amount(c.get("cost"))}
                                   for c in saved["consumables"] if isinstance(c, dict)]
    except (AttributeError, KeyError, TypeError):
        pass
    return data


def save(data):
    path = routing.app_dir() / COSTS_FILE
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def add_papers(data, names):
    """Add papers (e.g. found in print_log.csv) that aren't in the list yet, with no cost."""
    known = {p["name"].lower() for p in data["papers"]}
    for n in names:
        if n and n.lower() not in known:
            known.add(n.lower())
            data["papers"].append({"name": n, "A4": None, "A3": None})


def parse_amount(text):
    """Euro amount from a field: '0,20' or '0.2' -> 0.2; empty -> None. Raises ValueError otherwise."""
    text = text.strip().replace("€", "").replace(",", ".").strip()
    if not text:
        return None
    value = float(text)
    if value < 0 or value != value or value == float("inf"):
        raise ValueError(text)
    if "." in text and len(text.split(".")[1]) > 4:
        raise ValueError(text)
    return round(value, 4)


def amount_text(value):
    """0.2 -> '0.20', 0.0525 -> '0.0525', None -> ''."""
    if value is None:
        return ""
    text = f"{value:.4f}".rstrip("0")
    return text + "0" * max(0, 2 - len(text.split(".")[1]))


def euro(value):
    return f"€ {value:,.2f}"


class Costs:
    """Cost lookups for the Counter: cost of a job = sides x copy cost + sheets x paper extra."""

    def __init__(self, data):
        self.copy = data["copy"]
        self.papers = {p["name"].lower(): p for p in data["papers"]}

    def job_cost(self, size, color_sides, bw_sides, sheets, paper):
        """(cost in euro, True when a cost it needed isn't set: counted as 0)."""
        cost, missing = 0.0, False
        for mode, sides in (("color", color_sides), ("bw", bw_sides)):
            if sides:
                rate = self.copy.get(size, {}).get(mode)
                if rate is None:
                    missing = True
                else:
                    cost += sides * rate
        if sheets:
            extra = (self.papers.get((paper or "").lower()) or {}).get(size)
            if extra is None:
                missing = True
            else:
                cost += sheets * extra
        return cost, missing


# ------------------------------------------------------------------ the password

def has_password():
    return (routing.app_dir() / PASSWORD_FILE).is_file()


def _hash(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def set_password(password):
    salt = secrets.token_bytes(16)
    data = {"salt": salt.hex(), "iterations": ITERATIONS, "hash": _hash(password, salt, ITERATIONS)}
    path = routing.app_dir() / PASSWORD_FILE
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def check_password(password):
    try:
        data = json.loads((routing.app_dir() / PASSWORD_FILE).read_text(encoding="utf-8"))
        return hmac.compare_digest(_hash(password, bytes.fromhex(data["salt"]), int(data["iterations"])),
                                   data["hash"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


class PasswordDialog:
    """A small dark dialog. mode 'new' (typed twice), 'ask' (checked), 'change' (old, then new twice).
    self.ok is True once it succeeded."""

    def __init__(self, parent, mode):
        self.mode, self.ok = mode, False
        self.dlg = dlg = tk.Toplevel(parent)
        dlg.title("Prices")
        dlg.resizable(False, False)
        dlg.transient(parent)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        text = {"new": "Choose a password for Prices.\nIt keeps costs from being changed by mistake.",
                "ask": "Password for Prices:",
                "change": "Change the Prices password."}[mode]
        ttk.Label(f, text=text, justify="left").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        labels = {"new": ["New password:", "Type it again:"], "ask": ["Password:"],
                  "change": ["Old password:", "New password:", "Type it again:"]}[mode]
        self.vars = []
        for i, label in enumerate(labels, start=1):
            var = tk.StringVar()
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Entry(f, textvariable=var, show="•", width=24, font=FONT)
            e.grid(row=i, column=1, sticky="w", padx=(8, 0), pady=3)
            e.bind("<Return>", lambda _: self.done())
            if i == 1:
                e.focus_set()
            self.vars.append(var)
        self.error = ttk.Label(f, text="", foreground=theme.ERROR)
        self.error.grid(row=len(labels) + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(f)
        buttons.grid(row=len(labels) + 2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="OK", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        dlg.bind("<Escape>", lambda _: dlg.destroy())
        theme.dark_title_bar(dlg)
        dlg.grab_set()
        dlg.focus_force()

    def done(self):
        values = [v.get() for v in self.vars]
        if self.mode == "ask":
            if not check_password(values[0]):
                self.error.config(text="Wrong password.")
                self.vars[0].set("")
                return
        else:
            if self.mode == "change" and not check_password(values[0]):
                self.error.config(text="The old password is wrong.")
                return
            new, again = values[-2], values[-1]
            if not new:
                self.error.config(text="Type a password.")
                return
            if new != again:
                self.error.config(text="The two passwords are not the same.")
                return
            set_password(new)
        self.ok = True
        self.dlg.destroy()

    def wait(self):
        self.dlg.wait_window()
        return self.ok


def ask_to_open(parent):
    """The password step before Prices opens: choose one the first time, then type it. True to open."""
    return PasswordDialog(parent, "ask" if has_password() else "new").wait()


# ------------------------------------------------------------------ the Prices screen

class ScrollFrame(ttk.Frame):
    """A frame whose content (self.inner) scrolls up and down."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=theme.BG, highlightthickness=0, borderwidth=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._item = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._item, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        try:
            if str(event.widget).startswith(str(self)) and self.winfo_ismapped():
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass


class PricesScreen:
    """Copy costs, paper extras per sheet and other consumables, with Save / Cancel."""

    def __init__(self, root, rules, on_back, papers_in_log=()):
        self.rules, self.on_back = rules, on_back
        self.papers_in_log = list(papers_in_log)
        self.data = load(rules)
        add_papers(self.data, self.papers_in_log)
        self.win = win = tk.Toplevel(root)
        win.title("PrintRouter: Prices")
        win.geometry("900x860")
        win.minsize(760, 600)
        win.protocol("WM_DELETE_WINDOW", self.back)
        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)

        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="← Back", command=self.back).pack(side="left", padx=(0, 24))
        ttk.Label(top, text="Prices: what printing costs the shop", style="Summary.TLabel").pack(side="left")
        ttk.Button(top, text="Change password…", command=self.change_password).pack(side="right")
        ttk.Label(f, text="Amounts in euro, up to 4 decimals (0,20 or 0.20). An empty field means not set. "
                          "Used by the Counter only.", style="Hint.TLabel").grid(row=1, column=0, sticky="w",
                                                                                pady=(8, 8))
        self.scroll = ScrollFrame(f)
        self.scroll.grid(row=2, column=0, sticky="nsew")
        bottom = ttk.Frame(f)
        bottom.grid(row=3, column=0, sticky="we", pady=(12, 0))
        self.status = ttk.Label(bottom, text="", style="Hint.TLabel")
        self.status.pack(side="left")
        ttk.Button(bottom, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(bottom, text="Save", style="Print.TButton", command=self.save).pack(side="right", padx=(0, 8))
        self.fill()
        theme.dark_title_bar(win)

    # -------------------------------------------------------------- fields

    def fill(self):
        """Build every field from self.data; remember what they say, to notice unsaved changes."""
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        inner.columnconfigure(0, weight=1)

        box = ttk.LabelFrame(inner, text="Cost of a copy (one printed side, plain paper included)",
                             padding=12, style="Section.TLabelframe")
        box.grid(row=0, column=0, sticky="we", pady=(0, 12))
        self.copy_vars = {}
        for c, (_, title) in enumerate(MODES, start=1):
            ttk.Label(box, text=title).grid(row=0, column=c, sticky="w", padx=8)
        for r, size in enumerate(SIZES, start=1):
            ttk.Label(box, text=size).grid(row=r, column=0, sticky="w", pady=3)
            for c, (mode, _) in enumerate(MODES, start=1):
                var = tk.StringVar(value=amount_text(self.data["copy"][size][mode]))
                ttk.Entry(box, font=FONT, textvariable=var, width=10).grid(row=r, column=c, sticky="w", padx=8, pady=3)
                self.copy_vars[(size, mode)] = var
        theme.on_surface(box)

        box = ttk.LabelFrame(inner, text="Papers: extra cost per sheet, on top of the copy cost",
                             padding=12, style="Section.TLabelframe")
        box.grid(row=1, column=0, sticky="we", pady=(0, 12))
        box.columnconfigure(0, weight=1)
        self.paper_box = box
        self.paper_rows = []
        for p in self.data["papers"]:
            self.add_paper_row(p["name"], amount_text(p["A4"]), amount_text(p["A3"]))
        self.add_paper_btn = ttk.Button(box, text="Add paper", command=lambda: self.add_paper_row("", "", "", True))
        self.layout_papers()

        box = ttk.LabelFrame(inner, text="Other consumables (not used by the Counter yet)",
                             padding=12, style="Section.TLabelframe")
        box.grid(row=2, column=0, sticky="we")
        box.columnconfigure(0, weight=1)
        self.cons_box = box
        self.cons_rows = []
        for c in self.data["consumables"]:
            self.add_cons_row(c["name"], c["unit"], amount_text(c["cost"]))
        self.add_cons_btn = ttk.Button(box, text="Add", command=lambda: self.add_cons_row("", "", "", True))
        self.layout_cons()
        self.saved = self.snapshot()

    def add_paper_row(self, name, a4, a3, focus=False):
        box = self.paper_box
        row = {"vars": [tk.StringVar(value=name), tk.StringVar(value=a4), tk.StringVar(value=a3)]}
        row["widgets"] = [ttk.Entry(box, font=FONT, textvariable=row["vars"][0], width=34),
                          ttk.Entry(box, font=FONT, textvariable=row["vars"][1], width=10),
                          ttk.Entry(box, font=FONT, textvariable=row["vars"][2], width=10),
                          ttk.Button(box, text="Remove", command=lambda: self.remove(self.paper_rows, row,
                                                                                     self.layout_papers))]
        self.paper_rows.append(row)
        if focus:
            self.layout_papers()
            row["widgets"][0].focus_set()

    def add_cons_row(self, name, unit, cost, focus=False):
        box = self.cons_box
        row = {"vars": [tk.StringVar(value=name), tk.StringVar(value=unit), tk.StringVar(value=cost)]}
        row["widgets"] = [ttk.Entry(box, font=FONT, textvariable=row["vars"][0], width=34),
                          ttk.Entry(box, font=FONT, textvariable=row["vars"][1], width=14),
                          ttk.Entry(box, font=FONT, textvariable=row["vars"][2], width=10),
                          ttk.Button(box, text="Remove", command=lambda: self.remove(self.cons_rows, row,
                                                                                     self.layout_cons))]
        self.cons_rows.append(row)
        if focus:
            self.layout_cons()
            row["widgets"][0].focus_set()

    def remove(self, rows, row, relayout):
        rows.remove(row)
        for w in row["widgets"]:
            w.destroy()
        relayout()

    def _layout(self, box, rows, headings, button):
        for w in box.grid_slaves():
            w.grid_forget()
        for w in getattr(box, "_heads", []):
            w.destroy()
        box._heads = [ttk.Label(box, text=t, style="Hint.TLabel") for t in headings]
        for c, w in enumerate(box._heads):
            w.grid(row=0, column=c, sticky="w", padx=4)
        for r, row in enumerate(rows, start=1):
            for c, w in enumerate(row["widgets"]):
                w.grid(row=r, column=c, sticky="we" if c == 0 else "w", padx=4, pady=2)
        button.grid(row=len(rows) + 1, column=0, sticky="w", pady=(8, 0))
        theme.on_surface(box)

    def layout_papers(self):
        self._layout(self.paper_box, self.paper_rows, ["Paper", "A4 sheet", "A3 sheet", ""], self.add_paper_btn)

    def layout_cons(self):
        self._layout(self.cons_box, self.cons_rows, ["Name", "Unit", "Cost", ""], self.add_cons_btn)

    def snapshot(self):
        return ([v.get() for v in self.copy_vars.values()],
                [[v.get() for v in r["vars"]] for r in self.paper_rows],
                [[v.get() for v in r["vars"]] for r in self.cons_rows])

    def changed(self):
        return self.snapshot() != self.saved

    # -------------------------------------------------------------- buttons

    def collect(self):
        """The fields as costs data, or raise ValueError with the field's name."""
        def amount(text, where):
            try:
                return parse_amount(text)
            except ValueError:
                raise ValueError(f"{where}: “{text.strip()}” isn't an amount in euro (up to 4 decimals).")

        data = {"format": 1, "copy": {size: {} for size in SIZES}, "papers": [], "consumables": []}
        for (size, mode), var in self.copy_vars.items():
            data["copy"][size][mode] = amount(var.get(), f"Copy {size} {dict(MODES)[mode]}")
        names = set()
        for r in self.paper_rows:
            name, a4, a3 = (v.get() for v in r["vars"])
            name = name.strip()
            if not name:
                if a4.strip() or a3.strip():
                    raise ValueError("A paper with a cost has no name.")
                continue
            if name.lower() in names:
                raise ValueError(f"The paper “{name}” is in the list twice.")
            names.add(name.lower())
            data["papers"].append({"name": name, "A4": amount(a4, f"{name} A4"), "A3": amount(a3, f"{name} A3")})
        for r in self.cons_rows:
            name, unit, cost = (v.get().strip() for v in r["vars"])
            if name or unit or cost:
                data["consumables"].append({"name": name, "unit": unit, "cost": amount(cost, name or "Consumable")})
        return data

    def save(self):
        try:
            data = self.collect()
            save(data)
        except ValueError as e:
            messagebox.showwarning(parent=self.win, title="Prices", message=str(e))
            return False
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="Prices", message=f"Could not save {COSTS_FILE}.\n\n{e}")
            return False
        self.data = load(self.rules)
        self.saved = self.snapshot()
        self.status.config(text="Saved.")
        return True

    def cancel(self):
        """Put every field back to what was saved."""
        self.data = load(self.rules)
        add_papers(self.data, self.papers_in_log)
        self.fill()
        self.status.config(text="Changes undone.")

    def change_password(self):
        if PasswordDialog(self.win, "change").wait():
            self.status.config(text="Password changed.")

    def back(self):
        if self.changed():
            answer = messagebox.askyesnocancel(parent=self.win, title="Prices",
                                               message="Save the changes before going back?")
            if answer is None:
                return
            if answer and not self.save():
                return
        self.win.destroy()
        self.on_back()
