"""Printing walk-in orders (Print Jobs, 2026-11-17): settings from the order, the copier from routing, a cover
sheet first, every print logged in print_log.csv as source walk-in with the order number #123.

- Preparer: converts and checks each item's file in the background (documents to PDF with convert.py, page count
  and colour; products: the laid-out PDF must be A4 or A3), so the screen never waits.
- settings_for / job_for: the print settings of an item (staff can override them per item, kept in order.json).
- cover_pdf: the plain A4 cover sheet (customer, number, date, items; no prices on paper, 2026-11-17_09).
- The queue that sends them (customer batches per copier, Pages collected, Print backs): walkin_queue.py.
"""
import datetime
import queue
import re
import tempfile
import threading
from pathlib import Path

import analyze
import convert
import jobs
import orders as ph_orders
import routing
import walkin_catalogue as cat
import walkin_orders
import walkin_pricing

WORK_DIR = Path(tempfile.gettempdir()) / "ORCA" / "walk-in"
TRAY = ph_orders.TRAY
DOC_PAPER_TYPES = {"Normal 80 gsm": "Plain & Recycled", "Glossy 100 gsm": "Coated (Glossy)"}  # as the website's feed
PLAIN = "Plain & Recycled"
COVER = "Cover sheet"


def paper_type_for(rules, paper_name, product=False):
    """The driver paper type for a paper name: the website mapping (rules.json product_papers for products, the
    feed's mapping for documents), else the owner's rule by gsm (80: plain, up to 256: Thick 3, then Thick 4)."""
    if product and paper_name in rules.get("product_papers", {}):
        return rules["product_papers"][paper_name]
    if paper_name == "Label sheet":  # walk-in Labels (2026-11-17_08): the driver's Labels type, Bypass Tray
        return "Labels"
    if paper_name in DOC_PAPER_TYPES:
        return DOC_PAPER_TYPES[paper_name]
    gsm = routing.paper_gsm(paper_name)
    if gsm is None or gsm <= 81:
        return PLAIN
    return "Thick 3(221 to 256 g/m2)" if gsm <= 256 else "Thick 4(257 to 300 g/m2)"


# ------------------------------------------------------------------ preparing files

class Preparer:
    """Converts and checks item files in the background; results by (path, size, mtime)."""

    def __init__(self):
        self.done = {}
        self.wanted = queue.Queue()
        self.busy = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True).start()

    @staticmethod
    def key(path, item):
        st = path.stat()
        return (str(path), st.st_size, st.st_mtime_ns, item["kind"], item.get("size"))

    def get(self, order, item):
        """The prepared file, {"error": ...}, or None while it is being prepared (asked for in the background)."""
        path = walkin_orders.item_file(order, item)
        if path is None:
            return None
        try:
            key = self.key(path, item)
        except OSError:
            return None
        with self.lock:
            if key in self.done:
                return self.done[key]
            if key not in self.busy:
                self.busy.add(key)
                self.wanted.put((key, path, dict(item)))
        return None

    def _work(self):
        while True:
            key, path, item = self.wanted.get()
            try:
                result = self.prepare(path, item)
            except Exception as e:
                result = {"error": f"{path.name}: {e}"}
            with self.lock:
                self.done[key] = result
                self.busy.discard(key)

    @staticmethod
    def prepare(path, item):
        if item["kind"] == "product":
            paper, info = walkin_orders.pdf_sheet(path)
            if paper is None:
                return {"error": f"{path.name}: {info}"}
            with jobs.PDF_LOCK:
                coverage = analyze.color_coverage(path)
                colors = analyze.color_pages(path)
            return {"pdf": path, "paper": paper, "pages": info, "coverage": coverage, "page_colors": colors}
        work = WORK_DIR / re.sub(r"\W", "_", str(path))[-80:]
        work.mkdir(parents=True, exist_ok=True)
        pdf = work / f"document_{item['size']}.pdf"
        with jobs.PDF_LOCK:
            convert.to_pdf(path, pdf, item["size"])
            pages = analyze.page_count(pdf)
            coverage = analyze.color_coverage(pdf)
            colors = analyze.color_pages(pdf)
        return {"pdf": pdf, "paper": item["size"], "pages": pages, "coverage": coverage, "page_colors": colors,
                "src": path}


