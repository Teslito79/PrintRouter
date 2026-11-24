"""The copier's own counter page (2026-11-18_01): Web Image Monitor's getUnificationCounter.cgi, plain HTML, no
login (guest), read with one HTTP GET. Read-only, like the SNMP readings in toners.py.

Two layouts are known (Tesla's check, 2026-11-18):
- IM C4510 and IM C3000: sections Total, Copier, Printer, Fax, ... Each section has the rows Full Color, Black &
  White, Single Color and Two-color, each with "Total : n", then Simplex "A3/DLT : n" "Others : n" ("Banner : n")
  and Duplex "A3/DLT : n" "Others : n" ("Banner : n"). Simplex / Duplex count sheets; the Total columns count
  pages (A3 counts 2). The Total section has one more line, "Total Counter : n". The IM C3000 has no Banner.
- MP C3004: a top line "Total : n"; Copier and Printer with the four rows as totals only ("Black & White 318002");
  "Other Function(s)": A3/DLT, Duplex, Banner for the whole machine.

parse() matches the labels and allows any spaces, line breaks and table cells between them. The real IM C4510 page
(saved at work, 2026-11-24) has "Simplex" and "Duplex" only once, as column headings; each row then gives A3/DLT /
Others / Banner twice with no side word: the first group is simplex, the second duplex (a Simplex / Duplex word next
to the numbers wins; a new row starts again).
"""
import html as htmllib
import re
import urllib.request

PATH = "/web/guest/en/websys/status/getUnificationCounter.cgi"
TIMEOUT = 5

SECTIONS = ("Other Function(s)", "Send/TX Total", "Fax Transmission", "Scanner Send", "Coverage", "Copier",
            "Printer", "Fax", "Total")
ROWS = {"full color": "color", "full colour": "color", "black & white": "bw", "black and white": "bw",
        "single color": "single", "single colour": "single", "two-color": "two", "two-colour": "two"}
NUM = r"(\d[\d,]*)"
TOKEN = re.compile(
    r"(?P<counter>Total\s+Counter)\s*:?\s*" + NUM
    + r"|(?P<section>Other\s+Function\(s\)|Send/TX\s+Total|Fax\s+Transmission|Scanner\s+Send|Coverage|Copier|Printer"
      r"|Fax(?!\s+Transmission))(?!\s*:?\s*\d)"
    + r"|(?P<row>Full\s+Colou?r|Black\s*(?:&|and)\s*White|Single\s+Colou?r|Two-colou?r)(?:\s*:?\s*" + NUM + r")?"
    + r"|(?P<side>Simplex|Duplex)(?![\w/])(?:\s*:?\s*" + NUM + r")?"
    + r"|(?P<key>A3/DLT|Others|Banner|Total)\s*:?\s*" + NUM
    + r"|(?P<heading>Total)\b")


class PageError(Exception):
    """The page couldn't be read, or isn't a counter page we know."""


def url(address):
    """The page on the copier's web server: the host only (a ":port" typed for SNMP isn't the web server's)."""
    host = address.rsplit(":", 1)[0] if address.count(":") == 1 else address
    return f"http://{host}{PATH}"


def fetch(address, timeout=None):
    """The page's HTML (plain HTTP GET, no login). Raises PageError."""
    if not address:
        raise PageError("no address")
    try:
        with urllib.request.urlopen(urllib.request.Request(url(address), headers={"User-Agent": "ORCA"}),
                                    timeout=timeout or TIMEOUT) as r:
            raw = r.read(2_000_000)
            charset = r.headers.get_content_charset() or "utf-8"
    except (OSError, ValueError) as e:
        raise PageError(f"the counter page didn't answer ({type(e).__name__})") from None
    return raw.decode(charset, errors="replace")


def text_of(page):
    """The page as plain text: tags, scripts and styles gone, entities decoded, every run of space one space."""
    page = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    page = re.sub(r"(?s)<[^>]*>", " ", page)
    page = htmllib.unescape(page).replace("\xa0", " ")
    return re.sub(r"\s+", " ", page)


def _n(text):
    return int(text.replace(",", ""))


