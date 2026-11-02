"""Turn any supported file into a PDF.

Images: Pillow, fitted to the paper size with the page turned to match the
picture (landscape picture -> landscape page).
Word / Excel / PowerPoint: Microsoft Office, driven through pywin32.
"""
import shutil
from pathlib import Path

from PIL import Image, ImageOps

from layout import PAPER_MM

IMAGE_EXT = {".png", ".jpg", ".jpeg"}
WORD_EXT = {".doc", ".docx"}
EXCEL_EXT = {".xls", ".xlsx"}
POWERPOINT_EXT = {".ppt", ".pptx"}
SUPPORTED_EXT = {".pdf"} | IMAGE_EXT | WORD_EXT | EXCEL_EXT | POWERPOINT_EXT

IMAGE_DPI = 300
# Opening a password-protected file with a wrong password makes Office fail
# straight away instead of showing a password box nobody can answer.
NO_PASSWORD = "__no_password__"


class ConversionError(Exception):
    pass


def needs_paper(path):
    """True if the PDF depends on the chosen paper size (images do, other files don't)."""
    return Path(path).suffix.lower() in IMAGE_EXT


def to_pdf(src, out_pdf, paper):
    src, out_pdf = Path(src).resolve(), Path(out_pdf).resolve()
    ext = src.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise ConversionError(f"File type {ext or '(none)'} is not supported.")
    try:
        if ext == ".pdf":
            shutil.copyfile(src, out_pdf)
        elif ext in IMAGE_EXT:
            image_to_pdf(src, out_pdf, paper)
        else:
            office_to_pdf(src, out_pdf)
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"Could not convert {src.name}: {e}") from e
    if not out_pdf.is_file():
        raise ConversionError(f"Could not convert {src.name}: no PDF was produced.")


def image_to_pdf(src, out_pdf, paper):
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)  # respect the camera's rotation flag
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, "white")
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")

    w_mm, h_mm = PAPER_MM[paper]
    if img.width > img.height:
        w_mm, h_mm = h_mm, w_mm
    page_w = round(w_mm / 25.4 * IMAGE_DPI)
    page_h = round(h_mm / 25.4 * IMAGE_DPI)
    scale = min(page_w / img.width, page_h / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(size, Image.LANCZOS)

    page = Image.new("RGB", (page_w, page_h), "white")
    page.paste(img, ((page_w - size[0]) // 2, (page_h - size[1]) // 2))
    page.save(out_pdf, "PDF", resolution=IMAGE_DPI, quality=92)


def office_to_pdf(src, out_pdf):
    import pythoncom

    pythoncom.CoInitialize()  # needed because this runs in a worker thread
    try:
        ext = src.suffix.lower()
        if ext in WORD_EXT:
            _word(src, out_pdf)
        elif ext in EXCEL_EXT:
            _excel(src, out_pdf)
        else:
            _powerpoint(src, out_pdf)
    finally:
        pythoncom.CoUninitialize()


def _word(src, out_pdf):
    import win32com.client

    app = win32com.client.DispatchEx("Word.Application")  # own Word process, safe to quit
    try:
        app.Visible = False
        app.DisplayAlerts = 0
        doc = app.Documents.Open(str(src), ConfirmConversions=False, ReadOnly=True,
                                 AddToRecentFiles=False, PasswordDocument=NO_PASSWORD, Visible=False)
        try:
            doc.ExportAsFixedFormat(str(out_pdf), 17)  # 17 = PDF
        finally:
            doc.Close(0)
    finally:
        app.Quit(0)


def _excel(src, out_pdf):
    import win32com.client

    app = win32com.client.DispatchEx("Excel.Application")  # own Excel process, safe to quit
    try:
        app.Visible = False
        app.DisplayAlerts = False
        wb = app.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True,
                                Password=NO_PASSWORD, AddToMru=False)
        try:
            wb.ExportAsFixedFormat(0, str(out_pdf))  # 0 = PDF, all sheets
        finally:
            wb.Close(False)
    finally:
        app.Quit()


def _powerpoint(src, out_pdf):
    import win32com.client

    # PowerPoint only ever runs once; if staff already have presentations
    # open, leave it running when we're done.
    app = win32com.client.DispatchEx("PowerPoint.Application")
    was_in_use = app.Presentations.Count > 0
    try:
        pres = app.Presentations.Open(str(src), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            pres.SaveAs(str(out_pdf), 32)  # 32 = PDF
        finally:
            pres.Close()
    finally:
        if not was_in_use:
            app.Quit()
