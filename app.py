"""ORCA: starts the program (ORCA.bat runs this file).

First of all it takes ORCA's lock (already_open.py): ORCA opens only once, and a second start just brings the
running one to the front. Then it sets up the window icon and the taskbar ID, checks the settings files, and
opens the main menu (mainmenu.py), which starts everything else. The old Walk-in window (a batch of files with options, the Inbox folder, receipts
and "Add to counter") was replaced on 2026-11-17 by walk-in orders (walkin_screens.py and the walkin_ modules).
"""
import already_open


def main():
    # Before any window is built and before anything is read or written: another ORCA open? Show it, and stop.
    if not already_open.acquire():
        already_open.second_start()
        return
    import tkinter as tk
    from tkinter import messagebox

    import jobs
    import routing
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on scaled screens
    except Exception:
        pass
    import appicon
    appicon.set_app_id()  # its own taskbar button and icon, not Python's
    root = tk.Tk()
    appicon.apply(root)  # every window opened from here on shows icon.ico
    appicon.fix_shortcut_later()  # ORCA.lnk in the top folder gets the icon (in the background)
    try:
        rules = routing.load_rules()
        routing.load_json("prices.json")
    except Exception as e:
        root.withdraw()
        messagebox.showerror("ORCA", f"Could not read the settings files.\n\n{e}")
        return
    problems = routing.check_rules(rules)
    if problems:
        root.withdraw()
        messagebox.showerror("ORCA", "There is a problem in rules.json:\n\n" + "\n".join(problems))
        return
    import mainmenu
    root.withdraw()  # the hidden Tk root: the main menu and every screen are their own windows
    mainmenu.MainMenu(root)
    root.mainloop()
    # Let PDF work in progress finish first: pdfium crashes if Python shuts down under it.
    jobs.PDF_LOCK.acquire()


if __name__ == "__main__":
    main()
