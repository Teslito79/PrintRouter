"""Walk-in Copy counter (2026-11-17_10): a customer's documents copied by hand at a copier, counted by ORCA.

Each copier has its own counter. Start counting reads the copier's counters (read()) and opens the first segment:
the copies made since then go to the paper (and, when the copier can't split them, the copy type and sides) chosen
now; changing any of them reads the counter and starts a new segment. Extras and services are added as counts.
Finish reads until the counter stands still, prices it from Walk-in_Prices.xlsx (copies x copy price in tiers per
size and colour of this receipt, sheets x paper price, extras; no loyalty) and offers Print receipt (XP-80C, no shop
name, money only while rules.json walkin_paper_prices is true) and Done (the sale in Walk-in\\sales_log.csv, one
print_log.csv line per segment, the copier let go). Cancel throws it all away. A running counter is saved in
Walk-in\\Open\\copy_counter.json and goes on after a restart.

read(copier) is the one place the counter is read (2026-11-18_01). It first reads the copier's own counter page
(counter_page.py, getUnificationCounter.cgi):
- "sheets" (IM C4510, IM C3000): the Copier section's sheets by colour, size and simplex / duplex. The copier splits
  the copies by itself: staff pick only the paper. The Copier section counts no print jobs, so the copier is NOT
  held (neither print queue is stopped).
- "pages" (MP C3004 mode): the Copier section's B&W / colour totals only. Colour is counted by itself, staff pick
  the size and sides, and the copier is held. "Other Function(s)" (A3, Duplex, Banner for the whole machine, units
  not known yet) is only recorded in each segment, never counted.
- "total" (the fallback, 10's way): the SNMP total counter; staff pick the copy type and sides, the copier is held
  (copier_queue.HELD). A count whose page stops answering falls back to it while counting, from the last reading.
"""
import csv
import datetime
import json
import math
import os
import threading

import copier_queue
import counter_page
import routing
import walkin_orders as wo
import walkin_prices
import walkin_pricing as P

FILE = "copy_counter.json"
TYPES = {"A4 B&W": ("A4", "bw"), "A4 colour": ("A4", "color"), "A3 B&W": ("A3", "bw"), "A3 colour": ("A3", "color")}
SIDES = {"single": "one side", "double": "both sides"}
FIRST_PAPER = "Smooth white 80 gsm"
STABLE_SECONDS = 3  # Finish: two reads this far apart must agree
STABLE_GIVE_UP = 30  # …or the last read is used after this long
LOCK = threading.RLock()
FALLBACK_GAP = 500  # a fallback goes on from the last page reading's Total Counter when the SNMP total is this close
FALLBACK_TEXT = "Counting from the total counter: pick the copy type"
COLOUR_WORDS = (("bw", "B&W"), ("color", "colour"))
SIZE_KEYS = (("A4", "s_other", "d_other"), ("A3", "s_a3", "d_a3"))


class CounterError(Exception):
    """The copier didn't answer."""


def read(copier, rules=None, page=True):
    """The copier's counters, read-only. The one place a counter is read (tests put a pretend copier here).
    page=True: the counter page first ({"how": "sheets" | "pages", ...}, see from_page); when it can't be read or
    parsed, the SNMP total counter (prtMarkerLifeCount, toners.py): {"how": "total", "total": n}. Raises
    CounterError when neither answers."""
    import toners
    rules = rules or routing.load_json("rules.json")
    address, _ = toners.copier_address(rules["printers"], copier)
    if not address:
        raise CounterError("its network address isn't known (Data screen)")
    if page:
        try:
            return from_page(counter_page.parse(counter_page.fetch(address)))
        except counter_page.PageError:
            pass
    total = toners.read_total(address, toners.load_settings()["community"])
    if total is None:
        raise CounterError(f"no answer from {address}")
    return {"how": "total", "total": total}


