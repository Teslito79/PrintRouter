"""Print PDFs through the Windows printer driver with per-job driver settings.

Ricoh-specific settings such as paper type are private to the driver, so they
can't be set through the standard Windows print settings (which is all
SumatraPDF can do). Instead:

1. Read the driver's list of settings and options ("print capabilities").
2. Write a small print ticket naming the options we want (e.g. paper type
   Thick 4) and let Windows convert it into the driver's own settings block
   (a DEVMODE). This applies to this one job only; nothing is saved.
3. Put the standard settings (paper size, color, duplex, copies) into that
   block, then draw each PDF page onto the printer with pdfium.
"""
import ctypes
import functools
import re
import threading
import xml.etree.ElementTree as ET
from ctypes import wintypes

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

PSF = "http://schemas.microsoft.com/windows/2003/08/printing/printschemaframework"
PSK = "http://schemas.microsoft.com/windows/2003/08/printing/printschemakeywords"

prntvpt = ctypes.WinDLL("prntvpt.dll")
ole32 = ctypes.WinDLL("ole32.dll")
oleaut32 = ctypes.WinDLL("oleaut32.dll")
winspool = ctypes.WinDLL("winspool.drv")
gdi32 = ctypes.WinDLL("gdi32.dll")

HRESULT = ctypes.c_long
ole32.CreateStreamOnHGlobal.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.POINTER(ctypes.c_void_p)]
ole32.CreateStreamOnHGlobal.restype = HRESULT
ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
prntvpt.PTOpenProvider.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
prntvpt.PTOpenProvider.restype = HRESULT
prntvpt.PTCloseProvider.argtypes = [ctypes.c_void_p]
prntvpt.PTGetPrintCapabilities.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.POINTER(ctypes.c_void_p)]
prntvpt.PTGetPrintCapabilities.restype = HRESULT
prntvpt.PTConvertPrintTicketToDevMode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                                  ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(ctypes.c_void_p),
                                                  ctypes.POINTER(ctypes.c_void_p)]
prntvpt.PTConvertPrintTicketToDevMode.restype = HRESULT
prntvpt.PTConvertDevModeToPrintTicket.argtypes = [ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, ctypes.c_int,
                                                  ctypes.c_void_p]
prntvpt.PTConvertDevModeToPrintTicket.restype = HRESULT
prntvpt.PTReleaseMemory.argtypes = [ctypes.c_void_p]
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
winspool.OpenPrinterW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
winspool.DocumentPropertiesW.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_void_p,
                                         ctypes.c_void_p, wintypes.DWORD]
winspool.DocumentPropertiesW.restype = ctypes.c_long
gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
for _f in ("StartPage", "EndPage", "EndDoc", "AbortDoc"):
    getattr(gdi32, _f).argtypes = [wintypes.HDC]


class DOCINFOW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_int), ("lpszDocName", wintypes.LPCWSTR), ("lpszOutput", wintypes.LPCWSTR),
                ("lpszDatatype", wintypes.LPCWSTR), ("fwType", wintypes.DWORD)]


gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
gdi32.ResetDCW.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.ResetDCW.restype = wintypes.HDC

K_USER_DEFAULT_DEVMODE = 0
K_PT_JOB_SCOPE = 2
DM_OUT_BUFFER, DM_IN_BUFFER = 2, 8

# Offsets of the standard fields in a DEVMODEW.
_FIELDS, _ORIENTATION, _PAPERSIZE, _COPIES, _COLOR, _DUPLEX, _COLLATE = 72, 76, 78, 86, 92, 94, 100
DM_ORIENTATION, DM_PAPERSIZE, DM_COPIES, DM_COLOR, DM_DUPLEX, DM_COLLATE = 0x1, 0x2, 0x100, 0x800, 0x1000, 0x8000
DMPAPER = {"A3": 8, "A4": 9, "A5": 11}

# GetDeviceCaps indexes
HORZRES, VERTRES = 8, 10
LOGPIXELSX, LOGPIXELSY = 88, 90
PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY = 110, 111, 112, 113

FPDF_ANNOT, FPDF_PRINTING = 0x01, 0x800


class DriverError(Exception):
    pass


def _check(hr, what, err=None):
    if hr < 0:
        msg = ""
        if err is not None and err.value:
            msg = ": " + ctypes.wstring_at(err.value)
            oleaut32.SysFreeString(err.value)
        raise DriverError(f"{what} failed (0x{hr & 0xFFFFFFFF:08X}){msg}")


# ---------------------------------------------------------------- IStream

def _vcall(obj, index, restype, argtypes, *args):
    vtable = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
    return fn(obj, *args)


