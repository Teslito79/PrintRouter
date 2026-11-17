"""The copier queue logic PrintHub and walk-in Print Jobs share (2026-11-17).

Both screens send nothing until Start printing orders, fill every free copier, ask before a big send, put the
parts that run straight through first and each hand-turned part after them (fronts, then Print backs), and free a
copier with Pages collected. What a copier holds differs: PrintHub one order at a time, walk-in one customer's
orders (a batch, walkin_queue.py). The two screens keep separate queues.
"""
from tkinter import messagebox

# A copier taken by a part (sending, sent and not collected yet, waiting for Print backs, failed or interrupted).
BUSY = ("sending", "turn", "sent", "failed", "interrupted")


def run_text(running, what="order"):
    """The run line under Start / Stop printing orders."""
    if running:
        return f"Printing orders: ON. “Pages collected” starts that copier's next {what}."
    return "Printing orders: OFF. Nothing is sent until you press Start printing orders."


def fill_free(printers, start_next):
    """Start printing orders: give every free copier its next work (start_next skips busy copiers)."""
    for pid in printers:
        start_next(pid)


def big_send_ok(rules, parent, title, what, sheets, printer_label):
    """rules.json confirm_above_sheets: ask before a send of more sheets than that (True: send it)."""
    limit = rules.get("confirm_above_sheets", 0)
    if limit and sheets > limit:
        return messagebox.askyesno(title, f"{what} uses {sheets} sheets on {printer_label}.\n\nPrint it?",
                                   parent=parent)
    return True


def next_send(names, is_hand, sent, fronts):
    """What to send next on a copier: (the not-sent names that run straight through, in order; the first
    hand-turned name whose fronts are not out yet, or None). Its backs wait for Print backs."""
    straight, hand = [], None
    for name in names:
        if name in sent:
            continue
        if is_hand(name):
            if hand is None and name not in fronts:
                hand = name
            continue
        straight.append(name)
    return straight, hand


def waiting_backs(names, sent, fronts):
    """The first hand-turned name whose fronts are out and whose backs are not (it waits for Print backs)."""
    return next((n for n in names if n in fronts and n not in sent), None)