def from_page(parsed):
    """A reading from a parsed counter page:
    {"how": "sheets", "total", "copier": {"color": {"s_a3", "s_other", "d_a3", "d_other"}, "bw": {...}}} (sheets), or
    {"how": "pages", "total", "copier": {"color": {"pages"}, "bw": {"pages"}}, "other": {...}} (MP C3004 mode).
    Raises counter_page.PageError for a page ORCA doesn't know."""
    split = counter_page.sheet_split(parsed)
    if split:
        return {"how": "sheets", "total": parsed["total"], "copier": split}
    pages = counter_page.page_totals(parsed)
    if pages:
        return {"how": "pages", "total": parsed["total"],
                "copier": {"color": {"pages": pages["color"]}, "bw": {"pages": pages["bw"]}},
                "other": dict(parsed["other"])}
    raise counter_page.PageError("not a counter page ORCA knows")


def how_of(reading):
    return (reading or {}).get("how") or "total"


def a3_counts_as(rules):
    """How much one A3 page adds to the total counter (Tesla's test on the IM C4510, 2026-11-18: 2)."""
    try:
        return max(1, int(rules.get("copy_counter_a3_counts_as", 2)))
    except (TypeError, ValueError):
        return 2


def poll_seconds(rules):
    try:
        return max(1, int(rules.get("copy_counter_poll_seconds", 5)))
    except (TypeError, ValueError):
        return 5


def now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ the saved state

def path():
    return wo.open_dir() / FILE


