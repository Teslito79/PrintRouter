"""Look inside a PDF: page count and how much of it is color pictures.

Color coverage = share of the page covered by clearly colored pixels, measured
on a small low-resolution rendering. Black text, grey scans and white space
don't count; photos, colored areas and colorful graphics do. A few colored
headings or a logo stay low; a page of photos goes high.
"""
from PIL import ImageChops
import pypdfium2 as pdfium

RENDER_DPI = 36
MAX_PAGES_SAMPLED = 30
SATURATION_MIN = 64  # 0-255: below this a pixel counts as grey
BRIGHTNESS_MIN = 40  # 0-255: below this a pixel counts as black


def page_count(pdf_path):
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def _page_coverage(page):
    img = page.render(scale=RENDER_DPI / 72).to_pil().convert("RGB")
    _, s, v = img.convert("HSV").split()
    colored = ImageChops.multiply(
        s.point(lambda x: 255 if x >= SATURATION_MIN else 0),
        v.point(lambda x: 255 if x >= BRIGHTNESS_MIN else 0),
    )
    return colored.histogram()[255] / (img.width * img.height)


COLOR_PAGE_MIN = 0.0001  # a page with at least this share of colored pixels prints in color


def color_pages(pdf_path):
    """For every page, whether it has any color (True) or is black & white only (False)."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        result = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                result.append(_page_coverage(page) >= COLOR_PAGE_MIN)
            finally:
                page.close()
        return result
    finally:
        pdf.close()


def color_coverage(pdf_path):
    """Average color coverage of the pages, in percent (evenly sampled for long files)."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        n = len(pdf)
        if n == 0:
            return 0.0
        step = max(1, n / MAX_PAGES_SAMPLED)
        indexes = sorted({int(i * step) for i in range(min(n, MAX_PAGES_SAMPLED))})
        values = []
        for i in indexes:
            page = pdf[i]
            try:
                values.append(_page_coverage(page))
            finally:
                page.close()
        return 100 * sum(values) / len(values)
    finally:
        pdf.close()
