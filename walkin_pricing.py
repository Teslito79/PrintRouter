"""Prices for a walk-in order (2026-11-17_08): copies, paper and cuts, from Walk-in_Prices.xlsx (walkin_prices.py).

Tesla, 2026-11-17: "they should be priced of how many papers we copy the type of paper and the amount of cutting it
needs". Item = copies x price per copy + sheets x paper price + cuts x price per cut + extras.
- A copy is one printed side (both sides = 2 copies per sheet); its price depends on the sheet size (A4/A3) and colour,
  in tiers counted over all copies of the order of that size and colour (Settings: Tier 2 from, Tier 3 from), and
  never more for fewer: when the next tier's lowest count costs less in total, that is charged (the volume line).
- Each sheet of paper used is charged once at that paper's A4 or A3 price.
- Products: sheets = quantity / pieces per A4 (rules.json pieces_per_sheet); anything more than one per sheet is on A4;
  an A4 piece on A4, an A3 piece on A3, a size that only fits A3 on A3. Cuts per stack = (rows + 1) + (columns + 1),
  with rows x columns worked out from the pieces per sheet (fewest cuts); stacks = sheets / sheets per stack for the
  paper's weight. Labels: A4 label sheets, no cuts. Stapled booklets: pages / 4 sheets per copy of the opened size,
  both sides, staple per copy. Envelopes: the envelope's price plus its copies (C4 counts as A3).
- Documents: copies by pages per side and colour pages, sheets by sides, paper per sheet, a typed number of cuts,
  lamination per sheet, spiral by sheets per copy, staple per copy.
- Product extras and services: per piece, per sheet or once per item.
A needed cell that is empty blocks the item ("No price for …: fill it in in Walk-in_Prices.xlsx"); nothing is guessed.
Order: the items (plus the volume line), minus the loyalty %, then the staff's rounding. No minimum charge.
"""
import math

import routing
import walkin_catalogue as cat
from walkin_catalogue import r2

SHEET = "Walk-in_Prices.xlsx"
SHEET_MM = {"A4": (210, 297), "A3": (297, 420)}
COLOUR_WORD = {"bw": "black and white", "color": "colour"}
ENVELOPE_A3 = ("C4",)  # envelopes that count as A3 copies; the others count as A4


def euro(x):
    return f"EUR {x:,.2f}"


def money(x):
    return f"{x:,.2f}"


def no_price(what):
    return f"No price for {what}: fill it in in {SHEET}"


# ------------------------------------------------------------------ rounding (staff can only round the total)

ROUNDINGS = {"down1": ("Down to 1", -1, 1), "up1": ("Up to 1", 1, 1), "down5": ("Down to 5", -1, 5),
             "up5": ("Up to 5", 1, 5), "down10": ("Down to 10", -1, 10), "up10": ("Up to 10", 1, 10)}


def rounded(total, mode):
    """The total rounded by one of the six buttons (from the calculated total); None / unknown: unchanged.
    Already round: unchanged. Never below 0."""
    if mode not in ROUNDINGS:
        return r2(total)
    _, way, step = ROUNDINGS[mode]
    cents, unit = round(total * 100), step * 100
    value = (math.ceil(cents / unit) if way > 0 else math.floor(cents / unit)) * unit
    return max(0, value) / 100


# ------------------------------------------------------------------ describing items

def product_of(item):
    return cat.BY_ID.get(item.get("product"))


def describe(item):
    """One line for lists, the cover sheet and order.json."""
    if item["kind"] == "document":
        colour = {"bw": "B&W", "color": "colour", "mixed": f"colour pages {item.get('color_pages') or '-'}"}[item["color"]]
        parts = [f"Document {item['size']}", f"{item['pages']} pages x {item['copies']}", colour,
                 "both sides" if item["sides"] == "double" else "one side"]
        if item.get("per_side", 1) > 1:
            parts.append(f"{item['per_side']} per side")
        parts.append(item["paper"])
        if item.get("finish") in ("staple", "spiral"):
            parts.append(item["finish"])
        if item.get("lam"):
            parts.append(f"laminated ({item['lam_sheets']} sheets)" if item.get("lam_sheets") else "laminated")
        if item.get("cuts"):
            parts.append(f"{item['cuts']} cuts")
        text = ", ".join(parts)
    else:
        p = product_of(item)
        picks = [o["choices"][item["picks"].get(o["key"], 0)] for o in p["options"]]
        text = f"{item['qty']} x {p['name']}, " + ", ".join(c for c in picks if c not in ("None",))
    if item.get("services"):
        text += ", " + ", ".join(name if not count or count is True else f"{name} x {count}"
                                 for name, count in item["services"].items())
    return text


