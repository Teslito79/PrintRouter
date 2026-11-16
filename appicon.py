"""PrintRouter's icon (version A, orange; Tesla, 2026-11-16) on every window, the taskbar and the shortcut.

- set_app_id(): before the first window, so Windows groups PrintRouter under its own taskbar button
  with its own icon, not Python's.
- apply(root): icon.ico as the default icon of the root and of every window opened after it.
- window(win): the taskbar's relaunch details on one window (command, name, icon), so a pinned
  PrintRouter keeps the icon and starts PrintRouter.bat. Called by theme.dark_title_bar, which every
  PrintRouter window calls.
- fix_shortcut(): PrintRouter.lnk in the top folder gets the icon (only the icon, only once).
Nothing here may stop PrintRouter from starting: every step gives up quietly.
"""
import ctypes
import threading

import routing

APP_ID = "PrintRouter.App"
ICON = "icon.ico"
SHORTCUT = "PrintRouter.lnk"  # in the folder above ADMIN


def icon_path():
    path = routing.app_dir() / ICON
    return path if path.is_file() else None


def set_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def apply(root):
    path = icon_path()
    if path is None:
        return
    try:
        root.iconbitmap(default=str(path))
    except Exception:
        pass  # the default (feather) icon stays


def window(win):
    """Relaunch details for the taskbar on this window (used when PrintRouter is pinned)."""
    path = icon_path()
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
        bat = routing.app_dir() / "PrintRouter.bat"
        values = [(pscon.PKEY_AppUserModel_ID, APP_ID),
                  (pscon.PKEY_AppUserModel_RelaunchCommand, f'"{bat}"'),
                  (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "PrintRouter")]
        if path is not None:
            values.append((pscon.PKEY_AppUserModel_RelaunchIconResource, f"{path},0"))
        for key, value in values:
            store.SetValue(key, propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
        store.Commit()
    except Exception:
        pass


def fix_shortcut(top=None):
    """PrintRouter.lnk next to ADMIN shows icon.ico. Keeps the target and start folder as they are."""
    try:
        path = icon_path()
        link = (top or routing.app_dir().parent) / SHORTCUT
        if path is None or not link.is_file():
            return False
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        shell = shortcut = None
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(link))
            if str(path).lower() in str(shortcut.IconLocation).lower():
                return False  # already set
            shortcut.IconLocation = f"{path},0"
            shortcut.Save()
            return True
        finally:
            shell = shortcut = None  # let COM go before it is shut down
            pythoncom.CoUninitialize()
    except Exception:
        return False


def fix_shortcut_later():
    threading.Thread(target=fix_shortcut, daemon=True).start()
