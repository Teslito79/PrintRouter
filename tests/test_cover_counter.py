"""Handoff 2026-11-19_01: the cover sheet's "Counter" instead of "Items". Price lists in a temp folder; cover sheet
PDFs rendered to PNG; nothing printed."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import json, os, shutil, sys
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
helpers.temp_admin(OUT / "admin")  # ORCA reads its files from a temp ADMIN, never the real one
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
import jobs, routing, walkin_prices as wp, walkin_pricing as P, walkin_print
import price_sheet as ps
import pypdfium2 as pdfium

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:700])


EMPTY = Path(str(helpers.PRICE_TEMPLATE))
FILLED = ps.test_sheet(EMPTY, TMP / "filled.xlsx")
filled, trial, empty = wp.load(FILLED), wp.load(APP / "Walk-in_Prices.xlsx"), wp.load(EMPTY)
rules = routing.load_rules()


def doc(pages, copies, color="bw", sides="single", size="A4", paper="Normal 80 gsm", **kw):
    d = {"kind": "document", "size": size, "pages": pages, "copies": copies, "color": color, "color_pages": "",
         "sides": sides, "per_side": 1, "paper": paper, "finish": "none", "lam": False, "lam_sheets": 0}
    d.update(kw)
    return d


def bcard(qty, paper=2, sides=0, **kw):
    d = {"kind": "product", "product": "bcard", "qty": qty, "picks": {"size": 0, "paper": paper, "sides": sides}}
    d.update(kw)
    return d


def order(n, items, total=101.16):
    return {"number": n, "created": "2026-11-19T10:00:00", "changed_total": None, "total": total,
            "customer": {"name": "Maria Georgiou", "phone": "99 123 456", "email": "maria@example.com"}, "items": items}


def pdf_text(path, name=None):
    d = pdfium.PdfDocument(str(path))
    texts = []
    for i, page in enumerate(d):
        if name:
            page.render(scale=2).to_pil().save(OUT / f"{name}{'' if i == 0 else f'_page{i + 1}'}.png")
        texts.append(page.get_textpage().get_text_range().replace("\xa0", " ").replace("\r", ""))
    n = len(d); d.close()
    return "\n".join(texts), n


# ------------------------------------------------------------------ the mixed order
mixed = [
    doc(10, 2, sides="double", finish="staple"),                                   # A4 B&W both sides: 20 copies, 10 sheets
    doc(6, 3, color="mixed", color_pages="1,2", finish="spiral", lam=True, lam_sheets=4,
        services={"Folding": True}),                                              # A4: 6 colour + 12 B&W copies
    doc(2, 1, color="color", size="A3", paper="Gloss 130 gsm"),                    # the A3 colour poster
    bcard(250, sides=0),                                                          # 32 A4 colour copies on Silk 300
]
lines = walkin_print.counter_lines(order(100, mixed), filled, rules)
check("mixed order: the copy lines, summed over the order, in the order A4 B&W, A4 colour, A3 colour",
      lines[0] == ["A4 B&W: 32", "A4 colour: 38", "A3 colour: 2"], lines[0])
check("…the extras in the order: papers that aren't plain, lamination, spiral, staple, cuts, then services",
      lines[1] == ["Gloss 130 gsm: 2 A3 sheets", "Silk 300 gsm: 32 A4 sheets", "Lamination A4: 4 sheets",
                   "Spiral binding: 3", "Staple: 2", "Cuts: 8", "Folding: 18"], lines[1])
check("…no plain-paper line and no money", not any("80 gsm" in x or "EUR" in x or "." in x.split(":")[-1]
                                                   for x in lines[0] + lines[1]))
want = sum(n for n in P.needs(filled, mixed[0], rules).copies.values()) + 18
check("…a copy is a printed side, the count the price uses", want == 38, want)
path = TMP / "mixed.pdf"
walkin_print.cover_pdf(order(100, mixed), path, rules=dict(rules, walkin_paper_prices=False))
text, pages = pdf_text(path, "cover_mixed_order")
check("the cover sheet shows “Counter” and “Extras”, not “Items” or item descriptions",
      "Counter" in text and "Extras" in text and "Items" not in text and "Business cards" not in text
      and "A4 colour: 38" in text and "Silk 300 gsm: 32 A4 sheets" in text, text)
check("walkin_paper_prices false: no total line", "Total" not in text and "EUR" not in text)
walkin_print.cover_pdf(order(100, mixed), TMP / "money.pdf", rules=dict(rules, walkin_paper_prices=True))
check("walkin_paper_prices true: the total line still shows", "Total: EUR 101.16" in pdf_text(TMP / "money.pdf")[0])

# ------------------------------------------------------------------ plain B&W only
plain = order(101, [doc(10, 2)])
walkin_print.cover_pdf(plain, TMP / "plain.pdf", rules=dict(rules, walkin_paper_prices=False))
text, _ = pdf_text(TMP / "plain.pdf", "cover_plain_bw")
check("a plain B&W document only: “Counter” and “A4 B&W: 20”, no Extras heading",
      walkin_print.counter_lines(plain, filled, rules) == (["A4 B&W: 20"], []) and "Extras" not in text
      and "A4 B&W: 20" in text, text)

# ------------------------------------------------------------------ prices don't matter
same = [walkin_print.counter_lines(order(100, mixed), pl, rules) for pl in (filled, trial, empty)]
check("trial list and Tesla's empty sheet: the same counts as with a filled-in list (copies and extras)",
      same[0][0] == same[1][0] == same[2][0]
      # the trial list charges Folding per piece, which a document item needs typed (ORCA won't add it without):
      and [x for x in same[0][1] if not x.startswith("Folding")] == same[1][1]
      and same[2][1] == [x if not x.startswith("Folding") else "Folding" for x in same[0][1]], same)
check("…even though the empty sheet can't price anything", P.price_order(empty, mixed, rules=rules)["problems"])

# ------------------------------------------------------------------ the same paper twice, Layout done, unknown items
twice = order(102, [bcard(250), bcard(100)])
check("the same paper in two items: one line, summed (32 + 13 Silk 300 sheets)",
      walkin_print.counter_lines(twice, filled, rules)[1] == ["Silk 300 gsm: 45 A4 sheets", "Cuts: 16"],
      walkin_print.counter_lines(twice, filled, rules))
laid = order(103, [bcard(250, sheets=40)])
c = walkin_print.counter_lines(laid, filled, rules)
check("Layout done's sheet count (40) is used for the product's paper line (the price still counts 32)",
      c[1][0] == "Silk 300 gsm: 40 A4 sheets"
      and P.price_order(filled, laid["items"], rules=rules)["lines"][0]["sheets"] == 32, c)
bad = order(104, [doc(0, 1), doc(4, 1)])
check("an item that can't be counted: “Item 1: see the order on screen”",
      walkin_print.counter_lines(bad, filled, rules)[0] == ["A4 B&W: 4", "Item 1: see the order on screen"],
      walkin_print.counter_lines(bad, filled, rules))
env = order(105, [{"kind": "product", "product": "envelope", "qty": 100, "picks": {"size": 0, "paper": 0}},
                  {"kind": "product", "product": "labels", "qty": 10, "picks": {"size": 0, "paper": 0}}])
check("envelopes and label sheets", walkin_print.counter_lines(env, filled, rules)[1][:2] in (
    ["Label sheet: 10 A4 sheets", "DL 110 x 220 mm, White envelopes: 100"],), walkin_print.counter_lines(env, filled, rules))

# ------------------------------------------------------------------ a long order runs on
papers = [p for p in filled.papers if p not in walkin_print.PLAIN_PAPERS and p != wp.LABEL_SHEET]
long = order(150, [doc(1, 1, paper=p, size=s) for p in papers for s in ("A4", "A3")])
walkin_print.cover_pdf(long, TMP / "long.pdf", rules=dict(rules, walkin_paper_prices=False))
text, n = pdf_text(TMP / "long.pdf", "cover_long")
check(f"a long order ({len(papers) * 2} paper lines) runs onto a second page with nothing cut off",
      n >= 2 and all(f"{p}: 1 A4 sheet" in text and f"{p}: 1 A3 sheet" in text for p in papers), (n, len(papers)))
print(f"{sum(results)}/{len(results)} passed")
