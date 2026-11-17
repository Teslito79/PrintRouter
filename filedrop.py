"""Files dragged from Explorer (or a USB stick, or a saved email attachment) onto an ORCA window (2026-11-17).

Windows' own drag and drop, no new package: DragAcceptFiles on the Tk window and its WM_DROPFILES message, caught
by putting a small window procedure in front of Tk's (ctypes). The drop point picks the widget under it; the
nearest widget marked with target() gets the list of paths. The message only notes the drop: the handler runs a
moment later from Tk's own loop, never inside the window procedure.
"""
import ctypes
from ctypes import wintypes

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

try:
    _user32 = ctypes.windll.user32
    _shell32 = ctypes.windll.shell32
    _user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    _user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_void_p)
    _user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    _user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.CallWindowProcW.restype = LRESULT
    _user32.CallWindowProcW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                        wintypes.LPARAM)
    _user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    _shell32.DragAcceptFiles.argtypes = (wintypes.HWND, wintypes.BOOL)
    _shell32.DragQueryFileW.restype = wintypes.UINT
    _shell32.DragQueryFileW.argtypes = (ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT)
    _shell32.DragQueryPoint.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.POINT))
    _shell32.DragFinish.argtypes = (ctypes.c_void_p,)
except (AttributeError, OSError):  # not Windows
    _user32 = _shell32 = None

_windows = {}  # hwnd -> (Tk's window procedure, ours, the Tk window, the drops waiting)


def target(widget, on_drop):
    """Mark a widget as a drop area: on_drop(paths, x, y) with the screen point of the drop."""
    widget._orca_drop = on_drop
    return widget


def enable(window):
    """Let this Tk window (Toplevel) take files dropped on it. False when Windows refused."""
    if _user32 is None:
        return False
    try:
        window.update_idletasks()
        hwnd = int(window.wm_frame(), 16)
    except Exception:
        return False
    if hwnd in _windows:
        return True
    drops = []
    tk_proc = [None]

    def proc(h, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                drops.append(_read(h, wparam))
            except Exception:
                pass
            return 0
        return _user32.CallWindowProcW(tk_proc[0], h, msg, wparam, lparam)

    ours = WNDPROC(proc)
    tk_proc[0] = _user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
    if not tk_proc[0] or not _user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(ours, ctypes.c_void_p)):
        return False
    _windows[hwnd] = (tk_proc[0], ours, window, drops)  # ours must stay alive as long as the window
    _shell32.DragAcceptFiles(hwnd, True)

    def poll():
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        while drops:
            paths, x, y = drops.pop(0)
            deliver(window, paths, x, y)
        window.after(120, poll)

    window.after(120, poll)
    return True


def _read(hwnd, hdrop):
    """(paths, screen x, screen y) of a drop; the drop handle is freed."""
    try:
        count = _shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths = []
        for i in range(count):
            n = _shell32.DragQueryFileW(hdrop, i, None, 0)
            buf = ctypes.create_unicode_buffer(n + 1)
            _shell32.DragQueryFileW(hdrop, i, buf, n + 1)
            paths.append(buf.value)
        pt = wintypes.POINT()
        _shell32.DragQueryPoint(hdrop, ctypes.byref(pt))
        _user32.ClientToScreen(hwnd, ctypes.byref(pt))
        return paths, pt.x, pt.y
    finally:
        _shell32.DragFinish(hdrop)


def widget_at(window, x, y):
    """The innermost shown widget of this window under the screen point, found from the window's own layout
    (each level only where its parent shows, so a list scrolled out of sight never takes a drop)."""
    def inside(w):
        try:
            return (w.winfo_ismapped() and w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width()
                    and w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height())
        except Exception:
            return False

    if not inside(window):
        return None
    w = window
    while True:
        under = [c for c in w.winfo_children() if not hasattr(c, "wm_frame") and inside(c)]  # not other windows
        if not under:
            return w
        w = under[-1]  # the one drawn last is on top


def deliver(window, paths, x, y):
    """Hand a drop to the nearest drop area under the point (nothing happens elsewhere in the window)."""
    w = widget_at(window, x, y)
    while w is not None:
        handler = getattr(w, "_orca_drop", None)
        if handler is not None:
            handler(list(paths), x, y)
            return True
        w = w.master
    return False
