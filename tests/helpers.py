"""Shared set-up for ORCA's tests (2026-11-27_03). See README.txt for the safety rules.

dirs(__file__): a fresh temp folder for the test and one for its pictures, both under %TEMP%\\ORCA-tests\\<name>
(never in ADMIN); the real ADMIN folder is guarded: routing.app_dir() pointing at it makes the test stop.
PRICE_TEMPLATE: the walk-in price list's layout with every price empty, made from the repo's Walk-in_Prices.xlsx
(price_sheet.test_sheet fills it with the test prices).
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent
FIXTURES = TESTS / "fixtures"
COUNTER_PAGES = FIXTURES / "counter_pages"
PRICE_TEMPLATE = FIXTURES / "price_template.xlsx"
REAL_SHOPIFY_EXPORT = Path(os.path.expanduser("~")) / "Downloads" / "inventory_export_1.csv"  # read only, if there
ROOT = Path(tempfile.gettempdir()) / "ORCA-tests"

for p in (str(APP), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


def dirs(test_file):
    """(TMP, OUT): fresh folders for this test under %TEMP%\\ORCA-tests\\<name>. ORCA's code is imported from ADMIN;
    the working folder is ADMIN (read only for the tests). The guard is installed once routing is imported."""
    name = Path(test_file).stem
    base = ROOT / name
    remove_tree(base)
    tmp, out = base / "tmp", base / "out"
    tmp.mkdir(parents=True)
    out.mkdir(parents=True)
    os.chdir(APP)
    os.environ.setdefault("NO_SHOTS", "")
    atexit.register(guard_check)
    return tmp, out


def remove_tree(path):
    """Delete a temp folder, read-only files too (git makes its objects read-only)."""
    import stat

    def again(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if Path(path).exists():
        shutil.rmtree(path, onexc=again)


def guard_check():
    """At the end of every test: routing.app_dir() must not be the real ADMIN folder."""
    routing = sys.modules.get("routing")
    if routing is None:
        return
    try:
        where = Path(routing.app_dir()).resolve()
    except Exception:
        return
    if where == APP:
        print("FAIL safety: the test used the real ADMIN folder (routing.app_dir())")


def use_temp_admin(admin):
    """Point ORCA at a temp ADMIN folder (routing.app_dir) and refuse the real one."""
    import routing
    admin = Path(admin).resolve()
    if admin == APP or APP in admin.parents:
        raise SystemExit("FAIL safety: a test tried to use the real ADMIN folder")
    routing.app_dir = lambda: admin
    return admin


SHIPPED = ("rules.json", "prices.json", "icon.ico")


def temp_admin(tmp, files=SHIPPED):
    """A temp ADMIN folder with copies of the shipped files ORCA reads (rules.json, prices.json, icon.ico), and ORCA
    pointed at it. Returns its path."""
    admin = Path(tmp) / "ADMIN"
    admin.mkdir(parents=True, exist_ok=True)
    for name in files:
        if (APP / name).exists() and not (admin / name).exists():
            shutil.copyfile(APP / name, admin / name)
    return use_temp_admin(admin)


def no_printing():
    """Nothing reaches a printer: the driver path and SumatraPDF are replaced by recorders."""
    import driverprint
    import printing
    sent = []
    driverprint.print_pdf = lambda pdf, q, devmode, name, **kw: sent.append((q, name))
    printing.send = lambda pdf, queue, settings=None: sent.append((queue, str(pdf)))
    return sent


def make_price_template(path=PRICE_TEMPLATE):
    """The repo's Walk-in_Prices.xlsx (the trial sheet, every price 0) with its title "Walk-in prices" and every
    price cell, stack size and "per piece" emptied: the same as the empty sheet Tesla fills in."""
    import price_sheet as ps
    import walkin_prices as wp
    src = APP / "Walk-in_Prices.xlsx"
    values = {"Prices": {"A1": "Walk-in prices"}, "Settings": {}}
    for sheet, rows in wp.read_xlsx(src).items():
        for r, vals in rows:
            for c, v in enumerate(vals or []):
                ref = f"{ps._letter(c)}{r}"
                if v in (0, "0", 0.0) or (sheet == "Prices" and str(v).strip().lower() == "per piece") \
                        or (sheet == "Prices" and c == 1 and str(v) == "100" and _stack_row(rows, r)):
                    values.setdefault(sheet, {})[ref] = None
    ps.fill(src, path, values)
    return path


def _stack_row(rows, r):
    """A Cutting row "up to … gsm" (its sheets per stack, 100 in the trial sheet)."""
    label = next(((vals[0] or "") for rr, vals in rows if rr == r and vals), "")
    return "gsm" in str(label).lower()


if not PRICE_TEMPLATE.exists():  # made once from the repo's own sheet (committed with the tests)
    try:
        make_price_template()
    except Exception as e:  # the tests that need it say so
        print("price template not made:", e)
