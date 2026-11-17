"""Send PDFs to Windows print queues through SumatraPDF.

Used for receipts. Copier jobs go through driverprint, which can also set
Ricoh-specific options such as paper type.
"""
import subprocess
import sys
from pathlib import Path

from routing import app_dir

PRINT_TIMEOUT_S = 600


class PrintError(Exception):
    pass


def sumatra_path():
    candidates = [app_dir() / "tools" / "SumatraPDF" / "SumatraPDF.exe"]
    if hasattr(sys, "_MEIPASS"):  # bundled inside the .exe
        candidates.append(Path(sys._MEIPASS) / "tools" / "SumatraPDF" / "SumatraPDF.exe")
    for p in candidates:
        if p.is_file():
            return p
    raise PrintError("SumatraPDF.exe not found in the tools\\SumatraPDF folder.")


def send(pdf, queue, settings=None):
    cmd = [str(sumatra_path()), "-print-to", queue]
    if settings:
        cmd += ["-print-settings", settings]
    cmd += ["-silent", str(pdf)]
    try:
        result = subprocess.run(cmd, timeout=PRINT_TIMEOUT_S,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise PrintError(f"Sending to {queue} took too long and was stopped.")
    if result.returncode != 0:
        raise PrintError(f"SumatraPDF could not print to {queue} (code {result.returncode}).")
