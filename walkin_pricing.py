"""Prices for a walk-in order (2026-11-17): the website's rules with the walk-in prices (walkin_prices.PriceList).

Prices come only from Walk-in_Prices.xlsx (2026-11-17_07): a price that is empty there (or a size, quantity or
paper that isn't in it) is a problem, "No price in the price list for …", and the item can't be added or placed.
Products: price by size and quantity, Both sides x the Settings value (x1 while empty), extras (% of the item, per
piece or per line), same-size items priced together when Settings says Yes (cheapest exact sum, never more than a
larger priced quantity, plus the extra design fee per design after the first, only when cheaper). Envelopes and
booklets: the price for size, pages and quantity. Documents: per printed side with tiers across all document items
in the order, paper, lamination, spiral and staple, and "never pay more for fewer pages". Loyalty: that level's %
off the whole order, after the quantity price. Rounding (rounded()): staff may only round the total. No delivery fee.
"""
import math

import walkin_catalogue as cat
from walkin_catalogue import r2

SAME_ROW = {"1/3 A4": "DL 99 x 210 mm"}  # sizes that are one price row
SHEET = "Walk-in_Prices.xlsx"


def euro(x):
    return f"EUR {x:,.2f}"


def no_price(what):
    return f"No price in the price list for {what}: fill it in in {SHEET}"


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
        return ", ".join(parts)
    p = product_of(item)
    picks = [o["choices"][item["picks"].get(o["key"], 0)] for o in p["options"]]
    return f"{item['qty']} x {p['name']}, " + ", ".join(c for c in picks if c not in ("None",))


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


# ------------------------------------------------------------------ products

def _row(pl, size):
    return pl.products.get(SAME_ROW.get(size, size)) or pl.products.get(size)


def group_price(pl, size, q):
    """One-side price for q pieces: the price for exactly q, else the cheapest exact sum of priced quantities,
    never more than a larger priced quantity (the website's groupPrice)."""
    row = _row(pl, size)
    if not row or q <= 0:
        return None
    if q in row:
        return row[q]
    cents = {k: round(v * 100) for k, v in row.items()}
    best = [0] + [math.inf] * q
    for n in range(1, q + 1):
        for k, c in cents.items():
            if k <= n and best[n - k] + c < best[n]:
                best[n] = best[n - k] + c
    larger = [c for k, c in cents.items() if k > q]
    value = min([best[q]] + larger)
    return None if value == math.inf else value / 100


def _extra(pl, p, item):
    """(factor on the price, fixed EUR added, problem or None): the extra's price from the Extras sheet."""
    for o in p["options"]:
        if o["key"] == "extra" and p["id"] not in cat.EXAMPLE_PRICED:
            idx = item["picks"].get("extra", 0)
            if idx == 0:
                return 1.0, 0.0, None
            choice = o["choices"][idx]
            if choice not in pl.extras:
                return 1.0, 0.0, no_price(f"{choice} ({p['name']})")
            price, how = pl.extras[choice]
            if how == "pct":
                return 1 + price / 100, 0.0, None
            return 1.0, (price * item["qty"] if how == "piece" else price), None
    return 1.0, 0.0, None


def _sides(pl, p, item):
    return pl.sides_factor() if cat.choice(p, "sides", item["picks"]) == "Both sides" else 1.0


def product_alone(pl, item):
    """(price, problem or None) for one product item on its own."""
    p = product_of(item)
    if p is None:
        return 0.0, f"unknown product {item.get('product')}"
    size = cat.size_of(p, item["picks"])
    if p["id"] in cat.EXAMPLE_PRICED:
        pages = cat.choice(p, "extra", item["picks"])
        price = pl.examples.get((p["id"], size, pages, item["qty"]))
        if price is None:
            return 0.0, no_price(f"{p['name']} {size}{', ' + pages if pages else ''} x {item['qty']}")
        return price, None
    base = _row(pl, size).get(item["qty"]) if _row(pl, size) else None
    if base is None:
        return 0.0, no_price(f"{p['name']} {size} x {item['qty']}")
    factor, fixed, problem = _extra(pl, p, item)
    if problem:
        return 0.0, problem
    return r2(base * _sides(pl, p, item) * factor + fixed), None


def price_products(pl, items):
    """[(price, note)] for the product items (by their index in items); same-size items priced together."""
    out = {}
    problems = []
    bad = set()
    for i, item in enumerate(items):
        if item["kind"] == "product":
            price, problem = product_alone(pl, item)
            out[i] = [price, ""]
            if problem:
                problems.append(f"Item {i + 1}: {problem}")
                bad.add(i)
    if not pl.group:
        return out, problems
    groups = {}
    for i, item in enumerate(items):
        p = product_of(item) if item["kind"] == "product" else None
        if p is None or p["id"] in cat.EXAMPLE_PRICED or i in bad:
            continue
        size = cat.size_of(p, item["picks"])
        groups.setdefault(SAME_ROW.get(size, size), []).append(i)
    for size, idx in groups.items():
        if len(idx) < 2:
            continue
        q = sum(items[i]["qty"] for i in idx)
        gp = group_price(pl, size, q)
        if gp is None:
            continue
        g_cents = round(gp * 100) + round(pl.design_fee * 100) * (len(idx) - 1)
        exact = [g_cents * items[i]["qty"] / q for i in idx]
        share = [math.floor(x) for x in exact]
        left = g_cents - sum(share)
        for j in sorted(range(len(idx)), key=lambda j: (-(exact[j] - share[j]), j)):
            if left <= 0:
                break
            share[j] += 1
            left -= 1
        priced = []
        for j, i in enumerate(idx):
            p = product_of(items[i])
            factor, fixed, _ = _extra(pl, p, items[i])
            priced.append(r2(share[j] / 100 * _sides(pl, p, items[i]) * factor + fixed))
        alone = sum(round(out[i][0] * 100) for i in idx)
        save = alone - sum(round(x * 100) for x in priced)
        if save <= 0:
            continue
        note = (f"Priced together: {q} x {size}, {len(idx)} designs. "
                f"Saves {euro(save / 100)} ({round(save / alone * 100)}%).")
        for j, i in enumerate(idx):
            out[i] = [priced[j], note]
    return out, problems


