"""Price calculation and receipts for the XP-80C (80 mm thermal printer).

The receipt is drawn as an image with Pillow at the printer's resolution
(203 dpi, 72 mm printable width) and saved as a one-page PDF of exactly that
size, so it prints through SumatraPDF like every other job.
"""
import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DPI = 203
WIDTH_MM = 72
WIDTH_PX = round(WIDTH_MM / 25.4 * DPI)  # 576
MARGIN_PX = 8
FONT_DIR = Path(r"C:\Windows\Fonts")
# Not mentioned on compact receipt lines when these are used.
DEFAULT_PAPER_TYPE = "Plain & Recycled"
DEFAULT_TRAY = "Auto Tray Select"
SIDES = {"single": "Single", "long": "Double", "short": "Double short edge"}


def short_paper_type(name):
    """'Thick 4(257 to 300 g/m2)' -> 'Thick 4'."""
    return name.split("(")[0].strip()


def calculate_price(prices, job):
    """Return a list of (label, amount) lines; the total is their sum.

    job keys: pages, copies, color, paper, paper_type, sheets (physical sheets used),
    per_side (pages per printed side; then each printed side is charged as one page),
    color_units (mixed color: how many of those charged pages per copy are in color).
    """
    units = -(-job["pages"] // job.get("per_side", 1))
    color_units = job.get("color_units", units if job["color"] else 0)
    lines = []
    for mode, count in (("bw", units - color_units), ("color", color_units)):
        if count:
            rate = prices["per_page"][mode][job["paper"]]
            printed = count * job["copies"]
            lines.append((f"{printed} x {mode.upper()} {job['paper']} @ {fmt(prices, rate)}", rate * printed))
    surcharge = prices["paper_type_surcharge_per_sheet"].get(job["paper_type"], 0)
    if surcharge:
        sheets = job["sheets"]
        lines.append((f"{sheets} sheets {short_paper_type(job['paper_type'])} @ {fmt(prices, surcharge)}",
                      surcharge * sheets))
    return lines


def total_price(prices, job):
    return sum(amount for _, amount in calculate_price(prices, job))


def fmt(prices, amount):
    text = f"{amount:.2f}".replace(".", prices.get("decimal_separator", "."))
    return f"{prices.get('currency_symbol', '€')} {text}"


def _font(size, bold=False):
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _fit(draw, text, font, max_px):
    """Shorten text with '...' until it fits max_px."""
    if draw.textlength(text, font=font) <= max_px:
        return text
    while text and draw.textlength(text + "...", font=font) > max_px:
        text = text[:-1]
    return text + "..."


def color_text(job):
    if job.get("mixed"):
        return f"Mixed ({job['color_units']} color)"
    return "Color" if job["color"] else "B&W"


def describe(job):
    """One-line summary of a job's settings, e.g. '12 p x 3 · Color · Double · A4'."""
    parts = [f"{job['pages']} p x {job['copies']}", color_text(job),
             SIDES[job.get("flip", "long" if job["duplex"] else "single")], "A5 (2 on A4)" if job["paper"] == "A5" else job["paper"]]
    if job.get("per_side", 1) > 1:
        parts.append(f"{job['per_side']} per side")
    if job["paper_type"] != DEFAULT_PAPER_TYPE:
        parts.append(short_paper_type(job["paper_type"]))
    if job["tray"] != DEFAULT_TRAY:
        parts.append(job["tray"])
    return " · ".join(parts)


def make_receipt_pdf(path, prices, entries, when=None):
    """Draw the receipt and save it as a PDF. Returns the total price.

    entries: list of (job, printer label). One entry gets the detailed layout,
    several get one compact block per file.
    """
    when = when or datetime.datetime.now()
    priced = [(job, label, calculate_price(prices, job)) for job, label in entries]
    total = sum(amount for _, _, lines in priced for _, amount in lines)

    small, normal, bold, big = _font(22), _font(26), _font(26, True), _font(40, True)
    usable = WIDTH_PX - 2 * MARGIN_PX
    # Draw on a tall canvas, then crop to what was used.
    img = Image.new("L", (WIDTH_PX, 900 + 260 * len(entries)), 255)
    d = ImageDraw.Draw(img)
    y = 10

    def center(text, font):
        nonlocal y
        text = _fit(d, text, font, usable)
        d.text(((WIDTH_PX - d.textlength(text, font=font)) / 2, y), text, font=font, fill=0)
        y += font.size + 10

    def left_right(left, right, font):
        nonlocal y
        rw = d.textlength(right, font=font)
        d.text((MARGIN_PX, y), _fit(d, left, font, usable - rw - 12), font=font, fill=0)
        d.text((WIDTH_PX - MARGIN_PX - rw, y), right, font=font, fill=0)
        y += font.size + 10

    def rule():
        nonlocal y
        d.line((MARGIN_PX, y + 4, WIDTH_PX - MARGIN_PX, y + 4), fill=0, width=2)
        y += 16

    def left(text, font):
        nonlocal y
        d.text((MARGIN_PX, y), _fit(d, text, font, usable), font=font, fill=0)
        y += font.size + 10

    center(prices.get("shop_name", ""), big)
    center(when.strftime("%d/%m/%Y  %H:%M"), small)
    rule()
    if len(priced) == 1:
        job, printer_label, lines = priced[0]
        left_right("File:", "", normal)
        left(job["file_name"], small)
        left_right("Pages", str(job["pages"]), normal)
        left_right("Copies", str(job["copies"]), normal)
        left_right("Mode", color_text(job) if job["color"] else "Black & white", normal)
        left_right("Sides", SIDES[job.get("flip", "long" if job["duplex"] else "single")], normal)
        left_right("Paper", "A5 (2 on A4)" if job["paper"] == "A5" else job["paper"], normal)
        if job.get("per_side", 1) > 1:
            left_right("Pages per side", str(job["per_side"]), normal)
        left_right("Paper type", short_paper_type(job["paper_type"]), normal)
        if job["tray"] != DEFAULT_TRAY:
            left_right("Tray", job["tray"], normal)
        left_right("Printer", printer_label, small)
        rule()
        for label, amount in lines:
            left_right(label, fmt(prices, amount), small)
    else:
        left_right(f"{len(priced)} files", "", bold)
        y += 4
        for job, printer_label, lines in priced:
            left(job["file_name"], bold)
            left(describe(job), small)
            left_right(f"-> {printer_label}", fmt(prices, sum(a for _, a in lines)), small)
            y += 10
    rule()
    left_right("TOTAL", fmt(prices, total), big)
    y += 10
    center("Thank you!", normal)
    y += 30  # feed past the tear bar

    img = img.crop((0, 0, WIDTH_PX, y))
    img.save(path, "PDF", resolution=DPI)
    return total


if __name__ == "__main__":
    # Make a sample receipt, for testing the XP-80C.
    import json
    import sys

    here = Path(__file__).resolve().parent
    prices = json.loads((here / "prices.json").read_text(encoding="utf-8"))
    sample = {
        "file_name": "Sample document with a rather long file name.docx",
        "pages": 12, "copies": 3, "color": True, "duplex": True,
        "paper": "A4", "paper_type": "Thick 2(170 to 220 g/m2)", "tray": "Auto Tray Select", "sheets": 18,
    }
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else here / "test_results" / "sample_receipt.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    total = make_receipt_pdf(out, prices, [(sample, "IM C3000")])
    print(f"Receipt saved: {out}  total {fmt(prices, total)}")
