"""Paper sizes, sheet counts, and A5 printed two-up on A4 for cutting."""
import math

import pypdfium2 as pdfium

# Width x height in millimetres, portrait.
PAPER_MM = {"A4": (210, 297), "A3": (297, 420), "A5": (148, 210)}
MM = 72 / 25.4  # PDF points per millimetre


PER_SIDE = (1, 2, 4, 6, 8, 9, 16)  # pages per printed side


def printed_sides(pages, per_side):
    return math.ceil(pages / per_side)


def plan(pages, copies, duplex, paper, a5_layout, per_side=1):
    """Return (copies to send to the printer, total physical sheets)."""
    if paper != "A5":
        sides = printed_sides(pages, per_side)
        per_copy = math.ceil(sides / 2) if duplex else sides
        return copies, per_copy * copies
    if a5_layout == "same_page_twice":
        # Every sheet holds the same page twice, so one run yields two copies.
        runs = math.ceil(copies / 2)
        per_run = math.ceil(pages / 2) if duplex else pages
        return runs, per_run * runs
    per_copy = math.ceil(pages / 4) if duplex else math.ceil(pages / 2)
    return copies, per_copy * copies


def _sides(page_count, a5_layout, duplex):
    """List of (top page, bottom page) per printed side; None leaves a slot empty."""
    def page(i):
        return i if i < page_count else None

    if a5_layout == "same_page_twice":
        return [(i, i) for i in range(page_count)]
    if not duplex:
        return [(i, page(i + 1)) for i in range(0, page_count, 2)]
    # Front holds pages 1 and 3, back holds 2 and 4, so after cutting each
    # half-sheet has a page on the front and the following page on its back.
    sides = []
    for i in range(0, page_count, 4):
        sides.append((i, page(i + 2)))
        if page(i + 1) is not None:
            sides.append((i + 1, page(i + 3)))
    return sides


def _place(dest_page, src, index, dest, slot, clockwise):
    """Rotate a source page by `clockwise` degrees and fit it centred into slot (x, y, w, h)."""
    obj = src.page_as_xobject(index, dest).as_pageobject()
    angle = (clockwise + src[index].get_rotation()) % 360
    l, b, r, t = src[index].get_mediabox()
    m = pdfium.PdfMatrix().rotate(angle)
    x0, y0, x1, y1 = m.on_rect(l, b, r, t)
    sx, sy, sw, sh = slot
    s = min(sw / (x1 - x0), sh / (y1 - y0))
    m = m.scale(s, s)
    x0, y0, x1, y1 = m.on_rect(l, b, r, t)
    m = m.translate(sx + (sw - (x1 - x0)) / 2 - x0, sy + (sh - (y1 - y0)) / 2 - y0)
    obj.transform(m)
    dest_page.insert_obj(obj)


def a5_on_a4(src_pdf, out_pdf, a5_layout, duplex, flip="long"):
    """Put A5 pages two to a portrait A4 sheet (top and bottom half), turned sideways.

    flip is how each cut A5 piece is turned over: on its long edge (like a book
    page; backs are turned the other way) or its short edge. Print the result
    with long-edge duplex.
    """
    src = pdfium.PdfDocument(str(src_pdf))
    dest = pdfium.PdfDocument.new()
    w, h = 210 * MM, 297 * MM
    slots = [(0, h / 2, w, h / 2), (0, 0, w, h / 2)]  # top half, bottom half
    for n, side in enumerate(_sides(len(src), a5_layout, duplex)):
        page = dest.new_page(w, h)
        clockwise = 270 if duplex and flip == "long" and n % 2 == 1 else 90
        for slot, index in zip(slots, side):
            if index is not None:
                _place(page, src, index, dest, slot, clockwise)
        page.gen_content()
    dest.save(str(out_pdf))
    src.close()
    dest.close()


def _grid(per_side, page_w, page_h, sheet_w, sheet_h):
    """Best (columns, rows, landscape) for fitting pages of this shape, largest pages first."""
    best = None
    for landscape in (False, True):
        w, h = (sheet_h, sheet_w) if landscape else (sheet_w, sheet_h)
        for cols in range(1, per_side + 1):
            if per_side % cols:
                continue
            rows = per_side // cols
            scale = min(w / cols / page_w, h / rows / page_h)
            if best is None or scale > best[0] + 1e-9:
                best = (scale, cols, rows, landscape)
    return best[1:]


def n_up(src_pdf, out_pdf, per_side, paper):
    """Put several pages on each side of the sheet, in reading order (left to right, top to bottom).

    Output pages are always portrait; when the pages fit better on a sideways
    sheet, the whole side is turned clockwise, the same as landscape pages, so
    the printer's long/short edge flip applies to the paper as it is read.
    """
    src = pdfium.PdfDocument(str(src_pdf))
    dest = pdfium.PdfDocument.new()
    sw, sh = (v * MM for v in PAPER_MM[paper])
    cols, rows, landscape = _grid(per_side, *src[0].get_size(), sw, sh)
    rw, rh = (sh, sw) if landscape else (sw, sh)  # the side as it is read
    cw, ch = rw / cols, rh / rows
    for first in range(0, len(src), per_side):
        page = dest.new_page(sw, sh)
        for k, index in enumerate(range(first, min(first + per_side, len(src)))):
            x, y = (k % cols) * cw, rh - (k // cols + 1) * ch  # slot as read, PDF y goes up
            if landscape:  # turned clockwise
                slot, turn = (y, sh - x - cw, ch, cw), 90
            else:
                slot, turn = (x, y, cw, ch), 0
            _place(page, src, index, dest, slot, turn)
        page.gen_content()
    dest.save(str(out_pdf))
    src.close()
    dest.close()
