"""Walk-in prices from ORCA_Walk-in_Prices.xlsx (Tesla fills in the yellow cells; 2026-11-17).

Read with Python's own zipfile and xml (no extra package), by headings and labels, never by fixed row numbers,
so rows Tesla adds (quantities, sizes, papers) are read too. A filled walk-in (yellow) cell is used; an empty one
means the website price (the grey column, or walkin_catalogue when the grey cell is empty too). A cell with text
where a number should be falls back to the website price and gives a warning naming the sheet and row. A missing
or unreadable file means website prices for everything, with a warning. Read at start and again whenever the
file changes. ORCA never writes to it; prices are changed only in the spreadsheet.
"""
import os
import re
import threading
import xml.etree.ElementTree as ET
import zipfile

import routing
import walkin_catalogue as cat

FILE = "ORCA_Walk-in_Prices.xlsx"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


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
    return values[i] if i < len(values) else None


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
    """Every walk-in price, already resolved: walk-in where filled, else website. warnings: lines for the screen."""

    def __init__(self):
        self.warnings = []
        self.products = {size: dict(row) for size, row in cat.PRICE_TABLE.items()}  # size -> {qty: price}
        self.examples = {}  # (product id, size, pages text or None, qty) -> walk-in price
        self.extras = {}  # extra choice text -> (price, "piece" / "line")
        self.doc_rates = {s: {m: list(r) for m, r in modes.items()} for s, modes in cat.DOC_RATES.items()}
        self.glossy = (cat.GLOSSY_UNDER_100, cat.GLOSSY_FROM_100)
        self.lamination = dict(cat.LAMINATION_PER_SHEET)
        self.spiral = list(cat.SPIRAL_BANDS)
        self.staple = cat.STAPLE_PER_COPY
        self.doc_papers = {"Normal 80 gsm": None, "Glossy 100 gsm": "glossy"}  # name -> None / "glossy" / EUR per sheet
        self.both_sides = cat.BOTH_SIDES
        self.group = cat.GROUP_TOGETHER
        self.design_fee = cat.DESIGN_FEE
        self.loyalty = {1: None, 2: None, 3: None}  # level -> % or None (not set yet)

    def warn(self, sheet, row, text):
        self.warnings.append(f"{sheet} row {row}: {text}")

    def pick(self, sheet, row, walkin, website, what):
        """The walk-in value when it is a number; else the website one (with a warning for text)."""
        w = _number(walkin)
        if walkin is not None and w is None:
            self.warn(sheet, row, f"“{walkin}” in the walk-in column isn't a number: the website price is used for {what}.")
        if w is not None:
            return w
        return _number(website)


def _find_header(rows, first, second=None):
    for i, (_, values) in enumerate(rows):
        if (_cell(values, 0) or "").strip().lower() == first.lower() and (
                second is None or (_cell(values, 1) or "").strip().lower() == second.lower()):
            return i
    return None


def _block(rows, start):
    """Rows after a header row until the first row with nothing in it."""
    out = []
    for r, values in rows[start + 1:]:
        if not any(v is not None for v in values):
            break
        out.append((r, values))
    return out


def _read_documents(pl, rows):
    sheet = "Documents"
    h = _find_header(rows, "Print")
    if h is None:
        pl.warn(sheet, "-", "the “Print” heading row wasn't found: website prices are used for documents.")
    else:
        head = [(v or "").strip().lower() for v in rows[h][1]]
        web = [i for i, v in enumerate(head) if v.startswith("website")]
        walk = [i for i, v in enumerate(head) if v.startswith("walk-in")]
        labels = {"a4 black and white": ("A4", "bw"), "a4 colour": ("A4", "color"), "a4 color": ("A4", "color"),
                  "a3 black and white": ("A3", "bw"), "a3 colour": ("A3", "color"), "a3 color": ("A3", "color")}
        for r, values in _block(rows, h):
            key = labels.get((_cell(values, 0) or "").strip().lower())
            if key is None:
                pl.warn(sheet, r, f"“{_cell(values, 0)}” isn't a print line ORCA knows: skipped.")
                continue
            for tier in range(4):
                website = _cell(values, web[tier]) if tier < len(web) else None
                walkin = _cell(values, walk[tier]) if tier < len(walk) else None
                value = pl.pick(sheet, r, walkin, website, f"{key[0]} {key[1]} tier {tier + 1}")
                if value is not None:
                    pl.doc_rates[key[0]][key[1]][tier] = value
    h = _find_header(rows, "Extra", "Unit")
    if h is None:
        pl.warn(sheet, "-", "the “Extra / Unit” heading row wasn't found: website prices for paper, lamination and binding.")
        return
    head = [(v or "").strip().lower() for v in rows[h][1]]
    web = next((i for i, v in enumerate(head) if v.startswith("website")), 2)
    walk = next((i for i, v in enumerate(head) if v.startswith("walk-in")), 3)
    under, over = pl.glossy
    spiral = dict((band, price) for band, price in pl.spiral)
    for r, values in _block(rows, h):
        name, unit = (_cell(values, 0) or "").strip(), (_cell(values, 1) or "").strip().lower()
        value = pl.pick(sheet, r, _cell(values, walk), _cell(values, web), name)
        low = name.lower()
        if value is None:
            if low:
                pl.warn(sheet, r, f"“{name}” has no price: skipped.")
            continue
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
        elif "sheet" in unit and name:
            pl.doc_papers[name] = value  # an extra paper Tesla added: EUR per sheet
        else:
            pl.warn(sheet, r, f"“{name}” isn't an extra ORCA knows: skipped.")
    pl.glossy = (under, over)
    pl.spiral = sorted(spiral.items())


