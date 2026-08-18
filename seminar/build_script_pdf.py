"""
Render a Markdown file in this folder to a clean, printable PDF.

    py -m pip install reportlab

    py build_script_pdf.py                                       -> the full English presentation script
    py build_script_pdf.py DEMO_SCRIPT.md                        -> the English demo script
    py build_script_pdf.py Seminar_Topic8_NoiDung_TiengViet.md    -> the Vietnamese presentation script
    py build_script_pdf.py DEMO_SCRIPT_TiengViet.md              -> the Vietnamese demo script
    py build_script_pdf.py all                                   -> all four

Handles the subset of Markdown used in those files: headings, bold, italic,
inline code, fenced code blocks, blockquotes, bullet and numbered lists,
tables and horizontal rules. Uses Windows system fonts so Vietnamese
diacritics render correctly.
"""

import os
import re
import sys

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate,
                                    Paragraph, Preformatted, Spacer, Table,
                                    TableStyle, KeepTogether)
except ImportError as err:
    sys.exit(
        "Could not import reportlab.\n"
        "  interpreter : %s\n"
        "  real error  : %s\n\n"
        "Run:  py -m pip install reportlab\n"
        "Then: py build_script_pdf.py"
        % (sys.executable, err)
    )

HERE = os.path.dirname(os.path.abspath(__file__))

DOCS = {
    "Seminar_Topic8_Content_Script.md": (
        "Seminar Topic 8 - AI-Assisted DevOps - presentation script",
        "Seminar Topic 8  -  AI-Assisted DevOps  -  presentation script"),
    "DEMO_SCRIPT.md": (
        "Seminar Topic 8 - demo script and step-by-step explanation",
        "Topic 8  -  demo script  -  step by step"),
    "Seminar_Topic8_NoiDung_TiengViet.md": (
        "Seminar Topic 8 - AI-Assisted DevOps - noi dung tieng Viet",
        "Topic 8  -  AI-Assisted DevOps  -  kich ban tieng Viet"),
    "DEMO_SCRIPT_TiengViet.md": (
        "Seminar Topic 8 - kich ban demo - giai thich tung buoc",
        "Topic 8  -  kich ban demo  -  ban tieng Viet"),
}

INK = colors.HexColor("#15171C")
RED = colors.HexColor("#990011")
GREY = colors.HexColor("#6E727A")
FAINT = colors.HexColor("#A8ACB3")
RULE = colors.HexColor("#E4E4E6")
CODEBG = colors.HexColor("#F4F4F6")
HEADBG = colors.HexColor("#15171C")
ALTBG = colors.HexColor("#F7F7F9")


# ---------------------------------------------------------------- fonts
def _first_existing(*names):
    roots = [r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu",
             "/Library/Fonts"]
    for n in names:
        for root in roots:
            p = os.path.join(root, n)
            if os.path.exists(p):
                return p
    return None


_FACES = {
    "Body":   ("arial.ttf", "segoeui.ttf", "calibri.ttf", "DejaVuSans.ttf"),
    "BodyB":  ("arialbd.ttf", "segoeuib.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf"),
    "BodyI":  ("ariali.ttf", "segoeuii.ttf", "calibrii.ttf", "DejaVuSans-Oblique.ttf"),
    "BodyBI": ("arialbi.ttf", "segoeuiz.ttf", "calibriz.ttf", "DejaVuSans-BoldOblique.ttf"),
    "Mono":   ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"),
    "MonoB":  ("consolab.ttf", "courbd.ttf", "DejaVuSansMono-Bold.ttf"),
}

for face, candidates in _FACES.items():
    path = _first_existing(*candidates)
    if path is None:
        sys.exit("Could not find a font for '%s'. Tried: %s"
                 % (face, ", ".join(candidates)))
    pdfmetrics.registerFont(TTFont(face, path))

pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyB",
                              italic="BodyI", boldItalic="BodyBI")

# Glyphs the chosen fonts may not carry — swap for safe equivalents.
GLYPHS = {
    "\u2192": "->", "\u2190": "<-", "\u21d2": "=>",
    "\u2713": "[yes]", "\u2714": "[yes]",
    "\u2715": "[no]", "\u2717": "[no]", "\u2718": "[no]",
    "\u26a0": "!", "\ufe0f": "",
    "\u2460": "(1)", "\u2461": "(2)", "\u2462": "(3)",
    "\u22ee": "...", "\u2026": "...",
    "\u2014": " - ", "\u2013": "-",
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u00b7": "-", "\u2248": "~", "\u00d7": "x",
}


def clean(t):
    for a, b in GLYPHS.items():
        t = t.replace(a, b)
    return t


