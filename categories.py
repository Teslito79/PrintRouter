"""Inventory categories filled by name (2026-11-19_11, Tesla: "for now i want to group inks and toners, art supplies,
school bags diaries and calendars and notebooks"; Shopify's inventory export has no category column).

Rules, kept in inventory.json ("category_rules") as an ordered list: {"name", "words", "not"}. A name matches a rule
when it contains any of its words and none of its not-words. Case is ignored; only whole words count ("ink" never
matches "pink"); an entry of several words matches that phrase ("pencil case"); an entry starting with "^" must be the
name's first word ("^ink" matches "Ink 560 Black CANON", not "Pen Blue Ink"). The first rule that matches wins.
Shopify items are matched on their product title (variants share it); ORCA items on their name.
"""
import re

DEFAULT_RULES = [
    {"name": "Inks and toners",
     "words": ["toner", "toners", "cartridge", "cartridges", "cardidge", "cardidges", "cadridge", "^ink"],
     "not": ["pen", "pens", "acrylic", "stamp", "endorsing"]},
    {"name": "Diaries and calendars",
     "words": ["diary", "diaries", "calendar", "calendars", "calender", "planner", "agenda"],
     "not": ["spasikla"]},
    {"name": "School bags",
     "words": ["backpack", "trolley", "schoolbag", "pencil case", "pencilcase"],
     "not": []},
    {"name": "Notebooks",
     "words": ["notebook", "notebooks", "tetradio"],
     "not": ["hp", "laptop", "gift"]},
    {"name": "Art supplies",
     "words": ["paint", "paints", "acrylic", "canvas", "drawing", "clay", "beads", "colouring", "coloring", "crayons",
               "watercolour", "watercolor", "brush", "brushes", "easel", "sketch", "tempera", "oil", "varnish",
               "vernish", "plasticine", "palette", "posca", "glitter glue", "glitter foam", "soft pastel", "gouache",
               "white spirit"],
     "not": ["pen", "pens", "highlighter", "highlighters", "sign holder", "stickers", "whiteboard", "tray", "scissor",
             "sharpener", "tape", "clip board", "map pins", "squeezy", "hair"]},
]

WORD = re.compile(r"\w+", re.UNICODE)


def tokens(text):
    return WORD.findall(str(text or "").lower())


def _has(words, entry):
    """Whole words; a phrase as a phrase; "^word" as the first word."""
    entry = str(entry or "").strip().lower()
    first = entry.startswith("^")
    want = tokens(entry[1:] if first else entry)
    if not want or not words:
        return False
    if first:
        return words[:len(want)] == want
    n = len(want)
    return any(words[i:i + n] == want for i in range(len(words) - n + 1))


def match(name, rules):
    """The category for a name: the first rule with any of its words and none of its not-words, or ""."""
    words = tokens(name)
    for rule in rules:
        if any(_has(words, w) for w in rule.get("words", [])) and not any(_has(words, w) for w in rule.get("not", [])):
            return rule["name"]
    return ""


def split_words(text):
    """"toner, toners, ^ink" -> ["toner", "toners", "^ink"] (one box, comma separated)."""
    return [w.strip() for w in str(text or "").split(",") if w.strip()]


def rules_of(inventory):
    """The rules in force: inventory.json's, or the starting rules when it has none yet."""
    import copy
    rules = inventory.data.get("category_rules")
    return copy.deepcopy(rules) if isinstance(rules, list) else copy.deepcopy(DEFAULT_RULES)


def title_of(item):
    return item.get("shopify_title") or item.get("name", "")


def ruled(item):
    """Items the rules fill: not ORCA's own linked items (paper, finishing), and whose category is empty or was filled
    by the rules (`category_auto`). Any other category counts as set by hand (`category_hand`, or typed before the
    rules existed) and is never changed."""
    if item.get("link") or item.get("category_hand"):
        return False
    return not item.get("category") or bool(item.get("category_auto"))


def apply(inventory, rules=None, renamed=None, save=True):
    """Fill the categories of every item the rules fill. renamed: {old name: new name} of renamed rules (items not set
    by hand follow the new name; here they simply match again). Returns how many changed."""
    rules = rules if rules is not None else rules_of(inventory)
    changed = 0
    for item in inventory.items:
        if not ruled(item):
            continue
        cat = match(title_of(item), rules)
        if (item.get("category") or "") != cat:
            item["category"] = cat
            changed += 1
        item["category_auto"] = bool(cat)
    inventory.data["category_rules"] = rules
    if save:
        inventory.save()
    return changed


def counts(inventory, rules):
    """{category: items} the rules would give now (items set by hand counted as they are), and the empty ones."""
    out, empty = {}, []
    for item in inventory.items:
        if item.get("link"):
            continue
        cat = item.get("category") or "" if not ruled(item) else match(title_of(item), rules)
        if cat:
            out.setdefault(cat, []).append(item)
        else:
            empty.append(item)
    return out, empty
