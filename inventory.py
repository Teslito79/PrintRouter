"""Inventory management (2026-11-19_03, Tesla: "track the inventory of the physical shop, including paper and every
other item in there"): items with barcodes, stock, a minimum, a sale price; a Sell screen; Import of a list.

Files (local, in ADMIN, gitignored, written safely):
- inventory.json: {"items": [...], "next_sale": n}. An item: id, name (unique), category, barcodes (each one belongs
  to one item only), unit, stock and minimum (in pieces: sheets for paper; may go below 0: "count it"), price (sale
  price, EUR, VAT included; None: not for sale), link, per_unit (pieces in one unit: 500 sheets per ream), notes.
- inventory_log.csv: one line per change (time, item id, name, change, stock, reason, sale).

Stock goes down by itself where ORCA knows (an item linked to a paper and size, the label sheet, lamination A4 / A3,
spiral binding or an envelope): walk-in paper at Pages collected, lamination / spiral / envelopes / label sheets at
Collected, the copy counter at Done, PrintHub products' paper at Pages collected. Each deduction happens once per
order part (kept in the order's own state). Stock never blocks printing: it is information only.
Sale prices are fixed (Tesla, 2026-11-17): setting one, importing them, or removing an item needs the Prices
password. A USB barcode scanner types the code and Enter: nothing to install.
"""
import csv
import datetime
import json
import os
import re
import uuid

import routing

FILE = "inventory.json"
LOG_FILE = "inventory_log.csv"
LOG_COLUMNS = ["time", "item id", "name", "change", "stock", "reason", "sale"]
UNITS = ["piece", "pack", "ream", "box"]
PLAIN_PAPER = "Smooth white 80 gsm"  # the documents' Normal 80 gsm paper is this row of the price list


def _path(name):
    return routing.app_dir() / name


def now():
    return datetime.datetime.now().replace(microsecond=0)


def _write_safely(path, text):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def number(text, what, whole=True, low=None):
    """A typed number (None when empty), or raises ValueError naming the field."""
    t = str(text if text is not None else "").strip().replace(",", ".")
    if not t:
        return None
    try:
        value = int(t) if whole else round(float(t), 2)
    except ValueError:
        raise ValueError(f"{what}: “{text}” isn't {'a whole number' if whole else 'a number'}.") from None
    if low is not None and value < low:
        raise ValueError(f"{what}: {low} or more.")
    return value


# ------------------------------------------------------------------ links: what ORCA uses up by itself

def link_key(link):
    """A link as a tuple ORCA's uses are matched on: ("paper", name, size), ("label",), ("lamination", size),
    ("spiral",), ("envelope", "DL 110 x 220 mm, White")."""
    if not link:
        return None
    kind = link.get("kind")
    if kind == "paper":
        return ("paper", link.get("name"), link.get("size", "A4"))
    if kind == "lamination":
        return ("lamination", link.get("size", "A4"))
    if kind == "envelope":
        return ("envelope", link.get("name"))
    if kind in ("label", "spiral"):
        return (kind,)
    return None


def link_text(link):
    key = link_key(link)
    if not key:
        return ""
    return {"paper": lambda: f"{key[1]}, {key[2]} sheets", "label": lambda: "Label sheets",
            "lamination": lambda: f"Lamination {key[1]}", "spiral": lambda: "Spiral binding",
            "envelope": lambda: f"{key[1]} envelopes"}[key[0]]()


def link_choices(pl):
    """[(text, link)] staff can pick from: each paper of the price list in A4 and A3, label sheets, lamination A4 /
    A3, spiral binding, each envelope."""
    out = []
    for paper in pl.papers:
        if paper == "Label sheet":
            continue
        for size in ("A4", "A3"):
            out.append({"kind": "paper", "name": paper, "size": size})
    out += [{"kind": "label"}, {"kind": "lamination", "size": "A4"}, {"kind": "lamination", "size": "A3"},
            {"kind": "spiral"}]
    out += [{"kind": "envelope", "name": f"{size}, {kind}"} for size, kind in pl.envelopes]
    return [(link_text(link), link) for link in out]