def _read_products(pl, rows):
    sheet = "Products"
    h = _find_header(rows, "Size")
    if h is None:
        pl.warn(sheet, "-", "the “Size” heading row wasn't found: website prices are used for products.")
        return
    head = [(v or "").strip().lower() for v in rows[h][1]]
    qcol = next((i for i, v in enumerate(head) if v.startswith("quantity")), 2)
    web = next((i for i, v in enumerate(head) if v.startswith("website")), 3)
    walk = next((i for i, v in enumerate(head) if v.startswith("walk-in")), 4)
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
        value = pl.pick(sheet, r, _cell(values, walk), _cell(values, web), f"{size} x {int(qty)}")
        if value is None:
            pl.warn(sheet, r, f"{size} x {int(qty)} has no price: skipped.")
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
            head = [(v or "").strip().lower() for v in values]
            pcol = next((k for k, v in enumerate(head) if v.startswith("pages")), 1)
            qcol = next((k for k, v in enumerate(head) if v.startswith("quantity")), 2)
            walk = next((k for k, v in enumerate(head) if v.startswith("walk-in")), 4)
            size = pages = None
            for r2, v2 in _block(rows, i):
                if _cell(v2, 0):
                    size = _cell(v2, 0).strip()
                if _cell(v2, pcol):
                    pages = _cell(v2, pcol).strip()
                qty = _number(_cell(v2, qcol))
                walkin = _cell(v2, walk)
                if walkin is None:
                    continue
                w = _number(walkin)
                if w is None:
                    pl.warn(sheet, r2, f"“{walkin}” in the walk-in column isn't a number: the website price is used.")
                    continue
                if size is None or qty is None:
                    pl.warn(sheet, r2, "no size or quantity ORCA can read: skipped.")
                    continue
                pl.examples[(product, size, None if pages in (None, "-") else pages, int(qty))] = w
            i += len(_block(rows, i))
        i += 1


def _read_extras(pl, rows):
    sheet = "Extras"
    h = _find_header(rows, "Extra")
    if h is None:
        pl.warn(sheet, "-", "the “Extra” heading row wasn't found: website surcharges are used for extras.")
        return
    head = [(v or "").strip().lower() for v in rows[h][1]]
    walk = next((i for i, v in enumerate(head) if v.startswith("walk-in")), 3)
    mode = next((i for i, v in enumerate(head) if v.startswith("per piece")), 4)
    for r, values in _block(rows, h):
        name, walkin = (_cell(values, 0) or "").strip(), _cell(values, walk)
        if walkin is None or not name:
            continue
        value = _number(walkin)
        if value is None:
            pl.warn(sheet, r, f"“{walkin}” in the walk-in column isn't a number: the website surcharge is used for {name}.")
            continue
        how = (_cell(values, mode) or "").strip().lower()
        if "piece" in how:
            pl.extras[name] = (value, "piece")
        elif "line" in how or "order" in how:
            pl.extras[name] = (value, "line")
        else:
            pl.warn(sheet, r, f"{name}: write “per piece” or “per line”: the website surcharge is used.")


def _read_settings(pl, rows):
    sheet = "Settings"
    for r, values in rows:
        label = (_cell(values, 0) or "").strip().lower()
        web, walk = _cell(values, 2), _cell(values, 3)
        if label == "both sides":
            v = pl.pick(sheet, r, walk, web, "Both sides")
            if v is not None:
                pl.both_sides = v
        elif label.startswith("same-size"):
            text = (walk or web or "").strip().lower()
            if text in ("yes", "no"):
                pl.group = text == "yes"
            elif text:
                pl.warn(sheet, r, f"write Yes or No (“{walk or web}”): the website setting is used.")
        elif label.startswith("extra design fee"):
            v = pl.pick(sheet, r, walk, web, "the extra design fee")
            if v is not None:
                pl.design_fee = v
        else:
            m = re.fullmatch(r"loyalty\s*([123])", label)
            if m:
                if walk is None:
                    continue
                v = _number(str(walk).replace("%", ""))
                if v is None:
                    pl.warn(sheet, r, f"“{walk}” isn't a % number: Loyalty {m.group(1)} gives no discount.")
                elif 0 < v < 1 and "%" not in str(walk):
                    pl.loyalty[int(m.group(1))] = v * 100  # Excel stores 10% as 0.1
                else:
                    pl.loyalty[int(m.group(1))] = v


def load(path=None):
    """A PriceList from the spreadsheet; website prices with a warning when it can't be read."""
    path = path or routing.app_dir() / FILE
    pl = PriceList()
    try:
        sheets = read_xlsx(path)
    except FileNotFoundError:
        pl.warnings.append(f"{FILE} is missing: website prices are used for everything.")
        return pl
    except Exception as e:  # not a valid .xlsx, half-saved, locked
        pl.warnings.append(f"{FILE} can't be read ({type(e).__name__}): website prices are used for everything.")
        return pl
    for name, reader in (("Documents", _read_documents), ("Products", _read_products),
                         ("Envelopes & booklets", _read_examples), ("Extras", _read_extras),
                         ("Settings", _read_settings)):
        if name not in sheets:
            pl.warn(name, "-", "this sheet is missing: website prices are used for it.")
            continue
        try:
            reader(pl, sheets[name])
        except Exception as e:
            pl.warn(name, "-", f"couldn't be read ({type(e).__name__}): website prices are used for it.")
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
