"""Inventory management's screens (2026-11-19_03): the Inventory table, an item, Delivery / Used / Count, History,
Sell, Import list. The data and the rules are in inventory.py.

A USB barcode scanner types the code fast and ends with Enter: ScanCatcher tells it from a person typing (the keys
arrive within a few milliseconds of each other) and hands the code to the screen.
"""
import csv
import datetime
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import costs
import filedrop
import inventory as inv
import shopify_stock as shop
import theme
import walkin_prices
import walkin_pricing as P
from walkin_screens import FONT, Screen, euro, rounding_buttons

SCAN_GAP = 0.06  # seconds between a scanner's keys (people are slower)


class ScanCatcher:
    """Collects fast key presses anywhere in a window; Enter after at least 4 of them is a scan: on_scan(code)."""

    def __init__(self, win, on_scan):
        self.on_scan, self.keys, self.last = on_scan, "", 0.0
        win.bind_all("<Key>", self.key, add="+")
        self.win = win

    def key(self, event):
        try:
            if event.widget.winfo_toplevel() is not self.win:
                return
        except (tk.TclError, AttributeError):
            return
        t = time.monotonic()
        if event.keysym in ("Return", "KP_Enter"):
            code, self.keys = self.keys, ""
            if len(code) >= 4 and t - self.last < 0.3:
                self.on_scan(code)
                return "break"
            return None
        if len(event.char) == 1 and event.char.isprintable():
            if t - self.last > SCAN_GAP:
                self.keys = ""
            self.keys += event.char
            self.last = t
        return None


def ask_password(parent):
    """The Prices password (sale prices are fixed; Tesla, 2026-11-17)."""
    return costs.ask_to_open(parent)


# ------------------------------------------------------------------ the Inventory screen

