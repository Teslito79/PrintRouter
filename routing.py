"""Load the settings files and pick a printer for a job from rules.json."""
import json
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


def choose_printer(rules, job):
    """Return (printer_id, reason) for a job.

    job keys: color, content ('document'/'pictures'), duplex, paper, paper_type, tray.
    """
    for rule in rules["rules"]:
        if _matches(rule["if"], job):
            return rule["printer"], rule.get("reason", "")
    return rules["fallback_printer"], "No rule matched (fallback)"


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
    if rules.get("fallback_printer") not in printers:
        problems.append(f"Unknown fallback printer '{rules.get('fallback_printer')}'")
    d = rules.get("defaults", {})
    if d.get("paper_type") not in known["paper_type"]:
        problems.append(f"Default paper type '{d.get('paper_type')}' is not in the paper_types list")
    if d.get("tray") not in known["tray"]:
        problems.append(f"Default tray '{d.get('tray')}' is not in the trays list")
    return problems
