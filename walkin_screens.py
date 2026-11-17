"""The walk-in screens (2026-11-17): Walk-in (Get Quote, Add Email, Print Jobs), the quote / email order screen,
Print Jobs and Orders. Data in walkin_orders, prices in walkin_prices / walkin_pricing, printing in walkin_print.
Walk-in orders are never mixed with PrintHub (website) orders.
"""
import datetime
import math
import os
import tkinter as tk
from tkinter import messagebox, ttk

import analyze
import costs
import theme
import walkin_catalogue as cat
import walkin_orders as wo
import walkin_prices
import walkin_pricing
import walkin_print

FONT = costs.FONT
COLOUR_CHOICES = {"B&W": "bw", "Colour": "color", "Some pages in colour": "mixed"}
SIDE_CHOICES = {"One side": "single", "Both sides": "double"}
FINISH_CHOICES = {"None": "none", "Staple": "staple", "Spiral": "spiral"}


def euro(x):
    return f"EUR {x:,.2f}"


def parse_money(text):
    t = str(text).strip().replace("EUR", "").replace("€", "").replace(",", ".").strip()
    if not t:
        return None
    value = float(t)
    if value < 0:
        raise ValueError(t)
    return round(value, 2)


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


class Screen:
    """A screen window: title bar text, Back at the top left, closing with the X goes back too."""

    def __init__(self, ctx, title, on_back, size="1200x880"):
        self.ctx, self.on_back = ctx, on_back
        self.win = win = tk.Toplevel(ctx.root)
        win.title(f"ORCA - {title}")
        win.geometry(size)
        win.minsize(980, 620)
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

    def ready(self):
        theme.dark_title_bar(self.win)

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
    """Three big buttons: Get Quote, Add Email, Print Jobs."""

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Walk-in", on_back, size="900x560")
        self.warn = self.warnings(self.frame, 1)
        box = ttk.Frame(self.frame)
        box.grid(row=2, column=0, pady=(40, 0))
        for c, (text, command) in enumerate((("Get Quote", lambda: self.open_quote("quote")),
                                             ("Add Email", lambda: self.open_quote("email")),
                                             ("Print Jobs", self.open_print_jobs))):
            ttk.Button(box, text=text, style="Walkin.TButton", width=11, command=command).grid(row=0, column=c, padx=12)
        ttk.Label(self.frame, text="Get Quote: a customer at the counter (name and phone needed).   "
                                   "Add Email: an order that came by email.   Print Jobs: orders ready to print.",
                  style="Small.TLabel").grid(row=3, column=0, pady=(30, 0))
        self.ready()
        self.poll()

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


# ------------------------------------------------------------------ Get Quote / Add Email

