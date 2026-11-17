"""The website's products and prices, copied for walk-in orders (2026-11-17).

A copy of C:\\PrintHub\\Website\\lib\\products.ts and lib\\pricing.ts (read only, the website is never changed):
the products with their options, choices and quantities, and the website prices. ORCA prices walk-in orders
from ORCA_Walk-in_Prices.xlsx (walkin_prices.py); these website prices are what an empty or unreadable
cell there falls back to, and everything when the spreadsheet can't be read.
When the website's catalogue changes, change this copy the same way.
"""

SIDES = ["One side", "Both sides"]
LAMINATION = ["None", "Matt lamination", "Gloss lamination"]


def _sq(mm):
    return f"Square {mm} x {mm} mm"


def _p(pid, name, qty, base, sizes, papers, sides=False, extra=None):
    options = [{"key": "size", "label": "Size", "choices": sizes}, {"key": "paper", "label": "Paper", "choices": papers}]
    if sides:
        options.append({"key": "sides", "label": "Sides", "choices": SIDES})
    if extra:
        options.append({"key": "extra", "label": extra[0], "choices": extra[1]})
    return {"id": pid, "name": name, "qty": qty, "base": base, "options": options}


def _silk(g): return f"Silk {g} gsm"
def _gloss(g): return f"Gloss {g} gsm"
def _white(g): return f"Smooth white {g} gsm"
def _ivory(g): return f"Ivory {g} gsm"
def _kraft(g): return f"Kraft {g} gsm"
def _coloured(g): return f"Coloured {g} gsm"


METALLIC, GOLD_SILVER, TEXTURED = "Metallic pearl 250 gsm", "Gold or silver 250 gsm", "Textured linen 270 gsm"

PRODUCTS = [
    _p("bcard", "Business cards", [100, 250, 500, 1000], 15, ["85 x 55 mm", "90 x 50 mm", _sq(55)],
       [_white(300), _white(350), _silk(300), METALLIC, TEXTURED], sides=True),
    _p("loyalty", "Loyalty / stamp cards", [250, 500, 1000], 22, ["85 x 55 mm"], [_white(300), _white(350)], sides=True),
    _p("vouchers", "Gift vouchers", [25, 50, 100, 250], 16, ["DL 99 x 210 mm", "A6", "85 x 55 mm"],
       [_silk(300), _white(300), _ivory(300), METALLIC], sides=True, extra=("Extras", ["None", "With envelopes"])),
    _p("envelope", "Printed envelopes", [100, 250, 500, 1000], 25,
       ["DL 110 x 220 mm", "C5 162 x 229 mm", "C6 114 x 162 mm", "C4 229 x 324 mm"], ["White", "Kraft", "Coloured"]),
    _p("certificate", "Certificates & diplomas", [10, 25, 50, 100], 15, ["A4", "A5"],
       [_ivory(300), _silk(300), _white(250), METALLIC, GOLD_SILVER]),
    _p("badge", "Name badges", [10, 25, 50, 100, 250], 10, ["90 x 55 mm", "100 x 70 mm", "A6", "A7"],
       [_white(300), _silk(300)], sides=True, extra=("Finishing", ["None", "Laminated"])),
    _p("flyer", "Flyers", [50, 100, 250, 500, 1000], 12, ["A6", "A5", "A4", "A3", _sq(148), _sq(210)],
       [_silk(130), _silk(170), _gloss(130), _gloss(170), _silk(250), _white(90), _coloured(80)], sides=True),
    _p("stapled", "Stapled booklets", [10, 25, 50, 100, 250], 35, ["A5", "A4", "A6", _sq(148)],
       [_silk(130), _gloss(130), _silk(170), _white(100)],
       extra=("Pages", ["8 pages", "12 pages", "16 pages", "24 pages", "32 pages"])),
    _p("wire", "Spiral bound booklets", [1, 10, 25, 50, 100], 8, ["A4", "A5", "A6"], [_white(100), _white(160), _silk(130)],
       extra=("Pages", ["Up to 50 pages", "51-100 pages", "101-200 pages"])),
    _p("poster", "Posters", [1, 2, 5, 10, 25], 5, ["A4", "A3"],
       [_gloss(170), _silk(170), _gloss(250), _silk(250), _white(200)], extra=("Finishing", LAMINATION)),
    _p("menu", "Menus", [1, 10, 25, 50, 100], 4, ["A4", "A3", "A5", "DL 99 x 210 mm"],
       [_silk(300), _gloss(250), _silk(250), _white(300)], sides=True, extra=("Finishing", ["None", "Pouch laminated"])),
    _p("takeaway", "Takeaway & delivery menus", [250, 500, 1000, 2500], 35, ["DL 99 x 210 mm", "A5"],
       [_silk(130), _gloss(130), _silk(170)], sides=True),
    _p("insertcard", "Thank-you & insert cards", [100, 250, 500, 1000], 16, ["A6", "85 x 55 mm", _sq(100)],
       [_silk(300), _white(350), _kraft(275)], sides=True),
    _p("coupon", "Coupons", [100, 250, 500, 1000], 14, ["DL 99 x 210 mm", "A6", "1/3 A4"],
       [_white(160), _silk(170), _silk(250)], sides=True),
    _p("invite", "Invitations", [25, 50, 100, 200, 300, 500], 18,
       ["A5", "A6", "DL 99 x 210 mm", _sq(148), _sq(100), "A7", "85 x 55 mm"],
       [_ivory(300), _silk(300), _white(300), METALLIC, TEXTURED, _kraft(275)], sides=True,
       extra=("Extras", ["None", "With envelopes"])),
]
BY_ID = {p["id"]: p for p in PRODUCTS}

