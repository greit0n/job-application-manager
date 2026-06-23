"""ReportLab renderer for the Motivationsschreiben (cover-letter) PDF.

Pure module: standard library + reportlab only. No FastAPI, DB, or network.

Public API:
    register_fonts() -> tuple[str, str]
    sanitize(text: str) -> str
    render_letter_pdf(*, sender, subject, body, date_str, language="de") -> bytes
"""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

# Names under which the DejaVu fonts are (or fall back to being) registered.
_REGULAR_NAME = "DejaVuSans"
_BOLD_NAME = "DejaVuSans-Bold"

# Module-level cache so register_fonts() is cheaply idempotent.
_REGISTERED: tuple[str, str] | None = None


def _try_register(name: str, path: str) -> bool:
    """Register a TTF under ``name`` if not already present. Returns success."""
    if name in pdfmetrics.getRegisteredFontNames():
        return True
    try:
        pdfmetrics.registerFont(TTFont(name, path))
        return True
    except Exception:
        return False


def _matplotlib_font(filename: str) -> str | None:
    """Return a path to a bundled matplotlib copy of ``filename`` if importable."""
    try:
        import matplotlib  # type: ignore
    except Exception:
        return None
    try:
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / filename
        if base.is_file():
            return str(base)
    except Exception:
        return None
    return None


def register_fonts() -> tuple[str, str]:
    """Register DejaVu Sans with reportlab; return (regular_name, bold_name).

    Idempotent. Loads the vendored TTFs from ``app/assets/fonts/``; if missing,
    falls back to matplotlib's bundled copy, else to reportlab's built-in
    Helvetica / Helvetica-Bold.
    """
    global _REGISTERED
    if _REGISTERED is not None:
        return _REGISTERED

    fonts_dir = Path(__file__).resolve().parents[1] / "assets" / "fonts"

    # Regular face.
    regular = _REGULAR_NAME
    reg_path = fonts_dir / "DejaVuSans.ttf"
    if reg_path.is_file() and _try_register(_REGULAR_NAME, str(reg_path)):
        regular = _REGULAR_NAME
    else:
        mpl = _matplotlib_font("DejaVuSans.ttf")
        if mpl and _try_register(_REGULAR_NAME, mpl):
            regular = _REGULAR_NAME
        else:
            regular = "Helvetica"

    # Bold face.
    bold = _BOLD_NAME
    bold_path = fonts_dir / "DejaVuSans-Bold.ttf"
    if bold_path.is_file() and _try_register(_BOLD_NAME, str(bold_path)):
        bold = _BOLD_NAME
    else:
        mpl = _matplotlib_font("DejaVuSans-Bold.ttf")
        if mpl and _try_register(_BOLD_NAME, mpl):
            bold = _BOLD_NAME
        else:
            bold = "Helvetica-Bold"

    _REGISTERED = (regular, bold)
    return _REGISTERED


def sanitize(text: str) -> str:
    """Replace em dash, en dash and '--' with a single hyphen; normalize newlines."""
    if not text:
        return ""
    # Normalize Windows / classic-Mac newlines first.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Em dash (U+2014), en dash (U+2013), horizontal bar (U+2015), and double hyphen.
    text = text.replace("—", "-").replace("–", "-").replace("―", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _escape(text: str) -> str:
    """Escape XML-special chars so reportlab Paragraph renders them literally."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _prep(text: str) -> str:
    """sanitize + XML-escape a single line/value for a Paragraph."""
    return _escape(sanitize(text))


def render_letter_pdf(
    *,
    sender: dict,
    subject: str,
    body: str,
    date_str: str,
    language: str = "de",
) -> bytes:
    """Render an A4 Motivationsschreiben to PDF bytes."""
    regular, bold = register_fonts()

    base = ParagraphStyle(
        "Body",
        fontName=regular,
        fontSize=10.5,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=0,
    )
    sender_name_style = ParagraphStyle(
        "SenderName", parent=base, fontName=bold
    )
    sender_line_style = ParagraphStyle("SenderLine", parent=base)
    date_style = ParagraphStyle("Date", parent=base, alignment=TA_LEFT)
    subject_style = ParagraphStyle(
        "Subject", parent=base, fontName=bold, spaceBefore=0, spaceAfter=0
    )
    para_style = ParagraphStyle("Para", parent=base, spaceAfter=10)

    # Right-align the date by using a fully right-aligned paragraph.
    from reportlab.lib.enums import TA_RIGHT

    date_style.alignment = TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2.3 * cm,
        rightMargin=2.3 * cm,
        topMargin=2.3 * cm,
        bottomMargin=2.3 * cm,
        title=sanitize(subject) or "Motivationsschreiben",
    )

    flow: list = []

    sender = sender or {}
    name = sender.get("name") or ""
    address = sender.get("address") or ""
    phone = sender.get("phone") or ""
    email = sender.get("email") or ""

    # Sender block (skip empty lines).
    if name.strip():
        flow.append(Paragraph(_prep(name), sender_name_style))
    if address.strip():
        # Address may itself contain newlines -> one paragraph line per line.
        for line in sanitize(address).split("\n"):
            if line.strip():
                flow.append(Paragraph(_escape(line), sender_line_style))
    if phone.strip():
        flow.append(Paragraph("Tel.: " + _prep(phone), sender_line_style))
    if email.strip():
        flow.append(Paragraph(_prep(email), sender_line_style))

    # Date, right-aligned.
    flow.append(Spacer(1, 0.8 * cm))
    if date_str and date_str.strip():
        flow.append(Paragraph(_prep(date_str), date_style))

    # Subject (Betreff), bold.
    flow.append(Spacer(1, 0.8 * cm))
    if subject and subject.strip():
        flow.append(Paragraph(_prep(subject), subject_style))

    flow.append(Spacer(1, 0.6 * cm))

    # Body: split into paragraphs on blank lines.
    clean_body = sanitize(body or "")
    paragraphs = [p for p in clean_body.split("\n\n")]
    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            flow.append(Spacer(1, 0.3 * cm))
            continue
        # Preserve intentional single line breaks within a paragraph.
        lines = [_escape(ln) for ln in para.split("\n")]
        flow.append(Paragraph("<br/>".join(lines), para_style))

    doc.build(flow)
    return buf.getvalue()