class InventoryScreen(Screen):
    COLUMNS = (("name", "Name", 250), ("category", "Category", 120), ("barcode", "Barcode", 130),
               ("stock", "In stock", 125), ("minimum", "Minimum", 85), ("price", "Sale price", 90),
               ("display", "On display", 85), ("shelf", "On shelf", 75), ("storage", "In storage", 85),
               ("status", "Status", 200))

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Inventory management", on_back, size="1300x880")
        self.inventory = inv.Inventory()
        self.prices_open = False  # the Prices password was given on this screen
        self.sort_key, self.sort_rev = None, False
        top = self.top
        ttk.Label(top, text="Search:").pack(side="left", padx=(40, 6))
        self.search = tk.StringVar()
        self.search_box = ttk.Entry(top, textvariable=self.search, width=26, font=FONT)
        self.search_box.pack(side="left")
        self.search_box.bind("<Return>", lambda _: self.search_enter())
        self.search.trace_add("write", lambda *_: self.fill())
        ttk.Label(top, text="Category:").pack(side="left", padx=(16, 6))
        self.category = tk.StringVar(value="All")
        self.category_box = ttk.Combobox(top, textvariable=self.category, state="readonly", width=18, font=FONT)
        self.category_box.pack(side="left")
        self.category_box.bind("<<ComboboxSelected>>", lambda _: self.fill())
        f = self.frame
        f.rowconfigure(2, weight=1)
        self.totals = ttk.Label(f, text="", style="Small.TLabel")
        self.totals.grid(row=1, column=0, sticky="w", pady=(8, 4))
        box = ttk.Frame(f)
        box.grid(row=2, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(box, columns=[c for c, _, _ in self.COLUMNS], show="headings", selectmode="browse")
        for key, text, width in self.COLUMNS:
            self.tree.heading(key, text=text, anchor="w", command=lambda k=key: self.sort(k))
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("low", foreground=theme.ERROR)
        self.tree.tag_configure("gone", foreground=theme.MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        bar = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<Double-1>", lambda _: self.edit())
        row = ttk.Frame(f)
        row.grid(row=3, column=0, sticky="we", pady=(10, 0))
        for text, command in (("Delivery…", self.delivery), ("Used / broken…", self.used), ("Count…", self.count),
                              ("On display…", self.on_display), ("History…", self.history), ("Edit…", self.edit),
                              ("Remove", self.remove)):
            ttk.Button(row, text=text, command=command).pack(side="left", padx=(0, 8))
        self.message = ttk.Label(f, text="", style="Small.TLabel")
        self.message.grid(row=4, column=0, sticky="w", pady=(6, 0))
        # 2026-11-19_09: Shopify's stock at the end of the day, and what to bring from storage to the shelves; the
        # list buttons and Sell on the same row, right (two rows fit a 1366 screen)
        day = ttk.Frame(f)
        day.grid(row=5, column=0, sticky="we", pady=(6, 0))
        right = ttk.Frame(day)
        right.pack(side="right")
        for text, command, style in (("Add item…", self.add, None), ("Import list…", self.import_list, None),
                                     ("Export list…", self.export, None), ("Sell", self.sell, "Print.TButton")):
            b = ttk.Button(right, text=text, command=command, style=style or "TButton")
            b.pack(side="left", padx=(8, 0))
            if text == "Import list…":
                filedrop.target(b, lambda paths, x, y: self.dropped(paths))
        end_btn = ttk.Button(day, text="End of day: load Shopify stock…", command=self.load_shopify)
        end_btn.pack(side="left")
        ttk.Button(day, text="Restock", command=self.restock).pack(side="left", padx=(8, 0))
        # The drop box (2026-11-19_10, Tesla: "make it drag and drop"): the Shopify export runs the end-of-day load,
        # any other .csv / .xlsx Import list. Dropping on those two buttons does the same.
        self.drop_box = tk.Label(day, text="⤓  Drop the Shopify stock file or an item list here", background=theme.FIELD,
                                 foreground=theme.TEXT, font=("Segoe UI", 11), padx=14, pady=6, highlightthickness=2,
                                 highlightbackground=theme.PRIMARY, highlightcolor=theme.PRIMARY)
        self.drop_box.pack(side="left", padx=(16, 0))
        filedrop.target(self.drop_box, lambda paths, x, y: self.dropped(paths))
        filedrop.target(end_btn, lambda paths, x, y: self.dropped(paths))
        self.restock_line = ttk.Label(day, text="", style="Warn.TLabel")
        self.restock_line.pack(side="left", padx=(16, 0))
        ttk.Label(f, text="Shopify items: the next end-of-day load replaces ORCA's own stock changes for them "
                          "(Delivery, Count, Sell); Shopify's number wins.", style="Small.TLabel").grid(
            row=6, column=0, sticky="w", pady=(4, 0))
        self.scan = ScanCatcher(self.win, self.scanned)
        self.fill()
        self.ready()

    # -------------------------------------------------------------- the table
    def visible(self):
        text, cat = self.search.get().strip().lower(), self.category.get()
        out = []
        for it in self.inventory.items:
            if cat not in ("All", "") and (it.get("category") or "") != cat:
                continue
            if text and text not in it["name"].lower() and not any(text in b for b in it.get("barcodes", [])):
                continue
            out.append(it)
        if self.sort_key is None:  # Order more first, then by name
            low = {it["id"] for it in self.inventory.low()}
            return sorted(out, key=lambda it: (it["id"] not in low, it["name"].lower()))
        key = {"name": lambda it: it["name"].lower(), "category": lambda it: (it.get("category") or "").lower(),
               "barcode": lambda it: ",".join(it.get("barcodes", [])), "stock": lambda it: it.get("stock", 0),
               "minimum": lambda it: it.get("minimum") if it.get("minimum") is not None else -1,
               "price": lambda it: it.get("price") if it.get("price") is not None else -1,
               "status": lambda it: self.status(it),
               "display": lambda it: it.get("display") if it.get("display") is not None else -1,
               "shelf": lambda it: it.get("shelf") if it.get("shelf") is not None else -1,
               "storage": lambda it: shop.storage(it)}[self.sort_key]
        return sorted(out, key=key, reverse=self.sort_rev)

    def sort(self, key):
        self.sort_rev = (not self.sort_rev) if self.sort_key == key else False
        self.sort_key = key
        self.fill()

    @staticmethod
    def status(it):
        if it.get("gone"):
            return "Not in Shopify any more"
        if it.get("stock", 0) < 0:
            return "Count it"
        if it.get("minimum") is not None and it.get("stock", 0) < it["minimum"]:
            return "Order more"
        return ""

    def fill(self, select=None):
        keep = select or (self.tree.selection()[0] if self.tree.selection() else None)
        self.tree.delete(*self.tree.get_children())
        cats = self.inventory.categories()
        self.category_box.config(values=["All"] + cats)
        for it in self.visible():
            status = self.status(it)
            shown = it.get("display") is not None
            values = (it["name"], it.get("category") or "", ", ".join(it.get("barcodes", [])), inv.qty_text(it),
                      inv.qty_text(it, it["minimum"]) if it.get("minimum") is not None else "",
                      euro(it["price"]) if it.get("price") is not None else "not for sale",
                      it["display"] if shown else "", (it.get("shelf") or 0) if shown else "",
                      shop.storage(it) if shown else "", status)
            tag = ("gone",) if it.get("gone") else ("low",) if status else ()
            self.tree.insert("", "end", iid=it["id"], values=values, tags=tag)
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)
        low = len(self.inventory.low())
        self.totals.config(text=f"{len(self.inventory.items)} items   ·   {low} to order")
        n = len(shop.restock_lines(self.inventory))
        try:
            self.restock_line.config(text=f"Restock: {n} item{'' if n == 1 else 's'}" if n else "")
        except AttributeError:
            pass

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning(parent=self.win, title="Inventory", message="Select an item first.")
            return None
        return self.inventory.get(sel[0])

    def reload(self, select=None):
        self.inventory.data = inv.Inventory.load()  # in place: dialogs holding it see the change too
        self.fill(select)

    # -------------------------------------------------------------- scanning
    def scanned(self, code):
        """A scan anywhere on this screen selects the item; an unknown code offers a new item."""
        item = self.inventory.by_barcode(code)
        if item is None:
            if messagebox.askyesno(parent=self.win, title="Inventory",
                                   message=f"No item with barcode {code}. Add a new item with it?"):
                ItemDialog(self, None, barcode=code)
            return
        self.search.set("")
        self.category.set("All")
        self.fill(select=item["id"])
        self.message.config(text=f"Scanned: {item['name']}")

    def search_enter(self):
        code = self.search.get().strip()
        if self.inventory.by_barcode(code):
            self.scanned(code)

    # -------------------------------------------------------------- the buttons
    def add(self):
        ItemDialog(self, None)

    def edit(self):
        item = self.selected()
        if item:
            ItemDialog(self, item["id"])

    def remove(self):
        item = self.selected()
        if item is None:
            return
        if not self.prices_open and not ask_password(self.win):
            return
        self.prices_open = True
        if not messagebox.askyesno(parent=self.win, title="Inventory",
                                   message=f"Remove “{item['name']}” from Inventory? Its history stays in the log."):
            return
        self.inventory.remove(item["id"])
        self.reload()

    def delivery(self):
        item = self.selected()
        if item:
            QtyDialog(self, item, "delivery")

    def used(self):
        item = self.selected()
        if item:
            QtyDialog(self, item, "used")

    def count(self):
        item = self.selected()
        if item:
            QtyDialog(self, item, "count")

    def on_display(self):
        item = self.selected()
        if item:
            DisplayDialog(self, item)

    def restock(self):
        RestockWindow(self)

    def load_shopify(self, path=None):
        """End of day: load Shopify stock (a CSV exported from Shopify), then show Sold / Came in and the restock
        list."""
        if not path:
            import walkin_screens
            picked = walkin_screens.choose_files(self.win, False, "Load Shopify stock",
                                                 [("Shopify inventory export", "*.csv"), ("All files", "*.*")])
            path = picked[0] if picked else None
        if not path:
            return None
        older = shop.older_than_last(self.inventory, path)
        if older and not messagebox.askyesno(parent=self.win, title="Inventory",
                                             message=f"This file is older than the last one loaded ({older}). "
                                                     f"Load it anyway?"):
            return None
        take_over = True
        if shop.last_load(self.inventory) is None:
            try:
                export, _ = shop.read_export(path)
            except (OSError, ValueError) as e:
                messagebox.showwarning(parent=self.win, title="Inventory", message=str(e))
                return None
            matches = shop.matches_for_first_load(self.inventory, export)
            if matches:
                take_over = messagebox.askyesno(
                    parent=self.win, title="Inventory",
                    message=f"{len(matches)} items already in Inventory match Shopify products (by barcode or name). "
                            f"Join them, so they follow Shopify's stock from now on?")
        try:
            result = shop.load(self.inventory, path, take_over=take_over)
        except (OSError, ValueError) as e:
            messagebox.showwarning(parent=self.win, title="Inventory", message=str(e))
            return None
        self.reload()
        LoadReport(self, result)
        return result

    def history(self):
        item = self.selected()
        if item:
            HistoryDialog(self, item)

    def export(self):
        path = filedialog.asksaveasfilename(parent=self.win, title="Export list", defaultextension=".csv",
                                            initialfile=f"Inventory {datetime.date.today()}.csv",
                                            filetypes=[("CSV (Excel)", "*.csv")])
        if path:
            export_csv(self.inventory, path)
            self.message.config(text=f"Exported to {path}")

    def import_list(self):
        import walkin_screens
        paths = walkin_screens.choose_files(self.win, False, "Import list",
                                            [("Spreadsheets", "*.xlsx *.csv"), ("All files", "*.*")])
        if paths:
            ImportDialog(self, paths[0])

    def dropped(self, paths):
        """A file dropped on the box (or the End of day / Import list buttons): a Shopify export runs the end-of-day
        load, any other .csv or .xlsx Import list. One file at a time; folders, empty files and other types are
        refused with a message, changing nothing."""
        why = drop_problem(paths)
        if why:
            messagebox.showwarning(parent=self.win, title="Inventory", message=why)
            return None
        path = paths[0]
        if is_shopify_file(path):
            return self.load_shopify(path)
        return ImportDialog(self, path)

    def sell(self):
        self.win.withdraw()
        SellScreen(self.ctx, on_back=self.back_from_sell)

    def back_from_sell(self):
        self.reload()
        self.show()

    def back(self):
        self.win.unbind_all("<Key>")
        super().back()


def drop_problem(paths):
    """Why dropped files can't be used on the Inventory screen, or None (2026-11-19_10)."""
    import os
    if len(paths) != 1:
        return "Drop one file at a time."
    p = Path(paths[0])
    if p.is_dir():
        return f"{p.name} is a folder: drop the file itself."
    if p.suffix.lower() not in (".csv", ".xlsx"):
        return f"{p.name}: drop a .csv or .xlsx file."
    try:
        if os.path.getsize(p) == 0:
            return f"{p.name} is empty."
    except OSError as e:
        return f"{p.name} can't be read ({type(e).__name__})."
    return None


def is_shopify_file(path):
    """A Shopify inventory export (the columns Handle, Title, SKU, On hand (current)), read from its first line."""
    if not str(path).lower().endswith(".csv"):
        return False
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f), [])
    except (OSError, UnicodeDecodeError):
        return False
    return shop.is_shopify(header)