# ------------------------------------------------------------------ settings and jobs

def settings_for(rules, item, prepared):
    """The print settings of an item, from the order (staff overrides in item["print"] win)."""
    if item["kind"] == "product":
        p = walkin_pricing.product_of(item)
        paper = cat.choice(p, "paper", item["picks"])
        both = cat.choice(p, "sides", item["picks"]) == "Both sides"
        colour = "bw" if cat.choice(p, "colour", item["picks"]) == "Black and white" else "color"  # Labels can be B&W
        s = {"color": colour, "printer": "auto", "sides": "long" if both else "single",
             "paper": (prepared or {}).get("paper") or "A4", "per_side": "1",
             "paper_type": paper_type_for(rules, paper, product=True), "tray": TRAY,
             "copies": str(item.get("sheets") or 1), "rotate": "0", "product": True, "gsm": routing.paper_gsm(paper)}
    else:
        s = {"color": {"bw": "bw", "color": "color", "mixed": "auto"}[item["color"]], "printer": "auto",
             "sides": "long" if item["sides"] == "double" else "single", "paper": item["size"],
             "per_side": str(item.get("per_side", 1)), "paper_type": paper_type_for(rules, item["paper"]),
             "tray": TRAY, "copies": str(item["copies"]), "rotate": "0"}
    s.update(item.get("print") or {})
    return s


def job_for(shared_jobs, rules, item, prepared, printer=None, busy=None):
    """The print job for an item (None when it can't be worked out), with the copier routed or picked."""
    if not prepared or "error" in prepared:
        return None
    s = settings_for(rules, item, prepared)
    if printer:
        s["printer"] = printer
    job = shared_jobs.job_for(item["folder"], s, prepared["pages"], prepared["coverage"], prepared["page_colors"],
                              9999 if item["kind"] == "product" else jobs.MAX_COPIES, busy=busy)
    if job is not None and item["kind"] == "product":
        job["actual_size"] = True  # the laid-out sheet exactly as it is
    return job


def cover_job(shared_jobs, printer, pages=1):
    """The cover sheet's job: B&W, one side, plain A4 (a very long item list can run onto a second page)."""
    s = {"color": "bw", "printer": printer, "sides": "single", "paper": "A4", "per_side": "1", "paper_type": PLAIN,
         "tray": TRAY, "copies": "1", "rotate": "0"}
    return shared_jobs.job_for(COVER, s, pages, 0.0, [False] * pages)


def log_info(order, item=None):
    if item is None:
        return {"source": "walk-in", "order": f"#{order['number']}", "product": COVER, "quantity": "",
                "paper_name": "", "file": f"#{order['number']} {COVER}"}
    if item["kind"] == "product":
        p = walkin_pricing.product_of(item)
        return {"source": "walk-in", "order": f"#{order['number']}", "product": p["name"], "quantity": item["qty"],
                "paper_name": cat.choice(p, "paper", item["picks"]), "file": f"#{order['number']} {item['folder']}"}
    return {"source": "walk-in", "order": f"#{order['number']}", "product": "Document", "quantity": "",
            "paper_name": item["paper"], "file": f"#{order['number']} {item['folder']}"}


# ------------------------------------------------------------------ the cover sheet

def paper_prices(rules=None):
    """rules.json walkin_paper_prices: money on walk-in paper (the cover sheet's total). false while testing
    (Tesla, 2026-11-17: "do not include any prices"); a missing setting counts as false."""
    if rules is None:
        try:
            rules = routing.load_rules()
        except Exception:
            rules = {}
    return rules.get("walkin_paper_prices") is True