def folder_name(index, item):
    """The item's subfolder: '1 Business cards 85 x 55', '2 Flyers A5', '3 Document A4'."""
    if item["kind"] == "document":
        name = f"Document {item['size']}"
    else:
        p = product_of(item)
        size = cat.size_of(p, item["picks"]).replace(" mm", "")
        name = f"{p['name']} {size}"
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, " ")
    return f"{index} {' '.join(name.split())}"


# ------------------------------------------------------------------ layout: sheets and cuts

_RULES = {}


def rules_now():
    key = str(routing.app_dir())
    if key not in _RULES:
        _RULES[key] = routing.load_rules()
    return _RULES[key]


def pieces_entry(rules, w, h, tolerance=2):
    """rules.json pieces_per_sheet for a size in mm, either way round, within a few mm ({"A4": 8, "A3": 18}),
    or None."""
    table = rules.get("pieces_per_sheet") or {}
    for key, entry in table.items():
        if not isinstance(entry, dict) or "x" not in key:
            continue
        try:
            a, b = (float(v) for v in key.split("x"))
        except ValueError:
            continue
        if any(abs(a - x) <= tolerance and abs(b - y) <= tolerance for x, y in ((w, h), (h, w))):
            return entry
    return None


def grid(w, h, per, sheet):
    """(rows, columns) with rows x columns = per that fit on the sheet, the piece either way round, with the fewest
    cuts ((rows + 1) + (columns + 1)); None when none fits."""
    sw, sh = SHEET_MM[sheet]
    best = None
    for rows in range(1, per + 1):
        if per % rows:
            continue
        cols = per // rows
        for pw, ph in ((w, h), (h, w)):
            if cols * pw <= sw + 0.5 and rows * ph <= sh + 0.5:
                cuts = rows + 1 + cols + 1
                if best is None or cuts < best[2]:
                    best = (rows, cols, cuts)
    return best[:2] if best else None


def same_size(w, h, sheet, tolerance=2):
    """True when the piece is the sheet itself (within a few mm: an opened A5 booklet, 2 x 148 mm, is an A4)."""
    sw, sh = SHEET_MM[sheet]
    return any(abs(w - a) <= tolerance and abs(h - b) <= tolerance for a, b in ((sw, sh), (sh, sw)))


def layout(rules, w, h, what):
    """{sheet, per, rows, cols} for pieces of w x h mm, or raises ValueError with the reason (the item can't be
    added). An A4 / A3 piece: its own sheet, no cuts. More than one per A4: on A4. Only fits A3: on A3."""
    for sheet in ("A4", "A3"):
        if same_size(w, h, sheet):
            return {"sheet": sheet, "per": 1, "rows": None, "cols": None}
    entry = pieces_entry(rules, w, h)
    if entry is None:
        raise ValueError(f"{what}: no layout for {round(w)} x {round(h)} mm in rules.json pieces_per_sheet")
    if isinstance(entry.get("A4"), int) and entry["A4"] > 0:
        sheet, per = "A4", entry["A4"]
    elif isinstance(entry.get("A3"), int) and entry["A3"] > 0:
        sheet, per = "A3", entry["A3"]
    else:
        raise ValueError(f"{what}: no pieces per sheet for {round(w)} x {round(h)} mm in rules.json")
    rc = grid(w, h, per, sheet)
    if rc is None:
        sw, sh = SHEET_MM[sheet]
        raise ValueError(f"{what}: {per} pieces of {round(w)} x {round(h)} mm don't fit on {sw} x {sh} mm")
    return {"sheet": sheet, "per": per, "rows": rc[0], "cols": rc[1]}


# ------------------------------------------------------------------ one item's needs

