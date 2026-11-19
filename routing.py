"""Load the settings files and pick a printer for a job from rules.json."""
import json
import re
import sys
from pathlib import Path


def app_dir():
    """Folder holding rules.json and prices.json: next to the .exe when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_json(name):
    return json.loads((app_dir() / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ settings.json (2026-11-18_02)
# rules.json is the shipped default (in git, never written by ORCA). The Settings page saves only what was changed on
# this PC into settings.json next to it (local, gitignored), laid over rules.json by load_rules(), the one loader.
SETTINGS = "settings.json"
LOCAL_KEYS = ("printers", "rules", "fallback_printer", "receipt_printer", "walkin_paper_prices", "copy_counter")
COPY_COUNTER_KEYS = {"a3_counts_as": "copy_counter_a3_counts_as", "poll_seconds": "copy_counter_poll_seconds"}


def load_local():
    """settings.json as saved, or {} (none yet, or unreadable)."""
    try:
        data = json.loads((app_dir() / SETTINGS).read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in LOCAL_KEYS} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def merge(base, local):
    """rules.json (base) with settings.json (local) laid over it: a new dict, base untouched."""
    import copy
    rules = copy.deepcopy(base)
    for key, value in local.items():
        if key == "copy_counter":
            for short, long in COPY_COUNTER_KEYS.items():
                if short in (value or {}):
                    rules[long] = value[short]
        elif key in LOCAL_KEYS:
            rules[key] = copy.deepcopy(value)
    return rules


def shipped_rules():
    """rules.json alone: the shipped default (Settings compares with it; nothing else reads it)."""
    return load_json("rules.json")


def load_rules():
    """The rules in force: rules.json with settings.json laid over it. Every part of ORCA loads them through here."""
    return merge(shipped_rules(), load_local())


def local_diff(shipped, wanted):
    """What settings.json must hold so that merge(shipped, it) gives `wanted` for the local keys: only what differs."""
    out = {}
    for key in LOCAL_KEYS:
        if key == "copy_counter":
            cc = {short: wanted.get(long) for short, long in COPY_COUNTER_KEYS.items()
                  if long in wanted and wanted.get(long) != shipped.get(long)}
            if cc:
                out[key] = cc
        elif key in wanted and wanted[key] != shipped.get(key):
            out[key] = wanted[key]
    return out


def save_local(data):
    """Write settings.json safely (a temp file, then rename). An empty dict removes it."""
    path = app_dir() / SETTINGS
    if not data:
        reset_local()
        return
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    import os
    os.replace(tmp, path)


def reset_local():
    """Back to the shipped settings: settings.json deleted."""
    try:
        (app_dir() / SETTINGS).unlink()
    except FileNotFoundError:
        pass


def installed_printers():
    """The names of the printers installed on this PC (read only), or None when Windows can't be asked."""
    try:
        import win32print
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return [p[2] for p in win32print.EnumPrinters(flags, None, 1)]
    except Exception:
        return None


def missing_printers(rules, installed=None):
    """Printer ids whose Windows printer isn't installed on this PC (empty when that can't be known)."""
    installed = installed_printers() if installed is None else installed
    if installed is None:
        return set()
    return {pid for pid, p in rules["printers"].items() if p.get("queue") not in installed}


# ------------------------------------------------------------------ "Which printer does what" (three rows)
ROWS = (("bw", "Black and white"), ("doc", "Colour documents on plain paper"), ("colour", "Everything else in colour"))
ROW_REASONS = {"bw": "Black & white", "doc": "Color document", "colour": "Color"}


def row_conditions(rules):
    return {"bw": {"color": False},
            "doc": {"color": True, "content": "document", "product": False,
                    "paper_type": list(rules.get("plain_paper_types", {}).get("types", []))},
            "colour": {"color": True}}


def rules_from_rows(rules, rows):
    """The routing rules (today's format) from {"bw" / "doc" / "colour": (printer, if busy or None)}."""
    conditions = row_conditions(rules)
    out = []
    for key, _ in ROWS:
        printer, if_busy = rows[key]
        rule = {"if": conditions[key], "printer": printer}
        if if_busy:
            rule["if_busy"] = if_busy
        rule["reason"] = ROW_REASONS[key]
        out.append(rule)
    return out


def rows_of(rules):
    """The three rows the rules in force are, or None when they can't be shown that way (custom routing)."""
    found = rules.get("rules") or []
    if len(found) != 3:
        return None
    rows = {key: (rule.get("printer"), rule.get("if_busy")) for (key, _), rule in zip(ROWS, found)}
    return rows if rules_from_rows(rules, rows) == found else None


# ------------------------------------------------------------------ what a printer can take
def unable(rules, printer_id, job):
    """Why this printer can't take the job (colour on a black-and-white-only printer, A3 on an A4-only printer), or
    None. Printers without these settings (rules.json today) take everything, as before."""
    p = rules["printers"].get(printer_id, {})
    label = p.get("label", printer_id)
    if job.get("color") and p.get("color") == "bw":
        return f"{label} prints black and white only"
    if job.get("paper") == "A3" and p.get("max_paper") == "A4":
        return f"{label} takes A4 at most"
    return None


def resolve_content(rules, content, coverage_percent):
    """Turn the content choice ('auto', 'document', 'pictures') into 'document' or 'pictures'."""
    if content != "auto":
        return content
    if coverage_percent is None:
        return "document"
    return "pictures" if coverage_percent >= rules["picture_threshold_percent"] else "document"