class _Stream:
    """A memory IStream, used to pass XML to and from the print ticket API."""

    def __init__(self, data=b""):
        self.ptr = ctypes.c_void_p()
        _check(ole32.CreateStreamOnHGlobal(None, True, ctypes.byref(self.ptr)), "CreateStreamOnHGlobal")
        if data:
            written = wintypes.ULONG()
            _vcall(self.ptr, 4, HRESULT, [ctypes.c_char_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)],
                   data, len(data), ctypes.byref(written))
            self.rewind()

    def rewind(self):
        _vcall(self.ptr, 5, HRESULT, [ctypes.c_longlong, wintypes.DWORD, ctypes.c_void_p], 0, 0, None)

    def read_all(self):
        end = ctypes.c_ulonglong()
        _vcall(self.ptr, 5, HRESULT, [ctypes.c_longlong, wintypes.DWORD, ctypes.POINTER(ctypes.c_ulonglong)],
               0, 2, ctypes.byref(end))
        self.rewind()
        buf = ctypes.create_string_buffer(end.value)
        got = wintypes.ULONG()
        _vcall(self.ptr, 3, HRESULT, [ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)],
               buf, end.value, ctypes.byref(got))
        return buf.raw[:got.value]

    def close(self):
        if self.ptr:
            _vcall(self.ptr, 2, wintypes.ULONG, [])
            self.ptr = ctypes.c_void_p()


class _Provider:
    def __init__(self, printer):
        ole32.CoInitializeEx(None, 2)  # apartment-threaded; harmless if already done
        self.h = ctypes.c_void_p()
        _check(prntvpt.PTOpenProvider(printer, 1, ctypes.byref(self.h)), f"Opening {printer}")

    def __enter__(self):
        return self.h

    def __exit__(self, *exc):
        prntvpt.PTCloseProvider(self.h)


# ----------------------------------------------------------- capabilities

_caps_cache = {}
_caps_lock = threading.Lock()


def capabilities(printer):
    """The driver's settings: {feature name: {option display name: option name}}, plus XML namespaces."""
    with _caps_lock:
        if printer in _caps_cache:
            return _caps_cache[printer]
    with _Provider(printer) as h:
        out, err = _Stream(), ctypes.c_void_p()
        try:
            _check(prntvpt.PTGetPrintCapabilities(h, None, out.ptr, ctypes.byref(err)),
                   f"Reading settings of {printer}", err)
            xml = out.read_all()
        finally:
            out.close()
    text = xml.decode("utf-8", errors="replace")
    namespaces = dict(re.findall(r'xmlns:(\w+)="([^"]+)"', text))
    root = ET.fromstring(xml)
    features = {}
    for feature in root.findall(f"{{{PSF}}}Feature"):
        options = {}
        for option in feature.findall(f"{{{PSF}}}Option"):
            name = option.get("name")
            if not name:
                continue
            display = None
            for prop in option.findall(f"{{{PSF}}}Property"):
                if prop.get("name", "").endswith("DisplayName"):
                    value = prop.find(f"{{{PSF}}}Value")
                    display = value.text if value is not None else None
            options[display or name.split(":")[-1]] = name
        features[feature.get("name").split(":")[-1]] = options
    result = {"features": features, "namespaces": namespaces}
    with _caps_lock:
        _caps_cache[printer] = result
    return result


def option_names(printer, feature):
    """Display names of a feature's options, e.g. option_names(p, 'PageMediaType')."""
    return list(capabilities(printer)["features"].get(feature, {}))


# --------------------------------------------------------------- DEVMODE

def _ticket(caps, choices):
    """A print ticket selecting {feature: option display name}."""
    ns = caps["namespaces"]
    decls = " ".join(f'xmlns:{p}="{u}"' for p, u in ns.items())
    parts = []
    for feature, display in choices.items():
        options = caps["features"].get(feature)
        if options is None or display not in options:
            raise DriverError(f"The printer doesn't offer {feature} = {display}")
        parts.append(f'<psf:Feature name="psk:{feature}"><psf:Option name="{options[display]}"/></psf:Feature>')
    return f'<?xml version="1.0" encoding="UTF-8"?><psf:PrintTicket {decls} version="1">{"".join(parts)}</psf:PrintTicket>'


def _set_short(buf, offset, value):
    ctypes.c_short.from_buffer(buf, offset).value = value


