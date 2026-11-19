"""Walk-in prices from Walk-in_Prices.xlsx (Tesla fills in the yellow cells; 2026-11-17_08: copies, paper, cuts).

An item costs copies x price per copy + sheets x paper price + cuts x price per cut + extras (walkin_pricing.py).
The sheet holds only those unit prices: copies (per printed side, A4/A3, B&W/colour, three tiers), paper (per sheet
used, A4/A3, label sheets, envelopes), cutting (price per cut, sheets per stack by paper weight), extras (finishing,
product extras, services) and settings (where tiers 2 and 3 start, loyalty %, spending per level).
Since 2026-11-18_04 the file has two sheets: "Prices" (every table, top to bottom, its title in A1) and "Settings".
The older six sheets (Read me, Copies, Paper, Cutting, Extras, Settings) are still read. Warnings name the real sheet.

An empty yellow cell means "not sold": an item that needs it can't be added. Nothing is ever guessed and there is no
website fallback. A missing or unreadable file means no prices at all, with a yellow line.

Read with Python's own zipfile and xml (no extra package), by headings and labels, never by fixed row numbers,
so rows Tesla adds (papers) are read too. Text where a number should be gives a warning naming the sheet and row
and counts as empty. Read at start and again whenever the file changes. ORCA never writes to it.
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
TRIAL = "Trial price list: every price is 0"  # the title (A1 of Read me, or of Prices) says TEST (2026-11-17_09)
NO_PRICES = f"The price list has no prices yet: fill in the yellow cells in {FILE}. Until then no item can be added."
LABEL_SHEET = "Label sheet"
NORMAL_PAPER = "Normal 80 gsm"  # the documents' plain paper: priced from the "Smooth white 80 gsm" row
NORMAL_ROW = "Smooth white 80 gsm"
GLOSSY = "Glossy 100 gsm"


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


def _how(text):
    """The Charged column: "piece" / "sheet" / "item" (per line counts as once per item), or None."""
    t = (text or "").strip().lower()
    if "piece" in t:
        return "piece"
    if "sheet" in t:
        return "sheet"
    if "item" in t or "line" in t or "once" in t:
        return "item"
    return None


# ------------------------------------------------------------------ the price list

class PriceList:
    """The unit prices from the sheet; None (or absent) = empty cell. warnings: lines for the screen.
    missing: why there are no prices at all (file missing or unreadable), else None."""

    def __init__(self):
        self.warnings = []
        self.missing = None
        self.trial = False  # the title (A1 of Read me, or of the first sheet) contains "TEST": a trial price list
        self.filled = 0  # cells with a number in them
        self.copies = {(s, m): [None, None, None] for s in ("A4", "A3") for m in ("bw", "color")}  # per copy, tiers
        self.papers = {}  # paper name -> {"A4": EUR per sheet or None, "A3": ...}, in sheet order
        self.envelopes = {}  # (size, type) -> EUR per envelope or None
        self.cut_price = None
        self.stacks = []  # [(lowest gsm, highest gsm, label, sheets per stack or None)]
        self.lamination = {"A4": None, "A3": None}
        self.spiral = [(50, None), (100, None), (300, None)]  # per copy, by sheets per copy
        self.staple = None
        self.extras = {}  # product extra -> (price or None, "piece" / "sheet" / "item" or None)
        self.services = {}  # service -> (price or None, how or None, what it means)
        self.tier2 = self.tier3 = None  # copies where tiers 2 and 3 start
        self.loyalty = {1: None, 2: None, 3: None}  # level -> % or None (not set yet)
        self.spend = {1: None, 2: None, 3: None}  # level -> EUR in the last 12 months, or None

    def warn(self, sheet, row, text):
        self.warnings.append(f"{sheet} row {row}: {text}")

    def value(self, sheet, row, text, what):
        """A yellow cell: its number, None when empty ("-" too); text that isn't a number warns, counts as empty."""
        if text is None or str(text).strip() == "-":
            return None
        value = _number(text)
        if value is None:
            self.warn(sheet, row, f"“{text}” isn't a number: {what} counts as empty.")
            return None
        self.filled += 1
        return value

    def level_for(self, spent):
        """The automatic loyalty level for what a customer spent in 12 months: the highest level whose "from"
        amount is filled in and reached, else 0 (None)."""
        reached = [lvl for lvl, amount in self.spend.items() if amount is not None and spent + 1e-9 >= amount]
        return max(reached) if reached else 0

    def tier_of(self, count):
        """1, 2 or 3 for a number of copies of one size and colour in the order (Tier 2 from empty: all tier 1)."""
        if self.tier2 is None:
            return 1
        if self.tier3 is not None and count >= self.tier3:
            return 3
        return 2 if count >= self.tier2 else 1

    def tier_start(self, tier):
        return {2: self.tier2, 3: self.tier3}.get(tier) if self.tier2 is not None else None

    def doc_papers(self):
        """The papers a document can be printed on: Normal 80 gsm, Glossy 100 gsm, then the sheet's other papers."""
        out = [NORMAL_PAPER, GLOSSY]
        out += [p for p in self.papers if p not in (NORMAL_ROW, GLOSSY, LABEL_SHEET)]
        return out

    def paper_row(self, name):
        return NORMAL_ROW if name == NORMAL_PAPER else name

    def stack_for(self, gsm):
        """(label, sheets per stack or None) for a paper weight, or None when no row covers it."""
        for lo, hi, label, n in self.stacks:
            if lo <= gsm <= hi:
                return label, n
        return None


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


