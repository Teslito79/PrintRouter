"""ORCA's icon (version A, orange; Tesla, 2026-11-16) on every window, the taskbar and the shortcut.

- set_app_id(): before the first window, so Windows groups ORCA under its own taskbar button
  with its own icon, not Python's.
- apply(root): icon.ico as the default icon of the root and of every window opened after it.
- window(win): the taskbar's relaunch details on one window (command, name, icon), so a pinned
  ORCA keeps the icon and starts ORCA.bat. Called by theme.dark_title_bar, which every ORCA window calls.
- fix_shortcut(): ORCA.lnk in the top folder (and on the Desktop): an old PrintRouter.lnk becomes ORCA.lnk
  (ORCA was called PrintRouter until 2026-11-16), and ORCA.lnk gets the icon.
Nothing here may stop ORCA from starting: every step gives up quietly.
"""
import ctypes
import threading

import routing

APP_ID = "ORCA.App"
ICON = "icon.ico"
BAT = "ORCA.bat"
SHORTCUT = "ORCA.lnk"  # in the folder above ADMIN
OLD_SHORTCUT = "PrintRouter.lnk"  # the name before 2026-11-16
OLD_BAT = "PrintRouter.bat"


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
    """Relaunch details for the taskbar on this window (used when ORCA is pinned)."""
    path = icon_path()
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
        values = [(pscon.PKEY_AppUserModel_ID, APP_ID),
                  (pscon.PKEY_AppUserModel_RelaunchCommand, f'"{routing.app_dir() / BAT}"'),
                  (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "ORCA")]
        if path is not None:
            values.append((pscon.PKEY_AppUserModel_RelaunchIconResource, f"{path},0"))
        for key, value in values:
            store.SetValue(key, propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
        store.Commit()
    except Exception:
        pass


def _desktop():
    try:
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0:  # CSIDL_DESKTOPDIRECTORY
            from pathlib import Path
            return Path(buf.value)
    except Exception:
        pass
    return None


def _fix_folder(shell, folder, admin, icon, only_ours):
    """One folder: an old PrintRouter.lnk becomes ORCA.lnk (same start folder, ORCA.bat, the icon),
    then the old one is removed; an existing ORCA.lnk only gets the icon. Returns what was done."""
    done = []
    old, new = folder / OLD_SHORTCUT, folder / SHORTCUT
    if old.is_file():
        o = shell.CreateShortcut(str(old))
        target = str(o.TargetPath)
        if only_ours and not target.lower().endswith(OLD_BAT.lower()):
            return done  # a PrintRouter shortcut that isn't ours: left alone
        start_in = str(o.WorkingDirectory) or str(admin)
        o = None
        if not new.is_file():
            n = shell.CreateShortcut(str(new))
            n.TargetPath = str(admin / BAT)
            n.WorkingDirectory = start_in
            n.Description = "Open ORCA"
            if icon is not None:
                n.IconLocation = f"{icon},0"
            n.Save()
            n = None
            done.append(f"made {new}")
        if new.is_file():
            old.unlink()
            done.append(f"removed {old}")
    if new.is_file() and icon is not None:
        n = shell.CreateShortcut(str(new))
        if str(icon).lower() not in str(n.IconLocation).lower():
            n.IconLocation = f"{icon},0"
            n.Save()
            done.append(f"icon on {new}")
        n = None
    return done


def fix_shortcut(top=None, desktop=None):
    """The shortcuts: top folder (next to ADMIN) and the user's Desktop. Returns a list of what was done."""
    done = []
    try:
        import pythoncom
        import win32com.client
        admin = routing.app_dir()
        icon = icon_path()
        pythoncom.CoInitialize()
        shell = None
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            for folder, only_ours in (((top or admin.parent), False), ((desktop or _desktop()), True)):
                if folder is None:
                    continue
                try:
                    done += _fix_folder(shell, folder, admin, icon, only_ours)
                except Exception:
                    pass  # read-only folder, file in use: tried again at the next start
        finally:
            shell = None  # let COM go before it is shut down
            pythoncom.CoUninitialize()
    except Exception:
        pass
    return done


def fix_shortcut_later():
    threading.Thread(target=fix_shortcut, daemon=True).start()