def _merge(printer, buf):
    """Let the driver validate a DEVMODE and sync its private part with the standard fields."""
    hp = wintypes.HANDLE()
    if not winspool.OpenPrinterW(printer, ctypes.byref(hp), None):
        raise DriverError(f"Could not open {printer}")
    try:
        size = winspool.DocumentPropertiesW(None, hp, printer, None, None, 0)
        if size <= 0:
            raise DriverError(f"Could not read the settings of {printer}")
        out = (ctypes.c_char * max(size, len(buf)))()
        inp = (ctypes.c_char * len(buf)).from_buffer(buf)
        if winspool.DocumentPropertiesW(None, hp, printer, out, inp, DM_IN_BUFFER | DM_OUT_BUFFER) < 0:
            raise DriverError(f"{printer} did not accept the settings")
        return bytearray(out.raw[:size])
    finally:
        winspool.ClosePrinter(hp)


def build_devmode(printer, paper, color, duplex, copies, media_type=None, tray=None, short_edge=False):
    """Driver settings for one job. media_type / tray are option display names, e.g. 'Thick 4(257 to 300 g/m2)'.

    Double-sided flips on the long edge of the (portrait) paper, or on the short edge.
    """
    caps = capabilities(printer)
    choices = {}
    if media_type:
        choices["PageMediaType"] = media_type
    if tray:
        choices["JobInputBin"] = tray
    with _Provider(printer) as h:
        ticket = _Stream(_ticket(caps, choices).encode("utf-8"))
        size, dm, err = wintypes.ULONG(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            _check(prntvpt.PTConvertPrintTicketToDevMode(h, ticket.ptr, K_USER_DEFAULT_DEVMODE, K_PT_JOB_SCOPE,
                                                         ctypes.byref(size), ctypes.byref(dm), ctypes.byref(err)),
                   f"Preparing settings for {printer}", err)
            buf = bytearray(ctypes.string_at(dm, size.value))
        finally:
            ticket.close()
            if dm:
                prntvpt.PTReleaseMemory(dm)

    fields = ctypes.c_uint32.from_buffer(buf, _FIELDS)
    fields.value |= DM_ORIENTATION | DM_PAPERSIZE | DM_COPIES | DM_COLOR | DM_DUPLEX | DM_COLLATE
    _set_short(buf, _ORIENTATION, 1)  # portrait; landscape pages are turned when drawn
    _set_short(buf, _PAPERSIZE, DMPAPER[paper])
    _set_short(buf, _COPIES, copies)
    _set_short(buf, _COLOR, 2 if color else 1)
    _set_short(buf, _DUPLEX, (3 if short_edge else 2) if duplex else 1)  # 2 = long edge, 3 = short edge
    _set_short(buf, _COLLATE, 1)
    del fields  # release the buffer view before resizing
    return _merge(printer, buf)


def describe_devmode(printer, buf):
    """What the driver will actually do with these settings: {feature: option name}. For checking."""
    with _Provider(printer) as h:
        out = _Stream()
        try:
            raw = (ctypes.c_char * len(buf)).from_buffer(buf)
            _check(prntvpt.PTConvertDevModeToPrintTicket(h, len(buf), raw, K_PT_JOB_SCOPE, out.ptr),
                   f"Reading back settings for {printer}")
            xml = out.read_all()
        finally:
            out.close()
    root = ET.fromstring(xml)
    result = {}
    for feature in root.iter(f"{{{PSF}}}Feature"):
        option = feature.find(f"{{{PSF}}}Option")
        if option is not None and option.get("name"):
            result[feature.get("name").split(":")[-1]] = option.get("name").split(":")[-1]
    return result


@functools.lru_cache(maxsize=512)
def refused_settings(printer, paper, color, duplex, media_type, tray):
    """Settings the driver would quietly change for this combination, e.g. ['double-sided'].

    Drivers drop settings that can't go together (a printer may not print
    double-sided on its thickest paper) without saying so; this finds out first.
    """
    caps = capabilities(printer)["features"]
    dm = build_devmode(printer, paper, color, duplex, 1, media_type, tray)
    got = describe_devmode(printer, dm)

    def short(name):
        return name.split(":")[-1] if name else None

    refused = []
    if duplex and got.get("JobDuplexAllDocumentsContiguously") == "OneSided":
        refused.append("double-sided")
    if (got.get("PageOutputColor") == "Monochrome") == color:
        refused.append("color" if color else "black & white")
    if media_type and got.get("PageMediaType") != short(caps["PageMediaType"].get(media_type)):
        refused.append(media_type.split("(")[0].strip())
    if tray and got.get("JobInputBin") != short(caps["JobInputBin"].get(tray)):
        refused.append(tray)
    if got.get("PageMediaSize") != f"ISO{paper}":
        refused.append(paper)
    return refused


# --------------------------------------------------------------- printing

def print_pdf(pdf_path, printer, devmode, doc_name, mono_devmode=None, page_color=None, copies=1,
              duplex=False, actual_size=False):
    """Draw every page of the PDF onto the printer, fitted to the printable area.

    actual_size: draw at 100 %, centred on the sheet, never scaled (PrintHub products: the owner's
    laid-out sheets with cut marks). What falls in the copier's unprintable edge is left off.

    Mixed color: pass mono_devmode and page_color (True/False per page); the
    printer is switched to black & white for the pages without color. Copies
    are then made here (devmodes with 1 copy), each starting on a new sheet.
    """
    raw = (ctypes.c_char * len(devmode)).from_buffer(devmode)
    mono_raw = (ctypes.c_char * len(mono_devmode)).from_buffer(mono_devmode) if mono_devmode else None
    hdc = gdi32.CreateDCW("WINSPOOL", printer, None, raw)
    if not hdc:
        raise DriverError(f"Could not start a print job on {printer}")
    pdf = pdfium.PdfDocument(str(pdf_path))
    started = False
    try:
        info = DOCINFOW(ctypes.sizeof(DOCINFOW), doc_name[:200], None, None, 0)
        if gdi32.StartDocW(hdc, ctypes.byref(info)) <= 0:
            raise DriverError(f"{printer} refused the print job")
        started = True
        caps = {k: gdi32.GetDeviceCaps(hdc, k) for k in
                (HORZRES, VERTRES, PHYSICALWIDTH, PHYSICALHEIGHT, PHYSICALOFFSETX, PHYSICALOFFSETY,
                 LOGPIXELSX, LOGPIXELSY)}
        pages = list(range(len(pdf)))
        if duplex and len(pages) % 2 and copies > 1:
            pages.append(None)  # blank back, so the next copy starts on a new sheet
        current = True  # the job starts in color
        for _ in range(copies):
            for i in pages:
                if mono_raw is not None:
                    color = page_color[i] if i is not None else current
                    if color != current:
                        if not gdi32.ResetDCW(hdc, raw if color else mono_raw):
                            raise DriverError(f"{printer}: could not switch between color and black & white")
                        current = color
                page = pdf[i] if i is not None else None
                try:
                    if gdi32.StartPage(hdc) <= 0:
                        raise DriverError(f"{printer}: could not start a page")
                    if page is not None:
                        _draw_page(hdc, page, caps, actual_size)
                    if gdi32.EndPage(hdc) <= 0:
                        raise DriverError(f"{printer}: could not finish a page")
                finally:
                    if page is not None:
                        page.close()
        if gdi32.EndDoc(hdc) <= 0:
            raise DriverError(f"{printer}: the job could not be completed")
        started = False
    finally:
        if started:
            gdi32.AbortDoc(hdc)
        pdf.close()
        gdi32.DeleteDC(hdc)


def _draw_page(hdc, page, caps, actual_size=False):
    pw, ph = page.get_size()  # points, already including the page's own rotation
    area_w, area_h = caps[HORZRES], caps[VERTRES]
    paper_portrait = caps[PHYSICALWIDTH] <= caps[PHYSICALHEIGHT]
    turn = (pw > ph) == paper_portrait and pw != ph  # landscape page on portrait paper (or the reverse)
    if turn:
        pw, ph = ph, pw
    if actual_size:
        # 1 point = 1/72 inch on paper. Centred on the physical sheet; the printer clips its own edge.
        w, h = round(pw * caps[LOGPIXELSX] / 72), round(ph * caps[LOGPIXELSY] / 72)
        x = (caps[PHYSICALWIDTH] - w) // 2 - caps[PHYSICALOFFSETX]
        y = (caps[PHYSICALHEIGHT] - h) // 2 - caps[PHYSICALOFFSETY]
        pdfium_c.FPDF_RenderPage(ctypes.c_void_p(hdc), page.raw, x, y, w, h, 1 if turn else 0,
                                 FPDF_ANNOT | FPDF_PRINTING)
        return
    scale = min(area_w / pw, area_h / ph)  # fit, up or down
    w, h = round(pw * scale), round(ph * scale)
    # Centre on the physical sheet, but stay inside the printable area.
    x = (caps[PHYSICALWIDTH] - w) // 2 - caps[PHYSICALOFFSETX]
    y = (caps[PHYSICALHEIGHT] - h) // 2 - caps[PHYSICALOFFSETY]
    x = max(0, min(x, area_w - w))
    y = max(0, min(y, area_h - h))
    pdfium_c.FPDF_RenderPage(ctypes.c_void_p(hdc), page.raw, x, y, w, h, 1 if turn else 0,
                             FPDF_ANNOT | FPDF_PRINTING)