# ---------------------------------------------------------------- styles
def ps(name, **kw):
    base = dict(name=name, fontName="Body", fontSize=9.5, leading=13.5,
                textColor=INK, alignment=TA_LEFT, spaceBefore=0, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(**base)


S = {
    "h1": ps("h1", fontName="BodyB", fontSize=19, leading=23, textColor=INK,
             spaceBefore=6, spaceAfter=8),
    "h2": ps("h2", fontName="BodyB", fontSize=14.5, leading=18, textColor=RED,
             spaceBefore=16, spaceAfter=7),
    "h3": ps("h3", fontName="BodyB", fontSize=11.5, leading=15, textColor=INK,
             spaceBefore=13, spaceAfter=5),
    "h4": ps("h4", fontName="BodyB", fontSize=10, leading=13.5, textColor=GREY,
             spaceBefore=9, spaceAfter=4),
    "p": ps("p", spaceAfter=6),
    "quote": ps("quote", leftIndent=11, textColor=INK, fontSize=9.5,
                leading=14, spaceAfter=5),
    "quoteb": ps("quoteb", leftIndent=11, fontName="BodyB", fontSize=11,
                 leading=15, textColor=INK, spaceBefore=2, spaceAfter=5),
    "li": ps("li", leftIndent=13, bulletIndent=2, spaceAfter=3),
    "cell": ps("cell", fontSize=8.5, leading=11.5),
    "cellh": ps("cellh", fontName="BodyB", fontSize=8.5, leading=11.5,
                textColor=colors.white),
    "small": ps("small", fontSize=8.5, leading=11.5, textColor=GREY),
}

CODE = ParagraphStyle(name="code", fontName="Mono", fontSize=8,
                      leading=10.5, textColor=INK, leftIndent=6,
                      spaceBefore=2, spaceAfter=6)


# ---------------------------------------------------------------- inline
def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def inline(t):
    t = clean(t)
    t = esc(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+?)`",
               r'<font face="Mono" size="8.5" color="#990011">\1</font>', t)
    return t


# ---------------------------------------------------------------- parse
def build_story(src):
    with open(src, "r", encoding="utf-8") as fh:
        lines = fh.read().split("\n")

    story = []
    i = 0
    n = len(lines)

    while i < n:
        ln = lines[i]
        st = ln.strip()

        # fenced code
        if st.startswith("```"):
            i += 1
            buf = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(clean(lines[i]))
                i += 1
            i += 1
            if buf:
                tbl = Table([[Preformatted("\n".join(buf), CODE)]],
                            colWidths=[168 * mm])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 6))
            continue

        # table
        if st.startswith("|") and st.endswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                ncol = max(len(r) for r in rows)
                rows = [r + [""] * (ncol - len(r)) for r in rows]
                data = []
                for ri, r in enumerate(rows):
                    stl = S["cellh"] if ri == 0 else S["cell"]
                    data.append([Paragraph(inline(c), stl) for c in r])
                cw = [168.0 / ncol * mm] * ncol
                tbl = Table(data, colWidths=cw, repeatRows=1)
                style = [
                    ("BACKGROUND", (0, 0), (-1, 0), HEADBG),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
                ]
                for ri in range(2, len(rows), 2):
                    style.append(("BACKGROUND", (0, ri), (-1, ri), ALTBG))
                tbl.setStyle(TableStyle(style))
                story.append(tbl)
                story.append(Spacer(1, 8))
            continue

        # horizontal rule
        if re.fullmatch(r"-{3,}", st):
            story.append(Spacer(1, 4))
            r = Table([[""]], colWidths=[168 * mm], rowHeights=[0.4])
            r.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
            story.append(r)
            story.append(Spacer(1, 8))
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,4})\s+(.*)$", st)
        if m:
            lvl = len(m.group(1))
            story.append(Paragraph(inline(m.group(2)), S["h%d" % lvl]))
            i += 1
            continue

        # blockquote
        if st.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            for b in buf:
                if not b:
                    continue
                if b.startswith("##"):
                    story.append(Paragraph(inline(b.lstrip("#").strip()),
                                           S["quoteb"]))
                else:
                    story.append(Paragraph(inline(b), S["quote"]))
            story.append(Spacer(1, 3))
            continue

        # bullet
        if re.match(r"^[-*]\s+", st):
            story.append(Paragraph(inline(re.sub(r"^[-*]\s+", "", st)),
                                   S["li"], bulletText="\u2022"))
            i += 1
            continue

        # numbered
        m = re.match(r"^(\d+)\.\s+(.*)$", st)
        if m:
            story.append(Paragraph(inline(m.group(2)), S["li"],
                                   bulletText=m.group(1) + "."))
            i += 1
            continue

        # blank
        if not st:
            i += 1
            continue

        # paragraph — join soft-wrapped lines
        buf = [st]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", ">", "|", "```"))
                    or re.match(r"^[-*]\s+", nxt)
                    or re.match(r"^\d+\.\s+", nxt)
                    or re.fullmatch(r"-{3,}", nxt)):
                break
            buf.append(nxt)
            i += 1
        story.append(Paragraph(inline(" ".join(buf)), S["p"]))

    return story


# ---------------------------------------------------------------- page
def render(md_name):
    src = os.path.join(HERE, md_name)
    if not os.path.exists(src):
        print("  ! cannot find %s" % md_name)
        return
    title, footer = DOCS.get(md_name, (md_name, md_name))
    out = os.path.join(HERE, os.path.splitext(md_name)[0] + ".pdf")

    def decorate(canv, doc):
        canv.saveState()
        canv.setFont("Body", 7.5)
        canv.setFillColor(FAINT)
        canv.drawString(21 * mm, 12 * mm, footer)
        canv.setFont("Mono", 7.5)
        canv.drawRightString(A4[0] - 21 * mm, 12 * mm, "%02d" % doc.page)
        canv.restoreState()

    doc = BaseDocTemplate(
        out, pagesize=A4,
        leftMargin=21 * mm, rightMargin=21 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=title,
        author="Tran Gia Huy, Nguyen Hoang Danh, Vu Manh Quan",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="body", leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=decorate)])
    doc.build(build_story(src))
    print("Wrote %s   (%d pages)" % (os.path.basename(out), doc.page))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "Seminar_Topic8_Content_Script.md"
    if arg.lower() == "all":
        for name in DOCS:
            render(name)
    else:
        if not arg.lower().endswith(".md"):
            arg += ".md"
        render(arg)


if __name__ == "__main__":
    main()