def load_all():
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_all(counters):
    """Every running counter, written safely (temp file, then rename)."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(counters, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ one copier's counter

class Counter:
    """One copier's count: {"copier", "started", "mode": "counter" | "typed", "how": "sheets" | "pages" | "total",
    "start": the reading the current segment began at, "last": the last reading, "last_time",
    "current": {"type", "paper", "sides"}, "segments": [{"type", "paper", "sides", "copies", ("sheets", "group",
    "other")}], "extras": [{"name", "count", "per_copy"}], "rounding", "finished": bool, ("fell_back": time)}.
    sheets: staff pick only the paper (type and sides come from the copier). pages: only the size of "type" and the
    sides are used (colour comes from the copier). total: type and sides as picked."""

    def __init__(self, manager, copier, data):
        self.manager, self.copier, self.data = manager, copier, data
        data.setdefault("how", "total")

    @property
    def rules(self):
        return self.manager.rules

    @property
    def how(self):
        return self.data.get("how") or "total"

    def held(self):
        """Hold ORCA's own jobs on the copier? Not with the sheets reading (the Copier section counts no prints)."""
        return not (self.data["mode"] == "counter" and self.how == "sheets")

    # -------------------------------------------------------------- reading
    def reading(self):
        """Read the counter the way this count reads it. A page reading that stops working falls back to the total
        counter (fall_back), and the reading returned is then a total one."""
        how = self.how
        reading = self.manager.read(self.copier, page=how != "total")
        if how != "total" and how_of(reading) != how:
            if how_of(reading) != "total":  # another page layout: use the SNMP total
                reading = self.manager.read(self.copier, page=False)
            self.fall_back(reading)
        return reading

    def fall_back(self, reading):
        """The page can't be read any more: close the segment at the last page reading and go on from the total
        counter, with the copy type picked by staff, and hold the copier again."""
        last = self.data["last"]
        self._close(last)
        total, before = int(reading["total"]), (last or {}).get("total")
        base = before if isinstance(before, int) and 0 <= total - before <= FALLBACK_GAP else total
        self.data.update(how="total", start={"how": "total", "total": base}, last={"how": "total", "total": base},
                         fell_back=now())
        copier_queue.hold(self.copier)

    def counted(self, reading, start=None):
        """The current segment's copies between its start and a reading: [{"type", "sides", "copies", ("sheets")}].
        sheets: one side = simplex sheets, both sides = 2 x duplex sheets, per colour and size. pages: B&W and
        colour pages at the picked size and sides. total: the picked type (A3 pages may count as 2 on the total
        counter: rules.json copy_counter_a3_counts_as)."""
        start = start or self.data["start"]
        current, how = self.data["current"], self.how
        out = []
        if how == "sheets":
            for colour, word in COLOUR_WORDS:
                a, b = start["copier"][colour], reading["copier"][colour]
                for size, s_key, d_key in SIZE_KEYS:
                    one, both = max(0, b[s_key] - a[s_key]), max(0, b[d_key] - a[d_key])
                    if one:
                        out.append({"type": f"{size} {word}", "sides": "single", "copies": one, "sheets": one})
                    if both:
                        out.append({"type": f"{size} {word}", "sides": "double", "copies": 2 * both, "sheets": both})
            return out
        size = TYPES[current["type"]][0]
        if how == "pages":
            for colour, word in COLOUR_WORDS:
                n = max(0, int(reading["copier"][colour]["pages"]) - int(start["copier"][colour]["pages"]))
                if size == "A3":
                    n //= a3_counts_as(self.rules)
                if n:
                    out.append({"type": f"{size} {word}", "sides": current["sides"], "copies": n})
            return out
        raw = max(0, int(reading["total"]) - int(start["total"]))
        if size == "A3":
            raw //= a3_counts_as(self.rules)
        return [{"type": current["type"], "sides": current["sides"], "copies": raw}] if raw else []

    def diff(self, reading, kind=None):
        """The current segment's copies (every type) up to a reading."""
        return sum(e["copies"] for e in self.counted(reading))

    def poll(self):
        """Read the counter again (every few seconds while counting): the current segment's copies so far."""
        if self.data["mode"] != "counter" or self.data["finished"]:
            return self.current_copies()
        reading = self.reading()
        self.data["last"], self.data["last_time"] = reading, now()
        self.manager.save()
        return self.current_copies()

    def current_copies(self):
        if self.data["mode"] != "counter":
            return 0
        return self.diff(self.data["last"])

    def change(self, **current):
        """A copy type, paper or sides changed: close the current segment (read the counter), start a new one."""
        if self.data["finished"]:
            return
        new = dict(self.data["current"], **current)
        if new == self.data["current"]:
            return
        if self.data["mode"] == "counter":
            reading = self.reading()
            self._close(reading)
            self.data["start"] = reading
            self.data["last"], self.data["last_time"] = reading, now()
        self.data["current"] = new
        self.manager.save()

    def _entries(self, reading):
        """counted() with the paper (and, in pages mode, Other Function(s) at both ends, recorded only)."""
        out = []
        for e in self.counted(reading):
            e["paper"] = self.data["current"]["paper"]
            if self.how == "pages":
                e["other"] = {"start": self.data["start"].get("other"), "end": reading.get("other")}
            out.append(e)
        return out

    def _close(self, reading):
        entries = self._entries(reading)
        if entries:
            group = self.data.get("groups", 0) + 1
            self.data["groups"] = group
            for e in entries:
                self.data["segments"].append(dict(e, group=group))

    def add_typed(self, copies):
        """Type the copies instead (the copier didn't answer): a segment of the chosen type, paper and sides."""
        copies = int(copies)
        if copies < 1:
            raise ValueError("Copies: a whole number of 1 or more.")
        self.data["segments"].append(dict(self.data["current"], copies=copies))
        self.manager.save()

    def add_extra(self, name, count, per_copy=None):
        """An extra or a service with a count (sheets, copies, cuts, …): never money."""
        count = int(count)
        if count < 1:
            raise ValueError(f"{name}: a whole number of 1 or more.")
        if name == "Spiral binding" and not per_copy:
            raise ValueError("Spiral binding: say how many sheets per copy.")
        self.data["extras"].append({"name": name, "count": count, "per_copy": int(per_copy) if per_copy else None})
        self.manager.save()

    def remove_extra(self, index):
        if 0 <= index < len(self.data["extras"]):
            del self.data["extras"][index]
            self.manager.save()

    def set_rounding(self, mode):
        self.data["rounding"] = None if mode == self.data.get("rounding") else mode
        self.manager.save()

    def steady_key(self, reading):
        """What must stand still at Finish: the Copier section (page readings: ORCA's own prints may go on), else
        the total counter."""
        how = how_of(reading)
        return how, (reading.get("copier") if how != "total" else reading["total"])

    def finish(self, sleep=None, clock=None):
        """Read until two reads STABLE_SECONDS apart agree (give up after STABLE_GIVE_UP s: the last read), close the
        last segment. Returns True when the count was steady."""
        import time
        sleep, clock = sleep or time.sleep, clock or time.monotonic
        steady = True
        if self.data["mode"] == "counter":
            start = clock()
            reading = self.reading()
            while True:
                sleep(STABLE_SECONDS)
                again = self.reading()
                if self.steady_key(again) == self.steady_key(reading):
                    reading = again
                    break
                reading = again
                if clock() - start >= STABLE_GIVE_UP:
                    steady = False
                    break
            self._close(reading)
            self.data["start"] = self.data["last"] = reading
            self.data["last_time"] = now()
        self.data["finished"] = True
        self.manager.save()
        return steady

    # -------------------------------------------------------------- texts and prices
    def segment_text(self, seg):
        n = seg['copies']
        return f"{seg['type']}, {seg['paper']}, {SIDES[seg['sides']]}: {n} cop{'y' if n == 1 else 'ies'}"

    def segments_now(self):
        """The segments, with the running one while counting."""
        out = list(self.data["segments"])
        if not self.data["finished"] and self.data["mode"] == "counter":
            for e in self._entries(self.data["last"]):
                out.append(dict(e, group="now"))
        return out

    def lines(self):
        """The segment list for the panel. Copies the copier split by itself (sheets) are shown per segment and
        type: "A4 B&W: 23 copies on 20 sheets (17 one side, 3 both sides), Smooth white 80 gsm"."""
        out, grouped = [], {}
        for seg in self.segments_now():
            if seg.get("sheets") is None:
                out.append(self.segment_text(seg))
                continue
            key = (seg.get("group"), seg["type"], seg["paper"])
            if key not in grouped:
                grouped[key] = {"copies": 0, "sheets": 0, "single": 0, "double": 0}
                out.append(key)
            g = grouped[key]
            g["copies"] += seg["copies"]
            g["sheets"] += seg["sheets"]
            g[seg["sides"]] += seg["sheets"]
        return [line if isinstance(line, str) else auto_text(line[1], line[2], grouped[line]) for line in out]

    def priced(self, pl=None):
        return price(pl or walkin_prices.current(), self.segments_now(), self.data["extras"], self.data.get("rounding"))

    def short(self):
        """'A4 B&W one side x 37; A4 colour one side x 5; Staple x 2' for the sales list."""
        parts = [f"{s['type']} {SIDES[s['sides']]} x {s['copies']}" for s in self.data["segments"]]
        parts += [f"{e['name']} x {e['count']}" for e in self.data["extras"]]
        return "; ".join(parts)


