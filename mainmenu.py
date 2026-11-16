"""The main menu PrintRouter opens on: Walk-in, PrintHub, Counter, Prices (Tesla, 2026-11-15),
Data (toners, 2026-11-16).

Only one window shows at a time: the menu or one screen. Each screen's Back button (or its X)
comes back here; closing the menu closes PrintRouter. The walk-in screen is made at start and only
hidden, so its files, the inbox, the website sync and the finished-order cleanup keep running
whatever shows. PrintHub is made the first time it is opened and is then only hidden too.
Counter and Prices are made fresh each time.
"""
import tkinter as tk
from tkinter import messagebox, ttk

import costs
import counter
import printhub
import theme
import toners


class MainMenu:
    def __init__(self, root, walk_in_class):
        """walk_in_class: app.App (passed in, because app.py is the program that starts the menu)."""
        self.root = root
        walk_in = tk.Toplevel(root)
        walk_in.withdraw()
        # Builds the ttk style, starts the website sync and the cleanup (app.App.__init__).
        self.walkin = walk_in_class(walk_in, on_back=self.show_menu)
        theme.dark_title_bar(walk_in)
        self.rules = self.walkin.rules
        self.printhub = None
        # Copier counters and toner levels, read at start and every 10 minutes (toners.py).
        self.toners = toners.TonerWatch(self.rules)
        self.toners.start()

        self.win = win = tk.Toplevel(root)
        win.title("PrintRouter")
        win.configure(background=theme.BG)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.quit)
        style = ttk.Style(win)
        style.configure("Menu.TButton", font=("Segoe UI", 18, "bold"), padding=(20, 16))
        style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
        f = ttk.Frame(win, padding=(48, 36))
        f.grid(sticky="nsew")
        ttk.Label(f, text="PrintRouter", style="Title.TLabel").grid(row=0, column=0, pady=(0, 28))
        for r, (text, command) in enumerate((("Walk-in", self.open_walkin), ("PrintHub", self.open_printhub),
                                             ("Counter", self.open_counter), ("Prices", self.open_prices),
                                             ("Data", self.open_toners)),
                                            start=1):
            button = ttk.Button(f, text=text, style="Menu.TButton", width=16, command=command)
            button.grid(row=r, column=0, sticky="we", pady=7)
            if command == self.open_toners:  # by the command, so renaming the button keeps its dot
                # A red dot while a spare toner count is at or below its minimum (toners.stock_low).
                self.toner_dot = tk.Label(button, text="●", foreground=theme.ERROR, background=theme.BUTTON,
                                          font=("Segoe UI", 16), borderwidth=0)
        self.sync_label = ttk.Label(f, text="", style="Hint.TLabel", justify="center", wraplength=380)
        self.sync_label.grid(row=7, column=0, pady=(24, 0))
        theme.dark_title_bar(win)
        self.show_sync()

    # -------------------------------------------------------------- showing

    def screens(self):
        wins = [self.walkin.root]
        if self.printhub is not None:
            wins.append(self.printhub.win)
        return wins

    def show_menu(self):
        for w in self.screens():
            try:
                w.withdraw()
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
        self.open_screen(self.walkin.root)

    def open_printhub(self):
        if self.printhub is None or not self.printhub.is_open():
            self.printhub = printhub.PrintHubView(self.root, self.rules, self.walkin.jobs, self.walkin.sync,
                                                  on_back=self.show_menu)
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

    def show_sync(self):
        """The website sync's state, the same line as in PrintHub."""
        text, red, stuck = self.walkin.sync.status()
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

    # -------------------------------------------------------------- closing

    def quit(self):
        """Closing the menu closes PrintRouter (asks first while something is being sent)."""
        if self.walkin.busy and not messagebox.askyesno(
                parent=self.win, title="PrintRouter", message="Files are still being sent. Close anyway?"):
            return
        if (self.printhub is not None and self.printhub.sending() and not messagebox.askyesno(
                parent=self.win, title="PrintRouter", message="PrintHub orders are still being sent. Close anyway?")):
            return
        self.root.destroy()