PLAIN_PAPERS = ("Smooth white 80 gsm", "Normal 80 gsm")  # not listed under Extras
COPY_ORDER = (("A4", "bw"), ("A4", "color"), ("A3", "bw"), ("A3", "color"))
COPY_WORDS = {"bw": "B&W", "color": "colour"}
USE_ORDER = ("envelope", "lamination", "spiral", "staple", "cuts")  # after the papers; extras and services last


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def counter_lines(order, pl=None, rules=None):
    """The cover sheet's Counter for the whole order (2026-11-19_01, Tesla: "write how many a3/a4 color or black and
    white we printed, and the extras"): (copy lines, extra lines). Copies are printed sides, the counts the price is
    worked out from (walkin_pricing.needs), by A4 / A3 and B&W / colour; extras are the papers that aren't plain,
    envelopes, lamination, spiral, staple, cuts, product extras and services, each added up over the items. Never
    money. The counts don't need prices; an item that can't be counted at all says so. A product laid out by hand
    (Layout done) counts the sheets given there."""
    import walkin_prices
    pl = pl or walkin_prices.current()
    copies, papers, uses, extras, unknown = {}, {}, {}, {}, []
    for i, item in enumerate(order["items"], start=1):
        try:
            need = walkin_pricing.needs(pl, item, rules)
        except Exception:  # an item ORCA can't read (a very old order)
            need = None
        if need is None or (need.problems and not need.copies):
            unknown.append(f"Item {i}: see the order on screen")
            continue
        for key, n in need.copies.items():
            copies[key] = copies.get(key, 0) + n
        laid = item.get("sheets") if item.get("kind") == "product" else None
        for u in need.uses:
            n = u["count"]
            if u["kind"] == "paper":
                if laid:
                    n = int(laid)  # Layout done's sheet count (the cover sheet only, not the price)
                key = (u["name"], u["size"])
                papers[key] = papers.get(key, 0) + n
            elif u["kind"] in ("extra", "service"):
                if u["name"] not in extras:
                    extras[u["name"]] = None
                if n is not None:
                    extras[u["name"]] = (extras[u["name"]] or 0) + n
            else:
                uses.setdefault(u["kind"], {})
                uses[u["kind"]][u["name"]] = uses[u["kind"]].get(u["name"], 0) + (n or 0)
    copy_lines = [f"{size} {COPY_WORDS[colour]}: {copies[(size, colour)]}" for size, colour in COPY_ORDER
                  if copies.get((size, colour))] + unknown
    extra_lines = [f"{name}: {_plural(n, size + ' sheet')}" for (name, size), n in papers.items()
                   if name not in PLAIN_PAPERS and n]
    for kind in USE_ORDER:
        for name, n in uses.get(kind, {}).items():
            if not n:
                continue
            if kind == "envelope":
                extra_lines.append(f"{name} envelopes: {n}")
            elif kind == "lamination":
                extra_lines.append(f"{name}: {_plural(n, 'sheet')}")
            else:
                extra_lines.append(f"{name}: {n}")
    extra_lines += [f"{name}: {n}" if n else name for name, n in extras.items()]
    return copy_lines, extra_lines


