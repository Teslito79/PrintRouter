"""The walk-in print queue (Print Jobs, handoff 2026-11-17_04): one customer at a time per copier.

Nothing is sent until Start printing orders (or Print now on one order). Each copier's queue holds customer batches:
all of one customer's ready orders that have a part on that copier, oldest first. A free copier sends its first
batch, each order with its own cover sheet first (on the copier of the order's first part only), the parts that run
straight through first and then each hand-turned part (fronts, Print backs). Pages collected is pressed once per
batch and starts that copier's next batch. Staff can drag batches into another order (per copier), or drag one order
out of its customer's batch; that order is kept in Walk-in\\Open\\print_queue.json, with what each copier holds, so
a restart keeps both. Orders that become ready while printing is ON join their customer's waiting batch, or become a
new batch at the end; never a batch already sent.

Where an order's items go is fixed in order.json ("parts") when the order is first sent: {copier: {"items": [item
indexes], "cover": True on the copier of its first part, "state": "waiting" | "printing" | "collected", "sent": [keys],
"fronts": [keys of hand-turned items whose fronts are out]}}; the keys are "cover" and the item index as text.
The order is Printed once every part is collected. The queue logic shared with PrintHub is in copier_queue.py.

Everything here runs on the Tk thread except the sending, which has its own thread (as PrintHub's).
"""
import queue
import threading
import time

import analyze
import copier_queue
import jobs
import walkin_orders as wo
import walkin_print

QUEUE_FILE = "print_queue.json"
COVER_KEY = "cover"
CLOSED = ("ORCA was closed while this was being sent. Check what came out of the copier, then press Retry "
          "(it sends what isn't marked sent yet).")


def queue_path():
    return wo.open_dir() / QUEUE_FILE


def arrange(saved, waiting):
    """The batches on one copier: the saved order (staff moves) with gone orders left out, then each new order
    into its customer's first waiting batch, or as a new batch at the end. With nothing saved this is the default:
    batches by the customer's oldest ready order. Within a batch, oldest order first."""
    by_number = {o["number"]: o for o in waiting}
    out, seen = [], set()
    for batch in saved:
        kept = [n for n in batch if n in by_number and n not in seen]
        seen.update(kept)
        if kept:
            out.append(kept)
    for o in sorted(waiting, key=lambda o: o["created"]):
        if o["number"] in seen:
            continue
        seen.add(o["number"])
        target = next((b for b in out if by_number[b[0]]["customer"]["id"] == o["customer"]["id"]), None)
        if target is None:
            out.append([o["number"]])
        else:
            target.append(o["number"])
    return [sorted(b, key=lambda n: by_number[n]["created"]) for b in out]


def customer_name(order):
    c = order["customer"]
    return c.get("name") or c.get("phone") or c.get("email") or "No details"


def load(number):
    """The open order with this number, fresh from its folder, or None (collected, cancelled, gone)."""
    try:
        return wo.load_order(wo.open_dir() / f"#{number}")
    except (OSError, ValueError):
        return None