def _matches(condition, job):
    for key, want in condition.items():
        if isinstance(want, list):
            if job.get(key) not in want:
                return False
        elif job.get(key) != want:
            return False
    return True


BYPASS = "Bypass Tray"


def plain(rules, paper_type):
    """True for plain paper (rules.json plain_paper_types); every other paper prints from the Bypass Tray."""
    return paper_type in rules.get("plain_paper_types", {}).get("types", [])


def paper_gsm(name):
    """The weight in a website paper name ("Silk 250 gsm" -> 250), or None."""
    m = re.search(r"(\d+)\s*gsm\b", str(name or ""), re.IGNORECASE)
    return int(m.group(1)) if m else None


def hand_turned(rules, paper_type, gsm=None):
    """True when both sides on this paper are turned by hand (rules.json hand_fed_papers): not plain
    paper and min_gsm or more; when only the driver paper type is known, one of its paper_types."""
    if plain(rules, paper_type):
        return False
    hf = rules.get("hand_fed_papers", {})
    if gsm is not None and "min_gsm" in hf:
        return gsm >= hf["min_gsm"]
    return paper_type in hf.get("paper_types", [])


def max_gsm(rules, printer_id):
    """The heaviest paper this copier takes (rules.json printers max_gsm), or None for no limit."""
    return rules["printers"].get(printer_id, {}).get("max_gsm")


def choose_printer(rules, job, busy=(), missing=()):
    """Return (printer_id, reason) for a job.

    job keys: color, content ('document'/'pictures'), duplex, paper, paper_type, tray, product, gsm.
    busy: copiers ORCA is using right now; a rule's if_busy copier is taken instead of a busy one.
    A paper heavier than the chosen copier's max_gsm goes to the first copier that takes it.
    missing: printers not installed on this PC (Settings: "Not found"); skipped like a busy one, and so are printers
    that can't take the job (unable: B&W only, A4 only), when another printer can (2026-11-18_02).
    """
    printer_id, reason = _choose(rules, job, busy, missing)
    gsm = job.get("gsm")

    def fits(pid):
        limit = max_gsm(rules, pid)
        return not unable(rules, pid, job) and pid not in missing and not (gsm and limit and gsm > limit)

    if (unable(rules, printer_id, job) or printer_id in missing) and not fits(printer_id):
        others = [pid for pid in rules["printers"] if pid != printer_id and fits(pid)]
        others.sort(key=lambda pid: pid in busy)  # a free one first
        if others:
            why = unable(rules, printer_id, job) or (
                f"{rules['printers'].get(printer_id, {}).get('label', printer_id)} isn't installed on this PC")
            return others[0], f"{reason}; {why}"
    return printer_id, reason


def _choose(rules, job, busy=(), missing=()):
    """choose_printer before the 2026-11-18_02 checks: the rules, if_busy and the heaviest paper."""
    for rule in rules["rules"]:
        if _matches(rule["if"], job):
            printer_id, reason = rule["printer"], rule.get("reason", "")
            if printer_id in busy and rule.get("if_busy"):
                label = rules["printers"].get(printer_id, {}).get("label", printer_id)
                printer_id, reason = rule["if_busy"], f"{reason}; {label} is busy"
            break
    else:
        printer_id, reason = rules["fallback_printer"], "No rule matched (fallback)"
    gsm, limit = job.get("gsm"), max_gsm(rules, printer_id)
    if gsm and limit and gsm > limit:
        heavy = [pid for pid in rules["printers"] if (max_gsm(rules, pid) or 0) >= gsm and not unable(rules, pid, job)]
        heavy = [pid for pid in heavy if pid not in missing] or heavy  # an installed one first, if any
        if heavy:
            label = rules["printers"][printer_id].get("label", printer_id)
            return heavy[0], f"{gsm} gsm ({label} takes up to {limit} gsm)"
    return printer_id, reason


def check_rules(rules):
    """Return a list of problems in rules.json, empty when it looks fine."""
    problems = []
    printers = rules.get("printers", {})
    known = {"paper_type": rules.get("paper_types", []), "tray": rules.get("trays", [])}
    for i, rule in enumerate(rules.get("rules", []), start=1):
        if rule.get("printer") not in printers:
            problems.append(f"Rule {i}: unknown printer '{rule.get('printer')}'")
        for key, values in known.items():
            want = rule.get("if", {}).get(key)
            for value in want if isinstance(want, list) else [want] if want else []:
                if value not in values:
                    problems.append(f"Rule {i}: '{value}' is not in the {key}s list")
        if rule.get("if_busy") and rule["if_busy"] not in printers:
            problems.append(f"Rule {i}: unknown if_busy printer '{rule['if_busy']}'")
    for pid, p in printers.items():
        if "max_gsm" in p and not (isinstance(p["max_gsm"], int) and p["max_gsm"] > 0):
            problems.append(f"Printer {pid}: max_gsm must be a whole number")
    for value in rules.get("plain_paper_types", {}).get("types", []) +rules.get("hand_fed_papers", {}).get("paper_types", []):
        if value not in known["paper_type"]:
            problems.append(f"'{value}' is not in the paper_types list")
    if rules.get("fallback_printer") not in printers:
        problems.append(f"Unknown fallback printer '{rules.get('fallback_printer')}'")
    d = rules.get("defaults", {})
    if d.get("paper_type") not in known["paper_type"]:
        problems.append(f"Default paper type '{d.get('paper_type')}' is not in the paper_types list")
    if d.get("tray") not in known["tray"]:
        problems.append(f"Default tray '{d.get('tray')}' is not in the trays list")
    return problems