def uses_of_need(need, item=None, kinds=None):
    """[(link key, pieces)] from a walkin_pricing.Needs (2026-11-19_01 uses). kinds: "paper" (the paper sheets, label
    sheets excluded), "finish" (label sheets, lamination, spiral, envelopes). A product laid out by hand counts the
    sheets given at Layout done."""
    out = []
    laid = (item or {}).get("sheets") if (item or {}).get("kind") == "product" else None
    for u in need.uses:
        n = u.get("count") or 0
        if u["kind"] == "paper":
            if u["name"] == "Label sheet":
                key, group = ("label",), "finish"
            else:
                name = PLAIN_PAPER if u["name"] == "Normal 80 gsm" else u["name"]
                key, group = ("paper", name, u["size"]), "paper"
                if laid:
                    n = int(laid)
        elif u["kind"] == "lamination":
            key, group = ("lamination", u["name"].split()[-1]), "finish"
        elif u["kind"] == "spiral":
            key, group = ("spiral",), "finish"
        elif u["kind"] == "envelope":
            key, group = ("envelope", u["name"]), "finish"
        else:
            continue
        if (kinds is None or group in kinds) and n:
            out.append((key, n))
    return out


# ------------------------------------------------------------------ the items

class Inventory:
    """The items, read from inventory.json each time (small), changes logged to inventory_log.csv."""

    def __init__(self):
        self.data = self.load()

    @staticmethod
    def load():
        try:
            data = json.loads(_path(FILE).read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                data.setdefault("next_sale", 1)
                return data
        except (OSError, ValueError):
            pass
        return {"items": [], "next_sale": 1}

    def save(self):
        _write_safely(_path(FILE), json.dumps(self.data, indent=1, ensure_ascii=False))

    @property
    def items(self):
        return self.data["items"]

    def get(self, item_id):
        return next((it for it in self.items if it["id"] == item_id), None)

    def by_barcode(self, code):
        code = str(code).strip()
        return next((it for it in self.items if code and code in it.get("barcodes", [])), None)

    def by_name(self, name):
        name = str(name).strip().lower()
        return next((it for it in self.items if it["name"].strip().lower() == name), None)

    def by_link(self, key):
        return next((it for it in self.items if link_key(it.get("link")) == key), None)

    def categories(self):
        return sorted({it.get("category") or "" for it in self.items} - {""}, key=str.lower)

    def low(self):
        """Items under their minimum ("Order more")."""
        return [it for it in self.items if it.get("minimum") is not None and it.get("stock", 0) < it["minimum"]]

    def low_stock(self):
        """Every item to order (2026-11-19_11): under its minimum ("Order more"), or Low: an item On display whose
        storage can't fill the display once more (in storage < on display). Not the ones gone from Shopify."""
        out = []
        for it in self.items:
            if it.get("gone"):
                continue
            under = it.get("minimum") is not None and it.get("stock", 0) < it["minimum"]
            if under or is_low(it):
                out.append(it)
        return out

    def check(self, item, own_id=None):
        """Raises ValueError when the item can't be kept: no name, a name or barcode another item has."""
        name = (item.get("name") or "").strip()
        if not name:
            raise ValueError("Name: required.")
        other = self.by_name(name)
        if other and other["id"] != own_id:
            raise ValueError(f"Name: “{name}” is already an item.")
        seen = set()
        for code in item.get("barcodes", []):
            if code in seen:
                raise ValueError(f"Barcode {code} is given twice.")
            seen.add(code)
            other = self.by_barcode(code)
            if other and other["id"] != own_id:
                raise ValueError(f"Barcode {code} belongs to “{other['name']}”.")

    def add(self, item, reason="added"):
        item = dict(item)
        item.setdefault("barcodes", [])
        item.setdefault("stock", 0)
        item.setdefault("per_unit", 1)
        self.check(item)
        item["id"] = uuid.uuid4().hex[:8]
        self.items.append(item)
        self.save()
        if item.get("stock"):
            log(item, item["stock"], reason)
        return item

    def edit(self, item_id, changes):
        item = self.get(item_id)
        new = dict(item, **changes)
        self.check(new, own_id=item_id)
        stock = item.get("stock", 0)
        item.update(changes)
        self.save()
        if item.get("stock", 0) != stock:
            log(item, item["stock"] - stock, changes.get("_reason", "count"))
        return item

    def remove(self, item_id):
        self.data["items"] = [it for it in self.items if it["id"] != item_id]
        self.save()

    def change(self, item_id, delta, reason, sale=""):
        """Stock + delta (a delivery) or - (used, broken, sold, an order): logged."""
        item = self.get(item_id)
        if item is None or not delta:
            return item
        item["stock"] = item.get("stock", 0) + int(delta)
        self.save()
        log(item, delta, reason, sale)
        return item

    def count(self, item_id, on_shelf):
        """What is on the shelf: the difference is logged (reason count)."""
        item = self.get(item_id)
        return self.change(item_id, int(on_shelf) - item.get("stock", 0), "count")

    def take(self, uses, reason):
        """Linked items go down by what ORCA used: [(link key, pieces)]. Nothing linked: nothing changes."""
        done = []
        for key, n in uses:
            item = self.by_link(key)
            if item is not None and n:
                self.change(item["id"], -int(n), reason)
                done.append((item["name"], n))
        return done

    def next_sale(self):
        n = self.data.get("next_sale", 1)
        self.data["next_sale"] = n + 1
        self.save()
        return f"S{n}"


def log(item, delta, reason, sale=""):
    """One line in inventory_log.csv (never stops anything)."""
    p = _path(LOG_FILE)
    try:
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(LOG_COLUMNS)
            w.writerow([now().isoformat(sep=" "), item["id"], item["name"], f"{int(delta):+d}", item.get("stock", 0),
                        reason, sale])
    except OSError:
        pass


def read_log(item_id=None):
    try:
        with open(_path(LOG_FILE), newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    return [r for r in rows if item_id is None or r["item id"] == item_id]


def qty_text(item, n=None):
    """'3 reams + 120 sheets' (pieces in units when one unit holds several), '12 pieces', '-4 pieces'."""
    n = item.get("stock", 0) if n is None else n
    per = max(1, int(item.get("per_unit") or 1))
    unit = item.get("unit") or "piece"
    piece = "sheet" if (item.get("link") or {}).get("kind") in ("paper", "label") else "piece"

    def plural(k, word):
        return f"{k} {word}" + ("" if abs(k) == 1 or word.endswith("s") else "s")

    if per == 1:
        return plural(n, unit)
    if n < 0:
        return plural(n, piece)
    units, rest = divmod(n, per)
    parts = ([plural(units, unit)] if units else []) + ([plural(rest, piece)] if rest else [])
    return " + ".join(parts) or plural(0, unit)


def is_low(item):
    """Low (2026-11-19_11): On display set and in storage under it (storage can't fill the display once more)."""
    if item.get("display") is None or item.get("gone"):
        return False
    return max(0, item.get("stock", 0) - (item.get("shelf") or 0)) < item["display"]


def low_any():
    """For the menu's red dot: under a minimum, or Low."""
    try:
        return bool(Inventory().low_stock())
    except Exception:
        return False


# ------------------------------------------------------------------ deductions from orders, once per part

def _taken(order):
    return order.setdefault("stock_taken", [])


def take_for_part(order, pid, part, pl=None, rules=None):
    """Walk-in: a part's paper sheets at Pages collected, once per send of that part (the order's own state; a Retry
    that printed again takes again). Returns what was taken."""
    import walkin_orders as wo
    import walkin_prices
    import walkin_pricing
    key = f"paper:{pid}:{part.get('collected_times', 1)}"  # each time this part was printed and collected
    if order.get("round"):  # a later round's parts (items added, 2026-11-24_02): their own key
        key = f"paper:r{order['round']}:{pid}:{part.get('collected_times', 1)}"
    if key in _taken(order):
        return []
    pl = pl or walkin_prices.current()
    uses = []
    for index in part.get("items", []):
        item = order["items"][int(index)]
        try:
            uses += uses_of_need(walkin_pricing.needs(pl, item, rules), item, kinds=("paper",))
        except Exception:
            continue
    done = Inventory().take(uses, f"order #{order['number']}")
    _taken(order).append(key)
    wo.save_order(order)
    return done


def take_collected(order, pl=None, rules=None):
    """Walk-in: lamination, spiral, envelopes and label sheets when the order is Collected (once)."""
    import walkin_orders as wo
    import walkin_prices
    import walkin_pricing
    if "collected" in _taken(order):
        return []
    pl = pl or walkin_prices.current()
    uses = []
    for item in order["items"]:
        try:
            uses += uses_of_need(walkin_pricing.needs(pl, item, rules), item, kinds=("finish",))
        except Exception:
            continue
    done = Inventory().take(uses, f"order #{order['number']}")
    _taken(order).append("collected")
    try:
        wo.save_order(order)
    except OSError:
        pass
    return done


def take_copy_counter(counter):
    """The copy counter's Done: the sheets per paper given at Finish (2026-11-19_02) and the extras."""
    uses = []
    for size, rows in counter.papers_now().items():
        for paper, n in rows:
            uses.append((("paper", PLAIN_PAPER if paper == "Normal 80 gsm" else paper, size), n))
    import copy_counter
    for seg in counter.data["segments"]:  # old saved counts that named their paper
        if seg.get("paper"):
            uses.append((("paper", seg["paper"], copy_counter.TYPES[seg["type"]][0]), copy_counter.sheets_of(seg)))
    for e in counter.data["extras"]:
        if e["name"].startswith("Lamination"):
            uses.append((("lamination", e["name"].split()[-1]), e["count"]))
        elif e["name"] == "Spiral binding":
            uses.append((("spiral",), e["count"]))
    return Inventory().take(uses, "copy counter")


def take_printhub(order_number, paper, size, sheets, part_key, state):
    """PrintHub: a product's paper (the website paper name) at Pages collected, once per part (state: a list kept
    with the order's status)."""
    if part_key in state or not paper or not sheets:
        return []
    state.append(part_key)
    return Inventory().take([(("paper", PLAIN_PAPER if paper == "Normal 80 gsm" else paper, size), sheets)],
                            f"PrintHub {order_number}")


# ------------------------------------------------------------------ import

HEADINGS = {
    "name": ("name", "item", "product", "description", "όνομα", "ονομα", "περιγραφή", "περιγραφη", "είδος", "ειδος",
             "προϊόν", "προιον"),
    "barcode": ("barcode", "bar code", "ean", "code", "sku", "κωδικός", "κωδικος", "barcode / ean"),
    "category": ("category", "group", "type", "κατηγορία", "κατηγορια"),
    "unit": ("unit", "μονάδα", "μοναδα"),
    "stock": ("stock", "in stock", "qty", "quantity", "on hand", "απόθεμα", "αποθεμα", "ποσότητα", "ποσοτητα"),
    "minimum": ("minimum", "min", "reorder", "ελάχιστο", "ελαχιστο"),
    "price": ("price", "sale price", "retail", "τιμή", "τιμη", "τιμή πώλησης", "τιμη πωλησης"),
    "display": ("on display", "display", "shelf", "βιτρίνα", "βιτρινα", "ράφι", "ραφι"),
}
FIELDS = ("name", "barcode", "category", "unit", "stock", "minimum", "price", "display")


def read_table(path):
    """{sheet name: [[cell texts]]} from an .xlsx (walkin_prices.read_xlsx, no package) or a .csv ("CSV")."""
    import walkin_prices
    path = str(path)
    if path.lower().endswith(".csv"):
        raw = open(path, "rb").read()
        for enc in ("utf-8-sig", "cp1253", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t") if text.strip() else csv.excel
        return {"CSV": [row for row in csv.reader(text.splitlines(), dialect)]}
    out = {}
    for name, rows in walkin_prices.read_xlsx(path).items():
        table, width = [], max((len(v) for _, v in rows), default=0)
        last = 0
        for r, values in rows:
            while last + 1 < r and table:  # keep empty rows out, but keep the order
                last += 1
            table.append([(v if v is not None else "") for v in values] + [""] * (width - len(values)))
            last = r
        out[name] = table
    return out


def guess_columns(header):
    """{field: column index or None} from the heading row (EN and Greek words)."""
    low = [str(h or "").strip().lower() for h in header]
    out = {}
    for field in FIELDS:
        words = HEADINGS[field]
        out[field] = next((i for i, h in enumerate(low) if h in words), None)
        if out[field] is None:
            out[field] = next((i for i, h in enumerate(low) if h and any(h.startswith(w) for w in words)
                               and i not in out.values()), None)
    return out


def plan_import(rows, columns, inventory):
    """Read the rows under the heading: ([new items], [(existing id, changes)], [bad rows text])."""
    new, update, bad = [], [], []
    seen_codes = {}
    for k, row in enumerate(rows, start=2):
        def cell(field):
            i = columns.get(field)
            return str(row[i]).strip() if i is not None and i < len(row) and row[i] is not None else ""
        name = cell("name")
        if not name and not any(str(c).strip() for c in row):
            continue
        try:
            if not name:
                raise ValueError("no name")
            code = re.sub(r"\.0$", "", cell("barcode"))
            stock = number(cell("stock"), "In stock")
            minimum = number(cell("minimum"), "Minimum", low=0)
            price = number(cell("price"), "Sale price", whole=False, low=0)
            display = number(cell("display"), "On display", low=0)
            if code:
                if code in seen_codes:
                    raise ValueError(f"barcode {code} is used twice (row {seen_codes[code]})")
                seen_codes[code] = k
        except ValueError as e:
            bad.append(f"Row {k}: {e}")
            continue
        found = (inventory.by_barcode(code) if code else None) or inventory.by_name(name)
        fields = {"name": name}
        if code:
            fields["barcodes"] = [code]
        for key, value in (("category", cell("category")), ("unit", cell("unit"))):
            if value:
                fields[key] = value
        if fields.get("category"):
            fields["category_hand"] = True  # a category from a list counts as set by hand (2026-11-19_11)
        if stock is not None:
            fields["stock"] = stock
        if minimum is not None:
            fields["minimum"] = minimum
        if price is not None:
            fields["price"] = price
        if display is not None:
            fields["display"] = display  # 2026-11-19_09: set through shopify_stock.set_display (logged)
        if found:
            if code and code not in found.get("barcodes", []):
                fields["barcodes"] = found.get("barcodes", []) + [code]
            elif "barcodes" in fields:
                fields.pop("barcodes")
            update.append((found["id"], fields))
        else:
            other = inventory.by_barcode(code) if code else None
            if other:
                bad.append(f"Row {k}: barcode {code} belongs to “{other['name']}”")
                continue
            new.append(fields)
    return new, update, bad


def do_import(inventory, new, update, with_prices=True, with_updates=True):
    """Apply a planned import; every change logged with the reason import. Prices only with the password."""
    import shopify_stock
    added = changed = 0
    for fields in new:
        fields = dict(fields)
        if not with_prices:
            fields.pop("price", None)
        display = fields.pop("display", None)
        try:
            item = inventory.add(dict(fields, unit=fields.get("unit") or "piece"), reason="import")
            added += 1
        except ValueError:
            continue
        if display is not None:
            shopify_stock.set_display(inventory, item["id"], display)
    if with_updates:
        for item_id, fields in update:
            fields = dict(fields, _reason="import")
            if not with_prices:
                fields.pop("price", None)
            item = inventory.get(item_id)
            if item is None:
                continue
            stock = fields.pop("stock", None)
            display = fields.pop("display", None)
            if display is not None:
                shopify_stock.set_display(inventory, item_id, display)
            try:
                inventory.edit(item_id, {k: v for k, v in fields.items() if k != "_reason"})
            except ValueError:
                continue
            if stock is not None and stock != item.get("stock", 0):
                inventory.change(item_id, stock - item.get("stock", 0), "import")
            changed += 1
    return added, changed
