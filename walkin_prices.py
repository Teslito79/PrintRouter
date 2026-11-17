"""Walk-in prices from Walk-in_Prices.xlsx (Tesla fills in the yellow cells; 2026-11-17_07).

The sheet is walk-in only: every yellow cell is the walk-in price itself, there is no website column and no
website fallback. An empty price cell (or a size, quantity or paper that isn't in the sheet) means "no price":
that item can't be added or placed. A missing or unreadable file means no prices at all, with a yellow line.

Read with Python's own zipfile and xml (no extra package), by headings and labels, never by fixed row numbers,
so rows Tesla adds (quantities, sizes, papers) are read too. Text where a number should be gives a warning naming
the sheet and row and counts as empty. Read at start and again whenever the file changes. ORCA never writes to it.
"""
import os
import re
import threading
import xml.etree.ElementTree as ET
import zipfile

import routing

FILE = "Walk-in_Prices.xlsx"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
NO_PRICES = f"The price list has no prices yet: fill in the yellow cells in {FILE}. Until then no item can be added."


# ------------------------------------------------------------------ reading the .xlsx

def _col(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(path):
    """{sheet name: [(row number, [cell texts or None, ...]), ...]}. Values as text (numbers as Excel stores them)."""
    out = {}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(NS + "si"):
                shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet"):
            target = rels[sheet.get(REL)].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).iter(NS + "row"):
                cells = {}
                for c in row.iter(NS + "c"):
                    t, v = c.get("t"), c.find(NS + "v")
                    if t == "s" and v is not None:
                        value = shared[int(v.text)]
                    elif t == "inlineStr":
                        value = "".join(x.text or "" for x in c.iter(NS + "t"))
                    elif v is not None:
                        value = v.text
                    else:
                        value = None
                    if value is not None and str(value).strip() == "":
                        value = None
                    cells[_col(c.get("r"))] = value
                width = max(cells) + 1 if cells else 0
                rows.append((int(row.get("r")), [cells.get(i) for i in range(width)]))
            out[sheet.get("name")] = rows
    return out


def _cell(values, i):
    return values[i] if i is not None and i < len(values) else None