class Needs:
    """What one item uses: copies by (size, colour), fixed costs with their working lines, problems."""

    def __init__(self):
        self.copies = {}  # (size, "bw"/"color") -> count
        self.lines = []  # (text without the amount, amount)
        self.problems = []
        self.sheets = 0

    def copy(self, size, colour, n):
        if n > 0:
            self.copies[(size, colour)] = self.copies.get((size, colour), 0) + n

    def cost(self, text, amount):
        self.lines.append((text, r2(amount)))


def _paper(pl, n, need, paper, sheet):
    row = pl.paper_row(paper)
    price = pl.papers.get(row, {}).get(sheet)
    if price is None:
        need.problems.append(no_price(f"{row}, {sheet} sheet"))
        return
    need.cost(f"{n} {sheet} sheets {paper} x {money(price)}", n * price)


def _cuts(pl, need, lay, sheets, paper):
    """Cuts for a product (or a booklet laid out more than one per sheet)."""
    if lay["rows"] is None:
        return
    gsm = routing.paper_gsm(paper) or 80
    stack = pl.stack_for(gsm)
    if stack is None:
        need.problems.append(f"No Sheets per stack row covers {gsm} gsm (the “Paper weight” table on the Prices sheet of {SHEET})")
        return
    label, per_stack = stack
    if per_stack is None:
        need.problems.append(no_price(f"sheets per stack, {label}").replace("No price for", "No number for"))
        return
    if pl.cut_price is None:
        need.problems.append(no_price("the price per cut"))
        return
    stacks = math.ceil(sheets / per_stack)
    per = (lay["rows"] + 1) + (lay["cols"] + 1)
    n = per * stacks
    grid_text = f"{lay['rows']} x {lay['cols']}" + (f", {stacks} stacks" if stacks > 1 else "")
    need.cost(f"{n} cuts ({grid_text}) x {money(pl.cut_price)}", n * pl.cut_price)


def _extra(pl, need, name, table, what, pieces, sheets):
    price, how = table.get(name, (None, None))[:2]
    if price is None:
        need.problems.append(no_price(f"{name} ({what})"))
        return
    if how == "piece":
        need.cost(f"{name}: {pieces} x {money(price)}", pieces * price)
    elif how == "sheet":
        need.cost(f"{name}: {sheets} sheets x {money(price)}", sheets * price)
    else:
        need.cost(f"{name}: once x {money(price)}", price)


def _services(pl, need, item, pieces, sheets):
    for name, count in (item.get("services") or {}).items():
        _, how = pl.services.get(name, (None, None, ""))[:2]
        if how == "piece" and item["kind"] == "document":
            n = count if isinstance(count, int) and not isinstance(count, bool) else 0
            if n < 1:
                need.problems.append(f"{name}: type how many")
                continue
            _extra(pl, need, name, pl.services, "service", n, sheets)
        else:
            _extra(pl, need, name, pl.services, "service", pieces, sheets)


def page_set(text, pages):
    out = set()
    for part in str(text or "").split(","):
        t = part.strip()
        if "-" in t:
            a, _, b = t.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                lo, hi = sorted((int(a), int(b)))
                out.update(range(max(1, lo), min(pages, hi) + 1))
        elif t.isdigit() and 1 <= int(t) <= pages:
            out.add(int(t))
    return out


def doc_counts(item):
    """Copies (B&W, colour) and sheets for one document item, copies included."""
    pages, copies = max(0, int(item["pages"])), max(1, int(item["copies"]))
    nup = item.get("per_side", 1) if item.get("per_side", 1) in cat.PER_SIDE else 1
    sides_per_copy = math.ceil(pages / nup)
    if item["color"] == "color":
        col = sides_per_copy
    elif item["color"] == "mixed":
        cset = page_set(item.get("color_pages"), pages)
        col = sum(1 for b in range(sides_per_copy)
                  if any(q in cset for q in range(b * nup + 1, min(pages, (b + 1) * nup) + 1)))
    else:
        col = 0
    sheets_per_copy = math.ceil(sides_per_copy / (2 if item["sides"] == "double" else 1))
    return {"bw": (sides_per_copy - col) * copies, "color": col * copies, "sheets_per_copy": sheets_per_copy,
            "sheets": sheets_per_copy * copies, "copies": copies, "pages": pages}


