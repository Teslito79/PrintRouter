"""Test helper: a copy of Walk-in_Prices.xlsx with made-up prices typed into its yellow cells (zipfile + xml only).

fill(src, dst, values): values = {sheet name: {"B5": 0.3, "D12": "per piece", ...}}.
test_values(src): every yellow cell filled with the fixed test prices below (2026-11-17_08 layout).
cell(src, sheet, label, column_heading=None): the cell reference of a row by its label ("A4 colour", "Tier 2").
website_sheet(src, dst, extra=None): the test sheet (old name kept for the earlier tests).
"""
import re
import zipfile
from xml.sax.saxutils import escape

import walkin_prices as wp

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

COPIES = {"A4 black and white": [0.10, 0.08, 0.05], "A4 colour": [0.30, 0.25, 0.20],
          "A3 black and white": [0.20, 0.16, 0.10], "A3 colour": [0.60, 0.50, 0.40]}
PAPER_80 = (0.02, 0.04)  # Smooth white 80 gsm A4, A3
PAPER_OTHER = (0.20, 0.40)
LABEL_SHEET = 0.50
ENVELOPE = 0.15
CUT = 0.10
STACKS = [500, 300, 200, 100]  # up to 100, 101-170, 171-250, 251-350 gsm
LAMINATION = (1.00, 2.00)
SPIRAL = [1.50, 2.00, 2.50]
STAPLE = 0.05
PRODUCT_EXTRA = (0.50, "per piece")
SERVICES = {"Stapling": (0.20, "per piece"), "Folding": (0.05, "per sheet"), "Filing": (1.00, "once per item")}
TIER2, TIER3 = 200, 1000