def auto_text(kind, paper, g):
    copies = f"{g['copies']} cop{'y' if g['copies'] == 1 else 'ies'}"
    sheets = f"{g['sheets']} sheet{'' if g['sheets'] == 1 else 's'}"
    if g["single"] and g["double"]:
        sides = f"{g['single']} one side, {g['double']} both sides"
    else:
        sides = "one side" if g["single"] else "both sides"
    return f"{kind}: {copies} on {sheets} ({sides}), {paper}"


def sheets_of(seg):
    """Sheets of paper of a segment: as the copier counted them, else from the copies and sides."""
    if seg.get("sheets") is not None:
        return seg["sheets"]
    return seg["copies"] if seg["sides"] == "single" else math.ceil(seg["copies"] / 2)


def extra_rows(pl):
    """The extras and services a counter can add: (name, what is counted)."""
    rows = [("Lamination A4", "sheets"), ("Lamination A3", "sheets"), ("Spiral binding", "copies"),
            ("Staple", "copies"), ("Cutting", "cuts")]
    for name, (_, how, _) in pl.services.items():
        rows.append((name, {"piece": "pieces", "sheet": "sheets"}.get(how, "times")))
    return rows


def price(pl, segments, extras, rounding=None):
    """{"lines": [(text, amount)], "volume", "total", "due", "rounding", "problems"} for a receipt."""
    lines, problems = [], []
    counts = {}
    for seg in segments:
        key = TYPES[seg["type"]]
        counts[key] = counts.get(key, 0) + seg["copies"]
    tiers = {key: pl.tier_of(n) for key, n in counts.items()}
    for seg in segments:
        size, colour = TYPES[seg["type"]]
        tier = tiers[(size, colour)]
        rate = pl.copies[(size, colour)][tier - 1]
        text = f"{seg['type']} {SIDES[seg['sides']]} x {seg['copies']}"
        if rate is None:
            problems.append(P.no_price(f"{size} {P.COLOUR_WORD[colour]} copies, Tier {tier}"))
        else:
            lines.append((text, P.r2(seg["copies"] * rate)))
        sheets = sheets_of(seg)
        paper = pl.papers.get(pl.paper_row(seg["paper"]), {}).get(size)
        if paper is None:
            problems.append(P.no_price(f"{pl.paper_row(seg['paper'])}, {size} sheet"))
        else:
            lines.append((f"Paper {seg['paper']} x {sheets}", P.r2(sheets * paper)))
    for e in extras:
        name, n = e["name"], e["count"]
        if name.startswith("Lamination"):
            size = name.split()[-1]
            unit = pl.lamination.get(size)
            what = f"Lamination {size} (per sheet)"
        elif name == "Spiral binding":
            band = next(((limit, p) for limit, p in pl.spiral if (e.get("per_copy") or 0) <= limit), None)
            unit = band[1] if band else None
            what = f"Spiral binding (per copy, {e.get('per_copy')} sheets)"
            if band is None:
                problems.append(f"Spiral binding: more than {pl.spiral[-1][0]} sheets per copy can't be bound")
                continue
        elif name == "Staple":
            unit, what = pl.staple, "Staple (per copy)"
        elif name == "Cutting":
            unit, what = pl.cut_price, "the price per cut"
        else:
            unit, how, _ = pl.services.get(name, (None, None, ""))
            what = f"{name} (service)"
            if unit is not None and how == "item":
                n = 1
        if unit is None:
            problems.append(P.no_price(what))
            continue
        label = f"{name} x {e['count']}" + (f" ({e['per_copy']} sheets per copy)" if e.get("per_copy") else "")
        lines.append((label, P.r2(n * unit)))
    adjust = 0.0  # never pay more for fewer, per size and colour, as walk-in orders
    for key, n in counts.items():
        rates, tier = pl.copies[key], tiers[key]
        if rates[tier - 1] is None:
            continue
        normal = n * rates[tier - 1]
        best = min([normal] + [pl.tier_start(k) * rates[k - 1] for k in range(tier + 1, 4)
                               if pl.tier_start(k) is not None and rates[k - 1] is not None and pl.tier_start(k) > n])
        adjust += min(0.0, best - normal)
    adjust = P.r2(adjust) if adjust < -0.004 else 0.0
    if adjust:
        lines.append(("Volume price (never more for fewer copies)", adjust))
    total = P.r2(sum(a for _, a in lines))
    return {"lines": lines, "volume": adjust, "total": total, "rounding": rounding if rounding in P.ROUNDINGS else None,
            "due": P.rounded(total, rounding), "problems": problems}


