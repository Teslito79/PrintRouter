"""Dark theme for every PrintRouter window: colours, ttk style and dark title bars.

Always on, no switch. Windows message boxes are drawn by Windows and stay light.
"""

from tkinter import ttk

BG = "#1E1E1E"            # window and frame backgrounds
SURFACE = "#262626"       # labelframes (copier panels, Next steps, option sections)
FIELD = "#2F2F2F"         # entries, comboboxes, list rows, spinboxes
HEADING = "#333333"       # list headings
BORDER = "#454545"        # borders and separators
TEXT = "#E8E8E8"          # normal text
MUTED = "#A8A8A8"         # hints, "loading" and "done" rows
DISABLED = "#6E6E6E"      # disabled buttons and text
ERROR = "#FF6B6B"         # red rows, problems
BUTTON = "#3A3A3A"
BUTTON_HOVER = "#474747"
BUTTON_PRESSED = "#545454"
PRIMARY = "#2563EB"       # Print, Start printing orders, Layout done…
PRIMARY_HOVER = "#1D4ED8"
SELECT = "#2F4F7F"        # selected rows and selected text
WHITE = "#FFFFFF"

# Widgets inside a labelframe get a "Surface." style so their background matches it.
_ON_SURFACE = ("TFrame", "TLabel", "TRadiobutton", "TCheckbutton")


def apply(root):
    """Set up the dark ttk style once, at start. Fonts, sizes and padding are set by the caller."""
    style = ttk.Style(root)
    style.theme_use("clam")  # the Windows themes ignore most colour settings
    border = dict(bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)

    style.configure(".", background=BG, foreground=TEXT, fieldbackground=FIELD,
                    selectbackground=SELECT, selectforeground=WHITE, insertcolor=TEXT,
                    troughcolor=BG, focuscolor=BORDER, **border)
    style.map(".", foreground=[("disabled", DISABLED)], background=[("disabled", BG)])

    style.configure("TButton", background=BUTTON, foreground=TEXT, **border)
    style.map("TButton",
              background=[("disabled", BG), ("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)],
              foreground=[("disabled", DISABLED)],
              bordercolor=[("focus", "#5A5A5A")])
    style.configure("Print.TButton", background=PRIMARY, foreground=WHITE)
    style.map("Print.TButton",
              background=[("disabled", BUTTON), ("pressed", PRIMARY_HOVER), ("active", PRIMARY_HOVER)],
              foreground=[("disabled", DISABLED)])

    style.configure("Hint.TLabel", foreground=MUTED)

    style.configure("TLabelframe", background=SURFACE, **border)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT)

    for name in ("TRadiobutton", "TCheckbutton"):
        style.configure(name, indicatorbackground=FIELD, indicatorforeground=TEXT,
                        upperbordercolor=BORDER, lowerbordercolor=BORDER)
        style.map(name, background=[("active", BG)],
                  indicatorbackground=[("disabled", BG), ("pressed", BUTTON_PRESSED), ("selected", FIELD)],
                  foreground=[("disabled", DISABLED)])

    field_map = dict(fieldbackground=[("readonly", FIELD), ("disabled", BG)],
                     foreground=[("disabled", DISABLED)],
                     selectbackground=[("readonly", FIELD), ("!focus", FIELD)],
                     selectforeground=[("readonly", TEXT), ("!focus", TEXT)])
    style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, **border)
    style.map("TEntry", fieldbackground=[("disabled", BG)], foreground=[("disabled", DISABLED)])
    for name in ("TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=FIELD, background=BUTTON, foreground=TEXT,
                        arrowcolor=TEXT, **border)
        style.map(name, background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)],
                  arrowcolor=[("disabled", DISABLED)], **field_map)
    # The combobox drop-down is a plain Tk listbox.
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", WHITE)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, **border)
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", WHITE)])
    style.configure("Treeview.Heading", background=HEADING, foreground=TEXT, relief="flat", **border)
    style.map("Treeview.Heading", background=[("active", BUTTON_HOVER)])

    style.configure("TScrollbar", background=BUTTON, troughcolor=BG, arrowcolor=TEXT, **border)
    style.map("TScrollbar", background=[("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)])
    style.configure("TSeparator", background=BORDER)

    root.configure(background=BG)
    root.option_add("*Toplevel.background", BG)


def on_surface(container):
    """Give the frames, labels and radio/check buttons inside a labelframe its background.
    Call again after adding widgets to it."""
    style = ttk.Style(container)
    for w in container.winfo_children():
        cls = w.winfo_class()
        if cls in _ON_SURFACE:
            base = str(w.cget("style")) or cls
            if not base.startswith("Surface."):
                name = "Surface." + base
                style.configure(name, background=SURFACE)
                if cls in ("TRadiobutton", "TCheckbutton"):
                    style.map(name, background=[("active", SURFACE)])
                w.configure(style=name)
        on_surface(w)


def dark_title_bar(window):
    """Make a window's title bar dark (Windows 10 2004+ / 11). Does nothing if Windows refuses."""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return
        on = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(on),
                                                         ctypes.sizeof(on)) == 0:
                break
        # Redraw the frame now, not on the next focus change.
        flags = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE NOMOVE NOZORDER NOACTIVATE FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)
    except Exception:
        pass