class QuoteScreen(Screen):
    """Items with their prices, loyalty, change price, the customer, Place order (or discard)."""

    def __init__(self, ctx, mode, on_back):
        super().__init__(ctx, "Get Quote" if mode == "quote" else "Add Email", on_back, size="1320x900")
        self.mode = mode
        self.items = []
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
        cb.bind("<<ComboboxSelected>>", lambda _: self.build_options())
        self.options = ttk.Frame(self.editor)
        self.options.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 0))
        buttons = ttk.Frame(self.editor)
        buttons.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.add_btn = ttk.Button(buttons, text="Add item", style="Print.TButton", command=self.add_item)
        self.add_btn.pack(side="left")
        self.cancel_edit_btn = ttk.Button(buttons, text="Cancel edit", command=self.cancel_edit)
        self.editor_error = ttk.Label(self.editor, text="", style="Bad.TLabel", wraplength=380, justify="left")
        self.editor_error.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # The price list
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(right, columns=("n", "item", "price"), show="headings", height=8, selectmode="browse")
        for col, text, width, stretch in (("n", "#", 40, False), ("item", "Item", 520, True), ("price", "Price", 110, False)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, stretch=stretch, anchor="e" if col == "price" else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        row = ttk.Frame(right)
        row.grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Button(row, text="Edit", command=self.edit_item).pack(side="left")
        ttk.Button(row, text="Remove", command=self.remove_item).pack(side="left", padx=(8, 0))
        self.notes = ttk.Label(right, text="", style="Small.TLabel", justify="left", wraplength=760)
        self.notes.grid(row=2, column=0, sticky="w", pady=(4, 0))
        totals = ttk.Frame(right)
        totals.grid(row=3, column=0, sticky="we", pady=(8, 0))
        totals.columnconfigure(0, weight=1)
        self.total_lines = ttk.Label(totals, text="", justify="right", anchor="e")
        self.total_lines.grid(row=0, column=0, columnspan=4, sticky="e")
        ttk.Label(totals, text="Loyalty:").grid(row=1, column=1, sticky="e", pady=(8, 0))
        self.loyalty = tk.StringVar(value="None")
        lc = ttk.Combobox(totals, textvariable=self.loyalty, values=["None", "1", "2", "3"], state="readonly", width=6,
                          font=FONT)
        lc.grid(row=1, column=2, sticky="w", padx=6, pady=(8, 0))
        lc.bind("<<ComboboxSelected>>", lambda _: self.reprice())
        ttk.Label(totals, text="Change price (EUR):").grid(row=2, column=1, sticky="e", pady=(6, 0))
        self.changed = tk.StringVar()
        ttk.Entry(totals, textvariable=self.changed, width=10, font=FONT).grid(row=2, column=2, sticky="w", padx=6,
                                                                                pady=(6, 0))
        self.changed.trace_add("write", lambda *_: self.reprice())
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
        ttk.Label(cust, text=("* required. Email optional." if mode == "quote" else f"Name, phone, email: {need}."),
                  style="Small.TLabel").grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        self.known = ttk.Label(cust, text="", style="Good.TLabel")
        self.known.grid(row=2, column=0, columnspan=6, sticky="w")
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

        def combo(label, values, value):
            nonlocal row
            ttk.Label(self.options, text=label + ":").grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=value)
            ttk.Combobox(self.options, textvariable=var, values=values, state="readonly", width=28, font=FONT).grid(
                row=row, column=1, sticky="w", pady=3)
            row += 1
            return var

        def entry(label, value, width=8):
            nonlocal row
            ttk.Label(self.options, text=label + ":").grid(row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=str(value))
            ttk.Entry(self.options, textvariable=var, width=width, font=FONT).grid(row=row, column=1, sticky="w", pady=3)
            row += 1
            return var

        if self.what.get() == "Document":
            d = item or {"size": "A4", "pages": 1, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
                         "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
            v = self.option_vars
            v["size"] = combo("Size", ["A4", "A3"], d["size"])
            v["pages"] = entry("Pages", d["pages"])
            v["copies"] = entry("Copies", d["copies"])
            v["color"] = combo("Colour", list(COLOUR_CHOICES), next(k for k, x in COLOUR_CHOICES.items() if x == d["color"]))
            v["color_pages"] = entry("Colour pages (e.g. 1, 3-5)", d["color_pages"], 16)
            v["sides"] = combo("Sides", list(SIDE_CHOICES), next(k for k, x in SIDE_CHOICES.items() if x == d["sides"]))
            v["per_side"] = combo("Pages per side", [str(n) for n in cat.PER_SIDE], str(d["per_side"]))
            papers = list(pl.doc_papers)
            v["paper"] = combo("Paper", papers if d["paper"] in papers else papers + [d["paper"]], d["paper"])
            v["finish"] = combo("Finishing", list(FINISH_CHOICES),
                                next(k for k, x in FINISH_CHOICES.items() if x == d["finish"]))
            v["lam"] = tk.BooleanVar(value=d["lam"])
            ttk.Checkbutton(self.options, text="Laminate", variable=v["lam"]).grid(row=row, column=0, sticky="w", pady=3)
            row += 1
            v["lam_sheets"] = entry("Sheets to laminate (0 = all)", d["lam_sheets"])
        else:
            p = next(p for p in cat.PRODUCTS if p["name"] == self.what.get())
            picks = item["picks"] if item else cat.default_picks(p)
            for o in p["options"]:
                self.option_vars[o["key"]] = combo(o["label"], o["choices"], o["choices"][picks.get(o["key"], 0)])
            self.option_vars["qty"] = combo("Quantity", [str(q) for q in p["qty"]], str(item["qty"] if item else p["qty"][0]))
        theme.on_surface(self.editor)

    def read_item(self):
        """The item from the editor, or raises ValueError with what is wrong."""
        v = self.option_vars
        if self.what.get() == "Document":
            def whole(key, name, low=1):
                t = v[key].get().strip()
                if not t.isdigit() or int(t) < low:
                    raise ValueError(f"{name}: a whole number of {low} or more.")
                return int(t)
            item = {"kind": "document", "size": v["size"].get(), "pages": whole("pages", "Pages"),
                    "copies": whole("copies", "Copies"), "color": COLOUR_CHOICES[v["color"].get()],
                    "color_pages": v["color_pages"].get().strip(), "sides": SIDE_CHOICES[v["sides"].get()],
                    "per_side": int(v["per_side"].get()), "paper": v["paper"].get(),
                    "finish": FINISH_CHOICES[v["finish"].get()], "lam": bool(v["lam"].get()),
                    "lam_sheets": whole("lam_sheets", "Sheets to laminate", 0)}
            if item["color"] == "mixed" and not walkin_pricing.page_set(item["color_pages"], item["pages"]):
                raise ValueError("Colour pages: say which pages are in colour (e.g. 1, 3-5).")
            if item["copies"] > 999:
                raise ValueError("Copies: 999 at most.")
            return item
        p = next(p for p in cat.PRODUCTS if p["name"] == self.what.get())
        picks = {o["key"]: o["choices"].index(v[o["key"]].get()) for o in p["options"]}
        return {"kind": "product", "product": p["id"], "qty": int(v["qty"].get()), "picks": picks}

    def add_item(self):
        try:
            item = self.read_item()
        except ValueError as e:
            self.editor_error.config(text=str(e))
            return
        self.editor_error.config(text="")
        if self.editing is None:
            self.items.append(item)
        else:
            self.items[self.editing] = item
        self.cancel_edit()
        self.reprice()

    def edit_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.editing = int(sel[0])
        item = self.items[self.editing]
        self.what.set("Document" if item["kind"] == "document" else walkin_pricing.product_of(item)["name"])
        self.build_options(item)
        self.editor.config(text=f"Edit item {self.editing + 1}")
        self.add_btn.config(text="Save item")
        self.cancel_edit_btn.pack(side="left", padx=(8, 0))

    def cancel_edit(self):
        self.editing = None
        self.editor.config(text="Add an item")
        self.add_btn.config(text="Add item")
        self.cancel_edit_btn.pack_forget()
        self.build_options()

    def remove_item(self):
        sel = self.tree.selection()
        if sel:
            del self.items[int(sel[0])]
            self.cancel_edit()
            self.reprice()

    # -------------------------------------------------------------- prices

    def loyalty_level(self):
        return 0 if self.loyalty.get() == "None" else int(self.loyalty.get())

    def reprice(self):
        pl = walkin_prices.current()
        self.warn.config(text="\n".join(pl.warnings[:6]))
        self.priced = walkin_pricing.price_order(pl, self.items, self.loyalty_level())
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        notes = []
        for i, (item, line) in enumerate(zip(self.items, self.priced["lines"])):
            text = walkin_pricing.describe(item) + ("  · priced together" if line["note"] else "")
            self.tree.insert("", "end", iid=str(i), values=(i + 1, text, euro(line["price"])))
            if line["note"] and line["note"] not in notes:
                notes.append(line["note"])
        if keep and keep[0] in self.tree.get_children():
            self.tree.selection_set(keep)
        self.notes.config(text="\n".join(notes))
        lines = [f"Items: {euro(sum(l['price'] for l in self.priced['lines']))}"]
        if self.priced["volume"]:
            lines.append(f"Volume price (documents, never more for fewer pages): {euro(self.priced['volume'])}")
        loyalty = self.priced["loyalty"]
        if loyalty:
            lines.append(f"{loyalty['text']}: -{euro(-loyalty['amount'])}" if loyalty["amount"] else loyalty["text"])
        self.total_lines.config(text="\n".join(lines))
        total = self.priced["total"]
        try:
            changed = parse_money(self.changed.get())
            if changed is None:
                self.total_label.config(text=f"Total: {euro(total)}")
            else:
                diff = changed - total
                self.total_label.config(text=f"Calculated {euro(total)}   ·   Changed {euro(changed)}   ·   "
                                             f"Difference {'-' if diff < 0 else '+'}{euro(abs(diff))}")
        except ValueError:
            self.total_label.config(text=f"Total: {euro(total)}   ·   Change price: not an amount")
        self.problems.config(text="\n".join(self.priced["problems"]))

    # -------------------------------------------------------------- the customer

    def lookup(self):
        """A phone or email ORCA knows fills in the name and loyalty level (staff can change both)."""
        c = wo.Customers().lookup(self.cust_vars["phone"].get(), self.cust_vars["email"].get())
        if c and c["id"] != self.filled_from:
            self.filled_from = c["id"]
            self.cust_vars["name"].set(c["name"])
            self.loyalty.set(str(c["loyalty"]) if c.get("loyalty") else "None")
            self.known.config(text=f"Known customer: {c['name']} ({', '.join(c['phones'] + c['emails'])})")
            self.reprice()
        elif not c:
            self.known.config(text="")
            self.filled_from = None

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
        try:
            changed = parse_money(self.changed.get())
        except ValueError:
            messagebox.showwarning(parent=self.win, title="ORCA", message="Change price: not an amount in EUR.")
            return
        customers = wo.Customers()
        join = None
        clash = customers.conflict(phone, email)
        if clash:
            join = messagebox.askyesno(parent=self.win, title="ORCA",
                                       message=f"This phone is {clash[0]['name'] or clash[0]['folder']} and this email "
                                               f"is {clash[1]['name'] or clash[1]['folder']} in ORCA. Same customer?")
        try:  # a name with no phone or email: a new customer every time (Customers.resolve)
            customer = customers.resolve(name, phone, email, self.loyalty_level(), join=join)
            customer = dict(customer, entered_name=name, entered_phone=phone, entered_email=email)
            order = wo.place(self.items, self.priced, customer, self.mode, self.priced["loyalty"], changed)
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
        NumberDialog(self.win, order)
        self.items = []
        self.changed.set("")
        for v in self.cust_vars.values():
            v.set("")
        self.loyalty.set("None")
        self.cancel_edit()
        self.reprice()


class NumberDialog:
    """The new order's number, large."""

    def __init__(self, parent, order):
        self.dlg = dlg = tk.Toplevel(parent)
        dlg.title("ORCA - order placed")
        dlg.transient(parent)
        f = ttk.Frame(dlg, padding=30)
        f.grid()
        ttk.Label(f, text="Order placed").grid(row=0, column=0)
        ttk.Label(f, text=f"#{order['number']}", style="Huge.TLabel").grid(row=1, column=0, pady=10)
        ttk.Label(f, text=f"{customer_text(order['customer'])}\n{euro(wo.price_due(order))}\n"
                          f"Put each item's file into its folder (it is open in Explorer).",
                  justify="center").grid(row=2, column=0)
        ttk.Button(f, text="OK", style="Print.TButton", command=dlg.destroy).grid(row=3, column=0, pady=(16, 0))
        theme.dark_title_bar(dlg)


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

    def signature_of(self, orders):
        prep = self.ctx.preparer
        return tuple((o["number"], o["status"], o.get("changed_total"), tuple(
            (i.get("file"), i.get("sheets"), str(i.get("print")), bool(prep.get(o, i))) for i in o["items"]))
            for o in orders) + (self.extra_signature(),)

    def extra_signature(self):
        return None

    def card(self, parent, order, buttons):
        box = ttk.LabelFrame(parent, text=f"#{order['number']}  ·  {order['source']}  ·  {euro(wo.price_due(order))}"
                             + ("  (changed price)" if order.get("changed_total") is not None else ""),
                             padding=10, style="Section.TLabelframe")
        box.columnconfigure(0, weight=1)
        times = order["times"]
        ttk.Label(box, text=f"Placed {when(times['placed'])}   ·   printed {when(times['printed'])}   ·   "
                            f"ready {when(times['ready'])}", style="Small.TLabel").grid(row=0, column=0, sticky="w")
        r = 1
        for i, item in enumerate(order["items"], start=1):
            state = self.item_state(order, item)
            ttk.Label(box, text=f"{i}. {item['description']}   {euro(item['price'])}").grid(row=r, column=0, sticky="w")
            ttk.Label(box, text=f"     {state[0]}", style=state[1]).grid(row=r + 1, column=0, sticky="w")
            r += 2
        row = ttk.Frame(box)
        row.grid(row=r, column=0, sticky="w", pady=(6, 0))
        for text, command, style in buttons:
            ttk.Button(row, text=text, command=command, style=style or "TButton").pack(side="left", padx=(0, 8))
        theme.on_surface(box)
        return box

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
    """Orders ready to print, grouped by customer; nothing prints until Print (or Print all) is pressed."""

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Print Jobs", on_back)
        self.sending = {}  # order number -> "sending" / error text
        self.ready()
        self.poll()

    def back(self):
        if self.ctx.sender.busy():
            self.win.bell()
            return
        super().back()

    def extra_signature(self):
        return tuple(sorted(self.sending.items()))

    def handle_results(self):
        try:
            while True:
                msg = self.ctx.sender.results.get_nowait()
                if msg[0] == "progress":
                    self.status.config(text=msg[2])
                elif msg[0] == "turn":
                    _, number, name, label, answer = msg
                    answer["ok"] = messagebox.askokcancel(
                        parent=self.win, title="ORCA",
                        message=f"#{number}: the fronts of {name} were sent to {label}.\n\nWhen they are all out, turn "
                                f"the stack over, put it back in the Bypass Tray, then click OK to print the backs.\n\n"
                                f"Cancel: the backs are not printed.")
                    answer["event"].set()
                elif msg[0] == "done":
                    _, number, failed = msg
                    order = next((o for o in wo.list_open() if o["number"] == number), None)
                    if failed:
                        self.sending[number] = f"NOT all printed: {failed}"
                        self.status.config(text=f"#{number}: {failed}")
                    else:
                        self.sending.pop(number, None)
                        if order:
                            wo.set_status(order, "printed")
                        self.status.config(text=f"#{number} sent.")
                    self.signature = None
        except Exception:
            pass
        self.back_btn.config(state="disabled" if self.ctx.sender.busy() else "normal")

    def plan(self, order):
        """[(printer, [(item index or None, job, pdf)])]: the cover sheet first on the first part's copier."""
        rules, shared = self.ctx.rules, self.ctx.jobs
        parts = {}
        for i, item in enumerate(order["items"]):
            prepared = self.ctx.preparer.get(order, item)
            if prepared is None:
                raise ValueError(f"item {i + 1} is still being checked: try again in a moment")
            if "error" in prepared:
                raise ValueError(f"item {i + 1}: {prepared['error']}")
            job = walkin_print.job_for(shared, rules, item, prepared)
            if job is None:
                raise ValueError(f"item {i + 1}: these settings can't print")
            if job["problem"]:
                raise ValueError(f"item {i + 1}: {job['problem']}")
            job["file_name"] = f"#{order['number']} {item['folder']}"
            parts.setdefault(job["printer"], []).append((i, job, prepared["pdf"]))
        first = next(iter(parts))
        cover = walkin_print.WORK_DIR / f"cover_{order['number']}.pdf"
        cover.parent.mkdir(parents=True, exist_ok=True)
        import jobs as jobs_module
        with jobs_module.PDF_LOCK:
            walkin_print.cover_pdf(order, cover)
            cover_pages = analyze.page_count(cover)
        cjob = walkin_print.cover_job(shared, first, cover_pages)
        if cjob is None or cjob["problem"]:
            raise ValueError(f"the cover sheet can't print on {shared.printers[first]['label']}"
                             + (f": {cjob['problem']}" if cjob else ""))
        cjob["file_name"] = f"#{order['number']} {walkin_print.COVER}"
        plan = [(first, [(None, cjob, cover)] + parts.pop(first))]
        plan += list(parts.items())
        return plan

    def print_orders(self, orders):
        for order in orders:
            if order["number"] in self.sending and self.sending[order["number"]] == "sending":
                continue
            try:
                plan = self.plan(order)
            except ValueError as e:
                messagebox.showwarning(parent=self.win, title="ORCA", message=f"#{order['number']} can't print yet: {e}")
                continue
            self.sending[order["number"]] = "sending"
            self.ctx.sender.send(order, plan)
        self.signature = None

    def fill(self, orders):
        shown = [o for o in orders if o["status"] in ("ready_to_print", "printed")]
        self.status.config(text=self.status.cget("text") or "Nothing prints until you press Print.")
        if not shown:
            ttk.Label(self.scroll.inner, text="No order is ready to print.", style="Small.TLabel").grid(sticky="w")
            return
        r = 0
        for name, group in group_by_customer(shown):
            head = ttk.Frame(self.scroll.inner)
            head.grid(row=r, column=0, sticky="we", pady=(10, 4))
            ttk.Label(head, text=name, style="Big.TLabel").pack(side="left")
            ready = [o for o in group if o["status"] == "ready_to_print"]
            if len(ready) > 1:
                ttk.Button(head, text=f"Print all ({len(ready)})", style="Print.TButton",
                           command=lambda g=ready: self.print_orders(g)).pack(side="left", padx=(16, 0))
            r += 1
            for order in group:
                if order["status"] == "printed":
                    buttons = [("Ready for pickup", lambda o=order: self.ready_for_pickup(o), "Print.TButton"),
                               ("Open folder", lambda o=order: self.open_folder(o), None)]
                else:
                    state = self.sending.get(order["number"])
                    buttons = ([] if state == "sending" else
                               [("Print", lambda o=order: self.print_orders([o]), "Print.TButton")])
                    buttons.append(("Open folder", lambda o=order: self.open_folder(o), None))
                box = self.card(self.scroll.inner, order, buttons)
                box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                if order["status"] == "printed":
                    ttk.Label(box, text="Printed", style="Good.TLabel").grid(row=0, column=0, sticky="e")
                elif order["number"] in self.sending:
                    state = self.sending[order["number"]]
                    ttk.Label(box, text="Sending…" if state == "sending" else state,
                              style="Warn.TLabel" if state == "sending" else "Bad.TLabel").grid(row=0, column=0, sticky="e")
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
        job = walkin_print.job_for(self.ctx.jobs, self.ctx.rules, item, prepared)
        if job is None:
            return ("these settings can't print: use Settings…", "Bad.TLabel")
        s = walkin_print.settings_for(self.ctx.rules, item, prepared)
        text = (f"{f.name} → {self.ctx.jobs.printers[job['printer']]['label']} · "
                f"{self.ctx.jobs.settings_text(s, job)}")
        return (text + (f" · {job['problem']}" if job["problem"] else ""), "Bad.TLabel" if job["problem"] else "Good.TLabel")

    def card(self, parent, order, buttons):
        box = super().card(parent, order, buttons)
        r = 1
        for i, item in enumerate(order["items"]):
            if order["status"] == "ready_to_print":
                ttk.Button(box, text="Settings…", command=lambda o=order, k=i: SettingsDialog(self, o, k)).grid(
                    row=r, column=1, rowspan=2, sticky="e")
            r += 2
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

class OrdersScreen(OrderList):
    """Waiting for PDF, Ready to print (with printed ones), Ready for pickup; grouped by customer; search."""

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
                    box = self.card(self.scroll.inner, order, self.buttons(order))
                    box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                    if order["status"] == "printed":
                        ttk.Label(box, text="Printed", style="Good.TLabel").grid(row=0, column=0, sticky="e")
                        theme.on_surface(box)
                    r += 1
        if text.strip():
            history = [o for o in wo.list_history() if wo.matches(o, text)]
            ttk.Label(self.scroll.inner, text=f"Collected and cancelled ({len(history)})", style="Big.TLabel").grid(
                row=r, column=0, sticky="w", pady=(12, 4))
            r += 1
            for order in sorted(history, key=lambda o: o["created"], reverse=True):
                box = self.card(self.scroll.inner, order, [("Open folder", lambda o=order: self.open_folder(o), None)])
                state = (f"Cancelled {when(order['times']['cancelled'])}" if order["status"] == "cancelled" else
                         f"Collected {when(order['times']['collected'])}, paid {euro(order.get('paid') or 0)}")
                ttk.Label(box, text=f"{customer_text(order['customer'])}  ·  {state}",
                          style="Small.TLabel").grid(row=0, column=0, sticky="e")
                theme.on_surface(box)
                box.grid(row=r, column=0, sticky="we", pady=(0, 8))
                r += 1

    def buttons(self, order):
        out = [("Open folder", lambda: self.open_folder(order), None)]
        for i, item in enumerate(order["items"]):
            if (item["kind"] == "product" and wo.sheet_state(order, item)[0] in ("ok", "bad")
                    and not wo.laid_out(order, item)):
                out.insert(0, (f"Layout done (item {i + 1})…", lambda k=i: SheetsDialog(self, order, k), "Print.TButton"))
        if order["status"] == "printed":
            out.insert(0, ("Ready for pickup", lambda: self.ready_for_pickup(order), "Print.TButton"))
        out += [("Change price", lambda: self.change_price(order), None),
                ("Collected", lambda: self.collected(order), None),
                ("Cancel order", lambda: self.cancel(order), None)]
        return out

    def change_price(self, order):
        PriceDialog(self, order)

    def collected(self, order):
        if not messagebox.askyesno(parent=self.win, title="ORCA",
                                   message=f"Order #{order['number']}, {euro(wo.price_due(order))}: "
                                           f"the customer has picked it up and paid?"):
            return
        self.finish(order, False)

    def cancel(self, order):
        if not messagebox.askyesno(parent=self.win, title="ORCA",
                                   message=f"Cancel order #{order['number']}? Its folder is kept in the customer's "
                                           f"folder, marked cancelled, and the number is free again."):
            return
        self.finish(order, True)

    def finish(self, order, cancelled):
        try:
            wo.finish(order, cancelled)
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="ORCA",
                                   message=f"Could not move the order folder (is a file in it open?).\n\n{e}")
        self.signature = None


class PriceDialog:
    def __init__(self, screen, order):
        self.screen, self.order = screen, order
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(f"ORCA - #{order['number']} price")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=18)
        f.grid()
        ttk.Label(f, text=f"Calculated price: {euro(order['total'])}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="Changed price (EUR, empty = calculated):").grid(row=1, column=0, sticky="w", pady=6)
        self.var = tk.StringVar(value="" if order.get("changed_total") is None else f"{order['changed_total']:.2f}")
        ttk.Entry(f, textvariable=self.var, width=10, font=FONT).grid(row=1, column=1, sticky="w", padx=6)
        self.error = ttk.Label(f, text="", foreground=theme.ERROR)
        self.error.grid(row=2, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.save).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def save(self):
        try:
            value = parse_money(self.var.get())
        except ValueError:
            self.error.config(text="Not an amount in EUR.")
            return
        wo.change_price(self.order, value)
        self.screen.signature = None
        self.dlg.destroy()


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
