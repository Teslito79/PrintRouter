"""A window's picture with one of its comboboxes open: the window (PrintWindow) and the combobox's own list window
(also ORCA's, PrintWindow by its handle), pasted where it shows. Never the rest of the screen."""
import ctypes

import win32gui
import win32ui
from PIL import Image


def _grab(hwnd):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    hdc = win32gui.GetWindowDC(hwnd)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, h)
    mem.SelectObject(bmp)
    ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    img = Image.frombuffer("RGB", (w, h), bmp.GetBitmapBits(True), "raw", "BGRX", 0, 1)
    win32gui.DeleteObject(bmp.GetHandle())
    mem.DeleteDC()
    src.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    return img, (left, top)


def shot(window, combo, path, pump):
    window.update()
    main = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
    combo.tk.call("ttk::combobox::Post", combo)
    pump(0.6)
    popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo)
    pid = int(combo.tk.call("winfo", "id", popdown), 0)
    pop = ctypes.windll.user32.GetParent(pid) or pid
    base, (bx, by) = _grab(main)
    lst, (lx, ly) = _grab(pop)
    base.paste(lst, (lx - bx, ly - by))
    base.save(path)
    combo.tk.call("ttk::combobox::Unpost", combo)
    pump(0.2)
