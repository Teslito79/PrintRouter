"""The website's products, copied for walk-in orders (2026-11-17), plus walk-in-only Labels (2026-11-17_08).

A copy of C:\\PrintHub\\Website\\lib\\products.ts (read only, the website is never changed): the products with their
sizes, papers, options and quantity choices (the quantity is typed in walk-in; the choices only give the default).
Prices are not here: walk-in items are priced from copies, paper and cuts in Walk-in_Prices.xlsx (walkin_prices.py,
walkin_pricing.py). When the website's catalogue changes, change this copy the same way.
"""

SIDES = ["One side", "Both sides"]
LAMINATION = ["None", "Matt lamination", "Gloss lamination"]


def _sq(mm):
    return f"Square {mm} x {mm} mm"


def _p(pid, name, qty, sizes, papers, sides=False, extra=None):
    options = [{"key": "size", "label": "Size", "choices": sizes}, {"key": "paper", "label": "Paper", "choices": papers}]
    if sides:
        options.append({"key": "sides", "label": "Sides", "choices": SIDES})
    if extra:
        options.append({"key": "extra", "label": extra[0], "choices": extra[1]})
    return {"id": pid, "name": name, "qty": qty, "options": options}


def _silk(g): return f"Silk {g} gsm"
def _gloss(g): return f"Gloss {g} gsm"
def _white(g): return f"Smooth white {g} gsm"
def _ivory(g): return f"Ivory {g} gsm"
def _kraft(g): return f"Kraft {g} gsm"
def _coloured(g): return f"Coloured {g} gsm"


METALLIC, GOLD_SILVER, TEXTURED = "Metallic pearl 250 gsm", "Gold or silver 250 gsm", "Textured linen 270 gsm"

PRODUCTS = [
    _p("bcard", "Business cards", [100, 250, 500, 1000], ["85 x 55 mm", "90 x 50 mm", _sq(55)],
       [_white(300), _white(350), _silk(300), METALLIC, TEXTURED], sides=True),
    _p("loyalty", "Loyalty / stamp cards", [250, 500, 1000], ["85 x 55 mm"], [_white(300), _white(350)], sides=True),
    _p("vouchers", "Gift vouchers", [25, 50, 100, 250], ["DL 99 x 210 mm", "A6", "85 x 55 mm"],
       [_silk(300), _white(300), _ivory(300), METALLIC], sides=True, extra=("Extras", ["None", "With envelopes"])),
    _p("envelope", "Printed envelopes", [100, 250, 500, 1000],
       ["DL 110 x 220 mm", "C5 162 x 229 mm", "C6 114 x 162 mm", "C4 229 x 324 mm"], ["White", "Kraft", "Coloured"]),
    _p("certificate", "Certificates & diplomas", [10, 25, 50, 100], ["A4", "A5"],
       [_ivory(300), _silk(300), _white(250), METALLIC, GOLD_SILVER]),
    _p("badge", "Name badges", [10, 25, 50, 100, 250], ["90 x 55 mm", "100 x 70 mm", "A6", "A7"],
       [_white(300), _silk(300)], sides=True, extra=("Finishing", ["None", "Laminated"])),
    _p("flyer", "Flyers", [50, 100, 250, 500, 1000], ["A6", "A5", "A4", "A3", _sq(148), _sq(210)],
       [_silk(130), _silk(170), _gloss(130), _gloss(170), _silk(250), _white(90), _coloured(80)], sides=True),
    _p("stapled", "Stapled booklets", [10, 25, 50, 100, 250], ["A5", "A4", "A6", _sq(148)],
       [_silk(130), _gloss(130), _silk(170), _white(100)],
       extra=("Pages", ["8 pages", "12 pages", "16 pages", "24 pages", "32 pages"])),
    _p("wire", "Spiral bound booklets", [1, 10, 25, 50, 100], ["A4", "A5", "A6"], [_white(100), _white(160), _silk(130)],
       extra=("Pages", ["Up to 50 pages", "51-100 pages", "101-200 pages"])),
    _p("poster", "Posters", [1, 2, 5, 10, 25], ["A4", "A3"],
       [_gloss(170), _silk(170), _gloss(250), _silk(250), _white(200)], extra=("Finishing", LAMINATION)),
    _p("menu", "Menus", [1, 10, 25, 50, 100], ["A4", "A3", "A5", "DL 99 x 210 mm"],
       [_silk(300), _gloss(250), _silk(250), _white(300)], sides=True, extra=("Finishing", ["None", "Pouch laminated"])),
    _p("takeaway", "Takeaway & delivery menus", [250, 500, 1000, 2500], ["DL 99 x 210 mm", "A5"],
       [_silk(130), _gloss(130), _silk(170)], sides=True),
    _p("insertcard", "Thank-you & insert cards", [100, 250, 500, 1000], ["A6", "85 x 55 mm", _sq(100)],
       [_silk(300), _white(350), _kraft(275)], sides=True),
    _p("coupon", "Coupons", [100, 250, 500, 1000], ["DL 99 x 210 mm", "A6", "1/3 A4"],
       [_white(160), _silk(170), _silk(250)], sides=True),
    _p("invite", "Invitations", [25, 50, 100, 200, 300, 500],
       ["A5", "A6", "DL 99 x 210 mm", _sq(148), _sq(100), "A7", "85 x 55 mm"],
       [_ivory(300), _silk(300), _white(300), METALLIC, TEXTURED, _kraft(275)], sides=True,
       extra=("Extras", ["None", "With envelopes"])),
]
# Labels (walk-in only, 2026-11-17_08): the quantity is A4 label sheets, printed on one side, bought already cut.
PRODUCTS.append({"id": "labels", "name": "Labels", "qty": [1, 5, 10, 20, 50, 100], "options": [
    {"key": "size", "label": "Size", "choices": ["A4 label sheet"]},
    {"key": "paper", "label": "Paper", "choices": ["Label sheet"]},
    {"key": "colour", "label": "Colour", "choices": ["Colour", "Black and white"]}]})
