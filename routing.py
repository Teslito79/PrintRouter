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


def choose_printer(rules, job, busy=()):
    """Return (printer_id, reason) for a job.

    job keys: color, content ('document'/'pictures'), duplex, paper, paper_type, tray, product, gsm.
    busy: copiers PrintRouter is using right now; a rule's if_busy copier is taken instead of a busy one.
    A paper heavier than the chosen copier's max_gsm goes to the first copier that takes it.
    """
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
        for pid in rules["printers"]:
            if (max_gsm(rules, pid) or 0) >= gsm:
                label = rules["printers"][printer_id].get("label", printer_id)
                return pid, f"{gsm} gsm ({label} takes up to {limit} gsm)"
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