def _sheet_files(z):
    import xml.etree.ElementTree as ET
    REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet"):
        t = rels[sheet.get(REL)].lstrip("/")
        out[sheet.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return out


def _set(xml, ref, value):
    if value is None:
        pat = re.compile(rf'<c r="{ref}"((?: s="\d+")?)(?: t="\w+")?\s*(?:/>|>.*?</c>)', re.S)
        return pat.sub(lambda m: f'<c r="{ref}"{m.group(1)}/>', xml, count=1)
    if isinstance(value, (int, float)):
        inner, t = f"<v>{value}</v>", ""
    else:
        inner, t = f"<is><t>{escape(str(value))}</t></is>", ' t="inlineStr"'
    pat = re.compile(rf'<c r="{ref}"((?: s="\d+")?)(?: t="\w+")?\s*(?:/>|>.*?</c>)', re.S)
    if not pat.search(xml):
        raise KeyError(ref)
    return pat.sub(lambda m: f'<c r="{ref}"{m.group(1)}{t}>{inner}</c>', xml, count=1)


def fill(src, dst, values):
    names = set(wp.read_xlsx(src))
    merged = {}
    for name, cells in values.items():  # old sheet names land on "Prices" in the two-sheet file
        merged.setdefault(_real(names, name), {}).update(cells)
    values = merged
    with zipfile.ZipFile(src) as z:
        files = _sheet_files(z)
        data_out = {}
        for info in z.infolist():
            data = z.read(info.filename)
            for name, path in files.items():
                if path == info.filename and name in values:
                    xml = data.decode("utf-8")
                    for ref, v in values[name].items():
                        xml = _set(xml, ref, v)
                    data = xml.encode("utf-8")
            data_out[info.filename] = (info, data)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
        for info, data in data_out.values():
            out.writestr(info, data)


def _letter(i):
    return chr(65 + i)


OLD_TABLES = {"Copies": ("Copy",), "Paper": ("Paper", "Envelope"), "Cutting": ("Setting", "Paper weight"),
              "Extras": ("Finishing", "Product extra", "Service")}


def _real(sheets, name):
    """The sheet that holds an old sheet's tables: itself, or "Prices" in the two-sheet file (2026-11-18_04)."""
    return name if name in sheets or "Prices" not in sheets or name not in OLD_TABLES else "Prices"


def _tables(sheets):
    """{old sheet name: its rows}: the two-sheet file's "Prices" split back by the table headings."""
    if "Prices" not in sheets:
        return sheets
    out = {k: [] for k in OLD_TABLES}
    owner = None
    heads = {h.lower(): old for old, hs in OLD_TABLES.items() for h in hs}
    for r, vals in sheets["Prices"]:
        a = (vals[0] or "").strip().lower() if vals else ""
        b = (vals[1] or "").strip() if vals and len(vals) > 1 else ""
        if a in heads and b:
            owner = heads[a]
        elif not vals or not any(v is not None for v in vals):
            owner = None  # a table ends at its first empty row
        if owner:
            out[owner].append((r, vals))
    out["Settings"] = sheets.get("Settings", [])
    out["Prices"] = sheets["Prices"]
    return out


def rows_of(src, sheet):
    return _tables(wp.read_xlsx(src))[sheet]


def cell(src, sheet, label, heading=None, col=None):
    """The reference of the cell in the row labelled `label` (first column), under the column `heading`
    (the first heading row containing it) or in column index `col`."""
    rows = rows_of(src, sheet)
    if heading is not None:
        for _, vals in rows:
            low = [(v or "").strip().lower() for v in vals]
            if heading.lower() in low:
                col = low.index(heading.lower())
                break
    for r, vals in rows:
        if vals and (vals[0] or "").strip().lower() == label.lower():
            return f"{_letter(col)}{r}"
    raise KeyError(label)


def test_values(src):
    sheets = _tables(wp.read_xlsx(src))
    v = {k: {} for k in sheets}
    for r, vals in sheets["Copies"]:
        a = (vals[0] or "").strip() if vals else ""
        if a in COPIES:
            for k, price in enumerate(COPIES[a]):
                v["Copies"][f"{_letter(1 + k)}{r}"] = price
    part = "paper"
    for r, vals in sheets["Paper"]:
        a = (vals[0] or "").strip() if vals else ""
        if a == "Envelope":
            part = "envelope"
        elif a in ("Paper", "") or a.startswith("Price") or r < 4:
            continue
        elif part == "paper":
            if a == "Label sheet":
                v["Paper"][f"B{r}"] = LABEL_SHEET
            else:
                a4, a3 = PAPER_80 if a == "Smooth white 80 gsm" else PAPER_OTHER
                v["Paper"][f"B{r}"], v["Paper"][f"C{r}"] = a4, a3
        else:
            v["Paper"][f"B{r}"] = ENVELOPE
    stack = iter(STACKS)
    for r, vals in sheets["Cutting"]:
        a = (vals[0] or "").strip().lower() if vals else ""
        if a == "price per cut":
            v["Cutting"][f"B{r}"] = CUT
        elif "gsm" in a and not a.startswith("paper"):
            v["Cutting"][f"B{r}"] = next(stack)
    section = None
    spiral = iter(SPIRAL)
    for r, vals in sheets["Extras"]:
        a = (vals[0] or "").strip() if vals else ""
        if a in ("Finishing", "Product extra", "Service"):
            section = a
            continue
        if not a or section is None:
            continue
        if section == "Finishing":
            low = a.lower()
            v["Extras"][f"C{r}"] = (LAMINATION[0] if low == "lamination a4" else LAMINATION[1] if low == "lamination a3"
                                    else next(spiral) if low.startswith("spiral") else STAPLE)
        elif section == "Product extra":
            v["Extras"][f"C{r}"], v["Extras"][f"D{r}"] = PRODUCT_EXTRA
        elif a in SERVICES:
            v["Extras"][f"C{r}"], v["Extras"][f"D{r}"] = SERVICES[a]
    for r, vals in sheets["Settings"]:
        a = (vals[0] or "").strip().lower() if vals else ""
        if a == "tier 2 from":
            v["Settings"][f"C{r}"] = TIER2
        elif a == "tier 3 from":
            v["Settings"][f"C{r}"] = TIER3
    return v


def settings_rows(src):
    """{label lower: row number} on the Settings sheet."""
    return {(vals[0] or "").strip().lower(): r for r, vals in wp.read_xlsx(src)["Settings"] if vals and vals[0]}


def test_sheet(src, dst, extra=None):
    values = test_values(src)
    for sheet, cells in (extra or {}).items():
        values.setdefault(sheet, {}).update(cells)
    fill(src, dst, values)
    return dst


website_sheet = test_sheet