def export_csv(inventory, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Name", "Category", "Barcode", "Unit", "In stock", "Minimum", "Sale price", "Linked to", "Notes"])
        for it in inventory.items:
            w.writerow([it["name"], it.get("category") or "", " ".join(it.get("barcodes", [])), it.get("unit") or "",
                        it.get("stock", 0), "" if it.get("minimum") is None else it["minimum"],
                        "" if it.get("price") is None else f"{it['price']:.2f}", inv.link_text(it.get("link")),
                        it.get("notes") or ""])


# ------------------------------------------------------------------ one item

class ItemDialog:
    def __init__(self, screen, item_id, barcode=None):
        self.screen, self.item_id = screen, item_id
        it = screen.inventory.get(item_id) if item_id else {}
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Edit item" if item_id else "Add item")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        self.choices = inv.link_choices(walkin_prices.current())
        link_texts = ["None"] + [t for t, _ in self.choices]
        self.vars = {"name": tk.StringVar(value=it.get("name", "")),
                     "category": tk.StringVar(value=it.get("category", "")),
                     "barcodes": tk.StringVar(value=" ".join(it.get("barcodes", [barcode] if barcode else []))),
                     "unit": tk.StringVar(value=it.get("unit", "piece")),
                     "per_unit": tk.StringVar(value=str(it.get("per_unit", 1))),
                     "stock": tk.StringVar(value=str(it.get("stock", 0))),
                     "minimum": tk.StringVar(value="" if it.get("minimum") is None else str(it["minimum"])),
                     "price": tk.StringVar(value="" if it.get("price") is None else f"{it['price']:.2f}"),
                     "link": tk.StringVar(value=inv.link_text(it.get("link")) or "None"),
                     "notes": tk.StringVar(value=it.get("notes", "")),
                     "display": tk.StringVar(value="" if it.get("display") is None else str(it["display"]))}
        self.price_before = it.get("price")
        rows = (("Name *", "name", ttk.Entry, {"width": 32}),
                ("Category", "category", ttk.Combobox, {"values": screen.inventory.categories(), "width": 30}),
                ("Barcodes (scan or type, spaces between)", "barcodes", ttk.Entry, {"width": 32}),
                ("Unit", "unit", ttk.Combobox, {"values": inv.UNITS, "width": 30}),
                ("Pieces in one unit (e.g. 500 sheets per ream)", "per_unit", ttk.Entry, {"width": 8}),
                ("In stock (pieces)" if item_id else "In stock now (pieces)", "stock", ttk.Entry, {"width": 8}),
                ("Minimum (pieces; empty: no warning)", "minimum", ttk.Entry, {"width": 8}),
                ("Sale price EUR (empty: not for sale)", "price", ttk.Entry, {"width": 10}),
                ("Goes down by itself with", "link", ttk.Combobox, {"values": link_texts, "width": 40,
                                                                    "state": "readonly"}),
                ("Notes", "notes", ttk.Entry, {"width": 40}),
                ("On display (empty: not restocked daily)", "display", ttk.Entry, {"width": 8}))
        for r, (label, key, cls, opts) in enumerate(rows):
            ttk.Label(f, text=label + ":").grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
            w = cls(f, textvariable=self.vars[key], font=FONT, **opts)
            w.grid(row=r, column=1, sticky="w", pady=3)
            if key == "stock" and item_id:
                w.state(["disabled"])  # changed with Delivery, Used / broken and Count, which are logged
            if key == "price":
                self.price_entry = w
        self.price_note = ttk.Label(f, text="", style="Hint.TLabel")
        self.price_note.grid(row=len(rows), column=1, sticky="w")
        if not screen.prices_open:
            self.price_entry.state(["disabled"])
            ttk.Button(f, text="Unlock sale price…", command=self.unlock).grid(row=len(rows), column=0, sticky="w")
            self.price_note.config(text="Sale prices need the Prices password.")
        self.error = ttk.Label(f, text="", style="Bad.TLabel", wraplength=520, justify="left")
        self.error.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def unlock(self):
        if ask_password(self.dlg):
            self.screen.prices_open = True
            self.price_entry.state(["!disabled"])
            self.price_note.config(text="")

    def values(self):
        v = {k: var.get() for k, var in self.vars.items()}
        codes = [c for c in v["barcodes"].replace(",", " ").split() if c]
        link = next((l for t, l in self.choices if t == v["link"]), None)
        price = inv.number(v["price"], "Sale price", whole=False, low=0)
        if price != self.price_before and not self.screen.prices_open:
            raise ValueError("Sale price: needs the Prices password (Unlock sale price…).")
        self.display = inv.number(v["display"], "On display", low=0)
        return {"name": v["name"].strip(), "category": v["category"].strip(), "barcodes": codes,
                "unit": v["unit"].strip() or "piece", "per_unit": inv.number(v["per_unit"], "Pieces in one unit", low=1) or 1,
                "stock": inv.number(v["stock"], "In stock") or 0,
                "minimum": inv.number(v["minimum"], "Minimum", low=0), "price": price, "link": link,
                "notes": v["notes"].strip()}

    def done(self):
        try:
            values = self.values()
            if self.item_id:
                values.pop("stock")
                self.screen.inventory.edit(self.item_id, values)
                item_id = self.item_id
            else:
                item_id = self.screen.inventory.add(values)["id"]
            shop.set_display(self.screen.inventory, item_id, self.display)  # logged when it changes
        except ValueError as e:
            self.error.config(text=str(e))
            return
        self.dlg.destroy()
        self.screen.reload(select=item_id)


class QtyDialog:
    """Delivery (+), Used / broken (-, with the reason) or Count (what is on the shelf). Units and loose pieces when
    one unit holds several. A delivery can also be scanned: each scan of the item's code adds one unit."""

    TITLES = {"delivery": "Delivery", "used": "Used / broken", "count": "Count"}

    def __init__(self, screen, item, mode):
        self.screen, self.item, self.mode = screen, item, mode
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(self.TITLES[mode])
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        ttk.Label(f, text=item["name"], style="Head.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f, text=f"In stock: {inv.qty_text(item)}", style="Hint.TLabel").grid(row=1, column=0, columnspan=3,
                                                                                         sticky="w", pady=(0, 8))
        per = max(1, int(item.get("per_unit") or 1))
        what = {"delivery": "Delivered:", "used": "Used / broken:", "count": "On the shelf:"}[mode]
        ttk.Label(f, text=what).grid(row=2, column=0, sticky="w")
        self.units = tk.StringVar(value="")
        e = ttk.Entry(f, textvariable=self.units, width=8, font=FONT)
        e.grid(row=2, column=1, sticky="w", padx=6)
        e.focus_set()
        ttk.Label(f, text=item.get("unit") or "piece").grid(row=2, column=2, sticky="w")
        self.loose = tk.StringVar(value="")
        if per > 1:
            ttk.Label(f, text="and loose pieces:").grid(row=3, column=0, sticky="w")
            ttk.Entry(f, textvariable=self.loose, width=8, font=FONT).grid(row=3, column=1, sticky="w", padx=6, pady=3)
        self.reason = tk.StringVar(value="used")
        if mode == "used":
            r = ttk.Frame(f)
            r.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
            for value in ("used", "broken"):
                ttk.Radiobutton(r, text=value.capitalize(), value=value, variable=self.reason).pack(side="left",
                                                                                                    padx=(0, 12))
        if mode == "delivery":
            ttk.Label(f, text="Or scan the item's code once per unit delivered.", style="Hint.TLabel").grid(
                row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))
            self.scan = ScanCatcher(dlg, self.scanned)
        self.error = ttk.Label(f, text="", style="Bad.TLabel")
        self.error.grid(row=6, column=0, columnspan=3, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=7, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        dlg.bind("<Return>", lambda _: self.done())
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def scanned(self, code):
        if code in self.item.get("barcodes", []):
            n = inv.number(self.units.get(), "units") or 0
            self.units.set(str(n + 1))
        else:
            self.error.config(text=f"{code} is another item's code (or none): not counted.")

    def pieces(self):
        per = max(1, int(self.item.get("per_unit") or 1))
        units = inv.number(self.units.get(), "How many", low=0) or 0
        loose = inv.number(self.loose.get(), "Loose pieces", low=0) or 0
        return units * per + loose

    def done(self):
        try:
            n = self.pieces()
        except ValueError as e:
            self.error.config(text=str(e))
            return
        inventory = self.screen.inventory
        if self.mode == "delivery":
            inventory.change(self.item["id"], n, "delivery")
        elif self.mode == "used":
            inventory.change(self.item["id"], -n, self.reason.get())
        else:
            inventory.count(self.item["id"], n)
        self.dlg.destroy()
        self.screen.reload(select=self.item["id"])


class HistoryDialog:
    def __init__(self, screen, item):
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(f"History: {item['name']}")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=16)
        f.grid(sticky="nsew")
        cols = (("time", "When", 170), ("change", "Change", 90), ("stock", "In stock", 90), ("reason", "Reason", 200),
                ("sale", "Sale", 80))
        tree = ttk.Treeview(f, columns=[c for c, _, _ in cols], show="headings", height=16)
        for key, text, width in cols:
            tree.heading(key, text=text, anchor="w")
            tree.column(key, width=width, anchor="w")
        for row in reversed(inv.read_log(item["id"])):
            tree.insert("", "end", values=(row["time"], row["change"], row["stock"], row["reason"], row["sale"]))
        tree.grid(row=0, column=0, sticky="nsew")
        ttk.Button(f, text="Close", command=dlg.destroy).grid(row=1, column=0, sticky="e", pady=(10, 0))
        theme.dark_title_bar(dlg)