BY_ID = {p["id"]: p for p in PRODUCTS}
BOOKLETS = ("stapled", "wire")  # priced as folded booklets (pages / 4 sheets per copy)

# The paper most customers pick: selected first, as on the website.
POPULAR_PAPER = {
    "bcard": "Silk 300 gsm", "vouchers": "Silk 300 gsm", "menu": "Silk 300 gsm", "insertcard": "Silk 300 gsm",
    "loyalty": "Smooth white 300 gsm", "badge": "Smooth white 300 gsm",
    "certificate": "Ivory 300 gsm", "invite": "Ivory 300 gsm",
    "flyer": "Silk 170 gsm", "coupon": "Silk 170 gsm",
    "stapled": "Silk 130 gsm", "takeaway": "Silk 130 gsm", "wire": "Smooth white 100 gsm", "poster": "Gloss 170 gsm",
    "envelope": "White",
}

CUT_MM = {
    "85 x 55 mm": (85, 55), "90 x 50 mm": (90, 50), "90 x 55 mm": (90, 55), "Square 55 x 55 mm": (55, 55),
    "100 x 70 mm": (100, 70), "Square 100 x 100 mm": (100, 100), "A7": (74, 105), "A6": (105, 148), "A5": (148, 210),
    "A4": (210, 297), "A3": (297, 420), "DL 99 x 210 mm": (99, 210), "1/3 A4": (99, 210),
    "Square 148 x 148 mm": (148, 148), "Square 210 x 210 mm": (210, 210),
    "DL 110 x 220 mm": (110, 220), "C6 114 x 162 mm": (114, 162), "C5 162 x 229 mm": (162, 229),
    "C4 229 x 324 mm": (229, 324),
}

PER_SIDE = [1, 2, 4, 8, 16]


def r2(x):
    """Round to cents (halves go up)."""
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