def _document(pl, item):
    need = Needs()
    c = doc_counts(item)
    if c["pages"] == 0:
        need.problems.append("no pages")
        return need
    size = item["size"]
    need.copy(size, "bw", c["bw"])
    need.copy(size, "color", c["color"])
    need.sheets = c["sheets"]
    _paper(pl, c["sheets"], need, item["paper"], size)
    cuts = int(item.get("cuts") or 0)
    if cuts:
        if pl.cut_price is None:
            need.problems.append(no_price("the price per cut"))
        else:
            need.cost(f"{cuts} cuts x {money(pl.cut_price)}", cuts * pl.cut_price)
    if item.get("finish") == "spiral":
        band = next(((limit, price) for limit, price in pl.spiral if c["sheets_per_copy"] <= limit), None)
        if band is None:
            need.problems.append(f"more than {pl.spiral[-1][0]} sheets per copy can't be spiral bound")
        elif band[1] is None:
            need.problems.append(no_price(f"Spiral binding (per copy, {c['sheets_per_copy']} sheets)"))
        else:
            need.cost(f"Spiral binding: {c['copies']} x {money(band[1])}", c["copies"] * band[1])
    elif item.get("finish") == "staple":
        if pl.staple is None:
            need.problems.append(no_price("Staple (per copy)"))
        else:
            need.cost(f"Staple: {c['copies']} x {money(pl.staple)}", c["copies"] * pl.staple)
    if item.get("lam"):
        n = min(int(item.get("lam_sheets") or 0) or c["sheets"], c["sheets"])
        if pl.lamination[size] is None:
            need.problems.append(no_price(f"Lamination {size} (per sheet)"))
        else:
            need.cost(f"Lamination {size}: {n} sheets x {money(pl.lamination[size])}", n * pl.lamination[size])
    _services(pl, need, item, c["copies"], c["sheets"])
    return need


def _product(pl, item, rules):
    need = Needs()
    p = product_of(item)
    if p is None:
        need.problems.append(f"unknown product {item.get('product')}")
        return need
    qty = int(item["qty"])
    if qty < 1:
        need.problems.append("Quantity: 1 or more")
        return need
    size, paper = cat.size_of(p, item["picks"]), cat.choice(p, "paper", item["picks"])
    sides = 2 if cat.choice(p, "sides", item["picks"]) == "Both sides" else 1
    colour = "bw" if cat.choice(p, "colour", item["picks"]) == "Black and white" else "color"
    pieces, sheets = qty, 0
    if p["id"] == "envelope":
        kind = size.split()[0]
        price = pl.envelopes.get((size, paper))
        if price is None:
            need.problems.append(no_price(f"{size}, {paper} envelope"))
        else:
            need.cost(f"{qty} envelopes {size}, {paper} x {money(price)}", qty * price)
        need.copy("A3" if kind in ENVELOPE_A3 else "A4", colour, qty * sides)
    elif p["id"] == "labels":
        sheets = qty
        need.copy("A4", colour, sheets * sides)
        _paper(pl, sheets, need, "Label sheet", "A4")
    elif p["id"] in cat.BOOKLETS:
        pages_text = cat.choice(p, "extra", item["picks"]) or ""
        if not pages_text.split()[0].isdigit():
            need.problems.append(f"{p['name']}: the pages are a range (“{pages_text}”), so ORCA can't count the "
                                 f"sheets. Use a Document with Spiral finishing instead")
            return need
        pages = int(pages_text.split()[0])
        w, h = cat.CUT_MM[size]
        try:
            lay = layout(rules, 2 * w, h, f"{p['name']} {size} (opened {round(2 * w)} x {round(h)} mm)")
        except ValueError as e:
            need.problems.append(str(e))
            return need
        per_copy = math.ceil(pages / 4)
        sheets = math.ceil(per_copy * qty / lay["per"])
        need.copy(lay["sheet"], colour, sheets * 2)
        _paper(pl, sheets, need, paper, lay["sheet"])
        _cuts(pl, need, lay, sheets, paper)
        if p["id"] == "stapled":
            if pl.staple is None:
                need.problems.append(no_price("Staple (per copy)"))
            else:
                need.cost(f"Staple: {qty} x {money(pl.staple)}", qty * pl.staple)
    else:
        cut = cat.CUT_MM.get(size)
        if cut is None:
            need.problems.append(f"{p['name']} {size}: no cut size known")
            return need
        try:
            lay = layout(rules, cut[0], cut[1], f"{p['name']} {size}")
        except ValueError as e:
            need.problems.append(str(e))
            return need
        sheets = math.ceil(qty / lay["per"])
        need.copy(lay["sheet"], colour, sheets * sides)
        _paper(pl, sheets, need, paper, lay["sheet"])
        _cuts(pl, need, lay, sheets, paper)
    need.sheets = sheets
    extra = cat.choice(p, "extra", item["picks"]) if p["id"] not in cat.BOOKLETS else None
    if extra and extra != "None":
        _extra(pl, need, extra, pl.extras, "product extra", pieces, sheets)
    _services(pl, need, item, pieces, sheets)
    return need