# ------------------------------------------------------------------ Shopify, On display, Restock (2026-11-19_09)

def a4_pdf(path, title, lines):
    """A plain A4 PDF: the title and the lines (no money, no shop name, no ORCA, no PrintHub)."""
    from PIL import Image, ImageDraw
    import receipt
    big, small = receipt._font(46, True), receipt._font(30)
    pages, page, y = [], None, 0
    for k, line in enumerate([None] + list(lines)):
        if page is None or y > 1680:
            page = Image.new("L", (1240, 1754), 255)
            pages.append(page)
            y = 100
        d = ImageDraw.Draw(page)
        if line is None:
            d.text((90, y), title, font=big, fill=0)
            y += 90
            continue
        d.text((90, y), line, font=small, fill=0)
        y += 44
    pages[0].save(path, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    return path


def print_lines(ctx, header, lines, path):
    """The XP-80C, as the copy counter's receipt: the date and the lines only."""
    import printing
    import receipt
    receipt.lines_pdf(path, header, [(line, "") for line in lines], None)
    printing.send(path, ctx.rules["receipt_printer"])
    return path


class DisplayDialog:
    """On display… for the selected item (scan it first): the number shown on the shelf, empty = not restocked."""

    def __init__(self, screen, item):
        self.screen, self.item = screen, item
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("On display")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        ttk.Label(f, text=item["name"], style="Head.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(f, text="On display (empty: not restocked daily):").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.var = tk.StringVar(value="" if item.get("display") is None else str(item["display"]))
        e = ttk.Entry(f, textvariable=self.var, width=8, font=FONT)
        e.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        e.focus_set()
        self.error = ttk.Label(f, text="", style="Bad.TLabel")
        self.error.grid(row=2, column=0, columnspan=2, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="OK", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        dlg.bind("<Return>", lambda _: self.done())
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def done(self):
        try:
            amount = inv.number(self.var.get(), "On display", low=0)
        except ValueError as e:
            self.error.config(text=str(e))
            return
        shop.set_display(self.screen.inventory, self.item["id"], amount)
        self.dlg.destroy()
        self.screen.reload(select=self.item["id"])


class LoadReport:
    """After a load: "Since 18 Nov 19:02", Sold and Came in (sortable), new and gone items; Print / Save PDF; then the
    restock list."""

    def __init__(self, screen, result):
        self.screen, self.result = screen, result
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("End of day: Shopify stock")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=16)
        f.grid(sticky="nsew")
        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(0, weight=1)
        ttk.Label(f, text=shop.since_text(result), style="Big.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        extra = f"{result['items']} products loaded"
        if result["new"]:
            extra += f"   ·   new in Shopify: {len(result['new'])}"
        if result["gone"]:
            extra += f"   ·   not in Shopify any more: {len(result['gone'])}"
        if result["locations"] > 1:
            extra += f"   ·   stock added up over {result['locations']} locations"
        ttk.Label(f, text=extra, style="Small.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        self.trees = {}
        for c, (key, title) in enumerate((("sold", "Sold"), ("came", "Came in"))):
            ttk.Label(f, text=f"{title} ({len(result[key])})", style="Head.TLabel").grid(row=2, column=c, sticky="w")
            tree = ttk.Treeview(f, columns=("name", "n"), show="headings", height=16)
            tree.heading("name", text="Item", anchor="w", command=lambda k=key: self.sort(k, 0))
            tree.heading("n", text="How many", anchor="w", command=lambda k=key: self.sort(k, 1))
            tree.column("name", width=360, anchor="w")
            tree.column("n", width=90, anchor="w")
            tree.grid(row=3, column=c, sticky="nsew", padx=(0, 12))
            self.trees[key] = tree
            self.rows = getattr(self, "rows", {})
            self.rows[key] = list(result[key])
            self.fill(key)
        f.rowconfigure(3, weight=1)
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        if screen.ctx.rules.get("receipt_printer"):
            ttk.Button(b, text="Print", command=self.print_receipt).pack(side="left")
        ttk.Button(b, text="Save PDF…", command=self.save_pdf).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Restock list", command=lambda: RestockWindow(screen)).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Close", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        if shop.restock_lines(screen.inventory):
            dlg.after(200, lambda: RestockWindow(screen))

    def sort(self, key, col):
        rev = getattr(self, "_rev", {}).get((key, col), False)
        self.rows[key].sort(key=lambda r: (r[col].lower() if col == 0 else r[col]), reverse=rev)
        self._rev = dict(getattr(self, "_rev", {}), **{(key, col): not rev})
        self.fill(key)

    def fill(self, key):
        tree = self.trees[key]
        tree.delete(*tree.get_children())
        for name, n in self.rows[key]:
            tree.insert("", "end", values=(name, n))

    def lines(self):
        out = [shop.since_text(self.result), "", f"Sold ({len(self.rows['sold'])})"]
        out += [f"  {name}: {n}" for name, n in self.rows["sold"]] or ["  nothing"]
        out += ["", f"Came in ({len(self.rows['came'])})"]
        out += [f"  {name}: {n}" for name, n in self.rows["came"]] or ["  nothing"]
        return out

    def print_receipt(self, path=None):
        import walkin_print
        path = path or walkin_print.WORK_DIR / "shopify_report.pdf"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return print_lines(self.screen.ctx, [datetime.datetime.now().strftime("%d/%m/%Y  %H:%M")], self.lines(), path)

    def save_pdf(self, path=None):
        path = path or filedialog.asksaveasfilename(parent=self.dlg, title="Save PDF", defaultextension=".pdf",
                                                    initialfile=f"Sold {datetime.date.today()}.pdf",
                                                    filetypes=[("PDF", "*.pdf")])
        if path:
            a4_pdf(path, f"End of day {datetime.datetime.now():%d/%m/%Y %H:%M}", self.lines())
        return path


class RestockWindow:
    """What to bring from storage to the shelves: one line per item, Restocked per line, All restocked; Print on the
    XP-80C or Save an A4 PDF (the date and the lines only)."""

    def __init__(self, screen):
        self.screen = screen
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Restock")
        dlg.transient(screen.win)
        self.body = ttk.Frame(dlg, padding=16)
        self.body.grid(sticky="nsew")
        theme.dark_title_bar(dlg)
        self.fill()

    def fill(self):
        for w in self.body.winfo_children():
            w.destroy()
        lines = shop.restock_lines(self.screen.inventory)
        ttk.Label(self.body, text=f"Restock ({len(lines)})", style="Big.TLabel").grid(row=0, column=0, sticky="w")
        if not lines:
            ttk.Label(self.body, text="Every shelf is full.", style="Hint.TLabel").grid(row=1, column=0, sticky="w")
        cat = None
        r = 1
        for it, bring, kind, text in lines:
            if (it.get("category") or "") != cat:
                cat = it.get("category") or ""
                ttk.Label(self.body, text=cat or "No category", style="Head.TLabel").grid(row=r, column=0, sticky="w",
                                                                                            pady=(8, 0))
                r += 1
            style = {"ok": "TLabel", "short": "Warn.TLabel", "order": "Bad.TLabel"}[kind]
            ttk.Label(self.body, text=text, style=style).grid(row=r, column=0, sticky="w", padx=(12, 12))
            if bring > 0:
                ttk.Button(self.body, text="Restocked", command=lambda i=it["id"]: self.done(i)).grid(
                    row=r, column=1, sticky="w", pady=1)
            r += 1
        b = ttk.Frame(self.body)
        b.grid(row=r, column=0, columnspan=2, sticky="e", pady=(12, 0))
        if lines:
            ttk.Button(b, text="All restocked", style="Print.TButton", command=self.all_done).pack(side="left")
            if self.screen.ctx.rules.get("receipt_printer"):
                ttk.Button(b, text="Print", command=self.print_receipt).pack(side="left", padx=(8, 0))
            ttk.Button(b, text="Save PDF…", command=self.save_pdf).pack(side="left", padx=(8, 0))
        ttk.Button(b, text="Close", command=self.dlg.destroy).pack(side="left", padx=(8, 0))

    def done(self, item_id):
        shop.restocked(self.screen.inventory, item_id)
        self.screen.reload()
        self.fill()

    def all_done(self):
        for it, bring, _, _ in shop.restock_lines(self.screen.inventory):
            if bring > 0:
                shop.restocked(self.screen.inventory, it["id"])
        self.screen.reload()
        self.fill()

    def lines(self):
        return [text for _, _, _, text in shop.restock_lines(self.screen.inventory)]

    def print_receipt(self, path=None):
        import walkin_print
        path = path or walkin_print.WORK_DIR / "restock.pdf"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return print_lines(self.screen.ctx, [datetime.datetime.now().strftime("%d/%m/%Y  %H:%M"), "Restock"],
                           self.lines(), path)

    def save_pdf(self, path=None):
        path = path or filedialog.asksaveasfilename(parent=self.dlg, title="Save PDF", defaultextension=".pdf",
                                                    initialfile=f"Restock {datetime.date.today()}.pdf",
                                                    filetypes=[("PDF", "*.pdf")])
        if path:
            a4_pdf(path, f"Restock {datetime.datetime.now():%d/%m/%Y %H:%M}", self.lines())
        return path


# ------------------------------------------------------------------ Sell

class SellScreen(Screen):
    """Scan or search items into a basket; the total from each item's sale price, rounding; Done takes them off
    stock and writes the sale (Walk-in\\sales_log.csv, source shop); Print receipt; Cancel."""

    def __init__(self, ctx, on_back):
        super().__init__(ctx, "Sell", on_back, size="1100x820")
        self.inventory = inv.Inventory()
        self.basket = []  # [{"id", "qty"}]
        self.rounding = None
        f = self.frame
        f.rowconfigure(3, weight=1)
        row = ttk.Frame(f)
        row.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(row, text="Scan, or type a name:").pack(side="left")
        self.entry_var = tk.StringVar()
        self.entry = ttk.Combobox(row, textvariable=self.entry_var, width=36, font=FONT,
                                  values=sorted(it["name"] for it in self.inventory.items))
        self.entry.pack(side="left", padx=8)
        self.entry.bind("<Return>", lambda _: self.add_typed())
        self.entry.bind("<<ComboboxSelected>>", lambda _: self.add_typed())
        ttk.Button(row, text="Add", command=self.add_typed).pack(side="left")
        self.message = ttk.Label(f, text="", style="Bad.TLabel")
        self.message.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.lines = costs.ScrollFrame(f)
        self.lines.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        totals = ttk.Frame(f)
        totals.grid(row=4, column=0, sticky="e", pady=(10, 0))
        ttk.Label(totals, text="Round the total:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        rb, self.round_buttons = rounding_buttons(totals, self.set_rounding)
        rb.grid(row=0, column=1, sticky="w")
        self.total_label = ttk.Label(totals, text="", style="Big.TLabel")
        self.total_label.grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))
        buttons = ttk.Frame(f)
        buttons.grid(row=5, column=0, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="left", padx=(0, 8))
        self.receipt_btn = None
        if ctx.rules.get("receipt_printer"):
            self.receipt_btn = ttk.Button(buttons, text="Print receipt", command=self.print_receipt)
            self.receipt_btn.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Done", style="Print.TButton", command=self.done).pack(side="left")
        self.scan = ScanCatcher(self.win, self.scanned)
        self.show_basket()
        self.ready()
        self.entry.focus_set()

    # -------------------------------------------------------------- the basket
    def scanned(self, code):
        item = self.inventory.by_barcode(code)
        if item is None:
            self.message.config(text=f"No item with barcode {code}: add it in Inventory first.")
            return
        self.add(item)
        self.entry_var.set("")

    def add_typed(self):
        text = self.entry_var.get().strip()
        if not text:
            return
        item = self.inventory.by_barcode(text) or self.inventory.by_name(text)
        if item is None:
            matches = [it for it in self.inventory.items if text.lower() in it["name"].lower()]
            item = matches[0] if len(matches) == 1 else None
            if item is None:
                self.message.config(text=f"“{text}”: no single item matches. Pick it from the list." if matches else
                                    f"“{text}”: no item with that name or barcode.")
                return
        self.add(item)
        self.entry_var.set("")

    def add(self, item):
        """The same item again adds 1. Not for sale (no sale price): refused."""
        if item.get("price") is None:
            self.message.config(text=f"{item['name']}: no sale price: set it in Inventory.")
            return
        self.message.config(text="")
        for line in self.basket:
            if line["id"] == item["id"]:
                line["qty"] += 1
                break
        else:
            self.basket.append({"id": item["id"], "qty": 1})
        self.show_basket()

    def set_qty(self, index, qty):
        if 0 <= index < len(self.basket):
            if qty <= 0:
                del self.basket[index]
            else:
                self.basket[index]["qty"] = qty
        self.show_basket()

    def priced(self):
        rows = []
        for line in self.basket:
            it = self.inventory.get(line["id"])
            rows.append((it, line["qty"], P.r2(line["qty"] * it["price"])))
        total = P.r2(sum(r[2] for r in rows))
        return rows, total, P.rounded(total, self.rounding)

    def show_basket(self):
        for w in self.lines.inner.winfo_children():
            w.destroy()
        rows, total, due = self.priced()
        for c, (text, width) in enumerate((("Item", 36), ("Quantity", 18), ("Price", 12), ("Total", 12), ("", 4))):
            ttk.Label(self.lines.inner, text=text, style="Head.TLabel", width=width).grid(row=0, column=c, sticky="w")
        for k, (it, qty, amount) in enumerate(rows, start=1):
            short = it.get("stock", 0) - qty < 0
            ttk.Label(self.lines.inner, text=it["name"] + ("   count it" if short else ""),
                      style="Bad.TLabel" if short else "TLabel").grid(row=k, column=0, sticky="w", pady=2)
            q = ttk.Frame(self.lines.inner)
            q.grid(row=k, column=1, sticky="w")
            ttk.Button(q, text="−", width=3, command=lambda i=k - 1, n=qty: self.set_qty(i, n - 1)).pack(side="left")
            var = tk.StringVar(value=str(qty))
            e = ttk.Entry(q, textvariable=var, width=5, font=FONT)
            e.pack(side="left", padx=4)
            e.bind("<Return>", lambda _e, i=k - 1, v=var: self.set_qty(i, int(v.get()) if v.get().isdigit() else 0))
            e.bind("<FocusOut>", lambda _e, i=k - 1, v=var: self.typed_qty(i, v.get()))
            ttk.Button(q, text="+", width=3, command=lambda i=k - 1, n=qty: self.set_qty(i, n + 1)).pack(side="left")
            ttk.Label(self.lines.inner, text=euro(it["price"])).grid(row=k, column=2, sticky="w")
            ttk.Label(self.lines.inner, text=euro(amount)).grid(row=k, column=3, sticky="w")
            ttk.Button(self.lines.inner, text="✕", width=3, command=lambda i=k - 1: self.set_qty(i, 0)).grid(
                row=k, column=4, sticky="w")
        if not rows:
            ttk.Label(self.lines.inner, text="Scan an item to start.", style="Hint.TLabel").grid(
                row=1, column=0, sticky="w", pady=6)
        text = (f"Total: {euro(total)}" if abs(due - total) < 0.005 else
                f"Total: {euro(due)} (rounded {'up' if due > total else 'down'} from {total:,.2f})")
        self.total_label.config(text=text)
        for mode, b in self.round_buttons.items():
            b.state(["pressed"] if mode == self.rounding else ["!pressed"])

    def typed_qty(self, index, text):
        if index < len(self.basket) and text.strip().isdigit() and int(text) != self.basket[index]["qty"]:
            self.set_qty(index, int(text))

    def set_rounding(self, mode):
        self.rounding = None if mode == self.rounding else mode
        self.show_basket()

    # -------------------------------------------------------------- done, receipt, cancel
    def short(self, rows):
        return "; ".join(f"{it['name']} x {qty}" for it, qty, _ in rows)

    def done(self):
        """Each item off stock (reason sold), a sales_log.csv line (source shop), the basket cleared."""
        import walkin_orders as wo
        rows, total, due = self.priced()
        if not rows:
            self.message.config(text="The basket is empty.")
            return
        sale = self.inventory.next_sale()
        for it, qty, _ in rows:
            self.inventory.change(it["id"], -qty, "sold", sale)
        wo.write_sales_line({"date": datetime.date.today().isoformat(), "order": sale, "status": "sold",
                             "items": self.short(rows), "paid": f"{due:.2f}", "source": "shop", "copier": ""})
        self.last_sale = sale
        self.basket, self.rounding = [], None
        self.inventory = inv.Inventory()
        self.show_basket()
        self.message.config(text=f"Sale {sale} done: {euro(due)}.", style="Good.TLabel")

    def receipt_rows(self, prices_on, when=None):
        rows, total, due = self.priced()
        when = when or datetime.datetime.now()
        header = [when.strftime("%d/%m/%Y  %H:%M")]
        lines = [(f"{it['name']} x {qty}", f"{amount:.2f}" if prices_on else "") for it, qty, amount in rows]
        return header, lines, (f"EUR {due:.2f}" if prices_on else None)

    def print_receipt(self, path=None):
        """XP-80C as the copy counter: the date and time, the lines; the total only with walkin_paper_prices."""
        import printing
        import receipt
        import walkin_print
        if not self.basket:
            self.message.config(text="The basket is empty.")
            return None
        header, rows, total = self.receipt_rows(walkin_print.paper_prices(self.ctx.rules))
        path = path or walkin_print.WORK_DIR / "sale_receipt.pdf"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        receipt.lines_pdf(path, header, rows, total)
        try:
            printing.send(path, self.ctx.rules["receipt_printer"])
            self.message.config(text="Receipt sent to the receipt printer.", style="Good.TLabel")
        except Exception as e:
            messagebox.showwarning(parent=self.win, title="Sell", message=f"The receipt didn't print.\n\n{e}")
        return path

    def cancel(self):
        if self.basket and not messagebox.askyesno(parent=self.win, title="Sell", message="Empty the basket?"):
            return
        self.basket, self.rounding = [], None
        self.show_basket()

    def back(self):
        if self.basket and not messagebox.askyesno(parent=self.win, title="Sell",
                                                   message="The basket isn't sold. Leave it?"):
            return
        self.win.unbind_all("<Key>")
        super().back()


# ------------------------------------------------------------------ Import list

class ImportDialog:
    """Pick the sheet and which column is name, barcode, category, unit, in stock, minimum and sale price (guessed
    from the heading row); a preview of the first 20 rows; Import adds new items and, after asking once, updates
    the ones already there. Bad rows are listed and skipped. Sale prices need the Prices password."""

    def __init__(self, screen, path):
        self.screen, self.path = screen, path
        self.tables = inv.read_table(path)
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title(f"Import list: {Path(path).name}")
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=16)
        f.grid(sticky="nsew")
        self.f = f
        ttk.Label(f, text="Sheet:").grid(row=0, column=0, sticky="w")
        self.sheet = tk.StringVar(value=next(iter(self.tables), ""))
        sb = ttk.Combobox(f, textvariable=self.sheet, values=list(self.tables), state="readonly", width=24, font=FONT)
        sb.grid(row=0, column=1, sticky="w", pady=3)
        sb.bind("<<ComboboxSelected>>", lambda _: self.sheet_changed())
        self.cols = ttk.Frame(f)
        self.cols.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.preview = ttk.Treeview(f, show="headings", height=12)
        self.preview.grid(row=2, column=0, columnspan=4, sticky="we", pady=(10, 0))
        self.note = ttk.Label(f, text="", style="Hint.TLabel", wraplength=900, justify="left")
        self.note.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Import", style="Print.TButton", command=self.do).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        self.result = None
        self.sheet_changed()
        theme.dark_title_bar(dlg)

    def rows(self):
        return self.tables.get(self.sheet.get(), [])

    def sheet_changed(self):
        rows = self.rows()
        header = [str(h) for h in (rows[0] if rows else [])]
        guess = inv.guess_columns(header)
        for w in self.cols.winfo_children():
            w.destroy()
        names = ["(none)"] + [f"{chr(65 + i) if i < 26 else i + 1}: {h}" for i, h in enumerate(header)]
        self.col_vars = {}
        labels = {"name": "Name *", "barcode": "Barcode", "category": "Category", "unit": "Unit", "stock": "In stock",
                  "minimum": "Minimum", "price": "Sale price", "display": "On display"}
        for k, field in enumerate(inv.FIELDS):
            ttk.Label(self.cols, text=labels[field] + ":").grid(row=k // 4, column=(k % 4) * 2, sticky="e",
                                                               padx=(12, 4), pady=3)
            var = tk.StringVar(value=names[guess[field] + 1] if guess[field] is not None else "(none)")
            cb = ttk.Combobox(self.cols, textvariable=var, values=names, state="readonly", width=22, font=FONT)
            cb.grid(row=k // 4, column=(k % 4) * 2 + 1, sticky="w", pady=3)
            cb.bind("<<ComboboxSelected>>", lambda _: self.show_preview())
            self.col_vars[field] = (var, names)
        self.show_preview()

    def columns(self):
        out = {}
        for field, (var, names) in self.col_vars.items():
            i = names.index(var.get()) if var.get() in names else 0
            out[field] = i - 1 if i > 0 else None
        return out

    def show_preview(self):
        cols = self.columns()
        shown = [f for f in inv.FIELDS if cols[f] is not None]
        self.preview.config(columns=shown)
        for field in shown:
            self.preview.heading(field, text=field.capitalize(), anchor="w")
            self.preview.column(field, width=130, anchor="w")
        self.preview.delete(*self.preview.get_children())
        for row in self.rows()[1:21]:
            self.preview.insert("", "end", values=[row[cols[f]] if cols[f] < len(row) else "" for f in shown])
        new, update, bad = inv.plan_import(self.rows()[1:], cols, self.screen.inventory)
        self.plan = (new, update, bad)
        self.note.config(text=f"{len(new)} new, {len(update)} already in Inventory, {len(bad)} bad rows (skipped)"
                              + ("".join(f"\n{b}" for b in bad[:8])) + ("\n…" if len(bad) > 8 else ""))

    def do(self):
        if self.columns()["name"] is None:
            messagebox.showwarning(parent=self.dlg, title="Import", message="Pick which column is the name.")
            return
        new, update, bad = self.plan
        with_updates = True
        if update:
            with_updates = messagebox.askyesno(parent=self.dlg, title="Import",
                                               message=f"{len(update)} items are already in Inventory: update them?")
        has_prices = any("price" in x for x in new) or any("price" in x for _, x in update)
        with_prices = True
        if has_prices and not self.screen.prices_open:
            with_prices = ask_password(self.dlg)
            self.screen.prices_open = with_prices
        added, changed = inv.do_import(self.screen.inventory, new, update, with_prices, with_updates)
        self.result = (added, changed, bad)
        self.dlg.destroy()
        self.screen.reload()
        self.screen.message.config(text=f"Imported: {added} new, {changed} updated, {len(bad)} bad rows skipped"
                                        + ("" if with_prices or not has_prices else " (sale prices left out: no password)"))