def cover_pdf(order, path, when=None, rules=None):
    """A plain A4 page: the number large, customer, date, and the Counter (2026-11-19_01: copies by size and colour,
    then the extras; counter_lines); every line centred left to right, the block centred top to bottom (Tesla,
    2026-11-17). No prices on paper while rules.json walkin_paper_prices is false (2026-11-17_09); true brings the total
    line back. The Counter never carries money; the items' descriptions stay on screen only. A Counter too long for
    one page starts at the top margin and runs on, so nothing is cut off. Long lines wrap, each part centred."""
    import counter_pdf
    when = when or datetime.datetime.now()
    w = counter_pdf.Writer()
    c = order["customer"]
    lines = [(f"#{order['number']}", 72, True, 22)]  # (text, size, bold, space after)
    lines += [(text, 18, True, 8) for text in (c.get("name"), c.get("phone"), c.get("email")) if text]
    if len(lines) > 1:
        lines[-1] = lines[-1][:3] + (lines[-1][3] + 10,)  # the gap after the customer block
    else:
        lines[0] = lines[0][:3] + (lines[0][3] + 10,)
    if paper_prices(rules):
        due = walkin_orders.price_due(order)
        typed = order.get("changed_total") is not None and not order.get("rounding")  # test orders from before 17_07
        lines.append((f"Total: EUR {due:,.2f}" + ("  (changed price)" if typed else ""), 18, True, 8))  # rounded: the amount only
    else:
        lines[-1] = lines[-1][:3] + (lines[-1][3] + 8,)  # the gap the total line left after itself, kept
    lines.append((f"Printed {when.day} {when:%b %Y, %H:%M}   ·   placed {order['created'][:10]}", 11, False, 16))
    copy_lines, extra_lines = counter_lines(order)
    lines.append(("Counter", 13, True, 6))
    for text in copy_lines:
        lines += [(part, 11, False, 5) for part in _wrap(w, text, 11)]
    if extra_lines:
        lines[-1] = lines[-1][:3] + (lines[-1][3] + 10,)
        lines.append(("Extras", 13, True, 6))
        for text in extra_lines:
            lines += [(part, 11, False, 5) for part in _wrap(w, text, 11)]
    height = sum(size + gap for _, size, _, gap in lines) - lines[-1][3]
    room = counter_pdf.PAGE_H - 2 * counter_pdf.MARGIN - 20  # what Writer.room leaves free on a page
    if height <= room:
        # Centre the ink, not the line boxes: the first line's letters start below its box top (cap height),
        # the last line's end at its baseline plus descenders.
        first, last = lines[0], lines[-1]
        ink_top = first[1] - _ink(w, first[0], first[1], first[2])[1]  # below the block top
        ink_bottom = height + _ink(w, last[0], last[1], last[2])[3]  # the last baseline is `height` below the top
        w.y = counter_pdf.PAGE_H / 2 + (ink_top + ink_bottom) / 2
    for text, size, bold, gap in lines:
        w.room(size)
        left, _, right, _ = _ink(w, text, size, bold)
        w.text((counter_pdf.PAGE_W - (right - left)) / 2 - left, w.y - size, text, size, bold)  # ink centred
        w.y -= size + gap
    w.save(path)
    return path


def _ink(w, text, size, bold=False):
    """(left, height above the baseline, right, depth below it) of the letters' ink, in points. The font's own box
    gives the advance width, not where the ink is, so the first and last letters are drawn and measured; the width
    between them is the exact advance (pdfium places the letters the same way, without kerning)."""
    from PIL import Image, ImageDraw
    text = text.strip()
    if not text:
        return 0.0, 0.0, 0.0, 0.0
    from PIL import ImageFont
    import counter_pdf
    if bold not in _BIG:  # 2000 pt: widths as the PDF has them (at small sizes the font's widths are hinted)
        _BIG[bold] = ImageFont.truetype(str(counter_pdf.FONTS[bold]), 2000)
    font = _BIG[bold]
    pad, base = 600, 2600

    def glyph(ch):
        img = Image.new("L", (int(font.getlength(ch)) + 2 * pad, 3400), 0)
        ImageDraw.Draw(img).text((pad, base), ch, font=font, fill=255, anchor="ls")
        return img.getbbox()

    first, last = glyph(text[0]), glyph(text[-1])
    left = (first[0] - pad) if first else 0
    right = font.getlength(text) - (font.getlength(text[-1]) - ((last[2] - pad) if last else font.getlength(text[-1])))
    _, top, _, bottom = font.getbbox(text, anchor="ls")
    k = size / 2000
    return left * k, -top * k, right * k, bottom * k


_BIG = {}


def _wrap(w, text, size, bold=False):
    """Split a line into parts that fit the page width (at spaces where possible)."""
    import counter_pdf
    room = counter_pdf.WIDTH
    out, line = [], ""
    for word in text.split(" "):
        candidate = f"{line} {word}".strip()
        if w.width(candidate, size, bold) <= room:
            line = candidate
            continue
        if line:
            out.append(line)
        while w.width(word, size, bold) > room:  # one word longer than the page: cut it
            cut = len(word)
            while cut > 1 and w.width(word[:cut], size, bold) > room:
                cut -= 1
            out.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        out.append(line)
    return out or [""]