class Run:
    """Start / Stop, every copier's batch and queue, Pages collected, Print backs, Retry, Print now."""

    def __init__(self, shared_jobs, rules, preparer):
        self.jobs, self.rules, self.preparer = shared_jobs, rules, preparer
        self.printers = rules["printers"]
        self.running = False
        # What each copier holds: {"state": "idle" | "sending" | "turn" | "sent" | "failed", "orders": [numbers],
        # "customer": name, "turn": [number, key] (waiting for Print backs), "error": text}
        self.copiers = {pid: {"state": "idle"} for pid in self.printers}
        self.custom = {}  # copier -> [[order numbers]], only for copiers staff rearranged
        self.progress = {}  # copier -> (n, of total, text) while sending
        self.declined = {}  # copier -> the batch staff said No to (big send): not asked again by itself
        self.orders = {}  # number -> open order, as the screen (or the tick) last read them
        self.plans = {}  # number -> ({copier: [(key, job, pdf)]}, cover copier) or the reason it can't print
        self.updated = 0.0
        self.to_send = queue.Queue()
        self.results = queue.Queue()
        self.parent = None  # the window message boxes belong to (Print Jobs while it is open)
        self.messages = []  # lines for the Print Jobs status line
        self.load_file()
        # A copier with a walk-in batch is busy: colour goes to the IM C4510 instead of the IM C3000.
        shared_jobs.busy_sources.append(lambda: {p for p, c in self.copiers.items() if c["state"] != "idle"})
        copier_queue.RELEASED.append(self.start_next)  # a copier the Copy counter let go carries on
        threading.Thread(target=self._send_worker, daemon=True).start()

    # -------------------------------------------------------------- the file

    def load_file(self):
        try:
            import json
            data = json.loads(queue_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.custom = {p: [list(map(int, b)) for b in v] for p, v in data.get("custom", {}).items()
                       if p in self.printers}
        for p, c in data.get("copiers", {}).items():
            if p in self.printers and c.get("state") in ("sending", "turn", "sent", "failed"):
                if c["state"] == "sending":
                    c = dict(c, state="failed", error=CLOSED)
                self.copiers[p] = c

    def save_file(self):
        try:
            wo.open_dir().mkdir(parents=True, exist_ok=True)
            wo._write_json(queue_path(), {"custom": self.custom,
                                          "copiers": {p: c for p, c in self.copiers.items() if c["state"] != "idle"}})
        except OSError:
            pass  # the queue order is a convenience: never stop printing over it

    # -------------------------------------------------------------- plans

    def plan(self, order):
        """({copier: [(key, job, pdf)]}, cover copier) for the parts still to send, or raises ValueError."""
        fixed = {int(i): p for p, part in (order.get("parts") or {}).items() for i in part["items"]}
        parts = {}
        for i, item in enumerate(order["items"]):
            if fixed and fixed.get(i) is None:
                continue
            prepared = self.preparer.get(order, item)
            if prepared is None:
                raise ValueError(f"item {i + 1} is still being checked")
            if "error" in prepared:
                raise ValueError(f"item {i + 1}: {prepared['error']}")
            job = walkin_print.job_for(self.jobs, self.rules, item, prepared, printer=fixed.get(i))
            if job is None:
                raise ValueError(f"item {i + 1}: these settings can't print")
            if job["problem"]:
                raise ValueError(f"item {i + 1}: {job['problem']}")
            job["file_name"] = f"#{order['number']} {item['folder']}"
            job["log_info"] = walkin_print.log_info(order, item)
            parts.setdefault(job["printer"], []).append((str(i), job, prepared["pdf"]))
        if not parts:
            raise ValueError("nothing to print")
        if fixed:
            cover = next((p for p, part in order["parts"].items() if part.get("cover")), None)
        else:
            cover = next(iter(parts))  # the copier of the order's first part
        return parts, cover

    def waiting_parts(self, order):
        """The copiers this order still waits for (empty when it can't print yet or is being printed)."""
        plan = self.plans.get(order["number"])
        if order["status"] != "ready_to_print" or not isinstance(plan, tuple):
            return set()
        parts = order.get("parts")
        if parts:
            return {p for p, part in parts.items() if part["state"] == "waiting"}
        return set(plan[0])

    def update(self, orders):
        """The open orders as read now (the screen's poll, or the tick): plans, then fill free copiers if ON."""
        self.orders = {o["number"]: o for o in orders}
        self.plans = {}
        for o in orders:
            if o["status"] != "ready_to_print":
                continue
            try:
                self.plans[o["number"]] = self.plan(o)
            except ValueError as e:
                self.plans[o["number"]] = str(e)
        self.updated = time.time()
        if self.running:
            for pid in self.printers:
                self.start_next(pid, auto=True)

    def tick(self):
        """Every 2 s from the main menu: messages from the sending thread; with printing ON and no Print Jobs
        screen reading the orders, read them here so new ready orders still start."""
        self.handle_results()
        if self.running and time.time() - self.updated > 2.5:
            self.update([wo.refresh(o) for o in wo.list_open()])

    # -------------------------------------------------------------- the queues

    def batches(self, pid):
        """[[order numbers]] waiting for this copier, in the order they will go."""
        waiting = [o for o in self.orders.values() if pid in self.waiting_parts(o)]
        return arrange(self.custom.get(pid, []), waiting)

    def batch_info(self, pid, batch):
        """(sheets, colour text, sides text) of a batch's items on a copier (cover sheets not counted, as PrintHub
        counts only the documents)."""
        jobs_of = []
        for n in batch:
            plan = self.plans.get(n)
            if isinstance(plan, tuple):
                jobs_of += [job for _, job, _ in plan[0].get(pid, [])]
        sheets = sum(j["sheets"] for j in jobs_of)
        colours = {bool(j["color"]) for j in jobs_of}
        sides = {bool(j["duplex"]) for j in jobs_of}
        colour = "colour" if colours == {True} else "B&W" if colours == {False} else "colour and B&W"
        side = "both sides" if sides == {True} else "one side" if sides == {False} else "one and both sides"
        return sheets, colour, side

    def batch_text(self, pid, batch):
        """'Nikos P.: #101 (500 sheets, B&W, both sides)', 'no cover sheet' for a split order's second copier."""
        sheets, colour, side = self.batch_info(pid, batch)
        first = self.orders.get(batch[0])
        numbers = ", ".join(f"#{n}" + ("" if self.cover_here(n, pid) else " (no cover sheet)") for n in batch)
        return f"{customer_name(first) if first else '?'}: {numbers} ({sheets_text(sheets)}, {colour}, {side})"

    def cover_here(self, number, pid):
        plan = self.plans.get(number)
        return not isinstance(plan, tuple) or plan[1] == pid

    def copier_text(self, pid):
        """What the copier is doing, for its block in Print Jobs."""
        c = self.copiers[pid]
        if c["state"] == "idle":
            return copier_queue.HELD_TEXT if copier_queue.held(pid) else "Free"
        orders = c["orders"]
        held = f"{c.get('customer', '?')}: {', '.join(f'#{n}' for n in orders)}" + (
            f" ({len(orders)} orders)" if len(orders) > 1 else "")
        no_cover = [f"#{n}" for n in orders if not c.get("cover", {}).get(str(n), True)]
        if no_cover:
            held += f" · no cover sheet for {', '.join(no_cover)} (it prints on the other copier)"
        if c["state"] == "sending":
            n, total, _ = self.progress.get(pid, (0, 0, ""))
            return f"{held}\nsending {n} of {total}…" if total else f"{held}\nsending…"
        if c["state"] == "sent":
            return f"{held}\nAll sent. Take the pages off when they're done, then press Pages collected."
        if c["state"] == "turn":
            number, key = c["turn"]
            order = load(number)
            name = order["items"][int(key)]["folder"] if order else key
            return (f"{held}\n#{number} {name}: fronts sent. When they're out, turn the stack over, put it back "
                    f"in the Bypass Tray, then press Print backs.")
        return f"{held}\nNOT all sent: {c.get('error', '')}"

    def busy(self):
        """True while something is being sent (closing ORCA asks first)."""
        return any(c["state"] == "sending" for c in self.copiers.values())

    def order_state(self, order):
        """'Printing on IM C4510', 'In the queue on IM C4510 (2nd)', or None."""
        parts = order.get("parts") or {}
        on = [self.printers[p]["label"] for p, part in parts.items() if part["state"] == "printing"]
        if on:
            return "Printing on " + " and ".join(on)
        places = []
        for pid in sorted(self.waiting_parts(order)):
            batches = self.batches(pid)
            k = next((i for i, b in enumerate(batches) if order["number"] in b), None)
            if k is not None:
                places.append(f"{self.printers[pid]['label']} ({_nth(k + 1)})")
        return ("In the queue on " + ", ".join(places)) if places else None

    # -------------------------------------------------------------- rearranging

    def move_batch(self, pid, index, before):
        """Drag a waiting batch (or Move up / Move down): it lands before the batch at `before`."""
        lst = self.batches(pid)
        if not 0 <= index < len(lst):
            return
        moving = lst[index]
        lst[index] = None
        lst.insert(max(0, min(before, len(lst))), moving)
        self._keep(pid, lst)

    def move_order(self, pid, number, before=None, join=None):
        """Drag one order out of its batch (its own batch, landing before `before`), or onto a batch (`join`):
        onto its own customer's batch it joins it; onto another customer's it lands just before it."""
        lst = self.batches(pid)
        source = next((k for k, b in enumerate(lst) if number in b), None)
        if source is None:
            return
        if join is not None and 0 <= join < len(lst):
            target = lst[join]
            same = self.orders[target[0]]["customer"]["id"] == self.orders[number]["customer"]["id"]
            if join == source:
                return
            if same:
                lst[source] = [n for n in lst[source] if n != number] or None
                target.append(number)
                self._keep(pid, lst)
                return
            before = join
        rest = [n for n in lst[source] if n != number]
        lst[source] = rest or None
        lst.insert(max(0, min(before if before is not None else len(lst), len(lst))), [number])
        self._keep(pid, lst)

    def _keep(self, pid, lst):
        self.custom[pid] = [b for b in lst if b]
        self.save_file()

    # -------------------------------------------------------------- sending

    def start_printing(self):
        self.running = True
        self.declined.clear()
        copier_queue.fill_free(self.printers, self.start_next)

    def stop_printing(self):
        self.running = False

    def start_next(self, pid, auto=False):
        """Send this copier's first waiting batch if printing is ON and the copier is free."""
        if not self.running or self.copiers[pid]["state"] != "idle" or copier_queue.held(pid):
            return
        lst = self.batches(pid)
        if not lst:
            return
        if auto and self.declined.get(pid) == lst[0]:
            return
        if not self.start_batch(pid, lst[0]):
            self.declined[pid] = lst[0]

    def start_batch(self, pid, batch):
        """Fix the orders' parts, ask before a big send, then send. False when staff said No."""
        orders = sorted((self.orders[n] for n in batch), key=lambda o: o["created"])
        sheets, _, _ = self.batch_info(pid, batch)
        who = customer_name(orders[0])
        what = f"{who}'s order #{orders[0]['number']}" if len(orders) == 1 else \
            f"{who}'s orders {', '.join('#' + str(o['number']) for o in orders)}"
        if not copier_queue.big_send_ok(self.rules, self.parent, "ORCA", what[0].upper() + what[1:], sheets,
                                        self.printers[pid]["label"]):
            return False
        cover = {}
        # Read again from the folder: the sending thread's progress on another copier may be newer.
        orders = [o for o in (load(o["number"]) for o in orders) if o is not None]
        if not orders:
            return True
        for o in orders:
            self.orders[o["number"]] = o
            parts, cover_pid = self.plans[o["number"]]
            if not o.get("parts"):  # where every item goes, for all copiers at once
                o["parts"] = {p: {"items": [int(k) for k, _, _ in tasks], "cover": p == cover_pid,
                                  "state": "waiting", "sent": [], "fronts": []} for p, tasks in parts.items()}
            o["parts"][pid]["state"] = "printing"
            cover[str(o["number"])] = bool(o["parts"][pid]["cover"])
            wo.save_order(o)
        self.copiers[pid] = {"state": "sending", "orders": [o["number"] for o in orders], "customer": who,
                             "cover": cover}
        self.declined.pop(pid, None)
        self.save_file()
        self.step(pid)
        return True

    def job_of(self, order, key, pid):
        """(job, pdf) for one key of the order's part on this copier; raises ValueError."""
        if key == COVER_KEY:
            path = walkin_print.WORK_DIR / f"cover_{order['number']}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            with jobs.PDF_LOCK:
                walkin_print.cover_pdf(order, path)
                pages = analyze.page_count(path)
            job = walkin_print.cover_job(self.jobs, pid, pages)
            if job is None or job["problem"]:
                raise ValueError(f"the cover sheet can't print on {self.printers[pid]['label']}"
                                 + (f": {job['problem']}" if job else ""))
            job["file_name"] = f"#{order['number']} {walkin_print.COVER}"
            job["log_info"] = walkin_print.log_info(order)
            return job, path
        item = order["items"][int(key)]
        prepared = self.preparer.get(order, item)
        job = walkin_print.job_for(self.jobs, self.rules, item, prepared, printer=pid)
        if job is None or job["problem"]:
            raise ValueError(f"#{order['number']} {item['folder']} can't be printed any more"
                             + (f": {job['problem']}" if job and job["problem"] else ""))
        job["file_name"] = f"#{order['number']} {item['folder']}"
        job["log_info"] = walkin_print.log_info(order, item)
        return job, prepared["pdf"]

    def step(self, pid):
        """Send what comes next in the copier's batch: Print backs first if fronts are out; else the parts that
        run straight through (each order's cover sheet first), then the next hand-turned part's fronts."""
        c = self.copiers[pid]
        orders = [o for o in (load(n) for n in c["orders"]) if o is not None and pid in (o.get("parts") or {})]
        for o in orders:
            part = o["parts"][pid]
            keys = self.keys(part)
            backs = copier_queue.waiting_backs(keys, part["sent"], part["fronts"])
            if backs:
                c.update(state="turn", turn=[o["number"], backs], error=None)
                self.save_file()
                return
        tasks, hand = [], None
        try:
            for o in orders:
                part = o["parts"][pid]
                found = {k: self.job_of(o, k, pid) for k in self.keys(part) if k not in part["sent"]}
                straight, h = copier_queue.next_send(self.keys(part), lambda k: bool(found[k][0].get("hand")),
                                                     part["sent"], part["fronts"])
                tasks += [(o["number"], k, *found[k], None) for k in straight]
                if h and hand is None:
                    hand = (o["number"], h, *found[h], "fronts")
        except ValueError as e:
            c.update(state="failed", error=str(e))
            self.save_file()
            return
        if hand:
            number, key, job, pdf, _ = hand
            job["file_name"] += " fronts"
            tasks.append(hand)
        if not tasks:
            c.update(state="sent", error=None)
            c.pop("turn", None)
            self.save_file()
            return
        c.update(state="sending", error=None)
        c.pop("turn", None)
        self.progress[pid] = (0, len(tasks), "")
        self.save_file()
        self.to_send.put((pid, tasks))

    @staticmethod
    def keys(part):
        return ([COVER_KEY] if part.get("cover") else []) + [str(i) for i in part["items"]]

    def send_backs(self, pid):
        """Print backs: the stack of fronts was turned over and put back; send page 2."""
        c = self.copiers[pid]
        if c["state"] != "turn":
            return
        number, key = c["turn"]
        order = load(number)
        try:
            if order is None:
                raise ValueError(f"#{number} is no longer open")
            job, pdf = self.job_of(order, key, pid)
            job["file_name"] += " backs"
        except ValueError as e:
            c.update(state="failed", error=str(e))
            self.save_file()
            return
        c.update(state="sending", error=None)
        self.progress[pid] = (0, 1, "")
        self.save_file()
        self.to_send.put((pid, [(number, key, job, pdf, "backs")]))

    def retry(self, pid):
        if self.copiers[pid]["state"] == "failed":
            self.step(pid)

    def collected(self, pid):
        """The pages were taken off this copier: its orders' parts are collected (an order whose every part is
        collected is Printed), and the copier's next batch starts if printing is ON."""
        c = self.copiers[pid]
        if c["state"] == "idle":
            return
        for number in c.get("orders", []):
            o = load(number)
            if o is None or pid not in (o.get("parts") or {}):
                continue
            part = o["parts"][pid]
            part["collected_times"] = part.get("collected_times", 0) + 1
            try:  # Inventory (2026-11-19_03): the paper printed on this part, once per collection; never blocks
                import inventory
                inventory.take_for_part(o, pid, part, rules=self.rules)
            except Exception:
                pass
            part["state"] = "collected"
            if all(part["state"] == "collected" for part in o["parts"].values()):
                wo.set_status(o, "printed")
            else:
                wo.save_order(o)
        self.copiers[pid] = {"state": "idle"}
        self.progress.pop(pid, None)
        self.save_file()
        self.update([wo.refresh(o) for o in wo.list_open()])
        self.start_next(pid)

    def print_now(self, number):
        """Send one order straight away, only to free copiers. Returns the message to show, or None."""
        order = self.orders.get(number)
        plan = self.plans.get(number)
        if order is None or not isinstance(plan, tuple):
            return f"#{number} can't print yet: {plan or 'not ready'}"
        waiting = sorted(self.waiting_parts(order))
        for pid in waiting:
            c = self.copiers[pid]
            if copier_queue.held(pid):
                return f"{self.printers[pid]['label']} is held: the copy counter is running on it."
            if c["state"] != "idle":
                who = c.get("customer", "another customer").rstrip(".")
                return (f"{self.printers[pid]['label']} is busy with {who}. "
                        f"Press Pages collected first, or move the order up the queue.")
        for pid in waiting:
            self.start_batch(pid, [number])
        return None

    def _send_worker(self):
        """Send the batches one after another; the copiers then print them at the same time."""
        import itertools
        while True:
            pid, tasks = self.to_send.get()
            label = self.printers[pid]["label"]
            # Rotate sort (2026-11-19_05): one tray rotation for the whole batch, so file after file and copy after
            # copy lie crosswise on the one before.
            trays = itertools.cycle((self.rules.get("rotate_sort") or {}).get("trays") or [walkin_print.TRAY])
            for n, (number, key, job, pdf, side) in enumerate(tasks, start=1):
                self.results.put(("progress", pid, n, len(tasks), f"{job['file_name']} → {label}…"))
                try:
                    work = walkin_print.WORK_DIR / f"send_{number}_{key}"
                    work.mkdir(parents=True, exist_ok=True)
                    self.jobs.print_one(work, job, pdf, pdf, job["paper"], trays, side=side)
                except Exception as e:
                    self.results.put(("failed", pid, f"{job['file_name']}: {e}"))
                    break
                if side != "fronts":  # a hand-turned item is logged once, with its backs
                    self.jobs.log(job, label)
                self.results.put(("sent", pid, number, key, side))
            else:
                self.results.put(("done", pid))

    def handle_results(self):
        while True:
            try:
                msg = self.results.get_nowait()
            except queue.Empty:
                return
            kind, pid = msg[0], msg[1]
            c = self.copiers[pid]
            if kind == "progress":
                self.progress[pid] = msg[2:]
                self.messages = (self.messages + [msg[4]])[-20:]
            elif kind == "sent":
                _, _, number, key, side = msg
                o = load(number)
                if o is not None and pid in (o.get("parts") or {}):
                    part = o["parts"][pid]
                    (part["fronts"] if side == "fronts" else part["sent"]).append(key)
                    wo.save_order(o)
            elif kind == "failed":
                c.update(state="failed", error=msg[2])
                self.progress.pop(pid, None)
                self.messages = (self.messages + [f"{self.printers[pid]['label']}: {msg[2]}"])[-20:]
                self.save_file()
            elif kind == "done":
                self.progress.pop(pid, None)
                self.step(pid)


def sheets_text(n):
    return f"{n} sheet{'' if n == 1 else 's'}"


def _nth(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