def needs(pl, item, rules=None):
    rules = rules if rules is not None else rules_now()
    return _document(pl, item) if item["kind"] == "document" else _product(pl, item, rules)


# ------------------------------------------------------------------ the order

def price_order(pl, items, loyalty=0, rounding=None, rules=None):
    """Everything the price list shows: each item's price and working lines, the volume line (never more for fewer
    copies), subtotal, loyalty line, total, and `due`: the total after the staff's rounding."""
    all_needs = [needs(pl, item, rules) for item in items]
    problems = [f"Item {i + 1}: {p}" for i, n in enumerate(all_needs) for p in n.problems]
    counts = {}
    for n in all_needs:
        for key, k in n.copies.items():
            counts[key] = counts.get(key, 0) + k
    tiers = {key: pl.tier_of(count) for key, count in counts.items()}
    lines = []
    for i, (item, n) in enumerate(zip(items, all_needs)):
        working = [describe(item)]
        price = 0.0
        bad = bool(n.problems)
        for (size, colour), k in sorted(n.copies.items()):
            tier = tiers[(size, colour)]
            rate = pl.copies[(size, colour)][tier - 1]
            if rate is None:
                problems.append(f"Item {i + 1}: {no_price(f'{size} {COLOUR_WORD[colour]} copies, Tier {tier}')}")
                bad = True
                continue
            amount = r2(k * rate)
            working.append(f"{k} {size} {COLOUR_WORD[colour]} copies x {money(rate)} (tier {tier}) = {money(amount)}")
            price += amount
        for text, amount in n.lines:
            working.append(f"{text} = {money(amount)}")
            price += amount
        price = 0.0 if bad else r2(price)
        working.append(f"Total {money(price)}")
        lines.append({"price": price, "note": "", "working": working, "copies": {f"{s} {c}": k for (s, c), k
                                                                                in n.copies.items()},
                      "sheets": n.sheets})
    # Never pay more for fewer: per size and colour, the next tier's lowest count when that costs less in total.
    adjust = 0.0
    for key, count in counts.items():
        rates = pl.copies[key]
        tier = tiers[key]
        if rates[tier - 1] is None:
            continue
        normal = count * rates[tier - 1]
        best = normal
        for k in range(tier + 1, 4):
            start = pl.tier_start(k)
            if start is None or rates[k - 1] is None or start <= count:
                continue
            best = min(best, start * rates[k - 1])
        if best - normal < -0.004:
            adjust += best - normal
    adjust = r2(adjust)
    subtotal = r2(sum(l["price"] for l in lines) + adjust)
    pct = pl.loyalty.get(loyalty) if loyalty else None
    if loyalty and pct is None:
        loyalty_line = {"level": loyalty, "pct": None, "amount": 0.0,
                        "text": f"Loyalty {loyalty} (no discount set yet)"}
    elif loyalty:
        amount = -r2(subtotal * pct / 100)
        loyalty_line = {"level": loyalty, "pct": pct, "amount": amount,
                        "text": f"Loyalty {loyalty} ({pct:g}% off)"}
    else:
        loyalty_line = None
    total = r2(subtotal + (loyalty_line["amount"] if loyalty_line else 0))
    return {"lines": lines, "volume": adjust, "subtotal": subtotal, "loyalty": loyalty_line, "total": total,
            "rounding": rounding if rounding in ROUNDINGS else None, "due": rounded(total, rounding),
            "problems": problems}