# The paper most customers pick: selected first, as on the website.
POPULAR_PAPER = {
    "bcard": "Silk 300 gsm", "vouchers": "Silk 300 gsm", "menu": "Silk 300 gsm", "insertcard": "Silk 300 gsm",
    "loyalty": "Smooth white 300 gsm", "badge": "Smooth white 300 gsm",
    "certificate": "Ivory 300 gsm", "invite": "Ivory 300 gsm",
    "flyer": "Silk 170 gsm", "coupon": "Silk 170 gsm",
    "stapled": "Silk 130 gsm", "takeaway": "Silk 130 gsm", "wire": "Smooth white 100 gsm", "poster": "Gloss 170 gsm",
    "envelope": "White",
}

# Website prices (owner, 2026-11-12): EUR for the whole quantity, one side; the same size costs the same everywhere.
_DL = {1: 2, 10: 10, 25: 15, 30: 20, 50: 25, 100: 40, 200: 70, 250: 90, 300: 100, 500: 150, 1000: 250, 2500: 500}
PRICE_TABLE = {
    "Square 55 x 55 mm": {100: 15, 250: 35, 500: 55, 1000: 80},
    "90 x 50 mm": {100: 20, 250: 45, 500: 65, 1000: 80},
    "85 x 55 mm": {25: 8, 50: 15, 100: 20, 200: 35, 250: 40, 300: 50, 500: 70, 1000: 125},
    "90 x 55 mm": {10: 5, 25: 10, 50: 15, 100: 20, 250: 40},
    "100 x 70 mm": {10: 6, 25: 12, 50: 20, 100: 35, 250: 50},
    "A7": {10: 5, 25: 10, 50: 15, 100: 25, 200: 40, 250: 45, 300: 50, 500: 70},
    "Square 100 x 100 mm": {25: 12, 50: 20, 100: 30, 200: 50, 250: 60, 300: 65, 500: 90, 1000: 170},
    "A6": {10: 5, 25: 10, 30: 12, 50: 15, 100: 25, 200: 40, 250: 50, 300: 55, 500: 90, 1000: 150},
    "DL 99 x 210 mm": _DL, "1/3 A4": _DL,  # the same size: one row
    "Square 148 x 148 mm": {25: 15, 50: 30, 100: 50, 200: 90, 250: 120, 300: 130, 500: 220, 1000: 400},
    "A5": {1: 2, 10: 10, 25: 20, 30: 25, 50: 35, 100: 50, 200: 80, 250: 100, 300: 120, 500: 150, 1000: 250, 2500: 500},
    "Square 210 x 210 mm": {50: 50, 100: 80, 250: 190, 500: 350, 1000: 500},
    "A4": {1: 3, 2: 4, 5: 8, 10: 10, 25: 20, 50: 35, 100: 50, 250: 115, 500: 200, 1000: 300},
    "A3": {1: 4, 2: 7, 5: 16, 10: 20, 25: 40, 50: 70, 100: 100, 250: 230, 500: 400, 1000: 600},
}
BOTH_SIDES = 1.5
DESIGN_FEE = 1
GROUP_TOGETHER = True
EXAMPLE_PRICED = ("envelope", "stapled", "wire")  # the website's example formula (no real price yet)
EXTRA_STEP = 0.12  # Finishing / Extras: +12% per position in the list on the website