# ------------------------------------------------------------------ every copier

class Manager:
    """The copiers' counters, kept for the whole session (the screen comes and goes)."""

    def __init__(self, rules, shared_jobs=None, read_func=None):
        self.rules = rules
        self.printers = rules["printers"]
        self.read_func = read_func  # tests: a pretend copier
        self.counters = {}
        for pid, data in load_all().items():  # still counting when ORCA was closed: go on (held as before)
            if pid in self.printers and isinstance(data, dict) and "segments" in data:
                self.counters[pid] = Counter(self, pid, data)
                if self.counters[pid].held():
                    copier_queue.hold(pid)
        if shared_jobs is not None:  # a held copier counts as busy: a colour job goes to the if_busy copier
            shared_jobs.busy_sources.append(lambda: set(copier_queue.HELD))

    def read(self, pid, page=True):
        """A reading of a copier (page=False: the total counter only)."""
        if not self.read_func:
            return read(pid, self.rules, page=page)
        reading = self.read_func(pid)  # tests: a pretend copier
        if not page and how_of(reading) != "total":
            reading = {"how": "total", "total": reading["total"]}
        return reading

    def save(self):
        with LOCK:
            save_all({pid: c.data for pid, c in self.counters.items()})

    def label(self, pid):
        return self.printers[pid].get("label", pid)

    def start(self, pid, busy_text=None, typed=False):
        """Start counting on a copier. busy_text: why ORCA's own printing refuses it (None: free). Raises
        CounterError when the copier doesn't answer (then typed=True starts a typed count)."""
        if pid in self.counters:
            return self.counters[pid]
        if busy_text:
            raise ValueError(busy_text)
        current = {"type": "A4 B&W", "paper": FIRST_PAPER, "sides": "single"}
        if typed:
            data = {"mode": "typed", "how": "total", "start": None, "last": None, "last_time": None}
        else:
            reading = self.read(pid)  # CounterError: the screen offers Type the copies instead
            data = {"mode": "counter", "how": how_of(reading), "start": reading, "last": reading, "last_time": now()}
        data.update(copier=pid, started=now(), current=current, segments=[], extras=[], rounding=None, finished=False)
        self.counters[pid] = Counter(self, pid, data)
        if self.counters[pid].held():
            copier_queue.hold(pid)
        self.save()
        return self.counters[pid]

    def cancel(self, pid):
        """Throw the count away: nothing is written, the copier is let go."""
        self.counters.pop(pid, None)
        self.save()
        copier_queue.release(pid)

    def done(self, pid, pl=None):
        """Write the sale (sales_log.csv) and one print_log.csv line per segment, then let the copier go."""
        c = self.counters.get(pid)
        if c is None:
            return None
        priced = c.priced(pl)
        if priced["problems"]:
            raise ValueError("\n".join(priced["problems"]))
        wo.write_sales_line({"date": now()[:10], "order": "", "status": "copied", "items": c.short(),
                             "paid": f"{priced['due']:.2f}", "source": "copy counter", "copier": self.label(pid)})
        log_segments(self.rules, self.label(pid), c.data["segments"])
        self.counters.pop(pid, None)
        self.save()
        copier_queue.release(pid)
        return priced