def _number(text):
    """A number from a cell (a dot or comma decimal), or None when it isn't one."""
    if text is None:
        return None
    t = str(text).strip().replace("€", "").replace("EUR", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


# ------------------------------------------------------------------ the price list

class PriceList:
    """Every walk-in price from the sheet; None (or absent) = no price yet. warnings: lines for the screen.
    missing: why there are no prices at all (file missing or unreadable), else None."""

    def __init__(self):
        self.warnings = []
        self.missing = None
        self.filled = 0  # price cells with a number in them
        self.products = {}  # size -> {qty: price}
        self.examples = {}  # (product id, size, pages text or None, qty) -> price
        self.extras = {}  # extra choice text -> (price, "pct" / "piece" / "line")
        self.services = {}  # service name -> (price or None, per what text)
        self.doc_rates = {s: {m: [None] * 4 for m in ("bw", "color")} for s in ("A4", "A3")}
        self.glossy = (None, None)  # per sheet: under 100 sheets, 100 sheets or more
        self.lamination = {"A4": None, "A3": None}
        self.spiral = [(50, None), (100, None), (300, None)]  # per copy, by sheets per copy
        self.staple = None
        self.doc_papers = {"Normal 80 gsm": None, "Glossy 100 gsm": "glossy"}  # name -> None / "glossy" / EUR per sheet
        self.both_sides = None  # x the one-side price; empty = x1
        self.group = False
        self.design_fee = 0.0
        self.loyalty = {1: None, 2: None, 3: None}  # level -> % or None (not set yet)
        self.spend = {1: None, 2: None, 3: None}  # level -> EUR in the last 12 months, or None

    def warn(self, sheet, row, text):
        self.warnings.append(f"{sheet} row {row}: {text}")

    def price(self, sheet, row, text, what):
        """A price cell: its number, None when empty; text that isn't a number warns and counts as empty."""
        if text is None:
            return None
        value = _number(text)
        if value is None:
            self.warn(sheet, row, f"“{text}” isn't a number: {what} has no price.")
            return None
        self.filled += 1
        return value

    def sides_factor(self):
        return self.both_sides if self.both_sides is not None else 1.0

    def level_for(self, spent):
        """The automatic loyalty level for what a customer spent in 12 months: the highest level whose "from"
        amount is filled in and reached, else 0 (None)."""
        reached = [lvl for lvl, amount in self.spend.items() if amount is not None and spent + 1e-9 >= amount]
        return max(reached) if reached else 0


def _find_header(rows, first, second=None):
    """The heading row whose first cell is `first` (a cell starting with it when a second heading is given too)."""
    for i, (_, values) in enumerate(rows):
        a, b = (_cell(values, 0) or "").strip().lower(), (_cell(values, 1) or "").strip().lower()
        if second is None and a == first.lower():
            return i
        if second is not None and a.startswith(first.lower()) and b.startswith(second.lower()):
            return i
    return None


def _heading(rows, h, start, default=None):
    head = [(v or "").strip().lower() for v in rows[h][1]]
    return next((i for i, v in enumerate(head) if v.startswith(start)), default)


def _block(rows, start):
    """Rows after a header row until the first row with nothing in it."""
    out = []
    for r, values in rows[start + 1:]:
        if not any(v is not None for v in values):
            break
        out.append((r, values))
    return out


DOC_LINES = {"a4 black and white": ("A4", "bw"), "a4 colour": ("A4", "color"), "a4 color": ("A4", "color"),
             "a3 black and white": ("A3", "bw"), "a3 colour": ("A3", "color"), "a3 color": ("A3", "color")}


def _read_documents(pl, rows):
    sheet = "Documents"
    h = _find_header(rows, "Print")
    if h is None:
        pl.warn(sheet, "-", "the “Print” heading row wasn't found: documents have no prices.")
    else:
        head = [(v or "").strip().lower() for v in rows[h][1]]
        tiers = [i for i, v in enumerate(head) if "sides" in v][:4]
        for r, values in _block(rows, h):
            key = DOC_LINES.get((_cell(values, 0) or "").strip().lower())
            if key is None:
                pl.warn(sheet, r, f"“{_cell(values, 0)}” isn't a print line ORCA knows: skipped.")
                continue
            for tier, col in enumerate(tiers):
                pl.doc_rates[key[0]][key[1]][tier] = pl.price(sheet, r, _cell(values, col),
                                                              f"{key[0]} {key[1]} {head[col]}")
    h = _find_header(rows, "Paper", "Unit")
    if h is None:
        pl.warn(sheet, "-", "the “Paper, lamination, binding / Unit” heading row wasn't found: no prices for them.")
        return
    col = _heading(rows, h, "price", 2)
    under, over = pl.glossy
    spiral = dict(pl.spiral)
    for r, values in _block(rows, h):
        name, unit = (_cell(values, 0) or "").strip(), (_cell(values, 1) or "").strip().lower()
        if not name:
            continue
        value = pl.price(sheet, r, _cell(values, col), name)
        low = name.lower()
        if low.startswith("glossy 100"):
            if "under" in unit:
                under = value
            else:
                over = value
        elif low == "lamination a4":
            pl.lamination["A4"] = value
        elif low == "lamination a3":
            pl.lamination["A3"] = value
        elif low.startswith("spiral"):
            band = 50 if "up to 50" in unit else 100 if "51-100" in unit else 300 if "101-300" in unit else None
            if band is None:
                pl.warn(sheet, r, f"spiral binding “{unit}” isn't a band ORCA knows: skipped.")
            else:
                spiral[band] = value
        elif low.startswith("staple"):
            pl.staple = value
        elif "sheet" in unit:
            if value is not None:
                pl.doc_papers[name] = value  # an extra paper Tesla added: EUR per sheet
        else:
            pl.warn(sheet, r, f"“{name}” isn't an extra ORCA knows: skipped.")
    pl.glossy = (under, over)
    pl.spiral = sorted(spiral.items())


def _read_products(pl, rows):
    sheet = "Products"
    h = _find_header(rows, "Size")
    if h is None:
        pl.warn(sheet, "-", "the “Size” heading row wasn't found: products have no prices.")
        return
    qcol = _heading(rows, h, "quantity", 2)
    pcol = _heading(rows, h, "price", 3)
    size = None
    for r, values in rows[h + 1:]:
        if not any(v is not None for v in values):
            continue
        if _cell(values, 0):
            size = _cell(values, 0).strip()
        qty = _number(_cell(values, qcol))
        if size is None or qty is None or qty != int(qty) or qty <= 0:
            pl.warn(sheet, r, "no size or quantity ORCA can read: skipped.")
            continue
        value = pl.price(sheet, r, _cell(values, pcol), f"{size} x {int(qty)}")
        if value is None:
            continue
        for s in (part.strip() for part in size.split(" / ")):  # "DL 99 x 210 mm / 1/3 A4": one row, two names
            pl.products.setdefault(s, {})[int(qty)] = value


def _read_examples(pl, rows):
    sheet = "Envelopes & booklets"
    titles = {"printed envelopes": "envelope", "stapled booklets": "stapled", "spiral bound booklets": "wire"}
    product = None
    i = 0
    while i < len(rows):
        r, values = rows[i]
        first = (_cell(values, 0) or "").strip()
        if first.lower() in titles:
            product = titles[first.lower()]
        elif first.lower() == "size" and product:
            pcol = _heading(rows, i, "pages", 1)
            qcol = _heading(rows, i, "quantity", 2)
            price = _heading(rows, i, "price", 3)
            size = pages = None
            block = _block(rows, i)
            for r2, v2 in block:
                if _cell(v2, 0):
                    size = _cell(v2, 0).strip()
                if _cell(v2, pcol):
                    pages = _cell(v2, pcol).strip()
                qty = _number(_cell(v2, qcol))
                if size is None or qty is None:
                    pl.warn(sheet, r2, "no size or quantity ORCA can read: skipped.")
                    continue
                value = pl.price(sheet, r2, _cell(v2, price), f"{size} {pages or ''} x {int(qty)}")
                if value is not None:
                    pl.examples[(product, size, None if pages in (None, "-") else pages, int(qty))] = value
            i += len(block)
        i += 1


def _read_extras(pl, rows):
    sheet = "Extras"
    h = _find_header(rows, "Extra")
    if h is None:
        pl.warn(sheet, "-", "the “Extra” heading row wasn't found: extras have no prices.")
    else:
        pcol, hcol = _heading(rows, h, "price", 2), _heading(rows, h, "how", 3)
        for r, values in _block(rows, h):
            name = (_cell(values, 0) or "").strip()
            if not name:
                continue
            value = pl.price(sheet, r, _cell(values, pcol), name)
            if value is None:
                continue
            how = (_cell(values, hcol) or "").strip().lower()
            if "%" in how:
                pl.extras[name] = (value, "pct")
            elif "piece" in how:
                pl.extras[name] = (value, "piece")
            elif "line" in how or "order" in how:
                pl.extras[name] = (value, "line")
            else:
                pl.warn(sheet, r, f"{name}: write “% of item”, “per piece” or “per line” under How: it has no price.")
    h = _find_header(rows, "Service")
    if h is None:
        return
    pcol, wcol = _heading(rows, h, "price", 2), _heading(rows, h, "per", 3)
    for r, values in _block(rows, h):
        name = (_cell(values, 0) or "").strip()
        if name:
            pl.services[name] = (pl.price(sheet, r, _cell(values, pcol), name), (_cell(values, wcol) or "").strip())


def _read_settings(pl, rows):
    sheet = "Settings"
    for r, values in rows:
        label = (_cell(values, 0) or "").strip().lower()
        value = _cell(values, 2)
        if label == "both sides":
            v = _number(value)
            if value is not None and v is None:
                pl.warn(sheet, r, f"Both sides: “{value}” isn't a number: x1 is used.")
            pl.both_sides = v
        elif label.startswith("same-size"):
            text = (value or "").strip().lower()
            if text in ("yes", "no"):
                pl.group = text == "yes"
            elif text:
                pl.warn(sheet, r, f"Same-size items priced together: write Yes or No (“{value}”): No is used.")
        elif label.startswith("extra design fee"):
            v = _number(value)
            if value is not None and v is None:
                pl.warn(sheet, r, f"Extra design fee: “{value}” isn't a number: 0 is used.")
            pl.design_fee = v or 0.0
        elif re.fullmatch(r"loyalty\s*([123])", label):
            level = int(label[-1])
            if value is None:
                continue
            v = _number(str(value).replace("%", ""))
            if v is None:
                pl.warn(sheet, r, f"“{value}” isn't a % number: Loyalty {level} gives no discount.")
            elif 0 < v < 1 and "%" not in str(value):
                pl.loyalty[level] = v * 100  # Excel stores 10% as 0.1
            else:
                pl.loyalty[level] = v
        else:
            m = re.search(r"level\s*([123])\s*from", label)
            if m and value is not None:
                v = _number(value)
                if v is None:
                    pl.warn(sheet, r, f"“{value}” isn't an amount in EUR: Level {m.group(1)} has no spending set.")
                else:
                    pl.spend[int(m.group(1))] = v
    amounts = [pl.spend[k] for k in (1, 2, 3) if pl.spend[k] is not None]
    if any(b <= a for a, b in zip(amounts, amounts[1:])):
        pl.warn(sheet, "-", "Level amounts should rise from 1 to 3 (the highest level reached is used).")


def load(path=None):
    """A PriceList from the spreadsheet; no prices at all, with a yellow line, when it can't be read."""
    path = path or routing.app_dir() / FILE
    pl = PriceList()
    try:
        sheets = read_xlsx(path)
    except FileNotFoundError:
        pl.missing = f"{FILE} is missing from ADMIN: no item can be priced until it is back."
        pl.warnings.append(pl.missing)
        return pl
    except Exception as e:  # not a valid .xlsx, half-saved, locked
        pl.missing = f"{FILE} can't be read ({type(e).__name__}): no item can be priced until it can."
        pl.warnings.append(pl.missing)
        return pl
    for name, reader in (("Documents", _read_documents), ("Products", _read_products),
                         ("Envelopes & booklets", _read_examples), ("Extras", _read_extras),
                         ("Settings", _read_settings)):
        if name not in sheets:
            pl.warn(name, "-", "this sheet is missing: it gives no prices.")
            continue
        try:
            reader(pl, sheets[name])
        except Exception as e:
            pl.warn(name, "-", f"couldn't be read ({type(e).__name__}): it gives no prices.")
    if pl.filled == 0:
        pl.warnings.insert(0, NO_PRICES)
    elif pl.both_sides is None:
        pl.warnings.append("Settings: Both sides is empty: both sides costs the same as one side (x1) until it is "
                           "filled in.")
    return pl


_lock = threading.Lock()
_cache = {"key": None, "list": None}


def current(path=None):
    """The price list, read again whenever the file changed (size or time)."""
    path = path or routing.app_dir() / FILE
    try:
        st = os.stat(path)
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(path), None, None)
    with _lock:
        if _cache["key"] != key:
            _cache["list"], _cache["key"] = load(path), key
        return _cache["list"]