CUT_MM = {
    "85 x 55 mm": (85, 55), "90 x 50 mm": (90, 50), "90 x 55 mm": (90, 55), "Square 55 x 55 mm": (55, 55),
    "100 x 70 mm": (100, 70), "Square 100 x 100 mm": (100, 100), "A7": (74, 105), "A6": (105, 148), "A5": (148, 210),
    "A4": (210, 297), "A3": (297, 420), "DL 99 x 210 mm": (99, 210), "1/3 A4": (99, 210),
    "Square 148 x 148 mm": (148, 148), "Square 210 x 210 mm": (210, 210),
    "DL 110 x 220 mm": (110, 220), "C6 114 x 162 mm": (114, 162), "C5 162 x 229 mm": (162, 229),
    "C4 229 x 324 mm": (229, 324),
}

# Documents (lib/pricing.ts): EUR per printed side, tiers at 100 / 200 / 500 sides across all documents.
DOC_RATES = {"A4": {"bw": [0.12, 0.10, 0.08, 0.05], "color": [0.40, 0.35, 0.30, 0.25]},
             "A3": {"bw": [0.24, 0.20, 0.16, 0.10], "color": [0.80, 0.70, 0.60, 0.40]}}
DOC_TIERS = [0, 100, 200, 500]
GLOSSY_UNDER_100, GLOSSY_FROM_100 = 0.10, 0.05  # EUR per sheet; under 100 sheets capped at 100 x the 100+ rate
LAMINATION_PER_SHEET = {"A4": 1.0, "A3": 2.0}
SPIRAL_BANDS = [(50, 1.5), (100, 2.0), (300, 2.5)]  # per copy, by sheets per copy; over 300 can't be bound
STAPLE_PER_COPY = 0.0
DOC_PAPERS = ["Normal 80 gsm", "Glossy 100 gsm"]  # the website's two; extra rows come from the spreadsheet
PER_SIDE = [1, 2, 4, 8, 16]


def r2(x):
    """Round to cents the way the website does (JavaScript Math.round: halves go up)."""
    import math
    return math.floor(x * 100 + 0.5 + 1e-9) / 100


def size_of(product, picks):
    return choice(product, "size", picks)


def choice(product, key, picks):
    for o in product["options"]:
        if o["key"] == key:
            return o["choices"][picks.get(key, 0)]
    return None


def default_picks(product):
    picks = {o["key"]: 0 for o in product["options"]}
    for o in product["options"]:
        if o["key"] == "paper" and POPULAR_PAPER.get(product["id"]) in o["choices"]:
            picks["paper"] = o["choices"].index(POPULAR_PAPER[product["id"]])
    return picks


def example_price(product, qty, picks):
    """The website's example formula (envelopes and booklets): base scaled by quantity, each later choice a bit more."""
    by_qty = product["base"] * (qty / product["qty"][0]) ** 0.75
    factor = 1.0
    for o in product["options"]:
        factor *= 1 + (0.3 if o["key"] == "sides" else 0.12) * picks.get(o["key"], 0)
    return r2(by_qty * factor)
