"""What a product item folder gets, shared by PrintHub (website) and Walk-in orders (moved here from printhub.py,
2026-11-17; PrintHub behaves exactly as before):
- choose_template: the CorelDRAW template for the item's product and cut size;
- pieces_entry / pieces_line: pieces per sheet from rules.json;
- tray_lines: the Bypass Tray and hand-turned lines;
- write_once: put Options.txt or the template copy into the folder, never over an existing file.
`doc` is an orders.Document (Walk-in builds one for its product items, see walkin_orders.product_doc).
"""
import math
import os
import shutil

import orders
import routing


def choose_template(doc, templates):
    """(template path or None, "CorelDRAW template: ..." line) for a product item. First match wins:
    <product id>.cdr, then <W>x<H>.cdr from cut_mm in whole mm, then <H>x<W>.cdr, then blank.cdr.
    File names compare without regard to upper/lower case."""
    try:
        found = {p.name.lower(): p for p in templates.iterdir() if p.is_file()}
    except OSError:
        found = {}
    product = f"{doc.job.get('product')}.cdr"
    if orders._plain_name(product) and product.lower() in found:
        return found[product.lower()], f"CorelDRAW template: {found[product.lower()].name}"
    cut = orders._size_mm(doc.job.get("cut_mm"))
    if cut is not None:
        w, h = (math.floor(v + 0.5) for v in cut)
        for name in (f"{w}x{h}.cdr", f"{h}x{w}.cdr"):
            if name in found:
                return found[name], f"CorelDRAW template: {found[name].name}"
    why = f"no template for {w} x {h} mm" if cut is not None else "no cut size"
    blank = found.get("blank.cdr")
    return blank, f"CorelDRAW template: {blank.name if blank else 'blank.cdr (missing!)'} ({why})"


def pieces_entry(doc, rules):
    """(size text "85 x 55", {"A4": 8, "A3": 18}) from rules.json pieces_per_sheet for a product
    item's cut_mm in whole mm, WxH first, then HxW (as the templates); None when not in the table."""
    cut = orders._size_mm(doc.job.get("cut_mm"))
    if cut is None:
        return None
    table = rules.get("pieces_per_sheet") or {}
    w, h = (math.floor(v + 0.5) for v in cut)
    for a, b in ((w, h), (h, w)):
        entry = table.get(f"{a}x{b}")
        if isinstance(entry, dict):
            found = {k: v for k, v in entry.items() if k in ("A4", "A3") and orders._whole(v) and v > 0}
            if found:
                return f"{a} x {b}", found
    return None


def pieces_line(doc, rules):
    """'Pieces per sheet: 8 on A4, 18 on A3' for Options.txt, or None."""
    entry = pieces_entry(doc, rules)
    if entry is None:
        return None
    return "Pieces per sheet: " + ", ".join(f"{entry[1][k]} on {k}" for k in ("A4", "A3") if k in entry[1])


def tray_lines(doc, rules):
    """'Tray: Bypass Tray' for paper that isn't plain, and the hand-turned line, from what was ordered
    (Tesla, 2026-11-13). Empty for plain paper or an unknown paper."""
    if doc.product:
        paper_type = doc.default_paper_type(rules)
        hand = paper_type and doc.default_sides(rules) == orders.HAND
    else:
        paper_type = doc.job.get("paper_type")
        hand = doc.job.get("sides") in ("long", "short") and routing.hand_turned(rules, paper_type)
    if not paper_type or routing.plain(rules, paper_type):
        return []
    lines = [f"Tray: {orders.BYPASS} (the paper isn't plain paper)"]
    if hand:
        lines.append("Both sides, turned by hand: fronts first, turn the stack over, then Print backs")
    return lines


def write_once(dest, text=None, template=None):
    """Write `text` (Options.txt) or copy `template` to dest, unless dest exists already: staff may have written
    in Options.txt or laid out the CorelDRAW file. Through a temp file; an error leaves nothing behind."""
    if dest.exists():
        return False
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        if template is None:
            tmp.write_text(text, encoding="utf-8-sig")  # text mode: Windows line ends are added
        else:
            shutil.copyfile(template, tmp)
        os.replace(tmp, dest)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