# ------------------------------------------------------------------ documents

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
    """Printed sides (B&W, colour) and sheets for one document item, copies included (the website's way)."""
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


def price_documents(pl, items):
    """({item index: price}, volume adjustment (<= 0), problems)."""
    docs = [(i, it, doc_counts(it)) for i, it in enumerate(items) if it["kind"] == "document"]
    billed = sum(c["bw"] + c["color"] for _, _, c in docs)
    tier = 3 if billed >= 500 else 2 if billed >= 200 else 1 if billed >= 100 else 0
    tier_names = ["1-99 sides", "100-199 sides", "200-499 sides", "500+ sides"]
    colour_names = {"bw": "black and white", "color": "colour"}
    out, problems = {}, []
    for i, it, c in docs:
        if c["pages"] == 0:
            out[i] = 0.0
            problems.append(f"Item {i + 1}: no pages")
            continue
        missing = []
        rates = pl.doc_rates[it["size"]]
        amount = 0.0
        for mode in ("bw", "color"):
            if c[mode]:
                if rates[mode][tier] is None:
                    missing.append(f"{it['size']} {colour_names[mode]}, {tier_names[tier]}")
                else:
                    amount += c[mode] * rates[mode][tier]
        paper = pl.doc_papers.get(it["paper"])
        if paper == "glossy":
            under, over = pl.glossy
            if c["sheets"] < 100 and (under is None or over is None):
                missing.append("Glossy 100 gsm (under 100 sheets, and 100 sheets or more for the cap)")
            elif c["sheets"] >= 100 and over is None:
                missing.append("Glossy 100 gsm (100 sheets or more)")
            else:
                amount += min(c["sheets"] * under, 100 * over) if c["sheets"] < 100 else c["sheets"] * over
        elif isinstance(paper, (int, float)):
            amount += c["sheets"] * paper
        elif it["paper"] not in pl.doc_papers:
            missing.append(f"the paper “{it['paper']}”")
        if it.get("finish") == "spiral":
            band = next(((limit, price) for limit, price in pl.spiral if c["sheets_per_copy"] <= limit), None)
            if band is None:
                problems.append(f"Item {i + 1}: more than {pl.spiral[-1][0]} sheets per copy can't be spiral bound")
            elif band[1] is None:
                missing.append(f"Spiral binding ({c['sheets_per_copy']} sheets per copy)")
            else:
                amount += band[1] * c["copies"]
        elif it.get("finish") == "staple":
            if pl.staple is None:
                missing.append("Staple")
            else:
                amount += pl.staple * c["copies"]
        if it.get("lam"):
            n = min(int(it.get("lam_sheets") or 0) or c["sheets"], c["sheets"])
            if pl.lamination[it["size"]] is None:
                missing.append(f"Lamination {it['size']}")
            else:
                amount += n * pl.lamination[it["size"]]
        for what in missing:
            problems.append(f"Item {i + 1}: {no_price(what)}")
        out[i] = 0.0 if missing else amount
    # Never pay more for fewer pages: the next tier's rate (with padding pages) when that is cheaper.
    # A tier with an empty rate that this order would need is left out.
    def print_at(k):
        total = 0.0
        for _, it, c in docs:
            for mode in ("bw", "color"):
                if c[mode]:
                    rate = pl.doc_rates[it["size"]][mode][k]
                    if rate is None:
                        return None
                    total += c[mode] * rate
        return total
    active = [(it, c) for _, it, c in docs if c["pages"] > 0]
    adjust = 0.0
    normal = print_at(tier) if active else None
    if normal is not None:
        best = normal
        for k in range(tier + 1, 4):
            at = print_at(k)
            pads = [pl.doc_rates[it["size"]]["bw"][k] for it, _ in active]
            if at is None or any(r is None for r in pads):
                continue
            best = min(best, at + (cat.DOC_TIERS[k] - billed) * min(pads))
        if best - normal < -0.004:
            adjust = best - normal
    return {i: r2(v) for i, v in out.items()}, r2(adjust), problems


# ------------------------------------------------------------------ the order

def price_order(pl, items, loyalty=0, rounding=None):
    """Everything the price list shows: item prices and notes, volume line, subtotal, loyalty line, total, and
    `due`: the total after the staff's rounding (the same as total without one)."""
    prod, problems = price_products(pl, items)
    docs, adjust, doc_problems = price_documents(pl, items)
    lines = []
    for i, item in enumerate(items):
        price, note = prod[i] if i in prod else (docs.get(i, 0.0), "")
        lines.append({"price": r2(price), "note": note})
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
            "problems": problems + doc_problems}
