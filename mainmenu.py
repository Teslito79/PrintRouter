"""The main menu ORCA opens on: Walk-in, Orders, PrintHub, Counter, Prices, Data, Settings (Tesla, 2026-11-15 to 18).

Only one window shows at a time: the menu or one screen. Each screen's Back button (or its X) comes back here;
closing the menu closes ORCA. The menu starts what runs whatever shows: the ttk style, the website sync, the
finished-order cleanup, the toner reader, the walk-in file checks and the walk-in print queue (walkin_queue.py). PrintHub is made the first time
it is opened and is then only hidden (its orders and a waiting "Print backs" stay). Walk-in, Orders, Counter,
Prices and Data are made fresh each time (walk-in orders live in their folders, not in the window).
"""
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import cleanup
import copy_counter
import costs
import counter
import jobs
import printhub
import routing
import settings_screen
import sync
import theme
import toners
import walkin_orders
import walkin_print
import walkin_queue
import walkin_screens

FONT = ("Segoe UI", 12)


def setup_style(root):
    """The dark ttk style and the fonts every screen uses (was in the old Walk-in window until 2026-11-17)."""
    style = ttk.Style(root)
    theme.apply(root)
    style.configure(".", font=FONT)
    style.configure("Treeview", rowheight=28)
    style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"))
    style.configure("Print.TButton", font=("Segoe UI", 16, "bold"), padding=10)
    style.configure("Summary.TLabel", font=("Segoe UI", 13, "bold"))
    style.configure("Section.TLabelframe.Label", font=("Segoe UI", 12, "bold"))
    root.option_add("*TCombobox*Listbox.font", FONT)