COPY_LINES = {"a4 black and white": ("A4", "bw"), "a4 colour": ("A4", "color"), "a4 color": ("A4", "color"),
              "a3 black and white": ("A3", "bw"), "a3 colour": ("A3", "color"), "a3 color": ("A3", "color")}


def _read_copies(pl, rows, sheet="Copies"):
    h = _find_header(rows, "Copy", "Tier")
    if h is None:
        pl.warn(sheet, "-", "the “Copy / Tier 1” heading row wasn't found: copies have no prices.")
        return
    cols = [_heading(rows, h, f"tier {k}") for k in (1, 2, 3)]
    for r, values in _block(rows, h):
        key = COPY_LINES.get((_cell(values, 0) or "").strip().lower())
        if key is None:
            pl.warn(sheet, r, f"“{_cell(values, 0)}” isn't a copy line ORCA knows: skipped.")
            continue
        for k, col in enumerate(cols):
            pl.copies[key][k] = pl.value(sheet, r, _cell(values, col), f"{_cell(values, 0)}, Tier {k + 1}")


def _read_paper(pl, rows, sheet="Paper"):
    h = _find_header(rows, "Paper", "A4")
    if h is None:
        pl.warn(sheet, "-", "the “Paper / A4 sheet” heading row wasn't found: papers have no prices.")
    else:
        a4, a3 = _heading(rows, h, "a4", 1), _heading(rows, h, "a3", 2)
        for r, values in _block(rows, h):
            name = (_cell(values, 0) or "").strip()
            if name:
                pl.papers[name] = {"A4": pl.value(sheet, r, _cell(values, a4), f"{name}, A4 sheet"),
                                   "A3": pl.value(sheet, r, _cell(values, a3), f"{name}, A3 sheet")}
    h = _find_header(rows, "Envelope", "Per")
    if h is None:
        pl.warn(sheet, "-", "the “Envelope / Per envelope” heading row wasn't found: envelopes have no prices.")
        return
    col = _heading(rows, h, "per", 1)
    for r, values in _block(rows, h):
        name = (_cell(values, 0) or "").strip()
        if not name:
            continue
        size, _, kind = name.rpartition(",")
        if not size:
            pl.warn(sheet, r, f"“{name}”: write the envelope as “<size>, <type>”: skipped.")
            continue
        pl.envelopes[(size.strip(), kind.strip())] = pl.value(sheet, r, _cell(values, col), f"{name} envelope")


def _read_cutting(pl, rows, sheet="Cutting"):
    for r, values in rows:
        if (_cell(values, 0) or "").strip().lower() == "price per cut":
            pl.cut_price = pl.value(sheet, r, _cell(values, 1), "the price per cut")
    h = _find_header(rows, "Paper weight", "Sheets")
    if h is None:
        pl.warn(sheet, "-", "the “Paper weight / Sheets per stack” heading row wasn't found: nothing can be cut.")
        return
    for r, values in _block(rows, h):
        label = (_cell(values, 0) or "").strip()
        nums = [int(x) for x in re.findall(r"\d+", label)]
        if label.lower().startswith("up to") and nums:
            lo, hi = 0, nums[0]
        elif len(nums) >= 2:
            lo, hi = nums[0], nums[1]
        else:
            pl.warn(sheet, r, f"“{label}” isn't a paper weight range ORCA can read: skipped.")
            continue
        n = pl.value(sheet, r, _cell(values, 1), f"sheets per stack, {label}")
        if n is not None and (n != int(n) or n <= 0):
            pl.warn(sheet, r, f"sheets per stack, {label}: “{_cell(values, 1)}” isn't a whole number: counts as empty.")
            n = None
        pl.stacks.append((lo, hi, label, int(n) if n else None))