def parse(page):
    """{"total": the Total Counter (or the MP C3004's top "Total") or None,
        "sections": {section: {row: {"total": n, "simplex": {"A3/DLT", "Others", "Banner"}, "duplex": {...}}}},
        "other": {"A3/DLT", "Duplex", "Banner"} (Other Function(s), the MP C3004)}."""
    out = {"total": None, "sections": {}, "other": {}}
    section = row = side = None
    for m in TOKEN.finditer(text_of(page)):

        groups = m.groupdict()
        if groups["counter"]:
            out["total"] = _n(m.group(2))
        elif groups["section"]:
            section, row, side = re.sub(r"\s+", " ", groups["section"]), None, None
        elif groups["heading"]:
            # a bare "Total": the Total section is the page's first, so only before any row was read (a column
            # heading "Total" inside a later table changes nothing)
            if not out["sections"]:
                section, row, side = "Total", None, None
        elif groups["row"]:
            name = ROWS.get(re.sub(r"\s+", " ", groups["row"]).lower().replace("black&white", "black & white")
                            .replace("black &white", "black & white").replace("black& white", "black & white"))
            row, side = name, None
            if section and name:
                entry = out["sections"].setdefault(section, {}).setdefault(name, {})
                value = m.group(m.re.groupindex["row"] + 1)
                if value:
                    entry["total"] = _n(value)
        elif groups["side"]:
            side = groups["side"].lower()
            value = m.group(m.re.groupindex["side"] + 1)
            if value and section == "Other Function(s)":
                out["other"][groups["side"]] = _n(value)
        elif groups["key"]:
            key, value = groups["key"], _n(m.group(m.re.groupindex["key"] + 1))
            if section == "Other Function(s)":
                out["other"][key] = value
            elif section and row:
                entry = out["sections"].setdefault(section, {}).setdefault(row, {})
                if key == "Total":
                    entry["total"] = value
                elif side:
                    entry.setdefault(side, {})[key] = value
                else:
                    # the real IM C4510 page (2026-11-24_03): "Simplex Duplex" only as column headings, then each
                    # row gives its A3/DLT / Others / Banner twice: the first group simplex, the second duplex
                    first = entry.setdefault("simplex", {})
                    (first if key not in first else entry.setdefault("duplex", {}))[key] = value
            elif key == "Total" and out["total"] is None and not out["sections"]:
                out["total"] = value  # the MP C3004's top line
    return out


SHEET_KEYS = {"s_a3": ("simplex", "A3/DLT"), "s_other": ("simplex", "Others"), "d_a3": ("duplex", "A3/DLT"),
              "d_other": ("duplex", "Others")}


def sheet_split(parsed, section="Copier"):
    """{"color": {"s_a3", "s_other", "d_a3", "d_other"}, "bw": {...}} (sheets) from a section, or None when it
    hasn't the split. Single Color and Two-color go to colour."""
    rows = parsed["sections"].get(section) or {}
    if "color" not in rows or "bw" not in rows:
        return None
    out = {"color": dict.fromkeys(SHEET_KEYS, 0), "bw": dict.fromkeys(SHEET_KEYS, 0)}
    for row, entry in rows.items():
        target = "bw" if row == "bw" else "color"
        for key, (side, name) in SHEET_KEYS.items():
            value = (entry.get(side) or {}).get(name)
            if value is None:
                if row in ("color", "bw"):
                    return None  # the two rows that matter must have every column
                continue
            out[target][key] += value
    return out


def page_totals(parsed, sections=("Copier",)):
    """{"color": pages, "bw": pages} from the rows' totals of these sections, or None when a row is missing."""
    out = {"color": 0, "bw": 0}
    for section in sections:
        rows = parsed["sections"].get(section) or {}
        if rows.get("color", {}).get("total") is None or rows.get("bw", {}).get("total") is None:
            return None
        for row, entry in rows.items():
            if entry.get("total") is not None:
                out["bw" if row == "bw" else "color"] += entry["total"]
    return out


def toner_counts(parsed):
    """(black, colour) pages for the Data screen, or None: the Total section's sheets, duplex x 2 (IM C4510 and
    IM C3000); else Copier + Printer totals (MP C3004)."""
    split = sheet_split(parsed, "Total")
    if split:
        return tuple(s["s_a3"] + s["s_other"] + 2 * (s["d_a3"] + s["d_other"]) for s in (split["bw"], split["color"]))
    totals = page_totals(parsed, ("Copier", "Printer"))
    if totals:
        return totals["bw"], totals["color"]
    return None


def read_counts(address, timeout=None):
    """(black, colour, parsed) from a copier's page. Raises PageError."""
    parsed = parse(fetch(address, timeout))
    counts = toner_counts(parsed)
    if counts is None:
        raise PageError("the page has no B&W / colour counts we know")
    return counts[0], counts[1], parsed


def describe(parsed):
    """Lines for copier_check.txt: what the page gave."""
    lines = [f"  Total Counter: {parsed['total'] if parsed['total'] is not None else 'not given'}"]
    for section, rows in parsed["sections"].items():
        for row, entry in rows.items():
            parts = [f"total {entry['total']}"] if entry.get("total") is not None else []
            for side in ("simplex", "duplex"):
                if entry.get(side):
                    parts.append(side + " " + ", ".join(f"{k} {v}" for k, v in entry[side].items()))
            lines.append(f"  {section} / {row}: " + ("; ".join(parts) or "nothing"))
    if parsed["other"]:
        lines.append("  Other Function(s): " + ", ".join(f"{k} {v}" for k, v in parsed["other"].items()))
    return lines
