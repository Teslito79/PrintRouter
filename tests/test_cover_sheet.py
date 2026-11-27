"""Cover sheet: no heading, centred. Rendered from the PDF itself."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import os, sys
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
helpers.temp_admin(OUT / "admin")  # ORCA reads its files from a temp ADMIN, never the real one
sys.path.insert(0, str(APP)); os.chdir(APP)
import jobs, walkin_print
import pypdfium2 as pdfium

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", info)


def order(n, items, changed=None):
    return {"number": n, "created": "2026-11-17T10:00:00", "changed_total": changed, "total": 101.16,
            "customer": {"name": "Maria Georgiou", "phone": "99 123 456", "email": "maria@example.com"},
            "items": [{"description": d} for d in items]}


def analyse(path, name):
    """Render each page; per page: the ink box (left, right, top, bottom in mm) and the text."""
    doc = pdfium.PdfDocument(str(path))
    pages = []
    for i, page in enumerate(doc):
        img = page.render(scale=2).to_pil().convert("L")
        if name:
            img.save(OUT / f"{name}{'' if i == 0 else f'_page{i + 1}'}.png")
        px = img.load()
        w, h = img.size
        rows = [y for y in range(h) if any(px[x, y] < 128 for x in range(0, w, 2))]
        cols = [x for x in range(w) if any(px[x, y] < 128 for y in range(rows[0], rows[-1] + 1, 2))] if rows else []
        mm = 210 / w
        text = page.get_textpage().get_text_range().replace("\xa0", " ").replace("\xad", "-").replace("\r", "")
        lines = []
        for line_y in sorted(set(rows)):
            pass
        pages.append({"left": cols[0] * mm, "right": (w - cols[-1]) * mm, "top": rows[0] * mm, "bottom": (h - rows[-1]) * mm,
                      "text": text, "img": img})
    doc.close()
    return pages


def line_balance(img):
    """For every text line on the page: |left space - right space| in mm (centred lines: about 0)."""
    px = img.load(); w, h = img.size
    bands, inside, start = [], False, 0
    for y in range(h):
        ink = any(px[x, y] < 128 for x in range(0, w, 2))
        if ink and not inside:
            inside, start = True, y
        elif not ink and inside:
            inside = False
            bands.append((start, y))
    out = []
    for a, b in bands:
        xs = [x for x in range(w) if any(px[x, y] < 128 for y in range(a, b))]
        out.append(abs(xs[0] - (w - 1 - xs[-1])) * 210 / w)
    return out


with jobs.PDF_LOCK:
    for name, o in (("cover_one_item", order(101, ["100 x Business cards, 85 x 55 mm, Silk 300 gsm, One side"])),
                    ("cover_100_three_items", order(100, ["250 x Business cards, 85 x 55 mm, Silk 300 gsm, Both sides",
                                                          "100 x Flyers, A5, Silk 170 gsm, One side",
                                                          "Document A4, 10 pages x 2, B&W, one side, Normal 80 gsm"]))):
        walkin_print.cover_pdf(o, OUT / f"{name}.pdf")
        p = analyse(OUT / f"{name}.pdf", name)
        check(f"{name}: one page, no 'ORCA walk-in order'", len(p) == 1 and "ORCA walk-in order" not in p[0]["text"]
              and f"#{o['number']}" in p[0]["text"])
        bal = line_balance(p[0]["img"])
        check(f"{name}: every line centred left to right (within 1 mm)", max(bal) < 1.0, [round(b, 2) for b in bal])
        check(f"{name}: block centred top to bottom (within 3 mm)", abs(p[0]["top"] - p[0]["bottom"]) < 3,
              f"top {p[0]['top']:.1f} mm, bottom {p[0]['bottom']:.1f} mm")
    # A cover sheet too long for one centred block (2026-11-19_01 on: the Counter and Extras, not the items): an
    # order with a document on every paper, in A4 and A3, gives one Extras line per paper and size.
    import price_sheet, walkin_prices
    price_sheet.test_sheet(helpers.PRICE_TEMPLATE, OUT / "admin" / "Walk-in_Prices.xlsx")
    papers = [x for x in walkin_prices.load(OUT / "admin" / "Walk-in_Prices.xlsx").doc_papers()
              if x not in walkin_print.PLAIN_PAPERS]

    def doc(size, paper):
        return {"kind": "document", "size": size, "pages": 2, "copies": 3, "color": "bw", "color_pages": "",
                "sides": "single", "per_side": 1, "paper": paper, "finish": "none", "lam": False, "lam_sheets": 0,
                "description": f"Document {size}, {paper}"}
    many = [doc(size, paper) for paper in papers for size in ("A4", "A3")]
    walkin_print.cover_pdf(order(150, []) | {"items": many}, OUT / "cover_long.pdf")
    p = analyse(OUT / "cover_long.pdf", "cover_long")
    text = "".join(pg["text"] for pg in p)
    want = [f"{paper}: 6 {size} sheets" for paper in papers for size in ("A4", "A3")]
    check(f"long cover ({len(want)} Extras lines): starts at the top margin", p[0]["top"] < 25,
          f"top {p[0]['top']:.1f} mm, {len(p)} pages")
    check("long cover: every line is there (runs onto the next page when needed)",
          all(w in text for w in want) and f"A4 B&W: {6 * len(papers)}" in text
          and f"A3 B&W: {6 * len(papers)}" in text and len(p) > 1,
          [w for w in want if w not in text][:5])
    last = p[-1]["img"]
    bal = line_balance(last.crop((0, 0, last.size[0], int(last.size[1] * 0.9))))  # not the "Page 2 of 2" footer
    check("long cover: the lines on the last page are centred too", max(bal) < 1.0, [round(b, 2) for b in bal][:12])
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