def _read_extras(pl, rows, sheet="Extras"):
    h = _find_header(rows, "Finishing", "Unit")
    if h is None:
        pl.warn(sheet, "-", "the “Finishing / Unit” heading row wasn't found: no lamination, binding or staples.")
    else:
        col = _heading(rows, h, "price", 2)
        spiral = dict(pl.spiral)
        for r, values in _block(rows, h):
            name, unit = (_cell(values, 0) or "").strip(), (_cell(values, 1) or "").strip().lower()
            if not name:
                continue
            value = pl.value(sheet, r, _cell(values, col), f"{name} ({unit})")
            low = name.lower()
            if low == "lamination a4":
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
            else:
                pl.warn(sheet, r, f"“{name}” isn't finishing ORCA knows: skipped.")
        pl.spiral = sorted(spiral.items())
    for title, target in (("Product extra", pl.extras), ("Service", pl.services)):
        h = _find_header(rows, title)
        if h is None:
            pl.warn(sheet, "-", f"the “{title}” heading row wasn't found.")
            continue
        pcol, ccol = _heading(rows, h, "price", 2), _heading(rows, h, "charged", 3)
        mcol = _heading(rows, h, "what", None)
        for r, values in _block(rows, h):
            name = (_cell(values, 0) or "").strip()
            if not name:
                continue
            value = pl.value(sheet, r, _cell(values, pcol), name)
            how = _how(_cell(values, ccol))
            if value is not None and how is None:
                pl.warn(sheet, r, f"{name}: write “per piece”, “per sheet” or “once per item” under Charged: "
                                  f"it counts as empty.")
                value = None
            if title == "Service":
                target[name] = (value, how, (_cell(values, mcol) or "").strip())
            else:
                target[name] = (value, how)


def _read_settings(pl, rows, sheet="Settings"):
    for r, values in rows:
        label = (_cell(values, 0) or "").strip().lower()
        value = _cell(values, 2)
        m = re.fullmatch(r"tier\s*([23])\s*from", label)
        if m:
            v = pl.value(sheet, r, value, f"Tier {m.group(1)} from")
            setattr(pl, f"tier{m.group(1)}", v)
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
    if pl.tier2 is not None and pl.tier3 is not None and pl.tier3 <= pl.tier2:
        pl.warn(sheet, "-", "Tier 3 from should be more than Tier 2 from.")
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
    if "Prices" in sheets:  # 2026-11-18_04: two sheets, "Prices" (every table, top to bottom) and "Settings"
        plan = [("Prices", _read_copies), ("Prices", _read_paper), ("Prices", _read_cutting),
                ("Prices", _read_extras), ("Settings", _read_settings)]
    else:  # the older six-sheet file: still read
        plan = [("Copies", _read_copies), ("Paper", _read_paper), ("Cutting", _read_cutting),
                ("Extras", _read_extras), ("Settings", _read_settings)]
    for name, reader in plan:
        if name not in sheets:
            pl.warn(name, "-", "this sheet is missing: it gives no prices.")
            continue
        try:
            reader(pl, sheets[name], name)
        except Exception as e:
            pl.warn(name, "-", f"couldn't be read ({type(e).__name__}): it gives no prices.")
    if pl.filled == 0:
        pl.warnings.insert(0, NO_PRICES)
    # the title: A1 of "Read me" (older files), else A1 of the first sheet ("Prices")
    title_rows = sheets["Read me"] if "Read me" in sheets else next(iter(sheets.values()), [])
    title = next((v[0] for r, v in title_rows if r == 1 and v and v[0]), "") or ""
    if "TEST" in str(title):
        pl.trial = True
        pl.warnings.insert(0, TRIAL)  # so nobody mistakes it for real prices
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