def log_segments(rules, label, segments):
    """print_log.csv: one line per segment, source walk-in, order "copy counter" (the Counter counts it as Walk-in)."""
    import jobs
    p = routing.app_dir() / jobs.LOG_FILE
    try:
        jobs._upgrade_header(p)
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(jobs.LOG_COLUMNS)
            for seg in segments:
                size, colour = TYPES[seg["type"]]
                n, sheets = seg["copies"], sheets_of(seg)
                w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"copy counter {label}", n, 1,
                            "color" if colour == "color" else "bw", "double" if seg["sides"] == "double" else "single",
                            size, "", "", "", label, "copy counter", sheets, "", "walk-in", "copy counter", "Copies",
                            n, size, n if colour == "color" else 0, n if colour == "bw" else 0, seg["paper"]])
    except OSError:
        pass  # the log must never stop the sale


# ------------------------------------------------------------------ the receipt

def receipt_rows(counter, priced, prices_on, when=None):
    """(header lines, rows [(left, right)], total text or None) for the XP-80C: no shop name, no ORCA, no PrintHub.
    Money only when prices_on (rules.json walkin_paper_prices)."""
    when = when or datetime.datetime.now()
    header = [when.strftime("%d/%m/%Y  %H:%M"), counter.manager.label(counter.copier)]
    rows = []
    for text, amount in priced["lines"]:
        if text.startswith("Volume price") and not prices_on:
            continue
        rows.append((text, f"{amount:.2f}" if prices_on else ""))
    total = None
    if prices_on:
        total = f"EUR {priced['due']:.2f}"
    return header, rows, total


def print_receipt(counter, priced, rules, path):
    """Draw the receipt PDF and send it to the receipt printer (rules.json receipt_printer) through SumatraPDF."""
    import printing
    import receipt
    import walkin_print
    header, rows, total = receipt_rows(counter, priced, walkin_print.paper_prices(rules))
    receipt.lines_pdf(path, header, rows, total)
    printing.send(path, rules["receipt_printer"])
    return path