class MainMenu:
    def __init__(self, root):
        self.root = root
        setup_style(root)
        self.rules = routing.load_rules()
        self.prices = routing.load_json("prices.json")
        self.jobs = jobs.Jobs(self.rules, self.prices)  # routing, checks and sending, shared by every screen
        threading.Thread(target=self.jobs.warm_up_checks, daemon=True).start()
        # Website orders into Pending Orders, while ORCA is open (only with printhub_token.txt: the work PC).
        self.sync = sync.WebsiteSync(self.rules)
        self.sync.start()
        # Finished Orders: each order goes to the Recycle Bin 8 days after Ready for courier.
        cleanup.start(self.rules)
        # Copier counters and toner levels, read at start and every 10 minutes (toners.py).
        self.toners = toners.TonerWatch(self.rules)
        self.toners.start()
        # Walk-in orders: their files are checked in the background; the print queue (one customer at a time per
        # copier, Start / Stop printing orders, Pages collected) lives here, so it carries on behind other screens.
        self.preparer = walkin_print.Preparer()
        self.print_queue = walkin_queue.Run(self.jobs, self.rules, self.preparer)
        # Copy counter (2026-11-17_10): one counter per copier; a running one goes on after a restart (copier held).
        self.copy_counter = copy_counter.Manager(self.rules, self.jobs)
        # Open walk-in orders whose product folders lack W100-2.cdr or Options.txt get them (never overwritten).
        threading.Thread(target=walkin_orders.prepare_all, args=(self.rules,), daemon=True).start()
        self.printhub = None

        self.win = win = tk.Toplevel(root)
        win.title("ORCA")
        win.configure(background=theme.BG)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.quit)
        style = ttk.Style(win)
        style.configure("Menu.TButton", font=("Segoe UI", 18, "bold"), padding=(20, 14))
        style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
        f = ttk.Frame(win, padding=(48, 32))
        f.grid(sticky="nsew")
        ttk.Label(f, text="ORCA", style="Title.TLabel").grid(row=0, column=0, pady=(0, 24))
        for r, (text, command) in enumerate((("Walk-in", self.open_walkin), ("Orders", self.open_orders),
                                             ("PrintHub", self.open_printhub), ("Counter", self.open_counter),
                                             ("Prices", self.open_prices), ("Data", self.open_toners),
                                             ("Settings", self.open_settings)),
                                            start=1):
            button = ttk.Button(f, text=text, style="Menu.TButton", width=16, command=command)
            button.grid(row=r, column=0, sticky="we", pady=6)
            if command == self.open_toners:  # by the command, so renaming the button keeps its dot
                # A red dot while a spare toner count is at or below its minimum (toners.stock_low).
                self.toner_dot = tk.Label(button, text="●", foreground=theme.ERROR, background=theme.BUTTON,
                                          font=("Segoe UI", 16), borderwidth=0)
        # 2026-11-18_02: a shop whose printers aren't installed here (the demo, a new shop) is told where to go.
        ttk.Style(win).configure("MenuWarn.TLabel", foreground=theme.WARN)
        self.printer_line = ttk.Label(f, text="", style="MenuWarn.TLabel", justify="center", wraplength=380)
        self.printer_line.grid(row=8, column=0, pady=(18, 0))
        self.show_printer_line()
        self.sync_label = ttk.Label(f, text="", style="Hint.TLabel", justify="center", wraplength=380)
        self.sync_label.grid(row=9, column=0, pady=(22, 0))
        theme.dark_title_bar(win)
        self.print_queue.parent = win
        self.show_sync()
        self.queue_tick()

    # -------------------------------------------------------------- showing

    def show_menu(self):
        if self.printhub is not None:
            try:
                self.printhub.win.withdraw()
            except tk.TclError:
                pass
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def open_screen(self, window):
        self.win.withdraw()
        window.deiconify()
        window.lift()
        window.focus_force()

    def open_walkin(self):
        self.open_screen(walkin_screens.WalkinScreen(self, on_back=self.show_menu).win)

    def open_orders(self):
        self.open_screen(walkin_screens.OrdersScreen(self, on_back=self.show_menu).win)

    def open_printhub(self):
        if self.printhub is None or not self.printhub.is_open():
            self.printhub = printhub.PrintHubView(self.root, self.rules, self.jobs, self.sync, on_back=self.show_menu)
        self.open_screen(self.printhub.win)

    def open_counter(self):
        screen = counter.CounterScreen(self.root, self.rules, on_back=self.show_menu)
        self.open_screen(screen.win)

    def open_prices(self):
        if not costs.ask_to_open(self.win):
            return
        papers = sorted({e["paper"] for e in counter.read_log() if e["paper"]})
        screen = costs.PricesScreen(self.root, self.rules, on_back=self.show_menu, papers_in_log=papers)
        self.open_screen(screen.win)

    def open_toners(self):
        screen = toners.TonersScreen(self.root, self.rules, self.toners, on_back=self.show_menu)
        self.open_screen(screen.win)

    def open_settings(self):
        """Settings (2026-11-18_02): behind the same password as Prices."""
        if not costs.ask_to_open(self.win):
            return
        self.open_screen(settings_screen.SettingsScreen(self, on_back=self.show_menu).win)

    NO_PRINTERS = "No printers set up yet: open Settings"

    def show_printer_line(self):
        """One yellow line when no printer in force is installed on this PC (never blocks anything)."""
        installed = routing.installed_printers()
        none = installed is not None and not any(p.get("queue") in installed for p in self.rules["printers"].values())
        self.printer_line.config(text=self.NO_PRINTERS if none else "")
        if none:
            self.printer_line.grid()
        else:
            self.printer_line.grid_remove()

    def apply_settings(self):
        """Settings saved (or reset): the rules in force are loaded again and changed in place, so the queues, the
        copy counter, PrintHub and the Data screen use them for new jobs at once. Jobs already sent keep their
        printer."""
        new = routing.load_rules()
        before = set(self.rules["printers"])
        printers = self.rules["printers"]  # the same dict everyone holds
        printers.clear()
        printers.update(new.pop("printers"))
        for key in [k for k in self.rules if k not in new and k != "printers"]:
            del self.rules[key]
        self.rules.update(new)
        for pid in printers:
            self.print_queue.copiers.setdefault(pid, {"state": "idle"})
        threading.Thread(target=self.jobs.settings_changed, daemon=True).start()
        if set(printers) != before and self.printhub is not None:
            busy = any(self.printhub.busy_with(pid) for pid in before)
            if not busy and not self.printhub.sending():
                try:
                    self.printhub.win.destroy()
                except tk.TclError:
                    pass
                self.printhub = None  # made again with the new printers when opened
        self.show_printer_line()

    def show_sync(self):
        """The website sync's state, the same line as in PrintHub."""
        text, red, stuck = self.sync.status()
        self.sync_label.config(text="\n".join([text] + stuck), foreground=theme.ERROR if red or stuck else "")
        try:
            low = toners.stock_low(self.rules["printers"])
        except Exception:
            low = False
        if low:
            self.toner_dot.place(relx=1.0, x=-12, y=6, anchor="ne")
        else:
            self.toner_dot.place_forget()
        self.win.after(2000, self.show_sync)

    def queue_tick(self):
        try:
            self.print_queue.tick()
        except Exception:
            pass  # never stop the menu; the next tick tries again
        self.win.after(2000, self.queue_tick)

    # -------------------------------------------------------------- closing

    def quit(self):
        """Closing the menu closes ORCA (asks first while something is being sent)."""
        if self.print_queue.busy() and not messagebox.askyesno(
                parent=self.win, title="ORCA", message="Walk-in orders are still being sent. Close anyway?"):
            return
        if (self.printhub is not None and self.printhub.sending() and not messagebox.askyesno(
                parent=self.win, title="ORCA", message="PrintHub orders are still being sent. Close anyway?")):
            return
        self.root.destroy()
